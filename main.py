ubuntu@sandbox:~ $ cat /home/sandbox/athena-app/backend/main.py
"""
PROYECTO ATHENA — v0.0.1
FastAPI Backend — Servidor principal
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from database.connection import create_tables, SessionLocal, engine
from routers import teams, players, matches, predictions, leagues

# ─── App ─────────────────────────────────────────────────────
app = FastAPI(
    title="Proyecto Athena API",
    description="Motor de análisis de fútbol con IA — Índice Athena (IAI)",
    version="0.0.1",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ─── CORS ────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Seed de datos iniciales ─────────────────────────────────
def seed_data(db):
    from database.models import Liga, Equipo, Partido
    from datetime import date, timedelta
    import random

    if db.query(Liga).count() > 0:
        return  # Ya hay datos, no hacer nada

    # ── Ligas ────────────────────────────────────────────────
    laliga = Liga(nombre="La Liga", pais="España", temporada_actual="2024-25", activa=True)
    premier = Liga(nombre="Premier League", pais="Inglaterra", temporada_actual="2024-25", activa=True)
    db.add_all([laliga, premier])
    db.flush()

    # ── Equipos La Liga ──────────────────────────────────────
    equipos_laliga = [
        {"nombre": "Real Madrid",      "ciudad": "Madrid",       "formacion": "4-3-3",   "estilo_of": "posesion",    "estilo_def": "presion_alta",  "velocidad": 88, "mental": 95},
        {"nombre": "FC Barcelona",     "ciudad": "Barcelona",    "formacion": "4-3-3",   "estilo_of": "posesion",    "estilo_def": "presion_alta",  "velocidad": 85, "mental": 88},
        {"nombre": "Atletico Madrid",  "ciudad": "Madrid",       "formacion": "4-4-2",   "estilo_of": "contraataque","estilo_def": "bloque_bajo",   "velocidad": 80, "mental": 92},
        {"nombre": "Real Sociedad",    "ciudad": "San Sebastián","formacion": "4-3-3",   "estilo_of": "posesion",    "estilo_def": "presion_media", "velocidad": 78, "mental": 80},
        {"nombre": "Athletic Bilbao",  "ciudad": "Bilbao",       "formacion": "4-2-3-1", "estilo_of": "directo",     "estilo_def": "presion_alta",  "velocidad": 82, "mental": 85},
        {"nombre": "Villarreal",       "ciudad": "Villarreal",   "formacion": "4-3-3",   "estilo_of": "posesion",    "estilo_def": "presion_media", "velocidad": 76, "mental": 78},
        {"nombre": "Real Betis",       "ciudad": "Sevilla",      "formacion": "4-2-3-1", "estilo_of": "posesion",    "estilo_def": "presion_media", "velocidad": 74, "mental": 76},
        {"nombre": "Sevilla FC",       "ciudad": "Sevilla",      "formacion": "4-3-3",   "estilo_of": "directo",     "estilo_def": "bloque_medio",  "velocidad": 75, "mental": 78},
    ]

    # ── Equipos Premier League ───────────────────────────────
    equipos_premier = [
        {"nombre": "Manchester City",   "ciudad": "Manchester", "formacion": "4-3-3",   "estilo_of": "posesion",    "estilo_def": "presion_alta",  "velocidad": 87, "mental": 94},
        {"nombre": "Arsenal",           "ciudad": "Londres",    "formacion": "4-3-3",   "estilo_of": "posesion",    "estilo_def": "presion_alta",  "velocidad": 86, "mental": 88},
        {"nombre": "Liverpool",         "ciudad": "Liverpool",  "formacion": "4-3-3",   "estilo_of": "contraataque","estilo_def": "presion_alta",  "velocidad": 90, "mental": 92},
        {"nombre": "Chelsea",           "ciudad": "Londres",    "formacion": "4-2-3-1", "estilo_of": "directo",     "estilo_def": "presion_media", "velocidad": 83, "mental": 82},
        {"nombre": "Tottenham",         "ciudad": "Londres",    "formacion": "4-3-3",   "estilo_of": "contraataque","estilo_def": "presion_media", "velocidad": 84, "mental": 80},
        {"nombre": "Newcastle",         "ciudad": "Newcastle",  "formacion": "4-3-3",   "estilo_of": "directo",     "estilo_def": "bloque_medio",  "velocidad": 79, "mental": 81},
        {"nombre": "Aston Villa",       "ciudad": "Birmingham", "formacion": "4-2-3-1", "estilo_of": "contraataque","estilo_def": "presion_media", "velocidad": 81, "mental": 80},
        {"nombre": "Manchester United", "ciudad": "Manchester", "formacion": "4-2-3-1", "estilo_of": "directo",     "estilo_def": "bloque_medio",  "velocidad": 78, "mental": 82},
    ]

    def _crear_equipo(e, liga_id):
        eq = Equipo(
            nombre=e["nombre"], ciudad=e["ciudad"], liga_id=liga_id,
            formacion_habitual=e["formacion"],
            estilo_ofensivo=e["estilo_of"],
            estilo_defensivo=e["estilo_def"],
            velocidad_juego=e["velocidad"],
            fortaleza_mental=e["mental"],
            nivel_presion=random.randint(60, 90),
            juego_aereo=random.randint(60, 90),
            juego_bandas=random.randint(60, 90),
            transiciones_ofensivas=random.randint(60, 90),
            intensidad=random.randint(70, 95),
            partidos_jugados=random.randint(25, 35),
            victorias=random.randint(10, 25),
            empates=random.randint(3, 10),
            derrotas=random.randint(2, 12),
            goles_favor=random.randint(35, 85),
            goles_contra=random.randint(20, 55),
            xg_favor_promedio=round(random.uniform(1.0, 2.5), 2),
            xg_contra_promedio=round(random.uniform(0.8, 1.8), 2),
            posesion_promedio=round(random.uniform(42.0, 62.0), 1),
            corners_promedio=round(random.uniform(4.0, 8.0), 1),
        )
        eq.puntos = eq.victorias * 3 + eq.empates
        return eq

    obj_laliga  = [_crear_equipo(e, laliga.id)  for e in equipos_laliga]
    obj_premier = [_crear_equipo(e, premier.id) for e in equipos_premier]
    db.add_all(obj_laliga + obj_premier)
    db.flush()

    # ── Partidos próximos La Liga ────────────────────────────
    from datetime import date, timedelta
    hoy = date.today()
    partidos_laliga = [
        (obj_laliga[0], obj_laliga[1]),   # Real Madrid vs Barcelona
        (obj_laliga[2], obj_laliga[0]),   # Atletico vs Real Madrid
        (obj_laliga[1], obj_laliga[2]),   # Barcelona vs Atletico
        (obj_laliga[3], obj_laliga[4]),   # Real Sociedad vs Athletic
        (obj_laliga[5], obj_laliga[6]),   # Villarreal vs Betis
        (obj_laliga[7], obj_laliga[3]),   # Sevilla vs Real Sociedad
    ]
    for i, (local, visitante) in enumerate(partidos_laliga):
        p = Partido(
            liga_id=laliga.id,
            equipo_local_id=local.id,
            equipo_visitante_id=visitante.id,
            fecha=hoy + timedelta(days=i*7 + 3),
            jornada=i + 28,
            estadio=f"Estadio de {local.ciudad}",
            estado="programado"
        )
        db.add(p)

    # ── Partidos próximos Premier League ────────────────────
    partidos_premier = [
        (obj_premier[0], obj_premier[1]),  # Man City vs Arsenal
        (obj_premier[2], obj_premier[0]),  # Liverpool vs Man City
        (obj_premier[1], obj_premier[2]),  # Arsenal vs Liverpool
        (obj_premier[3], obj_premier[4]),  # Chelsea vs Tottenham
        (obj_premier[5], obj_premier[6]),  # Newcastle vs Aston Villa
        (obj_premier[7], obj_premier[3]),  # Man United vs Chelsea
    ]
    for i, (local, visitante) in enumerate(partidos_premier):
        p = Partido(
            liga_id=premier.id,
            equipo_local_id=local.id,
            equipo_visitante_id=visitante.id,
            fecha=hoy + timedelta(days=i*7 + 5),
            jornada=i + 28,
            estadio=f"Stadium {local.ciudad}",
            estado="programado"
        )
        db.add(p)

    db.commit()
    print("✅ Datos iniciales cargados: 2 ligas, 16 equipos, 12 partidos")


# ─── Crear tablas al inicio ──────────────────────────────────
@app.on_event("startup")
async def startup():
    # 1. Crear tablas nuevas si no existen
    create_tables()

    # 2. Ejecutar migraciones de esquema (renombres, columnas nuevas)
    from database.migrations import run_migrations
    run_migrations(engine)

    # 3. Seed inicial de datos si la BD está vacía
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()

# ─── Routers ─────────────────────────────────────────────────
app.include_router(leagues.router,     prefix="/api/v1/ligas",     tags=["Ligas"])
app.include_router(teams.router,       prefix="/api/v1/equipos",   tags=["Equipos"])
app.include_router(players.router,     prefix="/api/v1/jugadores", tags=["Jugadores"])
app.include_router(matches.router,     prefix="/api/v1/partidos",  tags=["Partidos"])
app.include_router(predictions.router, prefix="/api/v1/iai",       tags=["IAI - Índice Athena"])

# ─── Root ────────────────────────────────────────────────────
@app.get("/", tags=["Sistema"])
async def root():
    return {
        "proyecto": "Athena",
        "version": "0.0.1",
        "status": "operativo",
        "docs": "/docs"
    }

@app.get("/health", tags=["Sistema"])
async def health():
    return {"status": "ok", "version": "0.0.1"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
