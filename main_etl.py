# main_etl.py
# -*- coding: utf-8 -*-

"""
Script orquestador principal para ejecutar todos los procesos ETL 
en el orden correcto para garantizar la integridad referencial de la base de datos.
"""
import time

# Se importa cada módulo ETL desde el paquete src.etl
from src.etl import etl_periodos
from src.etl import etl_legislaturas
from src.etl import etl_roster
from src.etl import etl_roster_historico
from src.etl import etl_bills
from src.etl import etl_comisiones
from src.etl import etl_votes

def run_all():
    """Ejecuta todos los ETLs en la secuencia correcta."""
    start_time = time.time()
    print("🚀 --- INICIANDO PROCESO ETL COMPLETO --- 🚀")
    

    
    # --- PASO 1: Estructura Legislativa (La base de todo) ---
    print("\n--- [ETAPA 1/5] Cargando Períodos y Legislaturas ---")
    etl_periodos.main()
    etl_legislaturas.main()
    
    # --- PASO 2: Actores Principales (Parlamentarios y Partidos) ---
    print("\n--- [ETAPA 2/5] Cargando Roster de Parlamentarios (Actual e Histórico) ---")
    etl_roster.main() # Carga y/o actualiza el período vigente
    etl_roster_historico.main() # Añade los registros históricos que falten
    
    # --- PASO 3: Proyectos de Ley ---
    print("\n--- [ETAPA 3/5] Cargando Proyectos de Ley (Bills) ---")
    etl_bills.main()
    
    # --- PASO 4: Relaciones (Parlamentarios <-> Comisiones) ---
    print("\n--- [ETAPA 4/5] Cargando Comisiones y Membresías ---")
    etl_comisiones.main()
    
    # --- PASO 5: Acciones (Parlamentarios <-> Proyectos de Ley) ---
    print("\n--- [ETAPA 5/5] Cargando Votaciones (Votes) ---")
    etl_votes.main()
    
    end_time = time.time()
    total_time = end_time - start_time
    print(f"\n✅ --- PROCESO ETL COMPLETO FINALIZADO --- ✅")
    print(f"⏱️  Tiempo total de ejecución: {total_time:.2f} segundos.")

if __name__ == "__main__":
    run_all()