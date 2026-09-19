"""Revisa precios y avisa de cualquier bajada. Ejecutar: python main.py"""
import random
import sys
import time

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

    # todas las categorías de ML México y sus subcategorías; las más específicas primero
    # para que cada producto quede en su categoría concreta y no en la general
    cats, names = [], {}
    for top in ml.get("sites/MLM/categories") or []:
        if top["id"] in config.EXCLUDED_CATEGORIES:
            continue
        subs = ml.subcategories(top["id"])
        for cid, name in subs + [(top["id"], top["name"])]:
            names.setdefault(name, []).append(top["name"])
            cats.append((cid, name, top["name"], cid == top["id"]))
    # nombres repetidos ("Accesorios", "Otros") se distinguen con su categoría padre
    cats = [(c, n if len(names[n]) == 1 else f"{n} ({p})", top) for c, n, p, top in cats]
    random.shuffle(cats)  # si se acaba el tiempo, cada día se cubre un tramo distinto
    cats.sort(key=lambda c: c[2])  # estable: subcategorías primero, las generales al final
    cats = [c[:2] for c in cats]
    deadline = time.time() + config.MAX_RUN_MINUTES * 60

    for cat_id, cat_name in cats:
        if time.time() > deadline:
            print("Tiempo agotado; el resto se cubre en la próxima corrida")
            break
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
