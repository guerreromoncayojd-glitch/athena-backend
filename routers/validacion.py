"""
Validación (backtest) de Athena con resultados REALES.

Para cada partido ya jugado de las últimas temporadas, el sistema "viaja al
pasado": usa SOLO los 8 partidos anteriores de cada equipo (igual que la
plataforma en producción), genera su predicción y la compara con lo que
realmente pasó. Así se mide si las probabilidades son confiables.

Modelos comparados:
  - IAI actual (el motor real de producción)
  - Poisson independiente (goles esperados de cada equipo)
  - Tasas base de la liga (línea de referencia: ignora a los equipos)
Para goles (más de 1.5 y 2.5):
  - Poisson (el que usa el informe hoy)
  - Poisson con "encogimiento" hacia el promedio de la liga
  - Tasas base de la liga

Endpoints:
  POST /api/v1/validacion/ejecutar?temporadas=3   (corre en segundo plano)
  GET  /api/v1/validacion/resultado
"""
import os
import math
import asyncio
import types
from datetime import datetime, timezone
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, BackgroundTasks, Query

from engines.iai_engine import motor_iai
from routers.predictions import _equipo_a_datos_iai

router = APIRouter()

FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "")
BASE_URL = "https://api.football-data.org/v4"
LIGAS = {"PD": "La Liga", "PL": "Premier League", "BL1": "Bundesliga",
         "SA": "Serie A", "FL1": "Ligue 1"}
VENTANA = 8        # partidos previos usados (igual que producción)
MIN_PREVIOS = 5    # mínimo de partidos previos por equipo

ESTADO = {"estado": "sin ejecutar", "avance": "", "resultado": None, "error": None}


# ─── Utilidades matemáticas ──────────────────────────────────
def _pois(k, lam):
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _p1x2_poisson(lam_l, lam_v, maxg=10):
    p1 = px = p2 = 0.0
    for i in range(maxg + 1):
        pi = _pois(i, lam_l)
        for j in range(maxg + 1):
            p = pi * _pois(j, lam_v)
            if i > j: p1 += p
            elif i == j: px += p
            else: p2 += p
    t = p1 + px + p2
    return p1 / t * 100, px / t * 100, p2 / t * 100


def _p_mas(lam, linea):
    k = int(linea)
    return (1 - sum(_pois(i, lam) for i in range(k + 1))) * 100


def _clip(p):
    return min(max(p, 0.5), 99.5) / 100


# ─── Estadísticas "al momento del partido" ───────────────────
class Historial:
    def __init__(self):
        self.h = defaultdict(lambda: deque(maxlen=VENTANA))  # equipo -> (gf, gc, es_local)

    def agregar(self, eq, gf, gc, es_local):
        self.h[eq].append((gf, gc, es_local))

    def n(self, eq):
        return len(self.h[eq])

    def como_equipo(self, eq):
        """Objeto con los mismos campos que usa la plataforma (modelo Equipo)."""
        ps = list(self.h[eq])
        n = len(ps)
        v = sum(1 for gf, gc, _ in ps if gf > gc)
        e = sum(1 for gf, gc, _ in ps if gf == gc)
        gf = sum(p[0] for p in ps)
        gc = sum(p[1] for p in ps)
        loc = [p for p in ps if p[2]]
        vis = [p for p in ps if not p[2]]
        v_loc = sum(1 for p in loc if p[0] > p[1])
        v_vis = sum(1 for p in vis if p[0] > p[1])
        r_np = r_ng = 0
        rota_p = rota_g = False
        for a, b, _ in reversed(ps):
            if not rota_p:
                if a >= b: r_np += 1
                else: rota_p = True
            if not rota_g:
                if a <= b: r_ng += 1
                else: rota_g = True
        return types.SimpleNamespace(
            nombre=eq, partidos_jugados=n, victorias=v, empates=e,
            goles_favor=gf, goles_contra=gc,
            xg_favor_promedio=round(gf / n, 2), xg_contra_promedio=round(gc / n, 2),
            posesion_promedio=None, corners_promedio=None, tiros_promedio=None,
            faltas_promedio=None, tarjetas_amarillas_promedio=None,
            nivel_presion=None, fortaleza_mental=None, juego_aereo=None,
            intensidad=None, transiciones_ofensivas=None,
            fortaleza_local=round(v_loc / len(loc) * 10, 1) if loc else None,
            rendimiento_visitante=round(v_vis / len(vis) * 10, 1) if vis else None,
            victorias_local=v_loc, racha_sin_perder_real=r_np, racha_sin_ganar_real=r_ng,
            cambio_sistema_minuto=None, tendencia_goles_primeros=None,
            reaccion_desventaja=None,
        )


# ─── Acumulador de métricas ──────────────────────────────────
class Metricas:
    def __init__(self):
        self.n = 0
        self.brier = 0.0
        self.logloss = 0.0
        self.aciertos = 0
        self.p_empate = 0.0

    def add_1x2(self, probs, real):  # probs en %, real: 0=local,1=empate,2=visita
        p = [_clip(x) for x in probs]
        s = sum(p)
        p = [x / s for x in p]
        self.n += 1
        self.brier += sum((p[i] - (1 if i == real else 0)) ** 2 for i in range(3))
        self.logloss += -math.log(p[real])
        self.aciertos += 1 if p.index(max(p)) == real else 0
        self.p_empate += p[1]

    def add_bin(self, prob, real):  # real 0/1
        p = _clip(prob)
        self.n += 1
        self.brier += (p - real) ** 2
        self.logloss += -math.log(p if real else 1 - p)
        self.aciertos += real
        self.p_empate += p

    def resumen(self, es_1x2=True):
        n = max(self.n, 1)
        d = {"partidos": self.n,
             "brier": round(self.brier / n, 4),
             "logloss": round(self.logloss / n, 4)}
        if es_1x2:
            d["acierto_favorito_%"] = round(self.aciertos / n * 100, 1)
            d["empate_predicho_medio_%"] = round(self.p_empate / n * 100, 1)
        else:
            d["frecuencia_real_%"] = round(self.aciertos / n * 100, 1)
            d["prob_predicha_media_%"] = round(self.p_empate / n * 100, 1)
        return d


BINS = [(0, 60), (60, 70), (70, 80), (80, 90), (90, 101)]


def _calibracion(pares):
    """pares: lista de (prob_predicha_%, acierto 0/1)."""
    out = []
    for lo, hi in BINS:
        g = [(p, a) for p, a in pares if lo <= p < hi]
        if g:
            out.append({
                "rango_prob_%": f"{lo}-{min(hi,100)}",
                "partidos": len(g),
                "prob_predicha_media_%": round(sum(p for p, _ in g) / len(g), 1),
                "acierto_real_%": round(sum(a for _, a in g) / len(g) * 100, 1),
            })
    return out


# ─── Backtest (lógica pura, probada sin red) ─────────────────
async def backtest(partidos_por_liga: dict) -> dict:
    """partidos_por_liga: {codigo: [ {fecha, local, visita, gl, gv}, ... ]}"""
    m_iai, m_poi, m_base = Metricas(), Metricas(), Metricas()
    g = {k: {"poisson": Metricas(), "encogido": Metricas(), "base": Metricas()}
         for k in ("mas15", "mas25")}
    cal_dc, cal_goles = [], []
    total = 0

    for codigo, partidos in partidos_por_liga.items():
        partidos = sorted(partidos, key=lambda p: p["fecha"])
        hist = Historial()
        n_liga = 0
        cuenta = [0, 0, 0]   # local, empate, visita
        g15 = g25 = 0
        goles_tot = 0

        for p in partidos:
            L, V, gl, gv = p["local"], p["visita"], p["gl"], p["gv"]
            real = 0 if gl > gv else (1 if gl == gv else 2)
            tot = gl + gv

            if hist.n(L) >= MIN_PREVIOS and hist.n(V) >= MIN_PREVIOS and n_liga >= 30:
                eqL, eqV = hist.como_equipo(L), hist.como_equipo(V)

                # 1) IAI actual (motor de producción)
                dl = await _equipo_a_datos_iai(None, eqL, True, con_plantilla=False)
                dv = await _equipo_a_datos_iai(None, eqV, False, con_plantilla=False)
                r = motor_iai.analizar_partido(dl, dv)
                m_iai.add_1x2((r.victoria_local, r.empate, r.victoria_visitante), real)

                # Doble oportunidad "segura" tal como la elige el informe
                ops = {"1X": r.victoria_local + r.empate,
                       "X2": r.empate + r.victoria_visitante,
                       "12": r.victoria_local + r.victoria_visitante}
                mejor = max(ops, key=ops.get)
                ok = {"1X": real in (0, 1), "X2": real in (1, 2), "12": real in (0, 2)}[mejor]
                cal_dc.append((min(ops[mejor], 99.0), 1 if ok else 0))

                # 2) Poisson independiente
                lam_l = (eqL.xg_favor_promedio + eqV.xg_contra_promedio) / 2
                lam_v = (eqV.xg_favor_promedio + eqL.xg_contra_promedio) / 2
                lam_l, lam_v = max(lam_l, 0.1), max(lam_v, 0.1)
                m_poi.add_1x2(_p1x2_poisson(lam_l, lam_v), real)

                # 3) Tasas base de la liga
                t = max(sum(cuenta), 1)
                m_base.add_1x2([cuenta[0] / t * 100, cuenta[1] / t * 100, cuenta[2] / t * 100], real)

                # Goles
                lam = lam_l + lam_v
                prom_liga = goles_tot / max(n_liga, 1)
                lam_enc = 0.5 * lam + 0.5 * prom_liga
                for clave, linea, hecho in (("mas15", 1.5, tot > 1.5), ("mas25", 2.5, tot > 2.5)):
                    real_b = 1 if hecho else 0
                    g[clave]["poisson"].add_bin(_p_mas(lam, linea), real_b)
                    g[clave]["encogido"].add_bin(_p_mas(lam_enc, linea), real_b)
                    frec = (g15 if linea == 1.5 else g25) / max(n_liga, 1) * 100
                    g[clave]["base"].add_bin(frec, real_b)

                # Calibración del pick de goles más seguro (como el informe)
                opts = {"mas15": _p_mas(lam, 1.5), "menos35": 100 - _p_mas(lam, 3.5),
                        "mas25": _p_mas(lam, 2.5), "menos25": 100 - _p_mas(lam, 2.5)}
                mj = max(opts, key=opts.get)
                hecho = {"mas15": tot > 1.5, "menos35": tot < 3.5,
                         "mas25": tot > 2.5, "menos25": tot < 2.5}[mj]
                cal_goles.append((min(opts[mj], 99.0), 1 if hecho else 0))
                total += 1

            # Actualiza estado con el resultado real (después de predecir)
            hist.agregar(L, gl, gv, True)
            hist.agregar(V, gv, gl, False)
            cuenta[real] += 1
            n_liga += 1
            goles_tot += tot
            g15 += 1 if tot > 1.5 else 0
            g25 += 1 if tot > 2.5 else 0

    def pares_ok(pares):
        return round(sum(a for _, a in pares) / max(len(pares), 1) * 100, 1)

    return {
        "partidos_evaluados": total,
        "como_leer": (
            "Brier y logloss: MÁS BAJO es mejor. Un modelo útil debe superar a las "
            "'tasas base' (que ignoran a los equipos). Calibración: la probabilidad "
            "predicha debe parecerse al acierto real; si predice 85% y acierta 70%, "
            "está inflado."
        ),
        "resultado_1x2": {
            "IAI_actual": m_iai.resumen(),
            "Poisson_independiente": m_poi.resumen(),
            "Tasas_base_liga": m_base.resumen(),
        },
        "goles_mas_1_5": {k: v.resumen(False) for k, v in g["mas15"].items()},
        "goles_mas_2_5": {k: v.resumen(False) for k, v in g["mas25"].items()},
        "calibracion_doble_oportunidad_segura": {
            "acierto_global_%": pares_ok(cal_dc), "por_rango": _calibracion(cal_dc)},
        "calibracion_goles_pick_seguro": {
            "acierto_global_%": pares_ok(cal_goles), "por_rango": _calibracion(cal_goles)},
    }


# ─── Descarga de datos reales y ejecución ────────────────────
def _temporadas(n):
    hoy = datetime.now()
    actual = hoy.year if hoy.month >= 8 else hoy.year - 1
    return [actual - i for i in range(n)]


async def _ejecutar(temporadas: int):
    ESTADO.update(estado="corriendo", avance="iniciando", resultado=None, error=None)
    if not FOOTBALL_DATA_TOKEN:
        ESTADO.update(estado="error", error="FOOTBALL_DATA_TOKEN no configurado")
        return
    partidos = {}
    avisos = []
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            for cod in LIGAS:
                lista = []
                for temp in _temporadas(temporadas):
                    ESTADO["avance"] = f"descargando {LIGAS[cod]} {temp}"
                    r = await client.get(
                        f"{BASE_URL}/competitions/{cod}/matches",
                        headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN},
                        params={"season": temp, "status": "FINISHED"})
                    if r.status_code != 200:
                        avisos.append(f"{LIGAS[cod]} {temp}: HTTP {r.status_code}")
                    else:
                        for m in r.json().get("matches", []):
                            ft = m.get("score", {}).get("fullTime", {})
                            if ft.get("home") is None or ft.get("away") is None:
                                continue
                            lista.append({
                                "fecha": m.get("utcDate", ""),
                                "local": m["homeTeam"]["name"],
                                "visita": m["awayTeam"]["name"],
                                "gl": ft["home"], "gv": ft["away"]})
                    await asyncio.sleep(7)   # límite 10 peticiones/minuto
                if lista:
                    partidos[cod] = lista
        if not partidos:
            ESTADO.update(estado="error", error="No se descargaron partidos", resultado={"avisos": avisos})
            return
        ESTADO["avance"] = "calculando"
        res = await backtest(partidos)
        res["partidos_descargados"] = {LIGAS[c]: len(v) for c, v in partidos.items()}
        res["avisos"] = avisos
        res["nota_honesta"] = (
            "Las variables tácticas (presión, juego aéreo, etc.) se dejaron neutrales porque "
            "no existen datos reales históricos; en producción son estimadas con poco peso (5%)."
        )
        ESTADO.update(estado="terminado", avance="listo", resultado=res)
    except Exception as e:
        ESTADO.update(estado="error", error=str(e))


@router.post("/ejecutar")
async def ejecutar(background: BackgroundTasks, temporadas: int = Query(3, ge=1, le=5)):
    if ESTADO["estado"] == "corriendo":
        return {"mensaje": "Ya hay una validación en curso", "avance": ESTADO["avance"]}
    background.add_task(_ejecutar, temporadas)
    return {"mensaje": "Validación iniciada en segundo plano (tarda ~3-5 min). "
                       "Consulta GET /api/v1/validacion/resultado"}


@router.get("/resultado")
async def resultado():
    return ESTADO
