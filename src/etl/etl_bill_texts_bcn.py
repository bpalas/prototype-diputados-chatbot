# src/etl/etl_bill_texts_bcn.py
# -*- coding: utf-8 -*-
"""
ETL - Extracción de Textos de Proyectos de Ley desde datos.bcn.cl (v8 - API JSON)

Este script utiliza el método de convertir las URLs de la BCN a su formato .json
para una extracción de datos directa y fiable, eliminando la necesidad de
analizar HTML/XML.

Estrategia (Versión JSON):
1.  Para cada `bill_id`, consulta la página principal (HTML) para obtener los enlaces de "tramitación".
2.  Convierte cada URL de tramitación a su equivalente `.json`.
3.  Consume el JSON para obtener directamente la URL del "documento" (`esParteDe`).
4.  Construye la URL del `.txt` a partir de la URL del documento.
5.  Descarga el texto y carga los metadatos en la base de datos.
"""
import argparse
import logging
import sqlite3
import time
import re
import json
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# --- 1. CONFIGURACIÓN ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "database" / "parlamento.db"
TEXT_FILES_PATH = PROJECT_ROOT / "data" / "bill_texts"
INPUT_FILE = PROJECT_ROOT / "data" / "bill_ids_to_process.txt"

BCN_PROJECT_URL_TEMPLATE = "https://datos.bcn.cl/recurso/cl/proyecto-de-ley/{}/datos.html"
BCN_ES_PARTE_DE_KEY = "http://datos.bcn.cl/ontologies/bcn-resources#esParteDe"
BCN_DATE_KEY = "http://purl.org/dc/elements/1.1/date"
BCN_TIPO_DOC_KEY = "http://datos.bcn.cl/ontologies/bcn-resources#tieneTipoDocumento"
BCN_SESION_KEY = "http://datos.bcn.cl/ontologies/bcn-resources#tieneSesion"


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- 2. MÓDULO DE EXTRACCIÓN Y TRANSFORMACIÓN ---

def fetch_content(session: requests.Session, url: str, is_json: bool = False):
    """Obtiene el contenido de una URL (JSON o Texto)."""
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        if is_json:
            return response.json()
        response.encoding = 'utf-8'
        return response.text
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        logging.error(f"Error al obtener o procesar {url}: {e}")
    return None

def parse_session_url(url: str) -> dict:
    """Extrae información de la legislatura, cámara y sesión desde la URL."""
    if not url: return {}
    match = re.search(r"/legislatura/(\d+)/([\w-]+)/sesion/.*?/(\d+)", url)
    if match:
        legislatura, camara, sesion_num = match.groups()
        camara = camara.replace('-', ' ').title()
        return { "legislatura": legislatura, "camara": camara, "sesion_num": sesion_num }
    return {}

# --- 3. MÓDULO DE CARGA (SIMPLIFICADO) ---

def load_document_and_text(conn: sqlite3.Connection, data: dict):
    """
    Carga un único registro de documento en la base de datos.
    Ya no se necesita la tabla de trámites para este enfoque simplificado.
    """
    cursor = conn.cursor()
    try:
        # Usamos ON CONFLICT para evitar duplicados si el script se re-ejecuta
        cursor.execute("""
            INSERT INTO bill_documentos (bill_id, tipo_documento, url_documento, fecha_documento, descripcion)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url_documento) DO NOTHING;
        """, (
            data['bill_id'], data['tipo_documento'], data['txt_url'],
            data['fecha'], data['documento_descripcion']
        ))
        
        if cursor.rowcount > 0:
            documento_id = cursor.lastrowid
            TEXT_FILES_PATH.mkdir(parents=True, exist_ok=True)
            text_file = TEXT_FILES_PATH / f"{documento_id}.txt"
            text_file.write_text(data['texto_contenido'], encoding='utf-8')
            conn.commit()
            logging.info(f"Éxito: Documento ID {documento_id} cargado. Texto guardado en {text_file.name}")
        else:
            logging.warning(f"El documento con URL {data['txt_url']} ya existe. Se omite.")

    except sqlite3.Error as e:
        logging.error(f"Error en la base de datos para el documento {data['txt_url']}: {e}")
        conn.rollback()

# --- 4. ORQUESTADOR PRINCIPAL ---

def process_bill(session: requests.Session, conn: sqlite3.Connection, bill_id: str):
    logging.info(f"--- Iniciando procesamiento para el Boletín {bill_id} ---")
    project_url = BCN_PROJECT_URL_TEMPLATE.format(bill_id)
    project_html = fetch_content(session, project_url)

    if not project_html:
        logging.error(f"No se pudo obtener la página principal para {bill_id}")
        return

    soup = BeautifulSoup(project_html, 'lxml')
    tramitacion_urls = []
    prop_tags = soup.find_all('a', href="https://datos.bcn.cl/ontologies/bcn-resources#tieneTramitacion")
    for tag in prop_tags:
        resource_tag = tag.find_next_sibling('a', class_='resource')
        if resource_tag and 'href' in resource_tag.attrs:
            tramitacion_urls.append(resource_tag['href'])

    if not tramitacion_urls:
        logging.warning(f"No se encontraron trámites para el boletín {bill_id}.")
        return

    logging.info(f"Encontrados {len(tramitacion_urls)} trámites para {bill_id}. Procesando...")

    for i, tramite_html_url in enumerate(tramitacion_urls):
        logging.info(f"  -> Procesando trámite {i+1}/{len(tramitacion_urls)}: {tramite_html_url}")
        time.sleep(0.1)
        
        # **TRUCO: Convertir la URL a su versión JSON**
        tramite_json_url = tramite_html_url.replace("/datos.html", "") + "/datos.json"
        
        tramite_data = fetch_content(session, tramite_json_url, is_json=True)
        if not tramite_data:
            logging.error(f"    No se pudo obtener el JSON del trámite: {tramite_json_url}")
            continue

        # Extraer datos directamente del JSON
        tramite_id = list(tramite_data.keys())[0]
        tramite_info = tramite_data[tramite_id]
        
        documento_url_list = tramite_info.get(BCN_ES_PARTE_DE_KEY, [])
        documento_url = next((item['value'] for item in documento_url_list if '/documento/' in item.get('value', '')), None)

        if not documento_url:
            logging.warning("    No se encontró enlace a un 'documento' en el JSON del trámite.")
            continue

        txt_url = f"{documento_url}.txt"
        logging.info(f"    URL de texto construida: {txt_url}")
        
        texto_contenido = fetch_content(session, txt_url)
        if not texto_contenido:
            logging.error("    No se pudo descargar el contenido del texto.")
            continue

        fecha = tramite_info.get(BCN_DATE_KEY, [{}])[0].get('value', datetime.now().strftime('%Y-%m-%d'))
        tipo_doc_raw = tramite_info.get(BCN_TIPO_DOC_KEY, [{}])[0].get('value', '')
        tipo_documento = tipo_doc_raw.split('#')[-1] if tipo_doc_raw else "Documento"
        
        documento_descripcion = f"Texto del documento: {tipo_documento} para el boletín {bill_id}"

        data_package = {
            "bill_id": bill_id,
            "txt_url": txt_url,
            "texto_contenido": texto_contenido,
            "fecha": fecha,
            "tipo_documento": tipo_documento,
            "documento_descripcion": documento_descripcion
        }
        
        load_document_and_text(conn, data_package)


def main(limit: int | None = None):
    logging.info("--- [ETL Bill Texts BCN] Iniciando proceso ---")
    if not INPUT_FILE.exists():
        logging.error(f"No se encuentra el archivo de entrada: {INPUT_FILE}")
        return
        
    with INPUT_FILE.open('r') as f:
        bill_ids = [line.strip() for line in f if line.strip()]
    if not bill_ids:
        logging.info("No hay boletines para procesar. Finalizando.")
        return
        
    if limit: bill_ids = bill_ids[:limit]
    
    headers = {'User-Agent': 'ParlamentoAbierto-ETL/2.5 (contacto@fundacion.cl)'}
    with requests.Session() as session:
        session.headers.update(headers)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            # Limpiamos solo los documentos para evitar duplicados en re-ejecuciones
            logging.info("Limpiando la tabla bill_documentos antes de la carga...")
            conn.execute("DELETE FROM bill_documentos;")
            conn.commit()
            
            for bill_id in bill_ids:
                process_bill(session, conn, bill_id)

    logging.info("--- Proceso ETL Bill Texts BCN finalizado. ---")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL para extraer textos de proyectos de ley desde datos.bcn.cl.")
    parser.add_argument("--limit", type=int, help="Limita el número de boletines a procesar.")
    args = parser.parse_args()
    main(limit=args.limit)