ubuntu@sandbox:~ $ cat /home/sandbox/athena-app/backend/engines/data_fetcher.py
"""
Motor de datos en vivo — football-data.org API
Fetches partidos reales y los sincroniza con la BD de Athena
"""

import os
import httpx
from datetime import date, timedelta
from sqlalchemy.orm import Session
from database.models import Liga, Equipo, Partido

FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
BASE_URL = "https://api.football-data.org/v4"

LIGAS_MAP = {
    "PD":  "La Liga",           # España
    "PL":  "Premier League",    # Inglaterra
    "CL":  "Champions League",  # UEFA
    "BL1": "Bundesliga",        # Alemania
    "SA":  "Serie A",           # Italia
    "FL1": "Ligue 1",           # Francia
}

def _headers(token):
    return {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }


async def fetch_upcoming_matches(db: Session, days_ahead: int = 14) -> dict:
    """Descarga partidos próximos de football-data.org y los guarda en BD."""

    token = FOOTBALL_DATA_TOKEN
    if not token:
        return {"error": "FOOTBALL_DATA_TOKEN no configurado", "partidos": 0}

    date_from = date.today().strftime("%Y-%m-%d")
    date_to   = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    total_nuevos = 0
    errores = []

    async with httpx.AsyncClient(timeout=30) as client:
        for codigo, nombre_liga in LIGAS_MAP.items():
            try:
                url = f"{BASE_URL}/competitions/{codigo}/matches"
                params = {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"}
                r = await client.get(url, headers=_headers(token), params=params)

                if r.status_code == 403:
                    # Liga no disponible en plan gratuito — continuar
                    continue
                if r.status_code != 200:
                    errores.append(f"{nombre_liga}: HTTP {r.status_code}")
                    continue

                data = r.json()
                matches = data.get("matches", [])
                if not matches:
                    continue

                # Obtener o crear liga en BD
                liga_db = db.query(Liga).filter(Liga.nombre == nombre_liga).first()
                if not liga_db:
                    liga_db = Liga(
                        nombre=nombre_liga,
                        pais=_pais(codigo),
                        temporada_actual="2024-25",
                        activa=True
                    )
                    db.add(liga_db)
                    db.flush()

                for m in matches:
                    await _guardar_partido(db, m, liga_db)
                    total_nuevos += 1

                db.commit()

            except Exception as e:
                errores.append(f"{nombre_liga}: {str(e)}")

    return {"partidos_sincronizados": total_nuevos, "errores": errores}


async def _guardar_partido(db: Session, match: dict, liga: Liga):
    """Guarda o actualiza un partido en la BD."""
    api_id = str(match.get("id", ""))
    if not api_id:
        return

    # Verificar si ya existe
    existente = db.query(Partido).filter(Partido.api_match_id == api_id).first()
    if existente:
        return

    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    if not home.get("name") or not away.get("name"):
        return

    local     = _get_or_create_equipo(db, home, liga)
    visitante = _get_or_create_equipo(db, away, liga)

    fecha_str = match.get("utcDate", "")[:10]
    try:
        fecha = date.fromisoformat(fecha_str)
    except Exception:
        fecha = date.today()

    partido = Partido(
        liga_id=liga.id,
        equipo_local_id=local.id,
        equipo_visitante_id=visitante.id,
        fecha=fecha,
        jornada=match.get("matchday", 0) or 0,
        estadio=home.get("venue", f"Estadio {home.get('name', '')}"),
        estado="programado",
        api_match_id=api_id
    )
    db.add(partido)


def _get_or_create_equipo(db: Session, team_data: dict, liga: Liga) -> Equipo:
    nombre = team_data.get("name", "Desconocido")
    eq = db.query(Equipo).filter(Equipo.nombre == nombre).first()
    if not eq:
        import random
        eq = Equipo(
            nombre=nombre,
            ciudad=team_data.get("area", {}).get("name", ""),
            liga_id=liga.id,
            # ── Nombres correctos del modelo v0.0.2 ──────────
            formacion_habitual="4-3-3",
            estilo_ofensivo="posesion",
            estilo_defensivo="bloque_medio",
            velocidad_juego=random.randint(70, 88),
            fortaleza_mental=random.randint(70, 90),
            nivel_presion=random.randint(60, 85),
            juego_aereo=random.randint(60, 85),
            juego_bandas=random.randint(60, 85),
            transiciones_ofensivas=random.randint(60, 85),
            intensidad=random.randint(65, 90),
            partidos_jugados=random.randint(25, 35),
            victorias=random.randint(8, 22),
            empates=random.randint(3, 10),
            derrotas=random.randint(3, 12),
            goles_favor=random.randint(30, 75),
            goles_contra=random.randint(20, 55),
            xg_favor_promedio=round(random.uniform(1.0, 2.5), 2),
            xg_contra_promedio=round(random.uniform(0.8, 1.8), 2),
            posesion_promedio=round(random.uniform(42.0, 60.0), 1),
            corners_promedio=round(random.uniform(4.0, 8.0), 1),
        )
        eq.puntos = eq.victorias * 3 + eq.empates
        db.add(eq)
        db.flush()
    return eq


def _pais(codigo: str) -> str:
    return {
        "PD": "España", "PL": "Inglaterra", "CL": "Europa",
        "BL1": "Alemania", "SA": "Italia", "FL1": "Francia"
    }.get(codigo, "")
