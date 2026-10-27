"""CARGA al repositorio analítico (PostgreSQL).

IDEMPOTENCIA: cada corrida hace TRUNCATE de las tablas y las vuelve a llenar
dentro de UNA sola transacción. Si algo falla en medio, se hace ROLLBACK y
el repositorio queda como estaba. Correr el DAG dos veces con los mismos
archivos deja exactamente los mismos datos (los IDs se reinician con
RESTART IDENTITY).
"""
import io
import logging

import pandas as pd

log = logging.getLogger(__name__)

TABLES_IN_LOAD_ORDER = ["dim_product", "fact_sales", "fact_returns", "etl_rejections"]


def copy_dataframe(cursor, df: pd.DataFrame, table: str) -> None:
    """Carga rápida con COPY (mucho más veloz que INSERT fila por fila)."""
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False)
    buffer.seek(0)
    columns = ", ".join(df.columns)
    cursor.copy_expert(
        f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv, NULL '')", buffer)
    log.info("Cargadas %s filas en %s", len(df), table)


def load_all(conn, data: dict, load_date: str) -> None:
    rejections = data["rejections"].copy()
    rejections["load_date"] = load_date
    summary = pd.DataFrame(
        [(load_date, metric, value) for metric, value in data["stats"].items()],
        columns=["load_date", "metric", "value"])

    with conn:                       # commit al final, rollback si hay excepción
        with conn.cursor() as cur:
            cur.execute("""
                TRUNCATE fact_daily_product_revenue, fact_sales, fact_returns,
                         dim_product, etl_rejections, etl_run_summary
                RESTART IDENTITY
            """)
            copy_dataframe(cur, data["products"], "dim_product")
            copy_dataframe(cur, data["sales"], "fact_sales")
            copy_dataframe(cur, data["returns"], "fact_returns")
            copy_dataframe(cur, rejections, "etl_rejections")
            copy_dataframe(cur, summary, "etl_run_summary")


BUILD_DAILY_REVENUE_SQL = """
DELETE FROM fact_daily_product_revenue;

INSERT INTO fact_daily_product_revenue
    (revenue_date, product_code, units_sold, units_returned,
     gross_revenue, return_amount, net_revenue)
SELECT revenue_date,
       product_code,
       SUM(units_sold),
       SUM(units_returned),
       SUM(gross_revenue),
       SUM(return_amount),
       SUM(gross_revenue) - SUM(return_amount) AS net_revenue
FROM (
    SELECT invoice_date_utc AS revenue_date, product_code,
           quantity AS units_sold, 0 AS units_returned,
           gross_revenue, 0 AS return_amount
    FROM fact_sales
    UNION ALL
    SELECT invoice_date_utc, product_code,
           0, returned_quantity,
           0, return_amount
    FROM fact_returns
) movimientos
GROUP BY revenue_date, product_code;
"""


def build_daily_revenue(conn) -> None:
    """Revenue neto = bruto - devoluciones del MISMO código en el MISMO día (UTC)."""
    with conn:
        with conn.cursor() as cur:
            cur.execute(BUILD_DAILY_REVENUE_SQL)
            log.info("fact_daily_product_revenue: %s filas", cur.rowcount)


def count_rows(conn) -> dict:
    tables = TABLES_IN_LOAD_ORDER + ["fact_daily_product_revenue"]
    with conn.cursor() as cur:
        result = {}
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            result[table] = cur.fetchone()[0]
    return result
