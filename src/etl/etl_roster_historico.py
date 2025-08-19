# src/etl/etl_roster_historico.py
# -*- coding: utf-8 -*-

"""
ETL para la carga masiva de datos históricos de diputados de todos los 
períodos legislativos anteriores.

v1.0:
- Obtiene todos los períodos legislativos disponibles.
- Itera sobre cada período para extraer la lista de diputados.
- Utiliza un sistema de caché para evitar peticiones repetidas a la API.
- Carga los datos en la base de datos usando "INSERT OR IGNORE" para no 
  sobrescribir ni duplicar parlamentarios ya existentes.
"""

import sqlite3
import requests
import xml.etree.ElementTree as ET
import os
import time
from typing import List, Dict, Optional

# --- 1. CONFIGURACIÓN Y RUTAS ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
XML_CACHE_PATH = os.path.join(PROJECT_ROOT, 'data', 'xml', 'roster_historico')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}

# --- 2. FASE DE EXTRACCIÓN (CON CACHÉ) ---

def get_xml_content(url: str, cache_filename: str) -> Optional[bytes]:
    """Obtiene contenido XML desde una URL, usando un caché local."""
    cache_filepath = os.path.join(XML_CACHE_PATH, cache_filename)
    if os.path.exists(cache_filepath):
        print(f"  -> Leyendo desde caché: {cache_filename}")
        with open(cache_filepath, 'rb') as f:
            return f.read()
    
    print(f"  -> Obteniendo desde API: {url.split('?')[0]}...")
    try:
        response = requests.get(url, timeout=90) # Timeout más largo para peticiones potencialmente pesadas
        response.raise_for_status()
        xml_content = response.content
        with open(cache_filepath, 'wb') as f:
            f.write(xml_content)
        print("     -> XML guardado en caché.")
        time.sleep(0.5) # Pausa más larga para ser respetuoso con la API
        return xml_content
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error de red al intentar acceder a {url}: {e}")
        return None

def fetch_periodos_legislativos() -> List[Dict[str, str]]:
    """Obtiene la lista de todos los períodos legislativos disponibles."""
    url = "https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarPeriodosLegislativos"
    
    print("🏛️  [HISTORICO] Obteniendo listado de todos los períodos legislativos...")
    
    # La lógica de caché se encarga de guardar el XML
    xml_content = get_xml_content(url, "periodos_legislativos.xml") 
    
    if not xml_content:
        return []
    
    periodos = []
    root = ET.fromstring(xml_content)
    
    # La estructura del XML de respuesta podría ser diferente. 
    # Ajustamos la búsqueda al namespace correcto.
    for periodo_node in root.findall('.//{http://opendata.camara.cl/camaradiputados/v1}PeriodoLegislativo'):
        periodo_id = periodo_node.findtext('{http://opendata.camara.cl/camaradiputados/v1}Id')
        nombre = periodo_node.findtext('{http://opendata.camara.cl/camaradiputados/v1}Nombre')
        if periodo_id:
            periodos.append({'id': periodo_id, 'nombre': nombre})
            
    print(f"✅ Se encontraron {len(periodos)} períodos legislativos para procesar.")
    return periodos

def parse_diputados_por_periodo(periodo_id: str) -> List[Dict]:
    """Parsea la lista de diputados para un período legislativo específico."""
    url = f"https://opendata.camara.cl/camaradiputados/WServices/WSDiputado.asmx/retornarDiputadosXPeriodo?prmPeriodoId={periodo_id}"
    xml_content = get_xml_content(url, f"diputados_periodo_{periodo_id}.xml")
    if not xml_content:
        return []

    diputados_list = []
    root = ET.fromstring(xml_content)

    for diputado_periodo in root.findall('v1:DiputadoPeriodo', NS):
        diputado = diputado_periodo.find('v1:Diputado', NS)
        if diputado is None: continue

        militancias = []
        for m in diputado.findall('v1:Militancias/v1:Militancia', NS):
            partido_tag = m.find('v1:Partido/v1:Nombre', NS)
            if partido_tag is not None and partido_tag.text:
                fecha_fin_tag = m.find('v1:FechaTermino', NS)
                militancias.append({
                    'partido': partido_tag.text.strip(),
                    'fecha_inicio': m.findtext('v1:FechaInicio', namespaces=NS, default='').split('T')[0],
                    'fecha_fin': fecha_fin_tag.text.split('T')[0] if fecha_fin_tag is not None and fecha_fin_tag.text else None
                })

        sexo_tag = diputado.find('v1:Sexo', NS)
        distrito_tag = diputado_periodo.find('v1:Distrito', NS)
        fecha_inicio_mandato = diputado_periodo.findtext('v1:FechaInicio', namespaces=NS, default='').split('T')[0]
        fecha_fin_mandato = diputado_periodo.findtext('v1:FechaTermino', namespaces=NS, default='').split('T')[0]

        diputados_list.append({
            'diputadoid': diputado.findtext('v1:Id', namespaces=NS),
            'nombre_completo': f"{diputado.findtext('v1:Nombre', default='', namespaces=NS).strip()} {diputado.findtext('v1:ApellidoPaterno', default='', namespaces=NS).strip()} {diputado.findtext('v1:ApellidoMaterno', default='', namespaces=NS).strip()}".strip(),
            'genero': "Femenino" if sexo_tag is not None and sexo_tag.get('Valor') == '0' else "Masculino",
            'distrito': distrito_tag.get('Numero') if distrito_tag is not None else None,
            'militancias': militancias,
            'fecha_inicio_mandato': fecha_inicio_mandato,
            'fecha_fin_mandato': fecha_fin_mandato
        })
    return diputados_list

# --- 3. FASE DE CARGA (INCREMENTAL) ---

def load_historical_data(all_diputados: List[Dict], conn: sqlite3.Connection):
    """Carga los datos históricos, añadiendo solo los registros que no existen."""
    print("\n⚙️  [DB Load] Iniciando carga de datos históricos...")
    cursor = conn.cursor()

    # Cargar mapa de partidos para obtener IDs
    cursor.execute("SELECT partido_id, nombre_partido FROM dim_partidos")
    partido_map = {nombre: id for id, nombre in cursor.fetchall()}
    
    # Cargar IDs de diputados existentes para evitar intentar re-insertarlos
    cursor.execute("SELECT diputadoid FROM dim_parlamentario")
    existing_diputados = {row[0] for row in cursor.fetchall()}
    print(f"  -> {len(existing_diputados)} parlamentarios ya existen en la base de datos.")

    parlamentarios_cargados = 0
    mandatos_cargados = 0
    
    for diputado_data in all_diputados:
        diputado_id_str = diputado_data.get('diputadoid')
        if not diputado_id_str or diputado_id_str in existing_diputados:
            continue # Omitir si no tiene ID o si ya existe

        # 1. Insertar en `dim_parlamentario` (solo datos básicos de la Cámara)
        # Usamos INSERT OR IGNORE para seguridad, aunque ya filtramos antes.
        cursor.execute("""
            INSERT OR IGNORE INTO dim_parlamentario (diputadoid, nombre_completo, genero) 
            VALUES (?, ?, ?)
        """, (
            diputado_id_str,
            diputado_data['nombre_completo'],
            diputado_data['genero']
        ))
        
        if cursor.rowcount > 0:
            mp_uid = cursor.lastrowid
            parlamentarios_cargados += 1
            existing_diputados.add(diputado_id_str) # Añadir al set para mandatos del mismo diputado
        else:
            # Si no se insertó, necesitamos obtener el mp_uid existente
            cursor.execute("SELECT mp_uid FROM dim_parlamentario WHERE diputadoid = ?", (diputado_id_str,))
            result = cursor.fetchone()
            if result:
                mp_uid = result[0]
            else:
                continue # No se pudo encontrar, omitir

        # 2. Insertar en `parlamentario_mandatos`
        cursor.execute("""
            INSERT INTO parlamentario_mandatos (mp_uid, cargo, distrito, fecha_inicio, fecha_fin)
            VALUES (?, ?, ?, ?, ?)
        """, (
            mp_uid, 'Diputado', diputado_data.get('distrito'), 
            diputado_data.get('fecha_inicio_mandato') or None, 
            diputado_data.get('fecha_fin_mandato') or None
        ))
        mandatos_cargados += 1
        
        # 3. Insertar historial de militancia (si aplica)
        for militancia in diputado_data['militancias']:
            partido_id = partido_map.get(militancia['partido'])
            if partido_id:
                cursor.execute(
                    "INSERT INTO militancia_historial (mp_uid, partido_id, fecha_inicio, fecha_fin) VALUES (?, ?, ?, ?)",
                    (mp_uid, partido_id, militancia['fecha_inicio'] or None, militancia['fecha_fin'] or None)
                )

    conn.commit()
    print(f"✅ Carga histórica finalizada.")
    print(f"  -> Nuevos parlamentarios añadidos: {parlamentarios_cargados}")
    print(f"  -> Nuevos mandatos registrados: {mandatos_cargados}")


# --- 4. ORQUESTACIÓN ---

def main():
    """Función principal que orquesta el proceso ETL histórico."""
    print("--- Iniciando Proceso ETL: Roster Histórico Parlamentario ---")
    try:
        os.makedirs(XML_CACHE_PATH, exist_ok=True)
        
        periodos = fetch_periodos_legislativos()
        if not periodos:
            print("No se encontraron períodos legislativos. Finalizando.")
            return

        all_diputados_historicos = []
        total_periodos = len(periodos)
        for i, periodo in enumerate(periodos):
            print(f"\n({i+1}/{total_periodos}) Procesando período: {periodo['nombre']} (ID: {periodo['id']})")
            diputados_del_periodo = parse_diputados_por_periodo(periodo['id'])
            print(f"  -> Se encontraron {len(diputados_del_periodo)} diputados en este período.")
            all_diputados_historicos.extend(diputados_del_periodo)
            
        if all_diputados_historicos:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON;")
                load_historical_data(all_diputados_historicos, conn)

    except Exception as e:
        print(f"\n❌ Error Crítico durante el ETL histórico: {e}")

    print("\n--- Proceso ETL Histórico Finalizado ---")

if __name__ == "__main__":
    main()