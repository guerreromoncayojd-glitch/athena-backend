"""
Validación v2 de Athena — datos de MatchHistory (incluye decaimiento temporal, 2.ª división y segmentación por cuotas) (Football-Data.co.uk)

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
        "I1": "Serie A", "F1": "Ligue 1",
        "E1": "Championship", "SP2": "Segunda España", "D2": "2. Bundesliga",
        "I2": "Serie B", "F2": "Ligue 2"}
SEGUNDAS = {"Championship", "Segunda España", "2. Bundesliga", "Serie B", "Ligue 2"}


def grupo_de(liga):
    return "segunda" if liga in SEGUNDAS else "primera"
URL = "https://www.football-data.co.uk/mmz4281/{temp}/{div}.csv"
WMAX = 30
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
OPEN_OU = [("P>2.5", "P<2.5"), ("B365>2.5", "B365<2.5"), ("Avg>2.5", "Avg<2.5")]
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
        ou_ab, _ = _primera(row, OPEN_OU)
        out.append({
            "liga": liga, "fecha": d, "L": L, "V": V, "gl": int(gl), "gv": int(gv),
            "cl": _f(row.get("HC")), "cv": _f(row.get("AC")),
            "sl": _f(row.get("HST")), "sv": _f(row.get("AST")),
            "odds_ab": ab, "odds_ce": ce, "odds_ou": ou, "odds_ou_ab": ou_ab,
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


def lambdas(feat, W, hl, wc, ws, k):
    sl, sv, med = feat["st"][(W, hl)][0], feat["st"][(W, hl)][1], feat["med"]
    lam_l = med["gl"] * _fuerza(sl, med, k, wc, ws, True) * _fuerza(sv, med, k, wc, ws, False)
    lam_v = med["gv"] * _fuerza(sv, med, k, wc, ws, True) * _fuerza(sl, med, k, wc, ws, False)
    return min(max(lam_l, 0.15), 4.5), min(max(lam_v, 0.15), 4.5)


# ─── Construcción de variables sin mirar el futuro ───────────
def _stats(hist, W, hl):
    """Resumen de los últimos W partidos. Con hl (vida media en partidos) el más
    reciente pesa 1 y cada 'hl' partidos hacia atrás el peso se reduce a la mitad."""
    ult = hist[-W:]
    m = len(ult)
    s = [0.0] * 6
    n = nc = ns = 0.0
    for idx, (gf, gc, cf, ca, sf, sa) in enumerate(ult):
        w = 0.5 ** ((m - 1 - idx) / hl) if hl else 1.0
        n += w
        s[0] += w * gf; s[1] += w * gc
        if cf is not None and ca is not None:
            s[2] += w * cf; s[3] += w * ca; nc += w
        if sf is not None and sa is not None:
            s[4] += w * sf; s[5] += w * sa; ns += w
    return {"n": n, "s": s, "nc": nc, "ns": ns}


def construir(partidos, variantes):
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
                    "st": {(W, hl): (_stats(hist[L], W, hl), _stats(hist[V], W, hl)) for (W, hl) in variantes},
                    "grupo": grupo_de(liga),
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
    W, hl, wc, ws, k, rho = cfg
    b = l = 0.0
    for f in feats:
        ll, lv = lambdas(f, W, hl, wc, ws, k)
        p = predecir(ll, lv, rho)[:3]
        b += brier3(p, f["real"]); l += ll3(p, f["real"])
    n = max(len(feats), 1)
    return b / n, l / n



# ─── Calibración (se aprende SOLO con el 80% antiguo) ────────
def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def ajustar_platt(ps, ys):
    """p' = sigmoide(a + s*logit(p)); 'a' se calcula para que la media coincida con la
    frecuencia real y 's' se elige por Brier. s>1 estira, s<1 comprime."""
    media = sum(ys) / len(ys)
    lg = [_logit(p) for p in ps]
    mejor = None
    for s in [x / 10 for x in range(4, 17)]:
        lo, hi = -5.0, 5.0
        for _ in range(35):
            a = (lo + hi) / 2
            if sum(_sig(a + s * x) for x in lg) / len(lg) < media:
                lo = a
            else:
                hi = a
        b = sum((_sig(a + s * x) - y) ** 2 for x, y in zip(lg, ys)) / len(ys)
        if mejor is None or b < mejor[0]:
            mejor = (b, a, s)
    return mejor[1], mejor[2]


def aplicar_platt(p, a, s):
    return _sig(a + s * _logit(p))


def estirar(pr3, g):
    q = [max(x, 1e-6) ** g for x in pr3]
    t = sum(q)
    return [x / t for x in q]


# ─── Pruebas adicionales ─────────────────────────────────────
def _temporada_de(fecha):
    y = fecha.year if fecha.month >= 8 else fecha.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def sesgo_favorito_cuota_larga(feats):
    """ROI de apostar A CIEGAS a todos los resultados de cada banda de cuota (sin modelo).
    Sirve para ver si el propio mercado tiene un sesgo (favoritos infravalorados,
    cuotas largas sobrevaloradas) y si se repite en todas las temporadas."""
    def resumen(casos):
        n = len(casos)
        if n < 30:
            return None
        roi = sum(c["g"] for c in casos) / n
        var = max(sum(c["g"] ** 2 for c in casos) / n - roi * roi, 0)
        return {"casos": n, "cuota_media": round(sum(c["odd"] for c in casos) / n, 2),
                "prob_mercado_cierre_%": round(sum(c["pc"] for c in casos) / n * 100, 1),
                "frecuencia_real_%": round(sum(c["win"] for c in casos) / n * 100, 1),
                "ROI_ciego_%": round(roi * 100, 2), "error_estandar_%": round(math.sqrt(var / n) * 100, 2)}

    todos = []
    for f in feats:
        p = f["p"]
        if not (p["odds_ab"] and p["odds_ce"]):
            continue
        ce = sin_margen(p["odds_ce"])
        for i in range(3):
            odd = p["odds_ab"][i]
            win = 1 if f["real"] == i else 0
            todos.append({"odd": odd, "pc": ce[i], "win": win, "g": (odd - 1) if win else -1.0,
                          "temp": _temporada_de(p["fecha"]), "grupo": f["grupo"]})
    out = {"global": []}
    for nom, lo, hi in BANDAS:
        r = resumen([c for c in todos if lo <= c["odd"] < hi])
        if r:
            out["global"].append({"cuota": nom, **r})
    for nom, lo, hi in (BANDAS[0], BANDAS[3]):
        filas = []
        for t in sorted({c["temp"] for c in todos}):
            r = resumen([c for c in todos if lo <= c["odd"] < hi and c["temp"] == t])
            if r:
                filas.append({"temporada": t, **r})
        out[f"por_temporada_{nom}"] = filas
        for g in ("primera", "segunda"):
            r = resumen([c for c in todos if lo <= c["odd"] < hi and c["grupo"] == g])
            if r:
                out.setdefault(f"por_grupo_{nom}", {})[g] = r
    return out


def mezcla_con_mercado(p_sel, p_test):
    """¿Athena aporta información que el mercado no tiene? Se mezcla w*Athena + (1-w)*mercado,
    se elige w con el 80% antiguo y se mide en la prueba sellada."""
    def datos(preds):
        return [(pr[:3], sin_margen(f["p"]["odds_ce"]), f["real"]) for f, pr in preds if f["p"]["odds_ce"]]
    ds, dt = datos(p_sel), datos(p_test)
    if not ds or not dt:
        return None
    mejor = None
    for w in [x / 10 for x in range(0, 11)]:
        b = sum(brier3([w * a[i] + (1 - w) * m[i] for i in range(3)], r) for a, m, r in ds) / len(ds)
        if mejor is None or b < mejor[0]:
            mejor = (b, w)
    w = mejor[1]
    f = lambda w_: round(sum(brier3([w_ * a[i] + (1 - w_) * m[i] for i in range(3)], r) for a, m, r in dt) / len(dt), 4)
    return {"peso_athena_elegido_en_seleccion": w,
            "brier_prueba_solo_mercado": f(0.0), "brier_prueba_mezcla": f(w), "brier_prueba_solo_athena": f(1.0),
            "lectura": "Si la mezcla no baja claramente del Brier del mercado, Athena no aporta información adicional."}

# ─── Ejecución completa ──────────────────────────────────────
BANDAS = [("<1.70", 1.0, 1.70), ("1.70-3.30", 1.70, 3.30), ("3.30-4.00", 3.30, 4.00), (">4.00", 4.00, 99.0)]
RANGOS = [("todas", 1.0, 99.0), ("<=4.00", 1.0, 4.00), ("1.70-3.30", 1.70, 3.30),
          ("<1.70", 1.0, 1.70), (">4.00", 4.00, 99.0)]
UMBRALES = (0.0, 0.03, 0.05, 0.08)


def _opciones(f, pr, mercado):
    """Lista de (prob_modelo, cuota_apertura, prob_cierre_sin_margen, gana) por resultado."""
    p = f["p"]
    if mercado == "1X2":
        if not (p["odds_ab"] and p["odds_ce"]):
            return []
        ce = sin_margen(p["odds_ce"])
        return [(pr[i], p["odds_ab"][i], ce[i], f["real"] == i) for i in range(3)]
    if not (p["odds_ou_ab"] and p["odds_ou"]):
        return []
    ce = sin_margen(p["odds_ou"])
    over = f["tot"] > 2.5
    return [(pr[4], p["odds_ou_ab"][0], ce[0], over), (1 - pr[4], p["odds_ou_ab"][1], ce[1], not over)]


def simular(preds, mercado, grupo, lo, hi, thr):
    n = aciertos = 0
    profit = sq = ev = 0.0
    for f, pr in preds:
        if grupo != "todas" and f["grupo"] != grupo:
            continue
        ops = _opciones(f, pr, mercado)
        if not ops:
            continue
        edges = [o[0] * o[1] - 1 for o in ops]
        i = max(range(len(ops)), key=lambda x: edges[x])
        pm, odd, pc, gana = ops[i]
        if edges[i] > thr and lo <= odd < hi:
            g = (odd - 1) if gana else -1.0
            n += 1; profit += g; sq += g * g; aciertos += 1 if gana else 0
            ev += pc * odd - 1
    if not n:
        return None
    roi = profit / n
    se = math.sqrt(max(sq / n - roi * roi, 0) / n)
    return {"apuestas": n, "acierto_%": round(aciertos / n * 100, 1), "ROI_%": round(roi * 100, 2),
            "error_estandar_%": round(se * 100, 2), "CLV_%": round(ev / n * 100, 2),
            "ROI_menos_2_error_%": round((roi - 2 * se) * 100, 2)}


def analizar(partidos):
    variantes = [(W, hl) for W in (20, 30) for hl in (0, 5, 8, 12)]
    feats = construir(partidos, variantes)
    if len(feats) < 1000:
        return {"error": f"Pocos partidos evaluables ({len(feats)})"}
    c80 = int(len(feats) * 0.8)
    sel, test = feats[:c80], feats[c80:]          # selección (80% antiguo) / prueba sellada (20% reciente)
    sel_grid = sel[::2]

    # 1) Mejor configuración para el 1X2
    grid = [(W, hl, wc, ws, k, rho)
            for (W, hl) in variantes
            for wc, ws in ((0, 0), (0.3, 0), (0.5, 0), (0, 0.3), (0.3, 0.3))
            for k in (0, 3, 6)
            for rho in (0.0, -0.1, -0.2)]
    res = sorted(((*evaluar_1x2(sel_grid, cfg), cfg) for cfg in grid), key=lambda x: x[0])
    mejor = res[0][2]
    mejor_sin = next(r for r in res if r[2][1] == 0)[2]
    inicial = (20, 0, 0, 0, 0, 0.0)

    # 2) Estirar el 1X2 (corrige que el modelo comprime las probabilidades)
    raw_sel = []
    for f in sel:
        ll, lv = lambdas(f, *mejor[:5])
        raw_sel.append(predecir(ll, lv, mejor[5])[:3])
    gamma, mejor_b = 1.0, None
    for g in [x / 20 for x in range(14, 33)]:       # 0.70 a 1.60
        b = sum(brier3(estirar(p, g), f["real"]) for p, f in zip(raw_sel, sel)) / len(sel)
        if mejor_b is None or b < mejor_b:
            gamma, mejor_b = g, b

    # 3) Goles: configuración propia y calibración propia
    grid_g = [(W, hl, wc, ws, k, 0.0)
              for (W, hl) in variantes
              for wc, ws in ((0, 0), (0.3, 0), (0.5, 0), (0, 0.3), (0.3, 0.3))
              for k in (0, 3, 6, 10)]

    def brier_goles(fs, cfg):
        t = 0.0
        for f in fs:
            ll, lv = lambdas(f, *cfg[:5])
            p = predecir(ll, lv, 0.0)
            t += (p[3] - (1 if f["tot"] > 1.5 else 0)) ** 2 + (p[4] - (1 if f["tot"] > 2.5 else 0)) ** 2
        return t / len(fs)

    mejor_g = min(grid_g, key=lambda c: brier_goles(sel_grid, c))
    raw_g = []
    for f in sel:
        ll, lv = lambdas(f, *mejor_g[:5])
        p = predecir(ll, lv, 0.0)
        raw_g.append((p[3], p[4]))
    pl15 = ajustar_platt([p[0] for p in raw_g], [1 if f["tot"] > 1.5 else 0 for f in sel])
    pl25 = ajustar_platt([p[1] for p in raw_g], [1 if f["tot"] > 2.5 else 0 for f in sel])

    def fmt(cfg):
        return {"ventana": cfg[0], "vida_media_partidos": cfg[1] or "sin decaimiento",
                "peso_corners": cfg[2], "peso_tiros_puerta": cfg[3],
                "encogimiento_k": cfg[4], "rho_dixon_coles": cfg[5]}

    def armar(fs, calibrar=True):
        out = []
        for f in fs:
            ll, lv = lambdas(f, *mejor[:5])
            p = predecir(ll, lv, mejor[5])
            q = estirar(p[:3], gamma) if calibrar else list(p[:3])
            ll2, lv2 = lambdas(f, *mejor_g[:5])
            pg = predecir(ll2, lv2, 0.0)
            o15 = aplicar_platt(pg[3], *pl15) if calibrar else pg[3]
            o25 = aplicar_platt(pg[4], *pl25) if calibrar else pg[4]
            out.append((f, (q[0], q[1], q[2], o15, o25)))
        return out

    def metricas(preds):
        b = l = 0.0
        for f, pr in preds:
            b += brier3(pr[:3], f["real"]); l += ll3(pr[:3], f["real"])
        n = max(len(preds), 1)
        return {"brier": round(b / n, 4), "logloss": round(l / n, 4)}

    p_test, p_test_raw, p_sel = armar(test), armar(test, False), armar(sel)

    base_t = {"brier": round(sum(brier3(f["base"], f["real"]) for f in test) / len(test), 4),
              "logloss": round(sum(ll3(f["base"], f["real"]) for f in test) / len(test), 4)}
    ini_t = []
    for f in test:
        ll, lv = lambdas(f, *inicial[:5])
        ini_t.append((f, predecir(ll, lv, inicial[5])))

    # Contra el mercado (mismos partidos de prueba)
    con_ce = [(f, pr) for f, pr in p_test if f["p"]["odds_ce"]]
    mercado = None
    if con_ce:
        raw_map = {id(f): pr for f, pr in p_test_raw}
        sd = {}
        for f, _ in con_ce:
            ll, lv = lambdas(f, *mejor_sin[:5])
            sd[id(f)] = predecir(ll, lv, mejor_sin[5])[:3]
        bm = bmod = braw = bsd = lm = lmod = 0.0
        for f, pr in con_ce:
            pm = sin_margen(f["p"]["odds_ce"])
            bm += brier3(pm, f["real"]); lm += ll3(pm, f["real"])
            bmod += brier3(pr[:3], f["real"]); lmod += ll3(pr[:3], f["real"])
            braw += brier3(raw_map[id(f)][:3], f["real"])
            bsd += brier3(sd[id(f)], f["real"])
        n = len(con_ce)
        mercado = {"partidos_con_cuotas": n,
                   "mercado_brier": round(bm / n, 4), "mercado_logloss": round(lm / n, 4),
                   "athena_calibrado_brier": round(bmod / n, 4), "athena_calibrado_logloss": round(lmod / n, 4),
                   "athena_sin_calibrar_brier": round(braw / n, 4),
                   "athena_sin_decaimiento_brier_(sin_calibrar)": round(bsd / n, 4),
                   "brecha_vs_mercado_brier": round((bmod - bm) / n, 4)}
        for g in ("primera", "segunda"):
            sub = [(f, pr) for f, pr in con_ce if f["grupo"] == g]
            if len(sub) >= 50:
                mercado[f"{g}_mercado_vs_athena_brier"] = {
                    "partidos": len(sub),
                    "mercado": round(sum(brier3(sin_margen(f["p"]["odds_ce"]), f["real"]) for f, _ in sub) / len(sub), 4),
                    "athena": round(sum(brier3(pr[:3], f["real"]) for f, pr in sub) / len(sub), 4)}

    # Calibración 1X2 en prueba, antes y después
    def tabla_cal(preds):
        pares = []
        for f, pr in preds:
            for i in range(3):
                pares.append((pr[i] * 100, 1 if f["real"] == i else 0))
        out = []
        for lo, hi in ((0, 15), (15, 25), (25, 35), (35, 45), (45, 55), (55, 65), (65, 75), (75, 101)):
            g = [(p, y) for p, y in pares if lo <= p < hi]
            if len(g) >= 20:
                out.append({"rango_%": f"{lo}-{min(hi, 100)}", "casos": len(g),
                            "predicho_%": round(sum(p for p, _ in g) / len(g), 1),
                            "real_%": round(sum(y for _, y in g) / len(g) * 100, 1)})
        return out

    # Dónde se separa del mercado, por banda de cuota
    bandas = []
    for nom, lo, hi in BANDAS:
        casos = []
        for f, pr in con_ce:
            if not f["p"]["odds_ab"]:
                continue
            ce = sin_margen(f["p"]["odds_ce"])
            for i in range(3):
                if lo <= f["p"]["odds_ab"][i] < hi:
                    casos.append((pr[i], ce[i], 1 if f["real"] == i else 0))
        if len(casos) >= 30:
            bandas.append({"cuota": nom, "casos": len(casos),
                           "athena_prob_media_%": round(sum(c[0] for c in casos) / len(casos) * 100, 1),
                           "mercado_prob_media_%": round(sum(c[1] for c in casos) / len(casos) * 100, 1),
                           "frecuencia_real_%": round(sum(c[2] for c in casos) / len(casos) * 100, 1)})

    # Goles en prueba: modelo calibrado, sin calibrar, tasa base y mercado
    acc = {"m15": 0.0, "r15": 0.0, "b15": 0.0, "m25": 0.0, "r25": 0.0, "b25": 0.0, "mm": 0.0, "am": 0.0, "nm": 0}
    raw_map = {id(f): pr for f, pr in p_test_raw}
    for f, pr in p_test:
        y15, y25 = 1 if f["tot"] > 1.5 else 0, 1 if f["tot"] > 2.5 else 0
        rr = raw_map[id(f)]
        acc["m15"] += (pr[3] - y15) ** 2; acc["r15"] += (rr[3] - y15) ** 2; acc["b15"] += (f["base_o15"] - y15) ** 2
        acc["m25"] += (pr[4] - y25) ** 2; acc["r25"] += (rr[4] - y25) ** 2; acc["b25"] += (f["base_o25"] - y25) ** 2
        if f["p"]["odds_ou"]:
            acc["mm"] += (sin_margen(f["p"]["odds_ou"])[0] - y25) ** 2
            acc["am"] += (pr[4] - y25) ** 2; acc["nm"] += 1
    n = len(p_test)
    goles = {"mas_1.5": {"brier_calibrado": round(acc["m15"] / n, 4), "brier_sin_calibrar": round(acc["r15"] / n, 4),
                         "brier_base_liga": round(acc["b15"] / n, 4)},
             "mas_2.5": {"brier_calibrado": round(acc["m25"] / n, 4), "brier_sin_calibrar": round(acc["r25"] / n, 4),
                         "brier_base_liga": round(acc["b25"] / n, 4)}}
    if acc["nm"]:
        goles["mas_2.5_contra_mercado"] = {"partidos": acc["nm"],
                                           "brier_mercado": round(acc["mm"] / acc["nm"], 4),
                                           "brier_athena": round(acc["am"] / acc["nm"], 4)}

    # Reglas de apuesta: se eligen con el 80% antiguo y se reportan en el 20% sellado
    reglas = []
    for mk in ("1X2", "O/U 2.5"):
        for gr in ("todas", "primera", "segunda"):
            for rn, lo, hi in RANGOS:
                for thr in UMBRALES:
                    rs = simular(p_sel, mk, gr, lo, hi, thr)
                    if rs and rs["apuestas"] >= 150:
                        reglas.append((rs["ROI_menos_2_error_%"], {"mercado": mk, "ligas": gr, "cuotas": rn, "umbral": thr}, lo, hi, rs))
    reglas.sort(key=lambda r: r[0], reverse=True)
    top = []
    for _, regla, lo, hi, rs in reglas[:5]:
        rt = simular(p_test, regla["mercado"], regla["ligas"], lo, hi, regla["umbral"])
        top.append({"regla": regla, "en_seleccion_80%": rs, "en_prueba_sellada_20%": rt})

    tabla = []
    for mk in ("1X2", "O/U 2.5"):
        for gr in ("todas", "primera", "segunda"):
            for rn, lo, hi in RANGOS:
                for thr in (0.0, 0.05):
                    rt = simular(p_test, mk, gr, lo, hi, thr)
                    if rt and rt["apuestas"] >= 30:
                        tabla.append({"mercado": mk, "ligas": gr, "cuotas": rn, "umbral": thr, **rt})

    propuesta = {f"umbral_{t}": simular(p_test, "1X2", "todas", 1.70, 3.30, t) for t in UMBRALES}

    return {
        "partidos_evaluables": len(feats),
        "seleccion_80%": len(sel), "prueba_sellada_20%": len(test),
        "periodo_prueba": f'{test[0]["p"]["fecha"].date()} a {test[-1]["p"]["fecha"].date()}',
        "como_leer": ("Brier/logloss: más bajo es mejor. Parámetros, calibración y reglas se aprendieron SOLO con el "
                      "80% más antiguo; el 20% más reciente no se usó para decidir nada."),
        "parametros_1x2": fmt(mejor),
        "estiramiento_1x2_gamma": gamma,
        "parametros_goles": fmt(mejor_g),
        "calibracion_goles_(a,s)": {"mas_1.5": [round(x, 3) for x in pl15], "mas_2.5": [round(x, 3) for x in pl25]},
        "mejor_sin_decaimiento": fmt(mejor_sin),
        "top5_en_seleccion": [{"brier_sel": round(b, 4), "logloss_sel": round(l, 4), **fmt(c)} for b, l, c in res[:5]],
        "prueba_1x2": {
            "tasas_base": base_t,
            "poisson_simple_(ventana20)": metricas(ini_t),
            "modelo_sin_calibrar": metricas(p_test_raw),
            "modelo_calibrado": metricas(p_test),
        },
        "contra_el_mercado_1x2": mercado,
        "calibracion_1x2_prueba_sin_calibrar": tabla_cal(p_test_raw),
        "calibracion_1x2_prueba_calibrado": tabla_cal(p_test),
        "donde_se_separa_del_mercado_por_cuota": bandas,
        "prueba_goles": goles,
        "apuestas_regla_propuesta_1x2_cuotas_1.70-3.30": propuesta,
        "mejores_reglas_elegidas_en_seleccion": top,
        "tabla_segmentacion_prueba": tabla,
        "mezcla_athena_mercado": mezcla_con_mercado(p_sel, p_test),
        "sesgo_favorito_cuota_larga_todas_las_temporadas": sesgo_favorito_cuota_larga(feats),
        "aviso_pruebas_multiples": (
            f"Se evaluaron {len(reglas)} reglas candidatas. Con tantas, alguna sale positiva solo por azar. "
            "Una regla solo es creíble si en la prueba sellada mantiene ROI > 2 errores estándar Y CLV positivo."),
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
        res["con_cuotas_ou_2.5"] = sum(1 for p in partidos if p["odds_ou"] and p["odds_ou_ab"])
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
