"""Añade a la base los productos de búsquedas por texto. Uso: python buscar.py "smart tv 40 pulgadas" ..."""
import sys

import config
import db
from ml_api import MercadoLibre

sys.stdout.reconfigure(encoding="utf-8")
ml, conn = MercadoLibre(), db.connect()
for q in sys.argv[1:] or config.SEARCHES:
    n = 0
    for r in (ml.get("products/search", site_id="MLM", q=q, limit=50) or {}).get("results", []):
        if r.get("status") != "active":
            continue
        pid = r["id"]
        if not db.known_product(conn, pid):
            info = ml.product(pid)
            if not info:
                continue
            db.save_product(conn, info, q.title())
        found = ml.best_price(pid)
        if found:
            db.save_price(conn, pid, *found)
            n += 1
    conn.commit()
    print(f"{q}: {n} productos")
