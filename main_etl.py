# main_etl.py
# -*- coding: utf-8 -*-

"""
Orquestador principal para ejecutar todos los procesos ETL en orden.

- Alcance temporal:
  - Períodos/Legislaturas/Roster/Comisiones: catálogos completos (no anualizados).
  - Bills: por defecto procesa un año (ver `src/etl/etl_bills.py`, parámetro `--year`).
  - Votes: por defecto procesa todos los bills en BD (puede filtrarse por año desde el módulo).

Para cargas progresivas año a año, se recomienda:
  python src/scripts/run_etl_por_anio.py --from-year YYYY --to-year YYYY
"""

import time

# Se importa cada módulo ETL desde el paquete src.etl
from src.etl import etl_periodos
from src.etl import etl_legislaturas
from src.etl import etl_roster
from src.etl import etl_comisiones
from src.etl import etl_votes
from src.etl import etl_roster_ids
from src.etl import etl_comisiones
from src.etl import etl_materias
from src.scripts import enrich_parlamentarios
from src.etl import etl_ministerios

          
def run_all(): # asegurarse de haber usado create_database.py
    """Ejecuta todos los ETLs en la secuencia correcta (carga completa)."""
    start_time = time.time()
    print("🔧 --- INICIANDO PROCESO ETL COMPLETO --- 🔧")

    # --- PASO 1: Estructura Legislativa (La base de todo) ---
    etl_periodos.main()
    etl_legislaturas.main()
    etl_materias.main()
    etl_ministerios.main()
    etl_roster_ids.main()

    # enrich_parlamentarios.main()
    #  src\etl\etl_bills_enrichment.py
    #  src\etl\etl_laws_enrichment.py
    #  src\etl\etl_comisiones.py 
    #  
    end_time = time.time()

    total_time = end_time - start_time
    print(f"\n✅ --- PROCESO ETL COMPLETO FINALIZADO --- ✅")
    print(f"⏱️  Tiempo total de ejecución: {total_time:.2f} segundos.")

if __name__ == "__main__":
    run_all()

