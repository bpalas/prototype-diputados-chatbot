# src/etl/etl_comisiones.py
# -*- coding: utf-8 -*-

"""
Módulo ETL para Comisiones Parlamentarias v3.1

Este script implementa el proceso de Extracción, Transformación y Carga para poblar
las tablas `dim_comisiones` y `comision_membresias`.

v3.1:
- Añadido filtro para comisiones con nombres duplicados para prevenir errores de 'UNIQUE constraint'.
- Corregido el parámetro del endpoint de detalle a `prmComisionId`.
- Implementa carga de datos por lotes (batch) usando `executemany` para mayor eficiencia.
- Mejora la robustez en el parseo de XML y el feedback en consola.
- Añade un mapeo local para los tipos de comisión para normalizar los datos.
- Mantiene el sistema de caché local para optimizar las ejecuciones.
"""
import sqlite3
import requests
import xml.etree.ElementTree as ET
import os
import time
from typing import List, Dict, Tuple, Optional

# --- 1. CONFIGURACIÓN Y RUTAS ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
XML_CACHE_PATH = os.path.join(PROJECT_ROOT, 'data', 'xml', 'comisiones')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}

# Mapeo para normalizar los tipos de comisión según tu schema
TIPO_COMISION_MAP = {
    "Permanente": "Permanente",
    "Especial Investigadora": "Especial Investigadora",
    "Bicameral": "Bicameral"
    # Añadir otros tipos si aparecen en la API
}


# --- 2. FASE DE EXTRACCIÓN (CON CACHÉ) ---

def get_xml_content(url: str, cache_filename: str) -> Optional[bytes]:
    """Obtiene contenido XML desde una URL, usando un caché local para evitar peticiones repetidas."""
    cache_filepath = os.path.join(XML_CACHE_PATH, cache_filename)
    if os.path.exists(cache_filepath):
        print(f"   -> Leyendo desde caché: {cache_filename}")
        with open(cache_filepath, 'rb') as f:
            return f.read()
    
    print(f"   -> Obteniendo desde API: {url.split('?')[0]}...")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        xml_content = response.content
        with open(cache_filepath, 'wb') as f:
            f.write(xml_content)
        print("      -> XML guardado en caché.")
        time.sleep(0.3)  # Pausa para no saturar el servidor
        return xml_content
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Error de red al intentar acceder a {url}: {e}")
        return None

def fetch_comisiones_list() -> List[Dict[str, str]]:
    """Obtiene la lista de IDs de las comisiones vigentes."""
    url = "https://opendata.camara.cl/camaradiputados/WServices/WSComision.asmx/retornarComisionesVigentes"
    print("🏛️  [EXTRACCIÓN] Obteniendo listado de comisiones vigentes...")
    xml_content = get_xml_content(url, "comisiones_vigentes.xml")
    if not xml_content:
        return []
    
    comisiones = []
    root = ET.fromstring(xml_content)
    for comision_node in root.findall('.//{http://opendata.camara.cl/camaradiputados/v1}Comision'):
        comision_id = comision_node.findtext('{http://opendata.camara.cl/camaradiputados/v1}Id')
        if comision_id:
            comisiones.append({'id': comision_id})
            
    print(f"✅ Se encontraron {len(comisiones)} comisiones vigentes para procesar.")
    return comisiones

def parse_comision_details(comision_id: str) -> Optional[Tuple[Dict, List]]:
    """Parsea los detalles y miembros de una comisión específica a partir de su XML."""
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSComision.asmx/retornarComision?prmComisionId={comision_id}"
    xml_content = get_xml_content(url, f"comision_{comision_id}.xml")
    if not xml_content:
        return None

    root = ET.fromstring(xml_content)
    
    # Extraer detalles de la comisión
    tipo_raw = root.findtext('v1:Tipo', namespaces=NS)
    tipo_normalizado = TIPO_COMISION_MAP.get(tipo_raw, 'Permanente') # Default a 'Permanente'

    comision_details = {
        'id': int(root.findtext('v1:Id', namespaces=NS)),
        'nombre': root.findtext('v1:Nombre', namespaces=NS),
        'tipo': tipo_normalizado
    }

    # Extraer ID del presidente para asignarle el rol correcto
    presidente_id_node = root.find('.//v1:Presidente/v1:Diputado/v1:Id', namespaces=NS)
    presidente_id = presidente_id_node.text if presidente_id_node is not None else None

    # Extraer integrantes
    integrantes = []
    for integrante_node in root.findall('.//v1:Integrantes/v1:DiputadoIntegrante', NS):
        diputado_id = integrante_node.findtext('.//v1:Id', namespaces=NS)
        fecha_inicio_str = integrante_node.findtext('v1:FechaInicio', namespaces=NS)
        fecha_fin_str = integrante_node.findtext('v1:FechaTermino', namespaces=NS)
        
        if diputado_id:
            integrantes.append({
                'diputado_id': diputado_id,
                'rol': 'Presidente' if diputado_id == presidente_id else 'Miembro',
                'fecha_inicio': fecha_inicio_str.split('T')[0] if fecha_inicio_str else None,
                'fecha_fin': fecha_fin_str.split('T')[0] if fecha_fin_str and 'nil' not in fecha_fin_str else None
            })
            
    return comision_details, integrantes


# --- 3. FASE DE CARGA (CORREGIDA) ---

def load_data_to_db(all_comisiones_data: List[Tuple[Dict, List]], conn: sqlite3.Connection):
    """Carga los datos de comisiones y membresías, filtrando duplicados antes de insertar."""
    cursor = conn.cursor()
    print("\n🧹 Limpiando tablas de destino: `dim_comisiones` y `comision_membresias`...")
    cursor.execute("DELETE FROM comision_membresias;")
    cursor.execute("DELETE FROM dim_comisiones;")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('dim_comisiones', 'comision_membresias');")
    conn.commit()

    print("⚙️  [CARGA] Preparando y cargando datos en la base de datos...")
    
    cursor.execute("SELECT diputadoid, mp_uid FROM dim_parlamentario")
    diputado_map = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Usar un diccionario para filtrar comisiones con nombres duplicados
    comisiones_unicas = {}
    membresias_a_cargar = []
    
    for comision_details, integrantes in all_comisiones_data:
        nombre_comision = comision_details['nombre']
        
        # Al usar el nombre como clave, si aparece un duplicado, simplemente sobreescribe la entrada.
        # Esto asegura que solo tengamos una entrada por nombre de comisión.
        comisiones_unicas[nombre_comision] = (
            comision_details['id'], 
            nombre_comision, 
            comision_details['tipo']
        )
        
        for integrante in integrantes:
            diputado_id = integrante['diputado_id']
            mp_uid = diputado_map.get(diputado_id)
            
            if mp_uid:
                membresias_a_cargar.append(
                    (mp_uid, comision_details['id'], integrante['rol'], 
                     integrante['fecha_inicio'], integrante['fecha_fin'])
                )
            else:
                print(f"   ⚠️  Advertencia: No se encontró `mp_uid` para `diputadoid` {diputado_id} en la comisión '{nombre_comision}'. Se omitirá.")

    # Convertir los valores del diccionario a una lista para la carga
    comisiones_a_cargar = list(comisiones_unicas.values())

    try:
        # Insertar todos los datos en dos operaciones por lotes
        cursor.executemany(
            "INSERT INTO dim_comisiones (comision_id, nombre_comision, tipo) VALUES (?, ?, ?)",
            comisiones_a_cargar
        )
        print(f"   -> Se insertaron {len(comisiones_a_cargar)} registros únicos en `dim_comisiones`.")

        cursor.executemany(
            """INSERT INTO comision_membresias (mp_uid, comision_id, rol, fecha_inicio, fecha_fin) 
               VALUES (?, ?, ?, ?, ?)""",
            membresias_a_cargar
        )
        print(f"   -> Se insertaron {len(membresias_a_cargar)} registros en `comision_membresias`.")
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"❌ Error durante la carga a la base de datos: {e}")
        conn.rollback()

    print(f"\n✅ Carga finalizada.")


# --- 4. ORQUESTACIÓN ---

def main():
    """Función principal que orquesta el proceso ETL completo."""
    print("--- Iniciando Proceso ETL: Comisiones Parlamentarias (v3.1) ---")
    try:
        os.makedirs(XML_CACHE_PATH, exist_ok=True)
        
        # 1. Extracción y Transformación
        lista_ids_comisiones = fetch_comisiones_list()
        
        if not lista_ids_comisiones:
            print("No se encontraron comisiones para procesar. Finalizando.")
            return

        all_data = []
        total = len(lista_ids_comisiones)
        print("\n🔎 [TRANSFORMACIÓN] Parseando detalles de cada comisión...")
        for i, comision_ref in enumerate(lista_ids_comisiones):
            comision_id = comision_ref['id']
            print(f"   ({i+1}/{total}) Procesando comisión ID: {comision_id}")
            parsed_data = parse_comision_details(comision_id)
            if parsed_data:
                all_data.append(parsed_data)
        
        # 2. Carga
        if all_data:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON;")
                load_data_to_db(all_data, conn)
                
    except Exception as e:
        print(f"\n❌ Error Crítico durante la operación ETL de Comisiones: {e}")

    print("\n--- Proceso ETL de Comisiones Finalizado ---")

if __name__ == "__main__":
    main()