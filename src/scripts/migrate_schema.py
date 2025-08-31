import os
import sqlite3
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / 'data' / 'parlamento.db'


def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    tables_modified = {}

    # --- Example 1: simple ALTER TABLE ADD COLUMN ---
    table = 'dim_parlamentario'
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    tables_modified[table] = cur.fetchone()[0]

    if not column_exists(cur, table, 'validation_status'):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN validation_status TEXT")
    if not column_exists(cur, table, 'validation_error'):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN validation_error TEXT")

    # --- Example 2: renaming column using temporary table ---
    table = 'dim_periodo_legislativo'
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    tables_modified[table] = cur.fetchone()[0]

    cur.execute(
        """
        CREATE TABLE dim_periodo_legislativo_tmp (
            periodo_id INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            fecha_inicio DATE,
            fecha_termino DATE
        )
        """
    )
    cur.execute(
        """
        INSERT INTO dim_periodo_legislativo_tmp (periodo_id, nombre, fecha_inicio, fecha_termino)
        SELECT periodo_id, nombre_periodo, fecha_inicio, fecha_termino
        FROM dim_periodo_legislativo
        """
    )
    cur.execute("DROP TABLE dim_periodo_legislativo")
    cur.execute("ALTER TABLE dim_periodo_legislativo_tmp RENAME TO dim_periodo_legislativo")

    conn.commit()

    # --- Verification ---
    for table, before_count in tables_modified.items():
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        after_count = cur.fetchone()[0]
        print(f"Tabla {table}: antes={before_count}, despues={after_count}")
        cur.execute(f"SELECT * FROM {table} LIMIT 10")
        rows = cur.fetchall()
        for row in rows:
            print(row)
        print('-' * 40)

    conn.close()


if __name__ == '__main__':
    migrate()
