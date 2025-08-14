### Código Markdown Mejorado

# 🗺️ Planificación y Seguimiento del Prototipo

Este documento detalla la planificación y el seguimiento del desarrollo del prototipo, conectando cada tarea con su respectivo avance.

---

## 🎯 Plan de Trabajo (1 Semana)

**Objetivo:** Tener la base de datos completa y la app web funcional para el lunes de la próxima semana.

### Cronograma Diario

| Día         | Tarea Principal                                      | Estado      |
|-------------|------------------------------------------------------|-------------|
| Lunes (11-08)   | Setup del proyecto, estructura de carpetas, esquema SQL y creación de BD | ✅ Listo     |
| Martes (12-08)  | Finalizar `etl_roster.py` (biografías, distritos) y comenzar `etl_votes.py` | 🏃 En curso  |
| Miércoles (13-08)| Terminar `etl_votes.py` y desarrollar `etl_transcripts.py` (tabla `speech_turns`) | ⏳ Pendiente |
| Jueves (14-08)  | Desarrollar `etl_news_graph.py` (tabla `interactions`) y `alias_resolver.py` | ⏳ Pendiente |
| Viernes (15-08) | Desarrollar y probar la app web (Streamlit) usando la base de datos completa | ⏳ Pendiente |

---

## ✅ Avances y Trabajo por Día

### Lunes (11-08)
- Estructura de carpetas y archivos creada (`src/`, `data/`, `tests/`, etc.).
- Redacción y mejora del archivo `README.md`.
- Esquema preliminar y final de la base de datos en `data/docs/schema.sql`.
- Base de datos SQLite (`parlamento.db`) creada y probada.

### Martes (12-08)
- Finalizar el script `etl_roster.py` para poblar la tabla `dim_parlamentario` con biografías y distritos.
- Comenzar el desarrollo de `etl_votes.py` para poblar las tablas:

1.  🏛️ **`bills`**: Esta es la tabla principal para este ETL. Debes llenarla primero. Almacena la información de cada proyecto de ley, como su identificador (`bill_id`), resumen y estado.
2.  ✍️ **`bill_authors`**: Inmediatamente después de registrar un proyecto en `bills`, debes poblar esta tabla. Vincula cada `bill_id` con los `mp_uid` de los parlamentarios que lo propusieron. Es una tabla de relación clave para entender quién impulsa cada iniciativa.
3.  🗳️ **`votes`**: Finalmente, esta tabla registrará cada voto individual. Se conectará con `dim_parlamentario` a través de `mp_uid` y con `bills` a través de `bill_id`, registrando la decisión del parlamentario ('A Favor', 'En Contra', etc.) y la fecha.

`etl_votes.py` maneja exclusivamente la lógica de proyectos de ley y votaciones.


### Miércoles (13-08)
- Terminar el script `etl_votes.py`.
- Desarrollar el script `etl_transcripts.py` para cargar discursos en la tabla `speech_turns`.

### Jueves (14-08)
- Desarrollar el script `etl_news_graph.py` para poblar la tabla `interactions`.
- Desarrollar el módulo `alias_resolver.py` y sus tests unitarios.

### Viernes (15-08)
- Desarrollar y probar la app web con Streamlit usando la base de datos completa.

---

## 📝 Scripts por Desarrollar

- `etl_roster.py` (dim_parlamentario)
- `etl_votes.py` (votes, bills)
- `etl_transcripts.py` (speech_turns)
- `etl_news_graph.py` (interactions)
- `alias_resolver.py` (normalización de nombres)
- Tests para `alias_resolver.py`
- App web (`app.py` en Streamlit)

<!-- end list --