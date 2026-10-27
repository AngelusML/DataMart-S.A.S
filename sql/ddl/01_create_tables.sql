-- =====================================================================
-- DataMart S.A.S. - Repositorio analítico (modelo estrella simple)
-- Se ejecuta automáticamente la primera vez que arranca postgres-dw.
-- =====================================================================

-- ---------- DIMENSIÓN: productos ----------
CREATE TABLE IF NOT EXISTS dim_product (
    product_code          VARCHAR(20)  PRIMARY KEY,          -- normalizado: MAYÚSCULAS, sin espacios
    product_name          VARCHAR(255) NOT NULL,             -- nombre canónico (descripción más frecuente)
    category              VARCHAR(50)  NOT NULL,             -- Electrónica, Hogar, Ropa, Deportes, Papelería, Sin categoría
    description_variants  INTEGER      NOT NULL DEFAULT 1    -- cuántas escrituras distintas tenía en la fuente
);

-- ---------- HECHO: ventas (cantidad > 0 y precio > 0) ----------
CREATE TABLE IF NOT EXISTS fact_sales (
    sale_id                 BIGSERIAL     PRIMARY KEY,
    invoice_no              VARCHAR(20)   NOT NULL,
    product_code            VARCHAR(20)   NOT NULL REFERENCES dim_product(product_code),
    description_raw         VARCHAR(255),                    -- descripción tal como llegó (para auditoría)
    customer_id             VARCHAR(20)   NOT NULL,          -- 'SIN_CLIENTE' cuando no viene
    is_identified_customer  BOOLEAN       NOT NULL,
    country                 VARCHAR(60)   NOT NULL,
    quantity                INTEGER       NOT NULL CHECK (quantity > 0),
    unit_price              NUMERIC(12,3) NOT NULL CHECK (unit_price > 0),
    gross_revenue           NUMERIC(14,2) NOT NULL,          -- quantity * unit_price
    currency                CHAR(3)       NOT NULL DEFAULT 'GBP',
    invoice_ts_utc          TIMESTAMPTZ   NOT NULL,
    invoice_date_utc        DATE          NOT NULL,
    source_system           VARCHAR(30)   NOT NULL           -- 'ventas_diarias' o 'historico'
);

-- ---------- HECHO: devoluciones / ajustes (cantidad <= 0) ----------
CREATE TABLE IF NOT EXISTS fact_returns (
    return_id               BIGSERIAL     PRIMARY KEY,
    invoice_no              VARCHAR(20)   NOT NULL,
    product_code            VARCHAR(20)   NOT NULL REFERENCES dim_product(product_code),
    description_raw         VARCHAR(255),
    customer_id             VARCHAR(20)   NOT NULL,
    is_identified_customer  BOOLEAN       NOT NULL,
    country                 VARCHAR(60)   NOT NULL,
    return_type             VARCHAR(20)   NOT NULL,          -- 'CANCELACION' (factura C...) o 'AJUSTE'
    returned_quantity       INTEGER       NOT NULL CHECK (returned_quantity >= 0),  -- se guarda en positivo
    unit_price              NUMERIC(12,3) NOT NULL CHECK (unit_price > 0),
    return_amount           NUMERIC(14,2) NOT NULL,          -- returned_quantity * unit_price (positivo)
    currency                CHAR(3)       NOT NULL DEFAULT 'GBP',
    invoice_ts_utc          TIMESTAMPTZ   NOT NULL,
    invoice_date_utc        DATE          NOT NULL,
    source_system           VARCHAR(30)   NOT NULL
);

-- ---------- AGREGADO: revenue bruto y neto por producto y día ----------
CREATE TABLE IF NOT EXISTS fact_daily_product_revenue (
    revenue_date        DATE          NOT NULL,
    product_code        VARCHAR(20)   NOT NULL REFERENCES dim_product(product_code),
    units_sold          INTEGER       NOT NULL,
    units_returned      INTEGER       NOT NULL,
    gross_revenue       NUMERIC(14,2) NOT NULL,
    return_amount       NUMERIC(14,2) NOT NULL,
    net_revenue         NUMERIC(14,2) NOT NULL,   -- gross_revenue - return_amount
    PRIMARY KEY (revenue_date, product_code)
);

-- ---------- LOG DE RECHAZOS ----------
CREATE TABLE IF NOT EXISTS etl_rejections (
    rejection_id      BIGSERIAL    PRIMARY KEY,
    source_system     VARCHAR(30)  NOT NULL,
    rejection_reason  VARCHAR(100) NOT NULL,
    invoice_no        VARCHAR(50),
    product_code      VARCHAR(50),
    raw_record        JSONB        NOT NULL,
    load_date         DATE         NOT NULL       -- fecha lógica de la corrida del DAG (ds)
);

-- ---------- RESUMEN DE CADA CORRIDA (auditoría) ----------
CREATE TABLE IF NOT EXISTS etl_run_summary (
    load_date     DATE          NOT NULL,
    metric        VARCHAR(100)  NOT NULL,
    value         BIGINT        NOT NULL,
    PRIMARY KEY (load_date, metric)
);

-- ---------- Índices para las consultas de negocio ----------
CREATE INDEX IF NOT EXISTS ix_sales_date     ON fact_sales (invoice_date_utc);
CREATE INDEX IF NOT EXISTS ix_sales_product  ON fact_sales (product_code);
CREATE INDEX IF NOT EXISTS ix_sales_country  ON fact_sales (country);
CREATE INDEX IF NOT EXISTS ix_returns_date   ON fact_returns (invoice_date_utc);
CREATE INDEX IF NOT EXISTS ix_returns_prod   ON fact_returns (product_code);
CREATE INDEX IF NOT EXISTS ix_rej_reason     ON etl_rejections (source_system, rejection_reason);
