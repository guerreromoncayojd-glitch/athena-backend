import os
import asyncio
from datetime import datetime
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
 
LIGA_A_CODIGO_FD = {
    "La Liga": "PD", "Premier League": "PL", "Bundesliga": "BL1",
    "Serie A": "SA", "Ligue 1": "FL1", "Eredivisie": "DED", "Primeira Liga": "PPL",
}
LIGA_A_ID_AF = {
    "La Liga": 140, "Premier League": 39, "Bundesliga": 78,
    "Serie A": 135, "Ligue 1": 61, "Eredivisie": 88, "Primeira Liga": 94,
}
 
 
def _temporada_actual() -> int:
    hoy = datetime.now()
    return hoy.year if hoy.month >= 8 else hoy.year - 1
 
 
def _nombres_coinciden(nombre_bd: str, nombre_api: str) -> bool:
    a = nombre_bd.lower().strip()
    b = nombre_api.lower().strip()
    return a == b or a in b or b in a
 
 
@router.get("/", response_model=List[EquipoOut])
def listar_equipos(liga_id: Optional[int] = None, db: Session = Depends(get_db)):
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
 
 
def _equipos_relevantes(db: Session) -> List[Equipo]:
    ids_local = db.query(Partido.equipo_local_id).filter(Partido.jugado == False)
    ids_visitante = db.query(Partido.equipo_visitante_id).filter(Partido.jugado == False)
    ids = {row[0] for row in ids_local.union(ids_visitante).all()}
    if not ids:
        return []
    return db.query(Equipo).filter(Equipo.id.in_(ids), Equipo.activo == True).all()
 
 
async def _vincular_football_data(client: httpx.AsyncClient, equipos: List[Equipo], db: Session) -> dict:
    notas = {}
    if not FOOTBALL_DATA_TOKEN:
        return notas
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
                    notas[e.nombre] = f"liga '{liga.nombre}' no cubierta por football-data.org gratis"
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
                    (te for te in equipos_api if _nombres_coinciden(e.nombre, te.get("name", ""))), None
                )
                if encontrado:
                    e.football_data_team_id = encontrado["id"]
                else:
                    notas[e.nombre] = "sin coincidencia de nombre en football-data.org"
        except Exception as ex:
            for e in equipos_pendientes:
                if e.liga_id == liga.id:
                    notas[e.nombre] = f"error: {str(ex)}"
        await asyncio.sleep(6.5)
 
    return notas
 
 
async def _obtener_equipos_af(client: httpx.AsyncClient, liga_af_id: int, temporada: int) -> list:
    """Consulta la lista de equipos de una liga+temporada en API-Football."""
    r = await client.get(
        "https://v3.football.api-sports.io/teams",
        headers={"x-apisports-key": API_FOOTBALL_KEY},
        params={"league": liga_af_id, "season": temporada}
    )
    if r.status_code != 200:
        return None
    return r.json().get("response", [])
 
 
async def _vincular_api_football(client: httpx.AsyncClient, equipos: List[Equipo], db: Session) -> dict:
    notas = {}
    if not API_FOOTBALL_KEY:
        return notas
    equipos_pendientes = [e for e in equipos if not e.api_football_id]
    if not equipos_pendientes:
        return notas
 
    ligas_ids = {e.liga_id for e in equipos_pendientes}
    ligas = db.query(Liga).filter(Liga.id.in_(ligas_ids)).all()
    temporada_actual = _temporada_actual()
 
    for liga in ligas:
        liga_af_id = LIGA_A_ID_AF.get(liga.nombre)
        if not liga_af_id:
            for e in equipos_pendientes:
                if e.liga_id == liga.id:
                    notas[e.nombre] = f"liga '{liga.nombre}' sin ID configurado en API-Football"
            continue
 
        try:
            # Intenta con la temporada actual; si no hay equipos todavía
            # cargados para esa temporada (común antes de que arranque la
            # liga), reintenta automáticamente con la temporada anterior.
            equipos_api = await _obtener_equipos_af(client, liga_af_id, temporada_actual)
            temporada_usada = temporada_actual
            if not equipos_api:
                equipos_api = await _obtener_equipos_af(client, liga_af_id, temporada_actual - 1)
                temporada_usada = temporada_actual - 1
 
            if equipos_api is None:
                for e in equipos_pendientes:
                    if e.liga_id == liga.id:
                        notas[e.nombre] = "API-Football no respondió correctamente (revisa la clave o la cuota)"
                continue
 
            if not equipos_api:
                for e in equipos_pendientes:
                    if e.liga_id == liga.id:
                        notas[e.nombre] = f"API-Football no tiene equipos cargados para {liga.nombre} (probado {temporada_actual} y {temporada_actual - 1})"
                continue
 
            for e in equipos_pendientes:
                if e.liga_id != liga.id:
                    continue
                encontrado = next(
                    (te for te in equipos_api if _nombres_coinciden(e.nombre, te.get("team", {}).get("name", ""))),
                    None
                )
                if encontrado:
                    e.api_football_id = encontrado["team"]["id"]
                else:
                    notas[e.nombre] = f"sin coincidencia de nombre en API-Football (temporada {temporada_usada})"
        except Exception as ex:
            for e in equipos_pendientes:
                if e.liga_id == liga.id:
                    notas[e.nombre] = f"error: {str(ex)}"
 
    return notas
 
 
async def _tarea_vincular_ids_externos():
    db = SessionLocal()
    try:
        equipos = _equipos_relevantes(db)
        async with httpx.AsyncClient(timeout=20) as client:
            notas_fd = await _vincular_football_data(client, equipos, db)
            notas_af = await _vincular_api_football(client, equipos, db)
 
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
    return {"mensaje": "Proceso iniciado. Espera 20-30 segundos y consulta con GET /api/v1/equipos/vincular-ids-externos."}
 
 
@router.get("/vincular-ids-externos")
async def consultar_vinculacion_ids_externos():
    if _estado_vinculacion["en_progreso"]:
        return {"estado": "en_progreso", "mensaje": "Todavía procesando, intenta de nuevo en unos segundos."}
    if _estado_vinculacion["resultado"] is None:
        return {"estado": "sin_ejecutar", "mensaje": "Todavía no se ha ejecutado POST /vincular-ids-externos."}
    return {"estado": "completado", **_estado_vinculacion["resultado"]}
 
 
_estado_stats_reales = {"en_progreso": False, "resultado": None}
 
 
async def _tarea_actualizar_stats_reales():
    from engines.data_fetcher import actualizar_stats_reales_equipo
 
    db = SessionLocal()
    try:
        equipos = _equipos_relevantes(db)
        resultados = []
 
        async with httpx.AsyncClient(timeout=20) as client:
            for equipo in equipos:
                nota = await actualizar_stats_reales_equipo(client, equipo)
                resultados.append({
                    "equipo": equipo.nombre,
                    "actualizado": nota is None,
                    "nota": nota,
                    "partidos_jugados": equipo.partidos_jugados,
                    "xg_favor_promedio": equipo.xg_favor_promedio,
                    "xg_contra_promedio": equipo.xg_contra_promedio,
                })
                # Respetar el límite de 10 peticiones/minuto de football-data.org
                await asyncio.sleep(6.5)
 
        db.commit()
 
        _estado_stats_reales["resultado"] = {
            "total_procesados": len(resultados),
            "resultados": resultados,
        }
    finally:
        db.close()
        _estado_stats_reales["en_progreso"] = False
 
 
@router.post("/actualizar-stats-reales")
async def actualizar_stats_reales(background_tasks: BackgroundTasks):
    """
    Reemplaza las estadísticas aleatorias de los equipos (goles, xG
    proxy, forma) por datos reales calculados a partir de sus últimos
    partidos jugados en football-data.org. Corre en segundo plano
    porque puede tardar varios minutos según cuántos equipos haya.
    """
    if _estado_stats_reales["en_progreso"]:
        return {"mensaje": "Ya hay un proceso en curso, espera y consulta con GET."}
    _estado_stats_reales["en_progreso"] = True
    _estado_stats_reales["resultado"] = None
    background_tasks.add_task(_tarea_actualizar_stats_reales)
    return {"mensaje": "Proceso iniciado. Puede tardar varios minutos (1 equipo cada ~7s). Consulta con GET /api/v1/equipos/actualizar-stats-reales."}
 
 
@router.get("/actualizar-stats-reales")
async def consultar_actualizar_stats_reales():
    if _estado_stats_reales["en_progreso"]:
        return {"estado": "en_progreso", "mensaje": "Todavía procesando, intenta de nuevo en unos segundos."}
    if _estado_stats_reales["resultado"] is None:
        return {"estado": "sin_ejecutar", "mensaje": "Todavía no se ha ejecutado POST /actualizar-stats-reales."}
    return {"estado": "completado", **_estado_stats_reales["resultado"]}
 
 
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
 
