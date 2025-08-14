# src/etl/etl_bills.py
# -*- coding: utf-8 -*-

"""
ETL para poblar las tablas `bills` (proyectos de ley) y `bill_authors` (autores de proyectos de ley).
Este script se conecta a la API de la Cámara para obtener todos los proyectos de ley (mociones y mensajes)
y sus respectivos autores, registrándolos en la base de datos.
"""

import sqlite3
import requests
import xml.etree.ElementTree as ET
import os
from datetime import datetime

# --- 1. CONFIGURACIÓN Y RUTAS DEL PROYECTO ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'} # Namespace para el XML

# --- 2. FUNCIONES DE EXTRACCIÓN (Extract) ---

def fetch_projects_by_year(year):
    """
    Obtiene mociones y mensajes para un año específico desde la API de la Cámara.
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
            print(f"✅  [BILLS ETL] Se encontraron {len(projects)} proyectos en total hasta ahora.")
            
        except requests.exceptions.RequestException as e:
            print(f"❌  [BILLS ETL] Error al conectar con la API para {project_type}: {e}")
        except ET.ParseError as e:
            print(f"❌  [BILLS ETL] Error al analizar el XML de {project_type}: {e}")
            
    return list(set(projects))

def fetch_bill_details(bill_id):
    """
    Obtiene los detalles de un proyecto de ley específico, incluyendo su resumen y autores.
    """
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarProyectoLey?prmNumeroBoletin={bill_id}"
    print(f"  -> Obteniendo detalles para el boletín: {bill_id}")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        # --- INICIO DE LA CORRECCIÓN ---
        # 1. Intentar obtener el <Resumen> detallado.
        resumen_detallado = root.findtext('.//v1:Resumen', namespaces=NS)
        # 2. Obtener el <Nombre> del proyecto, que siempre existe.
        nombre_proyecto = root.findtext('.//v1:Nombre', namespaces=NS)
        # 3. Usar el resumen detallado si existe; si no, usar el nombre como fallback.
        resumen_final = resumen_detallado if resumen_detallado and resumen_detallado.strip() else nombre_proyecto
        # --- FIN DE LA CORRECCIÓN ---

        fecha_ingreso_str = root.findtext('.//v1:FechaIngreso', namespaces=NS)
        fecha_ingreso = fecha_ingreso_str.split('T')[0] if fecha_ingreso_str else None
        
        comision_node = root.find('.//v1:Comisiones/v1:Comision/v1:Nombre', NS)
        comision = comision_node.text if comision_node is not None else "No especificada"
        
        autores = []
        for autor_node in root.findall('.//v1:Autores/v1:ParlamentarioAutor', NS):
            diputado_id_node = autor_node.find('.//v1:Diputado/v1:Id', NS)
            if diputado_id_node is not None and diputado_id_node.text:
                autores.append(diputado_id_node.text)
        
        resultado_node = root.find('.//v1:Estado', NS)
        resultado = resultado_node.text if resultado_node is not None else "En tramitación"

        return {
            "bill_id": bill_id,
            "resumen": resumen_final,
            "comision": comision,
            "resultado": resultado,
            "fecha_ingreso": fecha_ingreso,
            "autores_ids": autores
        }

    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error de red para el boletín {bill_id}: {e}")
    except ET.ParseError as e:
        print(f"  ❌ Error de XML para el boletín {bill_id}: {e}")
    
    return None

# --- 3. FASE DE CARGA (Load) ---

def setup_database(conn):
    """
    Asegura que las tablas `bills` y `bill_authors` existan.
    """
    print("🛠️  [DB Setup] Verificando que las tablas `bills` y `bill_authors` existan...")
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS bills (
            bill_id TEXT PRIMARY KEY,
            resumen TEXT,
            comision TEXT,
            resultado TEXT,
            fecha_ingreso DATE
        );
        CREATE TABLE IF NOT EXISTS bill_authors (
            bill_id TEXT NOT NULL,
            mp_uid INTEGER NOT NULL,
            PRIMARY KEY (bill_id, mp_uid),
            FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
            FOREIGN KEY (mp_uid) REFERENCES dim_parlamentario(mp_uid) ON DELETE CASCADE
        );
    """)
    conn.commit()
    print("✅  [DB Setup] Esquema para `bills` y `bill_authors` verificado.")

def load_bill_to_db(bill_details, conn):
    """
    Carga los detalles de un proyecto de ley y sus autores en la base de datos.
    """
    if not bill_details:
        return

    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO bills (bill_id, resumen, comision, resultado, fecha_ingreso)
            VALUES (?, ?, ?, ?, ?)
        """, (
            bill_details['bill_id'],
            bill_details['resumen'] or "Sin descripción disponible.", # Fallback final
            bill_details['comision'],
            bill_details['resultado'],
            bill_details['fecha_ingreso']
        ))
        print(f"    -> Proyecto {bill_details['bill_id']} insertado/actualizado en `bills`.")
    except sqlite3.Error as e:
        print(f"    ❌ Error al insertar en `bills` para {bill_details['bill_id']}: {e}")
        return

    if not bill_details['autores_ids']:
        print(f"    -> El proyecto {bill_details['bill_id']} no tiene autores parlamentarios listados (puede ser un Mensaje).")
        conn.commit()
        return

    for diputado_id in bill_details['autores_ids']:
        try:
            cursor.execute("SELECT mp_uid FROM dim_parlamentario WHERE diputadoid = ?", (diputado_id,))
            result = cursor.fetchone()
            
            if result:
                mp_uid = result[0]
                cursor.execute("""
                    INSERT OR IGNORE INTO bill_authors (bill_id, mp_uid)
                    VALUES (?, ?)
                """, (bill_details['bill_id'], mp_uid))
            else:
                print(f"    ⚠️  Advertencia: No se encontró `mp_uid` para el autor con `diputadoid` {diputado_id}.")
        
        except sqlite3.Error as e:
            print(f"    ❌ Error al insertar en `bill_authors` para autor {diputado_id} en proyecto {bill_details['bill_id']}: {e}")

    conn.commit()

# --- 4. ORQUESTACIÓN ---

def main():
    """
    Función principal que orquesta el proceso ETL para proyectos de ley.
    """
    print("--- Iniciando Proceso ETL: Proyectos de Ley y Autores ---")
    start_year = 2023 
    end_year = datetime.now().year

    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            setup_database(conn)

            all_bill_ids = []
            for year in range(start_year, end_year + 1):
                all_bill_ids.extend(fetch_projects_by_year(year))
            
            unique_bill_ids = sorted(list(set(all_bill_ids)), reverse=True)
            print(f"\n📑 Se procesarán un total de {len(unique_bill_ids)} proyectos de ley únicos.\n")

            for bill_id in unique_bill_ids:
                details = fetch_bill_details(bill_id)
                if details:
                    load_bill_to_db(details, conn)

    except Exception as e:
        print(f"❌  Error Crítico durante la operación con la Base de Datos: {e}")

    print("\n--- Proceso ETL de Proyectos de Ley Finalizado ---")

if __name__ == "__main__":
    main()