
# Documentación del Script ETL: Roster Parlamentario

Este documento detalla el funcionamiento del script ETL (`etl_roster.py`), cuyo propósito es construir y mantener una base de datos actualizada con los perfiles detallados de los parlamentarios chilenos.

El script implementa una robusta estrategia de **"Borrar y Recargar"**. Se conecta a **dos fuentes de datos primarias** para consolidar la información:
1.  **API de la Cámara de Diputadas y Diputados**: Para obtener datos administrativos básicos, de distrito y el historial de militancias.
2.  **SPARQL de la Biblioteca del Congreso Nacional (BCN)**: Para enriquecer los perfiles con datos biográficos, enlaces externos y multimedia.

---
## Flujo del Proceso ETL ⚙️

El script sigue una secuencia lógica de tres fases para garantizar la integridad y actualidad de los datos:

1.  **Extracción (Extract)**:
    * **Datos de la Cámara**: Se realiza una llamada a la API `WSDiputado.asmx` para obtener un archivo XML con la lista de diputados del período actual, incluyendo su información personal y su historial completo de militancias.
    * **Datos de la BCN**: Se ejecuta una consulta SPARQL optimizada contra el endpoint `datos.bcn.cl` para obtener datos adicionales como la URL de la foto, redes sociales, profesión y sitios web, usando el ID de la cámara como punto de conexión.

2.  **Transformación (Transform)**:
    * Los datos de ambas fuentes son cargados en DataFrames de `pandas`.
    * Se realiza una operación de **unión (`merge`)** usando el `diputadoid` como clave común. Esto consolida toda la información de un parlamentario en un único registro.

3.  **Carga (Load)**:
    * **Preparación de la BD**: El script se conecta a la base de datos SQLite y primero se asegura de que toda la estructura de tablas e índices exista (usando sentencias `CREATE TABLE IF NOT EXISTS`).
    * **Limpieza de Datos**: Se ejecutan sentencias `DELETE` sobre las tablas `dim_parlamentario`, `dim_partidos` y `militancia_historial` para vaciarlas por completo. Esto evita la duplicación de datos y asegura que la información refleje fielmente el estado actual de las fuentes.
    * **Inserción de Datos**: Se recorre el DataFrame final y se insertan los registros limpios y consolidados en las tablas correspondientes.

---
## Detalle de Tablas Pobladas

A continuación se describe el propósito y el origen de los datos para cada tabla que este script alimenta.

### **1. Tabla: `dim_parlamentario` 👑**

Es la **tabla maestra** que contiene el perfil unificado y enriquecido de cada parlamentario.

* **Propósito**: Crear un registro único por diputado, generando una clave primaria (`mp_uid`) que servirá como ancla para todas las demás tablas relacionales.
* **Campos Rellenados y Origen de Datos**:
    * `mp_uid`: **(BD)** Se genera automáticamente por la base de datos (`AUTOINCREMENT`).
    * `diputadoid`: **(Cámara)** ID oficial del parlamentario en la API de la Cámara. Es la clave para el merge.
    * `nombre_completo`: **(Cámara)** Concatenación de nombre y apellidos.
    * `apellido_materno`: **(Cámara)** Extraído directamente del XML.
    * `genero`: **(Cámara)** Determinado a partir de la etiqueta `<Sexo>`.
    * `distrito`: **(Cámara)** Número del distrito que representa.
    * `bcn_uri`: **(BCN)** URL única del perfil del parlamentario en `datos.bcn.cl`.
    * `url_foto`: **(BCN)** Enlace directo a la fotografía oficial del parlamentario.
    * `twitter_handle`: **(BCN)** Nombre de usuario de Twitter (sin el "@").
    * `sitio_web_personal`: **(BCN)** Enlace al sitio web o blog oficial.
    * `titulo_honorifico`: **(BCN)** Prefijo honorífico (ej. "Honorable Diputado").
    * `profesion`: **(BCN)** Profesión o título profesional del parlamentario.
    * `nacionalidad`: **(BCN)** URI que representa la nacionalidad (ej. `http://datos.bcn.cl/recurso/pais/chile`).
    * `url_historia_politica`: **(BCN)** Enlace a la reseña biográfica detallada en el sitio de Historia Política de la BCN.

---
### **2. Tabla: `dim_partidos` 🏛️**

Es una **tabla de dimensión** que normaliza los nombres de los partidos políticos, asegurando que cada uno exista solo una vez.

* **Propósito**: Evitar la redundancia y mantener un listado único de todos los partidos políticos históricos y actuales mencionados en las militancias.
* **Campos Rellenados y Origen de Datos**:
    * `partido_id`: **(BD)** Se genera automáticamente la primera vez que se encuentra un partido. En cargas posteriores, se reutiliza el ID existente.
    * `nombre_partido`: **(Cámara)** Extraído del historial de militancias de cada diputado. La lógica `INSERT OR IGNORE` previene duplicados.
    * **Campos no rellenados**: `sigla`, `fecha_fundacion` y `sitio_web` quedan en `NULL` para ser poblados por otros procesos.

---
### **3. Tabla: `militancia_historial` 📜**

Esta tabla de hechos es **crucial** para el análisis político, ya que registra la trayectoria de afiliaciones de cada parlamentario a lo largo del tiempo.

* **Propósito**: Mapear la relación histórica y actual entre un parlamentario (`mp_uid`) y un partido político (`partido_id`).
* **Campos Rellenados y Origen de Datos**:
    * `militancia_id`: **(BD)** Clave primaria autoincremental.
    * `mp_uid`: **(Clave Foránea)** Referencia al `mp_uid` del parlamentario recién insertado en `dim_parlamentario`.
    * `partido_id`: **(Clave Foránea)** Referencia al `partido_id` correspondiente de la tabla `dim_partidos`.
    * `fecha_inicio`: **(Cámara)** Fecha de inicio de la afiliación.
    * `fecha_fin`: **(Cámara)** Fecha de término de la afiliación. Se guarda como `NULL` si la militancia está vigente.
    * **Campos no rellenados**: `coalicion_id` queda en `NULL`.

---
### Tablas No Afectadas por este Script 🚫

Este script está altamente especializado en el "Roster Parlamentario". Las siguientes tablas definidas en el esquema **NO son modificadas** y dependen de sus propios procesos ETL para ser pobladas:

* `parlamentario_aliases`
* `dim_coaliciones`
* `electoral_results`
* Y cualquier otra tabla relacionada con votaciones, proyectos de ley, comisiones, etc.