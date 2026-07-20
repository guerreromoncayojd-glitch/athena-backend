"""
Motor de Análisis de Jugadores — v0.0.1
Calcula el IAI individual de jugadores y detecta patrones de comportamiento.
"""

from typing import Dict, List, Optional


class MotorJugadores:
    """
    Analiza jugadores individualmente.
    
    Preguntas que puede responder:
    - ¿Qué delantero se mueve mejor entre líneas?
    - ¿Qué central pierde más duelos con delanteros rápidos?
    - ¿Qué mediocampista pierde precisión cuando es presionado?
    """

    # ── Cálculo IAI Individual ────────────────────────────────

    def calcular_iai_jugador(self, jugador_data: Dict, posicion: str) -> Dict[str, float]:
        """
        Calcula los componentes del IAI para un jugador según su posición.
        Retorna: iai_general, iai_ofensivo, iai_defensivo, iai_fisico, iai_mental
        """
        pesos = self._get_pesos_por_posicion(posicion)
        
        # IAI Ofensivo
        iai_ofensivo = (
            jugador_data.get("remate_pie", 50) * pesos.get("remate", 0) +
            jugador_data.get("pase_corto", 50) * pesos.get("pase", 0) +
            jugador_data.get("regate", 50) * pesos.get("regate", 0) +
            jugador_data.get("vision", 50) * pesos.get("vision", 0) +
            jugador_data.get("movimiento_entre_lineas", 50) * pesos.get("movimiento", 0)
        )
        
        # IAI Defensivo
        iai_defensivo = (
            jugador_data.get("marca", 50) * pesos.get("marca", 0) +
            jugador_data.get("intercepciones", 50) * pesos.get("intercepciones", 0) +
            jugador_data.get("entrada", 50) * pesos.get("entrada", 0) +
            jugador_data.get("posicionamiento", 50) * pesos.get("posicionamiento_def", 0)
        )
        
        # IAI Físico
        iai_fisico = (
            jugador_data.get("velocidad", 50) * 0.25 +
            jugador_data.get("resistencia", 50) * 0.25 +
            jugador_data.get("fuerza", 50) * 0.25 +
            jugador_data.get("aceleracion", 50) * 0.25
        )
        
        # IAI Mental
        iai_mental = (
            jugador_data.get("decision", 50) * 0.25 +
            jugador_data.get("compostura", 50) * 0.25 +
            jugador_data.get("concentracion", 50) * 0.25 +
            jugador_data.get("inteligencia_tactica", 50) * 0.25
        )
        
        # IAI General ponderado por posición
        iai_general = (
            iai_ofensivo * pesos.get("peso_ofensivo", 0.4) +
            iai_defensivo * pesos.get("peso_defensivo", 0.3) +
            iai_fisico * 0.15 +
            iai_mental * 0.15
        )
        
        return {
            "iai_general": round(iai_general, 1),
            "iai_ofensivo": round(iai_ofensivo, 1),
            "iai_defensivo": round(iai_defensivo, 1),
            "iai_fisico": round(iai_fisico, 1),
            "iai_mental": round(iai_mental, 1),
        }

    def detectar_vulnerabilidades(self, jugador_data: Dict, posicion: str) -> List[str]:
        """
        Detecta las vulnerabilidades específicas de un jugador.
        Esta información es clave para el análisis táctico.
        """
        vulnerabilidades = []
        
        # Error bajo presión
        if jugador_data.get("error_bajo_presion", 0) > 60:
            vulnerabilidades.append(
                f"Pierde el balón frecuentemente cuando es presionado ({jugador_data.get('error_bajo_presion')}%)"
            )
        
        # Pierna mala
        if jugador_data.get("pierna_mala", 50) < 45:
            vulnerabilidades.append(
                "Baja precisión con la pierna menos hábil — se puede forzar a ese lado"
            )
        
        # Primer control
        if jugador_data.get("error_primer_control", 0) > 50:
            vulnerabilidades.append(
                "Primer control deficiente — vulnerable cuando recibe el balón de espaldas"
            )
        
        # Específico por posición
        if posicion in ["CD", "CI", "LD", "LI"]:
            if jugador_data.get("velocidad", 50) < 55:
                vulnerabilidades.append(
                    "Defensor lento — vulnerable al espacio a la espalda con delanteros rápidos"
                )
            if jugador_data.get("cobertura_espacios", 50) < 50:
                vulnerabilidades.append(
                    "Deja espacios defensivos — puede ser explotado en transiciones"
                )
        
        if posicion in ["ED", "EI"]:
            if jugador_data.get("error_precision_centros", 0) > 55:
                vulnerabilidades.append(
                    "Baja precisión en centros — puede ser contraproducente en ataque"
                )
        
        if posicion == "DC":
            if jugador_data.get("error_definicion", 0) > 50:
                vulnerabilidades.append(
                    "Definición inconsistente — genera oportunidades pero no siempre convierte"
                )
        
        if posicion == "PO":
            if jugador_data.get("error_salida_portero", 0) > 40:
                vulnerabilidades.append(
                    "Errores en salidas — puede ser sorprendido con globos o tiros lejanos"
                )
        
        return vulnerabilidades

    def detectar_fortalezas(self, jugador_data: Dict, posicion: str) -> List[str]:
        """Detecta las fortalezas específicas de un jugador."""
        fortalezas = []
        
        if jugador_data.get("movimiento_entre_lineas", 50) > 80:
            fortalezas.append("Se mueve muy bien entre líneas — difícil de marcar")
        
        if jugador_data.get("velocidad", 50) > 85:
            fortalezas.append("Velocidad excepcional — activo en profundidad")
        
        if jugador_data.get("liderazgo", 50) > 80:
            fortalezas.append("Líder del equipo — eleva el rendimiento colectivo")
        
        if jugador_data.get("rendimiento_partidos_grandes", 50) > 75:
            fortalezas.append("Rendimiento elevado en partidos grandes")
        
        if jugador_data.get("compostura", 50) > 80:
            fortalezas.append("Muy calmado bajo presión — fiable en momentos decisivos")
        
        return fortalezas

    def comparar_jugadores(
        self, jugador1: Dict, jugador2: Dict,
        atributos: Optional[List[str]] = None
    ) -> Dict:
        """Compara dos jugadores en atributos específicos o en general."""
        if atributos is None:
            atributos = ["velocidad", "pase_corto", "regate", "remate_pie", "decision", "resistencia"]
        
        comparacion = {}
        for attr in atributos:
            val1 = jugador1.get(attr, 50)
            val2 = jugador2.get(attr, 50)
            ganador = jugador1.get("nombre", "J1") if val1 > val2 else jugador2.get("nombre", "J2")
            comparacion[attr] = {
                jugador1.get("nombre", "J1"): val1,
                jugador2.get("nombre", "J2"): val2,
                "ventaja": ganador,
                "diferencia": round(abs(val1 - val2), 1)
            }
        
        return comparacion

    # ── Pesos por posición ────────────────────────────────────

    def _get_pesos_por_posicion(self, posicion: str) -> Dict[str, float]:
        pesos_base = {
            "remate": 0.0, "pase": 0.0, "regate": 0.0, "vision": 0.0,
            "movimiento": 0.0, "marca": 0.0, "intercepciones": 0.0,
            "entrada": 0.0, "posicionamiento_def": 0.0,
            "peso_ofensivo": 0.3, "peso_defensivo": 0.5
        }
        
        if posicion == "PO":
            return {**pesos_base, "peso_ofensivo": 0.1, "peso_defensivo": 0.7,
                    "marca": 0.3, "intercepciones": 0.3, "entrada": 0.2, "posicionamiento_def": 0.2}
        elif posicion in ["CD", "CI"]:
            return {**pesos_base, "peso_ofensivo": 0.2, "peso_defensivo": 0.6,
                    "pase": 0.3, "vision": 0.2, "movimiento": 0.0, "remate": 0.2, "regate": 0.3,
                    "marca": 0.35, "intercepciones": 0.3, "entrada": 0.25, "posicionamiento_def": 0.1}
        elif posicion in ["LD", "LI"]:
            return {**pesos_base, "peso_ofensivo": 0.4, "peso_defensivo": 0.4,
                    "pase": 0.2, "regate": 0.3, "movimiento": 0.2, "remate": 0.3,
                    "marca": 0.3, "intercepciones": 0.3, "entrada": 0.2, "posicionamiento_def": 0.2}
        elif posicion == "MCD":
            return {**pesos_base, "peso_ofensivo": 0.25, "peso_defensivo": 0.55,
                    "pase": 0.4, "vision": 0.3, "movimiento": 0.3,
                    "marca": 0.3, "intercepciones": 0.4, "entrada": 0.2, "posicionamiento_def": 0.1}
        elif posicion in ["MC", "MCO"]:
            return {**pesos_base, "peso_ofensivo": 0.5, "peso_defensivo": 0.3,
                    "pase": 0.3, "vision": 0.3, "regate": 0.2, "movimiento": 0.2,
                    "marca": 0.2, "intercepciones": 0.4, "entrada": 0.2, "posicionamiento_def": 0.2}
        elif posicion in ["ED", "EI"]:
            return {**pesos_base, "peso_ofensivo": 0.65, "peso_defensivo": 0.15,
                    "remate": 0.3, "regate": 0.4, "velocidad": 0.3,
                    "marca": 0.2, "intercepciones": 0.4, "entrada": 0.2, "posicionamiento_def": 0.2}
        elif posicion == "DC":
            return {**pesos_base, "peso_ofensivo": 0.75, "peso_defensivo": 0.1,
                    "remate": 0.4, "cabeceo": 0.2, "movimiento": 0.2, "regate": 0.2,
                    "marca": 0.2, "intercepciones": 0.4, "entrada": 0.2, "posicionamiento_def": 0.2}
        
        return pesos_base


motor_jugadores = MotorJugadores()
