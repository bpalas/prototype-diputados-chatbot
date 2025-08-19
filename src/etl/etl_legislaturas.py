# src/etl/etl_legislaturas.py
# -*- coding: utf-8 -*-

"""
Módulo ETL para Legislaturas con Lógica de Respaldo Local.

Este script implementa el proceso de Extracción, Transformación y Carga para
poblar la tabla dimensional `dim_legislatura` desde una fuente de datos plana.
"""

import sqlite3
import requests
import xml.etree.ElementTree as ET
import os

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYECTO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
XML_FALLBACK_PATH = os.path.join(PROJECT_ROOT, 'data', 'xml', 'legislaturas.xml')

NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}

# URL CORREGIDA para el endpoint que devuelve la lista plana de legislaturas
API_URL = "https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarLegislaturas"

# --- 2. FASE DE EXTRACCIÓN Y TRANSFORMACIÓN ---

def _parse_xml_content(xml_content):
    """
    Función auxiliar que parsea el contenido XML de legislaturas (estructura plana)
    y devuelve una lista de diccionarios.
    """
    legislaturas_list = []
    try:
        root = ET.fromstring(xml_content)
        # Iteramos directamente sobre 'v1:Legislatura' bajo el nodo raíz.
        for legislatura_node in root.findall('v1:Legislatura', NS):
            fecha_inicio_str = legislatura_node.findtext('v1:FechaInicio', namespaces=NS)
            fecha_termino_str = legislatura_node.findtext('v1:FechaTermino', namespaces=NS)
            tipo_node = legislatura_node.find('v1:Tipo', NS)
            tipo_valor = tipo_node.text if tipo_node is not None else "No especificado"
            
            legislatura_data = {
                'legislatura_id': int(legislatura_node.findtext('v1:Id', namespaces=NS)),
                'numero': int(legislatura_node.findtext('v1:Numero', namespaces=NS)),
                'fecha_inicio': fecha_inicio_str.split('T')[0] if fecha_inicio_str else None,
                'fecha_termino': fecha_termino_str.split('T')[0] if fecha_termino_str else None,
                'tipo': tipo_valor
            }
            legislaturas_list.append(legislatura_data)
    except (ET.ParseError, TypeError, ValueError, AttributeError) as e:
        print(f"❌  [ETL] Error al parsear el contenido XML: {e}")
    return legislaturas_list


def fetch_and_transform_all_legislaturas():
    """
    Intenta obtener las legislaturas desde la API. Si falla, recurre a un
    archivo XML local como respaldo.
    """
    legislaturas_data = []
    try:
        print("🏛️  [ETL] Intentando obtener datos desde la API...")
        response = requests.get(API_URL, timeout=60)
        response.raise_for_status()
        legislaturas_data = _parse_xml_content(response.content)

        if legislaturas_data:
            print(f"✅  [ETL] Se procesaron {len(legislaturas_data)} legislaturas desde la API.")
            os.makedirs(os.path.dirname(XML_FALLBACK_PATH), exist_ok=True)
            with open(XML_FALLBACK_PATH, 'wb') as f:
                f.write(response.content)
            print(f"✅  [ETL] Respaldo actualizado en '{XML_FALLBACK_PATH}'")
            return legislaturas_data
        else:
            print("⚠️  [ETL] La API no devolvió legislaturas válidas.")
    except requests.exceptions.RequestException as e:
        print(f"❌  [ETL] Error de red al conectar con la API: {e}")

    print(f"⚙️  [ETL] Intentando leer desde el archivo de respaldo local: '{XML_FALLBACK_PATH}'...")
    if os.path.exists(XML_FALLBACK_PATH):
        try:
            with open(XML_FALLBACK_PATH, 'rb') as f:
                xml_content = f.read()
            legislaturas_data = _parse_xml_content(xml_content)
            
            if legislaturas_data:
                print(f"✅  [ETL] Se procesaron {len(legislaturas_data)} legislaturas desde el archivo local.")
            else:
                print("⚠️  [ETL] El archivo de respaldo no contiene legislaturas válidas.")
        except IOError as e:
            print(f"❌  [ETL] No se pudo leer el archivo de respaldo: {e}")
    else:
        print(f"❌  [ETL] El archivo de respaldo no fue encontrado en la ruta especificada.")
    return legislaturas_data


# --- 3. FASE DE CARGA (Load) ---

def load_legislaturas_to_db(legislaturas, conn):
    """
    Carga la lista de legislaturas en la tabla `dim_legislatura`.
    """
    if not legislaturas:
        print("⚠️  [ETL] No hay datos de legislaturas para cargar en la base de datos.")
        return

    print("⚙️  [ETL] Cargando datos en la tabla `dim_legislatura`...")
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM dim_legislatura;")
        datos_para_insertar = [
            (
                leg['legislatura_id'], leg['numero'],
                leg['fecha_inicio'], leg['fecha_termino'], leg['tipo']
            ) for leg in legislaturas
        ]
        
        cursor.executemany("""
            INSERT OR REPLACE INTO dim_legislatura (legislatura_id, numero, fecha_inicio, fecha_termino, tipo)
            VALUES (?, ?, ?, ?, ?)
        """, datos_para_insertar)
        
        conn.commit()
        print(f"✅  [ETL] Se cargaron exitosamente {len(datos_para_insertar)} registros.")
    except sqlite3.Error as e:
        print(f"❌  [ETL] Error de base de datos durante la carga: {e}")
        conn.rollback()

# --- 4. ORQUESTACIÓN ---

def main():
    """
    Función principal que orquesta el proceso ETL completo.
    """
    print("--- Iniciando Proceso ETL: Legislaturas (Historial Completo) ---")
    try:
        legislaturas_data = fetch_and_transform_all_legislaturas()
        if legislaturas_data:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            with sqlite3.connect(DB_PATH) as conn:
                load_legislaturas_to_db(legislaturas_data, conn)
    except Exception as e:
        print(f"❌  Error Crítico durante la operación ETL de Legislaturas: {e}")
    print("\n--- Proceso ETL de Legislaturas Finalizado ---")

if __name__ == "__main__":
    main()