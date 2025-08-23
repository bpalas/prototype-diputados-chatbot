# 📜 Documentación del Script ETL: Proyectos de Ley (`etl_bills.py`)

Este documento describe el funcionamiento del script `etl_bills.py`, cuyo propósito es extraer, transformar y cargar la información relacionada con los proyectos de ley y sus autores en la base de datos del proyecto.

---

## 🎯 Propósito del Script

El objetivo principal es poblar dos tablas clave para el análisis de la **Actividad Legislativa**, creando un registro histórico y detallado de las iniciativas discutidas en el Congreso.

---

## 📊 Tablas de la Base de Datos Pobladas

El script interactúa y carga datos en las siguientes dos tablas:

### Tabla: `bills`

Esta es la **tabla principal o maestra** de los proyectos de ley. Cada fila representa un único proyecto de ley con toda su información descriptiva.

* **Propósito**: Almacenar los metadatos y el estado de cada iniciativa legislativa.
* **Clave Primaria**: `bill_id` (el número de boletín).
* **Columnas Principales**:
    * `bill_id`: Identificador único del proyecto (ej: "16393-07").
    * `titulo`: Nombre oficial del proyecto de ley.
    * `resumen`: Idea matriz o descripción.
    * `fecha_ingreso`: Fecha de inicio de la tramitación.
    * `etapa`: Fase actual del trámite (ej: "Primer trámite constitucional").
    * `iniciativa`: Origen ("Moción" o "Mensaje").
    * `origen`: Cámara donde se inició el proyecto.
    * `urgencia`: Nivel de urgencia actual (ej: "Suma", "Simple").
    * `resultado_final`: Estado final (ej: "Publicado", "Rechazado", "En tramitación").
    * `ley_numero`: Número de ley asignado si fue aprobado y publicado.
    * `ley_fecha_publicacion`: Fecha de publicación en el Diario Oficial.

### Tabla: `bill_authors`

Esta es una **tabla de hechos o de enlace** que conecta los proyectos de ley con sus autores parlamentarios.

* **Propósito**: Registrar la autoría de las mociones parlamentarias, creando una relación de muchos a muchos (un proyecto puede tener varios autores y un parlamentario puede ser autor de varios proyectos).
* **Clave Primaria**: Compuesta por (`bill_id`, `mp_uid`).
* **Columnas Principales**:
    * `bill_id`: **Clave foránea** que se conecta con `bills.bill_id`.
    * `mp_uid`: **Clave foránea** que se conecta con `dim_parlamentario.mp_uid`.

---

## ✨ Características Principales

Antes de detallar el flujo, es importante destacar dos características de diseño del script:

* **Caché Local de XML 💾**: Para cada proyecto de ley, el script guarda la respuesta XML de la API en un archivo local (`/data/xml/bills/{bill_id}.xml`). En ejecuciones posteriores, el script lee este archivo en lugar de consultar la API nuevamente. Esto **acelera drásticamente el proceso** y **evita bloqueos** por exceso de peticiones a la API.
* **Idempotencia ✅**: El script está diseñado para ser re-ejecutable. Gracias al uso de `INSERT OR REPLACE` y `INSERT OR IGNORE`, ejecutarlo varias veces no genera datos duplicados, sino que **actualiza los registros existentes** si hay cambios (por ejemplo, si un proyecto avanza de etapa).

---

## ⚙️ Flujo del Proceso ETL

El script sigue una secuencia lógica para asegurar que los datos sean consistentes y completos.

### 1. Extracción (Extract)

El script se conecta a una única fuente de datos: la **API de la Cámara de Diputadas y Diputados de Chile**.

* **Paso 1: Obtener Listado de Proyectos por Año**
    * El script se ejecuta para un año de inicio específico, definido en la variable `START_YEAR`.
    * Para ese año, llama a dos endpoints de la API para obtener los números de boletín de todas las iniciativas:
        * `retornarMocionesXAnno`: Proyectos iniciados por parlamentarios.
        * `retornarMensajesXAnno`: Proyectos iniciados por el Poder Ejecutivo.
    * Todos los boletines se consolidan en una lista única, eliminando duplicados.

* **Paso 2: Obtener Detalles de Cada Proyecto (Usando Caché)**
    * Para cada número de boletín, el script primero **verifica si existe un archivo XML local**.
    * **Si existe**, lee los datos directamente del disco.
    * **Si no existe**, realiza la llamada al endpoint `retornarProyectoLey`, extrae los metadatos del proyecto y **guarda el XML localmente** para futuras ejecuciones.

### 2. Transformación (Transform)

La transformación es ligera y se realiza al momento de parsear el XML:

* **Fechas**: Las fechas extraídas en formato `dateTime` (ej: `2023-05-10T10:00:00`) se convierten a formato `YYYY-MM-DD`.
* **Resumen**: Si el campo `<Resumen>` del XML está vacío, se utiliza el contenido del campo `<Nombre>` (título del proyecto) como valor alternativo para asegurar que la columna `resumen` nunca quede vacía.
* **IDs de Autores**: Se extraen los `diputadoid` de los parlamentarios autores para su posterior vinculación.

### 3. Carga (Load)

* **Conexión a la BD**: El script se conecta a la base de datos SQLite `parlamento.db`. **Importante**: Este script no crea las tablas; asume que fueron creadas previamente por `create_database.py`.
* **Inserción en `bills`**:
    * Se utiliza `INSERT OR REPLACE`. Esto permite actualizar la información de un proyecto si ha cambiado (ej: cambio de estado, publicación como ley) sin generar errores.
* **Inserción en `bill_authors`**:
    * Por cada `diputadoid` de autor, primero se busca su `mp_uid` correspondiente en `dim_parlamentario`.
    * Si se encuentra, se inserta la relación (`bill_id`, `mp_uid`) en `bill_authors` usando `INSERT OR IGNORE` para evitar duplicados.
    * Si no se encuentra (lo cual es poco probable si `etl_roster.py` está actualizado), se muestra una advertencia en la consola.

---

## 📋 Mapeo de Datos: API (XML) a Base de Datos (SQL)

La siguiente tabla detalla cómo cada campo del XML se mapea a una columna en la tabla `bills`.

| Campo XML (en `<ProyectoLey>`) | Tabla Destino | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- | :--- |
| `<NumeroBoletin>` | `bills` | `bill_id` | **Clave Primaria**. Identificador único del proyecto. |
| `<Nombre>` | `bills` | `titulo` | Título oficial del proyecto de ley. |
| `<Resumen>` | `bills` | `resumen` | Idea matriz o resumen. Si está vacío, se usa el `titulo`. |
| `<FechaIngreso>` | `bills` | `fecha_ingreso` | Fecha de ingreso a tramitación, formateada a `YYYY-MM-DD`. |
| `<Etapa>` | `bills` | `etapa` | Descripción de la fase actual del trámite legislativo. |
| `<TipoIniciativa>/<Nombre>` | `bills` | `iniciativa` | Define si es "Moción" (parlamentaria) o "Mensaje" (ejecutivo). |
| `<CamaraOrigen>/<Nombre>` | `bills` | `origen` | Cámara donde se inició el proyecto (ej: "Cámara de Diputados"). |
| `<UrgenciaActual>` | `bills` | `urgencia` | Tipo de urgencia que tiene el proyecto (ej: "Suma", "Simple"). |
| `<Estado>` | `bills` | `resultado_final` | El estado actual del proyecto (ej: "En tramitación", "Publicado"). |
| `<Ley>/<Numero>` | `bills` | `ley_numero` | El número de ley asignado si el proyecto fue publicado. |
| `<Ley>/<FechaPublicacion>` | `bills` | `ley_fecha_publicacion` | Fecha de publicación en el Diario Oficial. |
| `<Autores>...<Diputado>/<Id>` | `bill_authors` | `mp_uid` | Se itera, se extrae el `diputadoid` y se busca el `mp_uid` para la inserción.|