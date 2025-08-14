-- #####################################################################
-- ## Esquema de Base de Datos v3.0 (Preparado para Crecimiento)      ##
-- ## --------------------------------------------------------------- ##
-- ## Modelo actualizado que alinea 'dim_parlamentario' y 'dim_partidos'
-- ## con el script 'etl_roster.py' y expande las tablas de proyectos
-- ## de ley y votaciones para los próximos scripts ETL.
-- #####################################################################

-- ==========================================================
-- 1. TABLAS DE DIMENSIONES (Describen entidades)
-- ==========================================================

-- Tabla para almacenar información detallada de los parlamentarios.
-- Poblada por: src/etl/etl_roster.py
CREATE TABLE dim_parlamentario (
    mp_uid INTEGER PRIMARY KEY AUTOINCREMENT,
    diputadoid TEXT UNIQUE,
    nombre_completo TEXT NOT NULL,
    nombre_propio TEXT,
    apellido_paterno TEXT,
    apellido_materno TEXT,
    genero TEXT,
    fecha_nacimiento DATE,
    lugar_nacimiento TEXT,
    distrito INTEGER,
    fechas_mandato TEXT, -- Campo mantenido por si se usa a futuro.
    bcn_uri TEXT,
    url_foto TEXT,
    twitter_handle TEXT,
    sitio_web_personal TEXT,
    titulo_honorifico TEXT,
    profesion TEXT,
    nacionalidad TEXT,
    url_historia_politica TEXT,
    fecha_extraccion DATE DEFAULT CURRENT_DATE
);

-- Tabla para gestionar diferentes nombres o alias de un parlamentario.
-- Poblada por: (futuro script, ej: alias_resolver.py)
CREATE TABLE parlamentario_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    alias TEXT NOT NULL UNIQUE,             -- E.g., "Pepe Auth", "Diputada Jiles".
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

-- Tabla de partidos políticos, enriquecida con datos de la BCN.
-- Poblada por: src/etl/etl_roster.py
CREATE TABLE dim_partidos (
    partido_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_partido TEXT NOT NULL UNIQUE,
    nombre_alternativo TEXT,
    sigla TEXT,
    fecha_fundacion TEXT,
    sitio_web TEXT,
    url_historia_politica TEXT,
    url_logo TEXT,
    ultima_actualizacion DATETIME
);

-- Tabla para las coaliciones políticas.
-- Poblada por: (futuro script)
CREATE TABLE dim_coaliciones (
    coalicion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_coalicion TEXT NOT NULL UNIQUE
);

-- ----------------------------------------------------------
-- NUEVO: Tabla de proyectos de ley enriquecida para alinearse
-- con el futuro script 'etl_bills.py'.
-- ----------------------------------------------------------
CREATE TABLE bills (
    bill_id TEXT PRIMARY KEY,               -- E.g., "15665-07", extraído de <NumeroBoletin>
    titulo TEXT,                            -- Extraído de <Nombre>
    fecha_ingreso DATE,                     -- Extraído de <FechaIngreso>
    iniciativa TEXT,                        -- 'Moción' o 'Mensaje', extraído de <TipoIniciativa>
    origen TEXT,                            -- 'C.D.' o 'Senado', extraído de <CamaraOrigen>
    estado_actual TEXT,                     -- Para poblar a futuro.
    url_detalle TEXT                        -- Para poblar a futuro con la URL a la ficha del proyecto.
);


-- ==========================================================
-- 2. TABLAS DE HECHOS Y RELACIONES (Registran eventos)
-- ==========================================================

-- Historial de militancia de los parlamentarios en partidos.
-- Poblada por: src/etl/etl_roster.py
CREATE TABLE militancia_historial (
    militancia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    partido_id INTEGER NOT NULL,
    coalicion_id INTEGER,                   -- No poblado por el script de roster actual.
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE,
    FOREIGN KEY (partido_id) REFERENCES dim_partidos(partido_id) ON DELETE CASCADE
);

-- Autores de los proyectos de ley.
-- Poblada por: src/etl/etl_bills.py (futuro)
CREATE TABLE bill_authors (
    bill_id TEXT NOT NULL,
    mp_uid INTEGER NOT NULL,
    PRIMARY KEY (bill_id, mp_uid),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- NUEVO: Estructura de votaciones dividida en dos tablas para
-- reflejar la granularidad de la API y el script 'etl_votes.py'.
-- ----------------------------------------------------------

-- Tabla para las sesiones de votación. Almacena la información general del evento.
-- Poblada por: src/etl/etl_votes.py (futuro)
CREATE TABLE sesiones_votacion (
    sesion_votacion_id INTEGER PRIMARY KEY, -- ID de la votación desde la API (<Id>).
    bill_id TEXT,
    tema TEXT NOT NULL,                     -- La descripción completa del asunto votado.
    fecha DATE NOT NULL,
    resultado_general TEXT,                 -- 'Aprobado', 'Rechazado'.
    quorum_aplicado TEXT,                   -- 'Quórum Simple', '3/5', etc.
    a_favor_total INTEGER,
    en_contra_total INTEGER,
    abstencion_total INTEGER,
    pareo_total INTEGER,
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE
);

-- Tabla para el voto individual de cada parlamentario por sesión.
-- Poblada por: src/etl/etl_votes.py (futuro)
CREATE TABLE votos_parlamentario (
    voto_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_votacion_id INTEGER NOT NULL,
    mp_uid INTEGER NOT NULL,
    voto TEXT NOT NULL,                     -- 'A Favor', 'En Contra', 'Abstención', 'Pareo'.
    FOREIGN KEY (sesion_votacion_id) REFERENCES sesiones_votacion(sesion_votacion_id) ON DELETE CASCADE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

-- Turnos de palabra o discursos de los parlamentarios.
-- Poblada por: src/etl/etl_transcripts.py (futuro)
CREATE TABLE speech_turns (
    speech_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    texto TEXT NOT NULL,
    inicio_seg REAL,
    fin_seg REAL,
    fecha DATE,
    comision TEXT,
    tema TEXT,
    url_video TEXT,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

-- Interacciones (e.g., críticas, apoyos) entre parlamentarios.
-- Poblada por: src/etl/etl_news_graph.py (futuro)
CREATE TABLE interactions (
    interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_uid INTEGER NOT NULL,
    target_uid INTEGER NOT NULL,
    tipo TEXT NOT NULL,                     -- 'critica', 'apoya', 'menciona'.
    fecha DATE NOT NULL,
    fuente TEXT,
    snippet TEXT,
    FOREIGN KEY (source_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE,
    FOREIGN KEY (target_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

-- Membresías de los parlamentarios en comisiones.
CREATE TABLE comision_membresias (
    membresia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    nombre_comision TEXT NOT NULL,
    rol TEXT,                               -- E.g., "Presidente", "Miembro".
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

-- Resultados electorales de los parlamentarios.
CREATE TABLE electoral_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    fecha_eleccion DATE NOT NULL,
    cargo TEXT,
    distrito INTEGER,
    total_votos INTEGER,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);


-- ==========================================================
-- 3. ÍNDICES PARA OPTIMIZACIÓN DE CONSULTAS
-- ==========================================================

-- Índices para las nuevas tablas de votaciones
CREATE INDEX IF NOT EXISTS idx_sesiones_votacion_bill_id ON sesiones_votacion(bill_id);
CREATE INDEX IF NOT EXISTS idx_votos_parlamentario_sesion_mp ON votos_parlamentario(sesion_votacion_id, mp_uid);

-- Otros índices
CREATE INDEX IF NOT EXISTS idx_militancia_mp ON militancia_historial(mp_uid);
CREATE INDEX IF NOT EXISTS idx_speech_mp_date ON speech_turns(mp_uid, fecha);
CREATE INDEX IF NOT EXISTS idx_interactions_source_target ON interactions(source_uid, target_uid);
CREATE INDEX IF NOT EXISTS idx_bill_authors_bill_id ON bill_authors(bill_id);