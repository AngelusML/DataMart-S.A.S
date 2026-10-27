-- Consultas de negocio (sección 7). Ejecutar contra datamart_dw
-- después de correr el DAG.

-- ---------------------------------------------------------------------
-- P1. Evolución mensual de las ventas netas (descontando devoluciones)
-- ---------------------------------------------------------------------
SELECT DATE_TRUNC('month', revenue_date)::date AS mes,
       SUM(gross_revenue)                       AS revenue_bruto,
       SUM(return_amount)                       AS devoluciones,
       SUM(net_revenue)                         AS revenue_neto
FROM fact_daily_product_revenue
GROUP BY 1
ORDER BY 1;


-- ---------------------------------------------------------------------
-- P2. Categorías con más revenue bruto y mayor proporción de devoluciones
-- ---------------------------------------------------------------------
SELECT p.category                                         AS categoria,
       SUM(d.gross_revenue)                               AS revenue_bruto,
       SUM(d.return_amount)                               AS devoluciones,
       ROUND(100 * SUM(d.return_amount) / NULLIF(SUM(d.gross_revenue), 0), 2) AS pct_devolucion
FROM fact_daily_product_revenue d
JOIN dim_product p ON p.product_code = d.product_code
GROUP BY p.category
ORDER BY revenue_bruto DESC;


-- ---------------------------------------------------------------------
-- P3a. Top 10 productos por revenue neto
-- ---------------------------------------------------------------------
SELECT p.product_code, p.product_name, p.category,
       SUM(d.gross_revenue) AS revenue_bruto,
       SUM(d.return_amount) AS devoluciones,
       SUM(d.net_revenue)   AS revenue_neto
FROM fact_daily_product_revenue d
JOIN dim_product p ON p.product_code = d.product_code
GROUP BY p.product_code, p.product_name, p.category
ORDER BY revenue_neto DESC
LIMIT 10;

-- ---------------------------------------------------------------------
-- P3b. Top 10 productos por tasa de devolución
--      (solo productos con al menos 100 unidades vendidas, para no
--       destacar productos que vendieron 1 unidad y la devolvieron)
-- ---------------------------------------------------------------------
SELECT p.product_code, p.product_name, p.category,
       SUM(d.units_sold)     AS unidades_vendidas,
       SUM(d.units_returned) AS unidades_devueltas,
       ROUND(100.0 * SUM(d.units_returned) / NULLIF(SUM(d.units_sold), 0), 2) AS tasa_devolucion_pct,
       SUM(d.return_amount)  AS monto_devuelto
FROM fact_daily_product_revenue d
JOIN dim_product p ON p.product_code = d.product_code
GROUP BY p.product_code, p.product_name, p.category
HAVING SUM(d.units_sold) >= 100
ORDER BY tasa_devolucion_pct DESC
LIMIT 10;


-- ---------------------------------------------------------------------
-- P4. Países que concentran las transacciones y ticket promedio
--     (ticket = revenue bruto / número de facturas)
-- ---------------------------------------------------------------------
SELECT country                                               AS pais,
       COUNT(DISTINCT invoice_no)                            AS facturas,
       ROUND(100.0 * COUNT(DISTINCT invoice_no)
             / SUM(COUNT(DISTINCT invoice_no)) OVER (), 2)   AS pct_facturas,
       SUM(gross_revenue)                                    AS revenue_bruto,
       ROUND(SUM(gross_revenue) / COUNT(DISTINCT invoice_no), 2) AS ticket_promedio
FROM fact_sales
GROUP BY country
ORDER BY facturas DESC;


-- ---------------------------------------------------------------------
-- P5. Clientes identificados vs transacciones sin customer ID
-- ---------------------------------------------------------------------
WITH ventas AS (
    SELECT is_identified_customer,
           COUNT(DISTINCT invoice_no)                                AS facturas,
           COUNT(*)                                                  AS lineas,
           SUM(gross_revenue)                                        AS revenue_bruto,
           ROUND(SUM(gross_revenue) / COUNT(DISTINCT invoice_no), 2) AS ticket_promedio,
           ROUND(COUNT(*)::numeric / COUNT(DISTINCT invoice_no), 2)  AS lineas_por_factura,
           ROUND(AVG(quantity), 2)                                   AS unidades_promedio_por_linea,
           ROUND(AVG(unit_price), 2)                                 AS precio_promedio
    FROM fact_sales
    GROUP BY is_identified_customer
),
devol AS (
    SELECT is_identified_customer, SUM(return_amount) AS devoluciones
    FROM fact_returns
    GROUP BY is_identified_customer
)
SELECT CASE WHEN v.is_identified_customer THEN 'Cliente identificado'
            ELSE 'Sin customer ID' END AS tipo_cliente,
       v.facturas, v.lineas, v.revenue_bruto, v.ticket_promedio,
       v.lineas_por_factura, v.unidades_promedio_por_linea, v.precio_promedio,
       COALESCE(d.devoluciones, 0) AS devoluciones,
       ROUND(100 * COALESCE(d.devoluciones, 0) / v.revenue_bruto, 2) AS pct_devolucion
FROM ventas v
LEFT JOIN devol d USING (is_identified_customer);


-- ---------------------------------------------------------------------
-- P6a. ¿Cuántos códigos únicos de producto existen?
-- ---------------------------------------------------------------------
SELECT COUNT(*)                                                AS codigos_unicos,
       COUNT(*) FILTER (WHERE description_variants > 1)        AS codigos_con_varios_nombres,
       COUNT(*) FILTER (WHERE product_name = 'SIN DESCRIPCION') AS codigos_sin_descripcion
FROM dim_product;

-- P6b. Productos sin descripción consistente: todas las formas en que se
--      escribió cada código (incluye diferencias de mayúsculas/minúsculas)
WITH todas AS (
    SELECT product_code, description_raw FROM fact_sales
    UNION ALL
    SELECT product_code, description_raw FROM fact_returns
)
SELECT t.product_code,
       p.product_name                              AS nombre_canonico,
       COUNT(DISTINCT t.description_raw)           AS escrituras_distintas,
       COUNT(DISTINCT UPPER(TRIM(t.description_raw))) AS nombres_distintos_normalizados,
       STRING_AGG(DISTINCT t.description_raw, ' | ') AS variantes
FROM todas t
JOIN dim_product p ON p.product_code = t.product_code
WHERE t.description_raw IS NOT NULL
GROUP BY t.product_code, p.product_name
HAVING COUNT(DISTINCT t.description_raw) > 1
ORDER BY escrituras_distintas DESC, t.product_code;


-- ---------------------------------------------------------------------
-- P7. Soporte para la recomendación al equipo de producto:
--     productos que más dinero devuelven (impacto absoluto) junto con
--     su tasa de devolución y su peso en el revenue.
-- ---------------------------------------------------------------------
SELECT p.product_code, p.product_name, p.category,
       SUM(d.gross_revenue)  AS revenue_bruto,
       SUM(d.return_amount)  AS monto_devuelto,
       ROUND(100 * SUM(d.return_amount) / NULLIF(SUM(d.gross_revenue), 0), 2) AS pct_devuelto,
       ROUND(100 * SUM(d.return_amount)
             / SUM(SUM(d.return_amount)) OVER (), 2) AS pct_del_total_devuelto
FROM fact_daily_product_revenue d
JOIN dim_product p ON p.product_code = d.product_code
GROUP BY p.product_code, p.product_name, p.category
ORDER BY monto_devuelto DESC
LIMIT 15;

-- P7b. Concentración: ¿qué % del revenue bruto aportan los 20 productos top?
WITH ranking AS (
    SELECT product_code, SUM(gross_revenue) AS rev,
           ROW_NUMBER() OVER (ORDER BY SUM(gross_revenue) DESC) AS pos
    FROM fact_daily_product_revenue
    GROUP BY product_code
)
SELECT ROUND(100 * SUM(rev) FILTER (WHERE pos <= 20) / SUM(rev), 2) AS pct_revenue_top20,
       COUNT(*)                                                   AS total_productos
FROM ranking;


-- ---------------------------------------------------------------------
-- VALIDACIÓN DEL PIPELINE
-- ---------------------------------------------------------------------
-- Resumen de la última corrida
SELECT metric, value FROM etl_run_summary ORDER BY metric;

-- Rechazos por motivo y fuente
SELECT source_system, rejection_reason, COUNT(*) AS registros
FROM etl_rejections
GROUP BY 1, 2
ORDER BY 3 DESC;

-- Rango de fechas cargadas por fuente
SELECT source_system, MIN(invoice_ts_utc), MAX(invoice_ts_utc), COUNT(*)
FROM fact_sales
GROUP BY source_system;

-- Productos por categoría (% de productos sin categoría, sección 4.6 de DECISIONES.md)
SELECT category, COUNT(*) AS productos,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM dim_product
GROUP BY category
ORDER BY productos DESC;

-- % del revenue bruto que viene de ventas sin customer ID (sección 4.1 de DECISIONES.md)
SELECT ROUND(100.0 * SUM(gross_revenue) FILTER (WHERE NOT is_identified_customer)
             / SUM(gross_revenue), 1) AS pct_revenue_sin_cliente
FROM fact_sales;

-- Prueba de idempotencia: correr antes y después de relanzar el DAG; los 5 valores
-- deben ser idénticos (sección 5 de DECISIONES.md)
SELECT (SELECT COUNT(*) FROM fact_sales)                       AS ventas,
       (SELECT COUNT(*) FROM fact_returns)                     AS devoluciones,
       (SELECT COUNT(*) FROM etl_rejections)                   AS rechazos,
       (SELECT SUM(net_revenue) FROM fact_daily_product_revenue) AS revenue_neto,
       (SELECT MAX(sale_id) FROM fact_sales)                   AS max_id;
