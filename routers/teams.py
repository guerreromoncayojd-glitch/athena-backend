from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from database.connection import get_db
from database.models import Equipo
from database.schemas import EquipoCreate, EquipoOut

router = APIRouter()

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
