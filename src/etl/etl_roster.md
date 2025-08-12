
# Documentación del Script ETL: Roster Parlamentario y Partidos

Este documento detalla el funcionamiento del script ETL (`etl_roster.py`), cuyo propósito es construir y mantener una base de datos actualizada con los perfiles detallados de los parlamentarios y partidos políticos chilenos.

El script implementa una robusta estrategia de **"Borrar y Recargar"**. Se conecta a **dos fuentes de datos primarias** para consolidar la información:
1.  **API de la Cámara de Diputadas y Diputados**: Para obtener datos administrativos básicos, de distrito y el historial de militancias.
2.  **SPARQL de la Biblioteca del Congreso Nacional (BCN)**: Para enriquecer los perfiles biográficos de los parlamentarios y obtener un catálogo completo y detallado de los partidos políticos.

---
## Flujo del Proceso ETL ⚙️

El script sigue una secuencia lógica de tres fases para garantizar la integridad y actualidad de los datos:

1.  **Extracción (Extract)**:
    * **Datos de la Cámara**: Se realiza una llamada a la API `WSDiputado.asmx` para obtener un archivo XML con la lista de diputados del período actual, incluyendo su información personal y su historial completo de militancias.
    * **Datos Biográficos (BCN)**: Se ejecuta una consulta SPARQL optimizada contra el endpoint `datos.bcn.cl` para obtener datos adicionales para cada parlamentario, como la URL de la foto, redes sociales, profesión y fecha de nacimiento, usando el ID de la cámara como punto de conexión.
    * **[CAMBIO]** **Datos de Partidos Políticos (BCN)**: Se ejecuta una segunda consulta SPARQL dedicada a obtener un listado completo y enriquecido de todos los partidos políticos. Esta consulta extrae siglas, fechas de fundación, logos, sitios web y más.

2.  **Transformación (Transform)**:
    * Los datos de todas las fuentes son cargados en DataFrames de `pandas`.
    * Se realiza una operación de **unión (`merge`)** entre los datos de la Cámara y los datos biográficos de la BCN, usando el `diputadoid` como clave común. Esto consolida toda la información de un parlamentario en un único registro.

3.  **Carga (Load)**:
    * **Preparación de la BD**: El script se conecta a la base de datos SQLite y primero se asegura de que toda la estructura de tablas e índices exista (usando sentencias `CREATE TABLE IF NOT EXISTS`).
    * **Limpieza de Datos**: Se ejecutan sentencias `DELETE` sobre las tablas `dim_parlamentario`, `dim_partidos` y `militancia_historial` para vaciarlas por completo. Esto evita la duplicación de datos y asegura que la información refleje fielmente el estado actual de las fuentes.
    * **Inserción de Datos**: Se recorre el DataFrame final y se insertan los registros limpios y consolidados en las tablas correspondientes. Primero se puebla `dim_partidos` y luego `dim_parlamentario` y `militancia_historial`.

---
## Detalle de Tablas Pobladas

A continuación se describe el propósito y el origen de los datos para cada tabla que este script alimenta.

### **1. Tabla: `dim_parlamentario` 👑**

Es la **tabla maestra** que contiene el perfil unificado y enriquecido de cada parlamentario.

* **Propósito**: Crear un registro único por diputado, generando una clave primaria (`mp_uid`) que servirá como ancla para todas las demás tablas relacionales.
* **Campos Rellenados y Origen de Datos**:
    * `mp_uid`: **(BD)** Generado automáticamente (`AUTOINCREMENT`).
    * `diputadoid`: **(Cámara)** ID oficial. Es la clave para el merge.
    * `nombre_completo`: **(Cámara)** Concatenación de nombre y apellidos.
    * **[CAMBIO]** `nombre_propio`: **(BCN)** Nombre de pila del parlamentario.
    * **[CAMBIO]** `apellido_paterno`: **(BCN)** Apellido paterno del parlamentario.
    * `apellido_materno`: **(BCN / Cámara)** Se prioriza el dato de la BCN; si no existe, se usa el de la Cámara.
    * `genero`: **(Cámara)** Determinado a partir de la etiqueta `<Sexo>`.
    * **[CAMBIO]** `fecha_nacimiento`: **(BCN)** Fecha de nacimiento en formato `YYYY-MM-DD`.
    * **[CAMBIO]** `lugar_nacimiento`: **(BCN)** Comuna o ciudad de nacimiento.
    * `distrito`: **(Cámara)** Número del distrito que representa.
    * `bcn_uri`: **(BCN)** URL única del perfil del parlamentario en `datos.bcn.cl`.
    * `url_foto`: **(BCN)** Enlace directo a la fotografía oficial.
    * `twitter_handle`: **(BCN)** Nombre de usuario de Twitter (sin el "@").
    * `sitio_web_personal`: **(BCN)** Enlace al sitio web o blog oficial.
    * `titulo_honorifico`: **(BCN)** Prefijo honorífico (ej. "Honorable Diputado").
    * `profesion`: **(BCN)** Profesión o título profesional del parlamentario.
    * `nacionalidad`: **(BCN)** URI que representa la nacionalidad.
    * `url_historia_politica`: **(BCN)** Enlace a la reseña biográfica detallada en el sitio de Historia Política de la BCN.

---
### **2. Tabla: `dim_partidos` 🏛️**

**[CAMBIO]** Es una **tabla de dimensión enriquecida**, poblada directamente desde la BCN para crear un catálogo maestro de partidos políticos.

* **Propósito**: Mantener un listado único, detallado y centralizado de todos los partidos políticos, sirviendo como la fuente de verdad para esta entidad.
* **Campos Rellenados y Origen de Datos**:
    * `partido_id`: **(BD)** Se genera automáticamente.
    * `nombre_partido`: **(BCN)** Nombre oficial y completo del partido (ej. "Partido Unión Demócrata Independiente").
    * `nombre_alternativo`: **(BCN)** Nombres secundarios o más comunes (ej. "Unión Demócrata Independiente").
    * `sigla`: **(BCN)** Acrónimo oficial del partido (ej. "UDI").
    * `fecha_fundacion`: **(BCN)** Año de fundación del partido.
    * `sitio_web`: **(BCN)** URL de la página principal del partido.
    * `url_historia_politica`: **(BCN)** Enlace a la página del partido en la Historia Política de la BCN.
    * `url_logo`: **(BCN)** Enlace directo a la imagen del logo del partido.
    * `ultima_actualizacion`: **(BCN)** Fecha y hora de la última modificación del registro en la BCN.

---
### **3. Tabla: `militancia_historial` 📜**

Esta tabla de hechos es **crucial** para el análisis político, ya que registra la trayectoria de afiliaciones de cada parlamentario a lo largo del tiempo.

* **Propósito**: Mapear la relación histórica y actual entre un parlamentario (`mp_uid`) y un partido político (`partido_id`).
* **Campos Rellenados y Origen de Datos**:
    * `militancia_id`: **(BD)** Clave primaria autoincremental.
    * `mp_uid`: **(Clave Foránea)** Referencia al `mp_uid` del parlamentario recién insertado.
    * `partido_id`: **(Clave Foránea)** Referencia al `partido_id` correspondiente de la tabla `dim_partidos`, ahora enriquecida por la BCN.
    * `fecha_inicio`: **(Cámara)** Fecha de inicio de la afiliación.
    * `fecha_fin`: **(Cámara)** Fecha de término de la afiliación. Se guarda como `NULL` si la militancia está vigente.
    * **Campos no rellenados**: `coalicion_id` queda en `NULL`.

---
### Tablas No Afectadas por este Script 🚫

Este script está altamente especializado en el "Roster Parlamentario" y el "Catálogo de Partidos". Las siguientes tablas definidas en el esquema **NO son modificadas** y dependen de sus propios procesos ETL para ser pobladas:

* `parlamentario_aliases`
* `dim_coaliciones`
* `electoral_results`
* `bills`
* `votes`
* Y cualquier otra tabla relacionada con votaciones, proyectos de ley, comisiones, etc.