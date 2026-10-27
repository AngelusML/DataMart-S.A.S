"""Exploración de las fuentes (sección 6 de la prueba).

Imprime un reporte en Markdown con estructura, tipos, nulos, rangos,
duplicados y problemas de calidad de cada CSV.

Uso (con el entorno levantado):
    docker compose exec airflow-scheduler python /opt/airflow/scripts/explore_sources.py > docs/exploracion.md
"""
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.environ.get("DAGS_DIR", "/opt/airflow/dags"))
from etl.config import COLUMN_ALIASES, VALID_PRODUCT_CODE_REGEX  # noqa: E402

RAW_DIR = os.environ.get("RAW_DIR", "/opt/airflow/data/raw")
FILES = {
    "ventas_diarias (data.csv)": os.path.join(RAW_DIR, "data.csv"),
    "historico (online_retail_II.csv)": os.path.join(RAW_DIR, "online_retail_II.csv"),
}


def standard_columns(df):
    """Devuelve {nombre_estándar: nombre_real} usando los mismos alias del pipeline."""
    found = {}
    for col in df.columns:
        std = COLUMN_ALIASES.get(re.sub(r"[^a-z0-9]", "", str(col).lower()))
        if std and std not in found:
            found[std] = col
    return found


def read(path):
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, encoding="latin-1")


def profile(name, path):
    df = read(path)
    cols = standard_columns(df)
    qty_col, price_col = cols["quantity"], cols["unit_price"]
    code_col, desc_col = cols["product_code"], cols["description"]
    cust_col, date_col = cols["customer_id"], cols["invoice_date"]
    inv_col, country_col = cols["invoice_no"], cols["country"]

    qty = pd.to_numeric(df[qty_col], errors="coerce")
    price = pd.to_numeric(df[price_col], errors="coerce")
    code = df[code_col].str.upper().str.replace(r"\s+", "", regex=True)
    desc_norm = df[desc_col].str.upper().str.strip()

    print(f"## {name}\n")
    print(f"- Filas: **{len(df):,}** | Columnas: `{list(df.columns)}`")
    print(f"- Ejemplo de fecha: `{df[date_col].dropna().iloc[0]}`")
    print(f"- Filas duplicadas exactas: **{int(df.duplicated().sum()):,}**")
    print(f"- Cantidad: min {qty.min():,.0f}, max {qty.max():,.0f}; "
          f"<= 0 (devoluciones/ajustes): **{int((qty <= 0).sum()):,}**")
    print(f"- Precio: min {price.min():,.2f}, max {price.max():,.2f}; "
          f"= 0: **{int((price == 0).sum()):,}**, < 0: **{int((price < 0).sum()):,}**")
    print(f"- Facturas que empiezan con 'C' (cancelaciones): "
          f"**{int(df[inv_col].str.upper().str.startswith('C').sum()):,}**")
    print(f"- Sin customer ID: **{int(df[cust_col].isna().sum()):,}** "
          f"({100 * df[cust_col].isna().mean():.1f}%)")
    print(f"- Sin descripción: **{int(df[desc_col].isna().sum()):,}**")
    print(f"- Códigos únicos: **{code.nunique():,}** | códigos que NO son producto "
          f"(no cumplen `{VALID_PRODUCT_CODE_REGEX}`): "
          f"**{code[~code.str.match(VALID_PRODUCT_CODE_REGEX, na=False)].nunique():,}** "
          f"→ ej. {sorted(code[~code.str.match(VALID_PRODUCT_CODE_REGEX, na=False)].dropna().unique())[:10]}")
    var = (pd.DataFrame({"c": code, "d": df[desc_col]}).dropna()
           .groupby("c")["d"].nunique())
    var_norm = (pd.DataFrame({"c": code, "d": desc_norm}).dropna()
                .groupby("c")["d"].nunique())
    print(f"- Códigos con más de una escritura de descripción: **{int((var > 1).sum()):,}** "
          f"(después de pasar a mayúsculas: **{int((var_norm > 1).sum()):,}**)")
    print(f"- Países: {df[country_col].nunique()} → top 5: "
          f"{df[country_col].value_counts().head(5).to_dict()}")
    print("\n| Columna | Nulos |\n|---|---|")
    for col, n in df.isna().sum().items():
        print(f"| {col} | {n:,} |")
    print()


if __name__ == "__main__":
    print("# Exploración de fuentes\n")
    for name, path in FILES.items():
        profile(name, path)
