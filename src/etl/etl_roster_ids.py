# src/etl/etl_roster_ids.py
# -*- coding: utf-8 -*-
"""ETL mínimo para sincronizar identificadores de parlamentarios.

Obtiene desde el SPARQL de la BCN la lista de personas con sus IDs
externos y los inserta/actualiza en la tabla ``dim_parlamentario``.
Solo se manejan ``bcn_uri``, identificadores externos y nombres si se
encuentran disponibles.
"""

import os
import sqlite3
from SPARQLWrapper import SPARQLWrapper, JSON

# Rutas del proyecto
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
BCN_SPARQL_ENDPOINT = "http://datos.bcn.cl/sparql"


def fetch_identifiers():
    """Recupera IDs básicos de parlamentarios desde el SPARQL de la BCN."""
    sparql = SPARQLWrapper(BCN_SPARQL_ENDPOINT)
    sparql.setReturnFormat(JSON)
    query = """
        PREFIX bcnbio: <http://datos.bcn.cl/ontologies/bcn-biographies#>
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>

        SELECT ?bcn_uri ?bcn_person_id ?id_externo_diputado ?id_externo_senador
               ?nombre ?apellido_paterno ?apellido_materno
        WHERE {
            ?bcn_uri a bcnbio:Person .
            BIND(REPLACE(STR(?bcn_uri), '^.*/', '') AS ?bcn_person_id)
            OPTIONAL { ?bcn_uri bcnbio:idCamaraDeDiputados ?id_externo_diputado . }
            OPTIONAL { ?bcn_uri bcnbio:idSenadores ?id_externo_senador . }
            OPTIONAL { ?bcn_uri foaf:givenName ?nombre . }
            OPTIONAL { ?bcn_uri bcnbio:surnameOfFather ?apellido_paterno . }
            OPTIONAL { ?bcn_uri bcnbio:surnameOfMother ?apellido_materno . }
        }
    """
    sparql.setQuery(query)
    try:
        results = sparql.query().convert()["results"]["bindings"]
    except Exception as exc:
        print(f"❌ Error al ejecutar SPARQL: {exc}")
        return []

    data = []
    for res in results:
        data.append({
            "bcn_uri": res.get("bcn_uri", {}).get("value"),
            "bcn_person_id": res.get("bcn_person_id", {}).get("value"),
            "id_externo_diputado": res.get("id_externo_diputado", {}).get("value"),
            "id_externo_senador": res.get("id_externo_senador", {}).get("value"),
            "nombre": res.get("nombre", {}).get("value"),
            "apellido_paterno": res.get("apellido_paterno", {}).get("value"),
            "apellido_materno": res.get("apellido_materno", {}).get("value"),
        })
    return data


def load_identifiers(data):
    """Inserta o actualiza ``dim_parlamentario`` con los IDs obtenidos."""
    if not data:
        print("⚠️ No se encontraron datos para cargar.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for item in data:
        nombre_completo = " ".join(
            part for part in [item.get("nombre"),
                              item.get("apellido_paterno"),
                              item.get("apellido_materno")] if part
        ).strip() or None

        # Inserción inicial (no duplicar)
        cur.execute(
            """
            INSERT OR IGNORE INTO dim_parlamentario (
                diputadoid, senadorid, bcn_uri, bcn_person_id,
                nombre_completo, nombre_propio, apellido_paterno, apellido_materno
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("id_externo_diputado"),
                item.get("id_externo_senador"),
                item.get("bcn_uri"),
                item.get("bcn_person_id"),
                nombre_completo,
                item.get("nombre"),
                item.get("apellido_paterno"),
                item.get("apellido_materno"),
            ),
        )

        # Actualización de campos existentes
        cur.execute(
            """
            UPDATE dim_parlamentario SET
                bcn_uri = COALESCE(?, bcn_uri),
                bcn_person_id = COALESCE(?, bcn_person_id),
                senadorid = COALESCE(?, senadorid),
                nombre_completo = COALESCE(?, nombre_completo),
                nombre_propio = COALESCE(?, nombre_propio),
                apellido_paterno = COALESCE(?, apellido_paterno),
                apellido_materno = COALESCE(?, apellido_materno)
            WHERE diputadoid = ? OR bcn_uri = ?
            """,
            (
                item.get("bcn_uri"),
                item.get("bcn_person_id"),
                item.get("id_externo_senador"),
                nombre_completo,
                item.get("nombre"),
                item.get("apellido_paterno"),
                item.get("apellido_materno"),
                item.get("id_externo_diputado"),
                item.get("bcn_uri"),
            ),
        )

    conn.commit()
    conn.close()
    print(f"✅ Se cargaron {len(data)} identificadores.")


def main():
    data = fetch_identifiers()
    load_identifiers(data)


if __name__ == "__main__":
    main()
