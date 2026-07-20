"""
PROYECTO ATHENA — v0.0.1
FastAPI Backend — Servidor principal
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from database.connection import create_tables
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

# ─── Crear tablas al inicio ──────────────────────────────────
@app.on_event("startup")
async def startup():
    create_tables()

# ─── Routers ─────────────────────────────────────────────────
app.include_router(leagues.router, prefix="/api/v1/ligas",     tags=["Ligas"])
app.include_router(teams.router,   prefix="/api/v1/equipos",   tags=["Equipos"])
app.include_router(players.router, prefix="/api/v1/jugadores", tags=["Jugadores"])
app.include_router(matches.router, prefix="/api/v1/partidos",  tags=["Partidos"])
app.include_router(predictions.router, prefix="/api/v1/iai",   tags=["IAI - Índice Athena"])

# ─── Root ────────────────────────────────────────────────────
@app.get("/", tags=["Sistema"])
async def root():
    return {
        "proyecto": "Athena",
        "version": "0.0.1",
        "descripcion": "Motor de análisis de fútbol con IA",
        "indice": "IAI — Índice Athena (0-100)",
        "modulos": [
            "Motor Estadístico",
            "Motor Táctico",
            "Motor de Jugadores",
            "Motor de Simulación",
            "Motor IAI",
        ],
        "docs": "/docs",
        "status": "operativo"
    }

@app.get("/health", tags=["Sistema"])
async def health():
    return {"status": "ok", "version": "0.0.1"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
