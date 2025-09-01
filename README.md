# Prototipo de Chatbot sobre Actividad Parlamentaria en Chile

Este proyecto construye y alimenta una base de conocimiento para un chatbot capaz de responder preguntas sobre la actividad parlamentaria en Chile. La información se integra en una base de datos relacional unificada a partir de fuentes públicas (Cámara de Diputadas y Diputados, BCN), y se expone mediante un generador de contexto para tareas RAG (Retrieval-Augmented Generation).

---

## Estado Actual

- Base de datos `SQLite` operativa en `data/database/parlamento.db` (esquema en `data/docs/schema.sql`).
- ETLs funcionales para: roster/partidos, proyectos de ley, votaciones y legislaturas (con caché local de XML).
- Generador de contexto por parlamentario (`src/core/context_builder.py`) listo para exportar a JSON y texto.
- Scripts para videos de comisiones (enlazar títulos a comisiones con heurística + LLM) disponibles.
- App Streamlit experimental (`src/app/digital_twin_app.py`) para un “digital twin” parlamentario.

Cambios recientes:
- Corrección de acentos/strings mal codificados que afectaban consultas y agregados (core/votes).
- Limpieza de `requirements.txt` (se removieron módulos built-in y se añadieron extras opcionales).

---

## Estructura del Repositorio

```
prototype-diputados-chatbot/
├─ data/
│  ├─ database/
│  │  └─ parlamento.db            # Base de datos SQLite
│  ├─ docs/
│  │  └─ schema.sql               # Esquema SQL de la BD
│  ├─ xml/                        # Caché de XML (bills/votes/...)
│  └─ video_processing/           # Manifiestos y cachés de videos
├─ docs/
│  └─ migrations.md               # Notas de migraciones
├─ images/
│  └─ diagram.png                 # Diagrama (referencial)
├─ src/
│  ├─ app/
│  │  └─ digital_twin_app.py      # App Streamlit (experimental)
│  ├─ core/
│  │  └─ context_builder.py       # Generador de contexto por mp_uid
│  ├─ etl/
│  │  ├─ etl_roster.py            # Dimensiones: parlamentarios/partidos/mandatos/militancias
│  │  ├─ etl_bills.py             # Proyectos de ley + autores
│  │  ├─ etl_votes.py             # Sesiones de votación + votos individuales
│  │  ├─ etl_legislaturas.py      # Catálogo de legislaturas
│  │  └─ etl_comisiones.py        # Catálogo de comisiones (si aplica)
│  ├─ scripts/
│  │  ├─ fetch_playlist.py        # Extrae metadata de playlists (YouTube)
│  │  ├─ link_videos_to_comisiones.py  # Enlaza videos ↔ comisiones (regex + LLM)
│  │  ├─ migrate_schema.py        # Script de migración puntual (usar con respaldo)
│  │  └─ process_video_transcripts.py  # Orquesta descargas/transcripción (GCP + LLM)
│  └─ utils/
│     └─ retry.py                 # Decorador de reintentos
├─ create_database.py              # Inicializa BD desde schema.sql
├─ requirements.txt                # Dependencias (núcleo + opcionales)
└─ reports.ipynb                   # Exploración/QA de la BD
```

---

## Base de Datos

- Motor: `SQLite` (`data/database/parlamento.db`).
- Esquema: ver `data/docs/schema.sql`.
- Módulos principales (resumen):
  - CORE: `dim_parlamentario`, `dim_partidos`, `dim_legislatura`.
  - Trayectoria: `parlamentario_mandatos`, `militancia_historial`.
  - Actividad legislativa: `bills`, `bill_authors`, `sesiones_votacion`, `votos_parlamentario`.
  - Actividad pública (planeado): `speech_turns`, `interactions`.

---

## Instalación Rápida

- Requisitos: Python 3.10+ (se recomienda 3.11/3.12) y `pip`.

```bash
# 1) Crear entorno y activar
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2) Instalar dependencias
pip install -r requirements.txt
```

Variables de entorno sugeridas (según scripts a usar):
- `OPENAI_API_KEY` (LLM, linking de videos y algunas tareas de identificación).
- `GOOGLE_APPLICATION_CREDENTIALS` (GCP Speech-to-Text para transcripciones).

---

## Inicializar la BD

```bash
# Crear/limpiar estructura según schema.sql
python create_database.py
```

---

## Pipelines ETL (orden sugerido)

- Roster/Partidos/Militancias/Mandatos: `src/etl/etl_roster.py`
- Proyectos de Ley: `src/etl/etl_bills.py`
- Votaciones: `src/etl/etl_votes.py`
- Legislaturas: `src/etl/etl_legislaturas.py`

Notas:
- Los ETL usan caché local de XML en `data/xml/` para acelerar re-ejecuciones.
- Asegúrate de tener conectividad a los endpoints de la Cámara/BCN.

Ejemplos:
```bash
python src/etl/etl_roster.py
python src/etl/etl_bills.py
python src/etl/etl_votes.py
python src/etl/etl_legislaturas.py
```

---

## Generar Contexto para RAG

El generador construye un contexto consolidado por parlamentario (`mp_uid`) y exporta a JSON y/o texto.

```bash
# JSON (por defecto) o texto o ambos
python src/core/context_builder.py <mp_uid> [json|text|both]

# Ejemplo
python src/core/context_builder.py 1 both
```

Salida por defecto:
- JSON: `data/contexts/context_mp_<mp_uid>_YYYYMMDD_HHMMSS.json`
- Texto: `data/contexts/context_mp_<mp_uid>_YYYYMMDD_HHMMSS.txt`

---

## Enlazar Videos a Comisiones (Opcional, LLM)

`src/scripts/link_videos_to_comisiones.py` toma un manifiesto CSV de videos (YouTube) y vincula cada título con una comisión utilizando heurística regex + LLM (formato JSON estricto).

Requisitos:
- `OPENAI_API_KEY` definido.
- Catálogo `dim_comisiones` presente en la BD.

Parámetros principales:
```bash
python src/scripts/link_videos_to_comisiones.py \
  --db-path data/database/parlamento.db \
  --input-csv data/video_processing/playlists/playlists\ 2025/comisiones_2025.csv \
  --output-csv data/video_processing/playlists/playlists\ 2025/comisiones_2025_enlazado.csv \
  --cache-path data/video_processing/cache_enlaces.json \
  --pending-review-path data/video_processing/playlists/playlists\ 2025/pending_review.csv \
  --skip-llm   # Opcional: solo heurística + caché
```

---

## App Streamlit (Experimental)

`src/app/digital_twin_app.py` incluye una app con un “gemelo digital” parlamentario que usa el contexto generado. Requiere que la BD esté poblada y que el contexto pueda construirse.

```bash
streamlit run src/app/digital_twin_app.py
```

---

## Limitaciones y Pendientes

- Consolas Windows pueden mostrar caracteres raros (acentos) al imprimir; internamente todos los módulos se guardan como UTF‑8.
- `src/scripts/migrate_schema.py` es un script de migración puntual; puede ser destructivo (usa tablas temporales). Úsalo con respaldo de la BD.
- Transcripciones: `process_video_transcripts.py` requiere GCP (bucket y credenciales) y FFmpeg instalado en el sistema.
- El módulo `alias_resolver.py` está vacío/pending; normalización de nombres aún en diseño.

---

## Contacto y Contribución

Sugerencias y PRs son bienvenidos. Si detectas inconsistencias en datos o encoding, abre un issue con ejemplos concretos (mp_uid, tabla, campo) para depurar más rápido.
