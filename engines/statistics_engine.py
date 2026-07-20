"""
Motor de Estadísticas — v0.0.1
Analiza tendencias estadísticas de equipos y genera métricas avanzadas.
"""

from typing import List, Dict, Optional


class MotorEstadisticas:
    """Análisis estadístico avanzado para equipos."""

    def calcular_forma(self, resultados: List[str]) -> float:
        """
        Calcula el índice de forma de un equipo (0-100).
        resultados: lista de 'V'/'E'/'D' (últimos N partidos, más reciente primero)
        """
        if not resultados:
            return 50.0
        
        total_puntos_posibles = len(resultados) * 3
        puntos = 0
        pesos = [1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.6][:len(resultados)]
        
        for resultado, peso in zip(resultados, pesos):
            if resultado == 'V':
                puntos += 3 * peso
            elif resultado == 'E':
                puntos += 1 * peso
        
        total_ponderado = sum(pesos) * 3
        return round((puntos / total_ponderado) * 100, 1)

    def calcular_xg_ajustado(
        self, xg_generado: float, xg_recibido: float,
        tiros: int, tiros_rival: int
    ) -> Dict:
        """Calcula el xG ajustado por calidad de oportunidades."""
        ratio_tiros = tiros / max(tiros_rival, 1)
        xg_neto = xg_generado - xg_recibido
        
        return {
            "xg_neto": round(xg_neto, 2),
            "xg_ratio": round(xg_generado / max(xg_recibido, 0.1), 2),
            "dominancia_tiros": round(ratio_tiros, 2),
            "valoracion": "dominante" if xg_neto > 0.5 else "equilibrado" if xg_neto > -0.5 else "vulnerable"
        }

    def tendencias_goles(
        self, goles_favor: List[int], goles_contra: List[int]
    ) -> Dict:
        """Analiza tendencias de goles en los últimos partidos."""
        if not goles_favor:
            return {}
        
        promedio_favor = sum(goles_favor) / len(goles_favor)
        promedio_contra = sum(goles_contra) / len(goles_contra)
        partidos_mas_25 = sum(1 for g1, g2 in zip(goles_favor, goles_contra) if g1 + g2 > 2.5)
        partidos_ambos = sum(1 for g1, g2 in zip(goles_favor, goles_contra) if g1 > 0 and g2 > 0)
        
        return {
            "promedio_goles_favor": round(promedio_favor, 2),
            "promedio_goles_contra": round(promedio_contra, 2),
            "promedio_total": round(promedio_favor + promedio_contra, 2),
            "pct_mas_25_goles": round(partidos_mas_25 / len(goles_favor) * 100, 1),
            "pct_ambos_anotan": round(partidos_ambos / len(goles_favor) * 100, 1),
        }

    def analizar_rendimiento_temporal(
        self, goles_por_minuto: Dict[int, int]
    ) -> Dict:
        """
        Analiza en qué momentos del partido un equipo es más peligroso.
        goles_por_minuto: {minuto: cantidad_goles}
        """
        if not goles_por_minuto:
            return {}
        
        periodos = {
            "0-15": [goles_por_minuto.get(m, 0) for m in range(0, 16)],
            "16-30": [goles_por_minuto.get(m, 0) for m in range(16, 31)],
            "31-45": [goles_por_minuto.get(m, 0) for m in range(31, 46)],
            "46-60": [goles_por_minuto.get(m, 0) for m in range(46, 61)],
            "61-75": [goles_por_minuto.get(m, 0) for m in range(61, 76)],
            "76-90": [goles_por_minuto.get(m, 0) for m in range(76, 91)],
        }
        
        return {periodo: sum(goles) for periodo, goles in periodos.items()}


motor_estadisticas = MotorEstadisticas()
