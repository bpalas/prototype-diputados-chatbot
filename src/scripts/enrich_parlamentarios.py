# -*- coding: utf-8 -*-
"""Enriquece datos de parlamentarios usando servicios de BCN.

Lee `bcn_person_id` y `bcn_uri` desde la tabla `dim_parlamentario`,
consulta los endpoints RDF de la BCN y completa la información básica
(nombre, género, profesión, foto, etc.).

Además, para cada `bcnbio:hasPositionPeriod` y `bcnbio:hasMilitancy`
actualiza las tablas `parlamentario_mandatos` y
`militancia_historial` respectivamente.

Los documentos JSON descargados se cachean localmente para evitar
solicitudes repetidas.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

import requests

# Rutas base
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "database" / "parlamento.db"
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "bcn"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Utilidades de extracción de valores RDF/JSON
# ---------------------------------------------------------------------------

def _extract_literal(obj: dict[str, Any], key: str) -> Optional[str]:
    items = obj.get(key, [])
    if items:
        return str(items[0].get("value"))
    return None


def _extract_uri(obj: dict[str, Any], key: str) -> Optional[str]:
    items = obj.get(key, [])
    if items:
        return items[0].get("value")
    return None


def _fetch_json(url: str) -> dict[str, Any]:
    """Descarga un JSON con caché local."""
    fname = CACHE_DIR / (url.replace("https://", "").replace("http://", "").replace("/", "_") + ".json")
    if fname.exists():
        with open(fname, "r", encoding="utf-8") as f:
            return json.load(f)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def _fetch_event_date(event_uri: str) -> Optional[str]:
    """Obtiene la fecha (`originalDate`) de un recurso de evento."""
    data = _fetch_json(f"{event_uri}/datos.json")
    event = data.get(event_uri, {})
    return _extract_literal(event, "http://datos.bcn.cl/ontologies/bcn-biographies#originalDate")


def _upsert_party(conn: sqlite3.Connection, party_uri: str) -> Optional[int]:
    """Inserta o actualiza un partido y devuelve su `partido_id`."""
    data = _fetch_json(f"{party_uri}/datos.json")
    node = data.get(party_uri, {})
    nombre = (
        _extract_literal(node, "http://www.w3.org/2000/01/rdf-schema#label")
        or _extract_literal(node, "http://xmlns.com/foaf/0.1/name")
    )
    sigla = _extract_literal(node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasAcronym")
    if not nombre:
        return None
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO dim_partidos(nombre_partido, sigla) VALUES (?, ?)",
        (nombre, sigla),
    )
    cur.execute("SELECT partido_id FROM dim_partidos WHERE nombre_partido = ?", (nombre,))
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Procesamiento principal
# ---------------------------------------------------------------------------

def enrich_person(conn: sqlite3.Connection, mp_uid: int, person_id: str, bcn_uri: str) -> None:
    person_url = f"https://datos.bcn.cl/recurso/persona/{person_id}/datos.json"
    data = _fetch_json(person_url)
    person_node = data.get(f"http://datos.bcn.cl/recurso/persona/{person_id}", {})

    cur = conn.cursor()

    # Campos básicos
    nombre_completo = _extract_literal(person_node, "http://xmlns.com/foaf/0.1/name")
    nombre_propio = _extract_literal(person_node, "http://xmlns.com/foaf/0.1/givenName")
    apellido_paterno = _extract_literal(person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#surnameOfFather")
    apellido_materno = _extract_literal(person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#surnameOfMother")
    genero_raw = (
        _extract_literal(person_node, "http://xmlns.com/foaf/0.1/gender")
        or _extract_literal(person_node, "https://www.wikidata.org/wiki/Property:P21")
    )
    genero_map = {"hombre": "Masculino", "mujer": "Femenino"}
    genero = genero_map.get(genero_raw.lower()) if genero_raw else None
    profesion = _extract_literal(person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#profession")
    url_foto = _extract_uri(person_node, "http://xmlns.com/foaf/0.1/img") or _extract_uri(
        person_node, "http://xmlns.com/foaf/0.1/depiction"
    )
    historia = _extract_uri(
        person_node, "http://datos.bcn.cl/ontologies/bcn-biographies#bcnPage"
    ) or _extract_uri(person_node, "http://xmlns.com/foaf/0.1/isPrimaryTopicOf")

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
               url_historia_politica = COALESCE(?, url_historia_politica)
         WHERE mp_uid = ?
        """,
        (
            nombre_completo,
            nombre_propio,
            apellido_paterno,
            apellido_materno,
            genero,
            profesion,
            url_foto,
            historia,
            mp_uid,
        ),
    )

    # Position periods -> parlamentario_mandatos
    for item in person_node.get("http://datos.bcn.cl/ontologies/bcn-biographies#hasPositionPeriod", []):
        pp_uri = item["value"]
        pp_data = _fetch_json(f"{pp_uri}/datos.json")
        pp_node = pp_data.get(pp_uri, {})
        pos_uri = _extract_uri(pp_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasPosition")
        cargo = None
        if pos_uri:
            pos_data = _fetch_json(f"{pos_uri}/datos.json")
            cargo = _extract_literal(pos_data.get(pos_uri, {}), "http://www.w3.org/2000/01/rdf-schema#label")
        inicio_uri = _extract_uri(pp_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasBeginning")
        fin_uri = _extract_uri(pp_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasEnd")
        fecha_inicio = _fetch_event_date(inicio_uri) if inicio_uri else None
        fecha_fin = _fetch_event_date(fin_uri) if fin_uri else None
        partido_uri = _extract_uri(pp_node, "http://datos.bcn.cl/ontologies/bcn-biographies#electedByParty")
        partido_id = _upsert_party(conn, partido_uri) if partido_uri else None

        cur.execute(
            """
            INSERT INTO parlamentario_mandatos (mp_uid, cargo, partido_id_mandato, fecha_inicio, fecha_fin)
                 VALUES (?, ?, ?, ?, ?)
            """,
            (mp_uid, cargo, partido_id, fecha_inicio, fecha_fin),
        )

    # Militancy history
    for item in person_node.get("http://datos.bcn.cl/ontologies/bcn-biographies#hasMilitancy", []):
        mil_uri = item["value"]
        mil_data = _fetch_json(f"{mil_uri}/datos.json")
        mil_node = mil_data.get(mil_uri, {})
        inicio_uri = _extract_uri(mil_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasBeginning")
        fin_uri = _extract_uri(mil_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasEnd")
        fecha_inicio = _fetch_event_date(inicio_uri) if inicio_uri else None
        fecha_fin = _fetch_event_date(fin_uri) if fin_uri else None
        partido_uri = _extract_uri(mil_node, "http://datos.bcn.cl/ontologies/bcn-biographies#hasPoliticalParty")
        partido_id = _upsert_party(conn, partido_uri) if partido_uri else None

        cur.execute(
            """
            INSERT INTO militancia_historial (mp_uid, partido_id, fecha_inicio, fecha_fin)
                 VALUES (?, ?, ?, ?)
            """,
            (mp_uid, partido_id, fecha_inicio, fecha_fin),
        )

    conn.commit()


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"No se encontró la base de datos en {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        # Detectar columna del identificador BCN (bcn_person_id o diputadoid)
        cur.execute("PRAGMA table_info(dim_parlamentario)")
        cols = [r[1] for r in cur.fetchall()]
        id_col = "bcn_person_id" if "bcn_person_id" in cols else "diputadoid"

        cur.execute(f"SELECT mp_uid, {id_col}, bcn_uri FROM dim_parlamentario WHERE {id_col} IS NOT NULL AND bcn_uri IS NOT NULL")
        rows = cur.fetchall()
        for mp_uid, bcn_person_id, bcn_uri in rows:
            enrich_person(conn, mp_uid, str(bcn_person_id), bcn_uri)
        # TODO: complementar datos de parlamentarios activos con API Cámara/Senado
    finally:
        conn.close()


if __name__ == "__main__":
    main()
