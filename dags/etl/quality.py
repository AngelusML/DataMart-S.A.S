"""VALIDACIÓN DE CALIDAD: se ejecuta ANTES de cargar. Si algo falla, la tarea
falla y no se carga nada al repositorio analítico."""
import logging

import pandas as pd

from etl.config import VALID_PRODUCT_CODE_REGEX

log = logging.getLogger(__name__)


def run_quality_checks(data: dict, max_reject_pct: float) -> list:
    """Devuelve la lista de checks que FALLARON (vacía = todo bien)."""
    sales, returns = data["sales"], data["returns"]
    products, rejections = data["products"], data["rejections"]
    product_codes = set(products["product_code"])

    total_considered = len(sales) + len(returns) + len(rejections)
    reject_pct = 100 * len(rejections) / total_considered if total_considered else 0

    checks = {
        "hay ventas para cargar": len(sales) > 0,
        "ventas: cantidad > 0": bool((sales["quantity"] > 0).all()),
        "ventas: precio > 0": bool((sales["unit_price"] > 0).all()),
        "devoluciones: precio > 0": bool((returns["unit_price"] > 0).all()),
        "devoluciones: cantidad devuelta >= 0": bool((returns["returned_quantity"] >= 0).all()),
        "sin nulos en columnas clave (ventas)": not sales[
            ["invoice_no", "product_code", "customer_id", "country", "invoice_ts_utc"]
        ].isna().any().any(),
        "sin nulos en columnas clave (devoluciones)": not returns[
            ["invoice_no", "product_code", "customer_id", "country", "invoice_ts_utc"]
        ].isna().any().any(),
        "códigos normalizados (mayúsculas, sin espacios)": bool(
            products["product_code"].str.match(VALID_PRODUCT_CODE_REGEX).all()),
        "productos sin duplicar": products["product_code"].is_unique,
        "todo código de ventas existe en dim_product": set(sales["product_code"]) <= product_codes,
        "todo código de devoluciones existe en dim_product": set(returns["product_code"]) <= product_codes,
        "fechas en UTC": str(sales["invoice_ts_utc"].dt.tz) == "UTC",
        f"rechazos <= {max_reject_pct}% (actual {reject_pct:.2f}%)": reject_pct <= max_reject_pct,
    }

    failed = []
    for name, passed in checks.items():
        log.info("[%s] %s", "OK " if passed else "FALLA", name)
        if not passed:
            failed.append(name)
    return failed
