"""
Motor de datos en vivo — football-data.org API
Fetches partidos reales y los sincroniza con la BD de Athena
"""
import os
import httpx
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from database.models import Liga, Equipo, Partido
 
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
BASE_URL = "https://api.football-data.org/v4"
 
LIGAS_MAP = {
    "PD": "La Liga",              # España
    "PL": "Premier League",       # Inglaterra
    "CL": "Champions League",     # UEFA
    "BL1": "Bundesliga",          # Alemania
    "SA": "Serie A",              # Italia
    "FL1": "Ligue 1",             # Francia
    "BSA": "Brasileirao Serie A", # Brasil
    "CLI": "Copa Libertadores",   # CONMEBOL
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
    date_to = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
 
    total_nuevos = 0
    errores = []
    ligas_no_disponibles = []
 
    async with httpx.AsyncClient(timeout=30) as client:
        for codigo, nombre_liga in LIGAS_MAP.items():
            try:
                url = f"{BASE_URL}/competitions/{codigo}/matches"
                params = {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"}
                r = await client.get(url, headers=_headers(token), params=params)
 
                if r.status_code == 403:
                    ligas_no_disponibles.append(nombre_liga)
                    continue
                if r.status_code != 200:
                    errores.append(f"{nombre_liga}: HTTP {r.status_code}")
                    continue
 
                data = r.json()
                matches = data.get("matches", [])
                if not matches:
                    continue
 
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
 
    return {
        "partidos_sincronizados": total_nuevos,
        "errores": errores,
        "ligas_no_disponibles_en_tu_plan": ligas_no_disponibles,
    }
 
 
async def _guardar_partido(db: Session, match: dict, liga: Liga):
    """Guarda o actualiza un partido en la BD."""
    api_id = str(match.get("id", ""))
    if not api_id:
        return
 
    existente = db.query(Partido).filter(Partido.api_match_id == api_id).first()
    if existente:
        return
 
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})
    if not home.get("name") or not away.get("name"):
        return
 
    local = _get_or_create_equipo(db, home, liga)
    visitante = _get_or_create_equipo(db, away, liga)
 
    utc_date_str = match.get("utcDate", "")
    try:
        fecha = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
    except Exception:
        fecha = datetime.now(timezone.utc)
 
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
            # Guardamos el ID real de football-data.org desde el inicio —
            # esto es lo que permite luego traer sus partidos reales y
            # calcular estadísticas de verdad, no aleatorias.
            football_data_team_id=team_data.get("id"),
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
            # Valores de arranque — se sobrescriben con datos reales al
            # ejecutar POST /api/v1/equipos/actualizar-stats-reales
            partidos_jugados=0,
            victorias=0,
            empates=0,
            derrotas=0,
            goles_favor=0,
            goles_contra=0,
            xg_favor_promedio=1.2,
            xg_contra_promedio=1.2,
            posesion_promedio=50.0,
            corners_promedio=5.0,
        )
        eq.puntos = 0
        db.add(eq)
        db.flush()
    else:
        if not eq.liga_id:
            eq.liga_id = liga.id
        if not eq.football_data_team_id and team_data.get("id"):
            eq.football_data_team_id = team_data.get("id")
    return eq
 
 
async def actualizar_stats_reales_equipo(client: httpx.AsyncClient, equipo: Equipo, limite: int = 8) -> Optional[str]:
    """
    Trae los últimos partidos JUGADOS reales de un equipo (usando su
    football_data_team_id) y calcula estadísticas reales:
    - Goles a favor/en contra (proxy real de xG, ya que el plan
      gratuito no da xG de verdad)
    - Victorias/empates/derrotas y puntos
    - Racha actual (sin perder / sin ganar), calculada en orden real
    - Rendimiento como local vs. como visitante, calculado por separado
 
    NOTA HONESTA: esto NO incluye presión, juego aéreo ni transiciones
    ofensivas — esos datos requieren estadísticas de eventos del
    partido que ninguna API gratuita ofrece. Esos campos siguen siendo
    estimados; ver notas en iai_engine.py.
 
    Devuelve None si se actualizó bien, o un mensaje de error/nota.
    """
    if not equipo.football_data_team_id or not FOOTBALL_DATA_TOKEN:
        return "sin football_data_team_id o token configurado"
 
    try:
        r = await client.get(
            f"{BASE_URL}/teams/{equipo.football_data_team_id}/matches",
            headers=_headers(FOOTBALL_DATA_TOKEN),
            params={"status": "FINISHED", "limit": limite}
        )
        if r.status_code != 200:
            return f"football-data respondió {r.status_code}"
 
        partidos = r.json().get("matches", [])
        if not partidos:
            return "sin partidos jugados todavía esta temporada"
 
        # Football-data.org devuelve los partidos del más reciente al
        # más antiguo por defecto — lo confirmamos ordenando nosotros
        # mismos por fecha, de más reciente a más antiguo.
        def _fecha_partido(p):
            try:
                return datetime.fromisoformat(p.get("utcDate", "").replace("Z", "+00:00"))
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)
 
        partidos.sort(key=_fecha_partido, reverse=True)
 
        victorias = empates = derrotas = 0
        goles_favor = goles_contra = 0
        victorias_local = partidos_local = 0
        victorias_visitante = partidos_visitante = 0
        racha_sin_perder = 0
        racha_sin_ganar = 0
        racha_rota_perder = False
        racha_rota_ganar = False
 
        for p in partidos:
            marcador = p.get("score", {}).get("fullTime", {})
            gh = marcador.get("home")
            ga = marcador.get("away")
            if gh is None or ga is None:
                continue
 
            es_local = p.get("homeTeam", {}).get("id") == equipo.football_data_team_id
            goles_propios = gh if es_local else ga
            goles_rival = ga if es_local else gh
 
            goles_favor += goles_propios
            goles_contra += goles_rival
 
            if goles_propios > goles_rival:
                resultado = "victoria"
                victorias += 1
            elif goles_propios == goles_rival:
                resultado = "empate"
                empates += 1
            else:
                resultado = "derrota"
                derrotas += 1
 
            if es_local:
                partidos_local += 1
                if resultado == "victoria":
                    victorias_local += 1
            else:
                partidos_visitante += 1
                if resultado == "victoria":
                    victorias_visitante += 1
 
            # Racha: solo cuenta partidos consecutivos desde el más
            # reciente hacia atrás, sin cortes.
            if not racha_rota_perder:
                if resultado != "derrota":
                    racha_sin_perder += 1
                else:
                    racha_rota_perder = True
            if not racha_rota_ganar:
                if resultado != "victoria":
                    racha_sin_ganar += 1
                else:
                    racha_rota_ganar = True
 
        total = victorias + empates + derrotas
        if total == 0:
            return "sin partidos con marcador válido"
 
        equipo.partidos_jugados = total
        equipo.victorias = victorias
        equipo.empates = empates
        equipo.derrotas = derrotas
        equipo.goles_favor = goles_favor
        equipo.goles_contra = goles_contra
        equipo.puntos = victorias * 3 + empates
        equipo.xg_favor_promedio = round(goles_favor / total, 2)
        equipo.xg_contra_promedio = round(goles_contra / total, 2)
 
        equipo.victorias_local = victorias_local
        equipo.victorias_visitante = victorias_visitante
 
        # Fortaleza local / rendimiento visitante en escala 0-10, real,
        # basada en el % de victorias jugando en casa vs. fuera.
        if partidos_local > 0:
            equipo.fortaleza_local = round((victorias_local / partidos_local) * 10, 1)
        if partidos_visitante > 0:
            equipo.rendimiento_visitante = round((victorias_visitante / partidos_visitante) * 10, 1)
 
        equipo.racha_sin_perder_real = racha_sin_perder if racha_rota_perder else racha_sin_perder
        equipo.racha_sin_ganar_real = racha_sin_ganar if racha_rota_ganar else racha_sin_ganar
 
        return None
 
    except Exception as e:
        return f"error: {str(e)}"
 
 
def _pais(codigo: str) -> str:
    return {
        "PD": "España", "PL": "Inglaterra", "CL": "Europa",
        "BL1": "Alemania", "SA": "Italia", "FL1": "Francia",
        "BSA": "Brasil", "CLI": "Sudamérica",
    }.get(codigo, "")
 
