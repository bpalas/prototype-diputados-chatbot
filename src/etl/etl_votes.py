# src/etl/etl_votes.py
# -*- coding: utf-8 -*-

"""
Módulo ETL para Votaciones Parlamentarias

Este script implementa el proceso de Extracción, Transformación y Carga para poblar
las tablas `sesiones_votacion` y `votos_parlamentario` de la base de datos.

Fuentes de Datos Primarias:
1.  API de la Cámara de Diputadas y Diputados de Chile:
    - Endpoints: `retornarVotacionesXProyectoLey`, `retornarVotacionDetalle`.
    - Origen: Se utiliza para obtener las votaciones asociadas a un proyecto de ley
      y el detalle de cada voto individual por parlamentario.

2.  Base de Datos Local (parlamento.db):
    - Origen: Se consulta la tabla `bills` para obtener los proyectos a procesar
      y la tabla `dim_parlamentario` para mapear los `diputadoid` a `mp_uid`.
"""

import sqlite3
import requests
import xml.etree.ElementTree as ET
import os
import time
import re

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYECTO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}

# --- ================================================= ---
# --- CONFIGURACIÓN DE PRUEBA (AJUSTA ESTOS VALORES) ---
# --- ================================================= ---
TEST_MODE = True      # Poner en False para ejecutar el ETL completo
TEST_BILL_LIMIT = 5   # Limita el número de proyectos de ley a procesar
# --- ================================================= ---

# --- 2. FASE DE EXTRACCIÓN Y TRANSFORMACIÓN ---

def get_bill_ids_from_db(conn):
    """
    Obtiene los `bill_id` de la tabla local `bills`. En modo de prueba, aplica un límite.
    """
    print("📋 [VOTES ETL] Obteniendo lista de proyectos de ley desde la base de datos local...")
    cursor = conn.cursor()
    query = "SELECT bill_id FROM bills ORDER BY fecha_ingreso DESC"
    if TEST_MODE:
        query += f" LIMIT {TEST_BILL_LIMIT}"
    
    cursor.execute(query)
    bill_ids = [row[0] for row in cursor.fetchall()]
    
    if TEST_MODE:
        print(f"✔️  [VOTES ETL] MODO PRUEBA: Se procesarán {len(bill_ids)} proyectos.")
    else:
        print(f"✔️  [VOTES ETL] Se encontraron {len(bill_ids)} proyectos para procesar.")
    return bill_ids

def fetch_vote_ids_for_bill(bill_id):
    """
    Para un `bill_id` dado, consulta la API para obtener los IDs de todas sus votaciones.
    """
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarVotacionesXProyectoLey?prmNumeroBoletin={bill_id}"
    print(f"  -> Buscando votaciones para el boletín: {bill_id}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        votaciones_nodes = root.findall('.//v1:Votaciones/v1:VotacionProyectoLey', NS)
        if not votaciones_nodes:
            print("    - No se encontraron votaciones para este proyecto.")
            return []

        vote_ids = [v.findtext('v1:Id', namespaces=NS) for v in votaciones_nodes]
        print(f"    - Se encontraron {len(vote_ids)} votaciones.")
        return vote_ids

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error de red para el boletín {bill_id}: {e}")
    except ET.ParseError as e:
        print(f"  ❌ Error de XML para el boletín {bill_id}: {e}")
    return []

def parse_bill_id_from_description(description):
    """
    Extrae un número de boletín (ej: 12345-67) del texto de descripción de una votación.
    """
    if not description:
        return None
    match = re.search(r'(\d{1,5}-\d{2})', description)
    return match.group(1) if match else None

def normalize_vote_option(vote_text):
    """
    Normaliza las diferentes opciones de voto al formato definido en el esquema.
    """
    vote_map = {
        'Afirmativo': 'A Favor',
        'En contra': 'En Contra',
        'Abstención': 'Abstención',
        'Pareo': 'Pareo',
        'Dispensado': 'Pareo' # Se asume que 'Dispensado' es un tipo de pareo
    }
    return vote_map.get(vote_text, vote_text)


# --- 3. FASE DE CARGA (Load) ---

def fetch_and_load_vote_details(vote_id, conn):
    """
    Obtiene los detalles de una votación, los carga en `sesiones_votacion` y
    luego carga cada voto individual en `votos_parlamentario`.
    """
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarVotacionDetalle?prmVotacionId={vote_id}"
    print(f"    -> Procesando detalles de la votación ID: {vote_id}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        # --- 3.1 Extraer datos para `sesiones_votacion` ---
        descripcion = root.findtext('v1:Descripcion', namespaces=NS)
        # Intenta parsear el bill_id de la descripción. Crucial para la relación.
        bill_id = parse_bill_id_from_description(descripcion)
        if not bill_id:
            print(f"      ⚠️  Advertencia: No se pudo extraer un bill_id para la votación {vote_id}. Se omitirá.")
            return

        fecha_str = root.findtext('v1:Fecha', namespaces=NS)
        fecha_votacion = fecha_str.split('T')[0] if fecha_str else None

        sesion_data = {
            'sesion_votacion_id': int(vote_id),
            'bill_id': bill_id,
            'fecha': fecha_votacion,
            'tema': descripcion,
            'resultado_general': root.findtext('.//v1:Resultado', namespaces=NS),
            'quorum_aplicado': root.findtext('.//v1:Quorum', namespaces=NS),
            'a_favor_total': root.findtext('.//v1:TotalSi', namespaces=NS),
            'en_contra_total': root.findtext('.//v1:TotalNo', namespaces=NS),
            'abstencion_total': root.findtext('.//v1:TotalAbstencion', namespaces=NS),
            'pareo_total': root.findtext('.//v1:TotalDispensado', namespaces=NS)
        }

        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO sesiones_votacion (
                sesion_votacion_id, bill_id, fecha, tema, resultado_general, quorum_aplicado,
                a_favor_total, en_contra_total, abstencion_total, pareo_total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(sesion_data.values()))

        # --- 3.2 Extraer y cargar datos para `votos_parlamentario` ---
        votos_a_insertar = []
        for voto_node in root.findall('.//v1:Votos/v1:Voto', NS):
            diputado_id = voto_node.findtext('.//v1:Diputado/v1:Id', namespaces=NS)
            opcion_voto_raw = voto_node.findtext('v1:OpcionVoto', namespaces=NS, default='').strip()
            
            cursor.execute("SELECT mp_uid FROM dim_parlamentario WHERE diputadoid = ?", (diputado_id,))
            result = cursor.fetchone()
            
            if result:
                mp_uid = result[0]
                voto_normalizado = normalize_vote_option(opcion_voto_raw)
                votos_a_insertar.append((sesion_data['sesion_votacion_id'], mp_uid, voto_normalizado))
            else:
                print(f"      ⚠️  Advertencia: No se encontró `mp_uid` para el `diputadoid` {diputado_id}.")

        if votos_a_insertar:
            cursor.executemany("""
                INSERT OR IGNORE INTO votos_parlamentario (sesion_votacion_id, mp_uid, voto)
                VALUES (?, ?, ?)
            """, votos_a_insertar)
        
        conn.commit()
        print(f"      -> Votación {vote_id} y {len(votos_a_insertar)} votos individuales cargados en BD.")

    except requests.exceptions.RequestException as e:
        print(f"    ❌ Error de red para la votación {vote_id}: {e}")
    except ET.ParseError as e:
        print(f"    ❌ Error de XML para la votación {vote_id}: {e}")
    except sqlite3.Error as e:
        print(f"    ❌ Error de base de datos para la votación {vote_id}: {e}")


# --- 4. ORQUESTACIÓN ---

def main():
    """
    Función principal que orquesta el proceso ETL para las votaciones.
    """
    if TEST_MODE:
        print("--- Running VOTES ETL in TEST MODE ---")
    else:
        print("--- Iniciando Proceso ETL: Votaciones de Proyectos de Ley ---")
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            
            bill_ids = get_bill_ids_from_db(conn)
            
            for bill_id in bill_ids:
                vote_ids = fetch_vote_ids_for_bill(bill_id)
                if vote_ids:
                    for vote_id in vote_ids:
                        fetch_and_load_vote_details(vote_id, conn)
                        time.sleep(0.25) # Pausa cortés para no sobrecargar la API
                print("-" * 40)

    except Exception as e:
        print(f"❌  Error Crítico durante la operación ETL de Votaciones: {e}")

    print("\n--- Proceso ETL de Votaciones Finalizado ---")

if __name__ == "__main__":
    main()