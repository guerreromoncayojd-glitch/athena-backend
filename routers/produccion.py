"""
Athena en producción (v MH-1.0) — modelo validado con 16.499 partidos reales.

Fuente: MatchHistory (Football-Data.co.uk): resultados, córners, tiros a puerta y cuotas
de las 5 primeras y 5 segundas divisiones europeas, más los próximos partidos con cuotas.

Modelo (parámetros elegidos en el backtest con el 80% antiguo y medidos en el 20% sellado):
  1X2   : ventana 30, vida media 12 partidos, córners 0.3 + tiros a puerta 0.3,
          Dixon-Coles rho=-0.1, estiramiento gamma=1.05
  Goles : ventana 30, córners 0.3 + tiros 0.3, encogimiento k=10, calibración logística

IMPORTANTE (resultado del backtest): Athena NO supera a las cuotas del mercado
(Brier 0.6072 vs 0.5950). Sirve como probabilidad calibrada para filtrar partidos,
no como señal de apuesta con ventaja.

Endpoints (prefijo /api/v1/produccion):
  GET  /jornada?dias=7            informe con probabilidad de Athena y del mercado
  POST /actualizar                 descarga datos y recalcula (también corre solo cada 6 h)
  GET  /registro/resumen           desempeño real acumulado del modelo en producción
  GET  /registro/picks             últimos picks registrados
  POST /registro/resolver          fuerza la búsqueda de resultados de picks pendientes
"""
import asyncio
import csv
import io
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from database.connection import SessionLocal, get_db
from database.registro import RegistroPick
from routers.validacion2 import (
    DIVS, URL, parsear, _stats, lambdas, predecir, estirar, aplicar_platt,
    sin_margen, _fuerza, _primera, OPEN_1X2, OPEN_OU, _fecha, _temporadas,
)

router = APIRouter()

VERSION = "MH-1.0"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
CFG_1X2 = (30, 12, 0.3, 0.3, 0, -0.1)       # ventana, vida media, peso córners, peso tiros, k, rho
GAMMA = 1.05
CFG_GOLES = (30, 0, 0.3, 0.3, 10, 0.0)
PLATT15 = (0.143, 0.9)
PLATT25 = (0.029, 0.8)
WMAX = 30
MIN_PREVIOS = 5
MIN_LIGA = 100
TEMPORADAS_DESCARGA = 3
LIGAS_MH = sorted(set(DIVS.values()))

CACHE = {"estado": "sin datos", "actualizado": None, "items": [], "error": None,
         "avisos": [], "partidos_historicos": 0, "version": VERSION}
_LOCK = asyncio.Lock()


# ─── Hora: el fixtures.csv viene en hora del Reino Unido ─────
def _ultimo_domingo(y, m):
    d = datetime(y, m, 31)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def uk_a_utc(dt):
    ini = _ultimo_domingo(dt.year, 3).replace(hour=1)
    fin = _ultimo_domingo(dt.year, 10).replace(hour=1)
    verano = ini <= dt < fin
    return (dt - timedelta(hours=1 if verano else 0)).replace(tzinfo=timezone.utc)


# ─── Lectura de próximos partidos ────────────────────────────
def parsear_fixtures(texto):
    out = []
    for row in csv.DictReader(io.StringIO(texto.lstrip("﻿"))):
        div = (row.get("Div") or "").strip()
        if div not in DIVS:
            continue
        d = _fecha(row.get("Date", "") or "")
        L, V = (row.get("HomeTeam") or "").strip(), (row.get("AwayTeam") or "").strip()
        if not d or not L or not V:
            continue
        try:
            hh, mm = [int(x) for x in (row.get("Time") or "12:00").strip().split(":")]
        except Exception:
            hh, mm = 12, 0
        ab, fuente = _primera(row, OPEN_1X2)
        ou, _ = _primera(row, OPEN_OU)
        out.append({"liga": DIVS[div], "L": L, "V": V, "fecha_local": d,
                    "fecha_utc": uk_a_utc(d.replace(hour=hh, minute=mm)),
                    "odds": ab, "fuente_cuotas": fuente, "odds_ou": ou})
    return out


# ─── Estado del modelo con todo el historial ─────────────────
def construir_estado(partidos):
    estado = {}
    por_liga = defaultdict(list)
    for p in partidos:
        por_liga[p["liga"]].append(p)
    for liga, lista in por_liga.items():
        lista.sort(key=lambda p: p["fecha"])
        hist = defaultdict(list)
        s = {"n": 0, "gl": 0.0, "gv": 0.0, "c": 0.0, "nc": 0, "s": 0.0, "ns": 0}
        for p in lista:
            L, V = p["L"], p["V"]
            hist[L].append((p["gl"], p["gv"], p["cl"], p["cv"], p["sl"], p["sv"]))
            hist[V].append((p["gv"], p["gl"], p["cv"], p["cl"], p["sv"], p["sl"]))
            hist[L], hist[V] = hist[L][-WMAX:], hist[V][-WMAX:]
            s["n"] += 1; s["gl"] += p["gl"]; s["gv"] += p["gv"]
            if p["cl"] is not None and p["cv"] is not None:
                s["c"] += p["cl"] + p["cv"]; s["nc"] += 2
            if p["sl"] is not None and p["sv"] is not None:
                s["s"] += p["sl"] + p["sv"]; s["ns"] += 2
        estado[liga] = {"hist": hist, "s": s}
    return estado


def _pois(k, lam):
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def predecir_partido(estado, liga, L, V):
    e = estado.get(liga)
    if not e or e["s"]["n"] < MIN_LIGA:
        return None
    hist, s = e["hist"], e["s"]
    if len(hist.get(L, [])) < MIN_PREVIOS or len(hist.get(V, [])) < MIN_PREVIOS:
        return None
    med = {"gl": s["gl"] / s["n"], "gv": s["gv"] / s["n"], "g": (s["gl"] + s["gv"]) / (2 * s["n"]),
           "c": s["c"] / s["nc"] if s["nc"] else None, "s": s["s"] / s["ns"] if s["ns"] else None}
    st = {}
    for W, hl in {(CFG_1X2[0], CFG_1X2[1]), (CFG_GOLES[0], CFG_GOLES[1])}:
        st[(W, hl)] = (_stats(hist[L], W, hl), _stats(hist[V], W, hl))
    feat = {"st": st, "med": med}

    ll, lv = lambdas(feat, *CFG_1X2[:5])
    q = estirar(predecir(ll, lv, CFG_1X2[5])[:3], GAMMA)
    ll2, lv2 = lambdas(feat, *CFG_GOLES[:5])
    pg = predecir(ll2, lv2, CFG_GOLES[5])
    o15, o25 = aplicar_platt(pg[3], *PLATT15), aplicar_platt(pg[4], *PLATT25)
    lam = ll2 + lv2
    menos35 = sum(_pois(k, lam) for k in range(4))          # sin calibrar

    sl, sv = st[(CFG_1X2[0], CFG_1X2[1])]
    att_l = _fuerza(sl, med, CFG_1X2[4], CFG_1X2[2], CFG_1X2[3], True)
    def_l = _fuerza(sl, med, CFG_1X2[4], CFG_1X2[2], CFG_1X2[3], False)
    att_v = _fuerza(sv, med, CFG_1X2[4], CFG_1X2[2], CFG_1X2[3], True)
    def_v = _fuerza(sv, med, CFG_1X2[4], CFG_1X2[2], CFG_1X2[3], False)
    return {"p": q, "o15": o15, "o25": o25, "menos35": menos35, "lam": lam,
            "perfil": (perfil(att_l, def_l), perfil(att_v, def_v)),
            "previos": (len(hist[L]), len(hist[V]))}


def perfil(att, deff):
    """att/def relativos al promedio de la liga (1.0 = promedio; defensa alta = recibe más)."""
    if att >= 1.15 and deff <= 0.9:
        return "dominante (ataca bien y defiende bien)"
    if att >= 1.15 and deff > 1.1:
        return "ofensivo y frágil atrás"
    if att >= 1.15:
        return "ofensivo"
    if deff <= 0.85 and att < 0.95:
        return "defensivo (cierra y marca poco)"
    if deff <= 0.85:
        return "defensivo sólido"
    if att < 0.85 and deff > 1.1:
        return "débil en ambas áreas"
    return "equilibrado"


def _nivel(prob, riesgos):
    if riesgos and prob < 80:
        return "PRECAUCION"
    if prob >= 85 and not riesgos:
        return "MUY SEGURO"
    if prob >= 75:
        return "SEGURO"
    return "RIESGOSO"


def armar_item(fx, pr, n):
    p1, px, p2 = pr["p"]
    L, V = fx["L"], fx["V"]
    ops = {f"1X ({L} gana o empata)": p1 + px, f"X2 ({V} gana o empata)": px + p2,
           "12 (no hay empate)": p1 + p2}
    dc, prob_dc = max(ops.items(), key=lambda kv: kv[1])
    gops = {"Más de 1.5 goles": pr["o15"], "Menos de 3.5 goles": pr["menos35"],
            "Más de 2.5 goles": pr["o25"], "Menos de 2.5 goles": 1 - pr["o25"]}
    gp, prob_g = max(gops.items(), key=lambda kv: kv[1])

    mercado = None
    dif = None
    if fx["odds"]:
        pm = sin_margen(fx["odds"])
        dif = [round((pr["p"][i] - pm[i]) * 100, 1) for i in range(3)]
        tok = dc.split(" ")[0]
        pm_dc = {"1X": pm[0] + pm[1], "X2": pm[1] + pm[2], "12": pm[0] + pm[2]}[tok]
        mercado = {"cuotas": fx["odds"], "fuente_cuotas": fx["fuente_cuotas"],
                   "prob_mercado_%": [round(x * 100, 1) for x in pm],
                   "dif_athena_menos_mercado_pts": dif,
                   "prob_dc_mercado_%": round(pm_dc * 100, 1)}
    mkt25 = None
    if fx["odds_ou"]:
        mkt25 = round(sin_margen(fx["odds_ou"])[0] * 100, 1)

    riesgos = []
    if min(pr["previos"]) < 10:
        riesgos.append("Pocos partidos previos de uno de los equipos")
    if max(p1, p2) < 0.40:
        riesgos.append("Partido muy parejo")
    if px >= 0.30:
        riesgos.append("Alta probabilidad de empate")
    if dif and max(abs(x) for x in dif) >= 8:
        riesgos.append("Athena difiere del mercado en 8 puntos o más (el mercado suele estar mejor informado: lesiones, alineaciones)")

    prob_dc_pct = round(min(prob_dc * 100, 99.0), 1)
    return {
        "partido_id": f"mh-{n}",
        "fecha": fx["fecha_utc"].isoformat(),
        "liga": fx["liga"], "partido": f"{L} vs {V}",
        "perfiles": {"local": pr["perfil"][0], "visitante": pr["perfil"][1]},
        "goles": {"goles_esperados": round(pr["lam"], 2),
                  "opciones": {k: round(v * 100, 1) for k, v in gops.items()},
                  "apuesta_segura": gp, "probabilidad": round(prob_g * 100, 1),
                  "mercado_mas_2.5_%": mkt25},
        "1x2": {"local": round(p1 * 100, 1), "empate": round(px * 100, 1), "visitante": round(p2 * 100, 1)},
        "apuesta_segura": dc, "probabilidad": prob_dc_pct,
        "nivel": _nivel(prob_dc_pct, riesgos), "riesgos": riesgos,
        "confianza_modelo": round(max(p1, px, p2) * 100, 1),
        "fuente": "MatchHistory", "modelo": VERSION, "mercado": mercado,
    }


# ─── Registro: lógica pura (probada sin base de datos) ───────
def evaluar_dc(pick, gl, gv):
    tok = (pick or "").split(" ")[0]
    return {"1X": gl >= gv, "X2": gv >= gl, "12": gl != gv}.get(tok)


def evaluar_goles(pick, gl, gv):
    t = gl + gv
    if pick.startswith("Más de 1.5"): return t > 1.5
    if pick.startswith("Más de 2.5"): return t > 2.5
    if pick.startswith("Menos de 2.5"): return t < 2.5
    if pick.startswith("Menos de 3.5"): return t < 3.5
    return None


def indexar_resultados(partidos):
    idx = defaultdict(list)
    for p in partidos:
        idx[(p["liga"], p["L"], p["V"])].append((p["fecha"], p["gl"], p["gv"]))
    return idx


def buscar_resultado(idx, liga, local, visita, fecha):
    """Resultado del partido con el mismo par de equipos a ±3 días de la fecha prevista."""
    mejor = None
    for f, gl, gv in idx.get((liga, local, visita), []):
        d = abs((f.date() - fecha.date()).days)
        if d <= 3 and (mejor is None or d < mejor[0]):
            mejor = (d, gl, gv)
    return (mejor[1], mejor[2]) if mejor else None


def _bin(p):
    for lo, hi in ((0, 60), (60, 70), (70, 80), (80, 90), (90, 101)):
        if lo <= p < hi:
            return f"{lo}-{min(hi, 100)}"
    return "?"


def resumen_registro(filas):
    """filas: lista de dicts con las columnas de RegistroPick."""
    res = [f for f in filas if f["resuelto"]]
    out = {"picks_registrados": len(filas), "resueltos": len(res), "pendientes": len(filas) - len(res)}
    if not res:
        out["nota"] = "Aún no hay partidos resueltos. Los resultados se completan solos después de cada jornada."
        return out
    out["desde"] = min(f["fecha_partido"] for f in res).date().isoformat()
    out["hasta"] = max(f["fecha_partido"] for f in res).date().isoformat()

    # 1X2: Athena contra el mercado (cuotas del momento del registro, sin margen)
    ba = bm = la = lm = 0.0
    n = 0
    for f in res:
        if not (f["cuota_local"] and f["cuota_empate"] and f["cuota_visita"]):
            continue
        real = 0 if f["goles_local"] > f["goles_visita"] else (1 if f["goles_local"] == f["goles_visita"] else 2)
        pa = [f["p_local"], f["p_empate"], f["p_visita"]]
        pm = sin_margen([f["cuota_local"], f["cuota_empate"], f["cuota_visita"]])
        ba += sum((pa[i] - (1 if i == real else 0)) ** 2 for i in range(3))
        bm += sum((pm[i] - (1 if i == real else 0)) ** 2 for i in range(3))
        la += -math.log(max(pa[real], 1e-3)); lm += -math.log(max(pm[real], 1e-3))
        n += 1
    if n:
        out["1x2_vs_mercado"] = {"partidos": n, "brier_athena": round(ba / n, 4), "brier_mercado": round(bm / n, 4),
                                 "logloss_athena": round(la / n, 4), "logloss_mercado": round(lm / n, 4),
                                 "nota": "Referencia del backtest: Athena 0.6072 vs mercado 0.5950 (más bajo es mejor)."}

    def calib(clave_pick, clave_prob, ev):
        g = defaultdict(list)
        tot = []
        for f in res:
            a = ev(f[clave_pick], f["goles_local"], f["goles_visita"])
            if a is None:
                continue
            g[_bin(f[clave_prob])].append((f[clave_prob], 1 if a else 0))
            tot.append((f[clave_prob], 1 if a else 0))
        if not tot:
            return None
        filas_ = [{"rango_%": k, "picks": len(v), "predicho_medio_%": round(sum(p for p, _ in v) / len(v), 1),
                   "acierto_real_%": round(sum(a for _, a in v) / len(v) * 100, 1)}
                  for k, v in sorted(g.items())]
        return {"picks": len(tot), "predicho_medio_%": round(sum(p for p, _ in tot) / len(tot), 1),
                "acierto_real_%": round(sum(a for _, a in tot) / len(tot) * 100, 1), "por_rango": filas_}

    out["doble_oportunidad"] = calib("pick_dc", "prob_dc", evaluar_dc)
    out["goles"] = calib("pick_goles", "prob_goles", evaluar_goles)
    out["aviso"] = ("Con pocos picks el resultado es ruido: no saques conclusiones hasta tener al menos "
                    "300 resueltos por mercado.")
    return out


# ─── Descarga y actualización ────────────────────────────────
async def _bajar(client, sem, url):
    async with sem:
        try:
            r = await client.get(url)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code} {url.split('/')[-2:]}"
            return r.content.decode("utf-8-sig", errors="replace"), None
        except Exception as e:
            return None, f"{url}: {e}"


async def _descargar():
    sem = asyncio.Semaphore(5)
    avisos, partidos, fixtures = [], [], []
    async with httpx.AsyncClient(timeout=40, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 Athena"}) as client:
        tareas = [(div, t, _bajar(client, sem, URL.format(temp=t, div=div)))
                  for div in DIVS for t in _temporadas(TEMPORADAS_DESCARGA)]
        tareas.append((None, None, _bajar(client, sem, FIXTURES_URL)))
        resultados = await asyncio.gather(*[t[2] for t in tareas])
    for (div, t, _), (txt, err) in zip(tareas, resultados):
        if err:
            avisos.append(err)
            continue
        if div is None:
            fixtures = parsear_fixtures(txt)
        else:
            partidos += parsear(txt, DIVS[div])
    return partidos, fixtures, avisos


def _guardar_y_resolver(preds, partidos):
    """Guarda picks nuevos (solo de partidos que aún no empezaron) y resuelve los pendientes."""
    db = SessionLocal()
    nuevos = resueltos = 0
    try:
        ahora = datetime.now(timezone.utc)
        for fx, pr, item in preds:
            if fx["fecha_utc"] <= ahora:
                continue
            clave = f'{fx["liga"]}|{fx["fecha_local"].date()}|{fx["L"]}|{fx["V"]}'
            if db.query(RegistroPick).filter(RegistroPick.clave == clave).first():
                continue
            o = fx["odds"] or [None, None, None]
            db.add(RegistroPick(
                clave=clave, version_modelo=VERSION, liga=fx["liga"], fecha_partido=fx["fecha_utc"],
                local=fx["L"], visita=fx["V"],
                p_local=pr["p"][0], p_empate=pr["p"][1], p_visita=pr["p"][2],
                p_mas15=pr["o15"], p_mas25=pr["o25"],
                pick_dc=item["apuesta_segura"], prob_dc=item["probabilidad"],
                pick_goles=item["goles"]["apuesta_segura"], prob_goles=item["goles"]["probabilidad"],
                cuota_local=o[0], cuota_empate=o[1], cuota_visita=o[2], cuota_fuente=fx["fuente_cuotas"],
                resuelto=False))
            nuevos += 1
        db.commit()
        resueltos = _resolver(db, partidos)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return nuevos, resueltos


def _resolver(db, partidos):
    idx = indexar_resultados(partidos)
    ahora = datetime.now(timezone.utc)
    n = 0
    pendientes = db.query(RegistroPick).filter(RegistroPick.resuelto == False).all()  # noqa: E712
    for r in pendientes:
        fp = r.fecha_partido
        if fp.tzinfo is None:
            fp = fp.replace(tzinfo=timezone.utc)
        if fp > ahora - timedelta(hours=2):
            continue
        res = buscar_resultado(idx, r.liga, r.local, r.visita, fp.replace(tzinfo=None))
        if res:
            r.goles_local, r.goles_visita, r.resuelto = res[0], res[1], True
            n += 1
    db.commit()
    return n


async def refrescar():
    async with _LOCK:
        CACHE["estado"] = "actualizando"
        try:
            partidos, fixtures, avisos = await _descargar()
            if not partidos:
                raise RuntimeError("No se descargó historial. " + "; ".join(avisos[:3]))
            estado = await asyncio.to_thread(construir_estado, partidos)
            items, preds = [], []
            for i, fx in enumerate(sorted(fixtures, key=lambda f: f["fecha_utc"])):
                pr = predecir_partido(estado, fx["liga"], fx["L"], fx["V"])
                if not pr:
                    continue
                item = armar_item(fx, pr, i)
                items.append(item)
                preds.append((fx, pr, item))
            reg = {}
            try:
                n, r = await asyncio.to_thread(_guardar_y_resolver, preds, partidos)
                reg = {"picks_nuevos_registrados": n, "picks_resueltos_ahora": r}
            except Exception as e:
                avisos.append(f"Registro: {e}")
            CACHE.update(estado="listo", actualizado=datetime.now(timezone.utc).isoformat(),
                         items=items, error=None, avisos=avisos, partidos_historicos=len(partidos),
                         partidos_proximos_leidos=len(fixtures), registro=reg)
        except Exception as e:
            CACHE.update(estado="error", error=str(e))


async def bucle_actualizacion():
    """Se lanza al arrancar el servidor: actualiza datos cada 6 horas."""
    await asyncio.sleep(45)
    while True:
        try:
            await refrescar()
        except Exception:
            pass
        await asyncio.sleep(6 * 3600)


# ─── Endpoints ───────────────────────────────────────────────
@router.get("/jornada")
async def jornada(background: BackgroundTasks, dias: int = Query(7, ge=1, le=14)):
    if not CACHE["items"] and CACHE["estado"] not in ("actualizando",):
        background.add_task(refrescar)
        return {"estado": "iniciando", "items": [], "mensaje": "Preparando datos; vuelve a consultar en ~1 minuto."}
    limite = datetime.now(timezone.utc) + timedelta(days=dias)
    ahora = datetime.now(timezone.utc) - timedelta(hours=2)
    items = [i for i in CACHE["items"] if ahora <= datetime.fromisoformat(i["fecha"]) <= limite]
    return {"estado": CACHE["estado"], "actualizado": CACHE["actualizado"], "version": VERSION,
            "ligas": LIGAS_MH, "items": items, "avisos": CACHE["avisos"], "error": CACHE["error"],
            "aviso": ("Athena entrega probabilidades calibradas, no una ventaja sobre el mercado: en el backtest "
                      "las cuotas de cierre fueron más precisas. Úsalo para filtrar, no como señal de apuesta.")}


@router.post("/actualizar")
async def actualizar(background: BackgroundTasks):
    if CACHE["estado"] == "actualizando":
        return {"mensaje": "Ya hay una actualización en curso"}
    background.add_task(refrescar)
    return {"mensaje": "Actualización iniciada. Consulta GET /api/v1/produccion/jornada en ~1 minuto."}


def _fila(r):
    return {c: getattr(r, c) for c in (
        "clave", "liga", "fecha_partido", "local", "visita", "p_local", "p_empate", "p_visita",
        "pick_dc", "prob_dc", "pick_goles", "prob_goles", "cuota_local", "cuota_empate", "cuota_visita",
        "resuelto", "goles_local", "goles_visita")}


@router.get("/registro/resumen")
def registro_resumen(db: Session = Depends(get_db)):
    filas = []
    for r in db.query(RegistroPick).all():
        d = _fila(r)
        if d["fecha_partido"] and d["fecha_partido"].tzinfo is None:
            d["fecha_partido"] = d["fecha_partido"].replace(tzinfo=timezone.utc)
        filas.append(d)
    out = resumen_registro(filas)
    out["version_modelo"] = VERSION
    return out


@router.get("/registro/picks")
def registro_picks(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.query(RegistroPick).order_by(RegistroPick.fecha_partido.desc()).limit(limit).all()
    return [{**_fila(r), "fecha_partido": r.fecha_partido.isoformat() if r.fecha_partido else None} for r in rows]


@router.post("/registro/resolver")
async def registro_resolver():
    partidos, _, avisos = await _descargar()

    def _run():
        db = SessionLocal()
        try:
            return _resolver(db, partidos)
        finally:
            db.close()
    n = await asyncio.to_thread(_run)
    return {"resueltos": n, "avisos": avisos}
