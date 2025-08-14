# 🗳️ Documentación del Script ETL: Votaciones (`etl_votes.py`)

Este documento describe el funcionamiento del script `etl_votes.py`, responsable de poblar las tablas relacionadas con las votaciones parlamentarias. Es el tercer script clave en la secuencia de ejecución, después de `etl_roster.py` y `etl_bills.py`.

---

## 🎯 Propósito del Script

El objetivo es construir un registro detallado de la actividad de votación en el Congreso, poblando dos tablas interconectadas del módulo de **Actividad Legislativa**:

1.  **`sesiones_votacion`**: Actúa como la tabla principal de este ETL. Almacena los metadatos de cada sesión de votación, como la fecha, el tema, el quórum y los resultados totales.
2.  **`votos_parlamentario`**: Es la tabla de hechos que registra cada voto individual. Vincula a un parlamentario (`mp_uid`) con una sesión de votación específica (`sesion_votacion_id`) y su decisión (`voto`).

Este script depende críticamente de que las tablas `dim_parlamentario` y `bills` ya estén pobladas.

---

## ⚙️ Flujo del Proceso ETL

### 1. Extracción (Extract)

* **Paso 1: Obtener Proyectos de Ley Locales**
    * El script se conecta a la base de datos local (`parlamento.db`) y **lee todos los `bill_id`** de la tabla `bills`. Esto asegura que solo se busquen votaciones para los proyectos de ley que ya han sido procesados.
    * **En modo de prueba**, se aplica un `LIMIT` a esta consulta para procesar solo un subconjunto pequeño de proyectos.

* **Paso 2: Obtener IDs de Votaciones por Proyecto**
    * Para cada `bill_id`, se consulta el endpoint `retornarVotacionesXProyectoLey` de la API de la Cámara para obtener una lista de todos los IDs de votaciones asociados a ese proyecto.

* **Paso 3: Obtener Detalles de Cada Votación**
    * Para cada ID de votación obtenido, se realiza una llamada al endpoint `retornarVotacionDetalle` para obtener el XML completo con toda la información de esa sesión, incluyendo los votos individuales de cada parlamentario.

### 2. Transformación (Transform)

La transformación de datos es un paso crucial en este script para asegurar la integridad y consistencia:

* **Extracción de `bill_id`**: El `bill_id` (boletín) se extrae usando una **expresión regular** desde el campo de texto `<Descripcion>` de la votación. Este paso es fundamental para poder vincular la sesión de votación con la tabla `bills`.
* **Normalización del Voto**: El texto del voto (ej. "Afirmativo", "Dispensado") se normaliza a los valores permitidos por el esquema de la base de datos (ej. "A Favor", "Pareo") para mantener la consistencia.
* **Fechas**: Se extrae y formatea la fecha de la votación al formato `YYYY-MM-DD`.

### 3. Carga (Load)

El proceso de carga se realiza en dos etapas por cada votación procesada:

* **Paso 1: Cargar en `sesiones_votacion`**
    * Se utiliza una sentencia `INSERT OR REPLACE` para insertar o actualizar el registro de la sesión de votación. Se usa el ID de la votación proporcionado por la API como clave primaria (`sesion_votacion_id`).

* **Paso 2: Cargar en `votos_parlamentario`**
    * Se itera sobre la lista de votos individuales del XML.
    * Por cada voto, se busca el `mp_uid` del parlamentario en `dim_parlamentario` usando su `diputadoid`.
    * Se inserta la fila (`sesion_votacion_id`, `mp_uid`, `voto`) en la tabla `votos_parlamentario` usando `INSERT OR IGNORE` para prevenir duplicados.

---

## 📋 Mapeo de Datos: API (XML) a Base de Datos (SQL)

### Tabla: `sesiones_votacion`

| Campo XML (en `<Votacion>`) | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- |
| `<Id>` | `sesion_votacion_id` | **Clave Primaria**. Se usa directamente el ID de la votación de la API. |
| `<Descripcion>` | `bill_id` | **Clave Foránea**. Se extrae el número de boletín (ej. `1234-56`) del texto. |
| `<Fecha>` | `fecha` | Se extrae y formatea a `YYYY-MM-DD`. |
| `<Descripcion>` | `tema` | Se guarda el texto completo de la descripción como el tema de la votación. |
| `<Resultado>` | `resultado_general` | Texto del resultado (ej: "Aprobado"). |
| `<Quorum>` | `quorum_aplicado` | Texto del quórum (ej: "Quórum Simple"). |
| `<TotalSi>` | `a_favor_total` | Conteo de votos afirmativos. |
| `<TotalNo>` | `en_contra_total` | Conteo de votos negativos. |
| `<TotalAbstencion>` | `abstencion_total`| Conteo de abstenciones. |
| `<TotalDispensado>`| `pareo_total` | Conteo de dispensados o pareos. |

### Tabla: `votos_parlamentario`

| Campo XML (en `<Votos>/<Voto>`) | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- |
| `<Id>` de la votación padre | `sesion_votacion_id` | **Clave Foránea** que vincula el voto a la sesión. |
| `<Diputado>/<Id>`| `mp_uid` | **Clave Foránea**. Se extrae el `diputadoid` y se busca su `mp_uid` en `dim_parlamentario`. |
| `<OpcionVoto>` | `voto` | Se extrae y **se normaliza** el texto (ej: "Afirmativo" -> "A Favor"). |