"""Configuración del rastreador de precios."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "prices.db"

SITE_NAME = "Rebajea"
SITE_URL = "https://rebajea.online"
GOATCOUNTER = "rebajea"  # código de tu cuenta en goatcounter.com (https://CODIGO.goatcounter.com); vacío = sin estadísticas
CONTACT_EMAIL = ""  # correo público de contacto para las páginas legales (derechos ARCO); vacío = no se muestra
OUT_DIR = BASE_DIR / "docs"

SITE = "MLM"  # Mercado Libre México

# Se vigilan todas las categorías de ML México (main.py las lee de la API), salvo las que no son productos
EXCLUDED_CATEGORIES = {"MLM1743", "MLM1459", "MLM1540"}  # Autos y motos, Inmuebles, Servicios
MAX_RUN_MINUTES = int(os.environ.get("MAX_RUN_MINUTES", 300))  # tope de main.py; al alcanzarlo termina y se publica lo avanzado
RUN_HOURS_UTC = (0, 4, 12, 16, 20)  # horas de las corridas (cron de update.yml): 6, 10, 14, 18 y 22 h en México

SEARCHES = ["smart tv 32 pulgadas", "smart tv 40 pulgadas", "smart tv 43 pulgadas", "smart tv 50 pulgadas", "smart tv 55 pulgadas",
            "laptop hp 15.6", "laptop lenovo", "laptop asus", "audifonos bluetooth inalambricos", "audifonos tws", "lavadora automatica 19 kg", "refrigerador 2 puertas", "consola playstation 5", "consola xbox series", "nintendo switch"]  # búsquedas por texto extra
PRODUCTS_PER_CATEGORY = 20   # cuántos productos vigilar por categoría
TELEGRAM_MIN_PCT = 5         # solo se publican en Telegram bajadas >= a este %
TELEGRAM_MAX_POSTS = 5       # máximo de bajadas publicadas por corrida (las mayores)
SUPER_PCT = 30               # superoferta = relámpago o descuento >= a este % contra el precio tachado
TELEGRAM_MAX_SUPER = 5       # máximo de superofertas publicadas por corrida
MIN_DROP_PCT = 1.0          # cualquier bajada >= a este % genera alerta
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
