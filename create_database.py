import sqlite3
import os

# --- 1. CONFIGURACIÓN DE RUTAS ---
# Directorio raíz del proyecto (asume que este script está en la raíz)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Ruta completa para la nueva base de datos
DB_DIRECTORY = os.path.join(PROJECT_ROOT, 'data', 'database')
DB_PATH = os.path.join(DB_DIRECTORY, 'parlamento.db')

# Ruta al archivo que contiene el esquema SQL
SCHEMA_PATH = os.path.join(PROJECT_ROOT, 'data', 'docs', 'schema.sql')


def column_exists(conn, table_name, column_name):
    """Verifica si una columna existe en una tabla dada."""
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return column_name in [row[1] for row in cursor.fetchall()]


def create_database_from_schema():
    """
    Crea la estructura de la base de datos a partir de un archivo .sql
    en la ruta especificada.
    """
    try:
        # --- 2. CREAR DIRECTORIOS ---
        print(f"Asegurando que el directorio '{DB_DIRECTORY}' exista...")
        os.makedirs(DB_DIRECTORY, exist_ok=True)
        print("-> Directorio verificado.")

        # Si la base de datos ya existe, aplicar migraciones mínimas
        if os.path.exists(DB_PATH):
            print(f"Base de datos existente detectada en '{DB_PATH}'. Aplicando migraciones...")
            with sqlite3.connect(DB_PATH) as conn:
                if not column_exists(conn, 'dim_parlamentario', 'bcn_person_id'):
                    print("-> Añadiendo columna 'bcn_person_id' a 'dim_parlamentario'...")
                    conn.execute("ALTER TABLE dim_parlamentario ADD COLUMN bcn_person_id TEXT UNIQUE")
                    conn.commit()
                    print("-> Columna añadida correctamente.")
                else:
                    print("-> La columna 'bcn_person_id' ya existe. No se requieren cambios.")
            return

        # --- 3. LEER EL ESQUEMA SQL ---
        print(f"Leyendo el esquema desde '{SCHEMA_PATH}'...")
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            sql_schema_script = f.read()
        print("-> Esquema leído correctamente.")

        # --- 4. CONECTAR Y CREAR LA BASE DE DATOS ---
        print(f"Creando y conectando a la base de datos en '{DB_PATH}'...")
        # La conexión crea el archivo .db si no existe
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

            # --- 5. EJECUTAR EL SCRIPT SQL ---
            print("Ejecutando script SQL para crear tablas e índices...")
            # executescript() permite ejecutar múltiples sentencias SQL a la vez
            cursor.executescript(sql_schema_script)
            conn.commit()

        print("\n✅ ¡Éxito! La base de datos 'parlamento.db' ha sido creada con la estructura correcta.")

    except FileNotFoundError:
        print(f"❌ ERROR: No se encontró el archivo de esquema en '{SCHEMA_PATH}'.")
        print("Asegúrate de que el archivo exista y la ruta sea correcta.")
    except sqlite3.Error as e:
        print(f"❌ ERROR de base de datos: {e}")
    except Exception as e:
        print(f"❌ Ocurrió un error inesperado: {e}")

# --- Ejecutar la función principal ---
if __name__ == "__main__":
    create_database_from_schema()
