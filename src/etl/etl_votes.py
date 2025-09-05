# src/etl/etl_votes.py
# -*- coding: utf-8 -*-

"""
Módulo ETL para Votaciones Parlamentarias v2.1

- Periodo temporal: por defecto procesa todas las votaciones de los `bills` en BD.
  Opcionalmente puede filtrarse por año de `fecha_ingreso` del proyecto (`--year`).
- Intensidad de red: alta (1 request por lista de votaciones por bill + 1 por detalle de votación),
  mitigada por caché local por votación.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import time
import xml.etree.ElementTree as ET

import requests

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYETO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
# Directorio para guardar XMLs de votaciones (caché)
XML_VOTES_PATH = os.path.join(PROJECT_ROOT, 'data', 'xml')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}


# --- 2. FASE DE EXTRACCIÓN Y TRANSFORMACIÓN ---

def get_bill_ids_from_db(conn: sqlite3.Connection, year: int | None = None):
    """
    Obtiene todos los `bill_id` de la tabla local `bills`. Si `year` se indica,
    filtra por `fecha_ingreso` del año dado.
    """
    print("[VOTES ETL] Obteniendo lista de proyectos de ley desde la base de datos local...")
    cursor = conn.cursor()
    if year is not None:
        query = "SELECT bill_id FROM bills WHERE substr(fecha_ingreso,1,4)=? ORDER BY fecha_ingreso DESC"
        cursor.execute(query, (str(year),))
    else:
        query = "SELECT bill_id FROM bills ORDER BY fecha_ingreso DESC"
        cursor.execute(query)
    bill_ids = [row[0] for row in cursor.fetchall()]

    print(f"[VOTES ETL] Se encontraron {len(bill_ids)} proyectos para procesar.")
    return bill_ids


def fetch_vote_ids_for_bill(bill_id: str):
    """
    Para un `bill_id` dado, consulta la API para obtener los IDs de todas sus votaciones.
    (Nota: Esta parte no se cachea porque la lista de votaciones de un proyecto en curso podría cambiar).
    """
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarVotacionesXProyectoLey?prmNumeroBoletin={bill_id}"
    print(f"  -> Buscando votaciones para el boletín: {bill_id}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        votaciones_nodes = root.findall('.//v1:Votaciones/v1:VotacionProyectoLey', NS)
        if not votaciones_nodes:
            print("     - No se encontraron votaciones para este proyecto.")
            return []

        vote_ids = [v.findtext('v1:Id', namespaces=NS) for v in votaciones_nodes]
        print(f"     - Se encontraron {len(vote_ids)} votaciones.")
        return vote_ids

    except requests.exceptions.RequestException as e:
        print(f"  ! Error de red para el boletín {bill_id}: {e}")
    except ET.ParseError as e:
        print(f"  ! Error de XML para el boletín {bill_id}: {e}")
    return []


def parse_bill_id_from_description(description: str | None):
    """
    Extrae un número de boletín (ej: 12345-67) del texto de descripción de una votación.
    """
    if not description:
        return None
    match = re.search(r'(\d{1,5}-\d{2})', description)
    return match.group(1) if match else None


def normalize_vote_option(vote_text: str):
    """
    Normaliza las diferentes opciones de voto al formato definido en el esquema.
    """
    vote_map = {
        'Afirmativo': 'A Favor',
        'En contra': 'En Contra',
        'Abstención': 'Abstención',
        'Abstención': 'Abstención',  # compatibilidad por posibles mojibake
        'Pareo': 'Pareo',
        'Dispensado': 'Pareo'  # Se asume que 'Dispensado' es un tipo de pareo
    }
    return vote_map.get(vote_text, vote_text)


# --- 3. FASE DE CARGA (Load) CON CACHÉ ---

def process_and_load_vote_details(vote_id: str, conn: sqlite3.Connection):
    """
    Obtiene los detalles de una votación desde el caché o la API, los carga en `sesiones_votacion` y
    luego carga cada voto individual en `votos_parlamentario`.
    """
    xml_file_path = os.path.join(XML_VOTES_PATH, f"{vote_id}.xml")
    xml_content = None

    # 1. Intentar leer desde el archivo local (caché)
    if os.path.exists(xml_file_path):
        print(f"     -> Leyendo votación {vote_id} desde caché local...")
        with open(xml_file_path, 'rb') as f:
            xml_content = f.read()
    else:
        # 2. Si no existe, obtener desde la API y guardar en caché
        url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarVotacionDetalle?prmVotacionId={vote_id}"
        print(f"     -> Obteniendo votación {vote_id} desde la API...")
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            xml_content = response.content
            # Guardar el contenido en el directorio de caché
            with open(xml_file_path, 'wb') as f:
                f.write(xml_content)
            print(f"         -> XML de votación {vote_id} guardado en caché.")
            time.sleep(0.2)  # Pausa corta al usar la API
        except requests.exceptions.RequestException as e:
            print(f"     ! Error de red para la votación {vote_id}: {e}")
            return  # Salir si no se pudo obtener el XML

    # 3. Procesar el XML y cargar a la base de datos
    if not xml_content:
        return

    try:
        root = ET.fromstring(xml_content)

        # --- 3.1 Extraer datos para `sesiones_votacion` ---
        descripcion = root.findtext('v1:Descripcion', namespaces=NS)
        bill_id = parse_bill_id_from_description(descripcion)
        if not bill_id:
            print(f"         (!) Advertencia: No se pudo extraer un bill_id para la votación {vote_id}. Se omitirá.")
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
        cursor.execute(
            """
            INSERT OR REPLACE INTO sesiones_votacion (
                sesion_votacion_id, bill_id, fecha, tema, resultado_general, quorum_aplicado,
                a_favor_total, en_contra_total, abstencion_total, pareo_total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(sesion_data.values()),
        )

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
                print(
                    f"         (!) Advertencia: No se encontró `mp_uid` para el `diputadoid` {diputado_id}."
                )

        if votos_a_insertar:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO votos_parlamentario (sesion_votacion_id, mp_uid, voto)
                VALUES (?, ?, ?)
                """,
                votos_a_insertar,
            )

        conn.commit()
        print(f"         -> Votación {vote_id} y {len(votos_a_insertar)} votos individuales cargados en BD.")

    except ET.ParseError as e:
        print(f"     ! Error de XML para la votación {vote_id}: {e}")
    except sqlite3.Error as e:
        print(f"     ! Error de base de datos para la votación {vote_id}: {e}")


# --- 4. ORQUESTACIÓN ---

def main(year: int | None = None):
    """
    Orquesta el proceso ETL de votaciones.

    - year: si se especifica, limita a bills con `fecha_ingreso` en ese año.
    """
    title = (
        f"--- Iniciando Proceso ETL: Votaciones de Proyectos de Ley (año={year}) ---"
        if year is not None
        else "--- Iniciando Proceso ETL: Votaciones de Proyectos de Ley ---"
    )
    print(title)

    try:
        # Asegurarse de que el directorio para los XML de votaciones (caché) exista
        os.makedirs(XML_VOTES_PATH, exist_ok=True)

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")

            bill_ids = get_bill_ids_from_db(conn, year)

            for bill_id in bill_ids:
                vote_ids = fetch_vote_ids_for_bill(bill_id)
                if vote_ids:
                    for vote_id in vote_ids:
                        # La lógica de caché está integrada en esta función
                        process_and_load_vote_details(vote_id, conn)
                print("-" * 40)

    except Exception as e:
        print(f"! Error Crítico durante la operación ETL de Votaciones: {e}")

    print("\n--- Proceso ETL de Votaciones Finalizado ---")


def _parse_args():
    parser = argparse.ArgumentParser(description="ETL de votaciones; opcionalmente filtra por año del bill")
    parser.add_argument("--year", type=int, help="Año (YYYY) para limitar los bills por fecha_ingreso")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(year=getattr(args, "year", None))

