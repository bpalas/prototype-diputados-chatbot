-- ---------------------------------------------------------------------------
-- Esquema de Base de Datos para el Prototipo de Chatbot Parlamentario
--
-- Este script define la estructura de la base de datos SQL que unifica
-- los datos de parlamentarios chilenos desde múltiples fuentes, incluyendo
-- metadatos, votaciones, intervenciones y relaciones políticas.
-- La clave de unificación es 'mp_uid'.
-- ---------------------------------------------------------------------------

-- Tabla Maestra (Dimensión) de Parlamentarios
-- Almacena los metadatos de cada diputado/a. Es la tabla central del sistema.
-- Fuente: API de la Cámara de Diputadas y Diputados.
CREATE TABLE dim_parlamentario (
    mp_uid INTEGER PRIMARY KEY AUTOINCREMENT, -- Identificador único interno del sistema.
    nombre_completo TEXT NOT NULL,            -- Nombre y apellidos.
    genero TEXT,                              -- Género del parlamentario.
    partido TEXT,                             -- Partido político actual.
    distrito INTEGER,                         -- Distrito al que representa.
    fechas_mandato TEXT,                      -- Periodos legislativos (e.g., "2018-2022, 2022-2026").
    diputadoid TEXT,                          -- ID oficial de la API del Congreso.
    wikidata_qid TEXT,                        -- ID de Wikidata para enlaces externos.
    fecha_extraccion DATE DEFAULT CURRENT_DATE -- Fecha en que se actualizaron los datos.
);

-- Proyectos de Ley
-- Contiene información sobre cada proyecto de ley que se somete a votación.
-- Fuente: API del Congreso.
CREATE TABLE bills (
    bill_id TEXT PRIMARY KEY,                 -- Identificador único del proyecto de ley (e.g., "15665-07").
    resumen TEXT NOT NULL,                    -- Descripción o sumario del proyecto.
    autores TEXT,                             -- Autores o mocionantes del proyecto.
    comision TEXT,                            -- Comisión de origen o principal.
    resultado TEXT,                           -- Estado final de la votación (e.g., "Aprobado", "Rechazado").
    fecha_ingreso DATE                        -- Fecha de ingreso del proyecto de ley.
);

-- Votaciones Nominales (Roll-Calls)
-- Registra el voto de cada parlamentario en un proyecto de ley específico.
-- Fuente: API del Congreso.
CREATE TABLE votes (
    vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,                  -- ID del parlamentario que vota (FK).
    bill_id TEXT NOT NULL,                    -- ID del proyecto de ley votado (FK).
    voto TEXT NOT NULL,                       -- Tipo de voto (e.g., 'A Favor', 'En Contra', 'Abstención').
    fecha DATE NOT NULL,                      -- Fecha de la votación.
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id)
);

-- Turnos de Palabra en Comisiones
-- Almacena las transcripciones de las intervenciones de los parlamentarios.
-- Fuente: Transcripciones de videos de YouTube.
CREATE TABLE speech_turns (
    speech_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,                  -- ID del parlamentario que habla (FK).
    texto TEXT NOT NULL,                      -- Contenido de la intervención.
    inicio_seg REAL,                          -- Timestamp de inicio del turno en el video.
    fin_seg REAL,                             -- Timestamp de fin del turno en el video.
    fecha DATE,                               -- Fecha de la sesión.
    comision TEXT,                            -- Nombre de la comisión legislativa.
    tema TEXT,                                -- Tema principal de la discusión.
    url_video TEXT,                           -- URL del video de origen.
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- Grafo de Interacciones Políticas
-- Modela relaciones entre parlamentarios extraídas de fuentes de prensa.
-- Fuente: Monitoreo de medios de comunicación.
CREATE TABLE interactions (
    interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_uid INTEGER NOT NULL,              -- Parlamentario que origina la interacción (FK).
    target_uid INTEGER NOT NULL,              -- Parlamentario que recibe la interacción (FK).
    tipo TEXT NOT NULL,                       -- Tipo de relación (e.g., 'critica', 'apoya', 'menciona').
    fecha DATE NOT NULL,                      -- Fecha del evento.
    fuente TEXT,                              -- Medio o URL de la fuente de prensa.
    snippet TEXT,                             -- Fragmento de texto donde se evidencia la interacción.
    FOREIGN KEY (source_uid) REFERENCES dim_parlamentario(mp_uid),
    FOREIGN KEY (target_uid) REFERENCES dim_parlamentario(mp_uid)
);

-- Índices para optimizar las consultas
CREATE INDEX idx_votes_mp_bill ON votes(mp_uid, bill_id);
CREATE INDEX idx_speech_mp_date ON speech_turns(mp_uid, fecha);
CREATE INDEX idx_interactions_source_target ON interactions(source_uid, target_uid);