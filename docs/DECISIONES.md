# Documento de decisiones técnicas
 
> Los números salen de la corrida real del DAG (tabla `etl_run_summary`) y de las consultas de
> `sql/queries/business_questions.sql`.
 
## 1. Arquitectura
 
| Componente | Decisión | Por qué |
|---|---|---|
| Orquestador | Airflow 2.10 con `LocalExecutor` | Un solo nodo, sin Redis/Celery: lo más simple que cumple |
| Metadatos Airflow | `postgres-airflow` | Separado del DW, como pide la prueba |
| Repositorio analítico | `postgres-dw` | Tablas creadas al iniciar con `sql/ddl/` |
| Configuración | Connections y Variables creadas por `airflow-init` | Cero pasos manuales; credenciales solo en `.env` |
| Paso de datos entre tareas | Archivos `.pkl` en una carpeta de staging | XCom no sirve para cientos de miles de filas |
| Carga | `COPY` de PostgreSQL | Mucho más rápido que `INSERT` fila por fila |
 
## 2. Modelo del repositorio analítico
 
Modelo estrella simple con **una dimensión, dos hechos separados y un agregado**:
 
- **`dim_product`**: un registro por código de producto, con nombre canónico y categoría.
- **`fact_sales`**: solo líneas con cantidad > 0 y precio > 0.
- **`fact_returns`**: líneas con cantidad ≤ 0 (cancelaciones y ajustes). La cantidad y el
  monto se guardan **en positivo** para que el neto sea simplemente `bruto − devoluciones`.
- **`fact_daily_product_revenue`**: bruto, devoluciones y **neto por producto y por día**
  (exactamente la regla de negocio de revenue neto).
- **`etl_rejections`**: log de rechazos con motivo, fuente y el registro original en JSON.
- **`etl_run_summary`**: métricas de cada corrida (filas leídas, rechazos por motivo, etc.).
**¿Por qué ventas y devoluciones en tablas separadas?** La prueba exige separarlas. Con dos
tablas no hay forma de sumar por error una devolución como venta, y las columnas tienen
significado claro (`return_type`, `returned_quantity`).
 
**¿Por qué no hay `dim_customer`, `dim_country` ni `dim_date`?** Los clientes y países no
tienen atributos adicionales en las fuentes; crear tablas solo con un ID no aporta. Las
fechas se manejan con `invoice_date_utc` y `DATE_TRUNC`. Se agregarían si el negocio
trae más atributos.
 
## 3. Reglas de calidad (qué se rechaza, qué se corrige)
 
| Problema encontrado | Tratamiento | Dónde queda |
|---|---|---|
| Cantidad ≤ 0 | **Se separa** como devolución/ajuste (`CANCELACION` si la factura empieza con `C`, si no `AJUSTE`) | `fact_returns` |
| Precio = 0 | **Se rechaza** (`precio unitario cero`) | `etl_rejections` |
| Precio < 0 | **Se rechaza** (`precio unitario negativo`) | `etl_rejections` |
| Código que no es producto (`POST`, `D`, `M`, `BANK CHARGES`, `AMAZONFEE`, `gift_...`) | **Se rechaza**: son envíos, descuentos, comisiones o ajustes contables, no productos | `etl_rejections` |
| Código en minúsculas o con espacios | **Se corrige**: mayúsculas y sin espacios | todas |
| Fecha inválida | **Se rechaza** | `etl_rejections` |
| Fecha ambigua (cambio de horario de octubre) | **Se rechaza**; no se puede saber a qué hora UTC corresponde | `etl_rejections` |
| Línea duplicada exacta | **Se rechaza** la copia, se conserva la primera | `etl_rejections` |
| Sin customer ID | **Se corrige**: `SIN_CLIENTE` + bandera `is_identified_customer = false` | facts |
| Sin descripción | Se conserva la línea; el producto toma el nombre de otras líneas del mismo código | `dim_product` |
 
El precio > 0 también se exige en devoluciones: una devolución sin valor monetario no
cambia el revenue neto (son ajustes de inventario tipo *damaged*, *lost*).
 
Un **código de producto válido** es `5 dígitos + hasta 3 letras` (`85123A`, `15056BL`).
 
## 4. Casos ambiguos (sección 5)
 
### 4.1 Transacciones sin customer ID
**Decisión: se incluyen** con `customer_id = 'SIN_CLIENTE'` y `is_identified_customer = false`.
- Son ventas reales que entraron a caja; excluirlas subestimaría el revenue en ~2,1 % (consulta P5).
- La bandera permite separarlas en cualquier análisis por cliente (pregunta 5).
- Impacto: **131.571 líneas**, el **12,4 %** de las 1.062.320 líneas válidas (ventas + devoluciones).
### 4.2 Descripciones con distinta escritura para el mismo código
**Decisión: nombre canónico = la descripción más frecuente del código**, después de
pasarla a MAYÚSCULAS, quitar espacios de los extremos y dejar un solo espacio entre palabras.
Empate → orden alfabético (para que el resultado sea siempre el mismo).
- `CANDLE HOLDER WHITE`, `Candle Holder White` y `candle holder white` quedan como una sola.
- La más frecuente es la que más usa el sistema operacional, normalmente la "oficial".
- La descripción original se guarda en `description_raw` para auditoría y para la pregunta 6.
### 4.3 Solapamiento de fechas entre los dos datasets
**Decisión: la fuente diaria (`data.csv`) tiene prioridad en su periodo.** Del histórico se
descartan los registros que caen **dentro** del rango de fechas de `data.csv` (de su primera a
su última fecha, calculado en cada corrida); lo que queda fuera de ese rango se carga.
- Así nunca se cuenta dos veces la misma venta, sin depender de que los códigos o
  descripciones coincidan exactamente entre fuentes.
- La regla funciona con cualquier combinación de archivos: si los rangos no se cruzan, no se
  descarta nada.
- Registros del histórico excluidos por esta regla: **0**. Las ventas diarias cubren 2010–2011 y
  el histórico entregado (gabrielramos87) 2018–2019, así que los rangos no se cruzan.
- Se eliminaron **10.459 duplicados exactos** en total.
- Además, después de unir, se eliminan duplicados exactos con la clave compuesta
  `(factura, código, cantidad, precio, fecha UTC, cliente)`.
### 4.4 Columnas y formatos distintos entre fuentes
El pipeline acepta los nombres de columna de los tres datasets de Kaggle usados para esta
prueba y los lleva a un nombre estándar:
 
| carrie1 (`data.csv`) | online_retail_II | gabrielramos87 (`Sales Transaction v.4a.csv`) | Columna estándar |
|---|---|---|---|
| `InvoiceNo` | `Invoice` | `TransactionNo` | `invoice_no` |
| `StockCode` | `StockCode` | `ProductNo` | `product_code` |
| `Description` | `Description` | `ProductName` | `description` |
| `UnitPrice` | `Price` | `Price` | `unit_price` |
| `CustomerID` | `Customer ID` | `CustomerNo` | `customer_id` |
| `12/1/2010 8:26` | `2009-12-01 07:45:00` | `12/9/2019` (sin hora) | `invoice_ts_utc` |
 
Cuando la fecha no trae hora se toma como 00:00 hora de Londres. El mapeo está en
`dags/etl/config.py` (`COLUMN_ALIASES`, `DATE_FORMATS`). El archivo que se use se renombra a
`data.csv` u `online_retail_II.csv` según el papel que cumpla (diario o histórico).
 
### 4.5 Zona horaria y moneda
Ambas fuentes son de una tienda del Reino Unido: las fechas se interpretan como
`Europe/London` y se convierten a **UTC** (regla de negocio). La moneda es libra
esterlina (`GBP`), se guarda en la columna `currency` para cuando se agreguen otros países.
 
### 4.6 Categoría de producto (sin API)
La API de productos es opcional y **no se implementó**. Estrategia: archivo estático
`data/seeds/category_keywords.csv` con palabras clave por categoría. Se toma cada palabra
completa del nombre canónico; si coincide con varias categorías gana la de menor
`priority` (Electrónica → Ropa → Deportes → Papelería → Hogar). Sin coincidencia →
`Sin categoría` (29,9 % de los 3.806 productos). El negocio puede mejorar la clasificación editando
el CSV, sin tocar código.
 
## 5. Idempotencia del DAG
 
1. **Carga completa (full refresh) en una sola transacción**: `TRUNCATE ... RESTART IDENTITY`
   de todas las tablas y luego `COPY`. Si algo falla, `ROLLBACK` y el DW queda como estaba.
2. **`RESTART IDENTITY`**: los IDs autoincrementales vuelven a 1 → mismos IDs en cada corrida.
3. **`fact_daily_product_revenue`** se recalcula con `DELETE` + `INSERT ... SELECT`.
4. **Sin `NOW()`**: la fecha de carga es la fecha lógica del DAG (`ds`), no la hora real.
5. **Transformación determinística**: ordenamientos con desempate alfabético.
6. `catchup=False` y `max_active_runs=1`: no hay corridas simultáneas pisándose.
Prueba: correr el DAG dos veces y comparar `SELECT COUNT(*)` y `SUM(net_revenue)`: son iguales.

**Resultado de la prueba (dos corridas seguidas con los mismos archivos):**

| Corrida | ventas | devoluciones | rechazos | revenue_neto | max_id |
|---|---|---|---|---|---|
| 1 | 1.045.104 | 17.216 | 15.939 | 69.887.126,25 | 1.045.104 |
| 2 | 1.045.104 | 17.216 | 15.939 | 69.887.126,25 | 1.045.104 |
 
**Reintentos:** cada tarea tiene `retries=2` con 1 minuto de espera.
**Calidad:** `validate_quality` corre antes de cargar; si falla, no se toca el DW.
`verify_dw_counts` compara al final lo cargado contra lo transformado.
 
## 6. Resultados de la corrida
 
Cada fila leída terminó en exactamente un lugar; no se perdió ningún registro:
 
| Concepto | Filas |
|---|---|
| Leídas de `data.csv` (ventas diarias) | 541.909 |
| Leídas del histórico (gabrielramos87) | 536.350 |
| **Total leído** | **1.078.259** |
| Ventas válidas (`fact_sales`) | 1.045.104 |
| Devoluciones válidas (`fact_returns`) | 17.216 |
| Rechazos (`etl_rejections`) | 15.939 |
| **Total cargado + rechazado** | **1.078.259** |
 
Rechazos por motivo: 10.459 duplicados exactos, 2.995 códigos que no son producto y 2.485
precios en cero. En total son el **1,5 %** de lo leído, por debajo del límite de 10 %
(`datamart_max_reject_pct`). Productos únicos: **3.806**.
 
### Problemas de entorno encontrados
- **Descarga de imágenes bloqueada por el proxy del sistema:** `docker pull` fallaba con
  *TLS handshake timeout*. Se resolvió poniendo *No proxy* en Docker Desktop → Resources →
  Proxies.
- **Docker Hub intermitente para `apache/airflow`:** la imagen se descargó desde el espejo de
  Google (`mirror.gcr.io/apache/airflow:2.10.5`) y se re-etiquetó como `apache/airflow:2.10.5`
  con `docker tag`. El `docker-compose.yml` no cambió.
- **Dataset histórico reemplazado:** el del enunciado (thedevastator) no estaba disponible y
  se usó gabrielramos87, con otros nombres de columna y fecha sin hora. Se resolvió con
  alias de columnas y formatos de fecha adicionales en `config.py`, sin tocar la lógica.
## 7. Pendiente / cómo lo mejoraría
 
- **Carga incremental**: en vez de full refresh, `DELETE` + `INSERT` solo de la fecha del
  archivo diario (partición por `invoice_date_utc`). Con datos estáticos de Kaggle el full
  refresh es más simple y igual de correcto.
- **API de productos** con FastAPI como servicio extra del compose; el DAG la consultaría en
  una tarea `extract_products_api` y reemplazaría el CSV de palabras clave.
- **Pruebas unitarias** con pytest para `transform.py`.
- **Alertas** por correo/Slack cuando falla `validate_quality`.
## 8. Recomendación al equipo de producto
 
**Hallazgo principal:** dos productos concentran el **50,65 %** de todo el dinero devuelto.
El `23166` (MEDIUM CERAMIC TOP STORAGE JAR) suma **£920.757,60** devueltos (29,32 %) y el
`23843` (PAPER CRAFT, LITTLE BIRDIE) **£669.828,65** (21,33 %). El `23843` devolvió el
**100 %** de las unidades que vendió (161.990 de 161.990). Todo indica que no son productos
defectuosos sino pedidos de volumen anormal (decenas de miles de unidades en una sola
factura) que se cancelaron el mismo día.
 
**Recomendaciones:**
 
1. **Control de pedidos atípicos.** Exigir confirmación antes de registrar pedidos que
   superen, por ejemplo, 10 veces la cantidad habitual del producto. Solo dos cancelaciones
   de este tipo explican la mitad de las devoluciones en dinero y distorsionan cualquier
   reporte de devoluciones.
2. **Revisar tres productos con devoluciones anormales.** El `84347` (ROTATING SILVER ANGELS
   T-LIGHT HLDR) devolvió el **99 %** de sus unidades (18.743 de 18.932), el `23113` (PANTRY
   CHOPPING BOARD) el **82 %** y el `47566B` (TEA TIME PARTY BUNTING) el **55 %** de 5.156
   vendidas. Hay que revisar calidad, descripción y fotos en la tienda, y considerar
   pausarlos mientras tanto.
3. **Catálogo de cola larga.** Los 20 productos más vendidos aportan solo el **12,32 %** del
   revenue bruto, entre 3.806 productos. Ningún producto concentra el negocio, así que la
   prioridad es reducir devoluciones más que proteger unos pocos productos estrella.
**Nota sobre los datos:** el histórico (gabrielramos87) parece contener las mismas
transacciones que `data.csv`, con fechas corridas 8 años y precios distintos. Por eso algunas
cantidades aparecen duplicadas (161.990 = 2 × 80.995). Las proporciones de la recomendación
se mantienen.
 
Consulta para verificar los pedidos atípicos:
 
```sql
SELECT 'venta' AS tipo, invoice_no, product_code, quantity AS unidades, invoice_date_utc, source_system
FROM fact_sales WHERE product_code IN ('23843','23166')
UNION ALL
SELECT 'devolucion', invoice_no, product_code, returned_quantity, invoice_date_utc, source_system
FROM fact_returns WHERE product_code IN ('23843','23166')
ORDER BY unidades DESC
LIMIT 8;
```