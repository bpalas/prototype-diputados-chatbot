# src/etl/enrich_biographies.py
# -*- coding: utf-8 -*-
"""
Paso 2: Enriquece los datos biográficos de los parlamentarios. (Versión Robusta sin DB Changes)

Lee los registros básicos de `dim_parlamentario`, consulta los JSON de la BCN
y completa sus datos.

Este script es RESUMIBLE: usa la columna `nombre_propio` como un indicador
para marcar registros como procesados (cambiando NULL a un valor o a un string vacío),
permitiendo continuar de forma segura tras una interrupción.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

import requests

# --- 1. CONFIGURACIÓN Y RUTAS ---
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "database" / "parlamento.db"
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "bcn"

# Asegurarse de que el directorio de caché exista
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# --- 2. FUNCIONES DE UTILIDAD (Sin cambios) ---

def _extract_literal(obj: dict[str, Any], key: str) -> Optional[str]:
    """Extrae el primer valor 'literal' de una clave en el JSON-LD."""
    items = obj.get(key, [])
    if items:
        return str(items[0].get("value"))
    return None


def _extract_uri(obj: dict[str, Any], key: str) -> Optional[str]:
    """Extrae el primer valor 'uri' de una clave en el JSON-LD."""
    items = obj.get(key, [])
    if items:
        return items[0].get("value")
    return None


def _fetch_json(url: str) -> Optional[dict[str, Any]]:
    """Descarga un JSON usando un sistema de caché local para evitar re-descargas."""
    filename = url.replace("https://", "").replace("http://", "").replace("/", "_") + ".json"
    cache_path = CACHE_DIR / filename
    
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except requests.exceptions.RequestException as e:
        print(f"❌ Error descargando {url}: {e}")
        return None


def _fetch_event_date(event_uri: str) -> Optional[str]:
    """Obtiene la fecha (`originalDate`) de un recurso de evento."""
    data = _fetch_json(f"{event_uri}/datos.json")
    if not data:
        return None
    event = data.get(event_uri, {})
    return _extract_literal(event, "http://datos.bcn.cl/ontologies/bcn-biographies#originalDate")


def _upsert_party(conn: sqlite3.Connection, party_uri: str) -> Optional[int]:
    """Asegura que un partido exista en `dim_partidos` y devuelve su ID."""
    data = _fetch_json(f"{party_uri}/datos.json")
    if not data:
        return None
    
    node = data.get(party_uri, {})
    nombre = (_extract_literal(node, "http://www.w3.org/2000/01/rdf-schema#label") or 
              _extract_literal(node, "http://xmlns.com/foaf/0.1/name"))
    sigla = _extract_literal(node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasAcronym")
    
    if not nombre:
        return None

    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO dim_partidos (nombre_partido, sigla) VALUES (?, ?)", (nombre, sigla))
    cur.execute("SELECT partido_id FROM dim_partidos WHERE nombre_partido = ?", (nombre,))
    row = cur.fetchone()
    return row[0] if row else None


# --- 3. LÓGICA DE ENRIQUECIMIENTO ---

def enrich_person(conn: sqlite3.Connection, mp_uid: int, person_id: str) -> None:
    """Enriquece una fila de `dim_parlamentario` y sus tablas relacionadas."""
    print(f"Enriqueciendo BCN ID: {person_id} (mp_uid: {mp_uid})...")
    person_url = f"https://datos.bcn.cl/recurso/persona/{person_id}/datos.json"
    data = _fetch_json(person_url)
    
    # Si la descarga falla, no podemos hacer nada, pero no queremos que se quede en bucle.
    # Así que actualizamos `nombre_propio` a '' para marcarlo como "intentado".
    if not data:
        cur = conn.cursor()
        cur.execute("UPDATE dim_parlamentario SET nombre_propio = COALESCE(?, nombre_propio) WHERE mp_uid = ?", ('', mp_uid))
        conn.commit()
        return

    person_uri = f"http://datos.bcn.cl/recurso/persona/{person_id}"
    person_node = data.get(person_uri, {})
    cur = conn.cursor()

    # --- 3.1 Enriquece `dim_parlamentario` ---
    nombre_completo = _extract_literal(person_node, "http://xmlns.com/foaf/0.1/name")
    
    # --- CAMBIO CLAVE AQUÍ ---
    # Si no se encuentra 'givenName', asignamos un string vacío ('') en lugar de None.
    # Esto asegura que la columna `nombre_propio` deje de ser NULL y el script
    # no intente procesar este registro de nuevo en el futuro.
    nombre_propio = _extract_literal(person_node, "http://xmlns.com/foaf/0.1/givenName") or ''
    
    apellido_paterno = _extract_literal(person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#surnameOfFather")
    apellido_materno = _extract_literal(person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#surnameOfMother")
    genero_raw = (_extract_literal(person_node, "http://xmlns.com/foaf/0.1/gender") or
                  _extract_literal(person_node, "https://www.wikidata.org/wiki/Property:P21"))
    genero = {"hombre": "Masculino", "mujer": "Femenino"}.get(genero_raw.lower()) if genero_raw else None
    profesion = _extract_literal(person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#profession")
    url_foto = (_extract_uri(person_node, "http://xmlns.com/foaf/0.1/img") or
                _extract_uri(person_node, "http://xmlns.com/foaf/0.1/depiction"))
    historia = (_extract_uri(person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#bcnPage") or
                _extract_uri(person_node, "http://xmlns.com/foaf/0.1/isPrimaryTopicOf"))
    id_camara = _extract_literal(person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#idCamaraDeDiputados")

    cur.execute(
        """
        UPDATE dim_parlamentario
           SET nombre_completo = COALESCE(?, nombre_completo),
               nombre_propio = COALESCE(?, nombre_propio),
               apellido_paterno = COALESCE(?, apellido_paterno),
               apellido_materno = COALESCE(?, apellido_materno),
               genero = COALESCE(?, genero),
               profesion = COALESCE(?, profesion),
               url_foto = COALESCE(?, url_foto),
               url_historia_politica = COALESCE(?, url_historia_politica),
               diputadoid = COALESCE(?, diputadoid)
         WHERE mp_uid = ?
        """,
        (nombre_completo, nombre_propio, apellido_paterno, apellido_materno, genero, 
         profesion, url_foto, historia, id_camara, mp_uid),
    )

    # --- 3.2 Pobla `parlamentario_mandatos` (sin cambios) ---
    cur.execute("DELETE FROM parlamentario_mandatos WHERE mp_uid = ?", (mp_uid,))
    for item in person_node.get("http://datos.bcn.cl/ontologies/bcn-biographies#hasPositionPeriod", []):
        pp_uri = item["value"]
        pp_data = _fetch_json(f"{pp_uri}/datos.json")
        if not pp_data: continue
        pp_node = pp_data.get(pp_uri, {})
        pos_uri = _extract_uri(pp_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasPosition")
        cargo = None
        if pos_uri:
            pos_data = _fetch_json(f"{pos_uri}/datos.json")
            if pos_data:
                cargo = _extract_literal(pos_data.get(pos_uri, {}), "http://www.w3.org/2000/01/rdf-schema#label")
        inicio_uri = _extract_uri(pp_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasBeginning")
        fin_uri = _extract_uri(pp_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasEnd")
        fecha_inicio = _fetch_event_date(inicio_uri) if inicio_uri else None
        fecha_fin = _fetch_event_date(fin_uri) if fin_uri else None
        if cargo and (cargo in ["Diputado", "Senador"]) and fecha_inicio:
            cur.execute(
                "INSERT INTO parlamentario_mandatos (mp_uid, cargo, fecha_inicio, fecha_fin) VALUES (?, ?, ?, ?)",
                (mp_uid, cargo, fecha_inicio, fecha_fin),
            )

    # --- 3.3 Pobla `militancia_historial` (sin cambios) ---
    cur.execute("DELETE FROM militancia_historial WHERE mp_uid = ?", (mp_uid,))
    for item in person_node.get("http://datos.bcn.cl/ontologies/bcn-biographies#hasMilitancy", []):
        mil_uri = item["value"]
        mil_data = _fetch_json(f"{mil_uri}/datos.json")
        if not mil_data: continue
        mil_node = mil_data.get(mil_uri, {})
        inicio_uri = _extract_uri(mil_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasBeginning")
        fin_uri = _extract_uri(mil_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasEnd")
        fecha_inicio = _fetch_event_date(inicio_uri) if inicio_uri else None
        fecha_fin = _fetch_event_date(fin_uri) if fin_uri else None
        partido_uri = _extract_uri(mil_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasPoliticalParty")
        if partido_uri:
            partido_id = _upsert_party(conn, partido_uri)
            if partido_id:
                cur.execute(
                    "INSERT INTO militancia_historial (mp_uid, partido_id, fecha_inicio, fecha_fin) VALUES (?, ?, ?, ?)",
                    (mp_uid, partido_id, fecha_inicio, fecha_fin),
                )

    conn.commit()


# --- 4. ORQUESTACIÓN ---
def main() -> None:
    """Función principal que orquesta el proceso de enriquecimiento."""
    print("--- Iniciando Proceso de Enriquecimiento Biográfico (Paso 2) ---")
    if not DB_PATH.exists():
        print(f"❌ Error: No se encontró la base de datos en {DB_PATH}")
        return
        
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        
        # --- CAMBIO CLAVE AQUÍ ---
        # La consulta sigue siendo la misma, pero ahora nuestra lógica la hace confiable.
        cur.execute("""
            SELECT mp_uid, bcn_person_id 
            FROM dim_parlamentario 
            WHERE bcn_person_id IS NOT NULL AND nombre_propio IS NULL
            ORDER BY mp_uid ASC
        """)
        rows = cur.fetchall()
        
        total = len(rows)
        if total == 0:
            print("✅ No hay parlamentarios nuevos para enriquecer. La base de datos está al día.")
            return

        print(f"Se encontraron {total} parlamentarios pendientes para enriquecer.")
        
        errores = 0
        for i, (mp_uid, bcn_person_id) in enumerate(rows):
            try:
                print(f"--- Procesando {i+1}/{total} ---")
                enrich_person(conn, mp_uid, str(bcn_person_id))
            
            except sqlite3.IntegrityError as e:
                errores += 1
                print(f"⚠️  Error de integridad al procesar mp_uid {mp_uid} (BCN ID: {bcn_person_id}): {e}")
                print("    Se saltará a este parlamentario y se desharán los cambios.")
                conn.rollback()
            
            except Exception as e:
                errores += 1
                print(f"❌ Error inesperado al procesar mp_uid {mp_uid} (BCN ID: {bcn_person_id}): {e}")
                print("    Se saltará a este parlamentario y se desharán los cambios.")
                conn.rollback()

    except sqlite3.Error as e:
        print(f"❌ Error de base de datos general: {e}")
    finally:
        conn.close()
    
    print("--- Proceso de Enriquecimiento Finalizado ---")
    if errores > 0:
        print(f"Resumen: Se encontraron {errores} errores durante el proceso.")


if __name__ == "__main__":
    main()