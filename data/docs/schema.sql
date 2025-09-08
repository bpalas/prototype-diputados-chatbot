-- ######################################################################
-- ## Esquema de Base de Datos v5.3 (Híbrido y Consolidado)            ##
-- ## ---------------------------------------------------------------- ##
-- ## Añade `bcn_historia_id` a `dim_normas`, `senadorid` a            ##
-- ## `dim_parlamentario` y nuevas tablas para `Ministerios Patrocinantes`. ##
-- ######################################################################

-- Configuración inicial para mejor rendimiento y consistencia
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ======================================================================
-- MÓDULO 1: CORE - ENTIDADES PRINCIPALES (El "Quién")
-- ======================================================================
CREATE TABLE dim_parlamentario (
    mp_uid INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    nombre_propio TEXT,
    apellido_paterno TEXT,
    apellido_materno TEXT,
    genero TEXT CHECK (genero IN ('Masculino', 'Femenino')),
    fecha_nacimiento DATE,
    lugar_nacimiento TEXT,
    diputadoid TEXT UNIQUE,
    senadorid TEXT UNIQUE, -- NUEVO: ID de Senador de la API de la Cámara
    bcn_person_id TEXT UNIQUE,
    bcn_uri TEXT,
    url_foto TEXT,
    twitter_handle TEXT,
    sitio_web_personal TEXT,
    profesion TEXT,
    url_historia_politica TEXT,
    fecha_extraccion DATE DEFAULT (date('now'))
);

CREATE TABLE dim_periodo_legislativo (
    periodo_id INTEGER PRIMARY KEY,
    nombre_periodo TEXT NOT NULL,
    fecha_inicio DATE,
    fecha_termino DATE
);

CREATE TABLE parlamentario_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    alias TEXT NOT NULL UNIQUE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

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

CREATE TABLE dim_coaliciones (
    coalicion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_coalicion TEXT NOT NULL UNIQUE
);

CREATE TABLE dim_comisiones (
    comision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_comision TEXT NOT NULL UNIQUE,
    tipo TEXT CHECK (tipo IN ('Permanente', 'Especial Investigadora', 'Bicameral'))
);

CREATE TABLE dim_legislatura (
    legislatura_id INTEGER PRIMARY KEY,
    numero INTEGER,
    fecha_inicio DATE,
    fecha_termino DATE,
    tipo TEXT
);

CREATE TABLE dim_materias (
    materia_id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE
);

CREATE TABLE dim_normas (
    norma_id INTEGER PRIMARY KEY,        -- Llave interna para joins rápidos
    bcn_norma_id TEXT UNIQUE,            -- Llave externa y única de la BCN para referencias de LeyChile (ej: 235507)
    bcn_historia_id TEXT UNIQUE,         -- ID interno de la BCN para la página "Historia de la Ley" (ej: 5755)
    numero_norma TEXT NOT NULL,
    tipo_norma TEXT,
    titulo_norma TEXT,
    fecha_publicacion DATE,
    organismo_promulgador TEXT,
    url_ley_chile TEXT
);

CREATE TABLE dim_ministerios ( -- NUEVO: Tabla para ministerios
    ministerio_id INTEGER PRIMARY KEY AUTOINCREMENT,
    camara_ministerio_id INTEGER UNIQUE, -- ID de la Cámara de Diputados para ministerios
    nombre_ministerio TEXT NOT NULL UNIQUE
);

-- ======================================================================
-- MÓDULO 2: TRAYECTORIA POLÍTICA (El "Cómo llegaron aquí")
-- ======================================================================
CREATE TABLE parlamentario_mandatos (
    mandato_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    cargo TEXT NOT NULL CHECK (cargo IN ('Diputado', 'Senador')),
    distrito INTEGER,
    partido_id_mandato INTEGER,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE,
    FOREIGN KEY (partido_id_mandato) REFERENCES dim_partidos(partido_id)
);

CREATE TABLE militancia_historial (
    militancia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    partido_id INTEGER NOT NULL,
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE,
    FOREIGN KEY (partido_id) REFERENCES dim_partidos(partido_id)
);

CREATE TABLE comision_membresias (
    membresia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    comision_id INTEGER NOT NULL,
    rol TEXT DEFAULT 'Miembro',
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE,
    FOREIGN KEY (comision_id) REFERENCES dim_comisiones(comision_id)
);

CREATE TABLE electoral_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    fecha_eleccion DATE NOT NULL,
    cargo TEXT,
    distrito INTEGER,
    total_votos INTEGER,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

CREATE TABLE educacion (
    edu_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    titulo TEXT,
    institucion TEXT,
    ano_graduacion INTEGER,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

-- ======================================================================
-- MÓDULO 3: ACTIVIDAD LEGISLATIVA (El "Qué hacen")
-- ======================================================================
CREATE TABLE bills (
    bill_id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL,
    resumen TEXT,
    tipo_proyecto TEXT,
    fecha_ingreso DATE,
    etapa TEXT,
    subetapa TEXT,
    iniciativa TEXT,
    origen TEXT,
    urgencia TEXT,
    resultado_final TEXT,
    estado TEXT NOT NULL,
    refundidos TEXT,
    numero_ley TEXT, -- Columna para el número de ley limpio.
    norma_id INTEGER,
    fecha_actualizacion DATETIME,
    FOREIGN KEY (norma_id) REFERENCES dim_normas(norma_id)
);

CREATE TABLE bill_authors (
    bill_id TEXT NOT NULL,
    mp_uid INTEGER NOT NULL,
    PRIMARY KEY (bill_id, mp_uid),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

CREATE TABLE bill_ministerios_patrocinantes ( -- NUEVO: Para vincular ministerios a proyectos de ley
    bill_id TEXT NOT NULL,
    ministerio_id INTEGER NOT NULL,
    PRIMARY KEY (bill_id, ministerio_id),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
    FOREIGN KEY (ministerio_id) REFERENCES dim_ministerios(ministerio_id)
);

CREATE TABLE bill_tramites (
    tramite_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id TEXT NOT NULL,
    fecha_tramite DATE NOT NULL,
    descripcion TEXT NOT NULL,
    etapa_general TEXT,
    etapa_especifica TEXT,
    camara TEXT,
    sesion TEXT,
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE
);

CREATE TABLE bill_documentos (
    documento_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id TEXT NOT NULL,
    tramite_id INTEGER,
    tipo_documento TEXT NOT NULL,
    url_documento TEXT NOT NULL UNIQUE, -- Añadimos UNIQUE para evitar duplicados si hay re-ejecuciones
    fecha_documento DATE,
    descripcion TEXT, -- Añadimos para guardar el texto del enlace si es descriptivo
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
    FOREIGN KEY (tramite_id) REFERENCES bill_tramites(tramite_id)
);

CREATE TABLE bill_materias (
    bill_id TEXT NOT NULL,
    materia_id INTEGER NOT NULL,
    PRIMARY KEY (bill_id, materia_id),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
    FOREIGN KEY (materia_id) REFERENCES dim_materias(materia_id)
);

CREATE TABLE sesiones_votacion (
    sesion_votacion_id INTEGER PRIMARY KEY,
    bill_id TEXT NOT NULL,
    camara TEXT NOT NULL,
    fecha DATE NOT NULL,
    tema TEXT,
    resultado_general TEXT,
    quorum_aplicado TEXT,
    a_favor_total INTEGER,
    en_contra_total INTEGER,
    abstencion_total INTEGER,
    pareo_total INTEGER,
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE
);

CREATE TABLE votos_parlamentario (
    voto_id INTEGER PRIMARY KEY,
    sesion_votacion_id INTEGER NOT NULL,
    mp_uid INTEGER NOT NULL,
    voto TEXT NOT NULL,
    FOREIGN KEY (sesion_votacion_id) REFERENCES sesiones_votacion(sesion_votacion_id) ON DELETE CASCADE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

CREATE TABLE entity_sources (
    source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    last_checked_at DATETIME
);

-- ======================================================================
-- MÓDULO 4: ACTIVIDAD PÚBLICA (El "Qué dicen")
-- ======================================================================
CREATE TABLE speech_turns (
    speech_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    sesion_votacion_id INTEGER,
    comision_id INTEGER,
    texto TEXT NOT NULL,
    fecha DATE,
    tema TEXT,
    url_video TEXT,
    inicio_seg REAL,
    fin_seg REAL,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (sesion_votacion_id) REFERENCES sesiones_votacion(sesion_votacion_id),
    FOREIGN KEY (comision_id) REFERENCES dim_comisiones(comision_id)
);

CREATE TABLE interactions (
    interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_uid INTEGER NOT NULL,
    target_uid INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('critica', 'apoya', 'menciona')),
    fecha DATE NOT NULL,
    fuente TEXT,
    snippet TEXT,
    FOREIGN KEY (source_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (target_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- ======================================================================
-- MÓDULO 5: ÍNDICES PARA OPTIMIZACIÓN
-- ======================================================================
CREATE INDEX idx_votos_parlamentario_mp_sesion ON votos_parlamentario(mp_uid, sesion_votacion_id);
CREATE INDEX idx_speech_mp_date ON speech_turns(mp_uid, fecha);
CREATE INDEX idx_interactions_source_target ON interactions(source_uid, target_uid);
CREATE INDEX idx_militancia_mp ON militancia_historial(mp_uid);
CREATE INDEX idx_mandatos_mp ON parlamentario_mandatos(mp_uid);
CREATE INDEX idx_membresias_mp ON comision_membresias(mp_uid);
CREATE INDEX idx_bills_estado ON bills(estado);
CREATE INDEX idx_entity_sources_lookup ON entity_sources(entity_id, entity_type);
CREATE INDEX idx_bills_numero_ley ON bills(numero_ley);
CREATE INDEX idx_dim_normas_bcn_historia_id ON dim_normas(bcn_historia_id);
CREATE INDEX idx_dim_parlamentario_senadorid ON dim_parlamentario(senadorid); -- NUEVO ÍNDICE
CREATE INDEX idx_dim_ministerios_camara_id ON dim_ministerios(camara_ministerio_id); -- NUEVO ÍNDICE
CREATE INDEX idx_bill_ministerios_patrocinantes_bill_id ON bill_ministerios_patrocinantes(bill_id); -- NUEVO ÍNDICE
CREATE INDEX idx_bill_ministerios_patrocinantes_ministerio_id ON bill_ministerios_patrocinantes(ministerio_id); -- NUEVO ÍNDICE