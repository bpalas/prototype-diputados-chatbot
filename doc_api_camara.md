¡Absolutamente\! Aquí tienes el documento Markdown consolidado que une toda la información. Este archivo sirve como una guía completa para los desarrolladores de tus scripts ETL, detallando el flujo de datos desde la API hasta la base de datos.

-----

# 📜 Guía Completa de ETL: API del Congreso a Base de Datos

Este documento describe el proceso de extracción, transformación y carga (ETL) para poblar la base de datos del chatbot parlamentario. Detalla los scripts responsables, los endpoints de la API que consumen, la estructura de los datos XML y el mapeo final a las tablas SQL.

## 📂 Script: `src/etl/etl_bills.py`

Este script es responsable de poblar las tablas `bills` (proyectos de ley) y `bill_authors` (autores de los proyectos).

### Fase 1: Descubrimiento de Proyectos de Ley

El objetivo de esta fase es obtener una lista completa de todos los `bill_id` (números de boletín) a procesar.

  * **Endpoints Utilizados**:
      * `Legislativo/retornarMocionesXAnno`
      * `Legislativo/retornarMensajesXAnno`
  * **Proceso**:
    1.  El script itera a través de un rango de años definido.
    2.  Para cada año, llama a ambos endpoints para obtener la lista de mociones (iniciativas parlamentarias) y mensajes (iniciativas del gobierno).
    3.  De cada respuesta XML, extrae el contenido de la etiqueta `<NumeroBoletin>` de cada `<ProyectoLey>`.
    4.  Consolida todos los `NumeroBoletin` en una lista única, que será el insumo para la siguiente fase.

### Fase 2: Carga de Detalles del Proyecto

Con la lista de `bill_id`s, el script procede a obtener y guardar la información detallada de cada proyecto.

  * **Endpoint Utilizado**: `Legislativo/retornarProyectoLey`
  * **Proceso**:
    1.  El script recorre la lista de `bill_id`s.
    2.  Para cada `bill_id`, llama al endpoint, pasando el número de boletín como parámetro.
    3.  La respuesta XML, correspondiente al elemento `<ProyectoLey>`, se utiliza para poblar las tablas `bills` y `bill_authors` según el mapeo a continuación.

### Estructura y Mapeo: `<ProyectoLey>`

| Campo XML | Tabla Destino | Columna Destino | Lógica |
| :--- | :--- | :--- | :--- |
| `<NumeroBoletin>` | **`bills`** | `bill_id` | **Clave Primaria**. Se extrae directamente. |
| `<Nombre>` | **`bills`** | `titulo` | Se extrae el título completo del proyecto. |
| `<FechaIngreso>` | **`bills`** | `fecha_ingreso` | Se extrae y formatea a `YYYY-MM-DD`. |
| `<TipoIniciativa>`| **`bills`** | `iniciativa` | Se extrae el texto (ej: "Moción"). |
| `<CamaraOrigen>` | **`bills`** | `origen` | Se extrae el texto (ej: "Cámara de Diputados").|
| `<Autores>` | **`bill_authors`**| (Múltiples) | Se itera sobre cada `<ParlamentarioAutor>`, se extrae el `<Id>` del diputado y se busca su `mp_uid` en `dim_parlamentario` para insertarlo en la columna `mp_uid`. |

-----

## 📂 Script: `src/etl/etl_votes.py`

Este script es responsable de poblar las tablas `sesiones_votacion` (resumen de cada votación) y `votos_parlamentario` (el voto individual de cada diputado).

### Fase 1: Descubrimiento de Votaciones

El objetivo es encontrar todas las sesiones de votación asociadas a cada proyecto de ley que ya existe en nuestra base de datos.

  * **Endpoint Utilizado**: `Legislativo/retornarVotacionesXProyectoLey`
  * **Proceso**:
    1.  El script consulta la tabla `bills` para obtener todos los `bill_id` existentes.
    2.  Para cada `bill_id`, llama al endpoint `retornarVotacionesXProyectoLey`.
    3.  De la respuesta XML, navega a `<Votaciones>` y, para cada `<VotacionProyectoLey>`, extrae el **`<Id>`** de la votación.
    4.  Genera una lista de todos los IDs de votaciones a procesar.

### Fase 2: Carga de Detalles de Votación

Con la lista de IDs de votaciones, el script obtiene el detalle completo de cada una.

  * **Endpoint Utilizado**: `Legislativo/retornarVotacionDetalle`
  * **Proceso**:
    1.  El script itera sobre la lista de IDs de votaciones.
    2.  Para cada ID, llama al endpoint `retornarVotacionDetalle`.
    3.  La respuesta XML, un elemento `<Votacion>`, se usa para una inserción en dos pasos: primero en `sesiones_votacion` y luego, con el ID generado, en `votos_parlamentario`.

### Estructura y Mapeo: `<Votacion>`

#### Mapeo a la tabla `sesiones_votacion`

| Campo XML | Columna Destino | Lógica |
| :--- | :--- | :--- |
| `<Descripcion>` | `bill_id` y `tema`| Se extrae el `NumeroBoletin` del texto para el `bill_id`. El texto completo sirve como `tema`. |
| `<Fecha>` | `fecha` | Se extrae y formatea a `YYYY-MM-DD`. |
| `<Resultado>` | `resultado_general`| Se extrae el texto (ej: "Aprobado"). |
| `<Quorum>` | `quorum_aplicado` | Se extrae el texto (ej: "Quórum Simple"). |
| `<TotalSi>` | `a_favor_total` | Se extrae el valor numérico. |
| `<TotalNo>` | `en_contra_total` | Se extrae el valor numérico. |
| `<TotalAbstencion>`| `abstencion_total`| Se extrae el valor numérico. |
| `<TotalDispensado>`| `pareo_total` | Se extrae el valor numérico. |

#### Mapeo a la tabla `votos_parlamentario`

| Campo XML (dentro de `<Votos>`) | Columna Destino | Lógica |
| :--- | :--- | :--- |
| (Clave Foránea) | `sesion_votacion_id` | Se usa el ID autoincremental generado al insertar el registro en `sesiones_votacion`. |
| `<Diputado>/<Id>`| `mp_uid` | Se usa el ID del diputado para buscar su `mp_uid` correspondiente en la tabla `dim_parlamentario`. |
| `<OpcionVoto>` | `voto` | Se extrae y normaliza el texto. "Afirmativo" se convierte en "A Favor" para cumplir la restricción de la tabla. |