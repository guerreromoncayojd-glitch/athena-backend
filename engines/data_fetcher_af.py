"""
Motor de datos en vivo — API-Football
Trae partidos de ligas que football-data.org NO cubre (ej. Ecuador).
Busca la liga automáticamente por nombre/país, en vez de depender de
un ID fijo que podría estar equivocado.
"""
import os
import random
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from database.models import Liga, Equipo, Partido
 
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
AF_BASE_URL = "https://v3.football.api-sports.io"
 
 
def _headers():
    return {"x-apisports-key": API_FOOTBALL_KEY}
 
 
async def _buscar_liga_id(client: httpx.AsyncClient, pais: str, nombre_contiene: str) -> tuple:
    """
    Busca el ID de una liga en API-Football por país y parte del nombre.
    Devuelve (id_o_None, lista_de_nombres_encontrados) — la lista sirve
    para diagnóstico si no hay coincidencia.
    """
    r = await client.get(f"{AF_BASE_URL}/leagues", headers=_headers(), params={"country": pais})
    if r.status_code != 200:
        return None, [f"HTTP {r.status_code} al consultar /leagues"]
    ligas = r.json().get("response", [])
    nombres = [l.get("league", {}).get("name", "") for l in ligas]
    for l in ligas:
        nombre = l.get("league", {}).get("name", "")
        if nombre_contiene.lower() in nombre.lower():
            return l["league"]["id"], nombres
    return None, nombres
 
 
async def fetch_upcoming_matches_ecuador(db: Session, days_ahead: int = 14) -> dict:
    """Descarga partidos próximos de LigaPro Ecuador (Serie A) vía API-Football."""
    if not API_FOOTBALL_KEY:
        return {"error": "API_FOOTBALL_KEY no configurado", "partidos_sincronizados": 0}
 
    nombre_liga = "LigaPro Ecuador"
    # La temporada de Ecuador corre de febrero a diciembre — coincide
    # con el año calendario, a diferencia de las ligas europeas.
    temporada = datetime.now().year
 
    async with httpx.AsyncClient(timeout=30) as client:
        liga_af_id, nombres_encontrados = await _buscar_liga_id(client, "Ecuador", "Liga Pro")
        if not liga_af_id:
            return {
                "error": "No se encontró 'Liga Pro' en las ligas de Ecuador de API-Football",
                "ligas_encontradas_para_ecuador": nombres_encontrados,
                "partidos_sincronizados": 0,
            }
 
        date_from = datetime.now().strftime("%Y-%m-%d")
        date_to = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
 
        r = await client.get(
            f"{AF_BASE_URL}/fixtures",
            headers=_headers(),
            params={"league": liga_af_id, "season": temporada, "from": date_from, "to": date_to}
        )
        if r.status_code != 200:
            return {"error": f"API-Football respondió {r.status_code}", "partidos_sincronizados": 0}
 
        fixtures = r.json().get("response", [])
        if not fixtures:
            return {
                "partidos_sincronizados": 0,
                "mensaje": "Sin partidos próximos encontrados en ese rango de fechas",
                "liga_af_id": liga_af_id,
            }
 
        liga_db = db.query(Liga).filter(Liga.nombre == nombre_liga).first()
        if not liga_db:
            liga_db = Liga(nombre=nombre_liga, pais="Ecuador", temporada_actual=str(temporada), activa=True)
            db.add(liga_db)
            db.flush()
 
        total_nuevos = 0
        for fx in fixtures:
            if _guardar_partido_af(db, fx, liga_db):
                total_nuevos += 1
        db.commit()
 
        return {"partidos_sincronizados": total_nuevos, "liga_af_id": liga_af_id}
 
 
def _guardar_partido_af(db: Session, fixture: dict, liga: Liga) -> bool:
    fx = fixture.get("fixture", {})
    api_id = str(fx.get("id", ""))
    if not api_id:
        return False
 
    existente = db.query(Partido).filter(Partido.api_match_id == api_id).first()
    if existente:
        return False
 
    teams = fixture.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})
    if not home.get("name") or not away.get("name"):
        return False
 
    local = _get_or_create_equipo_af(db, home, liga)
    visitante = _get_or_create_equipo_af(db, away, liga)
 
    fecha_str = fx.get("date", "")
    try:
        fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
    except Exception:
        fecha = datetime.now(timezone.utc)
 
    ronda = fixture.get("league", {}).get("round", "") or ""
    jornada_num = None
    if ronda:
        digitos = "".join(c for c in ronda if c.isdigit())
        if digitos:
            jornada_num = int(digitos)
 
    partido = Partido(
        liga_id=liga.id,
        equipo_local_id=local.id,
        equipo_visitante_id=visitante.id,
        fecha=fecha,
        jornada=jornada_num,
        estadio=(fx.get("venue", {}) or {}).get("name") or f"Estadio {home.get('name', '')}",
        estado="programado",
        api_match_id=api_id,
    )
    db.add(partido)
    return True
 
 
def _get_or_create_equipo_af(db: Session, team_data: dict, liga: Liga) -> Equipo:
    nombre = team_data.get("name", "Desconocido")
    eq = db.query(Equipo).filter(Equipo.nombre == nombre).first()
    if not eq:
        eq = Equipo(
            nombre=nombre,
            pais="Ecuador",
            liga_id=liga.id,
            api_football_id=team_data.get("id"),
            formacion_habitual="4-3-3",
            estilo_ofensivo="posesion",
            estilo_defensivo="bloque_medio",
            velocidad_juego=random.randint(60, 80),
            fortaleza_mental=random.randint(60, 80),
            nivel_presion=random.randint(50, 75),
            juego_aereo=random.randint(50, 75),
            juego_bandas=random.randint(50, 75),
            transiciones_ofensivas=random.randint(50, 75),
            intensidad=random.randint(55, 80),
            partidos_jugados=random.randint(15, 25),
            victorias=random.randint(5, 15),
            empates=random.randint(2, 8),
            derrotas=random.randint(2, 10),
            goles_favor=random.randint(15, 40),
            goles_contra=random.randint(10, 35),
            xg_favor_promedio=round(random.uniform(0.9, 1.8), 2),
            xg_contra_promedio=round(random.uniform(0.8, 1.6), 2),
            posesion_promedio=round(random.uniform(42.0, 58.0), 1),
            corners_promedio=round(random.uniform(3.5, 7.0), 1),
        )
        eq.puntos = eq.victorias * 3 + eq.empates
        db.add(eq)
        db.flush()
    else:
        if not eq.liga_id:
            eq.liga_id = liga.id
        if not eq.api_football_id and team_data.get("id"):
            eq.api_football_id = team_data.get("id")
    return eq
 
