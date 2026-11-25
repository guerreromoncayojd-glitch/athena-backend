"""
Validación v2 de Athena — datos de MatchHistory (Football-Data.co.uk)

Esa fuente trae por partido: goles, CÓRNERS, TIROS A PUERTA, tarjetas y CUOTAS
históricas (apertura y cierre). Con ella se hace:

 1. Poisson con ajuste Dixon-Coles (corrige 0-0 y 1-1) para el 1X2 y los goles.
 2. Fuerza ofensiva/defensiva mezclando goles con córners y tiros a puerta
    (indicadores menos ruidosos que los goles).
 3. Búsqueda de parámetros (ventana, pesos, encogimiento, rho) usando SOLO el
    70% más antiguo de los partidos, y evaluación final en el 30% más reciente
    (datos fuera de muestra, orden cronológico).
 4. Comparación contra el MERCADO (cuotas de cierre sin margen) y simulación de
    apuestas: ROI y valor frente a la cuota de cierre (CLV).

Endpoints:
  POST /api/v1/validacion2/ejecutar?temporadas=5
  GET  /api/v1/validacion2/resultado
"""
import asyncio
import csv
import io
import math
import itertools
from datetime import datetime
from collections import defaultdict

import httpx
from fastapi import APIRouter, BackgroundTasks, Query

router = APIRouter()

DIVS = {"E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga",
        "I1": "Serie A", "F1": "Ligue 1"}
URL = "https://www.football-data.co.uk/mmz4281/{temp}/{div}.csv"
WMAX = 20
MIN_PREVIOS = 5
MIN_LIGA = 100
MAXG = 7

ESTADO = {"estado": "sin ejecutar", "avance": "", "resultado": None, "error": None}


# ─── Lectura de CSV ──────────────────────────────────────────
def _f(x):
    try:
        v = float(str(x).strip())
        return v
    except Exception:
        return None


def _fecha(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            pass
    return None


def _primera(row, cols):
    """Devuelve la primera terna de cuotas completa y válida (>1.0)."""
    for c in cols:
        v = [_f(row.get(k)) for k in c]
        if all(x is not None and x > 1.0 for x in v):
            return v, c[0]
    return None, None


OPEN_1X2 = [("PSH", "PSD", "PSA"), ("B365H", "B365D", "B365A"), ("AvgH", "AvgD", "AvgA")]
CLOSE_1X2 = [("PSCH", "PSCD", "PSCA"), ("AvgCH", "AvgCD", "AvgCA"), ("B365CH", "B365CD", "B365CA")]
CLOSE_OU = [("PC>2.5", "PC<2.5"), ("AvgC>2.5", "AvgC<2.5"), ("B365C>2.5", "B365C<2.5"),
            ("P>2.5", "P<2.5"), ("Avg>2.5", "Avg<2.5")]


def parsear(texto: str, liga: str):
    out = []
    texto = texto.lstrip("﻿")
    for row in csv.DictReader(io.StringIO(texto)):
        d = _fecha(row.get("Date", "") or "")
        gl, gv = _f(row.get("FTHG")), _f(row.get("FTAG"))
        L, V = (row.get("HomeTeam") or "").strip(), (row.get("AwayTeam") or "").strip()
        if not d or gl is None or gv is None or not L or not V:
            continue
        ab, fab = _primera(row, OPEN_1X2)
        ce, fce = _primera(row, CLOSE_1X2)
        ou, _ = _primera(row, CLOSE_OU)
        out.append({
            "liga": liga, "fecha": d, "L": L, "V": V, "gl": int(gl), "gv": int(gv),
            "cl": _f(row.get("HC")), "cv": _f(row.get("AC")),
            "sl": _f(row.get("HST")), "sv": _f(row.get("AST")),
            "odds_ab": ab, "odds_ce": ce, "odds_ou": ou,
            "fuente_ab": fab, "fuente_ce": fce,
        })
    return out


# ─── Modelo Poisson / Dixon-Coles ────────────────────────────
def _pmf(lam):
    e = math.exp(-lam)
    out, t = [], e
    for k in range(MAXG + 1):
        out.append(t)
        t = t * lam / (k + 1)
    return out


def predecir(lam_l, lam_v, rho):
    """Devuelve (p1, px, p2, over15, over25) en probabilidad 0-1."""
    a, b = _pmf(lam_l), _pmf(lam_v)
    tot = 0.0
    p1 = px = p2 = o15 = o25 = 0.0
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            p = a[i] * b[j]
            if i < 2 and j < 2 and rho:
                if i == 0 and j == 0: p *= 1 - lam_l * lam_v * rho
                elif i == 0 and j == 1: p *= 1 + lam_l * rho
                elif i == 1 and j == 0: p *= 1 + lam_v * rho
                else: p *= 1 - rho
            p = max(p, 0.0)
            tot += p
            if i > j: p1 += p
            elif i == j: px += p
            else: p2 += p
            s = i + j
            if s >= 2: o15 += p
            if s >= 3: o25 += p
    return p1 / tot, px / tot, p2 / tot, o15 / tot, o25 / tot


def _tasa(suma, n, media, k):
    return (suma + k * media) / (n + k) if (n + k) > 0 else media


def _fuerza(st, med, k, wc, ws, ataque):
    """Fuerza relativa (1.0 = promedio de la liga) mezclando goles, córners y tiros."""
    i_g, i_c, i_s = (0, 2, 4) if ataque else (1, 3, 5)
    n, sg = st["n"], st["s"][i_g]
    comp = [(1.0, _tasa(sg, n, med["g"], k) / med["g"])]
    if wc > 0 and st["nc"] > 0 and med["c"]:
        comp.append((wc, _tasa(st["s"][i_c], st["nc"], med["c"], k) / med["c"]))
    if ws > 0 and st["ns"] > 0 and med["s"]:
        comp.append((ws, _tasa(st["s"][i_s], st["ns"], med["s"], k) / med["s"]))
    # el peso de goles es lo que queda; se renormaliza si falta algún indicador
    w_otros = sum(w for w, _ in comp[1:])
    comp[0] = (max(1.0 - w_otros, 0.05), comp[0][1])
    tw = sum(w for w, _ in comp)
    return sum(w * v for w, v in comp) / tw


def lambdas(feat, W, wc, ws, k):
    sl, sv, med = feat["st"][W][0], feat["st"][W][1], feat["med"]
    lam_l = med["gl"] * _fuerza(sl, med, k, wc, ws, True) * _fuerza(sv, med, k, wc, ws, False)
    lam_v = med["gv"] * _fuerza(sv, med, k, wc, ws, True) * _fuerza(sl, med, k, wc, ws, False)
    return min(max(lam_l, 0.15), 4.5), min(max(lam_v, 0.15), 4.5)


# ─── Construcción de variables sin mirar el futuro ───────────
def _stats(hist, W):
    ult = hist[-W:]
    n = len(ult)
    s = [0.0] * 6
    nc = ns = 0
    for gf, gc, cf, ca, sf, sa in ult:
        s[0] += gf; s[1] += gc
        if cf is not None and ca is not None:
            s[2] += cf; s[3] += ca; nc += 1
        if sf is not None and sa is not None:
            s[4] += sf; s[5] += sa; ns += 1
    return {"n": n, "s": s, "nc": nc, "ns": ns}


def construir(partidos, ventanas):
    feats = []
    por_liga = defaultdict(list)
    for p in partidos:
        por_liga[p["liga"]].append(p)
    for liga, lista in por_liga.items():
        lista.sort(key=lambda p: p["fecha"])
        hist = defaultdict(list)
        nl = 0
        sum_gl = sum_gv = 0.0
        sum_c = n_c = sum_s = n_s = 0.0
        cuenta = [0, 0, 0]
        o15 = o25 = 0
        for p in lista:
            L, V = p["L"], p["V"]
            real = 0 if p["gl"] > p["gv"] else (1 if p["gl"] == p["gv"] else 2)
            tot = p["gl"] + p["gv"]
            if nl >= MIN_LIGA and len(hist[L]) >= MIN_PREVIOS and len(hist[V]) >= MIN_PREVIOS:
                med = {"gl": sum_gl / nl, "gv": sum_gv / nl, "g": (sum_gl + sum_gv) / (2 * nl),
                       "c": (sum_c / n_c) if n_c else None, "s": (sum_s / n_s) if n_s else None}
                feats.append({
                    "p": p, "real": real, "tot": tot, "med": med,
                    "st": {W: (_stats(hist[L], W), _stats(hist[V], W)) for W in ventanas},
                    "base": [c / nl for c in cuenta],
                    "base_o15": o15 / nl, "base_o25": o25 / nl,
                })
            # actualizar con el resultado real (DESPUÉS de predecir)
            hist[L].append((p["gl"], p["gv"], p["cl"], p["cv"], p["sl"], p["sv"]))
            hist[V].append((p["gv"], p["gl"], p["cv"], p["cl"], p["sv"], p["sl"]))
            hist[L], hist[V] = hist[L][-WMAX:], hist[V][-WMAX:]
            nl += 1
            sum_gl += p["gl"]; sum_gv += p["gv"]
            if p["cl"] is not None and p["cv"] is not None:
                sum_c += p["cl"] + p["cv"]; n_c += 2
            if p["sl"] is not None and p["sv"] is not None:
                sum_s += p["sl"] + p["sv"]; n_s += 2
            cuenta[real] += 1
            o15 += 1 if tot > 1.5 else 0
            o25 += 1 if tot > 2.5 else 0
    feats.sort(key=lambda f: f["p"]["fecha"])
    return feats


# ─── Métricas ────────────────────────────────────────────────
def _c(p):
    return min(max(p, 0.005), 0.995)


def brier3(pr, real):
    return sum((pr[i] - (1 if i == real else 0)) ** 2 for i in range(3))


def ll3(pr, real):
    return -math.log(_c(pr[real]))


def sin_margen(odds):
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def evaluar_1x2(feats, cfg):
    W, wc, ws, k, rho = cfg
    b = l = 0.0
    for f in feats:
        ll, lv = lambdas(f, W, wc, ws, k)
        p = predecir(ll, lv, rho)[:3]
        b += brier3(p, f["real"]); l += ll3(p, f["real"])
    n = max(len(feats), 1)
    return b / n, l / n


# ─── Ejecución completa ──────────────────────────────────────
def analizar(partidos):
    feats = construir(partidos, (8, 15, 20))
    if len(feats) < 500:
        return {"error": f"Pocos partidos evaluables ({len(feats)})"}
    corte = int(len(feats) * 0.7)
    train, test = feats[:corte], feats[corte:]

    grid = [(W, wc, ws, k, rho)
            for W in (8, 15, 20)
            for wc, ws in ((0, 0), (0.3, 0), (0.5, 0), (0, 0.3), (0.3, 0.3))
            for k in (0, 3, 6)
            for rho in (0.0, -0.1, -0.2)]
    res = []
    for cfg in grid:
        b, l = evaluar_1x2(train, cfg)
        res.append((b, l, cfg))
    res.sort(key=lambda x: x[0])
    mejor = res[0][2]
    inicial = (8, 0, 0, 0, 0.0)

    def fmt(cfg):
        return {"ventana": cfg[0], "peso_corners": cfg[1], "peso_tiros_puerta": cfg[2],
                "encogimiento_k": cfg[3], "rho_dixon_coles": cfg[4]}

    # Referencias en el conjunto de prueba
    def base_1x2(fs):
        b = l = 0.0
        for f in fs:
            b += brier3(f["base"], f["real"]); l += ll3(f["base"], f["real"])
        return b / len(fs), l / len(fs)

    bt, lt = evaluar_1x2(test, mejor)
    bi, li = evaluar_1x2(test, inicial)
    bb, lb = base_1x2(test)

    # Mercado (cierre sin margen) sobre los mismos partidos de prueba con cuotas
    con_ce = [f for f in test if f["p"]["odds_ce"]]
    mercado = None
    if con_ce:
        bm = lm = bmod = lmod = 0.0
        for f in con_ce:
            pm = sin_margen(f["p"]["odds_ce"])
            bm += brier3(pm, f["real"]); lm += ll3(pm, f["real"])
            ll_, lv_ = lambdas(f, *mejor[:4])
            pmod = predecir(ll_, lv_, mejor[4])[:3]
            bmod += brier3(pmod, f["real"]); lmod += ll3(pmod, f["real"])
        n = len(con_ce)
        mercado = {"partidos_con_cuotas": n,
                   "mercado_brier": round(bm / n, 4), "mercado_logloss": round(lm / n, 4),
                   "athena_brier_mismos_partidos": round(bmod / n, 4),
                   "athena_logloss_mismos_partidos": round(lmod / n, 4)}

    # Goles (más de 1.5 y 2.5) en prueba
    def goles(fs, cfg):
        o = {"modelo": [0, 0], "base": [0, 0], "mercado_2.5": [0, 0, 0]}
        for f in fs:
            ll_, lv_ = lambdas(f, *cfg[:4])
            pr = predecir(ll_, lv_, cfg[4])
            for idx, (pm, pb, hecho) in enumerate(((pr[3], f["base_o15"], f["tot"] > 1.5),
                                                   (pr[4], f["base_o25"], f["tot"] > 2.5))):
                y = 1 if hecho else 0
                o["modelo"][idx] += (pm - y) ** 2
                o["base"][idx] += (pb - y) ** 2
            if f["p"]["odds_ou"]:
                po = sin_margen(f["p"]["odds_ou"])[0]
                y = 1 if f["tot"] > 2.5 else 0
                o["mercado_2.5"][0] += (po - y) ** 2
                o["mercado_2.5"][1] += (pr[4] - y) ** 2
                o["mercado_2.5"][2] += 1
        n = len(fs)
        r = {"mas_1.5": {"brier_modelo": round(o["modelo"][0] / n, 4), "brier_base": round(o["base"][0] / n, 4)},
             "mas_2.5": {"brier_modelo": round(o["modelo"][1] / n, 4), "brier_base": round(o["base"][1] / n, 4)}}
        if o["mercado_2.5"][2]:
            m = o["mercado_2.5"][2]
            r["mas_2.5_contra_mercado"] = {"partidos": m,
                                           "brier_mercado": round(o["mercado_2.5"][0] / m, 4),
                                           "brier_athena": round(o["mercado_2.5"][1] / m, 4)}
        return r

    # Calibración (prueba): lo que Athena dice vs lo que ocurre
    pares = []
    for f in test:
        ll_, lv_ = lambdas(f, *mejor[:4])
        pr = predecir(ll_, lv_, mejor[4])
        for nom, p_, y in (("local", pr[0], f["real"] == 0), ("empate", pr[1], f["real"] == 1),
                           ("visita", pr[2], f["real"] == 2)):
            pares.append((p_ * 100, 1 if y else 0))
    cal = []
    for lo, hi in ((0, 15), (15, 25), (25, 35), (35, 45), (45, 55), (55, 65), (65, 75), (75, 101)):
        g = [(p, y) for p, y in pares if lo <= p < hi]
        if len(g) >= 20:
            cal.append({"rango_prob_%": f"{lo}-{min(hi, 100)}", "casos": len(g),
                        "predicho_medio_%": round(sum(p for p, _ in g) / len(g), 1),
                        "real_%": round(sum(y for _, y in g) / len(g) * 100, 1)})

    # Simulación de apuestas 1X2 (prueba). Umbrales fijos, NO optimizados.
    apuestas = []
    con_odds = [f for f in test if f["p"]["odds_ab"] and f["p"]["odds_ce"]]
    margen = None
    if con_odds:
        margen = round(sum(sum(1 / o for o in f["p"]["odds_ab"]) - 1 for f in con_odds) / len(con_odds) * 100, 2)
    for thr in (0.0, 0.03, 0.05, 0.08, 0.12):
        n = 0; profit = 0.0; aciertos = 0; ev_cierre = 0.0; sq = 0.0
        for f in con_odds:
            ll_, lv_ = lambdas(f, *mejor[:4])
            pr = predecir(ll_, lv_, mejor[4])[:3]
            ab, ce = f["p"]["odds_ab"], sin_margen(f["p"]["odds_ce"])
            edges = [pr[i] * ab[i] - 1 for i in range(3)]
            i = max(range(3), key=lambda x: edges[x])
            if edges[i] > thr:
                gana = f["real"] == i
                gan = (ab[i] - 1) if gana else -1.0
                n += 1; profit += gan; sq += gan * gan
                aciertos += 1 if gana else 0
                ev_cierre += ce[i] * ab[i] - 1
        if n:
            roi = profit / n
            var = max(sq / n - roi * roi, 0)
            apuestas.append({"umbral_ventaja": thr, "apuestas": n,
                             "acierto_%": round(aciertos / n * 100, 1),
                             "ROI_%": round(roi * 100, 2),
                             "error_estandar_ROI_%": round(math.sqrt(var / n) * 100, 2),
                             "CLV_valor_vs_cierre_%": round(ev_cierre / n * 100, 2)})

    fuentes = defaultdict(int)
    for f in feats:
        fuentes[f["p"]["fuente_ab"] or "sin_cuotas"] += 1

    return {
        "partidos_evaluables": len(feats),
        "entrenamiento_70%": len(train),
        "prueba_30%_fuera_de_muestra": len(test),
        "periodo_prueba": f'{test[0]["p"]["fecha"].date()} a {test[-1]["p"]["fecha"].date()}',
        "como_leer": "Brier/logloss: más bajo es mejor. Los números de 'prueba' son los que cuentan (no se usaron para elegir parámetros).",
        "parametros_elegidos_en_entrenamiento": fmt(mejor),
        "top5_entrenamiento": [{"brier_train": round(b, 4), "logloss_train": round(l, 4), **fmt(c)} for b, l, c in res[:5]],
        "prueba_1x2": {
            "tasas_base": {"brier": round(bb, 4), "logloss": round(lb, 4)},
            "poisson_simple_(ventana8)": {"brier": round(bi, 4), "logloss": round(li, 4)},
            "modelo_optimizado_dixon_coles": {"brier": round(bt, 4), "logloss": round(lt, 4)},
        },
        "contra_el_mercado_1x2": mercado,
        "prueba_goles": goles(test, mejor),
        "calibracion_1x2_prueba": cal,
        "simulacion_apuestas_1x2_prueba": {
            "margen_medio_de_las_casas_%": margen,
            "fuente_cuotas_apertura": dict(fuentes),
            "resultados": apuestas,
            "nota": "ROI>0 solo es creíble si supera ~2 errores estándar. Sin ventaja real sobre el mercado se espera ROI negativo (≈ -margen).",
        },
    }


def _temporadas(n):
    hoy = datetime.now()
    y = hoy.year if hoy.month >= 8 else hoy.year - 1
    return [f"{(y - i) % 100:02d}{(y - i + 1) % 100:02d}" for i in range(n)]


async def _ejecutar(n_temp: int):
    ESTADO.update(estado="corriendo", avance="iniciando", resultado=None, error=None)
    partidos, avisos = [], []
    try:
        async with httpx.AsyncClient(timeout=40, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 Athena"}) as client:
            for div, nombre in DIVS.items():
                for t in _temporadas(n_temp):
                    ESTADO["avance"] = f"descargando {nombre} {t}"
                    try:
                        r = await client.get(URL.format(temp=t, div=div))
                        if r.status_code != 200:
                            avisos.append(f"{nombre} {t}: HTTP {r.status_code}")
                            continue
                        txt = r.content.decode("utf-8-sig", errors="replace")
                        partidos += parsear(txt, nombre)
                    except Exception as e:
                        avisos.append(f"{nombre} {t}: {e}")
        if not partidos:
            ESTADO.update(estado="error", error="No se descargaron partidos", resultado={"avisos": avisos})
            return
        ESTADO["avance"] = f"calculando con {len(partidos)} partidos (puede tardar unos minutos)"
        res = await asyncio.to_thread(analizar, partidos)
        res["partidos_descargados"] = len(partidos)
        res["con_corners"] = sum(1 for p in partidos if p["cl"] is not None)
        res["con_cuotas_cierre_1x2"] = sum(1 for p in partidos if p["odds_ce"])
        res["avisos"] = avisos
        ESTADO.update(estado="terminado", avance="listo", resultado=res)
    except Exception as e:
        ESTADO.update(estado="error", error=str(e))


@router.post("/ejecutar")
async def ejecutar(background: BackgroundTasks, temporadas: int = Query(5, ge=2, le=8)):
    if ESTADO["estado"] == "corriendo":
        return {"mensaje": "Ya hay una validación en curso", "avance": ESTADO["avance"]}
    background.add_task(_ejecutar, temporadas)
    return {"mensaje": "Validación v2 iniciada en segundo plano. Consulta GET /api/v1/validacion2/resultado"}


@router.get("/resultado")
async def resultado():
    return ESTADO
