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
    by_id = dict(cats)

    def category_name(cid):
        """Categoría de un producto nuevo: la más específica que rastreamos; None si es una categoría excluida."""
        path = ml.category_path(cid)
        if not path or path[0][0] in config.EXCLUDED_CATEGORIES:
            return None
        return next((by_id[i] for i, _ in reversed(path) if i in by_id), path[0][1])

    def check(pid, cat_name=None):
        nonlocal checked, drops
        found = ml.best_price(pid)
        if found is None:
            return
        price, orig, rep, is_flash, cid = found
        if not db.known_product(conn, pid):
            cat_name = cat_name or category_name(cid)
            info = cat_name and ml.product(pid)
            if not info:
                return
            db.save_product(conn, info, cat_name)
        checked += 1

        old = db.last_price(conn, pid)
        db.save_price(conn, pid, price, orig, rep, is_flash)
        conn.commit()

        if old and price < old:
            pct = (old - price) / old * 100
            if pct >= config.MIN_DROP_PCT:
                drops += 1
                name, link = db.product_info(conn, pid)
                notify(f"BAJO {pct:.1f}%: {name}\n  ${old:,.0f} -> ${price:,.0f}\n  {link}")

    # primero los productos en promoción/relámpago que ML muestra hoy, aunque no estén entre los más vendidos
    print("\n== Ofertas y relámpago ==")
    for pid in ml.deal_products():
        if time.time() > deadline:
            break
        seen.add(pid)
        check(pid)

    for cat_id, cat_name in cats:
        if time.time() > deadline:
            print("Tiempo agotado; el resto se cubre en la próxima corrida")
            break
        print(f"\n== {cat_name} ==")
        for pid in ml.best_sellers(cat_id, config.PRODUCTS_PER_CATEGORY):
            if pid in seen:
                continue
            seen.add(pid)
            check(pid, cat_name)

    print(f"\nRevisados: {checked} | Bajadas detectadas: {drops}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run()
