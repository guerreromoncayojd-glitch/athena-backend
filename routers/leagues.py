from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database.connection import get_db
from database.models import Liga
from database.schemas import LigaCreate, LigaOut

router = APIRouter()

@router.get("/", response_model=List[LigaOut])
def listar_ligas(db: Session = Depends(get_db)):
    return db.query(Liga).filter(Liga.activa == True).all()

@router.post("/", response_model=LigaOut, status_code=201)
def crear_liga(liga: LigaCreate, db: Session = Depends(get_db)):
    db_liga = Liga(**liga.dict())
    db.add(db_liga)
    db.commit()
    db.refresh(db_liga)
    return db_liga

@router.get("/{liga_id}", response_model=LigaOut)
def obtener_liga(liga_id: int, db: Session = Depends(get_db)):
    liga = db.query(Liga).filter(Liga.id == liga_id).first()
    if not liga:
        raise HTTPException(status_code=404, detail="Liga no encontrada")
    return liga
