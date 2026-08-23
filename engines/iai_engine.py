"""
MOTOR IAI — ÍNDICE ATHENA (v0.0.4)
====================================
El IAI es un número de 0 a 100 que representa la confianza del modelo
en cada escenario analizado. NO depende de cuotas externas.
 
Metodología (pesos que suman 100% cuando hay datos de jugadores):
- Análisis táctico comparativo (40%)
- Análisis estadístico histórico (25%)
- Estado real de la plantilla — bajas y profundidad (20%)
- Factores contextuales (15%)
 
Si no hay datos REALES de plantilla para ambos equipos (ver
squad_fetcher.py), el componente de jugadores se EXCLUYE del cálculo
en vez de rellenarse con un número neutral inventado, y su peso se
redistribuye proporcionalmente entre los otros 3 componentes.
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
 
from engines.tactical_engine import motor_tactico
 
# ─────────────────────────────────────────────────────────────
# ESTRUCTURAS DE DATOS
# ─────────────────────────────────────────────────────────────
 
@dataclass
class DatosEquipoIAI:
    """Snapshot de un equipo para el cálculo del IAI."""
    nombre: str
 
    victorias_ultimas_5: int = 0
    empates_ultimas_5: int = 0
    derrotas_ultimas_5: int = 0
    goles_favor_ultimas_5: float = 0.0
    goles_contra_ultimas_5: float = 0.0
 
    xg_favor_promedio: float = 1.2
    xg_contra_promedio: float = 1.2
    posesion_promedio: float = 50.0
    corners_promedio: float = 5.0
    tiros_promedio: float = 12.0
    faltas_promedio: float = 12.0
    amarillas_promedio: float = 2.0
 
    nivel_presion: float = 5.0
    fortaleza_mental: float = 5.0
    juego_aereo: float = 5.0
    intensidad: float = 5.0
    transiciones_ofensivas: float = 5.0
 
    es_local: bool = False
    victorias_local_pct: float = 0.45
    victorias_visitante_pct: float = 0.30
    fortaleza_local: float = 5.0
    rendimiento_visitante: float = 5.0
 
    racha_sin_perder: int = 0
    racha_sin_ganar: int = 0
 
    cambio_sistema_minuto: Optional[int] = None
    tendencia_goles_primeros: float = 0.3
    tendencia_goles_ultimos: float = 0.2
    reaccion_desventaja: float = 5.0
 
    # Jugadores — score real de plantilla (bajas + profundidad), 0-100.
    # None = sin datos reales disponibles para este equipo (el motor
    # excluye el componente en vez de inventar un número).
    jugadores_score: Optional[float] = None
 
 
@dataclass
class ResultadoIAI:
    """Resultado completo del análisis IAI."""
    victoria_local: float = 50.0
    empate: float = 50.0
    victoria_visitante: float = 50.0
 
    mas_25_goles: float = 50.0
    mas_35_goles: float = 50.0
    menos_25_goles: float = 50.0
    ambos_anotan: float = 50.0
 
    # Córners
    mas_75_corners: float = 50.0
    mas_85_corners: float = 50.0
    mas_95_corners: float = 50.0
    mas_105_corners: float = 50.0
 
    # Tarjetas
    mas_25_tarjetas: float = 50.0
    mas_35_tarjetas: float = 50.0
    mas_45_tarjetas: float = 50.0
 
    confianza_global: float = 50.0
    factores_clave: List[str] = field(default_factory=list)
    alertas: List[str] = field(default_factory=list)
    notas: str = ""
 
 
# ─────────────────────────────────────────────────────────────
# MOTOR IAI PRINCIPAL
# ─────────────────────────────────────────────────────────────
 
class MotorIAI:
    """Motor principal del Índice Athena. Calcula probabilidades de confianza."""
    VERSION = "0.0.4"
 
    def __init__(self):
        # Pesos base — suman 1.00 (100%) cuando hay datos de jugadores
        self.PESO_TACTICO = 0.40
        self.PESO_ESTADISTICO = 0.25
        self.PESO_JUGADORES = 0.20
        self.PESO_CONTEXTUAL = 0.15
 
    # ─── ANÁLISIS PRINCIPAL ──────────────────────────────────
    def analizar_partido(
        self,
        local: DatosEquipoIAI,
        visitante: DatosEquipoIAI,
        condiciones: Optional[Dict[str, Any]] = None
    ) -> ResultadoIAI:
        resultado = ResultadoIAI()
        condiciones = condiciones or {}
 
        stat = self._componente_estadistico(local, visitante)
        tac = self._componente_tactico(local, visitante)
        ctx = self._componente_contextual(local, visitante, condiciones)
 
        tiene_datos_jugadores = (
            local.jugadores_score is not None and visitante.jugadores_score is not None
        )
 
        if tiene_datos_jugadores:
            jug = self._componente_jugadores(local, visitante)
            peso_tac = self.PESO_TACTICO
            peso_stat = self.PESO_ESTADISTICO
            peso_jug = self.PESO_JUGADORES
            peso_ctx = self.PESO_CONTEXTUAL
        else:
            jug = {"prob_local": 0, "prob_visitante": 0}
            factor = 1 / (self.PESO_TACTICO + self.PESO_ESTADISTICO + self.PESO_CONTEXTUAL)
            peso_tac = self.PESO_TACTICO * factor
            peso_stat = self.PESO_ESTADISTICO * factor
            peso_jug = 0
            peso_ctx = self.PESO_CONTEXTUAL * factor
 
        prob_local = (
            tac["prob_local"] * peso_tac +
            stat["prob_local"] * peso_stat +
            jug["prob_local"] * peso_jug +
            ctx["ajuste_local"] * peso_ctx
        )
        prob_visitante = (
            tac["prob_visitante"] * peso_tac +
            stat["prob_visitante"] * peso_stat +
            jug["prob_visitante"] * peso_jug +
            ctx["ajuste_visitante"] * peso_ctx
        )
 
        prob_empate = max(0, 100 - prob_local - prob_visitante)
        total = prob_local + prob_empate + prob_visitante
        resultado.victoria_local = round((prob_local / total) * 100, 1)
        resultado.empate = round((prob_empate / total) * 100, 1)
        resultado.victoria_visitante = round((prob_visitante / total) * 100, 1)
 
        resultado.mas_25_goles = self._calcular_goles(local, visitante, linea=2.5)
        resultado.mas_35_goles = self._calcular_goles(local, visitante, linea=3.5)
        resultado.menos_25_goles = round(100 - resultado.mas_25_goles, 1)
        resultado.ambos_anotan = self._calcular_ambos_anotan(local, visitante)
 
        # Córners: 7.5, 8.5, 9.5 y 10.5
        resultado.mas_75_corners = self._calcular_corners(local, visitante, linea=7.5)
        resultado.mas_85_corners = self._calcular_corners(local, visitante, linea=8.5)
        resultado.mas_95_corners = self._calcular_corners(local, visitante, linea=9.5)
        resultado.mas_105_corners = self._calcular_corners(local, visitante, linea=10.5)
 
        # Tarjetas: 2.5, 3.5 y 4.5
        resultado.mas_25_tarjetas = self._calcular_tarjetas(local, visitante, linea=2.5)
        resultado.mas_35_tarjetas = self._calcular_tarjetas(local, visitante, linea=3.5)
        resultado.mas_45_tarjetas = self._calcular_tarjetas(local, visitante, linea=4.5)
 
        resultado.factores_clave = self._detectar_factores_clave(local, visitante, resultado)
        resultado.alertas = self._detectar_alertas(local, visitante)
 
        if not tiene_datos_jugadores:
            resultado.alertas.append(
                "Sin datos reales de plantilla para este partido — el análisis "
                "se basó solo en táctica, estadística y contexto (sin bajas/lesiones)."
            )
 
        resultado.confianza_global = self._calcular_confianza_global(resultado, stat, tac)
        resultado.notas = self._generar_notas(local, visitante, resultado)
 
        return resultado
 
    # ─── COMPONENTE ESTADÍSTICO ──────────────────────────────
    def _componente_estadistico(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI) -> Dict:
        puntos_local = (local.victorias_ultimas_5 * 3 + local.empates_ultimas_5)
        puntos_visitante = (visitante.victorias_ultimas_5 * 3 + visitante.empates_ultimas_5)
 
        forma_local = (puntos_local / 15) * 100
        forma_visitante = (puntos_visitante / 15) * 100
 
        xg_diff_local = local.xg_favor_promedio - local.xg_contra_promedio
        xg_diff_visitante = visitante.xg_favor_promedio - visitante.xg_contra_promedio
 
        xg_score_local = self._normalizar(xg_diff_local, -2.0, 2.0, 20, 80)
        xg_score_visitante = self._normalizar(xg_diff_visitante, -2.0, 2.0, 20, 80)
 
        prob_local = (forma_local * 0.5 + xg_score_local * 0.5)
        prob_visitante = (forma_visitante * 0.5 + xg_score_visitante * 0.5)
 
        return {
            "prob_local": prob_local,
            "prob_visitante": prob_visitante,
            "forma_local": forma_local,
            "forma_visitante": forma_visitante,
            "xg_diff_local": xg_diff_local,
            "xg_diff_visitante": xg_diff_visitante,
        }
 
    # ─── COMPONENTE TÁCTICO (motor táctico real) ─────────────
    def _componente_tactico(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI) -> Dict:
        local_dict = {
            "nombre": local.nombre,
            "nivel_presion": local.nivel_presion,
            "juego_aereo": local.juego_aereo,
            "transiciones_ofensivas": local.transiciones_ofensivas,
            "fortaleza_mental": local.fortaleza_mental,
            "cambio_sistema_minuto": local.cambio_sistema_minuto,
        }
        visitante_dict = {
            "nombre": visitante.nombre,
            "nivel_presion": visitante.nivel_presion,
            "juego_aereo": visitante.juego_aereo,
            "transiciones_ofensivas": visitante.transiciones_ofensivas,
            "fortaleza_mental": visitante.fortaleza_mental,
            "cambio_sistema_minuto": visitante.cambio_sistema_minuto,
        }
 
        analisis = motor_tactico.analizar_matchup(local_dict, visitante_dict)
        score_local = analisis.puntuacion_matchup
 
        return {
            "prob_local": max(20, min(80, score_local)),
            "prob_visitante": max(20, min(80, 100 - score_local)),
            "analisis_tactico": analisis,
        }
 
    # ─── COMPONENTE DE JUGADORES ──────────────────────────────
    def _componente_jugadores(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI) -> Dict:
        return {
            "prob_local": max(20, min(80, local.jugadores_score)),
            "prob_visitante": max(20, min(80, visitante.jugadores_score)),
        }
 
    # ─── COMPONENTE CONTEXTUAL ───────────────────────────────
    def _componente_contextual(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, condiciones: Dict
    ) -> Dict:
        ajuste_local = 50 + (local.fortaleza_local - 5) * 4
        ajuste_visitante = 50 + (visitante.rendimiento_visitante - 5) * 3
 
        if local.victorias_local_pct > 0.55:
            ajuste_local += 10
        elif local.victorias_local_pct < 0.35:
            ajuste_local -= 8
 
        if local.racha_sin_perder >= 5:
            ajuste_local += 6
        if visitante.racha_sin_perder >= 5:
            ajuste_visitante += 6
 
        return {
            "ajuste_local": max(20, min(80, ajuste_local)),
            "ajuste_visitante": max(20, min(80, ajuste_visitante)),
        }
 
    # ─── MERCADOS DE GOLES ───────────────────────────────────
    def _calcular_goles(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, linea: float) -> float:
        goles_esperados = local.xg_favor_promedio + visitante.xg_favor_promedio
        prob = self._poisson_supera_linea(goles_esperados, linea)
 
        presion_media = (local.nivel_presion + visitante.nivel_presion) / 2
        if presion_media > 7:
            prob = min(95, prob + 5)
        elif presion_media < 3:
            prob = max(5, prob - 5)
 
        return round(prob, 1)
 
    def _calcular_ambos_anotan(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI) -> float:
        prob_local_anota = self._probabilidad_anotar(local.xg_favor_promedio)
        prob_visitante_anota = self._probabilidad_anotar(visitante.xg_favor_promedio)
        prob = prob_local_anota * prob_visitante_anota * 100
        return round(min(95, max(5, prob)), 1)
 
    def _calcular_corners(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, linea: float) -> float:
        corners_esperados = local.corners_promedio + visitante.corners_promedio
        prob = self._poisson_supera_linea(corners_esperados, linea)
        if local.juego_aereo > 7 or visitante.juego_aereo > 7:
            prob = min(95, prob + 5)
        return round(prob, 1)
 
    def _calcular_tarjetas(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, linea: float) -> float:
        tarjetas_esperadas = local.amarillas_promedio + visitante.amarillas_promedio
        prob = self._poisson_supera_linea(tarjetas_esperadas, linea)
        if local.nivel_presion > 7 or visitante.nivel_presion > 7:
            prob = min(95, prob + 6)
        return round(prob, 1)
 
    # ─── ANÁLISIS INTELIGENTE — FACTORES Y ALERTAS ───────────
    def _detectar_factores_clave(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, resultado: ResultadoIAI
    ) -> List[str]:
        factores = []
 
        pts_l = local.victorias_ultimas_5 * 3 + local.empates_ultimas_5
        pts_v = visitante.victorias_ultimas_5 * 3 + visitante.empates_ultimas_5
 
        if pts_l >= 12:
            factores.append(f"{local.nombre} en estado de forma excepcional (últimos 5 partidos)")
        if pts_v >= 12:
            factores.append(f"{visitante.nombre} en estado de forma excepcional (últimos 5 partidos)")
 
        if local.xg_favor_promedio > 2.0:
            factores.append(f"{local.nombre} genera más de 2.0 xG por partido — ataque muy eficiente")
        if visitante.xg_contra_promedio > 1.8:
            factores.append(f"{visitante.nombre} recibe mucho — promedio xGC > 1.8 por partido")
 
        if local.nivel_presion > 7.5 and visitante.nivel_presion < 4:
            factores.append(f"Matchup táctico: pressing alto de {local.nombre} vs bloque bajo de {visitante.nombre}")
 
        if local.cambio_sistema_minuto and local.cambio_sistema_minuto <= 65:
            factores.append(f"Patrón detectado: {local.nombre} suele cambiar sistema al min {local.cambio_sistema_minuto}")
 
        if local.racha_sin_perder >= 7:
            factores.append(f"{local.nombre} lleva {local.racha_sin_perder} partidos sin perder")
 
        if local.jugadores_score is not None and local.jugadores_score <= 35:
            factores.append(f"{local.nombre} con plantilla debilitada (bajas/huecos detectados)")
        if visitante.jugadores_score is not None and visitante.jugadores_score <= 35:
            factores.append(f"{visitante.nombre} con plantilla debilitada (bajas/huecos detectados)")
 
        if resultado.mas_25_goles >= 75:
            factores.append(f"Alta probabilidad de más de 2.5 goles (IAI: {resultado.mas_25_goles})")
        if resultado.mas_75_corners >= 80:
            factores.append(f"Alta probabilidad de más de 7.5 córners (IAI: {resultado.mas_75_corners})")
 
        # Tendencia ofensiva/defensiva — derivada de goles reales
        # (no es la formación, es solo un perfil general del equipo)
        if local.xg_favor_promedio >= 1.8 and local.xg_contra_promedio <= 1.0:
            factores.append(f"{local.nombre} con perfil dominante: anota mucho y recibe poco")
        elif local.xg_favor_promedio <= 0.9 and local.xg_contra_promedio <= 1.0:
            factores.append(f"{local.nombre} con perfil defensivo/cerrado (pocos goles a favor y en contra)")
        elif local.xg_contra_promedio >= 1.8:
            factores.append(f"{local.nombre} con defensa vulnerable — recibe muchos goles en promedio")
 
        if visitante.xg_favor_promedio >= 1.8 and visitante.xg_contra_promedio <= 1.0:
            factores.append(f"{visitante.nombre} con perfil dominante: anota mucho y recibe poco")
        elif visitante.xg_favor_promedio <= 0.9 and visitante.xg_contra_promedio <= 1.0:
            factores.append(f"{visitante.nombre} con perfil defensivo/cerrado (pocos goles a favor y en contra)")
        elif visitante.xg_contra_promedio >= 1.8:
            factores.append(f"{visitante.nombre} con defensa vulnerable — recibe muchos goles en promedio")
 
        return factores[:9]
 
    def _detectar_alertas(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI) -> List[str]:
        alertas = []
 
        if local.racha_sin_ganar >= 4:
            alertas.append(f"ALERTA: {local.nombre} lleva {local.racha_sin_ganar} partidos sin ganar")
        if visitante.racha_sin_ganar >= 4:
            alertas.append(f"ALERTA: {visitante.nombre} lleva {visitante.racha_sin_ganar} partidos sin ganar")
 
        if abs(local.xg_favor_promedio - local.goles_favor_ultimas_5 / 5) > 0.8:
            alertas.append(f"Divergencia xG/Goles en {local.nombre} — rendimiento puede revertir")
 
        return alertas
 
    # ─── CONFIANZA GLOBAL ────────────────────────────────────
    def _calcular_confianza_global(self, resultado: ResultadoIAI, stat: Dict, tac: Dict) -> float:
        max_1x2 = max(resultado.victoria_local, resultado.empate, resultado.victoria_visitante)
        penalizacion = len(resultado.alertas) * 3
        base = self._normalizar(max_1x2, 33, 80, 40, 90)
 
        consenso = 1.0
        if (stat["prob_local"] > 55) == (tac["prob_local"] > 55):
            consenso = 1.1
 
        confianza = min(97, max(20, base * consenso - penalizacion))
        return round(confianza, 1)
 
    # ─── UTILIDADES MATEMÁTICAS ──────────────────────────────
    def _poisson_supera_linea(self, lambda_val: float, linea: float) -> float:
        linea_int = int(linea)
        prob_igual_o_menor = 0.0
        for k in range(linea_int + 1):
            prob_igual_o_menor += (
                (lambda_val ** k) * math.exp(-lambda_val) / math.factorial(k)
            )
        return round((1 - prob_igual_o_menor) * 100, 1)
 
    def _probabilidad_anotar(self, xg: float) -> float:
        return 1 - math.exp(-xg)
 
    def _normalizar(self, valor: float, min_in: float, max_in: float, min_out: float, max_out: float) -> float:
        valor_clamped = max(min_in, min(max_in, valor))
        ratio = (valor_clamped - min_in) / (max_in - min_in)
        return min_out + ratio * (max_out - min_out)
 
    def _generar_notas(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, resultado: ResultadoIAI) -> str:
        dominante = local.nombre if resultado.victoria_local > resultado.victoria_visitante else visitante.nombre
        return (
            f"El análisis favorece a {dominante} con IAI {max(resultado.victoria_local, resultado.victoria_visitante)}/100. "
            f"Se esperan ~{local.xg_favor_promedio + visitante.xg_favor_promedio:.1f} xG totales. "
            f"Confianza del modelo: {resultado.confianza_global}/100."
        )
 
 
motor_iai = MotorIAI()
 
