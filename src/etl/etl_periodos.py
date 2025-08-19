# src/etl/etl_periodos.py
# -*- coding: utf-8 -*-

"""
ETL para poblar la tabla dim_periodo_legislativo.
Debe ejecutarse antes que cualquier otro ETL que dependa de los períodos.
"""
import sqlite3
import requests
import xml.etree.ElementTree as ET
import os
import time

# --- CONFIGURACIÓN ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
XML_CACHE_PATH = os.path.join(PROJECT_ROOT, 'data', 'xml', 'periodos')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}

def get_xml_content(url: str, cache_filename: str) -> bytes | None:
    """Obtiene contenido XML desde una URL, usando un caché local."""
    os.makedirs(XML_CACHE_PATH, exist_ok=True)
    cache_filepath = os.path.join(XML_CACHE_PATH, cache_filename)
    if os.path.exists(cache_filepath):
        print(f"  -> [Periodos] Leyendo desde caché: {cache_filename}")
        with open(cache_filepath, 'rb') as f:
            return f.read()
    
    print(f"  -> [Periodos] Obteniendo desde API...")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        xml_content = response.content
        with open(cache_filepath, 'wb') as f:
            f.write(xml_content)
        return xml_content
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error de red: {e}")
        return None

def main():
    print("--- Iniciando ETL: Períodos Legislativos ---")
    url = "https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarPeriodosLegislativos"
    xml_content = get_xml_content(url, "periodos_legislativos.xml")
    
    if not xml_content:
        print("❌ No se pudo obtener la información de los períodos. Finalizando.")
        return

    root = ET.fromstring(xml_content)
    periodos_a_cargar = []
    for nodo in root.findall('.//v1:PeriodoLegislativo', NS):
        periodo_id = nodo.findtext('v1:Id', namespaces=NS)
        nombre = nodo.findtext('v1:Nombre', namespaces=NS)
        fecha_inicio = nodo.findtext('v1:FechaInicio', namespaces=NS, default='').split('T')[0]
        fecha_termino = nodo.findtext('v1:FechaTermino', namespaces=NS, default='').split('T')[0]
        
        if periodo_id:
            periodos_a_cargar.append((
                int(periodo_id),
                nombre,
                fecha_inicio or None,
                fecha_termino or None
            ))
            
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM dim_periodo_legislativo;")
            cursor.executemany(
                "INSERT INTO dim_periodo_legislativo (periodo_id, nombre_periodo, fecha_inicio, fecha_termino) VALUES (?, ?, ?, ?)",
                periodos_a_cargar
            )
            conn.commit()
            print(f"✅ Se cargaron {len(periodos_a_cargar)} períodos legislativos.")
    except sqlite3.Error as e:
        print(f"❌ Error de base de datos: {e}")
        
    print("--- ETL de Períodos Finalizado ---")

if __name__ == "__main__":
    main()