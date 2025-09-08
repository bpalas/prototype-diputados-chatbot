# src/etl/etl_ministerios.py
# -*- coding: utf-8 -*-
"""
ETL - Población de la Dimensión de Ministerios

Este script extrae la lista completa de ministerios desde la API
de la Cámara de Diputados, la transforma y la carga en la tabla
`dim_ministerios` de la base de datos.
"""
import logging
import sqlite3
import time
import xml.etree.ElementTree as ET
from pathlib import Path
import requests

# --- 1. CONFIGURACIÓN ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "database" / "parlamento.db"
CACHE_PATH = PROJECT_ROOT / "data" / "cache"
MINISTERIOS_API_URL = "https://opendata.camara.cl/camaradiputados/WServices/WSComun.asmx/retornarMinisterios"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- 2. MÓDULO DE EXTRACCIÓN (EXTRACT) ---

def fetch_data(session: requests.Session):
    """
    Obtiene y cachea la lista de ministerios desde la API.
    """
    cache_file = CACHE_PATH / "ministerios.xml"
    CACHE_PATH.mkdir(parents=True, exist_ok=True)

    if cache_file.exists():
        logging.info("Cargando lista de ministerios desde caché.")
        return cache_file.read_bytes()

    logging.info(f"Obteniendo lista de ministerios desde API: {MINISTERIOS_API_URL}")
    try:
        response = session.get(MINISTERIOS_API_URL, timeout=45)
        response.raise_for_status()
        content = response.content
        cache_file.write_bytes(content)
        time.sleep(0.3)
        return content
    except requests.exceptions.RequestException as e:
        logging.error(f"Error de red al obtener la lista de ministerios: {e}")
        return None

# --- 3. MÓDULO DE TRANSFORMACIÓN (TRANSFORM) ---

def transform_data(raw_xml: bytes):
    """
    Parsea el XML de ministerios y lo convierte en una lista de diccionarios.
    """
    if not raw_xml:
        return []

    ministerios = []
    try:
        root = ET.fromstring(raw_xml)
        ns = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}
        
        for ministerio_elem in root.findall('.//v1:Ministerio', ns):
            camara_id = ministerio_elem.findtext('v1:Id', namespaces=ns)
            nombre = ministerio_elem.findtext('v1:Nombre', namespaces=ns)
            
            if camara_id and nombre:
                ministerios.append({
                    'camara_ministerio_id': int(camara_id),
                    'nombre_ministerio': nombre.strip()
                })
        
        return ministerios
        
    except ET.ParseError as e:
        logging.error(f"Error al parsear XML de ministerios: {e}")
        return []

# --- 4. MÓDULO DE CARGA (LOAD) ---

def load_data(conn: sqlite3.Connection, ministerios: list):
    """
    Carga la lista de ministerios en la tabla `dim_ministerios` usando un UPSERT.
    """
    if not ministerios:
        logging.warning("No hay ministerios para cargar.")
        return

    cursor = conn.cursor()
    
    # Prepara los datos para executemany
    values_to_load = [(m['camara_ministerio_id'], m['nombre_ministerio']) for m in ministerios]

    # UPSERT: Inserta un nuevo ministerio si no existe (basado en camara_ministerio_id).
    # Si ya existe, actualiza su nombre por si ha cambiado.
    cursor.executemany("""
        INSERT INTO dim_ministerios (camara_ministerio_id, nombre_ministerio)
        VALUES (?, ?)
        ON CONFLICT(camara_ministerio_id) DO UPDATE SET
            nombre_ministerio=excluded.nombre_ministerio;
    """, values_to_load)
    
    conn.commit()
    logging.info(f"Proceso de carga finalizado. Se procesaron {len(ministerios)} ministerios.")
    logging.info(f"{cursor.rowcount} filas fueron afectadas en la base de datos.")


# --- 5. ORQUESTADOR PRINCIPAL (MAIN) ---

def main():
    """
    Función principal que orquesta todo el proceso ETL para ministerios.
    """
    logging.info("--- [ETL Ministerios] Iniciando proceso ---")
    
    headers = {'User-Agent': 'ParlamentoAbierto-ETL/1.0'}
    with requests.Session() as session:
        session.headers.update(headers)
        
        raw_data = fetch_data(session)
        transformed_data = transform_data(raw_data)
        
        if transformed_data:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("PRAGMA foreign_keys = ON;")
                    load_data(conn, transformed_data)
            except sqlite3.Error as e:
                logging.error(f"Error de base de datos durante la carga: {e}")
        else:
            logging.warning("No se transformaron datos, finalizando proceso.")

    logging.info("--- Proceso ETL Ministerios finalizado. ---")

if __name__ == "__main__":
    main()