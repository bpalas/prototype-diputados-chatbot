# src/etl/etl_bills_enrichment.py
# -*- coding: utf-8 -*-
"""
ETL - Enriquecimiento de Proyectos de Ley (Versión Modular)

Este script orquesta la extracción, transformación y carga de datos de proyectos
de ley desde múltiples fuentes. Su diseño modular separa cada paso lógico
en funciones dedicadas para mayor claridad, mantenimiento y robustez.

Pasos del Proceso por cada Boletín:
1. Extrae datos crudos del Senado, Cámara y BCN, usando un sistema de caché.
2. Transforma (parsea) los datos de cada fuente de forma independiente.
3. Unifica los datos transformados en una estructura de datos común.
4. Carga los datos en la base de datos en una transacción única,
   poblando la tabla `bills` y todas sus tablas relacionadas (`bill_authors`,
   `bill_ministerios_patrocinantes`, `bill_tramites`, etc.).
"""
import argparse
import json
import logging
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import requests

# --- 1. CONFIGURACIÓN ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "database" / "parlamento.db"
CACHE_PATH = PROJECT_ROOT / "data" / "cache"
INPUT_FILE = PROJECT_ROOT / "data" / "bill_ids_to_process.txt"

API_CONFIG = {
    "senado": {
        "url_template": "https://tramitacion.senado.cl/wspublico/tramitacion.php?boletin={}",
        "file_ext": "xml",
        "id_formatter": lambda bill_id: bill_id.split('-')[0]
    },
    "camara": {
        "url_template": "https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarProyectoLey?prmNumeroBoletin={}",
        "file_ext": "xml",
        "id_formatter": lambda bill_id: bill_id
    },
    "bcn": {
        "url_template": "https://datos.bcn.cl/recurso/cl/proyecto-de-ley/{}/datos.json",
        "file_ext": "json",
        "id_formatter": lambda bill_id: bill_id
    }
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


# --- 2. MÓDULO DE EXTRACCIÓN (EXTRACT) ---

def fetch_data(session: requests.Session, bill_id: str, api_source: str, use_cache: bool = True):
    """
    Obtiene datos de una API específica para un boletín, utilizando un sistema de caché.

    Args:
        session (requests.Session): La sesión de requests para realizar la petición.
        bill_id (str): El identificador del boletín (ej: "12345-06").
        api_source (str): La clave de la fuente de datos ('senado', 'camara', 'bcn').
        use_cache (bool): Si es True, intenta leer del caché antes de descargar.

    Returns:
        tuple[bytes | None, str | None]: El contenido de la respuesta y la URL final.
    """
    config = API_CONFIG.get(api_source)
    if not config: return None, None
    api_id = config["id_formatter"](bill_id)
    url = config["url_template"].format(api_id)
    
    cache_dir = CACHE_PATH / api_source
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{bill_id}.{config['file_ext']}"

    if use_cache and cache_file.exists():
        logging.info(f"Cargando {bill_id} desde caché para '{api_source}'.")
        return cache_file.read_bytes(), url

    logging.info(f"Obteniendo {bill_id} desde API '{api_source}'...")
    try:
        response = session.get(url, timeout=45)
        response.raise_for_status()
        content = response.content
        cache_file.write_bytes(content)
        time.sleep(0.3)
        return content, url
    except requests.exceptions.RequestException as e:
        logging.error(f"Error de red para {bill_id} en '{api_source}': {e}")
        return None, None


# --- 3. MÓDULO DE TRANSFORMACIÓN (TRANSFORM) ---

def parse_date(date_str: str | None, formats: list[str]) -> str | None:
    """Función de ayuda para parsear fechas en diferentes formatos."""
    if not date_str: return None
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            continue
    return None

def parse_senado_data(senado_xml: bytes) -> dict:
    """Parsea el XML del Senado para extraer datos del proyecto y sus trámites."""
    bill_info = {}
    tramites = []
    if not senado_xml: return {'bill_info': bill_info, 'tramites': tramites}

    try:
        root = ET.fromstring(senado_xml)
        if (proyecto := root.find('.//proyecto/descripcion')) is not None:
            numero_ley_raw = proyecto.findtext('leynro')
            bill_info['numero_ley'] = numero_ley_raw.replace('Ley Nº', '').replace('.', '').strip() if numero_ley_raw else None
            bill_info.update({
                'titulo': proyecto.findtext('titulo', '').strip(),
                'fecha_ingreso': parse_date(proyecto.findtext('fecha_ingreso'), ['%d/%m/%Y']),
                'iniciativa': proyecto.findtext('iniciativa', '').strip(),
                'origen': proyecto.findtext('camara_origen', '').strip(),
                'etapa': proyecto.findtext('etapa', '').strip(),
                'subetapa': proyecto.findtext('subetapa', '').strip(),
                'urgencia': proyecto.findtext('urgencia_actual', '').strip(),
                'resultado_final': proyecto.findtext('estado', '').strip(),
                'refundidos': proyecto.findtext('refundidos', '').strip(),
            })
        for tramite in root.findall('.//tramitacion/tramite'):
            tramites.append({'fecha_tramite': parse_date(tramite.findtext('FECHA'), ['%d/%m/%Y']),'descripcion': tramite.findtext('DESCRIPCIONTRAMITE', '').strip(),'etapa_especifica': tramite.findtext('ETAPDESCRIPCION', '').strip(),'camara': tramite.findtext('CAMARATRAMITE', '').strip(),'sesion': tramite.findtext('SESION', '').strip(),})
    except ET.ParseError as e:
        logging.warning(f"Error al parsear XML del Senado: {e}")
    
    return {'bill_info': bill_info, 'tramites': tramites}

def parse_camara_data(camara_xml: bytes) -> dict:
    """Parsea el XML de la Cámara para extraer autores, ministerios y materias."""
    diputados, senadores, ministerios, materias = [], [], [], []
    if not camara_xml: return {'diputados': diputados, 'senadores': senadores, 'ministerios': ministerios, 'materias': materias}
    
    try:
        ns = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}
        root = ET.fromstring(camara_xml)
        for autor in root.findall('.//v1:Autores/v1:ParlamentarioAutor/v1:Diputado', ns):
            if dip_id := autor.findtext('v1:Id', namespaces=ns):
                diputados.append({'diputadoid': dip_id})
        for autor in root.findall('.//v1:Autores/v1:ParlamentarioAutor/v1:Senador', ns):
            if sen_id := autor.findtext('v1:Id', namespaces=ns):
                nombre_completo = f"{autor.findtext('v1:Nombre', '', ns)} {autor.findtext('v1:ApellidoPaterno', '', ns)} {autor.findtext('v1:ApellidoMaterno', '', ns)}".strip()
                senadores.append({'senadorid': sen_id, 'nombre_completo': nombre_completo})
        for ministerio in root.findall('.//v1:MinisteriosPatrocinantes/v1:Ministerio', ns):
            if min_id := ministerio.findtext('v1:Id', namespaces=ns):
                ministerios.append({'camara_ministerio_id': min_id})
        for materia in root.findall('.//v1:Materias/v1:Materia', ns):
            if nombre_materia := materia.findtext('v1:Nombre', namespaces=ns):
                materias.append({'nombre': nombre_materia.strip().capitalize()})
    except ET.ParseError as e:
        logging.warning(f"Error al parsear XML de la Cámara: {e}")
        
    return {'diputados': diputados, 'senadores': senadores, 'ministerios': ministerios, 'materias': materias}

def parse_bcn_data(bcn_json: bytes) -> dict:
    """Parsea el JSON de la BCN para extraer metadatos adicionales."""
    bill_info = {}
    if not bcn_json: return {'bill_info': bill_info}
    
    try:
        data = json.loads(bcn_json)
        main_key = list(data.keys())[0]
        recurso = data[main_key]
        tipo_proyecto_list = recurso.get('http://datos.bcn.cl/ontologies/bcn-resources#tipoProyecto', [])
        if tipo_proyecto_list:
            bill_info['tipo_proyecto'] = tipo_proyecto_list[0].get('value', '').split('#')[-1]
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logging.warning(f"Error al parsear JSON de BCN: {e}")

    return {'bill_info': bill_info}
# Reemplaza esta función completa en tu archivo etl_bills_enrichment.py

def transform_data(bill_id: str, sources_content: dict) -> dict | None:
    """
    Función principal de transformación que orquesta el parseo y la unificación de datos.
    """
    # 1. Parsear cada fuente de forma independiente
    senado_data = parse_senado_data(sources_content.get('senado'))
    camara_data = parse_camara_data(sources_content.get('camara'))
    bcn_data = parse_bcn_data(sources_content.get('bcn'))
    
    # 2. Unificar datos del proyecto de ley
    # CORRECCIÓN: Empezamos con la plantilla completa para asegurar que todos los campos existan
    bill_template = {
        'bill_id': bill_id, 'titulo': None, 'resumen': None, 'tipo_proyecto': None,
        'fecha_ingreso': None, 'etapa': None, 'subetapa': None, 'iniciativa': None,
        'origen': None, 'urgencia': None, 'resultado_final': None, 'estado': 'TRAMITACIÓN',
        'refundidos': None, 'numero_ley': None, 'norma_id': None,
        'fecha_actualizacion': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    bill_data = bill_template.copy()

    # Actualizamos la plantilla con los datos que sí encontramos
    bill_data.update(bcn_data.get('bill_info', {}))
    bill_data.update(senado_data.get('bill_info', {}))
    
    # 3. Lógica de estado final
    if etapa := bill_data.get('etapa'):
        etapa_lower = etapa.lower()
        if 'publicado' in etapa_lower or 'tramitación terminada' in etapa_lower: bill_data['estado'] = 'PUBLICADO'
        elif 'archivado' in etapa_lower: bill_data['estado'] = 'ARCHIVADO'
        elif 'rechazado' in etapa_lower: bill_data['estado'] = 'RECHAZADO'

    # 4. Validar que tenemos información mínima
    if not bill_data.get('titulo'): 
        return None

    # 5. Devolver toda la información estructurada
    return {
        "bill": bill_data, 
        "diputados": camara_data['diputados'], 
        "senadores": camara_data['senadores'], 
        "ministerios": camara_data['ministerios'], 
        "tramites": senado_data['tramites'], 
        "materias": camara_data['materias']
    }

# --- 4. MÓDULO DE CARGA (LOAD) ---

def load_bill_main_data(cursor: sqlite3.Cursor, bill_data: dict):
    """Carga o actualiza la información principal del proyecto en la tabla `bills`."""
    cursor.execute("""
        INSERT INTO bills (bill_id, titulo, resumen, tipo_proyecto, fecha_ingreso, etapa, subetapa, iniciativa, origen, urgencia, resultado_final, estado, refundidos, numero_ley, norma_id, fecha_actualizacion)
        VALUES (:bill_id, :titulo, :resumen, :tipo_proyecto, :fecha_ingreso, :etapa, :subetapa, :iniciativa, :origen, :urgencia, :resultado_final, :estado, :refundidos, :numero_ley, :norma_id, :fecha_actualizacion)
        ON CONFLICT(bill_id) DO UPDATE SET
            titulo=excluded.titulo, etapa=excluded.etapa, subetapa=excluded.subetapa, urgencia=excluded.urgencia, resultado_final=excluded.resultado_final, estado=excluded.estado, numero_ley=excluded.numero_ley, fecha_actualizacion=excluded.fecha_actualizacion;
    """, {**{'resumen': None, 'norma_id': None}, **bill_data}) # Valores por defecto para campos que podrían faltar
    
def load_bill_authors_and_sponsors(cursor: sqlite3.Cursor, bill_id: str, data: dict):
    """Carga los autores (diputados/senadores) y ministerios patrocinantes."""
    cursor.execute("DELETE FROM bill_authors WHERE bill_id = ?", (bill_id,))
    cursor.execute("DELETE FROM bill_ministerios_patrocinantes WHERE bill_id = ?", (bill_id,))

    if diputados := data.get('diputados'):
        diputados_values = [(bill_id, d['diputadoid']) for d in diputados]
        cursor.executemany("INSERT INTO bill_authors (bill_id, mp_uid) SELECT ?, p.mp_uid FROM dim_parlamentario p WHERE p.diputadoid = ? ON CONFLICT(bill_id, mp_uid) DO NOTHING;", diputados_values)
        logging.info(f"Procesados {len(diputados_values)} autores diputados para {bill_id}.")

    if senadores := data.get('senadores'):
        senadores_cargados = 0
        for senador in senadores:
            sen_id, sen_nombre = senador['senadorid'], senador['nombre_completo']
            cursor.execute("UPDATE dim_parlamentario SET senadorid = ? WHERE nombre_completo = ? AND senadorid IS NULL", (sen_id, sen_nombre))
            if cursor.rowcount > 0: logging.info(f"ENRIQUECIMIENTO: Se ha añadido el senadorid {sen_id} al parlamentario '{sen_nombre}'.")
            cursor.execute("INSERT INTO bill_authors (bill_id, mp_uid) SELECT ?, p.mp_uid FROM dim_parlamentario p WHERE p.senadorid = ? ON CONFLICT(bill_id, mp_uid) DO NOTHING;", (bill_id, sen_id))
            if cursor.rowcount > 0: senadores_cargados += 1
        logging.info(f"Procesados {senadores_cargados} autores senadores para {bill_id}.")

    if ministerios := data.get('ministerios'):
        ministerios_values = [(bill_id, m['camara_ministerio_id']) for m in ministerios]
        cursor.executemany("INSERT INTO bill_ministerios_patrocinantes (bill_id, ministerio_id) SELECT ?, m.ministerio_id FROM dim_ministerios m WHERE m.camara_ministerio_id = ? ON CONFLICT(bill_id, ministerio_id) DO NOTHING;", ministerios_values)
        logging.info(f"Procesados {len(ministerios_values)} ministerios patrocinantes para {bill_id}.")

def load_bill_relations(cursor: sqlite3.Cursor, bill_id: str, data: dict):
    """Carga las relaciones secundarias: trámites y materias."""
    if tramites := data.get('tramites'):
        cursor.execute("DELETE FROM bill_tramites WHERE bill_id = ?", (bill_id,))
        tramites_values = [(bill_id, t['fecha_tramite'], t['descripcion'], t['etapa_especifica'], t['camara'], t['sesion']) for t in tramites]
        cursor.executemany("INSERT INTO bill_tramites (bill_id, fecha_tramite, descripcion, etapa_especifica, camara, sesion) VALUES (?, ?, ?, ?, ?, ?)", tramites_values)

    if materias := data.get('materias'):
        cursor.execute("DELETE FROM bill_materias WHERE bill_id = ?", (bill_id,))
        materias_values = [(m['nombre'],) for m in materias]
        cursor.executemany("INSERT OR IGNORE INTO dim_materias (nombre) VALUES (?)", materias_values)
        association_values = [(bill_id, m['nombre']) for m in materias]
        cursor.executemany("INSERT INTO bill_materias (bill_id, materia_id) SELECT ?, m.materia_id FROM dim_materias m WHERE m.nombre = ? ON CONFLICT(bill_id, materia_id) DO NOTHING;", association_values)

def load_entity_sources(cursor: sqlite3.Cursor, bill_id: str, sources_urls: dict):
    """Carga las URLs de origen del proyecto en la tabla `entity_sources`."""
    cursor.execute("DELETE FROM entity_sources WHERE entity_id = ? AND entity_type = 'bill'", (bill_id,))
    source_values = [(bill_id, 'bill', name, url, datetime.now().strftime("%Y-%m-%d %H:%M:%S")) for name, url in sources_urls.items() if url]
    cursor.executemany("INSERT INTO entity_sources (entity_id, entity_type, source_name, url, last_checked_at) VALUES (?, ?, ?, ?, ?)", source_values)


# --- 5. ORQUESTADOR PRINCIPAL (MAIN) ---

def main(limit: int | None = None, use_cache: bool = True):
    """
    Función principal que orquesta el pipeline ETL completo.
    """
    logging.info(f"--- [ETL Bills Enrichment] Iniciando proceso (Caché {'Activado' if use_cache else 'Desactivado'}) ---")
    if not INPUT_FILE.exists():
        logging.error(f"No se encuentra el archivo de entrada: {INPUT_FILE}")
        return
    with INPUT_FILE.open('r') as f:
        bill_ids = [line.strip() for line in f if line.strip()]
    if not bill_ids:
        logging.info("No hay boletines para procesar. Finalizando.")
        return
    if limit:
        bill_ids = bill_ids[:limit]
    
    headers = {'User-Agent': 'ParlamentoAbierto-ETL/1.0'}
    with requests.Session() as session:
        session.headers.update(headers)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            total = len(bill_ids)
            for i, bill_id in enumerate(bill_ids, 1):
                logging.info(f"--- Procesando {i}/{total}: {bill_id} ---")
                
                # EXTRACT
                senado_content, senado_url = fetch_data(session, bill_id, 'senado', use_cache=use_cache)
                camara_content, camara_url = fetch_data(session, bill_id, 'camara', use_cache=use_cache)
                bcn_content, bcn_url = fetch_data(session, bill_id, 'bcn', use_cache=use_cache)
                
                # TRANSFORM
                sources_content = {'senado': senado_content, 'camara': camara_content, 'bcn': bcn_content}
                transformed_data = transform_data(bill_id, sources_content)
                
                # LOAD
                if transformed_data:
                    try:
                        conn.execute("BEGIN TRANSACTION;")
                        cursor = conn.cursor()
                        sources_urls = {'senado_boletin': senado_url, 'camara_boletin': camara_url, 'bcn_proyecto': bcn_url}
                        
                        load_bill_main_data(cursor, transformed_data['bill'])
                        load_bill_authors_and_sponsors(cursor, bill_id, transformed_data)
                        load_bill_relations(cursor, bill_id, transformed_data)
                        load_entity_sources(cursor, bill_id, sources_urls)
                        
                        conn.commit()
                        logging.info(f"Transacción para {bill_id} completada exitosamente.")
                    except sqlite3.Error as e:
                        logging.error(f"Error en transacción para {bill_id}: {e}")
                        conn.rollback()
                else:
                    logging.warning(f"No se encontró información suficiente para transformar {bill_id}. Se omite.")

    logging.info("--- Proceso finalizado. ---")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL modular para enriquecer proyectos de ley, autores y ministerios.")
    parser.add_argument("--limit", type=int, help="Limita el número de boletines a procesar.")
    parser.add_argument("--no-cache", action="store_true", help="Desactiva el uso de caché y fuerza la descarga.")
    args = parser.parse_args()
    
    main(limit=args.limit, use_cache=not args.no_cache)