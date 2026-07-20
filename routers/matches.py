from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from database.connection import get_db
from database.models import Partido, Equipo, Liga
from database.schemas import PartidoCreate, PartidoOut

router = APIRouter()


@router.get("/", response_model=List[PartidoOut])
def listar_partidos(
    liga_id: Optional[int] = None,
    jugado: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Partido)
    if liga_id:
        query = query.filter(Partido.liga_id == liga_id)
    if jugado is not None:
        query = query.filter(Partido.jugado == jugado)
    return query.order_by(Partido.fecha.asc()).limit(100).all()


@router.post("/", response_model=PartidoOut, status_code=201)
def crear_partido(partido: PartidoCreate, db: Session = Depends(get_db)):
    db_partido = Partido(**partido.dict())
    db.add(db_partido)
    db.commit()
    db.refresh(db_partido)
    return db_partido


@router.get("/proximos/resumen")
def partidos_proximos(db: Session = Depends(get_db)):
    partidos = db.query(Partido).filter(
        Partido.jugado == False
    ).order_by(Partido.fecha.asc()).limit(50).all()

    def _stats(e):
        if not e:
            return None
        pj = max(e.partidos_jugados or 0, 1)
        win_rate  = (e.victorias or 0) / pj
        draw_rate = (e.empates   or 0) / pj
        return {
            "nombre": e.nombre,
            "xg_favor_promedio":  round(e.xg_favor_promedio  or 1.2, 2),
            "xg_contra_promedio": round(e.xg_contra_promedio or 1.0, 2),
            "corners_promedio":   round(e.corners_promedio   or 5.0, 1),
            "nivel_presion":      round(e.nivel_presion      or 5.0, 1),
            "fortaleza_mental":   round(e.fortaleza_mental   or 5.0, 1),
            "posesion_promedio":  round(e.posesion_promedio  or 50.0, 1),
            "formacion":          e.formacion_habitual or "4-3-3",
            "victorias_ultimas_5": min(5, round(win_rate  * 5)),
            "empates_ultimas_5":   min(5, round(draw_rate * 5)),
        }

    resultado = []
    for p in partidos:
        local     = db.query(Equipo).filter(Equipo.id == p.equipo_local_id).first()
        visitante = db.query(Equipo).filter(Equipo.id == p.equipo_visitante_id).first()
        liga      = db.query(Liga).filter(Liga.id == p.liga_id).first()
        resultado.append({
            "id":                  p.id,
            "liga":                liga.nombre if liga else "",
            "local":               local.nombre    if local     else "",
            "visitante":           visitante.nombre if visitante else "",
            "fecha":               str(p.fecha)[:10] if p.fecha else "",
            "jornada":             p.jornada,
            "estadio":             p.estadio or (local.estadio if local else "") or "",
            "equipo_local_id":     p.equipo_local_id,
            "equipo_visitante_id": p.equipo_visitante_id,
            "stats_local":         _stats(local),
            "stats_visitante":     _stats(visitante),
        })
    return resultado


@router.post("/sincronizar")
async def sincronizar_partidos_reales(dias: int = 14, db: Session = Depends(get_db)):
    from engines.data_fetcher import fetch_upcoming_matches
    result = await fetch_upcoming_matches(db, days_ahead=dias)
    return result


@router.get("/{partido_id}", response_model=PartidoOut)
def obtener_partido(partido_id: int, db: Session = Depends(get_db)):
    partido = db.query(Partido).filter(Partido.id == partido_id).first()
    if not partido:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    return partido
