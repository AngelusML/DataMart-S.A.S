"""
DAG: datamart_etl_pipeline
Pipeline diario de DataMart S.A.S.

  extract_sales_csv ─┐
                     ├─> transform_data -> validate_quality -> load_to_dw
  extract_history_csv┘        -> build_daily_net_revenue -> verify_dw_counts

- Connections usadas: dw_postgres (destino), fs_datamart_raw (carpeta de los CSV)
- Variables usadas:   datamart_sales_file, datamart_history_file,
                      datamart_source_timezone, datamart_max_reject_pct,
                      datamart_staging_dir
Los datos intermedios viajan entre tareas como archivos .pkl en la carpeta de
staging (no por XCom, porque son cientos de miles de filas).
"""
import logging
import os
import pickle
from datetime import datetime, timedelta

import pandas as pd
from airflow import DAG
from airflow.hooks.base import BaseHook
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

from etl import extract, load, quality, transform
from etl.config import (CATEGORY_SEED_PATH, DW_CONN_ID, FILES_CONN_ID,
                        SOURCE_HISTORY, SOURCE_SALES)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- helpers
def _staging_path(ds: str, name: str) -> str:
    folder = os.path.join(Variable.get("datamart_staging_dir"), ds)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{name}.pkl")


def _save(obj, ds: str, name: str) -> None:
    with open(_staging_path(ds, name), "wb") as f:
        pickle.dump(obj, f)


def _read(ds: str, name: str):
    with open(_staging_path(ds, name), "rb") as f:
        return pickle.load(f)


def _raw_folder() -> str:
    """La ruta de los CSV viene de la Connection fs_datamart_raw (campo extra 'path')."""
    return BaseHook.get_connection(FILES_CONN_ID).extra_dejson["path"]


# ---------------------------------------------------------------- tareas
def extract_sales_csv(ds, **_):
    path = os.path.join(_raw_folder(), Variable.get("datamart_sales_file"))
    _save(extract.read_source_csv(path, SOURCE_SALES), ds, "raw_sales")


def extract_history_csv(ds, **_):
    path = os.path.join(_raw_folder(), Variable.get("datamart_history_file"))
    _save(extract.read_source_csv(path, SOURCE_HISTORY), ds, "raw_history")


def transform_data(ds, **_):
    keywords = pd.read_csv(CATEGORY_SEED_PATH)
    result = transform.transform(
        sales_raw=_read(ds, "raw_sales"),
        history_raw=_read(ds, "raw_history"),
        category_keywords=keywords,
        source_timezone=Variable.get("datamart_source_timezone"),
    )
    for metric, value in result["stats"].items():
        log.info("%s: %s", metric, value)
    _save(result, ds, "clean")


def validate_quality(ds, **_):
    failed = quality.run_quality_checks(
        _read(ds, "clean"), float(Variable.get("datamart_max_reject_pct")))
    if failed:
        raise ValueError(f"Falló la validación de calidad: {failed}")


def load_to_dw(ds, **_):
    conn = PostgresHook(postgres_conn_id=DW_CONN_ID).get_conn()
    try:
        load.load_all(conn, _read(ds, "clean"), load_date=ds)
    finally:
        conn.close()


def build_daily_net_revenue(**_):
    conn = PostgresHook(postgres_conn_id=DW_CONN_ID).get_conn()
    try:
        load.build_daily_revenue(conn)
    finally:
        conn.close()


def verify_dw_counts(ds, **_):
    """Compara lo que quedó en PostgreSQL contra lo que salió de la transformación."""
    clean = _read(ds, "clean")
    expected = {
        "dim_product": len(clean["products"]),
        "fact_sales": len(clean["sales"]),
        "fact_returns": len(clean["returns"]),
        "etl_rejections": len(clean["rejections"]),
    }
    conn = PostgresHook(postgres_conn_id=DW_CONN_ID).get_conn()
    try:
        actual = load.count_rows(conn)
    finally:
        conn.close()
    log.info("Conteos en el DW: %s", actual)
    mismatches = {t: (n, actual[t]) for t, n in expected.items() if actual[t] != n}
    if mismatches or actual["fact_daily_product_revenue"] == 0:
        raise ValueError(f"Conteos no coinciden (esperado, real): {mismatches}")


# ---------------------------------------------------------------- DAG
default_args = {
    "owner": "datamart-data-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    dag_id="datamart_etl_pipeline",
    description="CSV de ventas + histórico -> limpieza -> calidad -> PostgreSQL",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,
    tags=["datamart", "etl"],
) as dag:

    t_extract_sales = PythonOperator(task_id="extract_sales_csv",
                                     python_callable=extract_sales_csv)
    t_extract_history = PythonOperator(task_id="extract_history_csv",
                                       python_callable=extract_history_csv)
    t_transform = PythonOperator(task_id="transform_data",
                                 python_callable=transform_data)
    t_quality = PythonOperator(task_id="validate_quality",
                               python_callable=validate_quality)
    t_load = PythonOperator(task_id="load_to_dw",
                            python_callable=load_to_dw)
    t_daily = PythonOperator(task_id="build_daily_net_revenue",
                             python_callable=build_daily_net_revenue)
    t_verify = PythonOperator(task_id="verify_dw_counts",
                              python_callable=verify_dw_counts)

    [t_extract_sales, t_extract_history] >> t_transform >> t_quality >> t_load >> t_daily >> t_verify
