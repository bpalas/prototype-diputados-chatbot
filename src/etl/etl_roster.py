import sqlite3
import requests
import xml.etree.ElementTree as ET
import os
from datetime import datetime

# --- 1. CONFIGURACIÓN ---
API_URL = "https://opendata.camara.cl/camaradiputados/WServices/WSDiputado.asmx/retornarDiputadosPeriodoActual"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, 'data', 'database', 'parlamento.db')

# --- 2. EXTRACCIÓN (Extract) ---
def fetch_diputados_data():
    """Se conecta a la API de la Cámara y obtiene los datos de diputados en formato XML."""
    print("🏛️  Conectando a la API de la Cámara de Diputados...")
    try:
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        print("✅ Datos XML recibidos correctamente.")
        return response.content
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al conectar con la API: {e}")
        return None

# --- 3. TRANSFORMACIÓN (Transform) & CARGA (Load) ---
def process_and_load_data(xml_data):
    """Parsea el XML, transforma los datos y los carga en la base de datos SQLite."""
    if not xml_data:
        print("No hay datos para procesar.")
        return

    print(f"🗃️  Conectando a la base de datos en: {DB_PATH}")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM dim_parlamentario")
        print("🧹 Tabla 'dim_parlamentario' limpiada.")

        # Definir el namespace correcto del XML
        ns = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}
        root = ET.fromstring(xml_data)
        
        # El elemento principal a iterar es 'DiputadoPeriodo'
        diputados_periodo_list = root.findall('v1:DiputadoPeriodo', ns)
        
        if not diputados_periodo_list:
            print("⚠️ ¡Alerta! No se encontraron elementos '<DiputadoPeriodo>' en el XML.")
            return

        count = 0
        today = datetime.now().date()

        for diputado_periodo in diputados_periodo_list:
            try:
                # Extraer datos del diputado desde la estructura anidada
                diputado = diputado_periodo.find('v1:Diputado', ns)
                if diputado is None:
                    continue # Saltar si por alguna razón no hay info del diputado

                diputado_id = diputado.findtext('v1:Id', namespaces=ns)
                nombre = diputado.findtext('v1:Nombre', default='', namespaces=ns).strip()
                apellido_paterno = diputado.findtext('v1:ApellidoPaterno', default='', namespaces=ns).strip()
                apellido_materno = diputado.findtext('v1:ApellidoMaterno', default='', namespaces=ns).strip()
                
                nombre_completo = f"{nombre} {apellido_paterno} {apellido_materno}".strip()
                
                sexo_tag = diputado.find('v1:Sexo', ns)
                genero = "Femenino" if sexo_tag is not None and sexo_tag.get('Valor') == '0' else "Masculino"

                # --- LÓGICA CLAVE: Encontrar la militancia actual ---
                current_party = 'Independiente' # Valor por defecto
                militancias = diputado.findall('v1:Militancias/v1:Militancia', ns)
                for militancia in militancias:
                    start_str = militancia.findtext('v1:FechaInicio', namespaces=ns)
                    end_str = militancia.findtext('v1:FechaTermino', namespaces=ns)
                    
                    if start_str and end_str:
                        # Convertir fechas ignorando la hora
                        start_date = datetime.fromisoformat(start_str.split('T')[0]).date()
                        end_date = datetime.fromisoformat(end_str.split('T')[0]).date()
                        
                        if start_date <= today <= end_date:
                            party_tag = militancia.find('v1:Partido', ns)
                            if party_tag is not None:
                                current_party = party_tag.findtext('v1:Nombre', namespaces=ns)
                                break # Encontramos el partido actual, salimos del bucle

                # Extraer fechas del mandato del elemento 'DiputadoPeriodo'
                fecha_inicio_mandato = diputado_periodo.findtext('v1:FechaInicio', namespaces=ns).split('T')[0]
                # 'FechaTermino' puede no estar presente en el periodo actual, lo manejamos
                fecha_termino_tag = diputado_periodo.find('v1:FechaTermino', ns)
                fecha_termino_mandato = fecha_termino_tag.text.split('T')[0] if fecha_termino_tag is not None and fecha_termino_tag.text else "Actual"
                fechas_mandato = f"{fecha_inicio_mandato} - {fecha_termino_mandato}"

                # Insertar los datos limpios en la base de datos
                parlamentario_data = (
                    nombre_completo, genero, current_party, None, 
                    fechas_mandato, diputado_id, None
                )
                cursor.execute("""
                    INSERT INTO dim_parlamentario (
                        nombre_completo, genero, partido, distrito, 
                        fechas_mandato, diputadoid, wikidata_qid
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, parlamentario_data)
                count += 1

            except Exception as e:
                print(f"⚠️ Error procesando un registro. Diputado ID podría ser {diputado_id or 'desconocido'}. Error: {e}")
        
        conn.commit()
        print(f"✅ ¡Proceso completado! Se insertaron {count} registros en la tabla 'dim_parlamentario'.")

# --- 4. ORQUESTACIÓN ---
def main():
    """Función principal que orquesta el proceso ETL."""
    print("--- Iniciando ETL para el Roster de Parlamentarios (v2) ---")
    xml_data = fetch_diputados_data()
    if xml_data:
        process_and_load_data(xml_data)
    print("--- ETL finalizado ---")

if __name__ == "__main__":
    main()

# estrategia Borrar y Recargar