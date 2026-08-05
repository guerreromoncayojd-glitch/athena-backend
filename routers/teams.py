import os
import asyncio
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
 
from database.connection import get_db, SessionLocal
from database.models import Equipo, Partido, Liga
from database.schemas import EquipoCreate, EquipoOut
 
router = APIRouter()
 
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
 
_estado_vinculacion = {"en_progreso": False, "resultado": None}
 
# Mapa de nombre de liga (como está en tu BD) -> código de competición
# en football-data.org. Solo incluye las ligas que su plan gratuito cubre.
LIGA_A_CODIGO_FD = {
    "La Liga": "PD",
    "Premier League": "PL",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue 1": "FL1",
    "Eredivisie": "DED",
    "Primeira Liga": "PPL",
}
 
 
def _nombres_coinciden(nombre_bd: str, nombre_api: str) -> bool:
    """
    Compara nombres de forma flexible: normaliza a minúsculas y compara
    si uno contiene al otro (para casos como "Sevilla FC" vs "Sevilla").
    """
    a = nombre_bd.lower().strip()
    b = nombre_api.lower().strip()
    return a == b or a in b or b in a
 
 
@router.get("/", response_model=List[EquipoOut])
def listar_equipos(
    liga_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Equipo).filter(Equipo.activo == True)
    if liga_id:
        query = query.filter(Equipo.liga_id == liga_id)
    return query.all()
 
 
@router.post("/", response_model=EquipoOut, status_code=201)
def crear_equipo(equipo: EquipoCreate, db: Session = Depends(get_db)):
    db_equipo = Equipo(**equipo.dict())
    db.add(db_equipo)
    db.commit()
    db.refresh(db_equipo)
    return db_equipo
 
 
# ─────────────────────────────────────────────────────────────
# IMPORTANTE: estas rutas van ANTES de "/{equipo_id}".
# ─────────────────────────────────────────────────────────────
 
def _equipos_relevantes(db: Session) -> List[Equipo]:
    """Solo equipos con al menos un partido próximo (no jugado) registrado."""
    ids_local = db.query(Partido.equipo_local_id).filter(Partido.jugado == False)
    ids_visitante = db.query(Partido.equipo_visitante_id).filter(Partido.jugado == False)
    ids = {row[0] for row in ids_local.union(ids_visitante).all()}
    if not ids:
        return []
    return db.query(Equipo).filter(Equipo.id.in_(ids), Equipo.activo == True).all()
 
 
async def _vincular_football_data(client: httpx.AsyncClient, equipos: List[Equipo], db: Session) -> dict:
    """
    Trae la lista completa de equipos por CADA competición relevante
    (una sola consulta por competición, no una por equipo) y compara
    nombres localmente. Mucho más confiable que un filtro por nombre.
    """
    notas = {}
    if not FOOTBALL_DATA_TOKEN:
        return notas
 
    # Agrupar equipos pendientes por su liga
    equipos_pendientes = [e for e in equipos if not e.football_data_team_id]
    if not equipos_pendientes:
        return notas
 
    ligas_ids = {e.liga_id for e in equipos_pendientes}
    ligas = db.query(Liga).filter(Liga.id.in_(ligas_ids)).all()
 
    for liga in ligas:
        codigo = LIGA_A_CODIGO_FD.get(liga.nombre)
        if not codigo:
            for e in equipos_pendientes:
                if e.liga_id == liga.id:
                    notas[e.nombre] = f"liga '{liga.nombre}' no cubierta por el plan gratuito de football-data.org"
            continue
 
        try:
            r = await client.get(
                f"https://api.football-data.org/v4/competitions/{codigo}/teams",
                headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN}
            )
            if r.status_code != 200:
                for e in equipos_pendientes:
                    if e.liga_id == liga.id:
                        notas[e.nombre] = f"football-data respondió {r.status_code}"
                continue
 
            equipos_api = r.json().get("teams", [])
            for e in equipos_pendientes:
                if e.liga_id != liga.id:
                    continue
                encontrado = next(
                    (te for te in equipos_api if _nombres_coinciden(e.nombre, te.get("name", ""))),
                    None
                )
                if encontrado:
                    e.football_data_team_id = encontrado["id"]
                else:
                    notas[e.nombre] = "sin coincidencia de nombre en football-data.org"
        except Exception as ex:
            for e in equipos_pendientes:
                if e.liga_id == liga.id:
                    notas[e.nombre] = f"error: {str(ex)}"
 
        # Respetar el límite de 10 peticiones/minuto de football-data.org
        await asyncio.sleep(6.5)
 
    return notas
 
 
async def _vincular_api_football(client: httpx.AsyncClient, equipos: List[Equipo]) -> dict:
    """Busca en API-Football (search por nombre), capturando el motivo si falla."""
    notas = {}
    if not API_FOOTBALL_KEY:
        return notas
 
    for e in equipos:
        if e.api_football_id:
            continue
        try:
            r = await client.get(
                "https://v3.football.api-sports.io/teams",
                headers={"x-apisports-key": API_FOOTBALL_KEY},
                params={"search": e.nombre}
            )
            if r.status_code == 200:
                candidatos = r.json().get("response", [])
                if candidatos:
                    e.api_football_id = candidatos[0]["team"]["id"]
                else:
                    notas[e.nombre] = "sin coincidencia en API-Football"
            else:
                notas[e.nombre] = f"API-Football respondió {r.status_code}"
        except Exception as ex:
            notas[e.nombre] = f"error: {str(ex)}"
 
    return notas
 
 
async def _tarea_vincular_ids_externos():
    db = SessionLocal()
    try:
        equipos = _equipos_relevantes(db)
 
        async with httpx.AsyncClient(timeout=20) as client:
            notas_fd = await _vincular_football_data(client, equipos, db)
            notas_af = await _vincular_api_football(client, equipos)
 
        db.commit()
 
        resultados = []
        for e in equipos:
            resultados.append({
                "equipo": e.nombre,
                "football_data_team_id": e.football_data_team_id,
                "api_football_id": e.api_football_id,
                "nota_football_data": notas_fd.get(e.nombre),
                "nota_api_football": notas_af.get(e.nombre),
            })
 
        sin_coincidencia_completa = [
            r["equipo"] for r in resultados
            if not r["football_data_team_id"] or not r["api_football_id"]
        ]
 
        _estado_vinculacion["resultado"] = {
            "total_procesados": len(resultados),
            "resultados": resultados,
            "sin_coincidencia_completa": sin_coincidencia_completa,
        }
    finally:
        db.close()
        _estado_vinculacion["en_progreso"] = False
 
 
@router.post("/vincular-ids-externos")
async def vincular_ids_externos(background_tasks: BackgroundTasks):
    if _estado_vinculacion["en_progreso"]:
        return {"mensaje": "Ya hay un proceso en curso, espera y consulta con GET."}
 
    _estado_vinculacion["en_progreso"] = True
    _estado_vinculacion["resultado"] = None
    background_tasks.add_task(_tarea_vincular_ids_externos)
 
    return {"mensaje": "Proceso iniciado. Espera 30-60 segundos y consulta con GET /api/v1/equipos/vincular-ids-externos."}
 
 
@router.get("/vincular-ids-externos")
async def consultar_vinculacion_ids_externos():
    if _estado_vinculacion["en_progreso"]:
        return {"estado": "en_progreso", "mensaje": "Todavía procesando, intenta de nuevo en unos segundos."}
    if _estado_vinculacion["resultado"] is None:
        return {"estado": "sin_ejecutar", "mensaje": "Todavía no se ha ejecutado POST /vincular-ids-externos."}
    return {"estado": "completado", **_estado_vinculacion["resultado"]}
 
 
# ─────────────────────────────────────────────────────────────
# Rutas con "/{equipo_id}" — SIEMPRE después de las rutas fijas.
# ─────────────────────────────────────────────────────────────
 
@router.get("/{equipo_id}", response_model=EquipoOut)
def obtener_equipo(equipo_id: int, db: Session = Depends(get_db)):
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    return equipo
 
 
@router.put("/{equipo_id}", response_model=EquipoOut)
def actualizar_equipo(equipo_id: int, datos: EquipoCreate, db: Session = Depends(get_db)):
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    for key, value in datos.dict(exclude_unset=True).items():
        setattr(equipo, key, value)
    db.commit()
    db.refresh(equipo)
    return equipo
 
 
@router.delete("/{equipo_id}", status_code=204)
def eliminar_equipo(equipo_id: int, db: Session = Depends(get_db)):
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    equipo.activo = False
    db.commit()
