# src/etl/etl_roster.py
# -*- coding: utf-8 -*-

"""
ETL para poblar las tablas dim_parlamentario y dim_partidos y relacionadas.
Versión que integra datos de la Cámara, BCN para parlamentarios y una tabla
dim_partidos enriquecida desde la BCN.
"""

import sqlite3
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from SPARQLWrapper import SPARQLWrapper, JSON
import os

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYECTO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')

API_CAMARA_URL = "https://opendata.camara.cl/camaradiputados/WServices/WSDiputado.asmx/retornarDiputadosPeriodoActual"
BCN_SPARQL_ENDPOINT = "http://datos.bcn.cl/sparql"


# --- ESQUEMA SQL CON TABLA dim_partidos ENRIQUECIDA ---
SQL_SCHEMA_SAFE = """
CREATE TABLE IF NOT EXISTS dim_parlamentario (
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

CREATE TABLE IF NOT EXISTS dim_partidos (
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

CREATE TABLE IF NOT EXISTS militancia_historial (
    militancia_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mp_uid INTEGER NOT NULL,
    partido_id INTEGER NOT NULL,
    coalicion_id INTEGER,
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE,
    FOREIGN KEY (partido_id) REFERENCES dim_partidos(partido_id) ON DELETE CASCADE
);

-- (Otras tablas como dim_coaliciones, electoral_results, etc.)
CREATE TABLE IF NOT EXISTS dim_coaliciones (
   coalicion_id INTEGER PRIMARY KEY AUTOINCREMENT,
   nombre_coalicion TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS parlamentario_aliases (
   alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
   mp_uid INTEGER NOT NULL,
   alias TEXT NOT NULL UNIQUE,
   FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS electoral_results (
   result_id INTEGER PRIMARY KEY AUTOINCREMENT,
   mp_uid INTEGER NOT NULL,
   fecha_eleccion DATE NOT NULL,
   cargo TEXT,
   distrito INTEGER,
   total_votos INTEGER,
   FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_militancia_mp ON militancia_historial(mp_uid);
"""


# --- 2. FASE DE EXTRACCIÓN ---
def fetch_camara_data_df():
    """Obtiene datos y militancias de la API de la Cámara y los estructura en un DataFrame."""
    print("🏛️  [ROSTER ETL] Obteniendo datos de la API de la Cámara...")
    try:
        response = requests.get(API_CAMARA_URL, timeout=60)
        response.raise_for_status()
        print("✅  [ROSTER ETL] Datos XML de la Cámara recibidos.")
    except requests.exceptions.RequestException as e:
        print(f"❌  [ROSTER ETL] Error al conectar con la API de la Cámara: {e}")
        return None

    diputados_list = []
    ns = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}
    root = ET.fromstring(response.content)

    for diputado_periodo in root.findall('v1:DiputadoPeriodo', ns):
        diputado = diputado_periodo.find('v1:Diputado', ns)
        if diputado is None: continue

        militancias = []
        for m in diputado.findall('v1:Militancias/v1:Militancia', ns):
            partido_tag = m.find('v1:Partido/v1:Nombre', ns)
            if partido_tag is not None and partido_tag.text:
                fecha_fin_tag = m.find('v1:FechaTermino', ns)
                militancias.append({
                    'partido': partido_tag.text.strip(),
                    'fecha_inicio': m.findtext('v1:FechaInicio', namespaces=ns, default='').split('T')[0],
                    'fecha_fin': fecha_fin_tag.text.split('T')[0] if fecha_fin_tag is not None and fecha_fin_tag.text else None
                })

        sexo_tag = diputado.find('v1:Sexo', ns)
        distrito_tag = diputado_periodo.find('v1:Distrito', ns)

        diputados_list.append({
            'diputadoid': diputado.findtext('v1:Id', namespaces=ns),
            'nombre_completo': f"{diputado.findtext('v1:Nombre', default='', namespaces=ns).strip()} {diputado.findtext('v1:ApellidoPaterno', default='', namespaces=ns).strip()} {diputado.findtext('v1:ApellidoMaterno', default='', namespaces=ns).strip()}".strip(),
            'apellido_materno_camara': diputado.findtext('v1:ApellidoMaterno', default='', namespaces=ns).strip(),
            'genero': "Femenino" if sexo_tag is not None and sexo_tag.get('Valor') == '0' else "Masculino",
            'distrito_camara': distrito_tag.get('Numero') if distrito_tag is not None else None,
            'militancias': militancias
        })

    print(f"✔️  [ROSTER ETL] Se procesaron {len(diputados_list)} diputados desde la Cámara.")
    return pd.DataFrame(diputados_list)


def fetch_bcn_data_df():
    """Obtiene datos específicos de la BCN para los parlamentarios usando una consulta SPARQL optimizada."""
    print("📚  [ROSTER ETL] Obteniendo datos específicos desde la BCN...")
    sparql = SPARQLWrapper(BCN_SPARQL_ENDPOINT)
    sparql.setReturnFormat(JSON)
    
    query_bcn_optimised = """
        PREFIX bcnbio: <http://datos.bcn.cl/ontologies/bcn-biographies#>
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        PREFIX dc: <http://purl.org/dc/elements/1.1/>
        PREFIX bio: <http://purl.org/vocab/bio/0.1/>

        SELECT 
            ?bcn_uri ?diputadoid ?nombre_propio ?apellido_paterno ?apellido_materno
            ?fecha_nacimiento ?lugar_nacimiento ?url_foto ?twitter_handle
            ?sitio_web_personal ?titulo_honorifico ?profesion ?nacionalidad ?url_historia_politica
        WHERE {
          ?bcn_uri bcnbio:idCamaraDeDiputados ?diputadoid .
          OPTIONAL { ?bcn_uri foaf:givenName ?nombre_propio . }
          OPTIONAL { ?bcn_uri bcnbio:surnameOfFather ?apellido_paterno . }
          OPTIONAL { ?bcn_uri bcnbio:surnameOfMother ?apellido_materno . }
          OPTIONAL {
            ?bcn_uri bcnbio:hasBorn ?nacimiento_uri .
            ?nacimiento_uri dc:date ?fecha_nacimiento .
            OPTIONAL { ?nacimiento_uri bio:place ?lugar_nacimiento . }
          }
          OPTIONAL { ?bcn_uri foaf:thumbnail ?url_foto . }
          OPTIONAL { ?bcn_uri bcnbio:twitterAccount ?twitter_handle . }
          OPTIONAL { ?bcn_uri foaf:homepage ?sitio_web_personal . }
          OPTIONAL { ?bcn_uri bcnbio:honorificPrefix ?titulo_honorifico . }
          OPTIONAL { ?bcn_uri bcnbio:profession ?profesion . }
          OPTIONAL { ?bcn_uri bcnbio:nationality ?nacionalidad . } 
          OPTIONAL { ?bcn_uri bcnbio:bcnPage ?url_historia_politica . }
        }
    """
    sparql.setQuery(query_bcn_optimised)
    
    try:
        results = sparql.query().convert()["results"]["bindings"]
        print(f"✅  [ROSTER ETL] Datos de BCN recibidos.")
    except Exception as e:
        print(f"❌  [ROSTER ETL] Error al consultar el SPARQL de la BCN: {e}")
        return pd.DataFrame()

    if not results:
        print("⚠️  [ROSTER ETL] La consulta a BCN no devolvió resultados.")
        return pd.DataFrame()
        
    bcn_list = []
    for res in results:
        bcn_list.append({
            'bcn_uri': res.get('bcn_uri', {}).get('value'),
            'diputadoid': res.get('diputadoid', {}).get('value'),
            'nombre_propio': res.get('nombre_propio', {}).get('value'),
            'apellido_paterno': res.get('apellido_paterno', {}).get('value'),
            'apellido_materno': res.get('apellido_materno', {}).get('value'),
            'fecha_nacimiento': res.get('fecha_nacimiento', {}).get('value'),
            'lugar_nacimiento': res.get('lugar_nacimiento', {}).get('value'),
            'url_foto': res.get('url_foto', {}).get('value'),
            'twitter_handle': res.get('twitter_handle', {}).get('value'),
            'sitio_web_personal': res.get('sitio_web_personal', {}).get('value'),
            'titulo_honorifico': res.get('titulo_honorifico', {}).get('value'),
            'profesion': res.get('profesion', {}).get('value'),
            'nacionalidad': res.get('nacionalidad', {}).get('value'),
            'url_historia_politica': res.get('url_historia_politica', {}).get('value')
        })

    df_bcn = pd.DataFrame(bcn_list)
    print(f"✔️  [ROSTER ETL] Se procesaron {len(df_bcn)} perfiles únicos de la BCN.")
    return df_bcn


# --- FUNCIÓN DE EXTRACCIÓN PARA PARTIDOS MEJORADA ---
def fetch_partidos_bcn_df():
    """Obtiene datos detallados de los partidos políticos desde la BCN usando SPARQL."""
    print("🏛️  [PARTIDOS ETL] Obteniendo datos enriquecidos de Partidos Políticos desde la BCN...")
    sparql = SPARQLWrapper(BCN_SPARQL_ENDPOINT)
    sparql.setReturnFormat(JSON)

    # Consulta SPARQL para obtener todos los datos deseados, agrupando los alternativos
    query_partidos = """
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX bcnbio: <http://datos.bcn.cl/ontologies/bcn-biographies#>

        SELECT
            ?nombre
            (GROUP_CONCAT(DISTINCT ?altLabel; SEPARATOR=", ") AS ?nombres_alternativos)
            ?sigla
            ?foundationYear
            ?homepage
            ?bcnPage
            ?logo
            ?lastUpdate
        WHERE {
            ?partido_uri a bcnbio:PoliticalParty .
            
            OPTIONAL { ?partido_uri foaf:name ?nombre . }
            OPTIONAL { ?partido_uri skos:altLabel ?altLabel . }
            OPTIONAL { ?partido_uri bcnbio:hasAcronym ?sigla . }
            OPTIONAL { ?partido_uri bcnbio:hasFoundationYear ?foundationYear . }
            OPTIONAL { ?partido_uri foaf:homepage ?homepage . }
            OPTIONAL { ?partido_uri bcnbio:bcnPage ?bcnPage . }
            OPTIONAL { ?partido_uri foaf:img ?logo . }
            OPTIONAL { ?partido_uri bcnbio:lastUpdate ?lastUpdate . }
        }
        GROUP BY ?nombre ?sigla ?foundationYear ?homepage ?bcnPage ?logo ?lastUpdate
    """
    sparql.setQuery(query_partidos)

    try:
        results = sparql.query().convert()["results"]["bindings"]
        print(f"✅  [PARTIDOS ETL] Datos de partidos recibidos.")
    except Exception as e:
        print(f"❌  [PARTIDOS ETL] Error al consultar el SPARQL de la BCN para partidos: {e}")
        return pd.DataFrame()

    partidos_list = []
    for res in results:
        partidos_list.append({
            'nombre_partido': res.get('nombre', {}).get('value'),
            'nombre_alternativo': res.get('nombres_alternativos', {}).get('value'),
            'sigla': res.get('sigla', {}).get('value'),
            'fecha_fundacion': res.get('foundationYear', {}).get('value'),
            'sitio_web': res.get('homepage', {}).get('value'),
            'url_historia_politica': res.get('bcnPage', {}).get('value'),
            'url_logo': res.get('logo', {}).get('value'),
            'ultima_actualizacion': res.get('lastUpdate', {}).get('value'),
        })
    
    df_partidos = pd.DataFrame(partidos_list).dropna(subset=['nombre_partido'])
    print(f"✔️  [PARTIDOS ETL] Se procesaron {len(df_partidos.index)} partidos políticos con datos enriquecidos.")
    return df_partidos


# --- 3. FASE DE CARGA (Load) ---
def setup_database(conn):
    """Asegura que las tablas existan en la base de datos usando el esquema seguro."""
    print("🛠️  [DB Setup] Verificando que las tablas existan...")
    try:
        cursor = conn.cursor()
        cursor.executescript(SQL_SCHEMA_SAFE)
        conn.commit()
        print("✅  [DB Setup] Esquema verificado. Las tablas necesarias existen.")
    except sqlite3.Error as e:
        print(f"❌  [DB Setup] Error al verificar/crear el esquema SQL: {e}")
        raise


def clear_data(conn):
    """Limpia las tablas que este script va a poblar para una carga fresca."""
    print("🧹  [DB Load] Limpiando datos antiguos para la nueva carga...")
    cursor = conn.cursor()
    # Se elimina partido_aliases
    tables_to_clear = ['militancia_historial', 'dim_parlamentario', 'dim_partidos']
    for table in tables_to_clear:
        try:
            cursor.execute(f"DELETE FROM {table};")
            cursor.execute(f"DELETE FROM sqlite_sequence WHERE name = '{table}';")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    print("✅  [DB Load] Tablas relevantes limpiadas.")


def load_data_to_db(df_parlamentarios, df_partidos, conn):
    """Carga los DataFrames procesados en las tablas normalizadas de la BD."""
    print("⚙️  [DB Load] Iniciando carga de datos en la base de datos...")
    cursor = conn.cursor()
    
    print("  -> Cargando partidos políticos con datos enriquecidos...")
    # Lógica de carga para la tabla dim_partidos actualizada
    for _, row in df_partidos.iterrows():
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO dim_partidos (
                    nombre_partido, nombre_alternativo, sigla, fecha_fundacion, 
                    sitio_web, url_historia_politica, url_logo, ultima_actualizacion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['nombre_partido'], row['nombre_alternativo'], row['sigla'],
                row['fecha_fundacion'], row['sitio_web'], row['url_historia_politica'],
                row['url_logo'], row['ultima_actualizacion']
            ))
        except sqlite3.IntegrityError as e:
            print(f"  ⚠️  Advertencia al cargar partido {row['nombre_partido']}: {e}.")
            continue
            
    cursor.execute("SELECT partido_id, nombre_partido FROM dim_partidos")
    partido_map = {nombre: id for id, nombre in cursor.fetchall()}
    print(f"  -> {len(partido_map)} partidos cargados/verificados.")

    print("  -> Cargando parlamentarios y su historial de militancia...")
    for _, row in df_parlamentarios.iterrows():
        try:
            cursor.execute("""
                INSERT INTO dim_parlamentario (
                    diputadoid, nombre_completo, nombre_propio, apellido_paterno, apellido_materno,
                    genero, fecha_nacimiento, lugar_nacimiento, distrito, bcn_uri, url_foto,
                    twitter_handle, sitio_web_personal, titulo_honorifico, profesion,
                    nacionalidad, url_historia_politica, fecha_extraccion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_DATE)
            """, (
                row.get('diputadoid'), row.get('nombre_completo'), row.get('nombre_propio'),
                row.get('apellido_paterno'), row.get('apellido_materno'), row.get('genero'),
                row.get('fecha_nacimiento'), row.get('lugar_nacimiento'), row.get('distrito_camara'),
                row.get('bcn_uri'), row.get('url_foto'), row.get('twitter_handle'),
                row.get('sitio_web_personal'), row.get('titulo_honorifico'),
                row.get('profesion'), row.get('nacionalidad'), row.get('url_historia_politica')
            ))
            mp_uid = cursor.lastrowid

            for militancia in row['militancias']:
                partido_id = partido_map.get(militancia['partido'])
                if partido_id:
                    cursor.execute(
                        "INSERT INTO militancia_historial (mp_uid, partido_id, fecha_inicio, fecha_fin) VALUES (?, ?, ?, ?)",
                        (mp_uid, partido_id, militancia['fecha_inicio'] or None, militancia['fecha_fin'] or None)
                    )
        except sqlite3.IntegrityError as e:
            print(f"  ⚠️  Advertencia para {row.get('nombre_completo')} (ID: {row.get('diputadoid')}): {e}. Es posible que ya exista.")
            continue
    
    conn.commit()
    print("✅  [DB Load] Proceso de carga de roster completado.")


# --- 4. ORQUESTACIÓN ---
def main():
    """Función principal que orquesta el proceso ETL completo."""
    print("--- Iniciando Proceso ETL: Roster Parlamentario y Partidos ---")
    
    # Fase 1: Extracción y Transformación
    df_camara = fetch_camara_data_df()
    df_bcn_parlamentarios = fetch_bcn_data_df()
    df_partidos = fetch_partidos_bcn_df()

    if df_camara is None or df_bcn_parlamentarios.empty:
        print("\n❌  ETL de Roster no pudo completarse debido a un error en la obtención de datos.")
        return

    print("\n🤝  [TRANSFORM] Realizando el cruce (merge) de datos de parlamentarios...")
    df_final_parlamentarios = pd.merge(df_camara, df_bcn_parlamentarios, on='diputadoid', how='left')
    
    df_final_parlamentarios['apellido_materno'] = df_final_parlamentarios['apellido_materno'].fillna(df_final_parlamentarios['apellido_materno_camara'])
    df_final_parlamentarios.drop(columns=['apellido_materno_camara'], inplace=True)

    print(f"✅  [TRANSFORM] Cruce completado. DataFrame final con {len(df_final_parlamentarios)} registros listo para cargar.")

    # Fase 2: Conexión y Carga a la Base de Datos
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            
            setup_database(conn)
            clear_data(conn)
            load_data_to_db(df_final_parlamentarios, df_partidos, conn)

    except Exception as e:
        print(f"❌  Error Crítico durante la operación con la Base de Datos: {e}")

    print("\n--- Proceso ETL Finalizado ---")

if __name__ == "__main__":
    main()