# Diccionario de datos — repositorio analítico `datamart_dw`

Modelo estrella simple: una dimensión (`dim_product`), dos tablas de hechos separadas
(`fact_sales` y `fact_returns`), un agregado diario (`fact_daily_product_revenue`) y dos
tablas de auditoría del pipeline (`etl_rejections` y `etl_run_summary`).
Definición completa en `sql/ddl/01_create_tables.sql`.
Diagrama: [`docs/modelo_datos.png`](modelo_datos.png) · [versión interactiva en dbdiagram.io](https://dbdiagram.io/d/DataMart-S-A-S-6ae0b7dded134e407e1f525f).

## 1. Resumen de tablas

| Tabla | Tipo | Una fila representa | Llave primaria | Se relaciona con | Filas cargadas |
|---|---|---|---|---|---|
| `dim_product` | Dimensión | Un producto (código único) | `product_code` | Las 3 tablas de hechos (1 a muchos) | 3.806 |
| `fact_sales` | Hecho | Una línea de factura vendida (cantidad > 0 y precio > 0) | `sale_id` | `dim_product` por `product_code` | 1.045.104 |
| `fact_returns` | Hecho | Una línea de devolución o ajuste (cantidad <= 0) | `return_id` | `dim_product` por `product_code` | 17.216 |
| `fact_daily_product_revenue` | Agregado | Un producto en un día: bruto, devoluciones y neto | `revenue_date` + `product_code` | `dim_product` por `product_code` | Según los días con movimiento |
| `etl_rejections` | Auditoría | Un registro rechazado, con su motivo y su fuente | `rejection_id` | Ninguna | 15.939 |
| `etl_run_summary` | Auditoría | Una métrica de la última corrida del DAG | `load_date` + `metric` | Ninguna | 11 |

**Relaciones:** `dim_product.product_code` (1) → (muchos) `fact_sales.product_code`,
`fact_returns.product_code` y `fact_daily_product_revenue.product_code`.
Las tablas `etl_` no se relacionan con las demás porque registran el funcionamiento del
pipeline, no el negocio.

## 2. Diccionario de columnas

**Llave:** PK = llave primaria · FK = llave foránea · — = ninguna.
**Nulo:** No = la columna siempre tiene valor. La columna *Ejemplo* muestra valores ilustrativos del formato de cada dato.

| Tabla | Columna | Tipo | Llave | Nulo | Descripción | Ejemplo |
|---|---|---|---|---|---|---|
| `dim_product` | `product_code` | VARCHAR(20) | PK | No | Código del producto normalizado: mayúsculas y sin espacios | `85123A` |
| `dim_product` | `product_name` | VARCHAR(255) | — | No | Nombre canónico: la descripción más frecuente del código, en mayúsculas | `WHITE HANGING HEART T-LIGHT HOLDER` |
| `dim_product` | `category` | VARCHAR(50) | — | No | Categoría asignada por palabras clave: Electrónica, Hogar, Ropa, Deportes, Papelería o Sin categoría | `Hogar` |
| `dim_product` | `description_variants` | INTEGER | — | No | Cuántos nombres distintos tuvo el código en las fuentes | `2` |
| `fact_sales` | `sale_id` | BIGSERIAL | PK | No | Identificador autoincremental de la línea de venta | `1` |
| `fact_sales` | `invoice_no` | VARCHAR(20) | — | No | Número de factura | `536365` |
| `fact_sales` | `product_code` | VARCHAR(20) | FK → `dim_product` | No | Producto vendido | `85123A` |
| `fact_sales` | `description_raw` | VARCHAR(255) | — | Sí | Descripción tal como llegó en la fuente (auditoría) | `White Hanging Heart T-Light Holder` |
| `fact_sales` | `customer_id` | VARCHAR(20) | — | No | Cliente; `SIN_CLIENTE` cuando la fuente no lo trae | `17850` |
| `fact_sales` | `is_identified_customer` | BOOLEAN | — | No | `true` si el cliente venía en la fuente | `true` |
| `fact_sales` | `country` | VARCHAR(60) | — | No | País del cliente | `United Kingdom` |
| `fact_sales` | `quantity` | INTEGER | — | No | Unidades vendidas (siempre > 0) | `6` |
| `fact_sales` | `unit_price` | NUMERIC(12,3) | — | No | Precio unitario (siempre > 0) | `2.550` |
| `fact_sales` | `gross_revenue` | NUMERIC(14,2) | — | No | Revenue bruto: `quantity × unit_price` | `15.30` |
| `fact_sales` | `currency` | CHAR(3) | — | No | Moneda | `GBP` |
| `fact_sales` | `invoice_ts_utc` | TIMESTAMPTZ | — | No | Fecha y hora de la factura convertida a UTC | `2010-12-01 08:26:00+00` |
| `fact_sales` | `invoice_date_utc` | DATE | — | No | Solo la fecha en UTC, para agrupar por día o mes | `2010-12-01` |
| `fact_sales` | `source_system` | VARCHAR(30) | — | No | Fuente de origen: `ventas_diarias` o `historico` | `ventas_diarias` |
| `fact_returns` | `return_id` | BIGSERIAL | PK | No | Identificador autoincremental de la línea de devolución | `1` |
| `fact_returns` | `invoice_no` | VARCHAR(20) | — | No | Número de factura; las cancelaciones empiezan con `C` | `C536379` |
| `fact_returns` | `product_code` | VARCHAR(20) | FK → `dim_product` | No | Producto devuelto | `22423` |
| `fact_returns` | `description_raw` | VARCHAR(255) | — | Sí | Descripción tal como llegó en la fuente | `REGENCY CAKESTAND 3 TIER` |
| `fact_returns` | `customer_id` | VARCHAR(20) | — | No | Cliente; `SIN_CLIENTE` cuando no viene | `14527` |
| `fact_returns` | `is_identified_customer` | BOOLEAN | — | No | `true` si el cliente venía en la fuente | `true` |
| `fact_returns` | `country` | VARCHAR(60) | — | No | País del cliente | `United Kingdom` |
| `fact_returns` | `return_type` | VARCHAR(20) | — | No | `CANCELACION` si la factura empieza con `C`; `AJUSTE` en otro caso | `CANCELACION` |
| `fact_returns` | `returned_quantity` | INTEGER | — | No | Unidades devueltas, guardadas en positivo | `1` |
| `fact_returns` | `unit_price` | NUMERIC(12,3) | — | No | Precio unitario (siempre > 0) | `12.750` |
| `fact_returns` | `return_amount` | NUMERIC(14,2) | — | No | Monto devuelto en positivo: `returned_quantity × unit_price` | `12.75` |
| `fact_returns` | `currency` | CHAR(3) | — | No | Moneda | `GBP` |
| `fact_returns` | `invoice_ts_utc` | TIMESTAMPTZ | — | No | Fecha y hora de la devolución en UTC | `2010-12-01 09:41:00+00` |
| `fact_returns` | `invoice_date_utc` | DATE | — | No | Solo la fecha en UTC | `2010-12-01` |
| `fact_returns` | `source_system` | VARCHAR(30) | — | No | Fuente de origen | `ventas_diarias` |
| `fact_daily_product_revenue` | `revenue_date` | DATE | PK | No | Día (UTC) | `2010-12-01` |
| `fact_daily_product_revenue` | `product_code` | VARCHAR(20) | PK, FK → `dim_product` | No | Producto | `85123A` |
| `fact_daily_product_revenue` | `units_sold` | INTEGER | — | No | Unidades vendidas ese día | `454` |
| `fact_daily_product_revenue` | `units_returned` | INTEGER | — | No | Unidades devueltas ese día | `0` |
| `fact_daily_product_revenue` | `gross_revenue` | NUMERIC(14,2) | — | No | Revenue bruto del día | `1157.70` |
| `fact_daily_product_revenue` | `return_amount` | NUMERIC(14,2) | — | No | Monto devuelto del día | `0.00` |
| `fact_daily_product_revenue` | `net_revenue` | NUMERIC(14,2) | — | No | Revenue neto: `gross_revenue − return_amount` (regla de negocio) | `1157.70` |
| `etl_rejections` | `rejection_id` | BIGSERIAL | PK | No | Identificador del rechazo | `1` |
| `etl_rejections` | `source_system` | VARCHAR(30) | — | No | Fuente de donde vino el registro | `ventas_diarias` |
| `etl_rejections` | `rejection_reason` | VARCHAR(100) | — | No | Motivo del rechazo | `precio unitario cero` |
| `etl_rejections` | `invoice_no` | VARCHAR(50) | — | Sí | Factura original, sin limpiar | `536414` |
| `etl_rejections` | `product_code` | VARCHAR(50) | — | Sí | Código original, sin limpiar | `22139` |
| `etl_rejections` | `raw_record` | JSONB | — | No | El registro completo tal como llegó | `{"quantity": "56", ...}` |
| `etl_rejections` | `load_date` | DATE | — | No | Fecha lógica de la corrida del DAG | `2026-10-26` |
| `etl_run_summary` | `load_date` | DATE | PK | No | Fecha lógica de la corrida del DAG | `2026-10-26` |
| `etl_run_summary` | `metric` | VARCHAR(100) | PK | No | Nombre de la métrica | `ventas_validas` |
| `etl_run_summary` | `value` | BIGINT | — | No | Valor de la métrica | `1045104` |

## 3. Reglas que garantiza la base de datos

| Regla | Cómo se garantiza |
|---|---|
| Una venta siempre tiene cantidad y precio positivos | `CHECK (quantity > 0)` y `CHECK (unit_price > 0)` en `fact_sales` |
| Una devolución se guarda en positivo | `CHECK (returned_quantity >= 0)` en `fact_returns` |
| Todo producto de un hecho existe en la dimensión | Llaves foráneas hacia `dim_product` |
| No hay dos filas para el mismo producto y día | Llave primaria compuesta en `fact_daily_product_revenue` |
| Consultas rápidas por fecha, producto y país | Índices `ix_sales_date`, `ix_sales_product`, `ix_sales_country`, `ix_returns_date`, `ix_returns_prod` |
