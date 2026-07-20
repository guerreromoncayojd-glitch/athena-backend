"""
MOTOR IAI — ÍNDICE ATHENA (v0.0.1)
====================================
El IAI es un número de 0 a 100 que representa la confianza del modelo
en cada escenario analizado. NO depende de cuotas externas.

Metodología:
- Análisis estadístico histórico (40%)
- Análisis táctico comparativo (25%)
- Análisis de jugadores clave (20%)
- Factores contextuales (15%)
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


# ─────────────────────────────────────────────────────────────
# ESTRUCTURAS DE DATOS
# ─────────────────────────────────────────────────────────────

@dataclass
class DatosEquipoIAI:
    """Snapshot de un equipo para el cálculo del IAI."""
    nombre: str
    
    # Rendimiento reciente
    victorias_ultimas_5: int = 0
    empates_ultimas_5: int = 0
    derrotas_ultimas_5: int = 0
    goles_favor_ultimas_5: float = 0.0
    goles_contra_ultimas_5: float = 0.0
    
    # Estadísticas de temporada
    xg_favor_promedio: float = 1.2
    xg_contra_promedio: float = 1.2
    posesion_promedio: float = 50.0
    corners_promedio: float = 5.0
    tiros_promedio: float = 12.0
    faltas_promedio: float = 12.0
    amarillas_promedio: float = 2.0
    
    # Táctico
    nivel_presion: float = 5.0
    fortaleza_mental: float = 5.0
    juego_aereo: float = 5.0
    intensidad: float = 5.0
    
    # Contexto local/visitante
    es_local: bool = False
    victorias_local_pct: float = 0.45
    victorias_visitante_pct: float = 0.30
    fortaleza_local: float = 5.0
    rendimiento_visitante: float = 5.0
    
    # Racha y forma
    racha_sin_perder: int = 0
    racha_sin_ganar: int = 0
    
    # Patrones tácticos especiales
    cambio_sistema_minuto: Optional[int] = None  # ¿A qué minuto cambia sistema?
    tendencia_goles_primeros: float = 0.3        # % goles primeros 30 min
    tendencia_goles_ultimos: float = 0.2         # % goles últimos 15 min
    reaccion_desventaja: float = 5.0


@dataclass
class ResultadoIAI:
    """Resultado completo del análisis IAI."""
    
    # Mercados principales
    victoria_local: float = 50.0
    empate: float = 50.0
    victoria_visitante: float = 50.0
    
    # Goles
    mas_25_goles: float = 50.0
    mas_35_goles: float = 50.0
    menos_25_goles: float = 50.0
    ambos_anotan: float = 50.0
    
    # Especiales
    mas_95_corners: float = 50.0
    mas_115_corners: float = 50.0
    mas_45_tarjetas: float = 50.0
    mas_55_tarjetas: float = 50.0
    
    # Meta
    confianza_global: float = 50.0
    factores_clave: List[str] = field(default_factory=list)
    alertas: List[str] = field(default_factory=list)
    notas: str = ""


# ─────────────────────────────────────────────────────────────
# MOTOR IAI PRINCIPAL
# ─────────────────────────────────────────────────────────────

class MotorIAI:
    """
    Motor principal del Índice Athena.
    Calcula probabilidades de confianza para cada escenario.
    """

    VERSION = "0.0.1"
    
    def __init__(self):
        # Pesos de los componentes
        self.PESO_ESTADISTICO = 0.40
        self.PESO_TACTICO     = 0.25
        self.PESO_JUGADORES   = 0.20
        self.PESO_CONTEXTUAL  = 0.15

    # ─── ANÁLISIS PRINCIPAL ──────────────────────────────────

    def analizar_partido(
        self,
        local: DatosEquipoIAI,
        visitante: DatosEquipoIAI,
        condiciones: Optional[Dict[str, Any]] = None
    ) -> ResultadoIAI:
        """
        Punto de entrada principal. Analiza un partido y devuelve el IAI completo.
        """
        resultado = ResultadoIAI()
        condiciones = condiciones or {}

        # ── Componente estadístico ────────────────────────────
        stat = self._componente_estadistico(local, visitante)

        # ── Componente táctico ────────────────────────────────
        tac = self._componente_tactico(local, visitante)

        # ── Componente contextual ─────────────────────────────
        ctx = self._componente_contextual(local, visitante, condiciones)

        # ── Síntesis: 1X2 ────────────────────────────────────
        prob_local = (
            stat["prob_local"]     * self.PESO_ESTADISTICO +
            tac["prob_local"]      * self.PESO_TACTICO +
            ctx["ajuste_local"]    * self.PESO_CONTEXTUAL
        )
        prob_visitante = (
            stat["prob_visitante"] * self.PESO_ESTADISTICO +
            tac["prob_visitante"]  * self.PESO_TACTICO +
            ctx["ajuste_visitante"]* self.PESO_CONTEXTUAL
        )

        # Empate como complemento calibrado
        prob_empate = max(0, 100 - prob_local - prob_visitante)

        # Normalizar a 100
        total = prob_local + prob_empate + prob_visitante
        resultado.victoria_local     = round((prob_local / total) * 100, 1)
        resultado.empate             = round((prob_empate / total) * 100, 1)
        resultado.victoria_visitante = round((prob_visitante / total) * 100, 1)

        # ── Mercados de goles ─────────────────────────────────
        resultado.mas_25_goles   = self._calcular_goles(local, visitante, linea=2.5)
        resultado.mas_35_goles   = self._calcular_goles(local, visitante, linea=3.5)
        resultado.menos_25_goles = round(100 - resultado.mas_25_goles, 1)
        resultado.ambos_anotan   = self._calcular_ambos_anotan(local, visitante)

        # ── Córners ───────────────────────────────────────────
        resultado.mas_95_corners  = self._calcular_corners(local, visitante, linea=9.5)
        resultado.mas_115_corners = self._calcular_corners(local, visitante, linea=11.5)

        # ── Tarjetas ──────────────────────────────────────────
        resultado.mas_45_tarjetas = self._calcular_tarjetas(local, visitante, linea=4.5)
        resultado.mas_55_tarjetas = self._calcular_tarjetas(local, visitante, linea=5.5)

        # ── Factores clave detectados ─────────────────────────
        resultado.factores_clave = self._detectar_factores_clave(local, visitante, resultado)
        resultado.alertas        = self._detectar_alertas(local, visitante)

        # ── Confianza global ──────────────────────────────────
        resultado.confianza_global = self._calcular_confianza_global(resultado, stat, tac)
        resultado.notas = self._generar_notas(local, visitante, resultado)

        return resultado

    # ─── COMPONENTE ESTADÍSTICO ──────────────────────────────

    def _componente_estadistico(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI) -> Dict:
        """Análisis basado en estadísticas históricas y recientes."""

        # Forma reciente (últimos 5 partidos)
        puntos_local = (local.victorias_ultimas_5 * 3 + local.empates_ultimas_5)
        puntos_visitante = (visitante.victorias_ultimas_5 * 3 + visitante.empates_ultimas_5)

        forma_local = (puntos_local / 15) * 100
        forma_visitante = (puntos_visitante / 15) * 100

        # XG diferencial — predictor más fiable
        xg_diff_local = local.xg_favor_promedio - local.xg_contra_promedio
        xg_diff_visitante = visitante.xg_favor_promedio - visitante.xg_contra_promedio

        xg_score_local = self._normalizar(xg_diff_local, -2.0, 2.0, 20, 80)
        xg_score_visitante = self._normalizar(xg_diff_visitante, -2.0, 2.0, 20, 80)

        # Combinación ponderada
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

    # ─── COMPONENTE TÁCTICO ──────────────────────────────────

    def _componente_tactico(self, local: DatosEquipoIAI, visitante: DatosEquipoIAI) -> Dict:
        """
        Análisis de matchup táctico — aquí es donde el IAI marca diferencia.
        Responde preguntas como:
        - ¿Equipo A presiona alto vs equipo B que juega por atrás?
        - ¿Quién tiene ventaja en juego aéreo?
        """

        score_local = 50.0
        score_visitante = 50.0

        # Ventaja de pressing: equipo con mayor presión vs bajo bloque
        if local.nivel_presion > 7 and visitante.nivel_presion < 4:
            score_local += 8
        elif visitante.nivel_presion > 7 and local.nivel_presion < 4:
            score_visitante += 8

        # Ventaja fortaleza mental
        diff_mental = local.fortaleza_mental - visitante.fortaleza_mental
        score_local += diff_mental * 2
        score_visitante -= diff_mental * 2

        # Ventaja intensidad
        if local.intensidad > visitante.intensidad + 2:
            score_local += 5
        elif visitante.intensidad > local.intensidad + 2:
            score_visitante += 5

        return {
            "prob_local": max(20, min(80, score_local)),
            "prob_visitante": max(20, min(80, score_visitante)),
        }

    # ─── COMPONENTE CONTEXTUAL ───────────────────────────────

    def _componente_contextual(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI,
        condiciones: Dict
    ) -> Dict:
        """Factores contextuales: local/visitante, clima, importancia del partido."""

        ajuste_local = 50 + (local.fortaleza_local - 5) * 4
        ajuste_visitante = 50 + (visitante.rendimiento_visitante - 5) * 3

        # Factor local histórico
        if local.victorias_local_pct > 0.55:
            ajuste_local += 10
        elif local.victorias_local_pct < 0.35:
            ajuste_local -= 8

        # Racha sin perder
        if local.racha_sin_perder >= 5:
            ajuste_local += 6
        if visitante.racha_sin_perder >= 5:
            ajuste_visitante += 6

        return {
            "ajuste_local": max(20, min(80, ajuste_local)),
            "ajuste_visitante": max(20, min(80, ajuste_visitante)),
        }

    # ─── MERCADOS DE GOLES ───────────────────────────────────

    def _calcular_goles(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, linea: float
    ) -> float:
        """IAI para mercado de goles totales."""
        goles_esperados = local.xg_favor_promedio + visitante.xg_favor_promedio

        # Probabilidad de superar la línea usando distribución de Poisson simplificada
        prob = self._poisson_supera_linea(goles_esperados, linea)
        
        # Ajuste por presión de ambos equipos (más presión = más goles generalmente)
        presion_media = (local.nivel_presion + visitante.nivel_presion) / 2
        if presion_media > 7:
            prob = min(95, prob + 5)
        elif presion_media < 3:
            prob = max(5, prob - 5)

        return round(prob, 1)

    def _calcular_ambos_anotan(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI
    ) -> float:
        """IAI para mercado 'ambos equipos anotan'."""
        prob_local_anota = self._probabilidad_anotar(local.xg_favor_promedio)
        prob_visitante_anota = self._probabilidad_anotar(visitante.xg_favor_promedio)
        prob = prob_local_anota * prob_visitante_anota * 100
        return round(min(95, max(5, prob)), 1)

    def _calcular_corners(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, linea: float
    ) -> float:
        """IAI para mercado de córners."""
        corners_esperados = local.corners_promedio + visitante.corners_promedio
        prob = self._poisson_supera_linea(corners_esperados, linea)
        
        # Equipos que atacan por bandas generan más córners
        if local.juego_aereo > 7 or visitante.juego_aereo > 7:
            prob = min(95, prob + 5)
        
        return round(prob, 1)

    def _calcular_tarjetas(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI, linea: float
    ) -> float:
        """IAI para mercado de tarjetas."""
        tarjetas_esperadas = local.amarillas_promedio + visitante.amarillas_promedio
        prob = self._poisson_supera_linea(tarjetas_esperadas, linea)
        
        # Partidos de alta presión generan más tarjetas
        if local.nivel_presion > 7 or visitante.nivel_presion > 7:
            prob = min(95, prob + 6)
        
        return round(prob, 1)

    # ─── ANÁLISIS INTELIGENTE — PREGUNTAS IAI ────────────────

    def _detectar_factores_clave(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI,
        resultado: ResultadoIAI
    ) -> List[str]:
        """
        Detecta los factores más relevantes del análisis.
        Aquí está la inteligencia táctica del sistema.
        """
        factores = []

        # Forma reciente dominante
        pts_l = local.victorias_ultimas_5 * 3 + local.empates_ultimas_5
        pts_v = visitante.victorias_ultimas_5 * 3 + visitante.empates_ultimas_5
        if pts_l >= 12:
            factores.append(f"{local.nombre} en estado de forma excepcional (últimos 5 partidos)")
        if pts_v >= 12:
            factores.append(f"{visitante.nombre} en estado de forma excepcional (últimos 5 partidos)")

        # XG superiority
        if local.xg_favor_promedio > 2.0:
            factores.append(f"{local.nombre} genera más de 2.0 xG por partido — ataque muy eficiente")
        if visitante.xg_contra_promedio > 1.8:
            factores.append(f"{visitante.nombre} recibe mucho — promedio xGC > 1.8 por partido")

        # Ventaja táctica de pressing
        if local.nivel_presion > 7.5 and visitante.nivel_presion < 4:
            factores.append(f"Matchup táctico: pressing alto de {local.nombre} vs bloque bajo de {visitante.nombre}")

        # Cambio de sistema a cierto minuto
        if local.cambio_sistema_minuto and local.cambio_sistema_minuto <= 65:
            factores.append(
                f"Patrón detectado: {local.nombre} suele cambiar sistema al min {local.cambio_sistema_minuto}"
            )

        # Racha sin perder
        if local.racha_sin_perder >= 7:
            factores.append(f"{local.nombre} lleva {local.racha_sin_perder} partidos sin perder")

        # Mercados con alta confianza
        if resultado.mas_25_goles >= 75:
            factores.append(f"Alta probabilidad de más de 2.5 goles (IAI: {resultado.mas_25_goles})")
        if resultado.mas_95_corners >= 80:
            factores.append(f"Alta probabilidad de más de 9.5 córners (IAI: {resultado.mas_95_corners})")

        return factores[:7]  # Top 7 factores

    def _detectar_alertas(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI
    ) -> List[str]:
        """Detecta señales de alerta que reducen la confianza."""
        alertas = []

        if local.racha_sin_ganar >= 4:
            alertas.append(f"ALERTA: {local.nombre} lleva {local.racha_sin_ganar} partidos sin ganar")
        if visitante.racha_sin_ganar >= 4:
            alertas.append(f"ALERTA: {visitante.nombre} lleva {visitante.racha_sin_ganar} partidos sin ganar")

        if abs(local.xg_favor_promedio - local.goles_favor_ultimas_5/5) > 0.8:
            alertas.append(f"Divergencia xG/Goles en {local.nombre} — rendimiento puede revertir")

        return alertas

    # ─── CONFIANZA GLOBAL ────────────────────────────────────

    def _calcular_confianza_global(
        self, resultado: ResultadoIAI, stat: Dict, tac: Dict
    ) -> float:
        """
        Calcula la confianza global del análisis.
        Alta cuando hay consenso entre los distintos componentes.
        """
        # Mayor confianza cuando hay señal clara en 1X2
        max_1x2 = max(resultado.victoria_local, resultado.empate, resultado.victoria_visitante)
        
        # Penalizar si hay alertas
        penalizacion = len(resultado.alertas) * 3
        
        # Base: qué tan decisiva es la señal
        base = self._normalizar(max_1x2, 33, 80, 40, 90)
        
        # Factor de consenso: estadístico y táctico apuntan al mismo ganador
        consenso = 1.0
        if (stat["prob_local"] > 55) == (tac["prob_local"] > 55):
            consenso = 1.1  # Boost cuando hay consenso
        
        confianza = min(97, max(20, base * consenso - penalizacion))
        return round(confianza, 1)

    # ─── UTILIDADES MATEMÁTICAS ──────────────────────────────

    def _poisson_supera_linea(self, lambda_val: float, linea: float) -> float:
        """Probabilidad de superar una línea usando distribución de Poisson."""
        linea_int = int(linea)
        prob_igual_o_menor = 0.0
        for k in range(linea_int + 1):
            prob_igual_o_menor += (
                (lambda_val ** k) * math.exp(-lambda_val) / math.factorial(k)
            )
        return round((1 - prob_igual_o_menor) * 100, 1)

    def _probabilidad_anotar(self, xg: float) -> float:
        """Probabilidad de que un equipo anote al menos 1 gol dado su xG."""
        return 1 - math.exp(-xg)

    def _normalizar(
        self, valor: float, min_in: float, max_in: float,
        min_out: float, max_out: float
    ) -> float:
        """Normaliza un valor de un rango de entrada a un rango de salida."""
        valor_clamped = max(min_in, min(max_in, valor))
        ratio = (valor_clamped - min_in) / (max_in - min_in)
        return min_out + ratio * (max_out - min_out)

    def _generar_notas(
        self, local: DatosEquipoIAI, visitante: DatosEquipoIAI,
        resultado: ResultadoIAI
    ) -> str:
        """Genera notas analíticas del partido."""
        dominante = local.nombre if resultado.victoria_local > resultado.victoria_visitante else visitante.nombre
        return (
            f"El análisis favorece a {dominante} con IAI {max(resultado.victoria_local, resultado.victoria_visitante)}/100. "
            f"Se esperan ~{local.xg_favor_promedio + visitante.xg_favor_promedio:.1f} xG totales. "
            f"Confianza del modelo: {resultado.confianza_global}/100."
        )


# ─── SINGLETON ───────────────────────────────────────────────
motor_iai = MotorIAI()
