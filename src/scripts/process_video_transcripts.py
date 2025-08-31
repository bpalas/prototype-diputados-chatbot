# src/etl/process_video_transcripts.py
# -*- coding: utf-8 -*-

"""
Orquestador principal para procesar videos de comisiones: descarga, transcribe
con diarización, identifica hablantes con un LLM y carga los turnos de habla
en la base de datos.
"""

import os
import pandas as pd
import sqlite3
from openai import OpenAI
from google.cloud import speech, storage
import yt_dlp
import json
from dotenv import load_dotenv
import time

# --- 1. CONFIGURACIÓN ---
load_dotenv() # Carga las variables de entorno desde el archivo .env

# Cliente de OpenAI
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("La variable de entorno OPENAI_API_KEY no está configurada.")
client = OpenAI()

# Cliente de Google Cloud (se autentica automáticamente con la variable de entorno)
if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    raise ValueError("La variable de entorno GOOGLE_APPLICATION_CREDENTIALS no está configurada.")

# Rutas del proyecto
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
INPUT_CSV_PATH = os.path.join(PROJECT_ROOT, 'data', 'video_processing', 'playlists', 'playlists 2025', 'comisiones_2025_enlazado.csv')
AUDIO_CACHE_PATH = os.path.join(PROJECT_ROOT, 'data', 'audio_cache')
os.makedirs(AUDIO_CACHE_PATH, exist_ok=True)

# Configuración de GCP (¡¡CORREGIDO!!)
GCS_BUCKET_NAME = 'audios-chatbot-diputados-bpalas-2025'

def get_miembros_comision(comision_id: int) -> pd.DataFrame:

    """Obtiene los miembros de una comisión específica desde la BD."""
    with sqlite3.connect(DB_PATH) as conn:
        query = """
            SELECT p.mp_uid, p.nombre_completo
            FROM comision_membresias cm
            JOIN dim_parlamentario p ON cm.mp_uid = p.mp_uid
            WHERE cm.comision_id = ?
        """
        df = pd.read_sql_query(query, conn, params=(comision_id,))
    return df

# Reemplaza la función download_audio en src/etl/process_video_transcripts.py con esta:
# Reemplaza tu función download_audio con esta versión final
# Reemplaza esta función en src/scripts/process_video_transcripts.py
def download_audio(video_url: str, video_id: str) -> str | None:
    """
    Descarga y convierte el audio a formato FLAC MONO, que es ideal para
    la API de Google Speech-to-Text. Requiere ffmpeg.
    """
    output_template = os.path.join(AUDIO_CACHE_PATH, f"{video_id}.flac")

    if os.path.exists(output_template):
        print(f"  -> Audio ya existe en caché: {output_template}")
        return output_template

    print(f"  -> Descargando y convirtiendo audio para '{video_url}' a FLAC MONO...")

    ydl_opts = {
        'format': 'bestaudio/best',
        # Usamos outtmpl para definir el nombre FINAL del archivo.
        'outtmpl': os.path.join(AUDIO_CACHE_PATH, video_id),
        'quiet': False,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'flac',
        }],
        # Forzamos la conversión a 1 canal de audio (mono)
        'postprocessor_args': [
            '-ac', '1'
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # El archivo final tendrá la extensión .flac añadida por el postprocesador
        final_filepath = os.path.join(AUDIO_CACHE_PATH, f"{video_id}.flac")
        
        if os.path.exists(final_filepath):
            print(f"  -> Descarga y conversión completada: {final_filepath}")
            return final_filepath
        else:
            # Fallback por si algo sale mal con los nombres
            raise FileNotFoundError(f"El archivo convertido {final_filepath} no fue encontrado.")

    except Exception as e:
        print(f"  ❌ Error al descargar/convertir con yt-dlp: {e}")
        print("  -> Asegúrate de que FFmpeg esté instalado y accesible en el PATH del sistema.")
        return None
def upload_to_gcs(source_file_path: str, destination_blob_name: str):
    """Sube un archivo a Google Cloud Storage."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)
    print(f"  -> Subiendo a GCS: gs://{GCS_BUCKET_NAME}/{destination_blob_name}")
    blob.upload_from_filename(source_file_path)
# Reemplaza esta función en src/scripts/process_video_transcripts.py
# Reemplaza esta función en src/scripts/process_video_transcripts.py
def transcribe_gcs_audio_with_diarization(gcs_uri: str):
    """Transcripción con diarización activada."""
    client = speech.SpeechClient()
    audio = speech.RecognitionAudio(uri=gcs_uri)
    
    diarization_config = speech.SpeakerDiarizationConfig(
        enable_speaker_diarization=True, min_speaker_count=2, max_speaker_count=15
    )
    
    config = speech.RecognitionConfig(
        language_code="es-CL",
        enable_automatic_punctuation=True,
        diarization_config=diarization_config,
        audio_channel_count=1,
        # La línea 'model="video",' ha sido eliminada.
    )
    
    print("  -> Iniciando trabajo de transcripción en GCP...")
    operation = client.long_running_recognize(config=config, audio=audio)
    
    print("  -> Esperando a que finalice la transcripción (esto puede tardar MUCHO tiempo)...")
    
    # Mantenemos el timeout largo, ¡esto es importante!
    response = operation.result(timeout=10800) 
    return response

def identify_speakers_with_llm(transcript_text: str, miembros_comision_df: pd.DataFrame) -> dict:
    """Usa un LLM para mapear etiquetas de hablante a mp_uid."""
    if miembros_comision_df.empty:
        print("  -> ⚠️ No hay miembros de comisión para identificar. Se omitirá la identificación.")
        return {}

    miembros_json_str = miembros_comision_df.to_json(orient='records', force_ascii=False)
    
    system_prompt = f"""
    Eres un asistente experto en analizar transcripciones del Congreso de Chile.
    Tu tarea es leer una transcripción con etiquetas de hablante genéricas (ej. "Hablante 1")
    y asignar cada hablante a un parlamentario de la lista de miembros de la comisión.

    Lista de posibles hablantes (miembros de la comisión):
    {miembros_json_str}

    Analiza la siguiente transcripción. Considera roles (como "presidente", "secretario") o pistas en el diálogo para hacer la asignación.
    Devuelve un objeto JSON que mapee cada 'speaker_tag' (el número del hablante como string) al 'mp_uid' correcto (como número).
    
    Ejemplo de respuesta: {{ "1": 123, "2": 456 }}
    
    Si no puedes identificar a un hablante con certeza, omítelo del JSON de respuesta.
    """

    print("  -> Usando LLM (OpenAI) para identificar hablantes...")
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Modelo potente para esta tarea compleja
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Transcripción:\n{transcript_text}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        
        mapping_str_keys = json.loads(response.choices[0].message.content)
        # Convertir las claves del JSON (que son string) a enteros
        return {int(k): v for k, v in mapping_str_keys.items()}
    except Exception as e:
        print(f"  -> ❌ Error en la API de OpenAI durante la identificación: {e}")
        return {}


def process_and_load_turns(response, video_info, speaker_mapping, conn):
    """Agrupa las palabras por hablante y carga los turnos en la base de datos."""
    if not (response.results and response.results[-1].alternatives):
        print("  -> ⚠️ La respuesta de transcripción está vacía. No se cargarán datos.")
        return

    words = response.results[-1].alternatives[0].words
    if not words: return

    speech_turns = []
    current_turn = None

    for word in words:
        speaker_tag = word.speaker_tag
        mp_uid = speaker_mapping.get(speaker_tag)
        if not mp_uid: continue # Omitir si el hablante no fue identificado

        if current_turn and current_turn['mp_uid'] == mp_uid:
            # Continuar el turno actual, añadiendo la palabra
            current_turn['texto'] += f" {word.word}"
            current_turn['fin_seg'] = word.end_time.total_seconds()
        else:
            # Si hay un turno anterior, guardarlo
            if current_turn:
                speech_turns.append(current_turn)
            
            # Empezar un nuevo turno de habla
            current_turn = {
                "mp_uid": mp_uid,
                "comision_id": video_info["comision_id"],
                "texto": word.word,
                "fecha": video_info["fecha"],
                "tema": video_info["title"],
                "url_video": video_info["video_url"],
                "inicio_seg": word.start_time.total_seconds(),
                "fin_seg": word.end_time.total_seconds(),
            }
            
    if current_turn:
        speech_turns.append(current_turn)

    if not speech_turns:
        print("  -> ⚠️ No se pudieron construir turnos de habla a partir de la transcripción.")
        return

    cursor = conn.cursor()
    for turn in speech_turns:
        cursor.execute("""
            INSERT INTO speech_turns (mp_uid, comision_id, texto, fecha, tema, url_video, inicio_seg, fin_seg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            turn['mp_uid'], int(turn['comision_id']), turn['texto'], turn['fecha'],
            turn['tema'], turn['url_video'], turn['inicio_seg'], turn['fin_seg']
        ))
    conn.commit()
    print(f"  ✅ Se insertaron {len(speech_turns)} turnos de habla en la base de datos.")


def main():
    """Función principal que orquesta todo el pipeline."""
    try:
        df_videos = pd.read_csv(INPUT_CSV_PATH).dropna(subset=['comision_id', 'fecha'])
    except FileNotFoundError:
        print(f"❌ Error: No se encontró el archivo de manifiesto en '{INPUT_CSV_PATH}'.")
        print("Asegúrate de ejecutar primero 'fetch_playlist.py' y 'link_videos_to_comisiones.py'.")
        return

    for _, video_row in df_videos.iterrows():
        print(f"\n▶️  Procesando video: {video_row['title']}")
        
        audio_path = download_audio(video_row['video_url'], video_row['video_id'])
        if not audio_path: continue

        try:
            gcs_blob = f"transcripts/{os.path.basename(audio_path)}"
            gcs_uri = f"gs://{GCS_BUCKET_NAME}/{gcs_blob}"
            upload_to_gcs(audio_path, gcs_blob)
            
            gcp_response = transcribe_gcs_audio_with_diarization(gcs_uri)
            
            # Construir el texto completo para el LLM
            full_transcript_text = ""
            if gcp_response.results:
                # Agrupar por hablante para dar más contexto al LLM
                speaker_text = {}
                for result in gcp_response.results:
                    for word_info in result.alternatives[0].words:
                        tag = word_info.speaker_tag
                        if tag not in speaker_text:
                            speaker_text[tag] = []
                        speaker_text[tag].append(word_info.word)
                
                for tag, words in sorted(speaker_text.items()):
                    full_transcript_text += f"\nHablante {tag}: {' '.join(words)}\n"
            
            if not full_transcript_text:
                print("  -> ⚠️ La transcripción de GCP está vacía. Saltando al siguiente video.")
                continue

            miembros_df = get_miembros_comision(int(video_row['comision_id']))
            speaker_map = identify_speakers_with_llm(full_transcript_text, miembros_df)
            
            if not speaker_map:
                print("  -> ⚠️ El LLM no pudo identificar a los hablantes. No se cargarán datos para este video.")
                continue

            with sqlite3.connect(DB_PATH) as conn:
                process_and_load_turns(gcp_response, video_row.to_dict(), speaker_map, conn)

        except Exception as e:
            print(f"  ❌ Ocurrió un error general procesando el video {video_row['video_id']}: {e}")
        finally:
            # Limpiar el archivo de audio local después de procesar
            if os.path.exists(audio_path):
                os.remove(audio_path)

    print("\n🎉 --- Proceso de Transcripción y Carga Finalizado --- 🎉")

if __name__ == "__main__":
    main()