"""TRANSFORMACIÓN: une las dos fuentes, aplica las reglas de negocio y separa
ventas, devoluciones, productos y rechazos.

Cada regla es un paso con nombre. Si un registro no cumple, va al log de
rechazos con el MOTIVO y la FUENTE (función `_reject`).
"""
import logging
import re

import pandas as pd

from etl.config import (
    CURRENCY, DATE_FORMATS, NO_DESCRIPTION, SOURCE_HISTORY, SOURCE_SALES,
    STANDARD_COLUMNS, UNKNOWN_CATEGORY, UNKNOWN_COUNTRY, UNKNOWN_CUSTOMER,
    VALID_PRODUCT_CODE_REGEX,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
class RejectionCollector:
    """Junta los registros rechazados con su motivo."""

    def __init__(self):
        self.parts = []

    def reject(self, df: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
        """Saca del DataFrame las filas donde mask=True, las guarda como rechazo
        y devuelve el DataFrame sin ellas."""
        rejected = df[mask]
        if len(rejected):
            log.info("Rechazados %s registros: %s", len(rejected), reason)
            raw = rejected[[f"raw_{c}" for c in STANDARD_COLUMNS]].copy()
            raw.columns = STANDARD_COLUMNS
            self.parts.append(pd.DataFrame({
                "source_system": rejected["source_system"].values,
                "rejection_reason": reason,
                "invoice_no": rejected["raw_invoice_no"].values,
                "product_code": rejected["raw_product_code"].values,
                "raw_record": raw.to_json(orient="records", lines=True,
                                          force_ascii=False).splitlines(),
            }))
        return df[~mask].copy()

    def result(self) -> pd.DataFrame:
        if not self.parts:
            return pd.DataFrame(columns=["source_system", "rejection_reason",
                                         "invoice_no", "product_code", "raw_record"])
        return pd.concat(self.parts, ignore_index=True)


def parse_dates(values: pd.Series) -> pd.Series:
    """Prueba cada formato de DATE_FORMATS y se queda con el primero que funcione."""
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        pending = result.isna() & values.notna()
        if not pending.any():
            break
        result[pending] = pd.to_datetime(values[pending], format=fmt, errors="coerce")
    return result


def normalize_text(values: pd.Series) -> pd.Series:
    """MAYÚSCULAS, sin espacios al inicio/fin y un solo espacio entre palabras."""
    return values.str.upper().str.strip().str.replace(r"\s+", " ", regex=True)


def clean_customer_id(values: pd.Series) -> pd.Series:
    """'17850.0' -> '17850'. Vacío -> NaN."""
    cleaned = values.str.strip().str.replace(r"\.0+$", "", regex=True)
    return cleaned.where(cleaned.notna() & (cleaned != ""))


# --------------------------------------------------------------------------
# Paso principal
# --------------------------------------------------------------------------
def transform(sales_raw: pd.DataFrame, history_raw: pd.DataFrame,
              category_keywords: pd.DataFrame, source_timezone: str) -> dict:
    """Devuelve un dict con: sales, returns, products, rejections, stats."""
    stats = {
        f"filas_leidas_{SOURCE_SALES}": len(sales_raw),
        f"filas_leidas_{SOURCE_HISTORY}": len(history_raw),
    }
    rejections = RejectionCollector()

    # 0) Unir fuentes. La fuente diaria va primero (tiene prioridad en duplicados).
    df = pd.concat([sales_raw, history_raw], ignore_index=True)
    for col in STANDARD_COLUMNS:                     # copia del valor original para auditoría
        df[f"raw_{col}"] = df[col]

    # 1) Limpieza de textos
    df["invoice_no"] = df["invoice_no"].str.strip().str.upper()
    # Regla de negocio: códigos en MAYÚSCULAS y sin espacios
    df["product_code"] = df["product_code"].str.upper().str.replace(r"\s+", "", regex=True)
    df["description_raw"] = df["description"].str.strip()
    df["country"] = df["country"].str.strip().fillna(UNKNOWN_COUNTRY)

    # 2) Campos obligatorios
    df = rejections.reject(df, df["invoice_no"].isna() | (df["invoice_no"] == ""),
                           "factura vacía")
    df = rejections.reject(df, df["product_code"].isna() | (df["product_code"] == ""),
                           "código de producto vacío")

    # 3) Números
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df = rejections.reject(df, df["quantity"].isna(), "cantidad no numérica")
    df = rejections.reject(df, df["unit_price"].isna(), "precio no numérico")
    df["quantity"] = df["quantity"].astype(int)

    # 4) Fechas -> UTC (las fuentes están en hora local del Reino Unido)
    local_ts = parse_dates(df["invoice_date"])
    df = rejections.reject(df, local_ts.isna(), "fecha inválida")
    local_ts = local_ts[df.index]
    df["invoice_ts_utc"] = (local_ts.dt.tz_localize(source_timezone, ambiguous="NaT",
                                                     nonexistent="shift_forward")
                            .dt.tz_convert("UTC"))
    df = rejections.reject(df, df["invoice_ts_utc"].isna(),
                           "fecha ambigua por cambio de horario")
    df["invoice_date_utc"] = df["invoice_ts_utc"].dt.date

    # 5) Solapamiento entre fuentes: la fuente diaria manda en su periodo.
    #    Del histórico se descartan las filas que caen DENTRO del rango de fechas de la
    #    fuente diaria (de su primera a su última fecha). Lo que queda fuera se conserva.
    sales_ts = df.loc[df["source_system"] == SOURCE_SALES, "invoice_ts_utc"]
    sales_start, sales_end = sales_ts.min(), sales_ts.max()
    overlap = ((df["source_system"] == SOURCE_HISTORY)
               & (df["invoice_ts_utc"] >= sales_start)
               & (df["invoice_ts_utc"] <= sales_end))
    stats["historico_excluido_por_solapamiento"] = int(overlap.sum())
    log.info("Rango de la fuente diaria: %s a %s. Histórico excluido por solapamiento: %s filas",
             sales_start, sales_end, int(overlap.sum()))
    df = df[~overlap].copy()

    # 6) Códigos que no son productos (envíos, descuentos, comisiones, ajustes manuales)
    invalid_code = ~df["product_code"].str.match(VALID_PRODUCT_CODE_REGEX)
    df = rejections.reject(df, invalid_code,
                           "código no corresponde a un producto (cargo/servicio/ajuste)")

    # 7) Regla de negocio: el precio no puede ser cero ni negativo
    df = rejections.reject(df, df["unit_price"] < 0, "precio unitario negativo")
    df = rejections.reject(df, df["unit_price"] == 0, "precio unitario cero")

    # 8) Duplicados exactos (misma factura, producto, cantidad, precio, fecha y cliente)
    df["customer_id"] = clean_customer_id(df["customer_id"])
    dup_key = ["invoice_no", "product_code", "quantity", "unit_price",
               "invoice_ts_utc", "customer_id"]
    df = rejections.reject(df, df.duplicated(subset=dup_key, keep="first"),
                           "registro duplicado")

    # 9) Clientes sin ID: se conservan con un valor explícito y una bandera
    df["is_identified_customer"] = df["customer_id"].notna()
    df["customer_id"] = df["customer_id"].fillna(UNKNOWN_CUSTOMER)
    df["currency"] = CURRENCY

    # 10) Productos: nombre canónico y categoría
    products = build_products(df, category_keywords)

    # 11) Regla de negocio: cantidad <= 0 es devolución/ajuste, no venta
    is_sale = df["quantity"] > 0
    sales = df[is_sale].copy()
    returns = df[~is_sale].copy()

    sales["gross_revenue"] = (sales["quantity"] * sales["unit_price"]).round(2)

    returns["return_type"] = returns["invoice_no"].str.startswith("C").map(
        {True: "CANCELACION", False: "AJUSTE"})
    returns["returned_quantity"] = returns["quantity"].abs()
    returns["return_amount"] = (returns["returned_quantity"] * returns["unit_price"]).round(2)

    rej = rejections.result()
    stats["ventas_validas"] = len(sales)
    stats["devoluciones_validas"] = len(returns)
    stats["productos_unicos"] = len(products)
    stats["clientes_sin_id_lineas"] = int((~df["is_identified_customer"]).sum())
    stats["rechazos_total"] = len(rej)
    for reason, count in rej["rejection_reason"].value_counts().items():
        stats[f"rechazo: {reason}"] = int(count)

    sales_cols = ["invoice_no", "product_code", "description_raw", "customer_id",
                  "is_identified_customer", "country", "quantity", "unit_price",
                  "gross_revenue", "currency", "invoice_ts_utc", "invoice_date_utc",
                  "source_system"]
    return_cols = ["invoice_no", "product_code", "description_raw", "customer_id",
                   "is_identified_customer", "country", "return_type",
                   "returned_quantity", "unit_price", "return_amount", "currency",
                   "invoice_ts_utc", "invoice_date_utc", "source_system"]

    return {
        "sales": sales[sales_cols].reset_index(drop=True),
        "returns": returns[return_cols].reset_index(drop=True),
        "products": products,
        "rejections": rej,
        "stats": stats,
    }


def build_products(df: pd.DataFrame, category_keywords: pd.DataFrame) -> pd.DataFrame:
    """Una fila por código.
    - Nombre canónico = descripción normalizada MÁS FRECUENTE del código
      (empate -> orden alfabético). Si nunca tuvo descripción -> 'SIN DESCRIPCION'.
    - description_variants = cuántos nombres distintos (ya normalizados) tuvo.
    - Categoría = por palabras clave del archivo data/seeds/category_keywords.csv
    """
    desc = pd.DataFrame({"product_code": df["product_code"],
                         "name": normalize_text(df["description_raw"])})
    desc = desc[desc["name"].notna() & (desc["name"] != "")]

    counts = desc.groupby(["product_code", "name"]).size().reset_index(name="n")
    counts = counts.sort_values(["product_code", "n", "name"], ascending=[True, False, True])
    canonical = counts.drop_duplicates("product_code")[["product_code", "name"]]
    variants = counts.groupby("product_code").size().rename("description_variants")

    products = pd.DataFrame({"product_code": sorted(df["product_code"].unique())})
    products = products.merge(canonical, on="product_code", how="left")
    products = products.merge(variants, on="product_code", how="left")
    products["product_name"] = products["name"].fillna(NO_DESCRIPTION)
    products["description_variants"] = products["description_variants"].fillna(0).astype(int)
    products["category"] = products["product_name"].map(
        lambda name: assign_category(name, category_keywords))
    return products[["product_code", "product_name", "category", "description_variants"]]


def assign_category(product_name: str, category_keywords: pd.DataFrame) -> str:
    """Busca palabras completas del nombre en el archivo de palabras clave.
    Gana la categoría con menor 'priority' (1 = Electrónica ... 5 = Hogar)."""
    words = set(re.findall(r"[A-Z0-9\-]+", product_name.upper()))
    matches = category_keywords[category_keywords["keyword"].isin(words)]
    if matches.empty:
        return UNKNOWN_CATEGORY
    return matches.sort_values("priority").iloc[0]["category"]
