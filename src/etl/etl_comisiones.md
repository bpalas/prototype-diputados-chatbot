
# 📜 Documentación del Script ETL: Comisiones Parlamentarias (`etl_comisiones.py`)

Este documento describe el funcionamiento del script `etl_comisiones.py`, cuyo propósito es extraer, transformar y cargar la información sobre la estructura y composición de las comisiones parlamentarias.

---

## 🎯 Propósito del Script

El objetivo principal es poblar dos tablas relacionales que definen qué son las comisiones y quiénes las integran, permitiendo analizar la participación de los parlamentarios en las distintas instancias legislativas.

---

## 📊 Tablas de la Base de Datos Pobladas

El script interactúa y carga datos en las siguientes dos tablas:

### Tabla: `dim_comisiones`

Es la **tabla de dimensión** que contiene el catálogo de todas las comisiones parlamentarias vigentes.

* **Propósito**: Servir como un registro único y descriptivo de cada comisión.
* **Clave Primaria**: `comision_id` (identificador numérico de la API).
* **Columnas Principales**:
    * `comision_id`: Identificador único de la comisión.
    * `nombre_comision`: Nombre oficial y completo de la comisión.
    * `tipo`: Tipo de comisión normalizado (ej: "Permanente", "Especial Investigadora", "Bicameral").

### Tabla: `comision_membresias`

Es una **tabla de hechos o de enlace** que registra la membresía de los parlamentarios en las comisiones.

* **Propósito**: Conectar a los parlamentarios (`dim_parlamentario`) con las comisiones (`dim_comisiones`), detallando su rol y el período de su membresía.
* **Clave Primaria**: Compuesta por (`mp_uid`, `comision_id`).
* **Columnas Principales**:
    * `mp_uid`: **Clave foránea** que se conecta con `dim_parlamentario.mp_uid`.
    * `comision_id`: **Clave foránea** que se conecta con `dim_comisiones.comision_id`.
    * `rol`: El cargo del parlamentario en la comisión ("Presidente" o "Miembro").
    * `fecha_inicio`: Fecha en que el parlamentario se unió a la comisión.
    * `fecha_fin`: Fecha en que el parlamentario dejó la comisión (puede ser NULO si sigue activo).

---

## ✨ Características Principales

Este script posee varias características de diseño importantes:

* **Full Refresh (Borrado y Carga) 🔄**: A diferencia de otros ETLs, este script **primero elimina todos los registros existentes** en las tablas `dim_comisiones` y `comision_membresias`. Luego, carga la información más reciente de las comisiones vigentes. Esto asegura que los datos siempre reflejen el estado actual, pero no mantiene un historial de membresías pasadas.
* **Caché Local de XML 💾**: Para acelerar las ejecuciones y evitar sobrecargar la API, el script guarda las respuestas XML en un directorio local. Las consultas posteriores leen estos archivos en lugar de hacer nuevas peticiones a la red.
* **Carga por Lotes (`executemany`) 🚀**: Para una mayor eficiencia, los datos de comisiones y membresías se insertan en la base de datos en grandes lotes, reduciendo significativamente el tiempo total de carga.
* **Normalización y Limpieza de Datos 🧹**:
    * Los tipos de comisión se normalizan usando un diccionario (`TIPO_COMISION_MAP`) para mantener la consistencia.
    * Se aplica un filtro para evitar cargar comisiones con nombres duplicados, lo que previene errores de unicidad en la base de datos.

---

## ⚙️ Flujo del Proceso ETL

El script sigue una secuencia lógica para asegurar que los datos sean consistentes y completos.

### 1. Extracción (Extract)

* **Paso 1: Obtener Listado de Comisiones Vigentes**
    * Se realiza una única llamada a la API (`retornarComisionesVigentes`) para obtener la lista de todas las comisiones actualmente en funcionamiento. El resultado se guarda en caché.

* **Paso 2: Obtener Detalles de Cada Comisión (Usando Caché)**
    * Para cada ID de comisión obtenido, se consulta el endpoint de detalle (`retornarComision`). El script prioriza leer la respuesta desde un archivo XML local si existe; de lo contrario, consulta la API y guarda el resultado para el futuro.

### 2. Transformación (Transform)

* **Parseo de Datos**: Se extrae la información clave de cada XML: ID, nombre y tipo de la comisión.
* **Asignación de Roles**: Se identifica al presidente de la comisión y se le asigna el rol "Presidente". A los demás integrantes se les asigna el rol "Miembro".
* **Limpieza**: Las fechas se formatean a `YYYY-MM-DD` y los datos se preparan en listas para la carga por lotes.
* **Vinculación**: Se prepara un mapa de `diputadoid` a `mp_uid` para vincular correctamente a los parlamentarios en la tabla de membresías.

### 3. Carga (Load)

* **Paso 1: Limpieza Total de Tablas**
    * **Importante**: Antes de cualquier inserción, el script ejecuta un `DELETE` sobre las tablas `dim_comisiones` y `comision_membresias` para vaciarlas por completo.

* **Paso 2: Filtrado de Duplicados**
    * Se procesan las comisiones extraídas y se eliminan aquellas con nombres duplicados, conservando solo una entrada por nombre.

* **Paso 3: Inserción por Lotes**
    * Se insertan todas las comisiones únicas en `dim_comisiones` con una sola operación `executemany`.
    * Se insertan todos los registros de membresías en `comision_membresias` con una segunda operación `executemany`.

---

## 📋 Mapeo de Datos: API (XML) a Base de Datos (SQL)

La siguiente tabla detalla cómo los campos del XML se mapean a las columnas de las tablas de destino.

| Campo XML (en `<Comision>`) | Tabla Destino | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- | :--- |
| `<Id>` | `dim_comisiones` | `comision_id` | **Clave Primaria**. También se usa como clave foránea en `comision_membresias`. |
| `<Nombre>` | `dim_comisiones` | `nombre_comision` | Nombre oficial de la comisión. Se usa para filtrar duplicados. |
| `<Tipo>` | `dim_comisiones` | `tipo` | Se normaliza usando el diccionario `TIPO_COMISION_MAP`. |
| `<Integrantes>...<Id>` | `comision_membresias` | `mp_uid` | Se extrae el `diputadoid` y se busca el `mp_uid` correspondiente para la inserción. |
| `<Presidente>...<Id>` | `comision_membresias` | `rol` | Si el `diputadoid` del integrante coincide con el del presidente, el rol es "Presidente". |
| `<Integrantes>...<FechaInicio>` | `comision_membresias` | `fecha_inicio` | Fecha de inicio de la membresía, formateada a `YYYY-MM-DD`. |
| `<Integrantes>...<FechaTermino>` | `comision_membresias` | `fecha_fin` | Fecha de fin de la membresía. Se mapea a NULO si no está presente o es inválida. |