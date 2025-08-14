
# Documentación del Script ETL: Roster Parlamentario (v3.0)

Este documento detalla el funcionamiento del script ETL (`etl_roster.py`), cuyo propósito es construir y mantener una base de datos actualizada con los perfiles detallados, mandatos y militancias de los parlamentarios, así como el catálogo de partidos políticos chilenos.

El script implementa una robusta estrategia de **"Borrar y Recargar"** y se conecta a **dos fuentes de datos primarias**:

1.  **API de la Cámara de Diputadas y Diputados**: Para obtener la lista de parlamentarios del período, sus datos de mandato (distrito, fechas) y el historial de militancias.
2.  **SPARQL de la Biblioteca del Congreso Nacional (BCN)**: Para enriquecer los perfiles biográficos de los parlamentarios y obtener un catálogo completo y detallado de los partidos políticos.

---

## Flujo del Proceso ETL ⚙️

El script sigue una secuencia lógica de tres fases para garantizar la integridad y actualidad de los datos:

1.  **Extracción (Extract)**:
    * **Datos de la Cámara**: Se realiza una llamada a la API `WSDiputado.asmx` para obtener un archivo XML con la lista de diputados del período actual, incluyendo su información personal, datos del mandato y su historial completo de militancias.
    * **Datos Biográficos (BCN)**: Se ejecuta una consulta SPARQL optimizada contra el endpoint `datos.bcn.cl` para obtener datos biográficos para cada parlamentario, como la URL de la foto, redes sociales, profesión y fecha de nacimiento.
    * **Datos de Partidos Políticos (BCN)**: Se ejecuta una segunda consulta SPARQL dedicada a obtener un listado completo y enriquecido de todos los partidos políticos.

2.  **Transformación (Transform)**:
    * Los datos de todas las fuentes son cargados en DataFrames de `pandas`.
    * Se realiza una operación de **unión (`merge`)** entre los datos de la Cámara y los datos biográficos de la BCN, usando el `diputadoid` como clave común para consolidar la información.

3.  **Carga (Load)**:
    * **Conexión a la BD**: El script se conecta a la base de datos SQLite existente. **Nota**: Este script ya no crea las tablas; asume que la estructura fue creada previamente por `create_database.py`.
    * **Limpieza de Datos**: Se ejecutan sentencias `DELETE` sobre las tablas `dim_parlamentario`, `dim_partidos`, `militancia_historial` y la nueva `parlamentario_mandatos` para vaciarlas por completo.
    * **Inserción de Datos**: Se recorren los datos consolidados y se insertan en las tablas correspondientes del nuevo esquema v3.0, poblando de forma separada los perfiles, mandatos y militancias.

---

## Detalle de Tablas Pobladas por este Script

### **1. Tabla: `dim_parlamentario` 👑**

Es la **tabla maestra** que contiene el perfil biográfico y estático de cada parlamentario.

* **Propósito**: Crear un registro único por diputado, generando una clave (`mp_uid`) que servirá como ancla para todas las demás tablas.
* **Campos Rellenados y Origen de Datos**:
    * `mp_uid`: **(BD)** Generado automáticamente.
    * `diputadoid`: **(Cámara)** ID oficial. Es la clave para el merge.
    * `nombre_completo`, `nombre_propio`, `apellido_paterno`, `apellido_materno`: **(Cámara/BCN)** Nombres y apellidos consolidados.
    * `genero`: **(Cámara)** Determinado a partir de la etiqueta `<Sexo>`.
    * `fecha_nacimiento`, `lugar_nacimiento`: **(BCN)** Datos biográficos.
    * `bcn_uri`, `url_foto`, `twitter_handle`, `sitio_web_personal`, `profesion`, `url_historia_politica`: **(BCN)** Enlaces y datos de perfil enriquecidos.

---

### **2. Tabla: `dim_partidos` 🏛️**

Tabla de dimensión enriquecida, poblada desde la BCN para crear un catálogo maestro de partidos.

* **Propósito**: Mantener un listado único y centralizado de todos los partidos políticos.
* **Campos Rellenados y Origen de Datos**:
    * `partido_id`: **(BD)** Generado automáticamente.
    * Todos los demás campos (`nombre_partido`, `sigla`, `fecha_fundacion`, etc.) son extraídos de la **BCN**.

---

### **3. Tabla: `parlamentario_mandatos` 👔 (NUEVA)**

Esta tabla de hechos registra cada período legislativo que ha servido un parlamentario.

* **Propósito**: Almacenar de forma normalizada los cargos ocupados, permitiendo consultas históricas precisas.
* **Campos Rellenados y Origen de Datos**:
    * `mandato_id`: **(BD)** Clave primaria autoincremental.
    * `mp_uid`: **(Clave Foránea)** Referencia al `mp_uid` del parlamentario.
    * `cargo`: **(Fijo)** Se establece como "Diputado".
    * `distrito`: **(Cámara)** Número del distrito que representa.
    * `fecha_inicio`, `fecha_fin`: **(Cámara)** Fechas de inicio y término del período.

---

### **4. Tabla: `militancia_historial` 📜**

Registra la trayectoria de afiliaciones políticas de cada parlamentario.

* **Propósito**: Mapear la relación histórica y actual entre un parlamentario (`mp_uid`) y un partido político (`partido_id`).
* **Campos Rellenados y Origen de Datos**:
    * `militancia_id`: **(BD)** Clave primaria autoincremental.
    * `mp_uid`: **(Clave Foránea)** Referencia al parlamentario.
    * `partido_id`: **(Clave Foránea)** Referencia al partido político.
    * `fecha_inicio`, `fecha_fin`: **(Cámara)** Fechas de inicio y término de la afiliación.

---

### Tablas No Afectadas por este Script 🚫

Este script está altamente especializado en el "Roster Parlamentario". Las siguientes tablas definidas en el esquema **NO son modificadas** y dependen de sus propios procesos ETL:

* `parlamentario_aliases`
* `dim_coaliciones`
* `dim_comisiones`
* `electoral_results`, `educacion`, `comision_membresias`
* Todas las tablas de los módulos de `ACTIVIDAD LEGISLATIVA` y `ACTIVIDAD PÚBLICA` (`bills`, `votes_parlamentario`, `speech_turns`, etc.).