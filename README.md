
# Prototipo de Chatbot sobre Actividad Parlamentaria en Chile

Este proyecto tiene como objetivo construir y alimentar un sistema de chatbot capaz de responder preguntas complejas sobre la actividad de los diputados y diputadas de Chile. Para lograrlo, se ha diseñado un proceso automatizado que extrae, unifica y estructura datos de múltiples fuentes públicas: el Congreso, la prensa y transcripciones de video.

El núcleo del sistema es una base de datos relacional que integra toda la información bajo un identificador único por parlamentario (`mp_uid`), permitiendo cruzar datos de votaciones, discursos e interacciones políticas. Este repositorio de datos unificados sirve como la base de conocimiento para un chatbot con capacidades de **RAG (Retrieval-Augmented Generation)**, que podrá ofrecer a los usuarios una visión completa y detallada del comportamiento legislativo.

-----

## Flujo del Proyecto

El proceso se puede resumir en los siguientes pasos clave:

1.  **Extracción y Transformación (ETL)**: Scripts automatizados recolectan datos desde diversas fuentes: APIs del Congreso, canales de YouTube y medios de prensa.
2.  **Normalización de Nombres**: Un módulo especializado (`alias_resolver.py`) se encarga de identificar y estandarizar los nombres de los parlamentarios, que a menudo aparecen con alias o variaciones, y los asocia a su `mp_uid` único.
3.  **Carga en Base de Datos**: Los datos limpios y estructurados se cargan en una base de datos SQL, siguiendo un esquema relacional diseñado para garantizar la integridad y consistencia de la información.
4.  **Alimentación del Chatbot**: La base de datos consolidada se utiliza para generar representaciones vectoriales y grafos de conocimiento que alimentan al modelo de lenguaje del chatbot, permitiéndole responder consultas complejas de manera precisa.

-----

## Estructura del Directorio

El proyecto está organizado en la siguiente estructura de carpetas y archivos, diseñada para separar la lógica de extracción de datos, el código fuente principal y las pruebas.

```
proyecto-diputados-chatbot/
│
├── .gitignore
├── README.md           # Esta documentación principal.
├── requirements.txt    # Dependencias del proyecto (pandas, sqlalchemy, etc.).
├── Makefile            # Comandos para automatizar tareas (ej: 'make etl').
│
├── data/
│   └── database/
│       └── parlamento.db # Base de datos SQLite generada por los scripts.
│   └── docs/
│       └── schema.sql    # Definición formal del esquema de la base de datos.
│
├── src/
│   ├── etl/
│   │   ├── etl_roster.py       # Script para poblar la tabla `dim_parlamentario`.
│   │   ├── etl_votes.py        # Script para poblar las tablas `votes` y `bills`.
│   │   ├── etl_transcripts.py  # Script para procesar y cargar discursos de YouTube.
│   │   └── etl_news_graph.py   # Script para extraer y cargar interacciones desde prensa.
│   │
│   ├── core/
│   │   └── alias_resolver.py   # Módulo central para la normalización de nombres.
│   │
│   └── app/
│       └── app.py            # Código de la aplicación web del chatbot (Streamlit).
│
└── tests/
    └── test_alias_resolver.py # Pruebas unitarias para el normalizador de nombres.
```

-----

## Base de Datos

El corazón del proyecto es la base de datos `parlamento.db`, una base de datos SQLite diseñada para centralizar toda la información. Su estructura se define en `data/docs/schema.sql` y se compone de las siguientes tablas:

### Tablas Principales

  * **`dim_parlamentario`**: Es la tabla maestra que contiene los metadatos de cada parlamentario. Funciona como el eje central del sistema, y cada diputado/a tiene un `mp_uid` único. Los datos se extraen de la API oficial de la Cámara de Diputados.

  * **`bills`**: Almacena la información de cada proyecto de ley, incluyendo su identificador (`bill_id`), un resumen, sus autores y el resultado final.

  * **`votes`**: Registra cada voto individual de un parlamentario en un proyecto de ley. Se conecta con `dim_parlamentario` a través de `mp_uid` y con `bills` a través de `bill_id`. Esta tabla es clave para analizar el comportamiento legislativo y el posicionamiento ideológico.

  * **`speech_turns`**: Contiene las transcripciones de las intervenciones de los parlamentarios en las comisiones legislativas, extraídas de YouTube. Cada entrada incluye el texto del discurso, timestamps, la comisión y el tema, vinculada al orador mediante `mp_uid`.

  * **`interactions`**: Modela una red de interacciones políticas (ej. "A criticó a B") extraídas de fuentes de prensa. Esta tabla funciona como un grafo dirigido, donde `source_uid` y `target_uid` son ambos `mp_uid` de los parlamentarios involucrados.

### Relaciones Clave

El diseño se basa en el **`mp_uid` como clave foránea** en las tablas `votes`, `speech_turns` e `interactions`, lo que permite unificar todas las fuentes de datos y realizar consultas cruzadas complejas. Por ejemplo, se puede preguntar: "*¿Qué dijo el diputado X sobre el proyecto de ley Y, y cómo votó finalmente?*".

-----

## Descripción de los Módulos

### Scripts ETL (`src/etl/`)

Estos scripts son responsables de la recolección y procesamiento de los datos:

  * `etl_roster.py`: Se conecta a la API de la Cámara para obtener la lista actualizada de diputados y llena la tabla `dim_parlamentario`.
  * `etl_votes.py`: Descarga las votaciones nominales y los metadatos de los proyectos de ley para poblar las tablas `votes` y `bills`.
  * `etl_transcripts.py`: Automatiza la descarga de audio desde YouTube, realiza la transcripción y diarización (identificación de hablantes) usando herramientas como Whisper, y carga los turnos de palabra en `speech_turns`.
  * `etl_news_graph.py`: Utiliza un modelo de lenguaje (LLM) para analizar noticias y extraer relaciones entre parlamentarios, las cuales se almacenan en la tabla `interactions`.

### Módulo de Normalización (`src/core/`)

  * `alias_resolver.py`: Este es un componente crítico que implementa la lógica para resolver diferentes variantes de nombres de un parlamentario (ej. "Juan Pérez", "diputado Pérez", "J. Pérez") y mapearlas a un único `mp_uid`. Se requiere que este módulo alcance una alta precisión para asegurar la calidad de los datos unificados. Su rendimiento se valida mediante las pruebas en `tests/test_alias_resolver.py`.
