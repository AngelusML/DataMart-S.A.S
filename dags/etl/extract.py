"""EXTRACCIÓN: lee cada CSV tal cual y lo deja con nombres de columna estándar.

No se limpia nada aquí: solo se lee y se renombran columnas. Toda la limpieza
vive en transform.py para que sea fácil de leer y explicar.
"""
import logging
import os
import re

import pandas as pd

from etl.config import COLUMN_ALIASES, STANDARD_COLUMNS

log = logging.getLogger(__name__)


def _normalize_column_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def read_source_csv(path: str, source_name: str) -> pd.DataFrame:
    """Lee un CSV (todo como texto) y devuelve las 8 columnas estándar + source_system."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No se encontró el archivo de la fuente '{source_name}': {path}. "
            "Descárgalo de Kaggle y ponlo en la carpeta data/raw/ (ver README)."
        )

    # data.csv de Kaggle viene en latin-1; si utf-8 falla se usa latin-1.
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype=str, encoding="latin-1")

    rename_map = {}
    for col in df.columns:
        standard = COLUMN_ALIASES.get(_normalize_column_name(col))
        if standard and standard not in rename_map.values():
            rename_map[col] = standard
    df = df.rename(columns=rename_map)

    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"La fuente '{source_name}' no tiene las columnas {missing}. "
            f"Columnas encontradas: {list(df.columns)}"
        )

    df = df[STANDARD_COLUMNS].copy()
    df["source_system"] = source_name
    log_profile(df, source_name)
    return df


def log_profile(df: pd.DataFrame, source_name: str) -> None:
    """Perfil rápido de la fuente que queda en el log de la tarea de Airflow."""
    log.info("=== Perfil de la fuente %s ===", source_name)
    log.info("Filas: %s | Columnas: %s", len(df), list(df.columns))
    log.info("Nulos por columna:\n%s", df.isna().sum().to_string())
    log.info("Filas duplicadas exactas: %s", int(df.duplicated().sum()))
    qty = pd.to_numeric(df["quantity"], errors="coerce")
    price = pd.to_numeric(df["unit_price"], errors="coerce")
    log.info("Cantidad: min=%s max=%s | negativas=%s", qty.min(), qty.max(), int((qty <= 0).sum()))
    log.info("Precio: min=%s max=%s | <=0: %s", price.min(), price.max(), int((price <= 0).sum()))
