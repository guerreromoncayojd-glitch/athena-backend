"""
Router de Predicciones IAI — El corazón del sistema
Genera el Índice Athena para cualquier partido.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import Optional

from database.connection import get_db
from database.models import Partido, Equipo, PrediccionIAI
from database.schemas import PrediccionOut
from engines.iai_engine import motor_iai, DatosEquipoIAI
from engines.tactical_engine import motor_tactico

router = APIRouter()


def _equipo_a_datos_iai(equipo: Equipo, es_local: bool) -> DatosEquipoIAI:
    """Convierte un modelo Equipo a DatosEquipoIAI para el motor."""
    return DatosEquipoIAI(
        nombre=equipo.nombre,
        es_local=es_local,
        xg_favor_promedio=equipo.xg_favor_promedio or 1.2,
        xg_contra_promedio=equipo.xg_contra_promedio or 1.2,
        posesion_promedio=equipo.posesion_promedio or 50.0,
        corners_promedio=equipo.corners_promedio or 5.0,
        tiros_promedio=equipo.tiros_promedio or 12.0,
        faltas_promedio=equipo.faltas_promedio or 12.0,
        amarillas_promedio=equipo.tarjetas_amarillas_promedio or 2.0,
        nivel_presion=equipo.nivel_presion or 5.0,
        fortaleza_mental=equipo.fortaleza_mental or 5.0,
        juego_aereo=equipo.juego_aereo or 5.0,
        intensidad=equipo.intensidad or 5.0,
        fortaleza_local=equipo.fortaleza_local or 5.0,
        rendimiento_visitante=equipo.rendimiento_visitante or 5.0,
        victorias_local_pct=(equipo.victorias_local / max(equipo.partidos_jugados, 1))
            if equipo.partidos_jugados else 0.45,
        cambio_sistema_minuto=equipo.cambio_sistema_minuto,
        tendencia_goles_primeros=equipo.tendencia_goles_primeros or 0.3,
        reaccion_desventaja=equipo.reaccion_desventaja or 5.0,
    )


@router.get("/partido/{partido_id}", response_model=PrediccionOut)
def predecir_partido(partido_id: int, db: Session = Depends(get_db)):
    """
    Genera el Índice Athena (IAI) completo para un partido.
    
    Retorna:
    - Victoria local/empate/visitante (0-100)
    - Mercados de goles (2.5, 3.5)
    - Ambos anotan
    - Córners (9.5, 11.5)
    - Tarjetas (4.5, 5.5)
    - Confianza global del modelo
    - Factores clave detectados
    - Alertas del sistema
    """
    partido = db.query(Partido).filter(Partido.id == partido_id).first()
    if not partido:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    
    local = db.query(Equipo).filter(Equipo.id == partido.equipo_local_id).first()
    visitante = db.query(Equipo).filter(Equipo.id == partido.equipo_visitante_id).first()
    
    if not local or not visitante:
        raise HTTPException(status_code=400, detail="Equipos del partido no encontrados")
    
    # Convertir a datos IAI
    datos_local = _equipo_a_datos_iai(local, es_local=True)
    datos_visitante = _equipo_a_datos_iai(visitante, es_local=False)
    
    # Calcular IAI
    resultado = motor_iai.analizar_partido(datos_local, datos_visitante)
    
    # Guardar predicción en DB
    pred_existente = db.query(PrediccionIAI).filter(PrediccionIAI.partido_id == partido_id).first()
    if pred_existente:
        db.delete(pred_existente)
    
    pred = PrediccionIAI(
        partido_id=partido_id,
        version_modelo=motor_iai.VERSION,
        victoria_local=resultado.victoria_local,
        empate=resultado.empate,
        victoria_visitante=resultado.victoria_visitante,
        mas_25_goles=resultado.mas_25_goles,
        mas_35_goles=resultado.mas_35_goles,
        ambos_anotan=resultado.ambos_anotan,
        mas_95_corners=resultado.mas_95_corners,
        mas_45_tarjetas=resultado.mas_45_tarjetas,
        confianza_global=resultado.confianza_global,
        factores_clave=resultado.factores_clave,
        alertas=resultado.alertas,
        notas_analiticas=resultado.notas,
    )
    
    # Actualizar partido con predicciones
    partido.iai_victoria_local = resultado.victoria_local
    partido.iai_empate = resultado.empate
    partido.iai_victoria_visitante = resultado.victoria_visitante
    partido.iai_mas_25_goles = resultado.mas_25_goles
    partido.iai_mas_95_corners = resultado.mas_95_corners
    partido.iai_mas_45_tarjetas = resultado.mas_45_tarjetas
    partido.iai_ambos_anotan = resultado.ambos_anotan
    
    db.add(pred)
    db.commit()
    db.refresh(pred)
    
    return pred


@router.post("/rapido")
def prediccion_rapida(
    local: dict = Body(...),
    visitante: dict = Body(...)
):
    """
    Predicción rápida sin necesitar partido en DB.
    Útil para análisis ad-hoc.
    
    Formato: {"nombre": "Barcelona", "xg_favor_promedio": 2.1, ...}
    """
    datos_local = DatosEquipoIAI(
        nombre=local.get("nombre", "Local"),
        es_local=True,
        xg_favor_promedio=local.get("xg_favor_promedio", 1.2),
        xg_contra_promedio=local.get("xg_contra_promedio", 1.2),
        corners_promedio=local.get("corners_promedio", 5.0),
        amarillas_promedio=local.get("amarillas_promedio", 2.0),
        nivel_presion=local.get("nivel_presion", 5.0),
        fortaleza_mental=local.get("fortaleza_mental", 5.0),
        juego_aereo=local.get("juego_aereo", 5.0),
        victorias_ultimas_5=local.get("victorias_ultimas_5", 2),
        empates_ultimas_5=local.get("empates_ultimas_5", 1),
        racha_sin_perder=local.get("racha_sin_perder", 0),
    )
    
    datos_visitante = DatosEquipoIAI(
        nombre=visitante.get("nombre", "Visitante"),
        es_local=False,
        xg_favor_promedio=visitante.get("xg_favor_promedio", 1.0),
        xg_contra_promedio=visitante.get("xg_contra_promedio", 1.4),
        corners_promedio=visitante.get("corners_promedio", 4.5),
        amarillas_promedio=visitante.get("amarillas_promedio", 2.2),
        nivel_presion=visitante.get("nivel_presion", 5.0),
        fortaleza_mental=visitante.get("fortaleza_mental", 5.0),
        juego_aereo=visitante.get("juego_aereo", 5.0),
        victorias_ultimas_5=visitante.get("victorias_ultimas_5", 1),
        empates_ultimas_5=visitante.get("empates_ultimas_5", 2),
        racha_sin_perder=visitante.get("racha_sin_perder", 0),
    )
    
    resultado = motor_iai.analizar_partido(datos_local, datos_visitante)
    
    return {
        "local": datos_local.nombre,
        "visitante": datos_visitante.nombre,
        "iai": {
            "victoria_local": resultado.victoria_local,
            "empate": resultado.empate,
            "victoria_visitante": resultado.victoria_visitante,
            "mas_25_goles": resultado.mas_25_goles,
            "mas_35_goles": resultado.mas_35_goles,
            "ambos_anotan": resultado.ambos_anotan,
            "mas_95_corners": resultado.mas_95_corners,
            "mas_115_corners": resultado.mas_115_corners,
            "mas_45_tarjetas": resultado.mas_45_tarjetas,
            "mas_55_tarjetas": resultado.mas_55_tarjetas,
            "confianza_global": resultado.confianza_global,
        },
        "factores_clave": resultado.factores_clave,
        "alertas": resultado.alertas,
        "analisis": resultado.notas,
        "version_modelo": motor_iai.VERSION
    }
