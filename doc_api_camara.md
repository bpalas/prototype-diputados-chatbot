¡Claro que sí! He preparado una documentación técnica completa y actualizada, tal como la pediste.

Este documento consolida la definición de las entidades clave de la API del Congreso, incluyendo `Diputado`, `Legislatura`, `Proyecto de Ley` y `Votación`, y describe cómo sus datos se mapean a las tablas de tu base de datos. Esta guía será fundamental para el desarrollo de tus próximos scripts ETL.

---

# 📜 Guía de Entidades y Mapeo: API de la Cámara a Base de Datos

Este documento técnico sirve como una referencia central para los desarrolladores de ETL. Describe las principales entidades de datos XML proporcionadas por los endpoints de la API de la Cámara de Diputadas y Diputados de Chile, y define su mapeo a las tablas del esquema SQL del proyecto.

## 🏛️ Entidad: `Diputado`

Un **Diputado** representa el perfil y los datos administrativos de un parlamentario. Es la entidad central del sistema, y la información enriquecida se almacena en la tabla `dim_parlamentario`.

* **Endpoint de Ejemplo**: `https://opendata.camara.cl/camaradiputados/pages/diputado/retornarDiputado.aspx`
* **Tabla Destino Principal**: `dim_parlamentario`
* **Poblado por**: `src/etl/etl_roster.py`

### Estructura y Mapeo: `<Diputado>`

| Campo XML | Tipo de Dato | Tabla Destino | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- | :--- | :--- |
| `<Id>` | `integer` | `dim_parlamentario` | `diputadoid` | **Clave de cruce**. Es el identificador oficial de la Cámara. |
| `<Nombre>` | `string` | `dim_parlamentario` | `nombre_completo` | Se concatena con los apellidos para formar el nombre completo. |
| `<Nombre2>` | `string` | - | - | Se puede omitir o usar para enriquecer el `nombre_completo` si es necesario. |
| `<ApellidoPaterno>`| `string` | `dim_parlamentario` | `nombre_completo` | Se concatena para formar el nombre completo. |
| `<ApellidoMaterno>`| `string` | `dim_parlamentario` | `nombre_completo` | Se concatena para formar el nombre completo. |
| `<FechaNacimiento>`| `dateTime` | `dim_parlamentario` | `fecha_nacimiento`| Se extrae y formatea a `YYYY-MM-DD`. Generalmente, se prefiere el dato de BCN. |
| `<Sexo>` | `TipoSexo` | `dim_parlamentario` | `genero` | Se mapea a "Masculino" o "Femenino" según el valor del atributo. |
| `<Militancias>` | `MilitanciasColeccion` | `militancia_historial` | (Múltiples) | Se itera sobre la colección para poblar el historial de militancias. |
| `<RUT>`, `<RUTDV>`| `string` | - | - | Campos no utilizados actualmente en el esquema. |
| `<FechaDefuncion>`| `dateTime` | - | - | Campo no utilizado actualmente en el esquema. |

---

## 🏛️ Entidad: `Legislatura` y `PeriodoLegislativo`

Una **Legislatura** representa un período específico dentro del ejercicio del Congreso. El **PeriodoLegislativo** agrupa a un conjunto de legislaturas.

* **Endpoints**:
    * `.../retornarLegislaturaActual`
    * `.../retornarPeriodoLegislativoActual`
* **Tabla Destino Sugerida**: `dim_legislatura` (nueva tabla dimensional)

### Estructura y Mapeo: `<Legislatura>`

| Campo XML | Tipo de Dato | Tabla Destino | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- | :--- | :--- |
| `<Id>` | `integer` | `dim_legislatura` | `legislatura_id` | **Clave Primaria** de la tabla. |
| `<Numero>` | `integer` | `dim_legislatura` | `numero` | Número que identifica a la legislatura (ej: 368). |
| `<FechaInicio>` | `dateTime` | `dim_legislatura` | `fecha_inicio` | Se extrae y formatea a `YYYY-MM-DD`. |
| `<FechaTermino>` | `dateTime` | `dim_legislatura` | `fecha_termino` | Se extrae y formatea a `YYYY-MM-DD`. |
| `<Tipo>` | `TipoLegislatura` | `dim_legislatura` | `tipo` | Define el tipo (ej: "Ordinaria"). |

---

## 🏛️ Entidad: `ProyectoLey`

Un **Proyecto de Ley** es una iniciativa legal. Su información detallada se almacena en la tabla `bills` y la autoría en `bill_authors`.

* **Endpoint de Ejemplo**: `.../retornarProyectoLey`
* **Tablas Destino**: `bills`, `bill_authors`
* **Poblado por**: `src/etl/etl_bills.py` (futuro)

### Estructura y Mapeo: `<ProyectoLey>`

| Campo XML | Tipo de Dato | Tabla Destino | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- | :--- | :--- |
| `<NumeroBoletin>` | `string` | `bills` | `bill_id` | **Clave Primaria**. Es el identificador único del proyecto. |
| `<Nombre>` | `string` | `bills` | `titulo` | Título oficial o idea matriz del proyecto. |
| `<FechaIngreso>` | `dateTime` | `bills` | `fecha_ingreso` | Se extrae y formatea a `YYYY-MM-DD`. |
| `<TipoIniciativa>` | `TipoIniciativa...` | `bills` | `iniciativa` | Define si es "Moción" o "Mensaje". |
| `<CamaraOrigen>` | `TipoCamaraOrigen` | `bills` | `origen` | Cámara donde se inició el trámite (ej: "C.D."). |
| `<Autores>` | `Parlamentarios...` | `bill_authors` | `mp_uid` | Se itera sobre cada autor, se extrae el ID y se busca el `mp_uid` en `dim_parlamentario` para insertar la relación. |
| `<Materias>` | `MateriasColeccion` | - | - | No utilizado actualmente. Podría mapearse a una futura tabla `bill_topics`. |
| `<Votaciones>` | `VotacionesColeccion` | - | - | No utilizado directamente. Se usa el endpoint de votaciones por proyecto. |
| `<Id>`, `<Adminisible>`| `integer`, `boolean`| - | - | Campos no utilizados actualmente en el esquema. |

---

## 🏛️ Entidad: `Votacion`

Una **Votación** registra el resultado de un sufragio parlamentario sobre un tema específico. La información se divide en dos tablas para mayor granularidad.

* **Endpoint de Ejemplo**: `.../retornarVotacionDetalle?prmVotacionId=23683`
* **Tablas Destino**: `sesiones_votacion`, `votos_parlamentario`
* **Poblado por**: `src/etl/etl_votes.py` (futuro)

### Estructura y Mapeo: `<Votacion>`

#### Mapeo a la tabla `sesiones_votacion`

| Campo XML | Tipo de Dato | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- | :--- |
| `<Id>` | `integer` | `sesion_votacion_id` | **Clave Primaria** de la sesión. |
| `<Descripcion>` | `string` | `tema` y `bill_id` | El texto completo es el `tema`. Se debe **parsear el número de boletín** de este texto para obtener el `bill_id` y crear la relación. |
| `<Fecha>` | `dateTime` | `fecha` | Se extrae y formatea a `YYYY-MM-DD`. |
| `<Resultado>` | `TipoResultado...` | `resultado_general`| Texto del resultado (ej: "Aprobado"). |
| `<Quorum>` | `TipoQuorum...` | `quorum_aplicado` | Texto del quórum (ej: "Quórum Simple"). |
| `<TotalSi>` | `integer` | `a_favor_total` | Conteo de votos afirmativos. |
| `<TotalNo>` | `integer` | `en_contra_total` | Conteo de votos negativos. |
| `<TotalAbstencion>`| `integer` | `abstencion_total`| Conteo de abstenciones. |
| `<TotalDispensado>`| `integer` | `pareo_total` | Conteo de dispensados o pareos. |

#### Mapeo a la tabla `votos_parlamentario` (iterando sobre `<Votos>`)

| Campo XML (en `<Votos>`) | Columna Destino | Lógica de Mapeo y Notas |
| :--- | :--- | :--- |
| (Implícito) | `sesion_votacion_id` | Se usa el `<Id>` de la votación padre como clave foránea. |
| `<Diputado>/<Id>`| `mp_uid` | Se extrae el ID del diputado y se busca su `mp_uid` en `dim_parlamentario`. |
| `<OpcionVoto>` | `voto` | Se extrae y **se normaliza** el texto (ej: "Afirmativo" se convierte en "A Favor"). |