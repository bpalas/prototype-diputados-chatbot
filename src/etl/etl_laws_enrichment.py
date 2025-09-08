# src/etl/etl_laws_enrichment.py
# -*- coding: utf-8 -*-
"""
ETL - Enriquecimiento de Leyes Publicadas (Versión Mejorada)

Este script no solo enriquece los metadatos de las leyes publicadas,
sino que también busca y almacena el ID de la "Historia de la Ley" de BCN,
dejando todos los identificadores listos para futuros procesos.
"""
import json
import logging
import sqlite3
import time
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import requests
from datetime import datetime
from bs4 import BeautifulSoup # NUEVO: Se necesita para el scraping

# --- 1. CONFIGURACIÓN ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "database" / "parlamento.db"
CACHE_PATH = PROJECT_ROOT / "data" / "cache"
LAW_HTML_CACHE_PATH = CACHE_PATH / "bcn_historia_html" # NUEVO: Caché para HTML

BCN_LAW_API_URL = "https://datos.bcn.cl/recurso/cl/ley/{}/datos.json"
LEYCHILE_LAW_API_URL = "https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma={}"
BCN_BUSQUEDA_HISTORIA_URL = "https://www.bcn.cl/historiadelaley/nc/lista-de-resultado-de-busqueda/ley%20{law_number}/" # NUEVO

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- 2. MÓDULO DE EXTRACCIÓN (EXTRACT) ---

def fetch_content(session: requests.Session, url: str, file_ext: str, cache_dir: Path, identifier: str):
    """Función genérica para obtener y cachear contenido web (HTML, XML, JSON)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{identifier}.{file_ext}"

    if cache_file.exists():
        logging.info(f"Cargando {identifier} desde caché para '{cache_dir.name}'.")
        return cache_file.read_bytes(), url

    logging.info(f"Obteniendo {identifier} desde API/URL: {url}")
    try:
        response = session.get(url, timeout=45)
        response.raise_for_status()
        content = response.content
        cache_file.write_bytes(content)
        time.sleep(0.3)
        return content, url
    except requests.exceptions.RequestException as e:
        logging.error(f"Error de red para {identifier} en {url}: {e}")
        return None, url

# --- 3. MÓDULO DE TRANSFORMACIÓN (TRANSFORM) ---

def parse_date(date_str: str | None) -> str | None:
    if not date_str: return None
    try:
        return datetime.strptime(date_str.strip(), '%Y-%m-%d').strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return None

def get_bcn_historia_id(session: requests.Session, law_number: str):
    """
    NUEVO: Busca el ID interno de la "Historia de la Ley" de BCN para un número de ley.
    """
    search_url = BCN_BUSQUEDA_HISTORIA_URL.format(law_number=law_number)
    content, _ = fetch_content(session, search_url, 'html', LAW_HTML_CACHE_PATH, f"search_{law_number}")
    if not content: return None

    try:
        soup = BeautifulSoup(content, 'lxml')
        # Selector robusto para el primer resultado del listado
        result_link = soup.select_one('div.listado_resultado ul li a[href*="/historia-de-la-ley/"]')
        if result_link:
            match = re.search(r'/historia-de-la-ley/(\d+)/', result_link['href'])
            if match:
                historia_id = match.group(1)
                logging.info(f"ID de Historia de la Ley BCN encontrado: {historia_id}")
                return historia_id
        logging.warning(f"No se pudo encontrar el ID de historia para Ley {law_number}.")
        return None
    except Exception as e:
        logging.error(f"Error al parsear página de búsqueda de BCN para Ley {law_number}: {e}")
        return None

def transform_law_data(bcn_json_content: bytes, leychile_xml_content: bytes, bcn_historia_id: str | None, bill_id: str):
    """
    Parsea los datos, incluyendo ahora el bcn_historia_id.
    """
    if not bcn_json_content or not leychile_xml_content: return None

    try:
        bcn_data = json.loads(bcn_json_content)
        main_key = list(bcn_data.keys())[0]
        recurso = bcn_data[main_key]
        bcn_norma_id = str(recurso.get("http://datos.bcn.cl/ontologies/bcn-norms#leychileCode", [{}])[0].get('value'))

        root = ET.fromstring(leychile_xml_content)
        ns = {'ley': 'http://www.leychile.cl/esquemas'}
        
        identificador_elem = root.find('ley:Identificador', ns)
        fecha_publicacion = parse_date(identificador_elem.attrib.get('fechaPublicacion')) if identificador_elem is not None else None

        norma_data = {
            'bcn_norma_id': bcn_norma_id,
            'bcn_historia_id': bcn_historia_id, # MODIFICADO: Se añade el ID de historia
            'numero_norma': root.findtext('.//ley:Identificador/ley:TiposNumeros/ley:TipoNumero/ley:Numero', None, ns),
            'titulo_norma': root.findtext('.//ley:Metadatos/ley:TituloNorma', None, ns),
            'fecha_publicacion': fecha_publicacion,
            'tipo_norma': root.findtext('.//ley:Identificador/ley:TiposNumeros/ley:TipoNumero/ley:Tipo', None, ns),
            'url_ley_chile': f"http://www.leychile.cl/Navegar?idNorma={bcn_norma_id}"
        }

        if not norma_data.get('numero_norma'):
            logging.warning("Datos incompletos: falta número de norma.")
            return None

        return { "norma_data": norma_data, "source_bill_id": bill_id }
    except Exception as e:
        logging.error(f"Error al transformar los datos de la ley: {e}")
        return None

# --- 4. MÓDULO DE CARGA (LOAD) ---

def load_law_data(conn: sqlite3.Connection, transformed_data: dict, source_urls: dict):
    """
    MODIFICADO: Carga los datos de la ley, incluyendo bcn_historia_id.
    """
    cursor = conn.cursor()
    norma_info = transformed_data['norma_data']
    bill_id = transformed_data['source_bill_id']

    cursor.execute("""
        INSERT INTO dim_normas (bcn_norma_id, bcn_historia_id, numero_norma, titulo_norma, fecha_publicacion, tipo_norma, url_ley_chile)
        VALUES (:bcn_norma_id, :bcn_historia_id, :numero_norma, :titulo_norma, :fecha_publicacion, :tipo_norma, :url_ley_chile)
        ON CONFLICT(bcn_norma_id) DO UPDATE SET
            bcn_historia_id=excluded.bcn_historia_id,
            numero_norma=excluded.numero_norma,
            titulo_norma=excluded.titulo_norma,
            fecha_publicacion=excluded.fecha_publicacion,
            url_ley_chile=excluded.url_ley_chile;
    """, norma_info)
    
    cursor.execute("SELECT norma_id FROM dim_normas WHERE bcn_norma_id = ?", (norma_info['bcn_norma_id'],))
    result = cursor.fetchone()
    if not result:
        logging.error(f"No se pudo obtener el norma_id interno para bcn_norma_id {norma_info['bcn_norma_id']}")
        return
    
    internal_norma_id = result[0]
    cursor.execute("UPDATE bills SET norma_id = ? WHERE bill_id = ?", (internal_norma_id, bill_id))
    logging.info(f"Ley {norma_info['numero_norma']} (ID: {internal_norma_id}) vinculada al proyecto {bill_id}. Filas afectadas: {cursor.rowcount}.")

    bcn_norma_id = norma_info['bcn_norma_id']
    cursor.execute("DELETE FROM entity_sources WHERE entity_id = ? AND entity_type = 'norma'", (bcn_norma_id,))
    source_values = [(bcn_norma_id, 'norma', name, url, datetime.now().strftime("%Y-%m-%d %H:%M:%S")) for name, url in source_urls.items() if url]
    if source_values:
        cursor.executemany("INSERT INTO entity_sources (entity_id, entity_type, source_name, url, last_checked_at) VALUES (?, ?, ?, ?, ?)", source_values)
        logging.info(f"Guardadas {len(source_values)} URLs de origen para la norma {bcn_norma_id}.")


# --- 5. ORQUESTADOR PRINCIPAL (MAIN) ---

def main():
    """
    MODIFICADO: El orquestador ahora incluye el paso para obtener el bcn_historia_id.
    """
    logging.info("--- [ETL Laws Enrichment] Iniciando proceso ---")
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            bills_to_process = conn.cursor().execute("SELECT bill_id, numero_ley FROM bills WHERE numero_ley IS NOT NULL AND norma_id IS NULL").fetchall()
    except sqlite3.Error as e:
        logging.error(f"No se pudo consultar la base de datos: {e}")
        return

    if not bills_to_process:
        logging.info("No hay nuevas leyes publicadas para procesar. Finalizando.")
        return

    logging.info(f"Se encontraron {len(bills_to_process)} proyectos de ley publicados para enriquecer.")

    headers = {'User-Agent': 'ParlamentoAbierto-ETL/1.0'}
    with requests.Session() as session:
        session.headers.update(headers)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")

            for i, (bill_id, law_number) in enumerate(bills_to_process, 1):
                if not law_number: continue
                logging.info(f"--- Procesando {i}/{len(bills_to_process)}: Boletín {bill_id} -> Ley {law_number} ---")
                
                bcn_content, bcn_url = fetch_content(session, BCN_LAW_API_URL.format(law_number), 'json', CACHE_PATH, law_number)
                
                if bcn_content:
                    try:
                        bcn_data = json.loads(bcn_content)
                        main_key = list(bcn_data.keys())[0]
                        leychile_code = bcn_data[main_key]["http://datos.bcn.cl/ontologies/bcn-norms#leychileCode"][0]['value']
                        
                        leychile_content, leychile_url = fetch_content(session, LEYCHILE_LAW_API_URL.format(leychile_code), 'xml', CACHE_PATH, leychile_code)
                        
                        # NUEVO: Obtener el ID de historia antes de transformar
                        bcn_historia_id = get_bcn_historia_id(session, law_number)
                        
                        transformed_data = transform_law_data(bcn_content, leychile_content, bcn_historia_id, bill_id)
                        
                        if transformed_data:
                            try:
                                conn.execute("BEGIN TRANSACTION;")
                                source_urls = {'bcn_law_json': bcn_url, 'leychile_law_xml': leychile_url}
                                load_law_data(conn, transformed_data, source_urls)
                                conn.commit()
                            except sqlite3.Error as e:
                                logging.error(f"Error en transacción para ley {law_number}: {e}")
                                conn.rollback()
                        else:
                            logging.warning(f"No se pudo transformar datos para ley {law_number}. Se omite.")
                    except (KeyError, IndexError, json.JSONDecodeError) as e:
                        logging.error(f"Error parseando JSON de BCN para ley {law_number}: {e}")
                else:
                    logging.warning(f"No se pudieron obtener datos de BCN para la ley {law_number}. Se omite.")

    logging.info("--- Proceso finalizado. ---")

if __name__ == "__main__":
    main()