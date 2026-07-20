"""
PROYECTO ATHENA - v0.0.1
Modelos de Base de Datos
Motor de Análisis de Fútbol con IA
"""

from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime,
    ForeignKey, Text, JSON, Enum as SAEnum
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()

# ─────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────

class PosicionEnum(str, enum.Enum):
    PORTERO = "PO"
    LATERAL_DERECHO = "LD"
    CENTRAL_DERECHO = "CD"
    CENTRAL_IZQUIERDO = "CI"
    LATERAL_IZQUIERDO = "LI"
    MEDIOCENTRO_DEFENSIVO = "MCD"
    MEDIOCENTRO = "MC"
    MEDIOCENTRO_OFENSIVO = "MCO"
    EXTREMO_DERECHO = "ED"
    EXTREMO_IZQUIERDO = "EI"
    DELANTERO_CENTRO = "DC"
    SEGUNDO_DELANTERO = "SD"

class PiernaEnum(str, enum.Enum):
    DERECHA = "derecha"
    IZQUIERDA = "izquierda"
    AMBAS = "ambas"

class EstiloOfensivoEnum(str, enum.Enum):
    POSESION = "posesion"
    CONTRAATAQUE = "contraataque"
    DIRECTO = "directo"
    COMBINATIVO = "combinativo"
    PRESION_ALTA = "presion_alta"

class EstiloDefensivoEnum(str, enum.Enum):
    BLOQUE_BAJO = "bloque_bajo"
    BLOQUE_MEDIO = "bloque_medio"
    PRESION_ALTA = "presion_alta"
    ZONA = "zona"
    MIXTA = "mixta"
    HOMBRE_A_HOMBRE = "hombre_a_hombre"

# ─────────────────────────────────────────────────────────────
# TABLA: LIGA
# ─────────────────────────────────────────────────────────────

class Liga(Base):
    __tablename__ = "ligas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    pais = Column(String(100), nullable=False)
    nivel = Column(Integer, default=1)  # 1=Primera, 2=Segunda, etc.
    logo_url = Column(String(500))
    activa = Column(Boolean, default=True)
    temporada_actual = Column(String(20))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    equipos = relationship("Equipo", back_populates="liga")
    partidos = relationship("Partido", back_populates="liga")


# ─────────────────────────────────────────────────────────────
# TABLA: EQUIPO
# ─────────────────────────────────────────────────────────────

class Equipo(Base):
    __tablename__ = "equipos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), nullable=False)
    nombre_corto = Column(String(50))
    pais = Column(String(100))
    ciudad = Column(String(100))
    liga_id = Column(Integer, ForeignKey("ligas.id"))
    entrenador = Column(String(150))
    estadio = Column(String(150))
    capacidad_estadio = Column(Integer)
    fundacion = Column(Integer)
    logo_url = Column(String(500))

    # ── ESTILO DE JUEGO ──────────────────────────────────────
    formacion_habitual = Column(String(20), default="4-3-3")
    formacion_alternativa = Column(String(20))
    estilo_ofensivo = Column(String(50))
    estilo_defensivo = Column(String(50))

    # ── MÉTRICAS TÁCTICAS (0.0 a 10.0) ─────────────────────
    nivel_presion = Column(Float, default=5.0)          # Intensidad del pressing
    juego_aereo = Column(Float, default=5.0)            # Efectividad en juego aéreo
    juego_bandas = Column(Float, default=5.0)           # Juego por las bandas
    transiciones_ofensivas = Column(Float, default=5.0) # Velocidad transición defensa-ataque
    transiciones_defensivas = Column(Float, default=5.0)# Velocidad transición ataque-defensa
    intensidad = Column(Float, default=5.0)             # Intensidad general
    velocidad_juego = Column(Float, default=5.0)        # Ritmo del juego
    fortaleza_mental = Column(Float, default=5.0)       # Resiliencia psicológica
    agresividad_tactica = Column(Float, default=5.0)    # Nivel de agresividad táctica
    creatividad = Column(Float, default=5.0)            # Creatividad en ataque
    disciplina_tactica = Column(Float, default=5.0)     # Seguimiento del plan táctico
    compacidad_defensiva = Column(Float, default=5.0)   # Qué tan compacto el bloque defensivo
    altura_linea_defensiva = Column(Float, default=5.0) # Altura de la línea defensiva (0=muy bajo, 10=muy alto)
    pressing_trigger = Column(String(200))              # Descripción del disparador de presión

    # ── ESTADÍSTICAS HISTÓRICAS ──────────────────────────────
    partidos_jugados = Column(Integer, default=0)
    victorias = Column(Integer, default=0)
    empates = Column(Integer, default=0)
    derrotas = Column(Integer, default=0)
    goles_favor = Column(Integer, default=0)
    goles_contra = Column(Integer, default=0)
    puntos = Column(Integer, default=0)

    # ── LOCAL vs VISITANTE ───────────────────────────────────
    victorias_local = Column(Integer, default=0)
    victorias_visitante = Column(Integer, default=0)
    fortaleza_local = Column(Float, default=5.0)        # 0-10
    rendimiento_visitante = Column(Float, default=5.0)  # 0-10

    # ── ESTADÍSTICAS AVANZADAS ───────────────────────────────
    xg_favor_promedio = Column(Float, default=0.0)      # Expected Goals a favor
    xg_contra_promedio = Column(Float, default=0.0)     # Expected Goals en contra
    posesion_promedio = Column(Float, default=50.0)     # % posesión promedio
    tiros_promedio = Column(Float, default=0.0)
    corners_promedio = Column(Float, default=0.0)
    faltas_promedio = Column(Float, default=0.0)
    tarjetas_amarillas_promedio = Column(Float, default=0.0)
    tarjetas_rojas_promedio = Column(Float, default=0.0)

    # ── PATRONES TÁCTICOS ────────────────────────────────────
    cambio_sistema_minuto = Column(Integer)             # Minuto habitual de cambio de sistema
    sistema_segunda_parte = Column(String(20))          # Formación en segunda parte
    tendencia_goles_primeros = Column(Float, default=0.0) # % goles primeros 30 min
    tendencia_goles_ultimos = Column(Float, default=0.0)  # % goles últimos 15 min
    reaccion_desventaja = Column(Float, default=5.0)    # Cómo reacciona cuando va perdiendo
    gestion_ventaja = Column(Float, default=5.0)        # Cómo gestiona cuando va ganando

    # ── METADATOS ────────────────────────────────────────────
    notas_scout = Column(Text)
    activo = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # ── RELACIONES ───────────────────────────────────────────
    liga = relationship("Liga", back_populates="equipos")
    jugadores = relationship("Jugador", back_populates="equipo")
    partidos_local = relationship("Partido", foreign_keys="Partido.equipo_local_id", back_populates="equipo_local")
    partidos_visitante = relationship("Partido", foreign_keys="Partido.equipo_visitante_id", back_populates="equipo_visitante")


# ─────────────────────────────────────────────────────────────
# TABLA: JUGADOR (150+ atributos)
# ─────────────────────────────────────────────────────────────

class Jugador(Base):
    __tablename__ = "jugadores"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), nullable=False)
    nombre_completo = Column(String(200))
    equipo_id = Column(Integer, ForeignKey("equipos.id"))
    numero_dorsal = Column(Integer)
    posicion_principal = Column(String(10))
    posicion_secundaria = Column(String(10))
    posicion_terciaria = Column(String(10))
    nacionalidad = Column(String(100))
    fecha_nacimiento = Column(String(20))
    edad = Column(Integer)
    pierna_habil = Column(String(20), default="derecha")
    altura = Column(Integer)   # cm
    peso = Column(Integer)     # kg
    foto_url = Column(String(500))
    valor_mercado = Column(Float)  # millones €

    # ════════════════════════════════════════════════════════
    # BLOQUE 1: DATOS FÍSICOS (0-100)
    # ════════════════════════════════════════════════════════
    velocidad_max = Column(Float, default=50.0)         # Velocidad máxima (km/h)
    velocidad = Column(Float, default=50.0)             # Rating velocidad
    aceleracion = Column(Float, default=50.0)           # Arranque explosivo
    resistencia = Column(Float, default=50.0)           # Resistencia aeróbica
    fuerza = Column(Float, default=50.0)                # Fuerza física
    salto = Column(Float, default=50.0)                 # Altura de salto
    agilidad = Column(Float, default=50.0)              # Cambios de dirección
    equilibrio = Column(Float, default=50.0)            # Estabilidad corporal
    coordinacion = Column(Float, default=50.0)          # Coordinación motriz
    potencia = Column(Float, default=50.0)              # Potencia en disparo/pase
    distancia_cubierta_promedio = Column(Float)         # km por partido
    sprints_promedio = Column(Float)                    # Sprints por partido
    intensidad_fisica = Column(Float, default=50.0)     # Intensidad física general

    # ════════════════════════════════════════════════════════
    # BLOQUE 2: DATOS TÉCNICOS (0-100)
    # ════════════════════════════════════════════════════════
    pase_corto = Column(Float, default=50.0)
    pase_largo = Column(Float, default=50.0)
    vision = Column(Float, default=50.0)                # Visión de juego
    control = Column(Float, default=50.0)               # Control del balón
    primer_control = Column(Float, default=50.0)        # Calidad primer toque
    regate = Column(Float, default=50.0)
    cabeceo = Column(Float, default=50.0)
    remate_pie = Column(Float, default=50.0)
    remate_cabeza = Column(Float, default=50.0)
    potencia_disparo = Column(Float, default=50.0)
    precision_disparo = Column(Float, default=50.0)
    centros = Column(Float, default=50.0)
    centros_precision = Column(Float, default=50.0)     # Precisión específica en centros
    conduccion = Column(Float, default=50.0)
    pierna_mala = Column(Float, default=50.0)           # Habilidad con pierna no dominante
    tecnica_individual = Column(Float, default=50.0)
    penales = Column(Float, default=50.0)               # Habilidad en penales
    tiros_libres = Column(Float, default=50.0)
    corners_tecnica = Column(Float, default=50.0)       # Técnica en saques de esquina

    # ════════════════════════════════════════════════════════
    # BLOQUE 3: DATOS MENTALES / PSICOLÓGICOS (0-100)
    # ════════════════════════════════════════════════════════
    liderazgo = Column(Float, default=50.0)
    concentracion = Column(Float, default=50.0)
    agresividad = Column(Float, default=50.0)
    decision = Column(Float, default=50.0)              # Toma de decisiones
    inteligencia_tactica = Column(Float, default=50.0)
    posicionamiento = Column(Float, default=50.0)
    anticipacion = Column(Float, default=50.0)
    creatividad_mental = Column(Float, default=50.0)
    compostura = Column(Float, default=50.0)            # Compostura bajo presión
    confianza = Column(Float, default=50.0)
    motivacion = Column(Float, default=50.0)
    resiliencia = Column(Float, default=50.0)           # Recuperación mental
    trabajo_equipo = Column(Float, default=50.0)
    presion_tolerancia = Column(Float, default=50.0)    # Tolerar alta presión
    rendimiento_partidos_grandes = Column(Float, default=50.0) # Big games performance

    # ════════════════════════════════════════════════════════
    # BLOQUE 4: DATOS DEFENSIVOS (0-100)
    # ════════════════════════════════════════════════════════
    entrada = Column(Float, default=50.0)               # Calidad de entrada
    marca = Column(Float, default=50.0)                 # Marcaje
    intercepciones = Column(Float, default=50.0)
    recuperacion_balon = Column(Float, default=50.0)
    cobertura_espacios = Column(Float, default=50.0)
    presion_defensiva = Column(Float, default=50.0)
    duelos_aereos_def = Column(Float, default=50.0)
    bloqueo_tiros = Column(Float, default=50.0)
    lectura_juego_def = Column(Float, default=50.0)

    # ════════════════════════════════════════════════════════
    # BLOQUE 5: DATOS DE PORTERO (0-100) — solo aplica para PO
    # ════════════════════════════════════════════════════════
    reflejos = Column(Float, default=50.0)
    posicionamiento_portero = Column(Float, default=50.0)
    salidas = Column(Float, default=50.0)
    manejo = Column(Float, default=50.0)
    saque_con_pie = Column(Float, default=50.0)
    penales_portero = Column(Float, default=50.0)       # Parada de penales
    comunicacion_portero = Column(Float, default=50.0)
    juego_aereo_portero = Column(Float, default=50.0)

    # ════════════════════════════════════════════════════════
    # BLOQUE 6: MOVIMIENTO Y POSICIONAMIENTO (0-100)
    # ════════════════════════════════════════════════════════
    movimiento_sin_balon = Column(Float, default=50.0)
    desmarques = Column(Float, default=50.0)
    movimiento_entre_lineas = Column(Float, default=50.0) # ¿Se mueve bien entre líneas?
    amplitud = Column(Float, default=50.0)              # Uso de la amplitud
    profundidad = Column(Float, default=50.0)           # Busca la profundidad
    pressing_activo = Column(Float, default=50.0)       # Intensidad en pressing
    cobertura_lateral = Column(Float, default=50.0)     # Cobertura cuando ataca lateral

    # ════════════════════════════════════════════════════════
    # BLOQUE 7: TENDENCIAS / ERRORES FRECUENTES (0-100, mayor = más frecuente)
    # ════════════════════════════════════════════════════════
    error_primer_control = Column(Float, default=10.0)
    error_bajo_presion = Column(Float, default=10.0)    # Pérdidas bajo presión
    error_pierna_mala = Column(Float, default=10.0)     # Imprecisión pierna menos hábil
    error_salida_portero = Column(Float, default=10.0)  # Solo porteros
    error_cobertura = Column(Float, default=10.0)
    error_precision_centros = Column(Float, default=10.0)
    error_definicion = Column(Float, default=10.0)      # Definición inconsistente
    amarillas_frecuencia = Column(Float, default=10.0)  # Frecuencia tarjetas amarillas
    perdidas_posesion = Column(Float, default=10.0)
    fuera_juego_frecuencia = Column(Float, default=10.0)

    # ════════════════════════════════════════════════════════
    # BLOQUE 8: ESTADÍSTICAS DE RENDIMIENTO REAL
    # ════════════════════════════════════════════════════════
    partidos_jugados = Column(Integer, default=0)
    partidos_titular = Column(Integer, default=0)
    minutos_jugados = Column(Integer, default=0)
    goles = Column(Integer, default=0)
    asistencias = Column(Integer, default=0)
    xg_total = Column(Float, default=0.0)               # Expected Goals acumulados
    xa_total = Column(Float, default=0.0)               # Expected Assists acumulados
    pases_completados = Column(Integer, default=0)
    pases_intentados = Column(Integer, default=0)
    precision_pases = Column(Float, default=0.0)        # %
    tiros_totales = Column(Integer, default=0)
    tiros_a_puerta = Column(Integer, default=0)
    regates_exitosos = Column(Integer, default=0)
    regates_intentados = Column(Integer, default=0)
    duelos_ganados = Column(Integer, default=0)
    duelos_totales = Column(Integer, default=0)
    intercepciones_stat = Column(Integer, default=0)
    despejes = Column(Integer, default=0)
    tarjetas_amarillas = Column(Integer, default=0)
    tarjetas_rojas = Column(Integer, default=0)
    corners_ganados = Column(Integer, default=0)
    faltas_cometidas = Column(Integer, default=0)
    faltas_recibidas = Column(Integer, default=0)

    # ════════════════════════════════════════════════════════
    # BLOQUE 9: ANÁLISIS CONTEXTUAL
    # ════════════════════════════════════════════════════════
    rendimiento_local = Column(Float, default=50.0)     # Rendimiento en casa
    rendimiento_visitante = Column(Float, default=50.0) # Rendimiento fuera
    rendimiento_primera_parte = Column(Float, default=50.0)
    rendimiento_segunda_parte = Column(Float, default=50.0)
    rendimiento_ultimos_15min = Column(Float, default=50.0)  # Cansancio/definición
    rendimiento_vs_top = Column(Float, default=50.0)    # Vs equipos grandes
    rendimiento_bajo_lluvia = Column(Float, default=50.0)
    rendimiento_cancha_sintetica = Column(Float, default=50.0)
    caida_rendimiento_cansancio = Column(Float, default=10.0)  # Cuánto baja con fatiga

    # ════════════════════════════════════════════════════════
    # BLOQUE 10: IAI - ÍNDICE ATHENA del jugador
    # ════════════════════════════════════════════════════════
    iai_general = Column(Float, default=50.0)           # Índice Athena general (0-100)
    iai_ofensivo = Column(Float, default=50.0)
    iai_defensivo = Column(Float, default=50.0)
    iai_fisico = Column(Float, default=50.0)
    iai_mental = Column(Float, default=50.0)

    # ── METADATOS ────────────────────────────────────────────
    notas_scout = Column(Text)
    activo = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    equipo = relationship("Equipo", back_populates="jugadores")
    actuaciones = relationship("ActuacionJugador", back_populates="jugador")


# ─────────────────────────────────────────────────────────────
# TABLA: PARTIDO
# ─────────────────────────────────────────────────────────────

class Partido(Base):
    __tablename__ = "partidos"

    id = Column(Integer, primary_key=True, index=True)
    liga_id = Column(Integer, ForeignKey("ligas.id"))
    equipo_local_id = Column(Integer, ForeignKey("equipos.id"))
    equipo_visitante_id = Column(Integer, ForeignKey("equipos.id"))
    fecha = Column(DateTime(timezone=True))
    jornada = Column(Integer)
    temporada = Column(String(20))
    estadio = Column(String(150))

    # ── RESULTADO ────────────────────────────────────────────
    goles_local = Column(Integer)
    goles_visitante = Column(Integer)
    resultado = Column(String(10))                      # "L" local, "E" empate, "V" visitante
    jugado = Column(Boolean, default=False)

    # ── ESTADÍSTICAS DEL PARTIDO ─────────────────────────────
    posesion_local = Column(Float)
    posesion_visitante = Column(Float)
    tiros_local = Column(Integer, default=0)
    tiros_visitante = Column(Integer, default=0)
    tiros_puerta_local = Column(Integer, default=0)
    tiros_puerta_visitante = Column(Integer, default=0)
    corners_local = Column(Integer, default=0)
    corners_visitante = Column(Integer, default=0)
    faltas_local = Column(Integer, default=0)
    faltas_visitante = Column(Integer, default=0)
    amarillas_local = Column(Integer, default=0)
    amarillas_visitante = Column(Integer, default=0)
    rojas_local = Column(Integer, default=0)
    rojas_visitante = Column(Integer, default=0)
    fuera_juego_local = Column(Integer, default=0)
    fuera_juego_visitante = Column(Integer, default=0)
    xg_local = Column(Float, default=0.0)
    xg_visitante = Column(Float, default=0.0)

    # ── PREDICCIONES IAI ─────────────────────────────────────
    iai_victoria_local = Column(Float)                  # 0-100 confianza victoria local
    iai_empate = Column(Float)                          # 0-100 confianza empate
    iai_victoria_visitante = Column(Float)              # 0-100 confianza victoria visitante
    iai_mas_25_goles = Column(Float)                    # 0-100 más de 2.5 goles
    iai_mas_35_goles = Column(Float)
    iai_mas_45_tarjetas = Column(Float)                 # 0-100 más de 4.5 tarjetas
    iai_mas_95_corners = Column(Float)                  # 0-100 más de 9.5 córners
    iai_ambos_anotan = Column(Float)                    # 0-100 ambos equipos anotan

    # ── CONTEXTO ─────────────────────────────────────────────
    temperatura = Column(Float)
    clima = Column(String(50))
    arbitro = Column(String(150))
    importancia = Column(String(50))                    # "normal", "final", "derby", "relegacion"

    liga = relationship("Liga", back_populates="partidos")
    equipo_local = relationship("Equipo", foreign_keys=[equipo_local_id], back_populates="partidos_local")
    equipo_visitante = relationship("Equipo", foreign_keys=[equipo_visitante_id], back_populates="partidos_visitante")
    actuaciones = relationship("ActuacionJugador", back_populates="partido")
    prediccion = relationship("PrediccionIAI", back_populates="partido", uselist=False)


# ─────────────────────────────────────────────────────────────
# TABLA: ACTUACIÓN JUGADOR (por partido)
# ─────────────────────────────────────────────────────────────

class ActuacionJugador(Base):
    __tablename__ = "actuaciones_jugadores"

    id = Column(Integer, primary_key=True, index=True)
    partido_id = Column(Integer, ForeignKey("partidos.id"))
    jugador_id = Column(Integer, ForeignKey("jugadores.id"))
    minutos_jugados = Column(Integer, default=0)
    titular = Column(Boolean, default=False)
    goles = Column(Integer, default=0)
    asistencias = Column(Integer, default=0)
    amarillas = Column(Integer, default=0)
    rojas = Column(Integer, default=0)
    nota = Column(Float)                                # Nota 1-10
    iai_actuacion = Column(Float)                       # IAI de la actuación

    partido = relationship("Partido", back_populates="actuaciones")
    jugador = relationship("Jugador", back_populates="actuaciones")


# ─────────────────────────────────────────────────────────────
# TABLA: PREDICCIÓN IAI (ÍNDICE ATHENA)
# ─────────────────────────────────────────────────────────────

class PrediccionIAI(Base):
    __tablename__ = "predicciones_iai"

    id = Column(Integer, primary_key=True, index=True)
    partido_id = Column(Integer, ForeignKey("partidos.id"), unique=True)
    generada_en = Column(DateTime(timezone=True), server_default=func.now())
    version_modelo = Column(String(20), default="0.0.1")

    # Resultados
    victoria_local = Column(Float)                      # IAI 0-100
    empate = Column(Float)
    victoria_visitante = Column(Float)
    mas_25_goles = Column(Float)
    mas_35_goles = Column(Float)
    ambos_anotan = Column(Float)
    mas_95_corners = Column(Float)
    mas_45_tarjetas = Column(Float)

    # Confianza global
    confianza_global = Column(Float)                    # 0-100
    factores_clave = Column(JSON)                       # Lista de factores que influyeron
    alertas = Column(JSON)                              # Alertas especiales detectadas
    notas_analiticas = Column(Text)

    partido = relationship("Partido", back_populates="prediccion")
