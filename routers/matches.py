from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from database.connection import get_db
from database.models import Partido
from database.schemas import PartidoCreate, PartidoOut

router = APIRouter()

@router.get("/", response_model=List[PartidoOut])
def listar_partidos(
    liga_id: Optional[int] = None,
    jugado: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Partido)
    if liga_id:
        query = query.filter(Partido.liga_id == liga_id)
    if jugado is not None:
        query = query.filter(Partido.jugado == jugado)
    return query.order_by(Partido.fecha.desc()).limit(100).all()

@router.post("/", response_model=PartidoOut, status_code=201)
def crear_partido(partido: PartidoCreate, db: Session = Depends(get_db)):
    db_partido = Partido(**partido.dict())
    db.add(db_partido)
    db.commit()
    db.refresh(db_partido)
    return db_partido

@router.get("/{partido_id}", response_model=PartidoOut)
def obtener_partido(partido_id: int, db: Session = Depends(get_db)):
    partido = db.query(Partido).filter(Partido.id == partido_id).first()
    if not partido:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    return partido
