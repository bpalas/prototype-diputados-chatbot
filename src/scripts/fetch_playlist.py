# src/scripts/fetch_playlist.py
# -*- coding: utf-8 -*-

"""
Script para extraer la metadata de una playlist de YouTube y guardarla en un
archivo CSV para su posterior procesamiento.
"""

import os
import pandas as pd
import yt_dlp

# --- 1. CONFIGURACIÓN ---
# URL de la playlist de YouTube que quieres procesar
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLNwLNrmA4-qObJYTzxhkwkL79qRU5yo73"

# Ruta de salida para el archivo CSV (manifiesto de videos)
# Se asegura de que la ruta sea relativa a la raíz del proyecto.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'data', 'video_processing', 'playlists', 'playlists 2025')
OUTPUT_CSV_PATH = os.path.join(OUTPUT_DIR, 'comisiones_2025.csv')


def fetch_playlist_metadata(playlist_url: str) -> list:
    """
    Usa yt-dlp para extraer la metadata esencial de cada video en una playlist.
    """
    print(f"📥 Obteniendo metadata de la playlist: {playlist_url}")
    
    ydl_opts = {
        'extract_flat': True,  # No descargar, solo obtener información
        'quiet': True,         # Suprimir salida innecesaria en la consola
    }

    videos_metadata = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            playlist_dict = ydl.extract_info(playlist_url, download=False)
            
            for video in playlist_dict['entries']:
                if video:
                    videos_metadata.append({
                        'video_id': video.get('id'),
                        'video_url': f"https://www.youtube.com/watch?v={video.get('id')}",
                        'title': video.get('title'),
                        # yt-dlp puede no proveer la fecha de subida en modo 'flat'.
                        # Se requeriría una llamada adicional por video si es necesaria.
                        'upload_date': None,
                    })
            print(f"✅ Se encontraron {len(videos_metadata)} videos en la playlist.")
            return videos_metadata
            
    except Exception as e:
        print(f"❌ Error al procesar la playlist: {e}")
        return []

def create_video_manifest(videos_metadata: list, output_path: str):
    """
    Crea y guarda un DataFrame de pandas con la metadata de los videos,
    añadiendo columnas de estado para el pipeline de procesamiento.
    """
    if not videos_metadata:
        print("⚠️ No hay metadata para crear el manifiesto. Saliendo.")
        return
        
    df = pd.DataFrame(videos_metadata)
    
    # --- Columnas para el control del pipeline ---
    df['status'] = 'pending'  # Estados: pending, processing, done, error
    df['last_processed'] = None
    
    # Crear el directorio si no existe
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Guardar en CSV
    df.to_csv(output_path, index=False, encoding='utf-8')
    print(f"✅ Manifiesto de videos guardado exitosamente en: {output_path}")


def main():
    """Función principal para orquestar la extracción y guardado."""
    metadata = fetch_playlist_metadata(PLAYLIST_URL)
    create_video_manifest(metadata, OUTPUT_CSV_PATH)


if __name__ == "__main__":
    main()