from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from database.connection import get_db
from database.models import Jugador
from database.schemas import JugadorCreate, JugadorOut
from engines.player_engine import motor_jugadores

router = APIRouter()

@router.get("/", response_model=List[JugadorOut])
def listar_jugadores(
    equipo_id: Optional[int] = None,
    posicion: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Jugador).filter(Jugador.activo == True)
    if equipo_id:
        query = query.filter(Jugador.equipo_id == equipo_id)
    if posicion:
        query = query.filter(Jugador.posicion_principal == posicion)
    return query.all()

@router.post("/", response_model=JugadorOut, status_code=201)
def crear_jugador(jugador: JugadorCreate, db: Session = Depends(get_db)):
    datos = jugador.dict()
    
    # Calcular IAI automáticamente al crear
    posicion = datos.get("posicion_principal", "MC")
    iai = motor_jugadores.calcular_iai_jugador(datos, posicion)
    datos.update(iai)
    
    db_jugador = Jugador(**datos)
    db.add(db_jugador)
    db.commit()
    db.refresh(db_jugador)
    return db_jugador

@router.get("/{jugador_id}", response_model=JugadorOut)
def obtener_jugador(jugador_id: int, db: Session = Depends(get_db)):
    jugador = db.query(Jugador).filter(Jugador.id == jugador_id).first()
    if not jugador:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    return jugador

@router.get("/{jugador_id}/analisis")
def analizar_jugador(jugador_id: int, db: Session = Depends(get_db)):
    """Análisis completo de un jugador con IAI, fortalezas y vulnerabilidades."""
    jugador = db.query(Jugador).filter(Jugador.id == jugador_id).first()
    if not jugador:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    
    datos = {col.name: getattr(jugador, col.name) for col in jugador.__table__.columns}
    posicion = jugador.posicion_principal or "MC"
    
    return {
        "jugador": jugador.nombre,
        "posicion": posicion,
        "iai": motor_jugadores.calcular_iai_jugador(datos, posicion),
        "fortalezas": motor_jugadores.detectar_fortalezas(datos, posicion),
        "vulnerabilidades": motor_jugadores.detectar_vulnerabilidades(datos, posicion),
    }
