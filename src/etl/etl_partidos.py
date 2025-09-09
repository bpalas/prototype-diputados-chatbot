# src/etl/etl_partidos.py
# -*- coding: utf-8 -*-
"""
Paso 0: Pobla la tabla de dimensión 'dim_partidos'.

Este script se conecta a las fuentes de datos de la BCN para realizar una
carga masiva de los partidos políticos. Asume que la base de datos y la tabla
'dim_partidos' ya han sido creadas con el esquema principal.
"""

import sqlite3
from pathlib import Path
from typing import Any, Optional, List, Tuple
from datetime import datetime

import requests

# --- 1. CONFIGURACIÓN Y RUTAS ---
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "database" / "parlamento.db"

# --- URLs de la API de BCN ---
PARTIES_LIST_URL = "https://datos.bcn.cl/recurso/cl/organismo/partido-politico/datos.json"

# --- Constantes para las claves del JSON (mejora la legibilidad) ---
RDF_MEMBER = "http://www.w3.org/2004/02/skos/core#member"
SKOS_PREF_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
BCN_ACRONYM = "http://datos.bcn.cl/ontologies/bcn-biographies#hasAcronym"
BCN_FOUNDATION_YEAR = "http://datos.bcn.cl/ontologies/bcn-biographies#hasFoundationYear"


# --- 2. FUNCIONES DE UTILIDAD ---

def _fetch_json(url: str) -> Optional[dict[str, Any]]:
    """Descarga y decodifica un JSON desde una URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
        }
        resp = requests.get(url, timeout=60, headers=headers)
        resp.raise_for_status()  # Lanza una excepción para errores HTTP (4xx o 5xx).
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Error descargando {url}: {e}")
        return None
    except requests.exceptions.JSONDecodeError as e:
        print(f"❌ Error decodificando JSON desde {url}: {e}")
        return None


# --- 3. LÓGICA DE CARGA DE DIMENSIONES ---

def populate_political_parties(conn: sqlite3.Connection):
    """Descarga la lista de partidos, obtiene sus detalles y los inserta en la DB."""
    print("📥 Iniciando carga de la dimensión 'Partidos Políticos'...")
    
    cur = conn.cursor()
    
    # 1. Obtener la lista de URIs de todos los partidos.
    initial_data = _fetch_json(PARTIES_LIST_URL)
    if not initial_data:
        print("❌ No se pudo obtener la lista de URIs de partidos. Proceso abortado.")
        return

    main_key = next(iter(initial_data))
    party_uris = [
        member['value'] 
        for member in initial_data.get(main_key, {}).get(RDF_MEMBER, [])
    ]

    if not party_uris:
        print("⚠️ No se encontraron URIs de partidos en la respuesta inicial.")
        return

    parties_to_insert: List[Tuple[str, Optional[str], str, Optional[str], str]] = []
    print(f"🔎 Se encontraron {len(party_uris)} partidos. Obteniendo detalles de cada uno...")

    # 2. Iterar sobre cada URI para obtener los detalles del partido.
    for uri in party_uris:
        party_data_url = f"{uri}/datos.json"
        party_details = _fetch_json(party_data_url)
        
        if not party_details or uri not in party_details:
            print(f"⚠️ No se pudieron obtener detalles para la URI: {uri}")
            continue

        details = party_details[uri]
        
        nombre_list = details.get(SKOS_PREF_LABEL, [])
        sigla_list = details.get(BCN_ACRONYM, [])
        foundation_year_list = details.get(BCN_FOUNDATION_YEAR, [])
        
        nombre = nombre_list[0].get("value") if nombre_list else None
        sigla = sigla_list[0].get("value") if sigla_list else None
        
        # Convierte el año a un formato de fecha 'YYYY-01-01' para compatibilidad con SQL.
        foundation_year = foundation_year_list[0].get("value") if foundation_year_list else None
        fecha_fundacion = f"{foundation_year}-01-01" if foundation_year else None
        
        # Fecha de actualización para el registro.
        ultima_actualizacion = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if nombre:
            parties_to_insert.append((nombre, sigla, uri, fecha_fundacion, ultima_actualizacion))

    if not parties_to_insert:
        print("⚠️ No se procesó ningún partido para insertar.")
        return

    # 3. Insertar todos los partidos en la base de datos de una sola vez.
    # Usamos INSERT OR IGNORE para evitar errores si un partido ya existe (por bcn_uri o nombre_partido).
    # Se actualiza la consulta para que coincida con más campos de tu esquema.
    try:
        cur.executemany(
            """
            INSERT OR IGNORE INTO dim_partidos (nombre_partido, sigla, bcn_uri, fecha_fundacion, ultima_actualizacion) 
            VALUES (?, ?, ?, ?, ?)
            """,
            parties_to_insert
        )
        conn.commit()
        print(f"✅ Carga de partidos finalizada. Se procesaron {len(parties_to_insert)} partidos. Se insertaron/ignoraron {cur.rowcount} registros.")
    except sqlite3.Error as e:
        print(f"❌ Error al insertar datos en la base de datos: {e}")
        print("   Asegúrate de que la tabla 'dim_partidos' exista y su esquema sea correcto.")


# --- 4. ORQUESTACIÓN ---
def main():
    """Función principal que orquesta la carga de todas las dimensiones."""
    print("--- Iniciando Proceso de Población de Dimensiones ---")
    
    if not DB_PATH.parent.exists():
        print(f"❌ El directorio de la base de datos no existe: {DB_PATH.parent}")
        return
        
    try:
        with sqlite3.connect(DB_PATH) as conn:
            populate_political_parties(conn)
            # Aquí podrías añadir llamadas a otras funciones para poblar más dimensiones.
            
    except sqlite3.Error as e:
        print(f"❌ Error de base de datos general: {e}")
        
    print("--- Proceso de Población de Dimensiones Finalizado ---")


if __name__ == "__main__":
    main()