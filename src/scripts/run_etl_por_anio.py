# src/scripts/run_etl_por_anio.py
# -*- coding: utf-8 -*-

"""
Orquestador de carga progresiva por año.

Objetivo
- Ejecutar los ETL base (períodos, legislaturas, roster actual, roster histórico, comisiones)
  y luego poblar proyectos de ley y sus votaciones año por año.

Periodo temporal y alcance
- Base: cubre catálogos completos (no anualizados).
- Proyectos/Votaciones: ejecuta por año calendario (YYYY).

Intensidad de red
- Base: baja/media (con caché en varios casos).
- Bills: media/alta (listados + detalle por bill; caché local).
- Votes: alta (detalle por votación; caché local). Limitar por año ayuda bastante.

Uso
  python src/scripts/run_etl_por_anio.py --from-year 2018 --to-year 2024

Opciones
  --from-year YYYY    Año inicial (inclusive)
  --to-year   YYYY    Año final (inclusive; si se omite, procesa solo from-year)
  --skip-core         No ejecuta ETLs base (periodos/legislaturas/roster/comisiones)
  --skip-comisiones   Omite comisiones (parte del core)
  --sleep-per-year S  Pausa en segundos entre años (por defecto: 0.5)
"""

from __future__ import annotations

import argparse
import time

from src.etl import (
    etl_periodos,
    etl_legislaturas,
    etl_roster,
    etl_roster_historico,
    etl_comisiones,
    etl_bills,
    etl_votes,
)


def _iter_years(from_year: int, to_year: int | None) -> list[int]:
    if to_year is None:
        return [int(from_year)]
    a, b = int(from_year), int(to_year)
    step = 1 if a <= b else -1
    return list(range(a, b + step, step))


def run(from_year: int, to_year: int | None, skip_core: bool, skip_comisiones: bool, sleep_per_year: float):
    if not skip_core:
        print("\n=== [CORE] Períodos y Legislaturas ===")
        etl_periodos.main()
        etl_legislaturas.main()

        print("\n=== [CORE] Roster actual e histórico ===")
        etl_roster.main()
        etl_roster_historico.main()

        if not skip_comisiones:
            print("\n=== [CORE] Comisiones ===")
            etl_comisiones.main()

    years = _iter_years(from_year, to_year)
    for y in years:
        print(f"\n=== [AÑO {y}] Bills ===")
        etl_bills.main(year=y)

        print(f"\n=== [AÑO {y}] Votes (filtrado por año) ===")
        etl_votes.main(year=y)

        if sleep_per_year > 0:
            time.sleep(sleep_per_year)


def _parse_args():
    parser = argparse.ArgumentParser(description="Orquestador ETL por año")
    parser.add_argument("--from-year", type=int, required=True, help="Año inicial (inclusive)")
    parser.add_argument("--to-year", type=int, help="Año final (inclusive)")
    parser.add_argument("--skip-core", action="store_true", help="Omitir ETLs base (periodos/legislaturas/roster/comisiones)")
    parser.add_argument("--skip-comisiones", action="store_true", help="Omitir ETL de comisiones (si no se usa --skip-core)")
    parser.add_argument("--sleep-per-year", type=float, default=0.5, help="Pausa entre años (segundos)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(
        from_year=args.from_year,
        to_year=args.to_year,
        skip_core=args.skip_core,
        skip_comisiones=args.skip_comisiones,
        sleep_per_year=args.sleep_per_year,
    )

