# src/etl/etl_bills_ids.py
# -*- coding: utf-8 -*-
"""
ETL - Fase 1: Descubrimiento de IDs de Proyectos de Ley.

- Intensidad de red: Baja (2 llamadas a la API por año).
- Objetivo: Crear una lista de boletines únicos para un rango de años,
  la cual servirá como entrada para el script de enriquecimiento.
"""
from __future__ import annotations

import argparse
import os
import xml.etree.ElementTree as ET
from typing import List

import requests

# --- CONFIGURACIÓN ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUTPUT_FILE = os.path.join(PROJECT_ROOT, 'data', 'bill_ids_to_process.txt')
NS = {'v1': 'http://opendata.camara.cl/camaradiputados/v1'}
START_YEAR = 2024

def fetch_projects_by_year(year: int) -> List[str]:
    """Obtiene los números de boletín de mociones y mensajes para un año."""
    projects: List[str] = []
    urls = {
        "mociones": f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarMocionesXAnno?prmAnno={year}",
        "mensajes": f"https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx/retornarMensajesXAnno?prmAnno={year}"
    }

    for project_type, url in urls.items():
        print(f"⚙️  Obteniendo {project_type} para el año {year}...")
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for proj in root.findall('v1:ProyectoLey', NS):
                boletin = proj.findtext('v1:NumeroBoletin', namespaces=NS)
                if boletin:
                    projects.append(boletin)
        except requests.exceptions.RequestException as e:
            print(f"⚠️  Error de red para {project_type} del año {year}: {e}")
        except ET.ParseError as e:
            print(f"⚠️  Error de XML para {project_type} del año {year}: {e}")
    
    return projects

def main(year: int | None = None, from_year: int | None = None, to_year: int | None = None, append: bool = False):
    """Ejecuta el ETL de descubrimiento de IDs para uno o varios años."""
    if year:
        years = [year]
    elif from_year and to_year:
        years = range(from_year, to_year + 1)
    else:
        years = [START_YEAR]

    print(f"--- [BILLS ID DISCOVERY] Iniciando proceso para años: {', '.join(map(str, years))} ---")
    
    all_bill_ids = set()

    if append and os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r') as f:
            for line in f:
                all_bill_ids.add(line.strip())
        print(f"Se cargaron {len(all_bill_ids)} IDs existentes para añadir nuevos.")

    for y in years:
        bill_ids_year = fetch_projects_by_year(y)
        found_count = len(bill_ids_year)
        new_ids = set(bill_ids_year) - all_bill_ids
        all_bill_ids.update(new_ids)
        print(f"🧮  [{y}] {found_count} proyectos encontrados ({len(new_ids)} nuevos).")

    mode = 'a' if append else 'w'
    with open(OUTPUT_FILE, mode) as f:
        for bill_id in sorted(list(all_bill_ids), reverse=True):
            f.write(f"{bill_id}\n")

    print(f"\n✅ Proceso finalizado. {len(all_bill_ids)} IDs únicos guardados en: {OUTPUT_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL de descubrimiento de IDs de proyectos de ley.")
    parser.add_argument("--year", type=int, help="Año a procesar (YYYY)")
    parser.add_argument("--from-year", type=int, help="Año inicial del rango")
    parser.add_argument("--to-year", type=int, help="Año final del rango")
    parser.add_argument("--append", action="store_true", help="Añade IDs al archivo existente en lugar de sobrescribirlo.")
    args = parser.parse_args()
    main(year=args.year, from_year=args.from_year, to_year=args.to_year, append=args.append)