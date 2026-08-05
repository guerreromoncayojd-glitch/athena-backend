import os
import asyncio
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
 
from database.connection import get_db, SessionLocal
from database.models import Equipo, Partido
from database.schemas import EquipoCreate, EquipoOut
 
router = APIRouter()
 
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
 
_estado_vinculacion = {"en_progreso": False, "resultado": None}
 
 
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
    """
    Solo los equipos que tienen al menos un partido próximo (no jugado)
    registrado — es decir, los que realmente se usan para calcular
    pronósticos ahora mismo. Evita procesar cientos de equipos
    acumulados de sincronizaciones anteriores que no vas a usar.
    """
    ids_local = db.query(Partido.equipo_local_id).filter(Partido.jugado == False)
    ids_visitante = db.query(Partido.equipo_visitante_id).filter(Partido.jugado == False)
    ids = {row[0] for row in ids_local.union(ids_visitante).all()}
 
    if not ids:
        return []
 
    return db.query(Equipo).filter(Equipo.id.in_(ids), Equipo.activo == True).all()
 
 
async def _buscar_ids_equipo(
    client: httpx.AsyncClient, equipo: Equipo, sem_fd: asyncio.Semaphore
) -> dict:
    """Busca el ID de un equipo en ambas APIs. football-data.org se limita
    con un semáforo para respetar su límite de 10 peticiones/minuto."""
    resultado = {
        "equipo": equipo.nombre,
        "football_data_team_id": equipo.football_data_team_id,
        "api_football_id": equipo.api_football_id,
    }
 
    necesita_fd = not equipo.football_data_team_id and FOOTBALL_DATA_TOKEN
    necesita_af = not equipo.api_football_id and API_FOOTBALL_KEY
 
    if necesita_fd:
        async with sem_fd:
            try:
                r = await client.get(
                    "https://api.football-data.org/v4/teams",
                    headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN},
                    params={"name": equipo.nombre}
                )
                if r.status_code == 200:
                    candidatos = r.json().get("teams", [])
                    if candidatos:
                        equipo.football_data_team_id = candidatos[0]["id"]
                        resultado["football_data_team_id"] = candidatos[0]["id"]
                elif r.status_code == 429:
                    resultado["nota_fd"] = "límite de peticiones alcanzado, reintenta más tarde"
            except Exception:
                pass
            # Pausa breve entre peticiones a football-data.org para no
            # disparar su límite de 10/minuto aunque haya varios equipos.
            await asyncio.sleep(6.5)
 
    if necesita_af:
        try:
            r = await client.get(
                "https://v3.football.api-sports.io/teams",
                headers={"x-apisports-key": API_FOOTBALL_KEY},
                params={"search": equipo.nombre}
            )
            if r.status_code == 200:
                candidatos = r.json().get("response", [])
                if candidatos:
                    equipo.api_football_id = candidatos[0]["team"]["id"]
                    resultado["api_football_id"] = candidatos[0]["team"]["id"]
            elif r.status_code == 429:
                resultado["nota_af"] = "límite de peticiones alcanzado, reintenta más tarde"
        except Exception:
            pass
 
    return resultado
 
 
async def _tarea_vincular_ids_externos():
    db = SessionLocal()
    try:
        equipos = _equipos_relevantes(db)
 
        sem_fd = asyncio.Semaphore(1)  # una petición a football-data.org a la vez
        async with httpx.AsyncClient(timeout=20) as client:
            resultados = []
            for equipo in equipos:
                r = await _buscar_ids_equipo(client, equipo, sem_fd)
                resultados.append(r)
 
        db.commit()
 
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
    """
    Busca en segundo plano el ID de cada equipo CON PARTIDOS PRÓXIMOS
    (no toda la base de datos) en football-data.org y API-Football.
    Respeta el límite de 10 peticiones/minuto de football-data.org
    espaciando esas consultas — puede tardar más de lo que parece si
    hay varios equipos, así que consulta el resultado con GET.
    """
    if _estado_vinculacion["en_progreso"]:
        return {"mensaje": "Ya hay un proceso en curso, espera y consulta con GET."}
 
    _estado_vinculacion["en_progreso"] = True
    _estado_vinculacion["resultado"] = None
    background_tasks.add_task(_tarea_vincular_ids_externos)
 
    return {"mensaje": "Proceso iniciado. Solo se procesan equipos con partidos próximos. Espera 30-60 segundos y consulta con GET /api/v1/equipos/vincular-ids-externos."}
 
 
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
