# src/etl/etl_bills.py
# -*- coding: utf-8 -*-

"""
Módulo ETL para Proyectos de Ley (Bills)

Este script implementa el proceso de Extracción, Transformación y Carga para poblar
las tablas `bills` y `bill_authors` de la base de datos.

Fuentes de Datos Primarias:
1.  API de la Cámara de Diputadas y Diputados de Chile:
    - Endpoints: `retornarMocionesXAnno`, `retornarMensajesXAnno`, `retornarProyectoLey`.
    - Origen: Se utiliza para obtener el listado de proyectos de ley por año y los
      detalles específicos de cada uno, como título, fecha, autores, estado, etc.

2.  Base de Datos Local (parlamento.db):
    - Origen: Se consulta la tabla `dim_parlamentario` para obtener el `mp_uid`
      a partir del `diputadoid` de los autores, asegurando la integridad referencial.
"""
import sqlite3
import requests
import xml.etree.ElementTree as ET
import os
from datetime import datetime
import time

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYECTO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}

# --- ================================================= ---
# ---         PARÁMETROS DE EJECUCIÓN DEL ETL           ---
# --- ================================================= ---
# Cambia a False para ejecutar en modo producción con los parámetros completos.
TEST_MODE = True 

# --- Parámetros para MODO PRUEBA (rá pido y con datos limitados) ---
if TEST_MODE:
    START_YEAR = 2024
    FILTER_MONTH = 7 # Procesará solo proyectos de Julio.
    PROCESS_LIMIT = 15 # Se detendrá después de procesar 15 proyectos que coincidan.

# --- Parámetros para MODO PRODUCCIÓN (completo) ---
else:
    START_YEAR = 2018 # Año de inicio para la extracción completa.
    FILTER_MONTH = None # None significa que procesará todos los meses.
    PROCESS_LIMIT = None # None significa sin límite.
# --- ================================================= ---


# --- 2. FASE DE EXTRACCIÓN (Extract) ---

def fetch_projects_by_year(year):
    """
    Obtiene los números de boletín de mociones y mensajes para un año específico
    desde la API de la Cámara.
    """
    projects = []
    urls = {
        "mociones": f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarMocionesXAnno?prmAnno={year}",
        "mensajes": f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarMensajesXAnno?prmAnno={year}"
    }

    for project_type, url in urls.items():
        print(f"🏛️  [BILLS ETL] Obteniendo {project_type} para el año {year}...")
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            
            for proj in root.findall('v1:ProyectoLey', NS):
                boletin = proj.findtext('v1:NumeroBoletin', namespaces=NS)
                if boletin:
                    projects.append(boletin)
            
        except requests.exceptions.RequestException as e:
            print(f"❌  [BILLS ETL] Error de red para {project_type} del año {year}: {e}")
        except ET.ParseError as e:
            print(f"❌  [BILLS ETL] Error de XML para {project_type} del año {year}: {e}")
            
    return list(set(projects))

def fetch_bill_details(bill_id):
    """
    Obtiene los detalles completos de un proyecto de ley.
    """
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarProyectoLey?prmNumeroBoletin={bill_id}"
    print(f"  -> Obteniendo detalles para el boletín: {bill_id}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        details = {}
        details["bill_id"] = bill_id
        fecha_ingreso_str = root.findtext('.//v1:FechaIngreso', namespaces=NS)
        details["fecha_ingreso"] = fecha_ingreso_str.split('T')[0] if fecha_ingreso_str else None
        details["titulo"] = root.findtext('.//v1:Nombre', namespaces=NS)
        resumen = root.findtext('.//v1:Resumen', namespaces=NS)
        details["resumen"] = resumen if resumen and resumen.strip() else details["titulo"]
        details["etapa"] = root.findtext('.//v1:Etapa', namespaces=NS)
        details["iniciativa"] = root.findtext('.//v1:TipoIniciativa/v1:Nombre', namespaces=NS)
        details["origen"] = root.findtext('.//v1:CamaraOrigen/v1:Nombre', namespaces=NS)
        urgencia_node = root.find('.//v1:UrgenciaActual', NS)
        details["urgencia"] = urgencia_node.text if urgencia_node is not None else "Sin urgencia"
        details["resultado_final"] = root.findtext('.//v1:Estado', namespaces=NS)
        ley_numero_node = root.find('.//v1:Ley/v1:Numero', NS)
        details["ley_numero"] = ley_numero_node.text if ley_numero_node is not None else None
        ley_fecha_str = root.findtext('.//v1:Ley/v1:FechaPublicacion', namespaces=NS)
        details["ley_fecha_publicacion"] = ley_fecha_str.split('T')[0] if ley_fecha_str else None
        
        autores_ids = []
        for autor_node in root.findall('.//v1:Autores/v1:ParlamentarioAutor', NS):
            diputado_id_node = autor_node.find('.//v1:Diputado/v1:Id', NS)
            if diputado_id_node is not None and diputado_id_node.text:
                autores_ids.append(diputado_id_node.text)
        details["autores_ids"] = autores_ids

        return details

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error de red para el boletín {bill_id}: {e}")
    except ET.ParseError as e:
        print(f"  ❌ Error de XML para el boletín {bill_id}: {e}")
    
    return None

# --- 3. FASE DE CARGA (Load) ---

def load_bill_to_db(bill_details, conn):
    """
    Carga los detalles de un proyecto de ley y sus autores en la base de datos.
    """
    if not bill_details:
        return

    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO bills (
                bill_id, titulo, resumen, fecha_ingreso, etapa, iniciativa,
                origen, urgencia, resultado_final, ley_numero, ley_fecha_publicacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bill_details['bill_id'], bill_details['titulo'], bill_details['resumen'],
            bill_details['fecha_ingreso'], bill_details['etapa'], bill_details['iniciativa'],
            bill_details['origen'], bill_details['urgencia'], bill_details['resultado_final'],
            bill_details['ley_numero'], bill_details['ley_fecha_publicacion']
        ))
    except sqlite3.Error as e:
        print(f"    ❌ Error al insertar en `bills` para {bill_details['bill_id']}: {e}")
        return

    if not bill_details['autores_ids']:
        print(f"    -> Proyecto {bill_details['bill_id']} insertado (Mensaje sin autores parlamentarios).")
        conn.commit()
        return

    autores_cargados = 0
    for diputado_id in bill_details['autores_ids']:
        try:
            cursor.execute("SELECT mp_uid FROM dim_parlamentario WHERE diputadoid = ?", (diputado_id,))
            result = cursor.fetchone()
            if result:
                mp_uid = result[0]
                cursor.execute("INSERT OR IGNORE INTO bill_authors (bill_id, mp_uid) VALUES (?, ?)", (bill_details['bill_id'], mp_uid))
                autores_cargados += 1
            else:
                print(f"    ⚠️  Advertencia: No se encontró `mp_uid` para el autor con `diputadoid` {diputado_id}.")
        except sqlite3.Error as e:
            print(f"    ❌ Error al insertar autor {diputado_id} en `bill_authors`: {e}")

    print(f"    -> Proyecto {bill_details['bill_id']} insertado y {autores_cargados} autores vinculados.")
    conn.commit()

# --- 4. ORQUESTACIÓN ---

def main():
    if TEST_MODE:
        print("--- [BILLS ETL] Ejecutando en MODO PRUEBA ---")
        print(f"Año: {START_YEAR}, Mes: {FILTER_MONTH}, Límite: {PROCESS_LIMIT}")
    else:
        print("--- [BILLS ETL] Iniciando Proceso ETL Completo ---")

    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            
            end_year = datetime.now().year
            all_bill_ids = []
            
            # Determinar el rango de años a procesar
            years_to_process = [START_YEAR] if TEST_MODE else range(START_YEAR, end_year + 1)

            for year in years_to_process:
                bill_ids_year = fetch_projects_by_year(year)
                all_bill_ids.extend(bill_ids_year)
                if not TEST_MODE:
                    print(f"✅  Año {year} procesado. {len(bill_ids_year)} proyectos encontrados.")
                    time.sleep(1)
            
            unique_bill_ids = sorted(list(set(all_bill_ids)), reverse=True)
            print(f"\n📑 Se encontraron un total de {len(unique_bill_ids)} proyectos de ley únicos para procesar.\n")

            processed_count = 0
            for bill_id in unique_bill_ids:
                if PROCESS_LIMIT is not None and processed_count >= PROCESS_LIMIT:
                    print(f"  -> Límite de procesamiento de {PROCESS_LIMIT} proyectos alcanzado.")
                    break
                
                details = fetch_bill_details(bill_id)
                time.sleep(0.2)
                
                if details and details['fecha_ingreso']:
                    try:
                        ingreso_date = datetime.strptime(details['fecha_ingreso'], '%Y-%m-%d')
                        # Si FILTER_MONTH está definido, solo procesar los proyectos de ese mes
                        if FILTER_MONTH is None or ingreso_date.month == FILTER_MONTH:
                            load_bill_to_db(details, conn)
                            processed_count += 1
                    except (ValueError, TypeError):
                        print(f"  -> Omitiendo proyecto {bill_id} por fecha inválida.")
                        continue
            
            print(f"\nTotal de proyectos cargados en la base de datos: {processed_count}")

    except Exception as e:
        print(f"❌  Error Crítico durante la operación ETL: {e}")

    print("\n--- Proceso ETL de Proyectos de Ley Finalizado ---")

if __name__ == "__main__":
    main()