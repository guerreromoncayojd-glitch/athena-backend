import os
import asyncio
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
 
from database.connection import get_db, SessionLocal
from database.models import Equipo
from database.schemas import EquipoCreate, EquipoOut
 
router = APIRouter()
 
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
 
# Estado del último proceso de vinculación (en memoria, se reinicia si el
# servicio se reinicia — suficiente para este uso puntual y manual)
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
# IMPORTANTE: estas 2 rutas van ANTES de "/{equipo_id}" — si no,
# FastAPI intenta interpretar "vincular-ids-externos" como un ID
# numérico de equipo y falla. El orden de las rutas SÍ importa.
# ─────────────────────────────────────────────────────────────
 
async def _buscar_ids_equipo(client: httpx.AsyncClient, equipo: Equipo) -> dict:
    """Busca en paralelo el ID de un equipo en ambas APIs."""
    resultado = {
        "equipo": equipo.nombre,
        "football_data_team_id": equipo.football_data_team_id,
        "api_football_id": equipo.api_football_id,
    }
 
    tareas = []
    necesita_fd = not equipo.football_data_team_id and FOOTBALL_DATA_TOKEN
    necesita_af = not equipo.api_football_id and API_FOOTBALL_KEY
 
    if necesita_fd:
        tareas.append(client.get(
            "https://api.football-data.org/v4/teams",
            headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN},
            params={"name": equipo.nombre}
        ))
    if necesita_af:
        tareas.append(client.get(
            "https://v3.football.api-sports.io/teams",
            headers={"x-apisports-key": API_FOOTBALL_KEY},
            params={"search": equipo.nombre}
        ))
 
    if not tareas:
        return resultado
 
    try:
        respuestas = await asyncio.gather(*tareas, return_exceptions=True)
    except Exception:
        return resultado
 
    idx = 0
    if necesita_fd:
        r = respuestas[idx]
        idx += 1
        if not isinstance(r, Exception) and r.status_code == 200:
            candidatos = r.json().get("teams", [])
            if candidatos:
                equipo.football_data_team_id = candidatos[0]["id"]
                resultado["football_data_team_id"] = candidatos[0]["id"]
 
    if necesita_af:
        r = respuestas[idx]
        if not isinstance(r, Exception) and r.status_code == 200:
            candidatos = r.json().get("response", [])
            if candidatos:
                equipo.api_football_id = candidatos[0]["team"]["id"]
                resultado["api_football_id"] = candidatos[0]["team"]["id"]
 
    return resultado
 
 
async def _tarea_vincular_ids_externos():
    """Corre en segundo plano: no bloquea la respuesta HTTP al usuario."""
    db = SessionLocal()
    try:
        equipos = db.query(Equipo).filter(Equipo.activo == True).all()
 
        async with httpx.AsyncClient(timeout=20) as client:
            resultados = await asyncio.gather(
                *[_buscar_ids_equipo(client, e) for e in equipos]
            )
 
        db.commit()
 
        sin_coincidencia_completa = [
            r["equipo"] for r in resultados
            if not r["football_data_team_id"] or not r["api_football_id"]
        ]
 
        _estado_vinculacion["resultado"] = {
            "resultados": resultados,
            "sin_coincidencia_completa": sin_coincidencia_completa,
        }
    finally:
        db.close()
        _estado_vinculacion["en_progreso"] = False
 
 
@router.post("/vincular-ids-externos")
async def vincular_ids_externos(background_tasks: BackgroundTasks):
    """
    Inicia en segundo plano la búsqueda del ID de cada equipo en
    football-data.org y API-Football. Responde de inmediato (para evitar
    el timeout del proxy de Railway) — usa GET /vincular-ids-externos
    para consultar el resultado unos segundos después.
    """
    if _estado_vinculacion["en_progreso"]:
        return {"mensaje": "Ya hay un proceso en curso, espera unos segundos y consulta con GET."}
 
    _estado_vinculacion["en_progreso"] = True
    _estado_vinculacion["resultado"] = None
    background_tasks.add_task(_tarea_vincular_ids_externos)
 
    return {"mensaje": "Proceso iniciado en segundo plano. Espera 10-15 segundos y luego llama a GET /api/v1/equipos/vincular-ids-externos para ver el resultado."}
 
 
@router.get("/vincular-ids-externos")
async def consultar_vinculacion_ids_externos():
    """Consulta el resultado del último proceso de vinculación de IDs."""
    if _estado_vinculacion["en_progreso"]:
        return {"estado": "en_progreso", "mensaje": "Todavía procesando, intenta de nuevo en unos segundos."}
    if _estado_vinculacion["resultado"] is None:
        return {"estado": "sin_ejecutar", "mensaje": "Todavía no se ha ejecutado POST /vincular-ids-externos."}
    return {"estado": "completado", **_estado_vinculacion["resultado"]}
 
 
# ─────────────────────────────────────────────────────────────
# Rutas con "/{equipo_id}" — SIEMPRE van después de las rutas fijas
# de arriba (como /vincular-ids-externos), nunca antes.
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
