"""
Informe de jornada — Athena recomienda la apuesta MÁS SEGURA por partido
(Doble Oportunidad: 1X, X2 o 12) y arma el ranking de los mejores picks.

Todo sale de las probabilidades del IAI; no inventa datos. Si un equipo
tiene pocos partidos reales cargados, el pick se marca con advertencia.
"""
import math
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Partido, Equipo, Liga
from engines.iai_engine import motor_iai
from routers.predictions import _equipo_a_datos_iai

router = APIRouter()


def _promedios_liga(db: Session, liga_id):
    eqs = db.query(Equipo).filter(Equipo.liga_id == liga_id, Equipo.partidos_jugados > 0).all()
    if not eqs:
        return 1.3, 1.3
    return (sum(e.xg_favor_promedio or 0 for e in eqs) / len(eqs),
            sum(e.xg_contra_promedio or 0 for e in eqs) / len(eqs))


def _perfil(eq: Equipo, prom_fav: float, prom_con: float) -> str:
    """Perfil REAL según goles marcados/recibidos por partido vs. el promedio
    de su liga (no usa los atributos tácticos estimados)."""
    if (eq.partidos_jugados or 0) < 5:
        return "sin datos suficientes"
    ataque = (eq.xg_favor_promedio or 0) / max(prom_fav, 0.1)
    defensa = (eq.xg_contra_promedio or 0) / max(prom_con, 0.1)
    if ataque >= 1.15 and defensa <= 0.9:
        return "dominante (ataca bien y defiende bien)"
    if ataque >= 1.15 and defensa > 1.1:
        return "ofensivo y frágil atrás"
    if ataque >= 1.15:
        return "ofensivo"
    if defensa <= 0.85 and ataque < 0.95:
        return "defensivo (cierra y marca poco)"
    if defensa <= 0.85:
        return "defensivo sólido"
    if ataque < 0.85 and defensa > 1.1:
        return "débil en ambas áreas"
    return "equilibrado"


def _goles(local: Equipo, visita: Equipo):
    """Mercado de goles con datos REALES (goles marcados/recibidos por partido).
    Goles esperados de cada equipo = promedio entre su ataque y la defensa rival."""
    if (local.partidos_jugados or 0) < 5 or (visita.partidos_jugados or 0) < 5:
        return None
    lam_l = ((local.xg_favor_promedio or 0) + (visita.xg_contra_promedio or 0)) / 2
    lam_v = ((visita.xg_favor_promedio or 0) + (local.xg_contra_promedio or 0)) / 2
    lam = max(lam_l + lam_v, 0.2)

    def mas(linea):
        k = int(linea)
        acum = sum((lam ** i) * math.exp(-lam) / math.factorial(i) for i in range(k + 1))
        return round((1 - acum) * 100, 1)

    mas15, mas25, mas35 = mas(1.5), mas(2.5), mas(3.5)
    opciones = {
        "Más de 1.5 goles": mas15,
        "Menos de 3.5 goles": round(100 - mas35, 1),
        "Más de 2.5 goles": mas25,
        "Menos de 2.5 goles": round(100 - mas25, 1),
    }
    mejor, prob = max(opciones.items(), key=lambda kv: kv[1])
    return {
        "goles_esperados": round(lam, 2),
        "opciones": opciones,
        "apuesta_segura": mejor,
        "probabilidad": prob,
    }


def _nivel(prob: float, riesgos: list) -> str:
    if riesgos and prob < 80:
        return "PRECAUCION"
    if prob >= 85 and not riesgos:
        return "MUY SEGURO"
    if prob >= 75:
        return "SEGURO"
    return "RIESGOSO"


@router.get("/jornada")
async def informe_jornada(
    dias: int = Query(3, ge=1, le=14, description="Días hacia adelante"),
    max_picks: int = Query(8, ge=1, le=15, description="Cuántos picks incluir en la combinada sugerida"),
    prob_minima: float = Query(70.0, description="Descarta partidos por debajo de esta probabilidad"),
    db: Session = Depends(get_db),
):
    ahora = datetime.now(timezone.utc)
    limite = ahora + timedelta(days=dias)
    partidos = (
        db.query(Partido)
        .filter(Partido.jugado == False, Partido.fecha >= ahora, Partido.fecha <= limite)
        .order_by(Partido.fecha)
        .all()
    )

    analisis = []
    for p in partidos:
        local = db.query(Equipo).filter(Equipo.id == p.equipo_local_id).first()
        visita = db.query(Equipo).filter(Equipo.id == p.equipo_visitante_id).first()
        if not local or not visita:
            continue
        liga = db.query(Liga).filter(Liga.id == p.liga_id).first()

        dl = await _equipo_a_datos_iai(db, local, True, con_plantilla=False)
        dv = await _equipo_a_datos_iai(db, visita, False, con_plantilla=False)
        r = motor_iai.analizar_partido(dl, dv)

        opciones = {
            f"1X ({local.nombre} gana o empata)": r.victoria_local + r.empate,
            f"X2 ({visita.nombre} gana o empata)": r.empate + r.victoria_visitante,
            "12 (no hay empate)": r.victoria_local + r.victoria_visitante,
        }
        mejor, prob = max(opciones.items(), key=lambda kv: kv[1])
        prob = round(min(prob, 99.0), 1)

        pf, pc = _promedios_liga(db, p.liga_id)
        perfil_l, perfil_v = _perfil(local, pf, pc), _perfil(visita, pf, pc)

        riesgos = []
        if perfil_l.startswith("defensivo") and perfil_v.startswith("defensivo"):
            riesgos.append("Dos equipos defensivos: partido cerrado, riesgo de empate")
        if perfil_l.startswith("débil") and perfil_v.startswith("débil"):
            riesgos.append("Ambos equipos flojos: resultado impredecible")
        if (local.partidos_jugados or 0) < 5 or (visita.partidos_jugados or 0) < 5:
            riesgos.append("Pocos partidos reales cargados de uno de los equipos")
        if r.confianza_global < 50:
            riesgos.append(f"Confianza baja del modelo ({r.confianza_global})")
        if max(r.victoria_local, r.victoria_visitante) < 40:
            riesgos.append("Partido muy parejo")
        if r.empate >= 32:
            riesgos.append("Alta probabilidad de empate")

        analisis.append({
            "partido_id": p.id,
            "fecha": p.fecha.isoformat() if p.fecha else None,
            "liga": liga.nombre if liga else "",
            "partido": f"{local.nombre} vs {visita.nombre}",
            "perfiles": {"local": perfil_l, "visitante": perfil_v},
            "goles": _goles(local, visita),
            "1x2": {"local": r.victoria_local, "empate": r.empate, "visitante": r.victoria_visitante},
            "apuesta_segura": mejor,
            "probabilidad": prob,
            "nivel": _nivel(prob, riesgos),
            "riesgos": riesgos,
            "confianza_modelo": r.confianza_global,
        })

    analisis.sort(key=lambda a: (len(a["riesgos"]), -a["probabilidad"]))
    aptos = [a for a in analisis if a["probabilidad"] >= prob_minima]
    aptos.sort(key=lambda a: -a["probabilidad"] + 8 * len(a["riesgos"]))
    seleccion = aptos[:max_picks]

    prob_combinada = 1.0
    for a in seleccion:
        prob_combinada *= a["probabilidad"] / 100
    prob_combinada = round(prob_combinada * 100, 1)

    # Combinada de goles (independiente de la doble oportunidad)
    con_goles = [a for a in analisis if a["goles"] and a["goles"]["probabilidad"] >= prob_minima]
    con_goles.sort(key=lambda a: -a["goles"]["probabilidad"])
    sel_goles = con_goles[:max_picks]
    prob_goles = 1.0
    for a in sel_goles:
        prob_goles *= a["goles"]["probabilidad"] / 100
    prob_goles = round(prob_goles * 100, 1)

    return {
        "partidos_analizados": len(analisis),
        "combinada_goles": {
            "picks": [
                {
                    "partido_id": a["partido_id"], "fecha": a["fecha"], "liga": a["liga"],
                    "partido": a["partido"], "perfiles": a["perfiles"],
                    "apuesta_segura": a["goles"]["apuesta_segura"],
                    "probabilidad": a["goles"]["probabilidad"],
                    "goles_esperados": a["goles"]["goles_esperados"],
                }
                for a in sel_goles
            ],
            "cantidad": len(sel_goles),
            "probabilidad_de_acertar_todos": prob_goles,
        },
        "corners_y_tarjetas": (
            "No disponible: ninguna fuente gratuita entrega córners ni tarjetas reales por "
            "equipo, y el sistema solo tiene valores por defecto. Recomendarlos sería inventar."
        ),
        "combinada_sugerida": {
            "picks": seleccion,
            "cantidad": len(seleccion),
            "probabilidad_de_acertar_todos": prob_combinada,
            "nota": (
                "La probabilidad de acertar TODOS es el producto de las individuales. "
                "Con menos picks sube; por eso conviene combinadas de 2-4 picks muy "
                "seguros o dividir los picks en varios boletos."
            ),
        },
        "todos_los_partidos": analisis,
        "aviso": "Probabilidades del modelo Athena, no garantías. Las cuotas de doble oportunidad suelen ser bajas.",
    }
