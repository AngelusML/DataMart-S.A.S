# Exploración de fuentes

Reporte generado con `scripts/explore_sources.py` sobre los archivos crudos, antes de cualquier limpieza.

## ventas_diarias (data.csv)

- Filas: **541.909** | Columnas: `['InvoiceNo', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'UnitPrice', 'CustomerID', 'Country']`
- Ejemplo de fecha: `12/1/2010 8:26` (mes/día/año, con hora)
- Filas duplicadas exactas: **5.268**
- Cantidad: mín. -80.995, máx. 80.995; <= 0 (devoluciones/ajustes): **10.624**
- Precio: mín. -11.062,06, máx. 38.970,00; = 0: **2.515**, < 0: **2**
- Facturas que empiezan con `C` (cancelaciones): **9.288**
- Sin customer ID: **135.080** (24,9 %)
- Sin descripción: **1.454**
- Códigos únicos: **3.958** | códigos que NO son producto (no cumplen `^\d{5}[A-Z]{0,3}$`): **32** → ej. `AMAZONFEE`, `B`, `BANKCHARGES`, `C2`, `CRUK`, `D`, `DCGS0003`, `DCGS0004`, `DCGS0055`, `DCGS0057`
- Códigos con más de una escritura de descripción: **645** (después de pasar a mayúsculas: **642**)
- Países: **38** → top 5: United Kingdom 495.478, Germany 9.495, France 8.557, EIRE 8.196, Spain 2.533

| Columna | Nulos |
|---|---|
| InvoiceNo | 0 |
| StockCode | 0 |
| Description | 1.454 |
| Quantity | 0 |
| InvoiceDate | 0 |
| UnitPrice | 0 |
| CustomerID | 135.080 |
| Country | 0 |

## historico (online_retail_II.csv)

- Filas: **536.350** | Columnas: `['TransactionNo', 'Date', 'ProductNo', 'ProductName', 'Price', 'Quantity', 'CustomerNo', 'Country']`
- Ejemplo de fecha: `12/9/2019` (mes/día/año, sin hora)
- Filas duplicadas exactas: **5.200**
- Cantidad: mín. -80.995, máx. 80.995; <= 0 (devoluciones/ajustes): **8.585**
- Precio: mín. 5,13, máx. 660,62; = 0: **0**, < 0: **0**
- Facturas que empiezan con `C` (cancelaciones): **8.585**
- Sin customer ID: **55** (0,0 %)
- Sin descripción: **0**
- Códigos únicos: **3.768** | códigos que NO son producto: **0**
- Códigos con más de una escritura de descripción: **0** (después de pasar a mayúsculas: **0**)
- Países: **38** → top 5: United Kingdom 485.095, Germany 10.675, France 10.526, EIRE 8.048, Belgium 2.539

| Columna | Nulos |
|---|---|
| TransactionNo | 0 |
| Date | 0 |
| ProductNo | 0 |
| ProductName | 0 |
| Price | 0 |
| Quantity | 0 |
| CustomerNo | 55 |
| Country | 0 |

## Hallazgos y cómo se trató cada uno

| Hallazgo | Fuente | Tratamiento en el pipeline |
|---|---|---|
| 10.624 líneas con cantidad <= 0 (9.288 facturas con `C`) | ventas_diarias | Se separan en `fact_returns` como `CANCELACION` o `AJUSTE` |
| 8.585 cancelaciones (todas con `C` y cantidad negativa) | historico | Igual: van a `fact_returns` |
| 2.515 precios en cero | ventas_diarias | Se rechazan y quedan en `etl_rejections` con su motivo |
| 2 precios negativos | ventas_diarias | Tienen código `B` (ajuste de deuda), así que se rechazan por código, no por precio |
| 32 códigos que no son productos (`POST`, `D`, `AMAZONFEE`, `BANKCHARGES`...) | ventas_diarias | Se rechazan: son envíos, descuentos, comisiones y ajustes |
| 5.268 y 5.200 filas duplicadas exactas | ambas | Se conserva la primera y las copias se rechazan |
| 135.080 líneas sin customer ID (24,9 %) | ventas_diarias | Se conservan como `SIN_CLIENTE` con la bandera `is_identified_customer` |
| 645 códigos con varias descripciones | ventas_diarias | Nombre canónico = descripción más frecuente, en mayúsculas |
| Nombres de columna y formato de fecha distintos (fecha sin hora) | historico | Alias de columnas y formatos de fecha en `config.py` |

**Por qué las cifras del pipeline son algo menores que las de esta exploración:** la exploración
cuenta sobre el archivo crudo y el pipeline aplica las reglas en orden. Por ejemplo, de las
10.468 filas duplicadas que hay en total, el pipeline rechaza 10.459 como duplicado porque
algunas copias ya habían salido antes por precio cero o código inválido. Lo mismo pasa con las
líneas sin customer ID (131.571 en el pipeline). Las cifras finales están en
`docs/DECISIONES.md`, sección 6.

**El histórico viene prelimpiado.** No tiene precios en cero, códigos inválidos ni descripciones
vacías, y solo 55 filas sin cliente. Sus precios mínimos (5,13) son mucho más altos que en
`data.csv`, así que la fuente usa otra escala de precios.

**Las dos fuentes parecen ser la misma tienda.** Ambas tienen 38 países, el mismo orden de
países principales y la misma cantidad extrema (±80.995 unidades). Esa cantidad es un pedido de
80.995 unidades registrado y cancelado: el mismo caso que aparece en la recomendación al equipo
de producto (producto `23843`).
