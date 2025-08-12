-- ###########################################################
-- ## Esquema de Base de Datos v2.1 (Enriquecido)           ##
-- ## ----------------------------------------------------- ##
-- ## Modelo consolidado con la tabla dim_partidos expandida ##
-- ## y optimizada con datos de la BCN.                      ##
-- ###########################################################

-- ==========================================================
-- 1. TABLAS DE DIMENSIONES (Describen entidades)
-- ==========================================================

-- Tabla para almacenar información detallada de los parlamentarios.
CREATE TABLE dim_parlamentario (
    mp_uid INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    nombre_propio TEXT,
    apellido_paterno TEXT,
    apellido_materno TEXT,
    genero TEXT,
    fecha_nacimiento DATE,
    lugar_nacimiento TEXT,
    distrito INTEGER,
    fechas_mandato TEXT,
    diputadoid TEXT UNIQUE,
    wikidata_qid TEXT,
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
CREATE TABLE parlamentario_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    alias TEXT NOT NULL UNIQUE,             -- E.g., "Pepe Auth", "Diputada Jiles".
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- CAMBIO: Tabla de partidos políticos enriquecida con datos de la BCN.
CREATE TABLE dim_partidos (
    partido_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_partido TEXT NOT NULL UNIQUE,
    nombre_alternativo TEXT,                -- CAMBIO: Añadido para nombres como "Unión Demócrata Independiente".
    sigla TEXT,
    fecha_fundacion TEXT,                   -- CAMBIO: Tipo a TEXT para manejar solo el año (ej: "1983").
    sitio_web TEXT,
    url_historia_politica TEXT,             -- CAMBIO: Añadido para enlace a la página de historia política en BCN.
    url_logo TEXT,                          -- CAMBIO: Añadido para URL del logo del partido.
    ultima_actualizacion TEXT               -- CAMBIO: Añadido para la fecha de última actualización desde BCN.
);

-- Tabla para las coaliciones políticas.
CREATE TABLE dim_coaliciones (
    coalicion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_coalicion TEXT NOT NULL UNIQUE
);

-- Tabla para almacenar información sobre los proyectos de ley.
CREATE TABLE bills (
    bill_id TEXT PRIMARY KEY,               -- E.g., "15665-07".
    resumen TEXT NOT NULL,
    comision TEXT,
    resultado TEXT,
    fecha_ingreso DATE
);

-- ==========================================================
-- 2. TABLAS DE HECHOS Y RELACIONES (Registran eventos)
-- ==========================================================

-- Historial de militancia de los parlamentarios en partidos y coaliciones.
CREATE TABLE militancia_historial (
    militancia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    partido_id INTEGER NOT NULL,
    coalicion_id INTEGER,
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (partido_id) REFERENCES dim_partidos(partido_id),
    FOREIGN KEY (coalicion_id) REFERENCES dim_coaliciones(coalicion_id)
);

-- Autores de los proyectos de ley.
CREATE TABLE bill_authors (
    bill_id TEXT NOT NULL,
    mp_uid INTEGER NOT NULL,
    PRIMARY KEY (bill_id, mp_uid),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id),
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- Registro de los votos de los parlamentarios en proyectos de ley.
CREATE TABLE votes (
    vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    bill_id TEXT NOT NULL,
    voto TEXT NOT NULL,                     -- 'A Favor', 'En Contra', 'Abstención', 'Pareo'.
    fecha DATE NOT NULL,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id)
);

-- Turnos de palabra o discursos de los parlamentarios.
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
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- Interacciones (e.g., críticas, apoyos) entre parlamentarios.
CREATE TABLE interactions (
    interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_uid INTEGER NOT NULL,
    target_uid INTEGER NOT NULL,
    tipo TEXT NOT NULL,                     -- 'critica', 'apoya', 'menciona'.
    fecha DATE NOT NULL,
    fuente TEXT,
    snippet TEXT,
    FOREIGN KEY (source_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (target_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- Formación académica de los parlamentarios.
CREATE TABLE educacion (
    edu_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    titulo TEXT,
    institucion TEXT,
    ano_graduacion INTEGER,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- Membresías de los parlamentarios en comisiones.
CREATE TABLE comision_membresias (
    membresia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    nombre_comision TEXT NOT NULL,
    rol TEXT,                               -- E.g., "Presidente", "Miembro".
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- Resultados electorales de los parlamentarios.
CREATE TABLE electoral_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    fecha_eleccion DATE NOT NULL,
    cargo TEXT,
    distrito INTEGER,
    total_votos INTEGER,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- ==========================================================
-- 3. ÍNDICES PARA OPTIMIZACIÓN DE CONSULTAS
-- ==========================================================

CREATE INDEX idx_votes_mp_bill ON votes(mp_uid, bill_id);
CREATE INDEX idx_speech_mp_date ON speech_turns(mp_uid, fecha);
CREATE INDEX idx_interactions_source_target ON interactions(source_uid, target_uid);
CREATE INDEX idx_militancia_mp ON militancia_historial(mp_uid);