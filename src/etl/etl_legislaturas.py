# src/etl/etl_legislaturas.py
# -*- coding: utf-8 -*-

"""
Módulo ETL para Legislaturas con Lógica de Respaldo Local.

Este script implementa el proceso de Extracción, Transformación y Carga para
poblar la tabla dimensional `dim_legislatura`.

Intenta obtener los datos desde la API de la Cámara de Diputados. Si la API
falla o no devuelve datos, utiliza un archivo XML local como fuente de respaldo.
"""

import sqlite3
import requests
import xml.etree.ElementTree as ET
import os

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYECTO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')

# --- RUTA DEL ARCHIVO XML DE RESPALDO ---
XML_FALLBACK_PATH = os.path.join(PROJECT_ROOT, 'data', 'xml', 'legislaturas.xml')

# URI del namespace definido en el XML de la API
NAMESPACE_URI = 'http://opendata.camara.cl/camaradiputados/v1'
TAG_PERIODO = f'{{{NAMESPACE_URI}}}PeriodoLegislativo'
TAG_LEGISLATURAS = f'{{{NAMESPACE_URI}}}Legislaturas'
TAG_LEGISLATURA = f'{{{NAMESPACE_URI}}}Legislatura'
TAG_ID = f'{{{NAMESPACE_URI}}}Id'
TAG_NUMERO = f'{{{NAMESPACE_URI}}}Numero'
TAG_FECHA_INICIO = f'{{{NAMESPACE_URI}}}FechaInicio'
TAG_FECHA_TERMINO = f'{{{NAMESPACE_URI}}}FechaTermino'
TAG_TIPO = f'{{{NAMESPACE_URI}}}Tipo'

# Endpoint para obtener TODOS los períodos legislativos
API_URL = "https://opendata.camara.cl/camaradiputados/WServices/WSCamaradeDiputados.asmx/retornarPeriodosLegislativos"


# --- 2. FASE DE EXTRACCIÓN Y TRANSFORMACIÓN ---

def _parse_xml_content(xml_content):
    """
    Función auxiliar que parsea el contenido XML (desde API o archivo)
    y devuelve una lista de diccionarios de legislaturas.
    """
    legislaturas_list = []
    try:
        root = ET.fromstring(xml_content)
        for periodo in root.findall(TAG_PERIODO):
            legislaturas_container = periodo.find(TAG_LEGISLATURAS)
            if legislaturas_container is not None:
                for legislatura_node in legislaturas_container.findall(TAG_LEGISLATURA):
                    fecha_inicio_str = legislatura_node.findtext(TAG_FECHA_INICIO)
                    fecha_termino_str = legislatura_node.findtext(TAG_FECHA_TERMINO)
                    tipo_node = legislatura_node.find(TAG_TIPO)
                    tipo_valor = tipo_node.text if tipo_node is not None else "No especificado"
                    legislatura_data = {
                        'legislatura_id': int(legislatura_node.findtext(TAG_ID)),
                        'numero': int(legislatura_node.findtext(TAG_NUMERO)),
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
    Intenta obtener las legislaturas desde la API. Si falla o no devuelve datos,
    recurre a un archivo XML local como respaldo.
    """
    legislaturas_data = []
    
    # --- Intento 1: Obtener datos desde la API ---
    try:
        print("🏛️  [ETL] Intentando obtener datos desde la API...")
        response = requests.get(API_URL, timeout=60)
        response.raise_for_status()
        
        legislaturas_data = _parse_xml_content(response.content)

        if legislaturas_data:
            print(f"✅  [ETL] Se procesaron {len(legislaturas_data)} legislaturas desde la API.")
            # Guarda una copia local como respaldo para el futuro
            os.makedirs(os.path.dirname(XML_FALLBACK_PATH), exist_ok=True)
            with open(XML_FALLBACK_PATH, 'wb') as f:
                f.write(response.content)
            print(f"✅  [ETL] Respaldo actualizado en '{XML_FALLBACK_PATH}'")
            return legislaturas_data
        else:
            # La API respondió pero no se encontraron datos, se activa el respaldo
            print("⚠️  [ETL] La API no devolvió legislaturas válidas.")

    except requests.exceptions.RequestException as e:
        # La API falló (error de red, bloqueo, etc.), se activa el respaldo
        print(f"❌  [ETL] Error de red al conectar con la API: {e}")

    # --- Intento 2: Usar archivo local de respaldo ---
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
    Carga la lista de legislaturas en la tabla `dim_legislatura` usando una
    estrategia de "borrar y recargar".
    """
    if not legislaturas:
        print("⚠️  [ETL] No hay datos de legislaturas para cargar en la base de datos.")
        return

    print("⚙️  [ETL] Cargando datos en la tabla `dim_legislatura`...")
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM dim_legislatura;")
        datos_para_insertar = [tuple(leg.values()) for leg in legislaturas]
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
    Función principal que orquesta el proceso ETL completo para las legislaturas.
    """
    print("--- Iniciando Proceso ETL: Legislaturas (Historial Completo) ---")
    try:
        legislaturas_data = fetch_and_transform_all_legislaturas()
        if legislaturas_data:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON;")
                load_legislaturas_to_db(legislaturas_data, conn)
    except Exception as e:
        print(f"❌  Error Crítico durante la operación ETL de Legislaturas: {e}")
    print("\n--- Proceso ETL de Legislaturas Finalizado ---")

if __name__ == "__main__":
    main()