"""Constantes del pipeline (nada de credenciales aquí: esas viven en Airflow Connections)."""

# IDs de Airflow
DW_CONN_ID = "dw_postgres"          # Connection al repositorio analítico
FILES_CONN_ID = "fs_datamart_raw"   # Connection (tipo fs) con la carpeta de los CSV

# Nombres de las fuentes (se guardan en la columna source_system)
SOURCE_SALES = "ventas_diarias"     # data.csv             -> fuente PRIORITARIA
SOURCE_HISTORY = "historico"        # online_retail_II.csv -> solo aporta fechas FUERA del rango de la diaria

# Columnas estándar a las que se mapean ambas fuentes
STANDARD_COLUMNS = [
    "invoice_no", "product_code", "description", "quantity",
    "invoice_date", "unit_price", "customer_id", "country",
]

# Los nombres de columna se comparan en minúscula y sin espacios/guiones/puntos.
# Ej: "Customer ID" -> "customerid", "InvoiceNo" -> "invoiceno"
# Se aceptan los nombres de los 3 datasets de Kaggle:
#   carrie1/ecommerce-data          InvoiceNo, StockCode, Description, InvoiceDate, UnitPrice, CustomerID
#   online_retail_II                Invoice,   StockCode, Description, InvoiceDate, Price,     Customer ID
#   gabrielramos87/an-online-shop   TransactionNo, ProductNo, ProductName, Date,    Price,     CustomerNo
COLUMN_ALIASES = {
    "invoiceno": "invoice_no",
    "invoice": "invoice_no",
    "transactionno": "invoice_no",
    "stockcode": "product_code",
    "productno": "product_code",
    "description": "description",
    "productname": "description",
    "quantity": "quantity",
    "invoicedate": "invoice_date",
    "date": "invoice_date",
    "unitprice": "unit_price",
    "price": "unit_price",
    "customerid": "customer_id",
    "customerno": "customer_id",
    "country": "country",
}

# Formatos de fecha que se intentan, en orden.
#  - data.csv usa mes/día/año:         12/1/2010 8:26
#  - online_retail_II.csv usa ISO:     2009-12-01 07:45:00
#  - gabrielramos87 solo trae la fecha: 12/9/2019  (se toma como 00:00 hora local)
DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
    "%Y-%m-%d",
]

# Un código de producto válido = 5 dígitos + hasta 3 letras (85123A, 15056BL).
# Lo demás (POST, D, M, BANK CHARGES, AMAZONFEE, gift_0001_20...) son cargos/servicios/ajustes.
VALID_PRODUCT_CODE_REGEX = r"^\d{5}[A-Z]{0,3}$"

UNKNOWN_CUSTOMER = "SIN_CLIENTE"
UNKNOWN_COUNTRY = "Unspecified"
UNKNOWN_CATEGORY = "Sin categoría"
NO_DESCRIPTION = "SIN DESCRIPCION"
CURRENCY = "GBP"

CATEGORY_SEED_PATH = "/opt/airflow/data/seeds/category_keywords.csv"
