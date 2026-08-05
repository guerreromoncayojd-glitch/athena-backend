"""
Motor de plantilla y bajas — v0.0.1
Combina dos fuentes gratuitas para dar una señal REAL del estado de la
plantilla de cada equipo, sin inventar ningún dato:
 
1. football-data.org → profundidad de plantilla por línea (portero,
   defensa, medio, delantero) — detecta si a un equipo le faltan piezas
   registradas en alguna posición.
2. API-Football → lesiones y sanciones activas — penaliza según el
   número real de bajas confirmadas.
 
Si ninguna de las dos fuentes tiene datos para un equipo, devuelve None.
El motor IAI, al recibir None, EXCLUYE este componente del cálculo en
vez de rellenarlo con un número neutral, y redistribuye ese peso entre
los demás componentes (ver iai_engine.py).
"""
import os
import httpx
from datetime import datetime
from typing import Optional, Dict
from database.models import Equipo
 
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
 
FD_BASE_URL = "https://api.football-data.org/v4"
AF_BASE_URL = "https://v3.football.api-sports.io"
 
# Posiciones tal como las devuelve football-data.org, agrupadas en 4 líneas
POSICIONES_PORTERO = {"Goalkeeper"}
POSICIONES_DEFENSA = {"Centre-Back", "Left-Back", "Right-Back", "Defence"}
POSICIONES_MEDIO = {
    "Defensive Midfield", "Central Midfield", "Attacking Midfield",
    "Midfield", "Left Midfield", "Right Midfield"
}
POSICIONES_DELANTERO = {
    "Centre-Forward", "Left Winger", "Right Winger", "Offence", "Second Striker"
}
 
 
def _temporada_actual() -> int:
    """API-Football usa el año en que empieza la temporada (ej. 2026 para 2026-27)."""
    hoy = datetime.now()
    return hoy.year if hoy.month >= 8 else hoy.year - 1
 
 
async def _obtener_profundidad_plantilla(equipo: Equipo) -> Optional[Dict[str, int]]:
    """Cuenta jugadores registrados por línea, usando la plantilla de football-data.org."""
    if not equipo.football_data_team_id or not FOOTBALL_DATA_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{FD_BASE_URL}/teams/{equipo.football_data_team_id}",
                headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN}
            )
            if r.status_code != 200:
                return None
            squad = r.json().get("squad", [])
            if not squad:
                return None
 
            conteo = {"portero": 0, "defensa": 0, "medio": 0, "delantero": 0}
            for j in squad:
                pos = j.get("position", "")
                if pos in POSICIONES_PORTERO:
                    conteo["portero"] += 1
                elif pos in POSICIONES_DEFENSA:
                    conteo["defensa"] += 1
                elif pos in POSICIONES_MEDIO:
                    conteo["medio"] += 1
                elif pos in POSICIONES_DELANTERO:
                    conteo["delantero"] += 1
            return conteo
    except Exception:
        return None
 
 
async def _obtener_bajas(equipo: Equipo) -> Optional[int]:
    """Cuenta lesiones/sanciones activas del equipo, usando API-Football."""
    if not equipo.api_football_id or not API_FOOTBALL_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{AF_BASE_URL}/injuries",
                headers={"x-apisports-key": API_FOOTBALL_KEY},
                params={"team": equipo.api_football_id, "season": _temporada_actual()}
            )
            if r.status_code != 200:
                return None
            return len(r.json().get("response", []))
    except Exception:
        return None
 
 
async def calcular_score_jugadores(equipo: Equipo) -> Optional[float]:
    """
    Calcula el score de plantilla del equipo (0-100, 50=punto de partida).
 
    - Resta puntos si faltan jugadores registrados en alguna línea
      (portero, defensa, medio, delantero) respecto a un mínimo razonable.
    - Resta puntos por cada baja real (lesión/sanción) confirmada.
 
    Devuelve None si NINGUNA de las dos fuentes tiene datos para este
    equipo — en ese caso no se inventa un número.
    """
    plantilla = await _obtener_profundidad_plantilla(equipo)
    bajas = await _obtener_bajas(equipo)
 
    if plantilla is None and bajas is None:
        return None
 
    score = 50.0
 
    if plantilla is not None:
        minimos = {"portero": 2, "defensa": 5, "medio": 5, "delantero": 3}
        for linea, minimo in minimos.items():
            faltante = max(0, minimo - plantilla.get(linea, 0))
            score -= faltante * 2
 
    if bajas is not None:
        score -= min(bajas * 3, 24)  # tope para no exagerar el efecto de muchas bajas
 
    return round(max(10, min(90, score)), 1)
