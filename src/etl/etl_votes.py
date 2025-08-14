# src/etl/etl_votes.py
# -*- coding: utf-8 -*-

"""
ETL para poblar la tabla `votes`.
Este script lee los proyectos de ley desde la base de datos local, consulta la API
de la Cámara para encontrar las votaciones asociadas a cada uno, y registra cada
voto individual en la tabla `votes`.
"""

import sqlite3
import requests
import xml.etree.ElementTree as ET
import os
import time

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYECTO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'} # Namespace para el XML

# --- 2. FUNCIONES DE EXTRACCIÓN (Extract) ---

def get_bill_ids_from_db(conn):
    """
    Obtiene todos los `bill_id` (boletines) de la tabla local `bills`.
    """
    print("📋 [VOTES ETL] Obteniendo lista de proyectos de ley desde la base de datos local...")
    cursor = conn.cursor()
    cursor.execute("SELECT bill_id FROM bills ORDER BY fecha_ingreso DESC;")
    bill_ids = [row[0] for row in cursor.fetchall()]
    print(f"✔️  [VOTES ETL] Se encontraron {len(bill_ids)} proyectos para procesar.")
    return bill_ids

def fetch_vote_ids_for_bill(bill_id):
    """
    Para un `bill_id` dado, consulta la API para obtener los IDs de todas sus votaciones.
    """
    # Usamos retornarVotacionesXProyectoLey por claridad semántica, aunque retornarProyectoLey también funcione.
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarVotacionesXProyectoLey?prmNumeroBoletin={bill_id}"
    print(f"  -> Buscando votaciones para el boletín: {bill_id}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        # --- INICIO DE LA CORRECCIÓN ---
        # El script ahora busca la etiqueta correcta <VotacionProyectoLey> que tú encontraste.
        votaciones_nodes = root.findall('.//v1:Votaciones/v1:VotacionProyectoLey', NS)
        if not votaciones_nodes:
            print("    - No se encontraron votaciones para este proyecto.")
            return []
        # --- FIN DE LA CORRECCIÓN ---

        vote_ids = [v.findtext('v1:Id', namespaces=NS) for v in votaciones_nodes]
        print(f"    - Se encontraron {len(vote_ids)} votaciones.")
        return vote_ids

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error de red para el boletín {bill_id}: {e}")
    except ET.ParseError as e:
        print(f"  ❌ Error de XML para el boletín {bill_id}: {e}")
    return []

# --- 3. FASE DE TRANSFORMACIÓN Y CARGA (Transform & Load) ---

def setup_database(conn):
    """
    Asegura que la tabla `votes` exista en la base de datos.
    """
    print("🛠️  [DB Setup] Verificando que la tabla `votes` exista...")
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS votes (
            vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mp_uid INTEGER NOT NULL,
            bill_id TEXT NOT NULL,
            voto TEXT NOT NULL, -- 'Afirmativo', 'En Contra', 'Abstención', 'Pareo', 'Dispensado'
            fecha DATE NOT NULL,
            FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE,
            FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_votes_mp_bill ON votes(mp_uid, bill_id);
    """)
    conn.commit()
    print("✅  [DB Setup] Esquema para `votes` verificado.")

def fetch_and_load_vote_details(vote_id, bill_id, conn):
    """
    Obtiene los detalles de una votación y carga cada voto individual en la BD.
    """
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarVotacionDetalle?prmVotacionId={vote_id}"
    print(f"    -> Procesando detalles de la votación ID: {vote_id}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        fecha_str = root.findtext('v1:Fecha', namespaces=NS)
        fecha_votacion = fecha_str.split('T')[0] if fecha_str else None

        if not fecha_votacion:
            print(f"      ⚠️  Advertencia: No se encontró fecha para la votación {vote_id}.")
            return

        cursor = conn.cursor()
        votos_a_insertar = []

        for voto_node in root.findall('.//v1:Votos/v1:Voto', NS):
            diputado_id = voto_node.findtext('.//v1:Diputado/v1:Id', namespaces=NS)
            opcion_voto_node = voto_node.find('v1:OpcionVoto', NS)
            voto_texto = opcion_voto_node.text.strip() if opcion_voto_node is not None and opcion_voto_node.text else "N/A"

            cursor.execute("SELECT mp_uid FROM dim_parlamentario WHERE diputadoid = ?", (diputado_id,))
            result = cursor.fetchone()
            
            if result:
                mp_uid = result[0]
                votos_a_insertar.append((mp_uid, bill_id, voto_texto, fecha_votacion))
            else:
                print(f"      ⚠️  Advertencia: No se encontró `mp_uid` para el `diputadoid` {diputado_id} en la votación {vote_id}.")

        if votos_a_insertar:
            cursor.executemany("""
                INSERT OR IGNORE INTO votes (mp_uid, bill_id, voto, fecha)
                VALUES (?, ?, ?, ?)
            """, votos_a_insertar)
            conn.commit()
            print(f"      -> Se insertaron {len(votos_a_insertar)} votos en la BD para la votación {vote_id}.")

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
    print("--- Iniciando Proceso ETL: Votaciones de Proyectos de Ley ---")
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            setup_database(conn)
            
            bill_ids = get_bill_ids_from_db(conn)
            
            for bill_id in bill_ids:
                vote_ids = fetch_vote_ids_for_bill(bill_id)
                if vote_ids:
                    for vote_id in vote_ids:
                        fetch_and_load_vote_details(vote_id, bill_id, conn)
                        time.sleep(0.2)
                print("-" * 20)

    except Exception as e:
        print(f"❌  Error Crítico durante la operación ETL de Votaciones: {e}")

    print("\n--- Proceso ETL de Votaciones Finalizado ---")

if __name__ == "__main__":
    main()