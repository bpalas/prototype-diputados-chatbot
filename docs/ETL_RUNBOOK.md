# ETL Runbook: Periodos y Carga Progresiva

Este documento resume el alcance temporal de cada módulo ETL y cómo ejecutar cargas progresivas por año.

## Alcance Temporal por Módulo

- `src/etl/etl_periodos.py`: catálogos de periodos legislativos (completo, no anualizado). Baja intensidad de red.
- `src/etl/etl_legislaturas.py`: catálogos de legislaturas (completo, no anualizado). Baja intensidad de red.
- `src/etl/etl_roster.py`: roster de parlamentarios del periodo vigente + datos BCN. Intensidad media.
- `src/etl/etl_roster_historico.py`: historización por periodos (completo). Intensidad media/alta si sin caché.
- `src/etl/etl_comisiones.py`: catálogos y membresías (completo). Intensidad media.
- `src/etl/etl_bills.py`: proyectos de ley por año calendario (YYYY). Intensidad media/alta; usa caché XML local.
- `src/etl/etl_votes.py`: votaciones por proyecto; puede filtrar por año de `fecha_ingreso` del bill. Intensidad alta; usa caché XML por votación.

## Carga Progresiva por Año

Orquestador recomendado para poblar año a año:

```bash
python src/scripts/run_etl_por_anio.py --from-year 2018 --to-year 2024
```

Parámetros:
- `--from-year`/`--to-year`: rango inclusivo; si `--to-year` se omite, procesa solo `from-year`.
- `--skip-core`: omite ETLs base (periodos/legislaturas/roster/comisiones) si ya están poblados.
- `--skip-comisiones`: omite solo comisiones dentro del core.
- `--sleep-per-year`: pausa entre años para ser amable con los servicios (por defecto 0.5s).

Ejecución directa por módulo (opcional):
- Bills por año o rango: `python src/etl/etl_bills.py --year 2022` o `--from-year 2018 --to-year 2020`.
- Votes con filtro por año: `python src/etl/etl_votes.py --year 2022`.

## Recomendaciones

- Ejecutar primero los módulos base (periodos, legislaturas, roster) para claves y dimensiones.
- Correr Bills y Votes de forma progresiva por año para reducir carga y favorecer reintentos/caché.
- Verificar que `data/xml/` persista entre ejecuciones para beneficiarse del caché.

