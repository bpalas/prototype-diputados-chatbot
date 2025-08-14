-- Esquema de datos de GCP del IMFD 

-- Tabla para los partidos políticos
CREATE TABLE political_parties (
    id INT PRIMARY KEY,
    name VARCHAR(255),
    short_name VARCHAR(50)
);

-- Tabla para los políticos
CREATE TABLE politicians (
    id INT PRIMARY KEY,
    fathers_surname VARCHAR(255),
    mothers_surname VARCHAR(255),
    first_name VARCHAR(255),
    bcn_id INT,
    congress_id INT,
    biography_id VARCHAR(255),
    updated_at_internal DATETIME
);

-- Tabla para los proyectos de ley
CREATE TABLE bills (
    id INT PRIMARY KEY,
    bulletin_number VARCHAR(255),
    normalized_bulletin_number VARCHAR(255),
    title TEXT,
    committee_id INT,
    stage VARCHAR(255),
    substage VARCHAR(255),
    introduced_at DATE,
    updated_at DATE,
    updated_at_internal DATETIME,
    history TEXT,
    origin VARCHAR(255),
    initiative VARCHAR(255),
    merged VARCHAR(255),
    authors_str TEXT,
    summary_link TEXT,
    created_at_internal DATE,
    urgency VARCHAR(255),
    law_number VARCHAR(255),
    date_diario_oficial DATE,
    state VARCHAR(255)
);

-- Tabla para las votaciones
CREATE TABLE votes (
    id INT PRIMARY KEY,
    external_id INT,
    vote_date DATE,
    source VARCHAR(255),
    type VARCHAR(255),
    topic TEXT,
    date DATE,
    in_favor INT,
    against INT,
    abstention INT,
    dispensed INT,
    pareo INT,
    quorum VARCHAR(255),
    result VARCHAR(255),
    session VARCHAR(255),
    stage VARCHAR(255),
    hash VARCHAR(255),
    bill_id INT,
    created_at_internal DATETIME,
    updated_at_internal DATETIME,
    FOREIGN KEY (bill_id) REFERENCES bills(id)
);

-- Tabla para los periodos legislativos
CREATE TABLE legislative_periods (
    id INT PRIMARY KEY,
    name VARCHAR(255),
    start_year INT,
    end_year INT,
    dip_quantity INT,
    sen_quantity INT
);

-- Tabla de unión para los autores (políticos) de un proyecto de ley
CREATE TABLE bill_politicians (
    bill_id INT,
    politician_id INT,
    PRIMARY KEY (bill_id, politician_id),
    FOREIGN KEY (bill_id) REFERENCES bills(id),
    FOREIGN KEY (politician_id) REFERENCES politicians(id)
);

-- Tabla para el voto específico de cada político en una votación
CREATE TABLE vote_selections (
    id INT PRIMARY KEY,
    vote_id INT,
    politician_id INT,
    selection VARCHAR(255),
    created_at_internal DATETIME,
    updated_at_internal DATETIME,
    FOREIGN KEY (vote_id) REFERENCES votes(id),
    FOREIGN KEY (politician_id) REFERENCES politicians(id)
);

-- Tabla que registra los cargos de un político a lo largo del tiempo
CREATE TABLE politician_periods (
    id INT PRIMARY KEY,
    politician_id INT,
    start_year INT,
    end_year INT,
    position VARCHAR(255),
    party_id INT,
    political_caucus_id INT,
    representation_unit_id INT,
    FOREIGN KEY (politician_id) REFERENCES politicians(id),
    FOREIGN KEY (party_id) REFERENCES political_parties(id)
);

-- Tabla denormalizada con información agregada de políticos por periodo
CREATE TABLE politicians_by_periods (
    politician_id INT,
    full_name VARCHAR(255),
    position VARCHAR(255),
    position_start_year INT,
    position_end_year INT,
    legislative_period_name VARCHAR(255),
    legislative_start_year INT,
    legislative_end_year INT,
    dip_quantity INT,
    sen_quantity INT,
    party_id INT,
    party_name VARCHAR(255),
    party_short_name VARCHAR(50),
    authored_bills JSON -- El tipo 'RECORD REPEATED' se representa comúnmente como JSON
);

-- Tabla denormalizada con los votos de cada político por periodo
CREATE TABLE votes_selections_by_period (
    politician_id INT,
    full_name VARCHAR(255),
    position VARCHAR(255),
    position_start_year INT,
    position_end_year INT,
    party_id INT,
    party_name VARCHAR(255),
    party_short_name VARCHAR(50),
    legislative_period_name VARCHAR(255),
    legislative_start_year INT,
    legislative_end_year INT,
    dip_quantity INT,
    sen_quantity INT,
    vote_id INT,
    vote_date DATE,
    bill_id INT,
    selection VARCHAR(255),
    result VARCHAR(255),
    quorum VARCHAR(255),
    type VARCHAR(255),
    topic TEXT,
    stage VARCHAR(255),
    session VARCHAR(255),
    source VARCHAR(255),
    bulletin_number VARCHAR(255),
    title TEXT,
    introduced_at DATE,
    state VARCHAR(255)
);

-- Tabla de agregación para la participación en votaciones por año y cámara
CREATE TABLE vote_participation_by_year (
    anio INT,
    camara VARCHAR(255),
    promedio_pct_participacion_anual FLOAT
);