"""
Motor Táctico — v0.0.1
Analiza el matchup táctico entre dos equipos.
Responde preguntas tácticas inteligentes.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class AnalisisTactico:
    equipo_favorecido: str
    ventajas_local: List[str]
    ventajas_visitante: List[str]
    matchups_clave: List[str]
    preguntas_tacticas: List[str]
    puntuacion_matchup: float  # 0-100, 50=equilibrado, >50 favorece local


class MotorTactico:
    """
    Analiza matchups tácticos y responde preguntas tácticas inteligentes.
    
    Preguntas que puede responder:
    - ¿Qué entrenador suele cambiar sistema al minuto 60?
    - ¿Qué equipo tiene ventaja en juego aéreo?
    - ¿Qué lateral deja espacios cuando ataca?
    - ¿Qué equipo es vulnerable al contraataque?
    """

    def analizar_matchup(
        self,
        local_data: Dict,
        visitante_data: Dict
    ) -> AnalisisTactico:
        """Análisis táctico completo del matchup entre dos equipos."""
        
        ventajas_local = []
        ventajas_visitante = []
        matchups = []
        preguntas = []
        
        # ── Pressing vs Bloque Bajo ────────────────────────────
        presion_local = local_data.get("nivel_presion", 5)
        presion_visitante = local_data.get("nivel_presion", 5)
        
        if presion_local > 7:
            ventajas_local.append("Pressing alto — puede ahogarlo en campo rival")
            preguntas.append(f"¿Puede {local_data['nombre']} sostener el pressing 90 min?")
        
        if presion_local > 7 and presion_visitante < 4:
            matchups.append("Pressing alto local vs bloque bajo visitante: favorece al local")
        
        # ── Juego Aéreo ───────────────────────────────────────
        aereo_local = local_data.get("juego_aereo", 5)
        aereo_visitante = visitante_data.get("juego_aereo", 5)
        
        if aereo_local > aereo_visitante + 2:
            ventajas_local.append(f"Superioridad aérea clara ({aereo_local:.1f} vs {aereo_visitante:.1f})")
            matchups.append("Juego aéreo: ventaja local en duelos aéreos y saques de esquina")
        elif aereo_visitante > aereo_local + 2:
            ventajas_visitante.append(f"Superioridad aérea del visitante ({aereo_visitante:.1f} vs {aereo_local:.1f})")
        
        # ── Transiciones ──────────────────────────────────────
        trans_local = local_data.get("transiciones_ofensivas", 5)
        trans_visitante = visitante_data.get("transiciones_ofensivas", 5)
        
        if trans_local > 7.5:
            ventajas_local.append("Peligroso en transiciones ofensivas rápidas")
            preguntas.append(f"¿Qué lateral de {visitante_data['nombre']} deja más espacio al atacar?")
        
        # ── Cambio de sistema ─────────────────────────────────
        minuto_cambio = local_data.get("cambio_sistema_minuto")
        if minuto_cambio:
            preguntas.append(
                f"¿Cambia {local_data['nombre']} al {minuto_cambio}' como es su patrón?"
            )
        
        # ── Fortaleza mental ──────────────────────────────────
        mental_local = local_data.get("fortaleza_mental", 5)
        mental_visitante = visitante_data.get("fortaleza_mental", 5)
        
        if mental_local > 8:
            ventajas_local.append("Fuerte mentalidad — buenos resultados en partidos ajustados")
        elif mental_visitante > 8:
            ventajas_visitante.append("Visitante muy fuerte mentalmente — peligroso si empatan")
        
        # ── Puntuación final de matchup ────────────────────────
        score = 50.0
        score += (presion_local - presion_visitante) * 2
        score += (aereo_local - aereo_visitante) * 1.5
        score += (mental_local - mental_visitante) * 1.5
        score += (trans_local - trans_visitante) * 1
        score = max(20, min(80, score))
        
        dominante = local_data["nombre"] if score > 55 else (
            visitante_data["nombre"] if score < 45 else "Equilibrado"
        )
        
        return AnalisisTactico(
            equipo_favorecido=dominante,
            ventajas_local=ventajas_local,
            ventajas_visitante=ventajas_visitante,
            matchups_clave=matchups,
            preguntas_tacticas=preguntas,
            puntuacion_matchup=round(score, 1)
        )

    def generar_preguntas_tacticas(
        self, equipo_data: Dict, rival_data: Dict
    ) -> List[str]:
        """
        Genera las preguntas tácticas inteligentes sobre el partido.
        Esta es la innovación del motor: pensar tácticamente, no solo numéricamente.
        """
        preguntas = []
        
        # Preguntas sobre el entrenador
        cambio = equipo_data.get("cambio_sistema_minuto")
        if cambio:
            preguntas.append(
                f"¿El entrenador de {equipo_data['nombre']} cambiará al minuto {cambio} como es habitual?"
            )
        
        # Preguntas sobre bandas
        if equipo_data.get("juego_bandas", 5) > 7.5:
            preguntas.append(
                f"¿{rival_data['nombre']} puede controlar las bandas de {equipo_data['nombre']}?"
            )
        
        # Preguntas sobre vulnerabilidad al contraataque
        if equipo_data.get("altura_linea_defensiva", 5) > 7.5:
            preguntas.append(
                f"¿{rival_data['nombre']} puede explotar el espacio a la espalda de la línea alta de {equipo_data['nombre']}?"
            )
        
        return preguntas


motor_tactico = MotorTactico()
