ubuntu@sandbox:~ $ cat /home/sandbox/athena-app/backend/database/migrations.py
"""
PROYECTO ATHENA — Migraciones de Base de Datos
Ejecuta migraciones incrementales al inicio para mantener el esquema actualizado.
"""

from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def run_migrations(engine):
    """Ejecuta todas las migraciones pendientes de forma segura."""
    
    # Lista ordenada de migraciones. Cada una falla silenciosamente si ya fue aplicada.
    migrations = [
        # ── v0.0.1 → v0.0.2: Renombrar columnas en equipos ──────────────────
        # formacion → formacion_habitual
        "ALTER TABLE equipos RENAME COLUMN formacion TO formacion_habitual",
        # estilo_ataque → estilo_ofensivo
        "ALTER TABLE equipos RENAME COLUMN estilo_ataque TO estilo_ofensivo",
        # estilo_defensa → estilo_defensivo
        "ALTER TABLE equipos RENAME COLUMN estilo_defensa TO estilo_defensivo",
        # velocidad → velocidad_juego
        "ALTER TABLE equipos RENAME COLUMN velocidad TO velocidad_juego",
        # juego_banda → juego_bandas
        "ALTER TABLE equipos RENAME COLUMN juego_banda TO juego_bandas",
        # transiciones → transiciones_ofensivas
        "ALTER TABLE equipos RENAME COLUMN transiciones TO transiciones_ofensivas",

        # ── v0.0.2: Agregar columnas faltantes en partidos ───────────────────
        "ALTER TABLE partidos ADD COLUMN IF NOT EXISTS api_match_id VARCHAR(50)",
        "ALTER TABLE partidos ADD COLUMN IF NOT EXISTS temporada VARCHAR(20)",
        "ALTER TABLE partidos ADD COLUMN IF NOT EXISTS estado VARCHAR(30) DEFAULT 'programado'",

        # ── v0.0.2: Agregar/renombrar columnas en ligas ──────────────────────
        "ALTER TABLE ligas RENAME COLUMN temporada TO temporada_actual",
        "ALTER TABLE ligas ADD COLUMN IF NOT EXISTS temporada_actual VARCHAR(20)",

        # ── v0.0.2: Agregar columnas nuevas en equipos si no existen ─────────
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS fortaleza_local FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS rendimiento_visitante FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS xg_favor_promedio FLOAT DEFAULT 1.2",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS xg_contra_promedio FLOAT DEFAULT 1.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS posesion_promedio FLOAT DEFAULT 50.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS corners_promedio FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS tiros_promedio FLOAT DEFAULT 0.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS faltas_promedio FLOAT DEFAULT 0.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS tarjetas_amarillas_promedio FLOAT DEFAULT 0.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS tarjetas_rojas_promedio FLOAT DEFAULT 0.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS victorias_local INT DEFAULT 0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS victorias_visitante INT DEFAULT 0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS agresividad_tactica FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS creatividad FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS disciplina_tactica FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS compacidad_defensiva FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS altura_linea_defensiva FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS pressing_trigger VARCHAR(200)",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS formacion_alternativa VARCHAR(20)",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS estilo_ofensivo VARCHAR(50)",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS estilo_defensivo VARCHAR(50)",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS cambio_sistema_minuto INT",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS sistema_segunda_parte VARCHAR(20)",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS tendencia_goles_primeros FLOAT DEFAULT 0.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS tendencia_goles_ultimos FLOAT DEFAULT 0.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS reaccion_desventaja FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS gestion_ventaja FLOAT DEFAULT 5.0",
        "ALTER TABLE equipos ADD COLUMN IF NOT EXISTS transiciones_defensivas FLOAT DEFAULT 5.0",
    ]

    applied = 0
    skipped = 0

    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
                applied += 1
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                skipped += 1

    logger.info(f"✅ Migraciones: {applied} aplicadas, {skipped} omitidas (ya existían)")
    print(f"✅ Migraciones: {applied} aplicadas, {skipped} omitidas (ya existían)")
