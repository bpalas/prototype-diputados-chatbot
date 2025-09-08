# src/etl/etl_materias.py
# -*- coding: utf-8 -*-
"""
ETL para la tabla dimensional de Materias.

- Intensidad de red: Baja (1 única llamada a la API).
- Objetivo: Poblar la tabla 'dim_materias' con el catálogo completo de
  materias legislativas de la Cámara de Diputados.
- Ejecución: Debe ejecutarse antes del ETL de enriquecimiento de proyectos
  para asegurar la integridad de las llaves foráneas.
"""
from __future__ import annotations

import os
import sqlite3
import xml.etree.ElementTree as ET
from typing import List, Tuple

import requests

# --- CONFIGURACIÓN ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
API_URL = "https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarMaterias"
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}

def fetch_materias_xml() -> str | None:
    """Extrae el XML con el listado completo de materias."""
    print("EXTRACT: Obteniendo el catálogo completo de materias...")
    try:
        response = requests.get(API_URL, timeout=120) # Aumentamos el timeout por si es una respuesta grande
        response.raise_for_status()
        print(" -> Extracción exitosa.")
        return response.content
    except requests.exceptions.RequestException as e:
        print(f"  ❗ ERROR: No se pudo obtener el XML de materias. Causa: {e}")
        return None

def transform_materias(xml_data: str) -> List[Tuple[int, str]]:
    """Transforma el XML en una lista de tuplas (id, nombre) para la base de datos."""
    print("TRANSFORM: Procesando XML y extrayendo materias...")
    materias_lista = []
    if not xml_data:
        return materias_lista
    
    try:
        root = ET.fromstring(xml_data)
        for materia_node in root.findall('v1:Materia', NS):
            materia_id = materia_node.findtext('v1:Id', namespaces=NS)
            materia_nombre = materia_node.findtext('v1:Nombre', namespaces=NS)

            if materia_id and materia_nombre:
                materias_lista.append(
                    (int(materia_id), materia_nombre.strip())
                )
        print(f" -> Se encontraron {len(materias_lista)} materias.")
        return materias_lista
    except ET.ParseError as e:
        print(f"  ❗ ERROR: El XML de materias está mal formado. Causa: {e}")
        return []

def load_materias_to_db(materias_data: List[Tuple[int, str]]):
    """Carga la lista de materias en la tabla dim_materias."""
    if not materias_data:
        print("LOAD: No hay materias para cargar.")
        return
        
    print(f"LOAD: Cargando {len(materias_data)} materias en la base de datos...")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Usamos INSERT OR IGNORE para añadir solo las materias nuevas
            # sin generar un error si ya existen.
            sql_query = "INSERT OR IGNORE INTO dim_materias (materia_id, nombre) VALUES (?, ?)"
            
            cursor.executemany(sql_query, materias_data)
            conn.commit()
            
            # Informamos cuántas filas fueron realmente añadidas
            changes = conn.total_changes
            print(f" -> Carga finalizada. Se añadieron o modificaron {changes} registros.")

    except sqlite3.Error as e:
        print(f"  ❗ ERROR: Falla en la operación de base de datos. Causa: {e}")


def main():
    """Orquesta el proceso ETL completo para las materias."""
    print("--- [MATERIAS ETL] Iniciando proceso ---")
    xml_content = fetch_materias_xml()
    if xml_content:
        materias = transform_materias(xml_content)
        load_materias_to_db(materias)
    print("--- Proceso ETL de Materias Finalizado ---")

if __name__ == '__main__':
    main()