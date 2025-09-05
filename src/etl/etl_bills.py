# src/etl/etl_bills.py
# -*- coding: utf-8 -*-

"""
ETL para Proyectos de Ley (Bills) — modo por año.

- Periodo temporal: ejecuta por año calendario (YYYY).
- Intensidad de red: media/alta (1 lista de mociones + 1 lista de mensajes por año,
  y 1 detalle por boletín). El caché local de XML reduce re-ejecuciones.

Permite invocación por CLI o desde un orquestador, especificando uno o varios años.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from typing import Iterable, List

import requests

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYECTO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
XML_BILLS_PATH = os.path.join(PROJECT_ROOT, 'data', 'xml', 'bills')  # Directorio para guardar XMLs
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}

# --- Parámetros por defecto (compatibilidad retro) ---
START_YEAR = 2024  # Se usa si no se pasan argumentos por CLI ni desde el orquestador


def fetch_projects_by_year(year: int) -> List[str]:
    """
    Obtiene los números de boletín de mociones y mensajes para un año específico
    desde la API de la Cámara.
    """
    projects: List[str] = []
    urls = {
        "mociones": f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarMocionesXAnno?prmAnno={year}",
        "mensajes": f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarMensajesXAnno?prmAnno={year}"
    }

    for project_type, url in urls.items():
        print(f"⚙️  [BILLS ETL] Obteniendo {project_type} para el año {year}...")
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            root = ET.fromstring(response.content)

            for proj in root.findall('v1:ProyectoLey', NS):
                boletin = proj.findtext('v1:NumeroBoletin', namespaces=NS)
                if boletin:
                    projects.append(boletin)

        except requests.exceptions.RequestException as e:
            print(f"⚠️  [BILLS ETL] Error de red para {project_type} del año {year}: {e}")
        except ET.ParseError as e:
            print(f"⚠️  [BILLS ETL] Error de XML para {project_type} del año {year}: {e}")

    return list(set(projects))


def fetch_bill_details(bill_id: str):
    """
    Obtiene los detalles de un proyecto de ley.
    Primero busca un XML local. Si no lo encuentra, consulta la API y guarda el resultado.
    """
    xml_file_path = os.path.join(XML_BILLS_PATH, f"{bill_id}.xml")
    xml_content = None

    # 1. Intentar leer desde el archivo local (caché)
    if os.path.exists(xml_file_path):
        print(f"  -> Leyendo detalles del boletín {bill_id} desde caché local...")
        with open(xml_file_path, 'rb') as f:
            xml_content = f.read()
    else:
        # 2. Si no existe, obtener desde la API
        print(f"  -> Obteniendo detalles para el boletín {bill_id} desde la API...")
        url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarProyectoLey?prmNumeroBoletin={bill_id}"
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            xml_content = response.content
            # Guardar el contenido en un archivo para la próxima vez
            with open(xml_file_path, 'wb') as f:
                f.write(xml_content)
            print(f"     -> XML guardado en caché: {xml_file_path}")
            time.sleep(0.2)  # Pausa cortas al usar la API
        except requests.exceptions.RequestException as e:
            print(f"  ❗ Error de red para el boletín {bill_id}: {e}")
            return None

    # 3. Parsear el contenido XML (ya sea de la API o del archivo)
    if not xml_content:
        return None

    try:
        root = ET.fromstring(xml_content)
        details = {}
        details["bill_id"] = bill_id

        # --- ⭐️ LÓGICA DE EXTRACCIÓN CORREGIDA ---
        # Usamos findtext con './/' para buscar en todo el árbol XML.
        # Esto es más robusto y encuentra el dato sin importar su nivel de anidación.

        fecha_ingreso_str = root.findtext('.//v1:FechaIngreso', namespaces=NS)
        details["fecha_ingreso"] = fecha_ingreso_str.split('T')[0] if fecha_ingreso_str else None

        details["titulo"] = root.findtext('.//v1:Nombre', namespaces=NS)

        resumen = root.findtext('.//v1:Resumen', namespaces=NS)
        details["resumen"] = resumen if resumen and resumen.strip() else details["titulo"]

        details["etapa"] = root.findtext('.//v1:Etapa', namespaces=NS)

        # Corrección principal: Usar findtext para más seguridad
        details["iniciativa"] = root.findtext('.//v1:TipoIniciativa', namespaces=NS)
        details["origen"] = root.findtext('.//v1:CamaraOrigen', namespaces=NS)

        urgencia_node = root.find('.//v1:UrgenciaActual', NS)
        details["urgencia"] = urgencia_node.text if urgencia_node is not None else "Sin urgencia"

        details["resultado_final"] = root.findtext('.//v1:Estado', namespaces=NS)

        details["ley_numero"] = root.findtext('.//v1:Ley/v1:Numero', namespaces=NS)

        ley_fecha_str = root.findtext('.//v1:Ley/v1:FechaPublicacion', namespaces=NS)
        details["ley_fecha_publicacion"] = ley_fecha_str.split('T')[0] if ley_fecha_str else None

        autores_ids = []
        for autor_node in root.findall('.//v1:Autores/v1:ParlamentarioAutor', NS):
            diputado_id_node = autor_node.find('.//v1:Diputado/v1:Id', NS)
            if diputado_id_node is not None and diputado_id_node.text:
                autores_ids.append(diputado_id_node.text)
        details["autores_ids"] = autores_ids

        return details

    except ET.ParseError as e:
        print(f"  ❗ Error de XML para el boletín {bill_id}: {e}")
        return None


# --- FASE DE CARGA ---
def load_bill_to_db(bill_details: dict, conn: sqlite3.Connection):
    """
    Carga los detalles de un proyecto de ley y sus autores en la base de datos.
    """
    if not bill_details:
        return

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT OR REPLACE INTO bills (
                bill_id, titulo, resumen, fecha_ingreso, etapa, iniciativa,
                origen, urgencia, resultado_final, ley_numero, ley_fecha_publicacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                bill_details['bill_id'], bill_details['titulo'], bill_details['resumen'],
                bill_details['fecha_ingreso'], bill_details['etapa'], bill_details['iniciativa'],
                bill_details['origen'], bill_details['urgencia'], bill_details['resultado_final'],
                bill_details['ley_numero'], bill_details['ley_fecha_publicacion']
            ),
        )
    except sqlite3.Error as e:
        print(f"     ❗ Error al insertar en `bills` para {bill_details['bill_id']}: {e}")
        return

    if not bill_details['autores_ids']:
        print(f"     -> Proyecto {bill_details['bill_id']} insertado (Mensaje sin autores parlamentarios).")
        conn.commit()
        return

    autores_cargados = 0
    for diputado_id in bill_details['autores_ids']:
        try:
            cursor.execute("SELECT mp_uid FROM dim_parlamentario WHERE diputadoid = ?", (diputado_id,))
            result = cursor.fetchone()
            if result:
                mp_uid = result[0]
                cursor.execute(
                    "INSERT OR IGNORE INTO bill_authors (bill_id, mp_uid) VALUES (?, ?)",
                    (bill_details['bill_id'], mp_uid),
                )
                autores_cargados += 1
            else:
                print(f"     ⚠️  Advertencia: No se encontró `mp_uid` para el autor con `diputadoid` {diputado_id}.")
        except sqlite3.Error as e:
            print(f"     ❗ Error al insertar autor {diputado_id} en `bill_authors`: {e}")

    print(f"     -> Proyecto {bill_details['bill_id']} insertado y {autores_cargados} autores vinculados.")
    conn.commit()


# --- 4. ORQUESTACIÓN ---
def _iter_years(year: int | None, from_year: int | None, to_year: int | None) -> List[int]:
    if year is not None:
        return [int(year)]
    if from_year is None and to_year is None:
        return [int(START_YEAR)]
    if from_year is not None and to_year is None:
        return [int(from_year)]
    if from_year is None and to_year is not None:
        return [int(to_year)]
    a, b = int(from_year), int(to_year)
    step = 1 if a <= b else -1
    return list(range(a, b + step, step))


def main(year: int | None = None, from_year: int | None = None, to_year: int | None = None):
    """
    Ejecuta el ETL de proyectos de ley para uno o varios años.

    - year: ejecuta solo para ese año.
    - from_year/to_year: ejecuta el rango inclusivo.
    Si no se especifica, usa START_YEAR para compatibilidad.
    """
    years = _iter_years(year, from_year, to_year)
    print(f"--- [BILLS ETL] Iniciando proceso para años: {', '.join(map(str, years))} ---")

    try:
        os.makedirs(XML_BILLS_PATH, exist_ok=True)

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")

            total_processed = 0
            for y in years:
                bill_ids = fetch_projects_by_year(int(y))
                unique_bill_ids = sorted(list(set(bill_ids)), reverse=True)
                print(f"\n🧮 [{y}] {len(unique_bill_ids)} proyectos únicos para procesar.\n")

                processed_count = 0
                for bill_id in unique_bill_ids:
                    details = fetch_bill_details(bill_id)
                    if details:
                        load_bill_to_db(details, conn)
                        processed_count += 1
                total_processed += processed_count
                print(f"→ [{y}] Proyectos cargados: {processed_count}")

            print(f"\nTotal de proyectos cargados en la base de datos: {total_processed}")

    except Exception as e:
        print(f"❗  Error Crítico durante la operación ETL (bills): {e}")

    print("\n--- Proceso ETL de Proyectos de Ley Finalizado ---")


def _parse_args():
    parser = argparse.ArgumentParser(description="ETL de proyectos de ley por año")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--year", type=int, help="Año a procesar (YYYY)")
    group.add_argument("--from-year", type=int, help="Año inicial (inclusive)")
    parser.add_argument("--to-year", type=int, help="Año final (inclusive). Requiere --from-year")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(year=getattr(args, "year", None), from_year=getattr(args, "from_year", None), to_year=getattr(args, "to_year", None))

