"""Configuración del rastreador de precios."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "prices.db"

SITE_NAME = "Rebajea"
SITE_URL = "https://rebajea.online"
OUT_DIR = BASE_DIR / "docs"

SITE = "MLM"  # Mercado Libre México

# Categorías a vigilar (los más vendidos de cada una). Ver: sites/MLM/categories
CATEGORIES = {
    "MLM1000": "Electrónica, Audio y Video",
    "MLM1051": "Celulares y Teléfonos",
    "MLM1648": "Computación",
    "MLM1574": "Hogar, Muebles y Jardín",
    "MLM1144": "Consolas y Videojuegos",
}

SEARCHES = ["smart tv 32 pulgadas", "smart tv 40 pulgadas", "smart tv 43 pulgadas", "smart tv 50 pulgadas", "smart tv 55 pulgadas",
            "laptop hp 15.6", "laptop lenovo", "laptop asus", "audifonos bluetooth inalambricos", "audifonos tws", "lavadora automatica 19 kg", "refrigerador 2 puertas", "consola playstation 5", "consola xbox series", "nintendo switch"]  # búsquedas por texto extra
PRODUCTS_PER_CATEGORY = 20   # cuántos productos vigilar por categoría
MIN_DROP_PCT = 1.0           # cualquier bajada >= a este % genera alerta
REQUEST_DELAY = 0.3          # segundos entre llamadas a la API


def load_env():
    """Carga variables de .env sin depender de librerías extra."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()
CLIENT_ID = os.environ.get("ML_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET", "")

# Afiliados de Mercado Libre (de tu enlace meli.la)
AFFILIATE = {"matt_tool": "82823235", "matt_word": "cristocontreras2"}
