"""
Tabla del registro en vivo de picks de Athena.
Cada partido se guarda UNA vez, antes de empezar, con las probabilidades y cuotas de ese momento
(nunca se sobreescriben), y luego se completa con el resultado real. Así se mide el
desempeño real del modelo en producción, sin poder "mejorar" el pasado.
"""
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime
from sqlalchemy.sql import func

from database.models import Base


class RegistroPick(Base):
    __tablename__ = "registro_picks"

    id = Column(Integer, primary_key=True, index=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())
    clave = Column(String(200), unique=True, index=True)   # liga|fecha|local|visita
    version_modelo = Column(String(30))
    liga = Column(String(80))
    fecha_partido = Column(DateTime(timezone=True))
    local = Column(String(100))
    visita = Column(String(100))

    p_local = Column(Float)
    p_empate = Column(Float)
    p_visita = Column(Float)
    p_mas15 = Column(Float)
    p_mas25 = Column(Float)
    pick_dc = Column(String(80))
    prob_dc = Column(Float)
    pick_goles = Column(String(60))
    prob_goles = Column(Float)

    cuota_local = Column(Float)
    cuota_empate = Column(Float)
    cuota_visita = Column(Float)
    cuota_fuente = Column(String(20))

    resuelto = Column(Boolean, default=False)
    goles_local = Column(Integer)
    goles_visita = Column(Integer)
