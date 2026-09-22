"""Revisa precios y avisa de cualquier bajada. Ejecutar: python main.py"""
import html
import os
import random
import sys
import time
from urllib.parse import urlencode

import requests

import config
import db
from ml_api import MercadoLibre


def notify(message):
    """Por ahora imprime. Aquí se conectará Telegram más adelante."""
    print(message)


def is_super(price, orig, flash):
    """Superoferta: relámpago, o descuento >= SUPER_PCT contra el precio tachado."""
    return bool(flash) or bool(orig and orig > price and (orig - price) / orig * 100 >= config.SUPER_PCT)


def telegram(conn, hits, supers):
    """Publica en el canal las superofertas nuevas y las mayores bajadas (si hay TELEGRAM_TOKEN y TELEGRAM_CHAT)."""
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT")
    if not (token and chat):
        return
    sup_ids = {s[5] for s in supers}
    drops = (h for h in hits if h[0] >= config.TELEGRAM_MIN_PCT and h[5] not in sup_ids)
    posts = [("⚡ <b>SUPEROFERTA</b>", s) for s in sorted(supers, reverse=True)[:config.TELEGRAM_MAX_SUPER]] \
        + [("🔥", h) for h in sorted(drops, reverse=True)[:config.TELEGRAM_MAX_POSTS]]
    for icon, (pct, name, old, price, link, pid) in posts:
        url = link + ("&" if "?" in link else "?") + urlencode(config.AFFILIATE)
        text = (f"{icon} <b>-{pct:.0f}%</b> {html.escape(name)}\n💰 ${price:,.0f} <s>${old:,.0f}</s>\n"
                f"👉 {url}\n📉 Más bajadas reales: {config.SITE_URL}/")
        img = conn.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone()[0]
        api = f"https://api.telegram.org/bot{token}/"
        try:
            r = requests.post(api + "sendPhoto", data={"chat_id": chat, "photo": img, "caption": text, "parse_mode": "HTML"}, timeout=20) if img \
                else requests.post(api + "sendMessage", data={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=20)
            print("Telegram:", r.status_code)
        except requests.RequestException as e:
            print("Telegram falló:", e)
        time.sleep(3)


def run(deals_only=False):
    ml = MercadoLibre()
    conn = db.connect()
    checked = drops = 0
    seen, hits, supers = set(), [], []

    # todas las categorías de ML México y sus subcategorías; las más específicas primero
    # para que cada producto quede en su categoría concreta y no en la general
    # (en modo deals_only se omite: es un chequeo rápido solo de la página de ofertas)
    cats, names = [], {}
    if not deals_only:
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
        prev = conn.execute("SELECT price, orig, is_flash FROM prices WHERE product_id=? ORDER BY seen_at DESC, rowid DESC LIMIT 1", (pid,)).fetchone()
        db.save_price(conn, pid, price, orig, rep, is_flash)
        conn.commit()

        if is_super(price, orig, is_flash) and not (prev and is_super(*prev)):  # entra ahora en superoferta
            base = orig if orig and orig > price else old or price
            if base > price:  # sin descuento demostrable no hay nada que anunciar
                name, link = db.product_info(conn, pid)
                supers.append(((base - price) / base * 100, name, base, price, link, pid))

        if old and price < old:
            pct = (old - price) / old * 100
            if pct >= config.MIN_DROP_PCT:
                drops += 1
                name, link = db.product_info(conn, pid)
                notify(f"BAJO {pct:.1f}%: {name}\n  ${old:,.0f} -> ${price:,.0f}\n  {link}")
                hits.append((pct, name, old, price, link, pid))

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
    telegram(conn, hits, supers)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run(deals_only="--deals-only" in sys.argv)
