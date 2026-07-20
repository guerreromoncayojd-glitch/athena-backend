"""
Schemas Pydantic — validación y serialización de datos
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# LIGA
# ─────────────────────────────────────────────────────────────

class LigaBase(BaseModel):
    nombre: str
    pais: str
    nivel: int = 1
    temporada_actual: Optional[str] = None

class LigaCreate(LigaBase):
    pass

class LigaOut(LigaBase):
    id: int
    activa: bool
    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# EQUIPO
# ─────────────────────────────────────────────────────────────

class EquipoBase(BaseModel):
    nombre: str
    pais: Optional[str] = None
    ciudad: Optional[str] = None
    liga_id: Optional[int] = None
    entrenador: Optional[str] = None
    estadio: Optional[str] = None
    formacion_habitual: str = "4-3-3"
    estilo_ofensivo: Optional[str] = None
    estilo_defensivo: Optional[str] = None
    nivel_presion: float = Field(default=5.0, ge=0, le=10)
    juego_aereo: float = Field(default=5.0, ge=0, le=10)
    juego_bandas: float = Field(default=5.0, ge=0, le=10)
    transiciones_ofensivas: float = Field(default=5.0, ge=0, le=10)
    transiciones_defensivas: float = Field(default=5.0, ge=0, le=10)
    intensidad: float = Field(default=5.0, ge=0, le=10)
    velocidad_juego: float = Field(default=5.0, ge=0, le=10)
    fortaleza_mental: float = Field(default=5.0, ge=0, le=10)
    notas_scout: Optional[str] = None

class EquipoCreate(EquipoBase):
    pass

class EquipoOut(EquipoBase):
    id: int
    partidos_jugados: int
    victorias: int
    empates: int
    derrotas: int
    goles_favor: int
    goles_contra: int
    puntos: int
    xg_favor_promedio: float
    xg_contra_promedio: float
    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# JUGADOR
# ─────────────────────────────────────────────────────────────

class JugadorBase(BaseModel):
    nombre: str
    equipo_id: Optional[int] = None
    numero_dorsal: Optional[int] = None
    posicion_principal: Optional[str] = None
    posicion_secundaria: Optional[str] = None
    nacionalidad: Optional[str] = None
    edad: Optional[int] = None
    pierna_habil: str = "derecha"
    altura: Optional[int] = None
    peso: Optional[int] = None
    valor_mercado: Optional[float] = None

    # Físicos
    velocidad: float = Field(default=50.0, ge=0, le=100)
    aceleracion: float = Field(default=50.0, ge=0, le=100)
    resistencia: float = Field(default=50.0, ge=0, le=100)
    fuerza: float = Field(default=50.0, ge=0, le=100)
    salto: float = Field(default=50.0, ge=0, le=100)

    # Técnicos
    pase_corto: float = Field(default=50.0, ge=0, le=100)
    pase_largo: float = Field(default=50.0, ge=0, le=100)
    control: float = Field(default=50.0, ge=0, le=100)
    regate: float = Field(default=50.0, ge=0, le=100)
    remate_pie: float = Field(default=50.0, ge=0, le=100)
    cabeceo: float = Field(default=50.0, ge=0, le=100)
    centros: float = Field(default=50.0, ge=0, le=100)

    # Mentales
    liderazgo: float = Field(default=50.0, ge=0, le=100)
    concentracion: float = Field(default=50.0, ge=0, le=100)
    decision: float = Field(default=50.0, ge=0, le=100)
    compostura: float = Field(default=50.0, ge=0, le=100)

    notas_scout: Optional[str] = None

class JugadorCreate(JugadorBase):
    pass

class JugadorOut(JugadorBase):
    id: int
    goles: int
    asistencias: int
    partidos_jugados: int
    iai_general: float
    iai_ofensivo: float
    iai_defensivo: float
    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# PARTIDO
# ─────────────────────────────────────────────────────────────

class PartidoCreate(BaseModel):
    liga_id: Optional[int] = None
    equipo_local_id: int
    equipo_visitante_id: int
    fecha: Optional[datetime] = None
    jornada: Optional[int] = None
    temporada: Optional[str] = None
    estadio: Optional[str] = None

class PartidoOut(PartidoCreate):
    id: int
    goles_local: Optional[int]
    goles_visitante: Optional[int]
    jugado: bool
    iai_victoria_local: Optional[float]
    iai_empate: Optional[float]
    iai_victoria_visitante: Optional[float]
    iai_mas_25_goles: Optional[float]
    iai_mas_95_corners: Optional[float]
    iai_mas_45_tarjetas: Optional[float]
    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# PREDICCIÓN IAI
# ─────────────────────────────────────────────────────────────

class PrediccionOut(BaseModel):
    partido_id: int
    version_modelo: str
    victoria_local: float
    empate: float
    victoria_visitante: float
    mas_25_goles: float
    mas_35_goles: float
    ambos_anotan: float
    mas_95_corners: float
    mas_45_tarjetas: float
    confianza_global: float
    factores_clave: Optional[list] = []
    alertas: Optional[list] = []
    notas_analiticas: Optional[str] = None

    class Config:
        from_attributes = True
