# -*- coding: utf-8 -*-
"""
Script para enriquecer el manifiesto de videos de comisiones, utilizando un LLM
para enlazar cada video con su comision_id correspondiente desde la base de datos.

Características clave:
- CLI con rutas configurables (DB, CSV entrada/salida, caché, pendientes)
- Obtención de comisiones desde SQLite
- Heurística regex previa al LLM (rápida y barata)
- Llamada al LLM con salida estricta en JSON
- Validación de comision_id y nombre contra la BD
- Caché por video_id/título (disco) para evitar llamadas repetidas
- Export de casos pendientes (validación ≠ ok)

Requisitos:
- Variables de entorno: OPENAI_API_KEY (y opcionalmente DB_PATH/INPUT_CSV_PATH/OUTPUT_CSV_PATH/CACHE_PATH/PENDING_REVIEW_PATH)
- Paquetes: pandas, python-dotenv, openai>=1.0.0
- utils.retry.retry decorador (reintentos exponenciales)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from utils.retry import retry  # se asume disponible en el proyecto

# -----------------------------------------------------------------------------
# 1) CONFIGURACIÓN BÁSICA
# -----------------------------------------------------------------------------
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("La variable de entorno OPENAI_API_KEY no está configurada.")

client = OpenAI()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "database", "parlamento.db")
DEFAULT_INPUT_CSV_PATH = os.path.join(
    PROJECT_ROOT,
    "data",
    "video_processing",
    "playlists",
    "playlists 2025",
    "comisiones_2025.csv",
)
DEFAULT_OUTPUT_CSV_PATH = os.path.join(
    PROJECT_ROOT,
    "data",
    "video_processing",
    "playlists",
    "playlists 2025",
    "comisiones_2025_enlazado.csv",
)
DEFAULT_CACHE_PATH = os.path.join(
    PROJECT_ROOT, "data", "video_processing", "cache_enlaces.json"
)
DEFAULT_PENDING_REVIEW_PATH = os.path.join(
    PROJECT_ROOT,
    "data",
    "video_processing",
    "playlists",
    "playlists 2025",
    "pending_review.csv",
)

# -----------------------------------------------------------------------------
# 2) UTILIDADES (caché, normalización, regex de fecha)
# -----------------------------------------------------------------------------

def load_cache(path: str) -> Dict[str, dict]:
    """Carga el contenido del caché desde ``path`` (JSON)."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("No se pudo leer la caché %s: %s", path, e)
    return {}


def save_cache(path: str, cache: Dict[str, dict]) -> None:
    """Guarda ``cache`` en ``path`` como JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("Error al escribir la caché %s: %s", path, e)


def _normalize(text: str) -> str:
    """Normaliza eliminando tildes, colapsando espacios y minúsculas."""
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = normalized.encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"\s+", " ", normalized).strip().lower()


def _extract_date(text: str) -> Optional[str]:
    """Extrae fecha DD-MM-YYYY o DD/MM/YYYY y retorna YYYY-MM-DD."""
    if not text:
        return None
    match = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", text)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month}-{day}"
    return None


def match_comision_by_regex(title: str, df_comisiones: pd.DataFrame) -> Optional[Dict[str, Optional[str]]]:
    """Busca coincidencias exactas de nombre de comisión en el título normalizado.
    Devuelve dict con comision_id, nombre_comision y fecha, o None si no hay match.
    """
    title_norm = _normalize(title)
    for row in df_comisiones.itertuples():
        nombre_norm = _normalize(row.nombre_comision)
        pattern = rf"\b{re.escape(nombre_norm)}\b"
        if re.search(pattern, title_norm):
            return {
                "comision_id": int(row.comision_id),
                "nombre_comision": row.nombre_comision,
                "fecha": _extract_date(title),
            }
    return None

# -----------------------------------------------------------------------------
# 3) ACCESO A DATOS
# -----------------------------------------------------------------------------

def get_comisiones_from_db(db_path: str) -> pd.DataFrame:
    """Obtiene el catálogo de comisiones desde la base de datos."""
    logger.info("Conectando a la base de datos para obtener comisiones: %s", db_path)
    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(
                "SELECT comision_id, nombre_comision FROM dim_comisiones", conn
            )
            logger.info("Se encontraron %d comisiones", len(df))
            return df
    except Exception as e:
        logger.error("Error al leer la base de datos: %s", e)
        return pd.DataFrame(columns=["comision_id", "nombre_comision"])

# -----------------------------------------------------------------------------
# 4) LLM
# -----------------------------------------------------------------------------

@retry()
def link_video_to_comision(video_title: str, comisiones_json_str: str) -> dict:
    """Usa el LLM de OpenAI para encontrar la comisión y fecha en el título."""
    system_prompt = f"""
    Eres un asistente experto en clasificar datos del Congreso de Chile.
    Tu tarea es analizar el título de un video de YouTube y asociarlo a una comisión específica de la siguiente lista.
    Debes extraer también la fecha mencionada en el título.

    Aquí está la lista de comisiones disponibles en formato JSON:
    {comisiones_json_str}

    Analiza el siguiente título y devuelve ÚNICAMENTE un objeto JSON con los campos:
    - "comision_id": El ID numérico de la comisión encontrada.
    - "nombre_comision": El nombre exacto de la comisión de la lista.
    - "fecha": La fecha extraída del título en formato YYYY-MM-DD.

    Si no puedes encontrar una coincidencia clara, devuelve un JSON con valores nulos.
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'Título del video: "{video_title}"'},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error("Error en la API de OpenAI: %s", e)
        return {"comision_id": None, "nombre_comision": None, "fecha": None}

# -----------------------------------------------------------------------------
# 5) VALIDACIÓN
# -----------------------------------------------------------------------------

@dataclass
class ValidationResult:
    comision_id: Optional[int]
    nombre_comision: Optional[str]
    fecha: Optional[str]
    validation_status: str
    validation_error: Optional[str]
    match_source: Optional[str] = None


def validate_link(linked: dict, df_comisiones: pd.DataFrame) -> ValidationResult:
    raw_id = linked.get("comision_id")
    try:
        comision_id = int(raw_id) if raw_id is not None else None
    except (ValueError, TypeError):
        comision_id = None

    nombre = linked.get("nombre_comision")
    fecha = linked.get("fecha")

    status = "ok"
    error = None

    if comision_id is None:
        status = "not_found"
        error = "comision_id inválido o ausente"
    else:
        match = df_comisiones[df_comisiones["comision_id"] == comision_id]
        if match.empty:
            status = "not_found"
            error = f"comision_id {comision_id} no encontrado"
        else:
            expected = match["nombre_comision"].iloc[0]
            if nombre != expected:
                status = "mismatch"
                error = f"nombre '{nombre}' no corresponde a '{expected}'"

    return ValidationResult(
        comision_id=comision_id,
        nombre_comision=nombre,
        fecha=fecha,
        validation_status=status,
        validation_error=error,
        match_source=linked.get("match_source"),
    )

# -----------------------------------------------------------------------------
# 6) CLI
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enlaza cada video del manifiesto con su comision_id utilizando un LLM"
        )
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("DB_PATH", DEFAULT_DB_PATH),
        help="Ruta al archivo de base de datos SQLite",
    )
    parser.add_argument(
        "--input-csv",
        default=os.getenv("INPUT_CSV_PATH", DEFAULT_INPUT_CSV_PATH),
        help="Ruta al CSV de entrada con el manifiesto de videos",
    )
    parser.add_argument(
        "--output-csv",
        default=os.getenv("OUTPUT_CSV_PATH", DEFAULT_OUTPUT_CSV_PATH),
        help="Ruta donde se guardará el CSV enriquecido",
    )
    parser.add_argument(
        "--cache-path",
        default=os.getenv("CACHE_PATH", DEFAULT_CACHE_PATH),
        help="Ruta del archivo de caché para resultados intermedios",
    )
    parser.add_argument(
        "--pending-review-path",
        default=os.getenv("PENDING_REVIEW_PATH", DEFAULT_PENDING_REVIEW_PATH),
        help="Ruta donde se guardarán casos pendientes de revisión",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Si se activa, NO llama al LLM (solo heurística y caché)",
    )
    return parser.parse_args()

# -----------------------------------------------------------------------------
# 7) MAIN
# -----------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    logger.info("Iniciando Proceso de Enlace de Videos a Comisiones")

    # 1. Cargar catálogos y manifiesto
    df_comisiones = get_comisiones_from_db(args.db_path)
    if df_comisiones.empty:
        logger.error("No hay comisiones disponibles, abortando.")
        return

    try:
        df_videos = pd.read_csv(args.input_csv)
        logger.info("Se cargaron %d videos desde el manifiesto", len(df_videos))
    except FileNotFoundError:
        logger.error("No se encontró el archivo de entrada: %s", args.input_csv)
        return

    # Asegurar columnas básicas si faltan (evita KeyError al reordenar)
    for col in [
        "video_id",
        "video_url",
        "title",
        "upload_date",
        "status",
        "last_processed",
    ]:
        if col not in df_videos.columns:
            df_videos[col] = None

    comisiones_context_str = df_comisiones.to_json(orient="records")

    # 2. Cargar caché
    cache = load_cache(args.cache_path)

    # 3. Iterar
    results: list[dict] = []
    total_videos = len(df_videos)

    for index, row in df_videos.iterrows():
        vid = row.get("video_id")
        title = row.get("title", "") or ""
        logger.info("Procesando video %d/%d: %s", index + 1, total_videos, title)

        # 3a. Buscar en caché (por video_id y fallback por título)
        cache_entry = None
        if vid and vid in cache:
            cache_entry = cache[vid]
        else:
            for _vid, data in cache.items():
                if data.get("title") == title:
                    cache_entry = data
                    break

        if cache_entry:
            linked = {
                "comision_id": cache_entry.get("comision_id"),
                "nombre_comision": cache_entry.get("nombre_comision"),
                "fecha": cache_entry.get("fecha"),
                "match_source": cache_entry.get("match_source", "cache"),
            }
        else:
            # 3b. Heurística
            heur = match_comision_by_regex(title, df_comisiones)
            if heur:
                heur["match_source"] = "heuristic"
                linked = heur
            else:
                # 3c. LLM (opcional)
                if args.skip_llm:
                    linked = {"comision_id": None, "nombre_comision": None, "fecha": None, "match_source": "skipped_llm"}
                else:
                    linked = link_video_to_comision(title, comisiones_context_str)
                    linked["match_source"] = "llm"

            # Persistir en caché
            cache[vid or title] = {
                "title": title,
                "comision_id": linked.get("comision_id"),
                "nombre_comision": linked.get("nombre_comision"),
                "fecha": linked.get("fecha"),
                "match_source": linked.get("match_source"),
            }
            save_cache(args.cache_path, cache)

        # 3d. Validación
        validation = validate_link(linked, df_comisiones)
        if validation.validation_status != "ok":
            logger.warning(
                "Validación fallida para video %s: %s",
                vid,
                validation.validation_error,
            )

        results.append({
            "comision_id": validation.comision_id,
            "nombre_comision": validation.nombre_comision,
            "fecha": validation.fecha,
            "validation_status": validation.validation_status,
            "validation_error": validation.validation_error,
            "match_source": linked.get("match_source"),
        })

    # 4. Unir resultados y guardar
    df_results = pd.DataFrame(results)
    df_final = pd.concat([df_videos.reset_index(drop=True), df_results], axis=1)

    # Orden de columnas amigable (mantén solo las que existan)
    column_order = [
        "video_id",
        "video_url",
        "title",
        "nombre_comision",
        "comision_id",
        "fecha",
        "match_source",
        "validation_status",
        "validation_error",
        "upload_date",
        "status",
        "last_processed",
    ]
    column_order = [c for c in column_order if c in df_final.columns]
    df_final = df_final[column_order]

    os.makedirs(os.path.dirname(args.output_csv), exist_ok=True)
    df_final.to_csv(args.output_csv, index=False, encoding="utf-8")
    logger.info("Archivo enriquecido guardado en: %s", args.output_csv)

    # 5. Export de pendientes
    df_pending = df_final[df_final["validation_status"] != "ok"] if "validation_status" in df_final.columns else pd.DataFrame()
    if not df_pending.empty:
        os.makedirs(os.path.dirname(args.pending_review_path), exist_ok=True)
        df_pending.to_csv(args.pending_review_path, index=False, encoding="utf-8")
        logger.warning("Se encontraron %d casos pendientes de revisión", len(df_pending))


if __name__ == "__main__":
    main()
