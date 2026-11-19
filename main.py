"""Revisa precios y avisa de cualquier bajada. Ejecutar: python main.py"""
import html
import json
import os
import random
import sys
import time
from urllib.parse import urlencode

import requests

import config
import db
from generate_site import MAX_PCT, reference
from ml_api import MercadoLibre


def notify(message):
    """Por ahora imprime. Aquí se conectará Telegram más adelante."""
    print(message)


def super_pct(price, orig, flash, hist):
    """% de superoferta contra la misma referencia que la web (mediana de 90 días / tachado creíble); 0 si no lo es."""
    _, pct, _, _ = reference(price, orig, hist or [(price, "")])
    return pct if pct >= config.SUPER_PCT or (flash and pct > 0) else 0


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
                f"📉 Más bajadas reales: {config.SITE_URL}/")
        markup = json.dumps({"inline_keyboard": [[{"text": "🛒 Dale click aquí", "url": url}]]})
        img = conn.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone()[0]
        api = f"https://api.telegram.org/bot{token}/"
        try:
            r = requests.post(api + "sendPhoto", data={"chat_id": chat, "photo": img, "caption": text, "parse_mode": "HTML", "reply_markup": markup}, timeout=20) if img \
                else requests.post(api + "sendMessage", data={"chat_id": chat, "text": text, "parse_mode": "HTML", "reply_markup": markup}, timeout=20)
            print("Telegram:", r.status_code)
        except requests.RequestException as e:
            print("Telegram falló:", e)
        time.sleep(3)


def whatsapp_notify(conn, hits, supers):
    """Envía al microservicio local de WhatsApp las ofertas."""
    chat_id = os.environ.get("WA_GROUP_ID")
    if not chat_id:
        return
    if not chat_id.endswith("@g.us") and not chat_id.endswith("@c.us"):
        chat_id += "@g.us"
    sup_ids = {s[5] for s in supers}
    drops = (h for h in hits if h[0] >= config.TELEGRAM_MIN_PCT and h[5] not in sup_ids)
    posts = [("⚡ *SUPEROFERTA*", s) for s in sorted(supers, reverse=True)[:config.TELEGRAM_MAX_SUPER]] \
        + [("🔥", h) for h in sorted(drops, reverse=True)[:config.TELEGRAM_MAX_POSTS]]
    
    for icon, (pct, name, old, price, link, pid) in posts:
        url = link + ("&" if "?" in link else "?") + urlencode(config.AFFILIATE)
        text = (f"{icon} *-{pct:.0f}%* {name}\n"
                f"💰 ${price:,.0f} ~${old:,.0f}~\n"
                f"🛒 {url}\n\n"
                f"📉 Más ofertas: {config.SITE_URL}/")
        
        img = conn.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone()[0]
        
        payload = {
            "chatId": chat_id,
            "message": text
        }
        if img:
            payload["imageUrl"] = img
            
        try:
            r = requests.post("http://localhost:3000/send", json=payload, timeout=20)
            print("WhatsApp:", r.status_code)
        except requests.RequestException as e:
            print("WhatsApp falló:", e)
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
        hist = conn.execute("SELECT price, seen_at FROM prices WHERE product_id=? AND seen_at >= date('now','-90 day') ORDER BY seen_at, rowid", (pid,)).fetchall()
        db.save_price(conn, pid, price, orig, rep, is_flash)
        conn.commit()

        pct = super_pct(price, orig, is_flash, hist + [(price, "")])
        if pct and not (prev and super_pct(*prev, hist)):  # entra ahora en superoferta (descuento real, no el tachado inflado)
            name, link = db.product_info(conn, pid)
            supers.append((pct, name, price / (1 - pct / 100), price, link, pid))

        if old and price < old:
            pct = (old - price) / old * 100
            if config.MIN_DROP_PCT <= pct <= MAX_PCT:  # > MAX_PCT suele ser error de precio: no se anuncia
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
    whatsapp_notify(conn, hits, supers)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run(deals_only="--deals-only" in sys.argv)
