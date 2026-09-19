"""Revisa precios y avisa de cualquier bajada. Ejecutar: python main.py"""
import sys

import config
import db
from ml_api import MercadoLibre


def notify(message):
    """Por ahora imprime. Aquí se conectará Telegram más adelante."""
    print(message)


def run():
    ml = MercadoLibre()
    conn = db.connect()
    checked = drops = 0
    seen = set()

    # categorías principales + todas sus subcategorías (televisores, laptops, etc.)
    cats = []
    for cat_id, cat_name in config.CATEGORIES.items():
        cats.append((cat_id, cat_name))
        cats += ml.subcategories(cat_id)

    for cat_id, cat_name in cats:
        print(f"\n== {cat_name} ==")
        for pid in ml.best_sellers(cat_id, config.PRODUCTS_PER_CATEGORY):
            if pid in seen:
                continue
            seen.add(pid)
            if not db.known_product(conn, pid):
                info = ml.product(pid)
                if not info:
                    continue
                db.save_product(conn, info, cat_name)

            found = ml.best_price(pid)
            if found is None:
                continue
            price, orig, rep = found
            checked += 1

            old = db.last_price(conn, pid)
            db.save_price(conn, pid, price, orig, rep)
            conn.commit()

            if old and price < old:
                pct = (old - price) / old * 100
                if pct >= config.MIN_DROP_PCT:
                    drops += 1
                    name, link = db.product_info(conn, pid)
                    notify(f"BAJO {pct:.1f}%: {name}\n  ${old:,.0f} -> ${price:,.0f}\n  {link}")

    print(f"\nRevisados: {checked} | Bajadas detectadas: {drops}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run()
