# src/etl/etl_roster_ids.py
# -*- coding: utf-8 -*-
"""
Paso 1: ETL de Roster para poblar `dim_parlamentario` con IDs básicos.

Este script crea un registro para cada parlamentario encontrado en los JSON de 
cargos de la BCN, poblando únicamente los identificadores únicos y la URI 
para su posterior enriquecimiento.
"""

import os
import sqlite3
import requests

# --- 1. CONFIGURACIÓN Y RUTAS ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')

CARGOS_URLS = {
    "Diputado": "https://datos.bcn.cl/recurso/cl/cargo/1/datos.json",
    "Senador": "https://datos.bcn.cl/recurso/cl/cargo/2/datos.json",
    # Puedes añadir los cargos históricos si también los necesitas
    # "Senador Suplente": "https://datos.bcn.cl/recurso/cl/cargo/121/datos.json",
    # "Senador Subrogante": "https://datos.bcn.cl/recurso/cl/cargo/165/datos.json",
    # "Senador Vitalicio": "https://datos.bcn.cl/recurso/cl/cargo/169/datos.json",
}

KEY_USEDBY = "http://datos.bcn.cl/ontologies/bcn-biographies#usedBy"

# --- 2. FASE DE EXTRACCIÓN ---
def fetch_parliamentarian_ids():
    """Recupera los IDs y URIs de parlamentarios desde los JSON de cargos."""
    print("📥 [ROSTER] Iniciando extracción de IDs desde JSON de cargos BCN...")
    parlamentarios = {}  # Usamos un diccionario para manejar duplicados

    for cargo_nombre, url in CARGOS_URLS.items():
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            cargo_uri = list(data.keys())[0]
            cargo_data = data[cargo_uri]

            if KEY_USEDBY not in cargo_data:
                continue

            for item in cargo_data[KEY_USEDBY]:
                person_url_completa = item.get("value")
                if not person_url_completa:
                    continue
                
                parts = person_url_completa.split('/')
                if 'persona' in parts:
                    bcn_person_id = parts[parts.index('persona') + 1]
                    bcn_uri = f"http://datos.bcn.cl/recurso/persona/{bcn_person_id}"

                    # Guardamos el ID y la URI. Usamos el ID como clave para evitar duplicados.
                    if bcn_person_id not in parlamentarios:
                        parlamentarios[bcn_person_id] = {
                            "bcn_person_id": bcn_person_id,
                            "bcn_uri": bcn_uri,
                        }
        except requests.exceptions.RequestException as e:
            print(f"❌ [ROSTER] Error al obtener JSON de '{cargo_nombre}': {e}")
            continue
    
    print(f"✅ [ROSTER] Extracción finalizada. Se encontraron {len(parlamentarios)} parlamentarios únicos.")
    return list(parlamentarios.values())


# --- 3. FASE DE CARGA ---
def load_ids_to_db(data):
    """Inserta los IDs y URIs en `dim_parlamentario` si no existen."""
    if not data:
        print("⚠️ [ROSTER] No se encontraron datos para cargar.")
        return

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            
            records_to_insert = []
            for item in data:
                # ### CAMBIO AQUÍ ###
                # En lugar de un nombre temporal, usamos una cadena vacía ('')
                # para cumplir con la restricción NOT NULL de la columna.
                records_to_insert.append(
                    (item['bcn_person_id'], item['bcn_uri'], '') # Usamos ''
                )

            cur.executemany(
                """
                INSERT OR IGNORE INTO dim_parlamentario (bcn_person_id, bcn_uri, nombre_completo)
                VALUES (?, ?, ?);
                """,
                records_to_insert
            )
            
            conn.commit()
            print(f"✅ [ROSTER] Base de datos sincronizada. Se insertaron {cur.rowcount} nuevos registros.")

    except sqlite3.Error as e:
        print(f"❌ [ROSTER] Error de base de datos: {e}")


# --- 4. ORQUESTACIÓN ---
def main():
    """Función principal que orquesta el proceso ETL de Roster."""
    print("--- Iniciando Proceso ETL de Roster de Parlamentarios ---")
    parliamentarian_list = fetch_parliamentarian_ids()
    load_ids_to_db(parliamentarian_list)
    print("--- Proceso de Roster Finalizado ---")


if __name__ == "__main__":
    main()