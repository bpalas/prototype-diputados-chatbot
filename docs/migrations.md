# Migraciones de Esquema

Este documento describe el proceso de migración del esquema de la base de datos `parlamento.db`.

## Respaldo inicial

1. Asegúrate de que la base de datos existe en `data/parlamento.db`.
2. Realiza un respaldo previo:
   ```bash
   cp data/parlamento.db data/parlamento_backup.db
   ```

## Script de migración

El script `src/scripts/migrate_schema.py` ejecuta dos tipos de cambios:

- **Alteraciones simples:** se añaden las columnas `validation_status` y `validation_error` a `dim_parlamentario` usando `ALTER TABLE ... ADD COLUMN`.
- **Cambios complejos:** se renombra la columna `nombre_periodo` a `nombre` en `dim_periodo_legislativo` mediante la creación de una tabla temporal, copia de datos y renombrado final.

El script verifica cada tabla modificada con:

- `SELECT COUNT(*)` antes y después de la migración.
- Un muestreo de filas (`LIMIT 10`) para revisar la correspondencia de campos.

Para ejecutar la migración:
```bash
python src/scripts/migrate_schema.py
```

## Rollback

Si algo sale mal, restaura el respaldo original:
```bash
rm data/parlamento.db
cp data/parlamento_backup.db data/parlamento.db
```

Luego, verifica nuevamente la integridad de la base.


