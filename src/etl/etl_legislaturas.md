# 🏛️ Documentación del Script ETL: Legislaturas (`etl_legislaturas.py`)

Este documento describe el funcionamiento del script `etl_legislaturas.py`, cuyo único propósito es poblar y mantener actualizada la tabla dimensional **`dim_legislatura`**.

---

## 🎯 Propósito del Script

El objetivo de este ETL es crear un catálogo histórico y completo de todas las legislaturas del Congreso. La tabla `dim_legislatura` sirve como una tabla de dimensiones que puede ser utilizada en el futuro para dar contexto temporal a otros eventos, como votaciones o mandatos de parlamentarios.

Debido a que esta información es pequeña y cambia con muy poca frecuencia (solo al inicio de una nueva legislatura), el script utiliza una estrategia de **borrar y recargar** (`DELETE` + `INSERT`).

---

## ⚙️ Flujo del Proceso ETL

### 1. Extracción y Transformación (Extract & Transform)

El script realiza estas dos fases en una sola función, `fetch_and_transform_legislaturas()`:

* **Fuente de Datos**: Se conecta a un único endpoint de la **API de la Cámara de Diputadas y Diputados**:
    * `WSCamaradeDiputados.asmx/retornarPeriodosLegislativos`
* **Lógica de Extracción**:
    1.  Realiza una única llamada a la API para obtener un archivo XML que contiene todos los períodos legislativos históricos.
    2.  Itera a través de cada `<PeriodoLegislativo>` en el XML.
    3.  Dentro de cada período, itera a través de la colección de `<Legislatura>`.
    4.  Para cada legislatura, extrae los campos relevantes.
* **Lógica de Transformación**:
    * Las fechas se convierten del formato `dateTime` a `YYYY-MM-DD`.
    * Los datos se estructuran en una lista de diccionarios, listos para ser insertados en la base de datos.

### 2. Carga (Load)

* **Conexión a la BD**: El script se conecta a la base de datos `parlamento.db`.
* **Limpieza de la Tabla**: Ejecuta una sentencia `DELETE FROM dim_legislatura;` para vaciar por completo la tabla.
* **Inserción Masiva**: Utiliza el método `executemany()` de SQLite para insertar todos los registros de legislaturas de una sola vez, lo cual es muy eficiente.

---

## 📋 Mapeo de Datos: API (XML) a Base de Datos (SQL)

La siguiente tabla detalla cómo cada campo del XML se mapea a una columna en la tabla `dim_legislatura`.

| Campo XML (en `<Legislatura>`) | Tabla Destino | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- | :--- |
| `<Id>` | `dim_legislatura` | `legislatura_id` | **Clave Primaria**. Se usa directamente el ID de la legislatura. |
| `<Numero>` | `dim_legislatura` | `numero` | Número que identifica a la legislatura (ej: 368, 369). |
| `<FechaInicio>` | `dim_legislatura` | `fecha_inicio` | Se extrae la fecha y se formatea a `YYYY-MM-DD`. |
| `<FechaTermino>`| `dim_legislatura` | `fecha_termino` | Se extrae la fecha y se formatea a `YYYY-MM-DD`. |
| Atributo `Valor` en `<Tipo>` | `dim_legislatura` | `tipo` | Define el tipo de legislatura (ej: "Ordinaria", "Extraordinaria"). |