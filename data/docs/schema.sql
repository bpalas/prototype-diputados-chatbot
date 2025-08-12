-- ---------------------------------------------------------------------------
-- Esquema de Base de Datos v2.0 para Chatbot Parlamentario
-- Modelo consolidado, normalizado y corregido.
-- ---------------------------------------------------------------------------

-- 1. TABLAS DE DIMENSIONES (Describen entidades)
-- ---------------------------------------------------------------------------

CREATE TABLE dim_parlamentario (
    mp_uid INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    nombre_propio TEXT,            -- <-- NUEVO
    apellido_paterno TEXT,         -- <-- NUEVO
    apellido_materno TEXT,
    genero TEXT,
    fecha_nacimiento DATE,         -- <-- NUEVO
    lugar_nacimiento TEXT,         -- <-- NUEVO
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
CREATE TABLE parlamentario_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    alias TEXT NOT NULL UNIQUE,                 -- E.g., "Pepe Auth", "Diputada Jiles".
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

CREATE TABLE dim_partidos (
    partido_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_partido TEXT NOT NULL UNIQUE,
    sigla TEXT,
    fecha_fundacion DATE,
    sitio_web TEXT
);

CREATE TABLE dim_coaliciones (
    coalicion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_coalicion TEXT NOT NULL UNIQUE
);

CREATE TABLE bills (
    bill_id TEXT PRIMARY KEY,                   -- E.g., "15665-07".
    resumen TEXT NOT NULL,
    comision TEXT,
    resultado TEXT,
    fecha_ingreso DATE
);

-- 2. TABLAS DE HECHOS Y RELACIONES (Registran eventos y conexiones)
-- ---------------------------------------------------------------------------

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

CREATE TABLE bill_authors (
    bill_id TEXT NOT NULL,
    mp_uid INTEGER NOT NULL,
    PRIMARY KEY (bill_id, mp_uid),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id),
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

CREATE TABLE votes (
    vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    bill_id TEXT NOT NULL,
    voto TEXT NOT NULL,                         -- 'A Favor', 'En Contra', 'Abstención', 'Pareo'.
    fecha DATE NOT NULL,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id)
);

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

CREATE TABLE interactions (
    interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_uid INTEGER NOT NULL,
    target_uid INTEGER NOT NULL,
    tipo TEXT NOT NULL,                         -- 'critica', 'apoya', 'menciona'.
    fecha DATE NOT NULL,
    fuente TEXT,
    snippet TEXT,
    FOREIGN KEY (source_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (target_uid) REFERENCES dim_parlamentario(mp_uid)
);

CREATE TABLE educacion (
    edu_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    titulo TEXT,
    institucion TEXT,
    ano_graduacion INTEGER,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

CREATE TABLE comision_membresias (
    membresia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    nombre_comision TEXT NOT NULL,
    rol TEXT,                                   -- E.g., "Presidente", "Miembro".
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

CREATE TABLE electoral_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    fecha_eleccion DATE NOT NULL,
    cargo TEXT,
    distrito INTEGER,
    total_votos INTEGER,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- 3. ÍNDICES PARA OPTIMIZACIÓN
-- ---------------------------------------------------------------------------

CREATE INDEX idx_votes_mp_bill ON votes(mp_uid, bill_id);
CREATE INDEX idx_speech_mp_date ON speech_turns(mp_uid, fecha);
CREATE INDEX idx_interactions_source_target ON interactions(source_uid, target_uid);
CREATE INDEX idx_militancia_mp ON militancia_historial(mp_uid);