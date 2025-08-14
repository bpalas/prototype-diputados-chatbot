# 📜 Documentación del Script ETL: Proyectos de Ley (`etl_bills.py`)

Este documento describe el funcionamiento del script `etl_bills.py`, cuyo propósito es extraer, transformar y cargar toda la información relacionada con los proyectos de ley y sus autores en la base de datos del proyecto.

---

## 🎯 Propósito del Script

El objetivo principal es poblar dos tablas clave del módulo de **Actividad Legislativa**:

1.  **`bills`**: Contiene el registro detallado de cada proyecto de ley, incluyendo su título, resumen, fechas, estado y, si aplica, el número de ley en que se convirtió.
2.  **`bill_authors`**: Tabla de hechos que vincula cada proyecto de ley (`bill_id`) con los parlamentarios (`mp_uid`) que lo propusieron.

---

## ⚙️ Flujo del Proceso ETL

El script sigue una secuencia lógica para asegurar que los datos sean consistentes y completos.

### 1. Extracción (Extract)

El script se conecta a **una única fuente de datos primaria**: la **API de la Cámara de Diputadas y Diputados de Chile**.

* **Paso 1: Obtener Listado de Proyectos por Año**
    * Se itera desde un año de inicio (configurable) hasta el año actual.
    * Para cada año, se llama a dos endpoints de la API para obtener los números de boletín de todas las iniciativas:
        * `retornarMocionesXAnno`: Proyectos de ley iniciados por parlamentarios.
        * `retornarMensajesXAnno`: Proyectos de ley iniciados por el Poder Ejecutivo.
    * Todos los boletines se consolidan en una lista única, eliminando duplicados.

* **Paso 2: Obtener Detalles de Cada Proyecto**
    * Para cada número de boletín único, se realiza una llamada al endpoint `retornarProyectoLey`.
    * De la respuesta XML de este endpoint se extraen todos los metadatos relevantes del proyecto.

### 2. Transformación (Transform)

La transformación es ligera y se realiza al momento de la extracción:

* **Fechas**: Las fechas extraídas en formato `dateTime` (ej: `2023-05-10T10:00:00`) se convierten a formato `YYYY-MM-DD`.
* **Resumen**: Si el campo `<Resumen>` del XML está vacío, se utiliza el contenido del campo `<Nombre>` (título del proyecto) como valor alternativo para asegurar que la columna `resumen` nunca quede vacía.
* **IDs de Autores**: Se extraen los `diputadoid` de los parlamentarios autores para su posterior vinculación.

### 3. Carga (Load)

* **Conexión a la BD**: El script se conecta a la base de datos SQLite `parlamento.db`. **Importante**: Este script no crea las tablas; asume que fueron creadas previamente por `create_database.py`.
* **Inserción en `bills`**:
    * Se utiliza una sentencia `INSERT OR REPLACE`. Esto permite que el script se ejecute múltiples veces, actualizando la información de un proyecto de ley si ha cambiado (ej: cambio de estado, publicación como ley) sin generar errores de clave duplicada.
* **Inserción en `bill_authors`**:
    * Por cada `diputadoid` de autor extraído, primero se busca su `mp_uid` correspondiente en la tabla `dim_parlamentario`.
    * Si se encuentra, se inserta la relación (`bill_id`, `mp_uid`) en `bill_authors` usando `INSERT OR IGNORE` para evitar duplicados.
    * Si no se encuentra (lo cual sería raro si `etl_roster.py` se ejecutó primero), se muestra una advertencia.

---

## 📋 Mapeo de Datos: API (XML) a Base de Datos (SQL)

La siguiente tabla detalla cómo cada campo del XML obtenido de la API se mapea a una columna en la tabla `bills`.

| Campo XML (en `<ProyectoLey>`) | Tabla Destino | Columna Destino         | Lógica de Mapeo y Notas                                                 |
| :----------------------------- | :------------ | :---------------------- | :---------------------------------------------------------------------- |
| `<NumeroBoletin>`              | `bills`       | `bill_id`               | **Clave Primaria**. Identificador único del proyecto.                   |
| `<Nombre>`                     | `bills`       | `titulo`                | Título oficial del proyecto de ley.                                     |
| `<Resumen>`                    | `bills`       | `resumen`               | Idea matriz o resumen. Si está vacío, se usa el `titulo`.               |
| `<FechaIngreso>`               | `bills`       | `fecha_ingreso`         | Fecha de ingreso a tramitación, formateada a `YYYY-MM-DD`.              |
| `<Etapa>`                      | `bills`       | `etapa`                 | Descripción de la fase actual del trámite legislativo.                  |
| `<TipoIniciativa>/<Nombre>`    | `bills`       | `iniciativa`            | Define si es "Moción" (parlamentaria) o "Mensaje" (ejecutivo).          |
| `<CamaraOrigen>/<Nombre>`      | `bills`       | `origen`                | Cámara donde se inició el proyecto (ej: "Cámara de Diputados").         |
| `<UrgenciaActual>`             | `bills`       | `urgencia`              | Tipo de urgencia que tiene el proyecto (ej: "Suma", "Simple").          |
| `<Estado>`                     | `bills`       | `resultado_final`       | El estado actual del proyecto (ej: "En tramitación", "Publicado").      |
| `<Ley>/<Numero>`               | `bills`       | `ley_numero`            | El número de ley asignado si el proyecto fue publicado.                 |
| `<Ley>/<FechaPublicacion>`     | `bills`       | `ley_fecha_publicacion` | Fecha de publicación en el Diario Oficial.                              |
| `<Autores>...<Diputado>/<Id>`  | `bill_authors`| `mp_uid`                | Se itera, se extrae el `diputadoid` y se busca el `mp_uid` para la inserción.|