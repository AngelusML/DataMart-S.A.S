# DataMart S.A.S. — Pipeline ETL con Apache Airflow + Data Warehouse

Pipeline diario que toma las ventas en CSV (fuente diaria + histórico), las limpia,
aplica las reglas de negocio, valida la calidad y las carga en un repositorio
analítico en PostgreSQL. Todo corre en Docker y se orquesta con Airflow.

```
data/raw/*.csv ─► extract_sales_csv ──┐
                  extract_history_csv ┴─► transform_data ─► validate_quality ─► load_to_dw
                                              ─► build_daily_net_revenue ─► verify_dw_counts
```

## Estructura del repositorio

```
├── docker-compose.yml          # 5 servicios: 2 Postgres, init, webserver, scheduler
├── .env.example                # variables de entorno (copiar a .env)
├── config/airflow_variables.json   # Airflow Variables que se importan al iniciar
├── dags/
│   ├── datamart_etl_dag.py     # el DAG (solo orquesta)
│   └── etl/                    # lógica: extract, transform, quality, load, config
├── sql/
│   ├── ddl/01_create_tables.sql    # se ejecuta solo al iniciar postgres-dw
│   └── queries/business_questions.sql  # consultas de la sección 7
├── data/
│   ├── raw/                    # aquí van los CSV de Kaggle
│   └── seeds/category_keywords.csv # reglas para asignar categoría
├── scripts/explore_sources.py  # reporte de exploración de las fuentes
└── docs/                       # decisiones, diagrama del modelo, exploración
```

## Requisitos

- Docker Desktop (o Docker Engine + Compose v2) con **al menos 4 GB de RAM** asignados.
- Dos CSV de Kaggle en `data/raw/`:
  - **Ventas diarias** → https://www.kaggle.com/datasets/carrie1/ecommerce-data — archivo `data.csv` (se deja con ese nombre).
  - **Historial extendido** → https://www.kaggle.com/datasets/gabrielramos87/an-online-shop-business — archivo
    `Sales Transaction v.4a.csv`, que se **renombra a `online_retail_II.csv`**. (El dataset original del enunciado,
    thedevastator/online-retail-transaction-dataset, también funciona sin cambios.)

## Puesta en marcha (≈ 10 minutos)

```bash
# 1. Clonar
git clone <URL_DEL_REPO> && cd datamart-pipeline

# 2. Variables de entorno
cp .env.example .env          # en Windows PowerShell: copy .env.example .env

# 3. Poner los CSV en data/raw/ con estos nombres exactos:
#    data/raw/data.csv
#    data/raw/online_retail_II.csv

# 4. Levantar todo
docker compose up -d
```

`airflow-init` crea el usuario admin, las **Connections** y las **Variables**, y
termina (estado `Exited (0)` es lo correcto). Después arrancan webserver y scheduler.

```bash
docker compose ps        # postgres-airflow, postgres-dw, webserver y scheduler en "healthy/running"
```

Abrir **http://localhost:8080** → usuario/contraseña = `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` del `.env`.

## Verificar Connections y Variables

```bash
docker compose exec airflow-scheduler airflow connections list
docker compose exec airflow-scheduler airflow variables list
docker compose exec airflow-scheduler airflow dags list-runs -d datamart_etl_pipeline
```

O en la UI: **Admin → Connections** (`dw_postgres`, `fs_datamart_raw`) y **Admin → Variables**.

| Tipo | Nombre | Para qué |
|---|---|---|
| Connection | `dw_postgres` | Repositorio analítico destino |
| Connection | `fs_datamart_raw` | Carpeta donde están los CSV (`extra.path`) |
| Variable | `datamart_sales_file` | Nombre del CSV diario |
| Variable | `datamart_history_file` | Nombre del CSV histórico |
| Variable | `datamart_source_timezone` | Zona horaria de las fuentes (`Europe/London`) |
| Variable | `datamart_max_reject_pct` | % máximo de rechazos antes de detener la carga |
| Variable | `datamart_staging_dir` | Carpeta temporal entre tareas |

## Ejecutar el pipeline

El DAG `datamart_etl_pipeline` está activo y corre una vez al levantar el entorno.
Para lanzarlo a mano:

```bash
docker compose exec airflow-scheduler airflow dags trigger datamart_etl_pipeline
```

o en la UI, botón ▶ (Trigger DAG). Tarda unos 2–4 minutos con los archivos completos.

## Verificar que los datos llegaron

Usuario y base son los de `DW_USER` y `DW_DB` en el `.env` (por defecto `datamart` y `datamart_dw`):

```bash
docker compose exec postgres-dw psql -U datamart -d datamart_dw -c "SELECT metric, value FROM etl_run_summary ORDER BY metric;"
```

Correr todas las consultas de negocio:

```bash
# Linux / macOS / Git Bash
docker compose exec -T postgres-dw psql -U datamart -d datamart_dw < sql/queries/business_questions.sql
# Windows PowerShell
Get-Content sql/queries/business_questions.sql | docker compose exec -T postgres-dw psql -U datamart -d datamart_dw
```

También se puede abrir con DBeaver/pgAdmin: host `localhost`, puerto `5433`,
base, usuario y contraseña los de `DW_*` en el `.env`.

## Exploración de las fuentes

```bash
# Linux / macOS / Git Bash
docker compose exec airflow-scheduler python /opt/airflow/scripts/explore_sources.py > docs/exploracion.md
# Windows PowerShell (la primera línea evita tildes rotas)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
docker compose exec airflow-scheduler python /opt/airflow/scripts/explore_sources.py | Out-File -Encoding utf8 docs/exploracion.md
```

## Reiniciar desde cero

```bash
docker compose down -v      # borra contenedores y volúmenes (las tablas se recrean al subir)
docker compose up -d
```

## Documentación

- [docs/DECISIONES.md](docs/DECISIONES.md) — modelo, casos ambiguos, idempotencia
- [docs/GUIA_SUSTENTACION.md](docs/GUIA_SUSTENTACION.md) — resumen para la sustentación
- [docs/modelo_datos.png](docs/modelo_datos.png) — diagrama del modelo de datos
- [Diagrama interactivo en dbdiagram.io](https://dbdiagram.io/d/DataMart-S-A-S-6ae0b7dded134e407e1f525f)
- [docs/modelo_datos.dbml](docs/modelo_datos.dbml) — fuente del diagrama (pegar en dbdiagram.io)
- [docs/diccionario_datos.md](docs/diccionario_datos.md) — diccionario de datos: tablas, columnas, llaves y reglas
- [docs/exploracion.md](docs/exploracion.md) — exploración de las fuentes y hallazgos
- [sql/queries/business_questions.sql](sql/queries/business_questions.sql) — consultas de la sección 7

## Problemas comunes

| Síntoma | Solución |
|---|---|
| `extract_*` falla con *No se encontró el archivo* | Revisar nombres en `data/raw/` y relanzar el DAG |
| El webserver no abre | Esperar 1–2 min; ver `docker compose logs airflow-webserver` |
| Tareas mueren sin error (SIGKILL) | Subir la RAM de Docker a 4–6 GB |
| Cambié el DDL y no se aplica | `docker compose down -v` (el DDL solo corre con volumen vacío) |
