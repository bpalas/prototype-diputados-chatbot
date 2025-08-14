-- ######################################################################
-- ## Esquema de Base de Datos v3.1 (Modular y Mejorado)               ##
-- ## ---------------------------------------------------------------- ##
-- ## Modelo optimizado para análisis y RAG, organizado en módulos     ##
-- ## lógicos para mayor claridad y escalabilidad.                     ##
-- ## v3.1: Añade la tabla dim_legislatura.                            ##
-- ######################################################################

-- ======================================================================
-- MÓDULO 1: CORE - ENTIDADES PRINCIPALES (El "Quién")
-- ======================================================================
-- Describe las personas, grupos y conceptos fundamentales del sistema.

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
    bcn_uri TEXT,
    url_foto TEXT,
    twitter_handle TEXT,
    sitio_web_personal TEXT,
    profesion TEXT,
    url_historia_politica TEXT,
    fecha_extraccion DATE DEFAULT (date('now'))
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

-- NUEVA TABLA: Basada en la documentación doc_api_camara.md
CREATE TABLE dim_legislatura (
    legislatura_id INTEGER PRIMARY KEY,
    numero INTEGER,
    fecha_inicio DATE,
    fecha_termino DATE,
    tipo TEXT -- Ejemplo: 'Ordinaria'
);


-- ======================================================================
-- MÓDULO 2: TRAYECTORIA POLÍTICA (El "Cómo llegaron aquí")
-- ======================================================================
-- Registra el historial, cargos y antecedentes de los parlamentarios.

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
-- Registra los eventos y artefactos del proceso legislativo formal.

CREATE TABLE bills (
    bill_id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL,
    resumen TEXT,
    fecha_ingreso DATE,
    etapa TEXT,
    iniciativa TEXT,
    origen TEXT,
    urgencia TEXT,
    resultado_final TEXT,
    ley_numero TEXT,
    ley_fecha_publicacion DATE
);

CREATE TABLE bill_authors (
    bill_id TEXT NOT NULL,
    mp_uid INTEGER NOT NULL,
    PRIMARY KEY (bill_id, mp_uid),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

CREATE TABLE sesiones_votacion (
    sesion_votacion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id TEXT NOT NULL,
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
    voto_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_votacion_id INTEGER NOT NULL,
    mp_uid INTEGER NOT NULL,
    voto TEXT NOT NULL CHECK (voto IN ('A Favor', 'En Contra', 'Abstención', 'Pareo')),
    FOREIGN KEY (sesion_votacion_id) REFERENCES sesiones_votacion(sesion_votacion_id) ON DELETE CASCADE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- ======================================================================
-- MÓDULO 4: ACTIVIDAD PÚBLICA (El "Qué dicen")
-- ======================================================================
-- Captura discursos e interacciones del debate público.

CREATE TABLE speech_turns (
    speech_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    sesion_votacion_id INTEGER, -- Opcional, para vincular a una votación
    comision_id INTEGER,        -- Opcional, para vincular a una comisión
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
-- Índices para acelerar las consultas más comunes.

CREATE INDEX idx_votos_parlamentario_mp_sesion ON votos_parlamentario(mp_uid, sesion_votacion_id);
CREATE INDEX idx_speech_mp_date ON speech_turns(mp_uid, fecha);
CREATE INDEX idx_interactions_source_target ON interactions(source_uid, target_uid);
CREATE INDEX idx_militancia_mp ON militancia_historial(mp_uid);
CREATE INDEX idx_mandatos_mp ON parlamentario_mandatos(mp_uid);
CREATE INDEX idx_membresias_mp ON comision_membresias(mp_uid);