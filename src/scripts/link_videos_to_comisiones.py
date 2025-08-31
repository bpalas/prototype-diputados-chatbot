# src/scripts/link_videos_to_comisiones.py
# -*- coding: utf-8 -*-

"""
Script para enriquecer el manifiesto de videos de comisiones, utilizando un LLM
para enlazar cada video con su comision_id correspondiente desde la base de datos.
"""

import os
import json
import re
import unicodedata
from typing import Dict

import pandas as pd
import sqlite3
from openai import OpenAI
from dotenv import load_dotenv
import logging

from utils.retry import retry

# --- 1. CONFIGURACIÓN ---
load_dotenv() # Carga las variables de entorno desde un archivo .env

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Asegúrate de que tu clave de API de OpenAI esté en un archivo .env
# OPENAI_API_KEY="sk-..."
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("La variable de entorno OPENAI_API_KEY no está configurada.")

client = OpenAI()

# Rutas de archivos
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
INPUT_CSV_PATH = os.path.join(PROJECT_ROOT, 'data', 'video_processing', 'playlists', 'playlists 2025', 'comisiones_2025.csv')
OUTPUT_CSV_PATH = os.path.join(PROJECT_ROOT, 'data', 'video_processing', 'playlists', 'playlists 2025', 'comisiones_2025_enlazado.csv')
CACHE_PATH = os.path.join(PROJECT_ROOT, 'data', 'video_processing', 'cache_enlaces.json')

def get_comisiones_from_db() -> pd.DataFrame:
    """Obtiene el catálogo de comisiones desde la base de datos."""
    logger.info("Conectando a la base de datos para obtener comisiones")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query("SELECT comision_id, nombre_comision FROM dim_comisiones", conn)
            logger.info("Se encontraron %d comisiones", len(df))
            return df
    except Exception as e:
        logger.error("Error al leer la base de datos: %s", e)
        return pd.DataFrame()

@retry()
def link_video_to_comision(video_title: str, comisiones_json_str: str) -> dict:
    """
    Usa el LLM de OpenAI para encontrar la comisión y fecha en el título de un video.
    """
    system_prompt = f"""
    Eres un asistente experto en clasificar datos del Congreso de Chile.
    Tu tarea es analizar el título de un video de YouTube y asociarlo a una comisión específica de la siguiente lista.
    Debes extraer también la fecha mencionada en el título.

    Aquí está la lista de comisiones disponibles en formato JSON:
    {comisiones_json_str}

    Analiza el siguiente título y devuelve ÚNICAMENTE un objeto JSON con los siguientes campos:
    - "comision_id": El ID numérico de la comisión encontrada.
    - "nombre_comision": El nombre exacto de la comisión de la lista.
    - "fecha": La fecha extraída del título en formato YYYY-MM-DD.

    Si no puedes encontrar una coincidencia clara, devuelve un JSON con valores nulos.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # Un modelo rápido y eficiente para esta tarea
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Título del video: \"{video_title}\""}
            ],
            response_format={"type": "json_object"},
            temperature=0.0 # Queremos respuestas predecibles y precisas
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error("Error en la API de OpenAI: %s", e)
        return {"comision_id": None, "nombre_comision": None, "fecha": None}

def main():
    """Función principal para orquestar el proceso de enlace."""
    logger.info("Iniciando Proceso de Enlace de Videos a Comisiones")
    
    # 1. Cargar los datos
    df_comisiones = get_comisiones_from_db()
    if df_comisiones.empty:
        return
        
    try:
        df_videos = pd.read_csv(INPUT_CSV_PATH)
        logger.info("Se cargaron %d videos desde el manifiesto", len(df_videos))
    except FileNotFoundError:
        logger.error("No se encontró el archivo de entrada", extra={"path": INPUT_CSV_PATH})
        return

    # 2. Preparar contexto para el LLM
    comisiones_context_str = df_comisiones.to_json(orient='records')

    # Cargar cache existente
    cache = load_cache()

    # 3. Iterar, procesar y enriquecer
    results = []
    total_videos = len(df_videos)
    for index, row in df_videos.iterrows():
        logger.info(
            "Procesando video %d/%d: %s",
            index + 1,
            total_videos,
            row['title'],
            extra={"video_id": row['video_id']},
        )
        
        # Llamada al LLM
        linked_data = link_video_to_comision(row['title'], comisiones_context_str)
        
        # Guardar resultado
        results.append({
            'comision_id': linked_data.get('comision_id'),
            'nombre_comision': linked_data.get('nombre_comision'),
            'fecha': linked_data.get('fecha')
        })

    # 4. Unir resultados y guardar
    df_results = pd.DataFrame(results)
    df_final = pd.concat([df_videos, df_results], axis=1)
    
    # Reordenar columnas para mayor claridad
    column_order = ['video_id', 'video_url', 'title', 'nombre_comision', 'comision_id', 'fecha', 'upload_date', 'status', 'last_processed']
    df_final = df_final[column_order]

    df_final.to_csv(OUTPUT_CSV_PATH, index=False, encoding='utf-8')
    logger.info("Proceso completado. Archivo enriquecido guardado en: %s", OUTPUT_CSV_PATH)


if __name__ == "__main__":
    main()
