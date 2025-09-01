# -*- coding: utf-8 -*-
"""
Script de prueba rápida para el Context Builder.

Uso básico (desde la raíz del repo):
  python src/scripts/test_context_builder.py --mp-uid 1 --format both

Si no pasas --mp-uid, intentará detectar uno automáticamente desde la BD.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Optional

# Asegurar que se pueda importar el paquete src.*
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.core.context_builder import ParlamentarioContextBuilder, DB_PATH  # type: ignore


def pick_any_mp_uid(db_path: str) -> Optional[int]:
    """Devuelve un mp_uid válido cualquiera, o None si no hay filas.

    Intenta primero en dim_parlamentario; si no, prueba mediante autores de proyectos.
    """
    if not os.path.exists(db_path):
        print(f"Error: no existe la base de datos en '{db_path}'. Ejecuta create_database.py y los ETLs.")
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            # Intento 1: dim_parlamentario
            cur.execute("SELECT mp_uid FROM dim_parlamentario LIMIT 1")
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
            # Intento 2: desde autores de proyectos
            cur.execute(
                """
                SELECT ba.mp_uid
                FROM bill_authors ba
                JOIN bills b ON ba.bill_id = b.bill_id
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
    except sqlite3.Error as e:
        print(f"Error SQLite al detectar mp_uid: {e}")
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prueba rápida del Context Builder")
    p.add_argument("--mp-uid", type=int, default=None, help="mp_uid a probar (opcional)")
    p.add_argument(
        "--format",
        choices=["json", "text", "both", "print"],
        default="print",
        help="Formato de salida: export JSON, texto, ambos, o imprimir JSON en consola",
    )
    p.add_argument(
        "--output-dir",
        default=os.path.join(PROJECT_ROOT, "data", "contexts"),
        help="Directorio de salida para archivos exportados",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    mp_uid = args.mp_uid or pick_any_mp_uid(DB_PATH)
    if not mp_uid:
        print("No se pudo determinar un mp_uid. Asegúrate de tener datos en la BD.")
        sys.exit(1)

    print(f"Probando Context Builder con mp_uid={mp_uid}")

    try:
        with ParlamentarioContextBuilder() as builder:
            if args.format in ("json", "both"):
                os.makedirs(args.output_dir, exist_ok=True)
                json_path = builder.export_context_to_json(mp_uid, os.path.join(args.output_dir, f"context_test_{mp_uid}.json"))
                print(f"-> JSON exportado: {json_path}")

            if args.format in ("text", "both"):
                os.makedirs(args.output_dir, exist_ok=True)
                txt_path = builder.export_context_to_text(mp_uid, os.path.join(args.output_dir, f"context_test_{mp_uid}.txt"))
                print(f"-> TEXTO exportado: {txt_path}")

            if args.format == "print":
                ctx = builder.build_complete_context(mp_uid)
                # Resumen mínimo legible
                bio = ctx.get("perfil_biografico", {})
                resumen = ctx.get("actividad_legislativa", {}).get("resumen", {})
                stats = ctx.get("actividad_legislativa", {}).get("estadisticas_votacion", {})
                print("\n=== RESUMEN ===")
                print(f"Nombre: {bio.get('nombre_completo')}")
                print(f"Proyectos (autor/coautor): {resumen.get('proyectos', {}).get('total_proyectos')}")
                print(f"Votaciones totales: {stats.get('total_votaciones')}")
                print("(Usa --format both para exportar archivos)")

    except Exception as e:
        print(f"Error durante la prueba: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

