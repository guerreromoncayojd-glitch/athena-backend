import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
 
from database.connection import get_db
from database.models import Equipo
from database.schemas import EquipoCreate, EquipoOut
 
router = APIRouter()
 
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
 
 
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
 
 
@router.post("/vincular-ids-externos")
async def vincular_ids_externos(db: Session = Depends(get_db)):
    """
    Busca automáticamente, por nombre, el ID de cada equipo activo en
    football-data.org y en API-Football, y lo guarda en la base de datos.
 
    Esto es lo que permite que squad_fetcher.py pueda consultar la
    plantilla y las bajas reales de cada equipo. Sin este paso, el
    componente de jugadores del IAI se queda excluido (sin datos).
 
    Es seguro ejecutarlo varias veces — solo actualiza equipos a los
    que todavía les falte algún ID.
    """
    equipos = db.query(Equipo).filter(Equipo.activo == True).all()
 
    resultado = {"vinculados": [], "sin_coincidencia": [], "errores": []}
 
    async with httpx.AsyncClient(timeout=15) as client:
        for equipo in equipos:
            cambios = False
 
            # ── football-data.org ────────────────────────────────
            if not equipo.football_data_team_id and FOOTBALL_DATA_TOKEN:
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
                            cambios = True
                except Exception as e:
                    resultado["errores"].append(f"{equipo.nombre} (football-data): {str(e)}")
 
            # ── API-Football ──────────────────────────────────────
            if not equipo.api_football_id and API_FOOTBALL_KEY:
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
                            cambios = True
                except Exception as e:
                    resultado["errores"].append(f"{equipo.nombre} (API-Football): {str(e)}")
 
            if cambios:
                resultado["vinculados"].append({
                    "equipo": equipo.nombre,
                    "football_data_team_id": equipo.football_data_team_id,
                    "api_football_id": equipo.api_football_id,
                })
            elif not equipo.football_data_team_id or not equipo.api_football_id:
                resultado["sin_coincidencia"].append(equipo.nombre)
 
    db.commit()
    return resultado
