"""Genera el sitio estático en docs/ desde prices.db. Ejecutar: python generate_site.py"""
import json
import shutil
import re
import unicodedata
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from collections import Counter
from html import escape
from urllib.parse import urlencode

import config
import db

FAQ = [
    ("¿Cómo detectan las ofertas?",
     "Guardamos el precio de cada producto de forma periódica y lo comparamos con su historial. "
     "El precio de referencia es la mediana de lo que costó en los últimos 90 días (así un error "
     "puntual del vendedor no infla el descuento), o el precio tachado de la tienda si es creíble. "
     "Solo mostramos descuento con al menos 3 registros o un precio tachado verificable, y nunca "
     "descuentos mayores al 85% (esos los revisamos a mano). Además te decimos si es el precio más bajo "
     "desde que lo seguimos."),
    ("¿Cuesta algo usar el sitio?",
     "No, es 100% gratuito para ti. Nuestro objetivo es ayudarte a ahorrar dinero en tus compras encontrando las verdaderas ofertas antes de que se agoten."),
    ("¿Los precios son definitivos?",
     "Los precios y el stock cambian muy rápido. El precio final siempre será el que te muestre la tienda al momento de pagar."),
]


# páginas de búsqueda específica: (título, regex sobre el nombre); se ordenan por precio
TV = r"(?i)^(?=.*(tv|televisi|pantalla)).*\b%s\b"
ACCESORIO = (r"(?i)\b(soporte|base|cable|antena|control remoto|funda|protector|regulador|cargador|adaptador|"
             r"refacci[oó]n|repuesto|mica|manguera|kit|carcasa|estuche|riel|brazo|tornillos?|empaque|voltaje|hdmi|vga|hub|pila|celular|tel[eé]fono|teclado|mouse|bocina|aud[ií]fonos? gamer)\b")
HEAD_ONLY = {"Laptops", "Lavadoras", "Refrigeradores", "Consolas de videojuegos"}
TV_ALL = "Smart TV y pantallas"
TOPICS = [
    (TV_ALL, r"(?i)^(?=.*(tv|televisi|pantalla)).*\b(2[4-9]|[3-9]\d)\b"),
    ("Smart TV y pantallas de 32 pulgadas", TV % 32),
    ("Smart TV y pantallas de 40 pulgadas", TV % 40),
    ("Smart TV y pantallas de 43 pulgadas", TV % 43),
    ("Smart TV y pantallas de 50 pulgadas", TV % 50),
    ("Smart TV y pantallas de 55 pulgadas", TV % 55),
    ("Laptops", r"(?i)laptop|notebook"),
    ("Audífonos Bluetooth", r"(?i)aud[ií]fonos.*(bluetooth|inal)|bluetooth.*aud[ií]fonos"),
    ("Lavadoras", r"(?i)lavadora"),
    ("Refrigeradores", r"(?i)refrigerador"),
    ("Consolas de videojuegos", r"(?i)consola|playstation|xbox|nintendo"),
]


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def load():
    conn = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else config.DB_PATH)
    db.migrate(conn)  # una base anterior puede no tener columnas nuevas
    rows = conn.execute(
        """SELECT p.name, p.link, p.category, p.image, p.id,
                  (SELECT price FROM prices WHERE product_id=p.id ORDER BY seen_at DESC, rowid DESC LIMIT 1),
                  (SELECT rep FROM prices WHERE product_id=p.id ORDER BY seen_at DESC, rowid DESC LIMIT 1),
                  (SELECT orig FROM prices WHERE product_id=p.id ORDER BY seen_at DESC, rowid DESC LIMIT 1),
                  (SELECT is_flash FROM prices WHERE product_id=p.id ORDER BY seen_at DESC, rowid DESC LIMIT 1)
           FROM products p
           WHERE (SELECT MAX(seen_at) FROM prices WHERE product_id=p.id) >= datetime('now', ?)""",
        (f"-{config.MAX_AGE_DAYS} day",)  # sin confirmar hace días = agotado o sin vendedor confiable: no se publica
    ).fetchall()
    items = []
    today = date.today().isoformat()
    for name, link, cat, image, pid, now, rep, orig, is_flash in rows:
        cat = config.CAT_RENAME.get(cat, cat)  # nombres de ML que confunden
        if now is None or not rep:  # sin vendedor confiable verificado no se publica
            continue
        hist = conn.execute("SELECT price, seen_at FROM prices WHERE product_id=? AND seen_at >= date('now', '-90 day') "
                            "ORDER BY seen_at, rowid", (pid,)).fetchall() or [(now, today)]
        top, pct, hist, flagged = reference(now, orig, hist)
        ps = [h[0] for h in hist]
        if flagged:
            review.append(f"{now:>10,.0f} | tachado {orig or 0:,.0f} | máx {max(ps):,.0f} | {name[:70]} | {link}")
        k = len(hist) - 1  # inicio de la racha del precio actual = cuándo lo detectamos
        while k and hist[k - 1][0] == now:
            k -= 1
        tag = ""
        if len(ps) > 1 and ps[-1] < ps[-2] and hist[-1][1][:10] == today and (ps[-2] - now) / ps[-2] * 100 >= config.MIN_DROP_PCT:
            tag = f"Bajó {money(ps[-2] - now)} hoy (antes {money(ps[-2])})"
        items.append(dict(id=pid, hd=[h[1][:10] for h in hist], name=clean_title(name), link=link, cat=cat, image=image, rep=rep, now=now, top=top, pct=pct,
                          ps=ps, since=hist[0][1], tag=tag, is_flash=bool(is_flash), light=light(now, orig, hist),
                          seen=hist[k][1].replace(" ", "T") + "Z", off=off_season(name)))
    # fuera de temporada al final; luego mejor promoción primero; a igualdad, el más barato
    items.sort(key=lambda i: (i["off"], -i["pct"], i["now"]))
    if review:
        print(f"Revisión manual: {len(review)} productos con descuento > {MAX_PCT}% (no se muestra descuento)")
        print("\n".join(review[:30]))
    return items


# temporadas: (regex en el nombre, desde MM-DD, hasta MM-DD); fuera de fecha el producto baja al final y sale de la portada
SEASONS = [
    (r"(?i)hallowe+n|d[ií]a de (los )?muertos|catrina|calabaza decorativa|disfraz", "09-15", "11-02"),
    (r"(?i)navide|navidad|santa claus|[aá]rbol de navidad|christmas", "10-25", "12-31"),
    (r"(?i)reyes magos|rosca de reyes", "12-15", "01-06"),
    (r"(?i)san valent[ií]n", "01-15", "02-14"),
    (r"(?i)d[ií]a de las madres", "04-10", "05-10"),
    (r"(?i)fiestas patrias|independencia de m[eé]xico|grito de", "08-15", "09-16"),
    (r"(?i)regreso a clases", "07-01", "08-31"),
]


def off_season(name):
    md = date.today().strftime("%m-%d")
    for rx, a, b in SEASONS:
        if re.search(rx, name):
            return not (a <= md <= b if a <= b else md >= a or md <= b)
    return False


def light(now, orig, hist):
    """Semáforo "¿Compro ya?" (clase, texto) con al menos 3 precios en el historial."""
    ps = [h[0] for h in hist]
    if len(ps) < 3:
        return None
    med = sorted(ps)[len(ps) // 2]
    if now <= min(ps):
        return "g", f"🟢 Precio más bajo desde {fecha(hist[0][1])}"
    return None  # fuera del mínimo no se etiqueta


MESES = "ene feb mar abr may jun jul ago sep oct nov dic".split()


def fecha(iso):
    y, m, d = map(int, iso[:10].split("-"))
    return f"{d} {MESES[m - 1]}"


MAX_PCT = 85  # descuento máximo creíble; lo que lo pase se manda a revisión manual
review = []


def reference(now, orig, hist):
    """(referencia, % descuento, historial sin atípicos, ¿a revisión?). Referencia = mediana de 90 días o precio
    tachado creíble; sin datos suficientes no hay descuento, y si pasa de MAX_PCT se oculta y se marca."""
    ps = sorted(h[0] for h in hist)
    med = ps[len(ps) // 2]
    hist = [h for h in hist if h[0] <= med * 3] or hist  # fuera errores del vendedor (precios absurdos)
    top = med if len(ps) >= 3 else 0
    cap = max(h[0] for h in hist) if top else med * 3  # con historial, el tachado no puede superar lo que realmente costó
    if orig and now < orig <= cap:  # tachado de la tienda, si no está inflado frente al historial
        top = max(top, orig)
    pct = (top - now) / top * 100 if top > now else 0
    return (top, pct, hist, False) if pct <= MAX_PCT else (0, 0, hist, True)


def clean_title(name):
    """Quita bloques repetidos ("A B A B"), palabras duplicadas y recorta a ~90 caracteres."""
    w = name.split()
    low = [re.sub(r"\W", "", x.lower()) for x in w]
    for n in range(len(w) // 2, 1, -1):
        k = next((k for k in range(len(w) - 2 * n + 1) if low[k:k + n] == low[k + n:k + 2 * n]), None)
        if k is not None:
            w, low = w[:k + n] + w[k + 2 * n:], low[:k + n] + low[k + 2 * n:]
            break
    seen, out = set(), []
    for x, l in zip(w, low):
        if len(l) > 3 and l in seen:  # relleno de palabras clave
            continue
        seen.add(l)
        out.append(x)
    s = " ".join(out)
    return s if len(s) <= 90 else s[:90].rsplit(" ", 1)[0].rstrip(",;-/") + "…"


def aff(link):
    return link + ("&" if "?" in link else "?") + urlencode(config.AFFILIATE)


def money(x):
    return f"${x:,.0f}"


def spark(ps):
    if len(ps) < 2 or max(ps) == min(ps):
        return ""
    lo, hi, n = min(ps), max(ps), len(ps) - 1
    pts = " ".join(f"{k / n * 56:.1f},{16 - (p - lo) / (hi - lo) * 14:.1f}" for k, p in enumerate(ps))
    return (f'<svg class="sp" viewBox="0 0 56 18" width="56" height="18" role="img" aria-label="Historial de precio">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>')


def card(i, up=""):
    deal = i["pct"] >= config.MIN_DROP_PCT
    flash = i.get("is_flash")
    hot = i["pct"] >= 60 and not flash
    cls = " flash" if flash else (" hot" if hot else "")
    txt = "⚡ " if flash else ("🔥 " if hot else "")
    badge = f'<span class="badge{cls}">{txt}-{i["pct"]:.0f}%</span>' if deal else ""
    old = f'<s>{money(i["top"])}</s>' if deal else ""
    save = f'<p class="save">Ahorras {money(i["top"] - i["now"])}</p>' if deal else ""
    bar = f'<div class="bar"><i style="width:{min(i["pct"], 100):.0f}%"></i></div>' if deal else ""
    sp = spark(i["ps"])
    lt = i.get("light")
    label = i["tag"] or (lt[1] if lt else "")  # una sola etiqueta: la bajada de hoy o el mínimo histórico
    trend = f'<p class="trend">{sp}<span>{label}</span></p>' if label or sp else ""
    img = (f'<img src="{escape(i["image"])}" alt="{escape(i["name"])}" width="300" height="225" loading="lazy">'
           if i["image"] else "")
    page = f'<a class="hl" href="{up}{i["page"]}">📈 Ver historial de precio</a>' if i.get("page") else ""
    return f"""<div class="card{cls}" data-id="{i['id']}" data-p="{i['now']:.0f}" data-d="{i['pct']:.0f}" data-f="{int(bool(flash))}">
  {badge}<button class="fav" type="button" aria-label="Guardar en favoritos" data-id="{i['id']}">♡</button><div class="img">{img}</div>
  <div class="body"><span class="cat" title="{escape(i['cat'])}">{escape(i['cat'])}</span>
  <h3><a class="st" href="{escape(aff(i['link']))}" target="_blank" rel="sponsored noopener">{escape(i['name'])}</a></h3>
  <p class="price"><strong>{money(i['now'])}</strong><small>MXN</small> {old}</p>
  {bar}{save}{trend}
  {page}
  <a class="go" href="{escape(aff(i['link']))}" target="_blank" rel="sponsored noopener">Ver oferta →</a></div>
</div>"""


PER_PAGE = 24
TABS = [("Inicio", ""), ("Relámpago", "relampago/"), ("Ofertas", "ofertas/"), ("Categorías", "c/"), ("Más buscados", "t/"), ("♡ Favoritos", "favoritos/")]
DISCLAIMER = ("es un rastreador independiente de ofertas. Los precios y la disponibilidad pueden variar rápidamente; "
              "por favor verifica el importe final en la página de la tienda antes de realizar tu compra. "
              "Como afiliado de Mercado Libre, podemos recibir una comisión por compras calificadas, sin costo extra para ti.")
LEGAL = [("Temporadas", "temporada/"), ("Privacidad", "privacidad/"), ("Términos", "terminos/")]


def rel(path):
    """Prefijo relativo para volver a la raíz desde una ruta como 'c/x/2/' (funciona en subcarpetas de GitHub Pages)."""
    return "../" * path.count("/")


def stats_tag():
    c = config.GOATCOUNTER
    return f'<script data-goatcounter="https://{c}.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>' if c else ""


def layout(path, title, desc, body, active="", ld=(), robots="index, follow", prev=None, nxt=None):
    """Envoltorio común: head SEO, navbar con buscador y pestañas, footer y scripts."""
    up, url = rel(path), f"{config.SITE_URL}/{path}"
    links = "".join(f'<link rel="{r}" href="{config.SITE_URL}/{p}">' for r, p in (("prev", prev), ("next", nxt)) if p is not None)
    tabs = "".join(f'<a href="{up}{p}"{" class=on" if n == active else ""}>{n}</a>' for n, p in TABS)
    m = re.search(r'"image": "(https?://[^"]+)"', json.dumps(list(ld)))  # foto principal para Google y redes
    og_img = f'\n<meta property="og:image" content="{escape(m.group(1))}">' if m else ""
    return f"""<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<link rel="icon" href="{up}favicon.ico" sizes="48x48">
<link rel="icon" href="{up}icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="{up}icon-192.png">
<link rel="manifest" href="{up}manifest.json">
<link rel="canonical" href="{url}">{links}
<meta name="robots" content="{robots}, max-image-preview:large">
<meta property="og:type" content="website">
<meta property="og:locale" content="es_MX">
<meta property="og:site_name" content="{config.SITE_NAME}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:url" content="{url}">{og_img}
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#07080d">
<link rel="stylesheet" href="{up}style.css">
<script type="application/ld+json">{json.dumps(list(ld), ensure_ascii=False)}</script>
</head>
<body data-up="{up}">
<header class="top"><div class="wrap nav">
  <a class="logo" href="{up}">
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: #00e57a; margin-right: 4px; vertical-align: bottom;"><path d="M6 21V3h7.5a5 5 0 0 1 0 10H6"/><path d="M10 13l8 8"/><path d="M18 15v6h-6"/></svg>
    {config.SITE_NAME}
  </a>
  <form class="sb" action="{up}buscar/" role="search"><input id="q" name="q" type="search" placeholder="Buscar productos…" aria-label="Buscar producto" autocomplete="off"><div id="sug" hidden></div></form>
  <nav class="tabs">{tabs}</nav>
</div></header>
<div class="reloj" id="reloj" hidden></div>
<main>
{body}
</main>
<footer><div class="wrap">
  <nav class="fl">{tabs}</nav>
  <p>{config.SITE_NAME} {DISCLAIMER}</p>
  <p>{" · ".join(f'<a href="{up}{p}">{n}</a>' for n, p in LEGAL)}{f' · Contacto: <a href="mailto:{config.CONTACT_EMAIL}">{config.CONTACT_EMAIL}</a>' if config.CONTACT_EMAIL else ""}</p>
</div></footer>
<script src="{up}app.js" defer></script>
{stats_tag()}</body>
</html>"""


def item_ld(items, start=1):
    return {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
        {"@type": "ListItem", "position": n, "item": {
            "@type": "Product", "name": i["name"], "image": i["image"],
            "offers": {"@type": "Offer", "price": round(i["now"], 2), "priceCurrency": "MXN",
                       "url": aff(i["link"]), "availability": "https://schema.org/InStock"}}}
        for n, i in enumerate(items, start)]}


def crumbs(trail):
    """trail = [(nombre, ruta)]; el último no es enlace. Devuelve (html, json-ld)."""
    up = rel(trail[-1][1])
    html = " › ".join(f'<a href="{up}{p}">{escape(n)}</a>' for n, p in trail[:-1]) + f" › {escape(trail[-1][0])}"
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": k, "name": n, "item": f"{config.SITE_URL}/{p}"} for k, (n, p) in enumerate(trail, 1)]}
    return f'<nav class="crumb">{html}</nav>', ld


def pager(base, n, total):
    if total < 2:
        return ""
    up = rel(base if n == 1 else f"{base}{n}/")
    u = lambda k: f'{up}{base}{"" if k == 1 else f"{k}/"}'
    out, last = [], 0
    for k in sorted({1, total, *range(n - 1, n + 2)} & set(range(1, total + 1))):
        if last and k - last > 1:
            out.append('<span class="gap">…</span>')
        out.append(f'<a class="pg on" aria-current="page">{k}</a>' if k == n else f'<a class="pg" href="{u(k)}">{k}</a>')
        last = k
    p = f'<a class="pg" rel="prev" href="{u(n - 1)}">‹ Anterior</a>' if n > 1 else ""
    x = f'<a class="pg" rel="next" href="{u(n + 1)}">Siguiente ›</a>' if n < total else ""
    return f'<nav class="pager" aria-label="Paginación">{p}{"".join(out)}{x}</nav>'


FILTERS = """<div class="tools flt" data-k="{k}" data-m="{m}"><select class="chip" id="fp" aria-label="Precio máximo"><option value="">Cualquier precio</option>{prices}</select>
  <select class="chip" id="fd" aria-label="Descuento mínimo"><option value="0">Cualquier descuento</option><option value="10">10% o más</option><option value="30">30% o más</option><option value="50">50% o más</option></select>
  <label class="chip"><input type="checkbox" id="ff"> Solo relámpago</label>
  <select class="chip" id="fo" aria-label="Ordenar"><option value="">Orden recomendado</option><option value="p">Menor precio</option><option value="d">Mayor descuento</option><option value="a">Mayor ahorro en pesos</option></select>
  <span class="cnt" id="fc"></span></div>"""


def filters(key, items, m=""):
    """Filtros reales sobre TODA la lista (no solo la página): app.js usa search.json con esta clave."""
    if not key or len(items) < 8:
        return ""
    hi = max(i["now"] for i in items)
    prices = "".join(f'<option value="{v}">Hasta {money(v)}</option>' for v in (300, 500, 1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 30000)
                     if v < hi and (not m or v < int(m)))
    return FILTERS.format(k=escape(key), m=m, prices=prices)


def paged(base, active, trail, title, desc, h1, lead, items, after="", robots="index, follow", key="", m=""):
    """Genera una página estática por cada PER_PAGE productos: base, base+'2/', base+'3/'…  → {ruta: html}."""
    total = max(1, -(-len(items) // PER_PAGE))
    out = {}
    for n in range(1, total + 1):
        path = base if n == 1 else f"{base}{n}/"
        chunk = items[(n - 1) * PER_PAGE:n * PER_PAGE]
        crumb_html, crumb_ld = crumbs(trail if n == 1 else trail + [(f"Página {n}", path)])
        suffix = f" - Página {n}" if n > 1 else ""
        body = f"""<section class="wrap">{crumb_html}
  <h1 class="lh">{escape(h1)}</h1>
  <p class="lead lh">{lead.replace("%UP%", rel(path))}</p>
  {filters(key, items, m)}<div class="grid" id="lst">{"".join(card(i, rel(path)) for i in chunk)}</div>
  <p class="more"><button class="chip" id="fmore" hidden>Ver más</button></p>
  <div id="pgr">{pager(base, n, total)}</div></section>{after}"""
        out[path] = layout(path, f"{title}{suffix} | {config.SITE_NAME}", desc + (f" Página {n} de {total}." if n > 1 else ""),
                           body, active, [crumb_ld, item_ld(chunk, (n - 1) * PER_PAGE + 1)],
                           robots=robots, prev=None if n == 1 else (base if n == 2 else f"{base}{n - 1}/"),
                           nxt=None if n == total else f"{base}{n + 1}/")
    return out


def hub(path, active, name, h1, lead, entries):
    """Índice de categorías o temas: entries = [(nombre, ruta, items)]."""
    up = rel(path)
    def tile(n, p, s):
        top = max((i for i in s if i["image"]), key=lambda i: i["pct"], default=None)  # portada: el de mayor descuento
        img = f'<img src="{escape(top["image"])}" alt="" loading="lazy">' if top else ""
        up_to = f' · hasta -{top["pct"]:.0f}%' if top and top["pct"] >= 1 else ""
        return (f'<a class="tile" href="{up}{p}"><span class="ti">{img}</span><strong>{escape(n)}</strong>'
                f'<small>{len(s)} ofertas · desde {money(min(i["now"] for i in s))}{up_to}</small></a>')
    tiles = "".join(tile(*e) for e in sorted(entries, key=lambda e: -len(e[2])))
    crumb_html, crumb_ld = crumbs([(config.SITE_NAME, ""), (name, path)])
    body = f'<section class="wrap">{crumb_html}<h1 class="lh">{escape(h1)}</h1><p class="lead lh">{lead}</p><div class="tiles">{tiles}</div></section>'
    return layout(path, f"{h1} | {config.SITE_NAME}", lead, body, active, [crumb_ld])


ICONS = [(r"celular|smartphone|tel[eé]fono", "📱"), (r"laptop|comput|pc|tablet", "💻"), (r"consola|videojuego|gaming", "🎮"),
         (r"tv|pantalla|audio|video|bocina|aud[ií]fono", "📺"), (r"belleza|maquillaje|perfume|cuidado personal|cabello", "💄"),
         (r"herramienta|taladro|construcci", "🔧"), (r"cocina|electrodom|lavadora|refrigerador|licuadora|freidora", "🍳"),
         (r"hogar|mueble|decoraci|jard[ií]n|ba[ñn]o|cama", "🏠"), (r"beb[eé]|pa[ñn]al", "🍼"), (r"juguete|juego", "🧸"),
         (r"deporte|fitness|bicicleta|gimnasio", "⚽"), (r"ropa|moda|calzado|tenis|zapato|reloj", "👟"),
         (r"mascota|perro|gato", "🐾"), (r"auto|veh[ií]culo|moto|llanta", "🚗"), (r"salud|vitamina|suplemento", "💊"),
         (r"c[aá]mara|foto", "📷"), (r"impresora|cartucho|t[oó]ner", "🖨️"), (r"despensa|alimento|bebida|abarrote", "🛒"), (r"m[eé]dic|ortop", "🩺"), (r"oficina|papeler|escolar|libro", "📚")]


def icon(cat):
    return next((e for rx, e in ICONS if re.search(rx, cat, re.I)), "🏷️")


def home(items, deals, lists, seasons=()):
    cats = [c for c, _ in Counter(i["cat"] for i in deals).most_common(8)]
    cpath = {n: p for p, n, k, _ in lists if k == "c"}
    today = date.today().isoformat()
    title = f"Ofertas en Mercado Libre México hoy | {config.SITE_NAME}"
    desc = ("Bajas de precio reales en Mercado Libre México, verificadas contra el historial: "
            "electrónica, celulares, computación, hogar y videojuegos. Actualizado a diario.")
    ld = [
        {"@context": "https://schema.org", "@type": "WebSite", "name": config.SITE_NAME, "url": config.SITE_URL + "/",
         "inLanguage": "es-MX", "potentialAction": {"@type": "SearchAction", "target": f"{config.SITE_URL}/buscar/?q={{q}}",
                                                   "query-input": "required name=q"}},
        item_ld(deals[:20]),
        {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in FAQ]},
    ]
    rail = lambda h, its, more: (
        f'<section class="wrap"><div class="sh"><h2>{h}</h2>{more}</div>'
        '<div class="rail"><button class="nv l" aria-label="Anterior">‹</button><button class="nv r" aria-label="Siguiente">›</button>'
        f'<div class="grid feat">{"".join(card(i) for i in its)}</div></div></section>')
    
    # portada sin repetidos ni productos de temporada pasada: cada bloque muestra algo nuevo
    used = set()
    def take(its, n):
        out = [i for i in its if not i["off"] and i["link"] not in used][:n]
        used.update(i["link"] for i in out)
        return out
    # oferta del día: la mayor baja con historial suficiente (no solo el tachado de la tienda)
    top = (take([d for d in deals if len(d["ps"]) >= 3], 1) or take(deals, 1) or [None])[0]
    ads = (f'<a class="promo" href="{escape(aff(top["link"]))}" target="_blank" rel="sponsored noopener">'
           f'<img src="{escape(top["image"] or "")}" alt="" loading="lazy"><div><span class="pk">🏆 Oferta del día · -{top["pct"]:.0f}%</span>'
           f'<b>{escape(top["name"])}</b><p><strong>{money(top["now"])}</strong> <s>{money(top["top"])}</s></p></div></a>' if top else "")
    flash = take([d for d in deals if d.get("is_flash")], 16)
    flash_rail = rail("⚡ Ofertas Relámpago", flash, '<a class="all" href="relampago/">Ver todas →</a>') if flash else ""
    best_rail = rail("Las mayores bajas", take(deals, 16), '<a class="all" href="ofertas/">Ver todas →</a>')
    rails = "".join(rail(f"Lo mejor en {escape(c)}", sel,
                         f'<a class="all" href="{cpath[c]}">Ver todo →</a>' if c in cpath else "")
                    for c in cats if len(sel := take([d for d in deals if d["cat"] == c], 15)) >= 4)
    # franja delgada arriba: publicidad propia + espacio para anunciantes (abre un correo al dueño)
    uni = (f'<a class="ad-main" href="{escape(config.UNISHOPP_URL)}" target="_blank" rel="sponsored noopener"><span class="ad-label">Publicidad</span>'
           f'<strong>{escape(config.UNISHOPP_TEXT)}</strong><span class="ad-cta">Visitar →</span></a>') if config.UNISHOPP_URL else ""
    slot = (f'<a class="ad-slot" href="mailto:{config.ADS_EMAIL}?subject=Quiero%20anunciarme%20en%20{config.SITE_NAME}">'
            '✉️ <strong>Anúnciate aquí</strong><small>Llega a miles de compradores</small></a>') if config.ADS_EMAIL else ""
    ad_strip = f'<section class="wrap ad-strip">{uni}{slot}</section>' if uni or slot else ""
    ads_sec = f'<section class="wrap promos">{ads}</section>' if ads else ""
    # sin los 5 tamaños de TV: viven dentro de la página de pantallas
    explore = "".join(f'<a class="chip" href="{p}">{icon(n)} {escape(n)}</a>' for p, n, k, _ in lists if k == "t" and not n.startswith(TV_ALL + " de"))
    big = "".join(f'<a class="chip" href="{cpath[c]}">{icon(c)} {escape(c)}</a>' for c, _ in Counter(i["cat"] for i in deals).most_common(8) if c in cpath)
    month = date.today().month  # solo la fecha especial en temporada; las demás siguen en su página
    now_s = "".join(f'<a class="chip" href="{p}">🎉 {escape(n)}</a>' for n, p, _, sl in seasons if sl and month in SEASON_MONTHS.get(n, ()))
    explore_sec = (f'<section class="wrap"><h2>Explora por categoría</h2><div class="chips wrapc">{big}{explore}{now_s}'
                   '<a class="chip on" href="c/">Ver todas →</a></div></section>')
    faq = "".join(f"<details><summary>{escape(q)}</summary><p>{escape(a)}</p></details>" for q, a in FAQ)
    body = f"""<section class="hero"><div class="wrap">
  <p class="eyebrow"><span class="dot"></span> Mercado Libre México · {len(items)} productos vigilados · Actualizado {today}</p>
  <h1>Los precios cambian todo el tiempo. <em>Nosotros los vigilamos por ti.</em></h1>
  <p class="lead">Bajas de precio reales, comparadas con el historial de cada producto. 10 actualizaciones al día. <a href="#como-funciona">Cómo funciona</a></p>
</div></section>
{ad_strip}
{ads_sec}
{flash_rail}
{best_rail}
<section id="como-funciona" class="wrap how">
  <h2>Cómo funciona</h2>
  <ol>
    <li><strong>Vigilamos</strong>Los productos más vendidos de cada categoría.</li>
    <li><strong>Comparamos</strong>Cada precio contra su historial real.</li>
    <li><strong>Publicamos</strong>Solo lo que cuesta menos que antes.</li>
  </ol>
</section>
{rails}
{explore_sec}
<section id="faq" class="wrap"><h2>Preguntas frecuentes</h2>{faq}</section>

"""
    return layout("", title, desc, body, "Inicio", ld)


def search_page():
    body = """<section class="wrap"><h1 class="lh sr">Resultados para «<span id="rq"></span>»</h1>
  <p class="cnt" id="cnt"></p>
  <div class="tools"><div class="chips" id="cf"></div>
  <select class="chip" id="so" aria-label="Ordenar"><option value="r">Más relevantes</option><option value="d">Mayor descuento</option><option value="a">Mayor ahorro en pesos</option><option value="p">Menor precio</option></select></div>
  <p class="none" id="none" hidden>No encontramos productos. Prueba con otra palabra o explora las <a class="all" href="../c/">categorías</a>.</p>
  <div class="grid" id="res"></div>
  <p class="more"><button class="chip" id="more" hidden>Ver más resultados</button></p></section>"""
    return layout("buscar/", f"Buscar productos | {config.SITE_NAME}", "Busca ofertas en Mercado Libre México.", body, robots="noindex, follow")


def legal_pages():
    n, u = config.SITE_NAME, config.SITE_URL
    mail = (f' Para ejercer tus derechos de acceso, rectificación, cancelación u oposición (ARCO), escríbenos a '
            f'<a href="mailto:{config.CONTACT_EMAIL}">{config.CONTACT_EMAIL}</a>.') if config.CONTACT_EMAIL else ""
    contact = f"<p>Contacto:{mail}</p>" if mail else ""
    priv = f"""<h2>Datos que recogemos</h2>
<p>{n} ({u}) no tiene cuentas, formularios ni registro: <strong>no recogemos ni almacenamos datos personales</strong>.
Lo que escribes en el buscador se procesa únicamente en tu navegador y no se envía a ningún servidor nuestro.</p>
<h2>Cookies y analítica</h2>
<p>El sitio no usa cookies propias ni de publicidad. {"Para contar visitas usamos GoatCounter, una analítica sin cookies que no identifica a las personas ni las sigue entre sitios; solo cuenta páginas vistas, país y tipo de dispositivo." if config.GOATCOUNTER else "No usa herramientas de analítica."}</p>
<h2>Servicios de terceros</h2>
<p>El sitio se aloja en GitHub Pages, que puede registrar datos técnicos de conexión (como la dirección IP) según su
<a href="https://docs.github.com/es/site-policy/privacy-policies/github-general-privacy-statement" rel="noopener">política de privacidad</a>.
Las imágenes de los productos se cargan desde los servidores de Mercado Libre. Al hacer clic en una oferta sales a
mercadolibre.com.mx, que tiene su propio aviso de privacidad y puede colocar sus cookies; además, el enlace lleva un identificador de afiliado.</p>
<h2>Cambios</h2>
<p>Si esto cambia (por ejemplo, si añadimos analítica o alertas), actualizaremos esta página. Última actualización: {date.today().isoformat()}.</p>{contact}"""
    terms = f"""<h2>Qué es {n}</h2>
<p>{n} es un sitio independiente que rastrea precios públicos de Mercado Libre México y muestra bajas de precio frente a su historial.
No vendemos productos ni procesamos pagos; la compra se realiza siempre en Mercado Libre. No estamos afiliados ni respaldados por Mercado Libre, más allá de participar en su programa de afiliados.</p>
<h2>Divulgación de afiliados</h2>
<p>Los enlaces a productos son enlaces de afiliado: si compras tras hacer clic, podemos recibir una comisión de Mercado Libre <strong>sin costo adicional para ti</strong>.
Esto no influye en el precio que pagas.</p>
<h2>Precios e información</h2>
<p>Los precios, descuentos y disponibilidad provienen de la API de Mercado Libre y pueden cambiar en cualquier momento, o contener errores.
El precio y las condiciones válidos son los que aparecen en Mercado Libre al momento de comprar. Solo mostramos vendedores con buena reputación, pero no garantizamos la calidad de ningún producto ni vendedor.</p>
<h2>Responsabilidad</h2>
<p>El sitio se ofrece «tal cual», sin garantías. No somos responsables de decisiones de compra ni de pérdidas derivadas del uso de la información publicada.
Las marcas y nombres pertenecen a sus respectivos dueños.</p>
<h2>Cambios y ley aplicable</h2>
<p>Podemos modificar estos términos en cualquier momento. Se rigen por las leyes de México. Última actualización: {date.today().isoformat()}.</p>{contact}"""
    out = {}
    for path, name, body in (("privacidad/", "Aviso de privacidad", priv), ("terminos/", "Términos y condiciones", terms)):
        html = f'<section class="wrap legal"><h1 class="lh sr">{name}</h1>{body}</section>'
        out[path] = layout(path, f"{name} | {n}", f"{name} de {n}, rastreador de ofertas de Mercado Libre México.", html)
    return out


def build_listings(items):
    """Devuelve [(ruta, nombre, tipo, items)] con al menos 3 productos."""
    out = []
    for c, _ in Counter(i["cat"] for i in items).most_common():
        sel = [i for i in items if i["cat"] == c]
        if len(sel) >= 3:
            out.append((f"c/{slug(c)}/", c, "c", sel))
    for name, rx in TOPICS:
        head = 28 if name in HEAD_ONLY else None  # el producto nombra su tipo al inicio; "cable para laptop" no cuenta
        sel = [i for i in items if re.search(rx, i["name"][:head]) and not re.search(ACCESORIO, i["name"])]
        if sel:  # piso de precio: lo que cuesta < 30% de la mediana suele ser refacción o accesorio
            floor = 0.3 * sorted(i["now"] for i in sel)[len(sel) // 2]
            sel = [i for i in sel if i["now"] >= floor]
        sel.sort(key=lambda i: i["now"])
        if len(sel) >= 5:
            out.append((f"t/{slug(name)}/", name, "t", sel))
    return out


# fechas especiales: (nombre, slug, cuándo es, regex de productos o None = las mayores ofertas del momento)
SPECIAL = [
    ("Buen Fin", "buen-fin", "el fin de semana largo de noviembre (alrededor del 20 de noviembre)", None),
    ("Hot Sale", "hot-sale", "finales de mayo o inicios de junio", None),
    ("Navidad", "navidad", "diciembre; conviene comprar desde noviembre para que llegue a tiempo",
     r"(?i)juguete|consola|smartwatch|perfume|aud[ií]fono|[aá]rbol|navide"),
    ("Día de Reyes", "reyes-magos", "el 6 de enero",
     r"(?i)juguete|lego|mu[ñn]ec|consola|bicicleta|pat[ií]n|scooter|montable"),
    ("Día de las Madres", "dia-de-las-madres", "el 10 de mayo",
     r"(?i)perfume|maquillaje|bolsa|freidora|licuadora|cafetera|joyer|reloj|secadora de cabello|plancha de cabello"),
    ("San Valentín", "san-valentin", "el 14 de febrero",
     r"(?i)perfume|reloj|joyer|collar|aretes|peluche|bocina|aud[ií]fono"),
    ("Regreso a clases", "regreso-a-clases", "agosto, antes del inicio del ciclo escolar",
     r"(?i)mochila|laptop|tablet|calculadora|cuaderno|lonchera|escolar|impresora"),
    ("Día del Padre", "dia-del-padre", "el tercer domingo de junio",
     r"(?i)herramienta|taladro|reloj|parrilla|asador|rasuradora|afeitadora|smartwatch"),
]
SEASON_MONTHS = {"Buen Fin": (11,), "Hot Sale": (5, 6), "Navidad": (11, 12), "Día de Reyes": (12, 1), "Día de las Madres": (4, 5),
                 "San Valentín": (1, 2), "Regreso a clases": (7, 8), "Día del Padre": (6,)}
RANGES = (1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000)


def season_items(items, rx):
    sel = [i for i in items if not i["off"] and (rx is None or re.search(rx, i["name"]))]
    if rx is None:
        sel = [i for i in sel if i["pct"] >= config.MIN_DROP_PCT]
    return sorted(sel, key=lambda i: (i["pct"] < config.MIN_DROP_PCT, -i["pct"], i["now"]))[:240]


def chart(i):
    """Gráfica grande del historial (SVG estático, sin JS)."""
    ps, hd = i["ps"], i["hd"]
    lo, hi, n = min(ps), max(ps), len(ps) - 1
    W, H = 640, 220
    y = lambda p: 20 + (hi - p) / (hi - lo) * (H - 50)
    pts = " ".join(f"{40 + k / n * (W - 60):.1f},{y(p):.1f}" for k, p in enumerate(ps))
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Historial de precio de {escape(i["name"])}">'
            f'<line x1="40" x2="{W - 20}" y1="{y(lo):.1f}" y2="{y(lo):.1f}" class="g"/><line x1="40" x2="{W - 20}" y1="{y(hi):.1f}" y2="{y(hi):.1f}" class="g"/>'
            f'<text x="36" y="{y(hi) + 4:.1f}" text-anchor="end">{money(hi)}</text><text x="36" y="{y(lo) + 4:.1f}" text-anchor="end">{money(lo)}</text>'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<text x="40" y="{H - 6}">{fecha(hd[0])}</text><text x="{W - 20}" y="{H - 6}" text-anchor="end">{fecha(hd[-1])}</text></svg>')


def product_page(i, related, cat_path):
    path = i["page"]
    up = rel(path)
    ps = i["ps"]
    med = sorted(ps)[len(ps) // 2]
    trail = [(config.SITE_NAME, "")] + ([(i["cat"], cat_path)] if cat_path else []) + [(i["name"], path)]
    crumb_html, crumb_ld = crumbs(trail)
    deal = i["pct"] >= config.MIN_DROP_PCT
    lt = i.get("light")
    near = (f"Está a {((i['now'] - min(ps)) / min(ps) * 100):.0f}% de su precio más bajo registrado ({money(min(ps))})."
            if i["now"] > min(ps) else "Es el precio más bajo que hemos registrado.")
    verdict = (f"Hoy cuesta {money(i['now'])} MXN. {near} En los últimos 90 días su precio típico (mediana) fue de {money(med)}, "
               f"con un máximo de {money(max(ps))}.")
    ld = {"@context": "https://schema.org", "@type": "Product", "name": i["name"], "image": i["image"], "category": i["cat"],
          "sku": i["id"], "offers": {"@type": "Offer", "price": round(i["now"], 2), "priceCurrency": "MXN", "url": aff(i["link"]),
                                     "availability": "https://schema.org/InStock", "seller": {"@type": "Organization", "name": "Mercado Libre"}}}
    stats = "".join(f"<div><small>{k}</small><b>{v}</b></div>" for k, v in (
        ("Precio más bajo", money(min(ps))), ("Precio más alto", money(max(ps))), ("Precio típico", money(med)),
        ("Registros", len(ps)), ("Vigilado desde", fecha(i["since"]))))
    rel_html = (f'<section class="wrap"><h2>Más ofertas en {escape(i["cat"])}</h2><div class="grid">{"".join(card(r, up) for r in related)}</div></section>'
                if related else "")
    img = f'<img src="{escape(i["image"])}" alt="{escape(i["name"])}" width="400" height="400">' if i["image"] else ""
    body = f"""<section class="wrap">{crumb_html}
  <div class="pp"><div class="ppi">{img}</div><div>
  <h1 class="lh">{escape(i["name"])}</h1>
  <p class="price big"><strong>{money(i["now"])}</strong><small>MXN</small>{f' <s>{money(i["top"])}</s> <span class="badge st">-{i["pct"]:.0f}%</span>' if deal else ""}</p>
  {f'<p class="light {lt[0]}">{lt[1]}</p>' if lt else ""}
  <p class="lead">{verdict}</p>
  <p class="rep">✓ {escape(i["rep"])}</p>
  <p class="cta"><a class="btn big" href="{escape(aff(i["link"]))}" target="_blank" rel="sponsored noopener">Ver en Mercado Libre →</a>
  <button class="fav pf" type="button" aria-label="Guardar en favoritos" data-id="{i["id"]}">♡</button></p>
  <small class="ago" data-t="{i["seen"]}"></small></div></div>
  <h2>Historial de precio</h2>{chart(i)}<div class="stats">{stats}</div>
  <p class="lead">El precio puede cambiar en cualquier momento; confírmalo en Mercado Libre antes de comprar.</p></section>{rel_html}"""
    title = f"{i['name'][:60].rstrip(' ,-')} — precio e historial | {config.SITE_NAME}"
    desc = f"{i['name'][:90]}: hoy {money(i['now'])} MXN. Precio más bajo {money(min(ps))}, típico {money(med)}. Historial de {len(ps)} precios en Mercado Libre México."
    return layout(path, title, desc, body, "", [crumb_ld, ld])


def build(items):
    """Todas las páginas del sitio: {ruta: html}."""
    today = date.today().isoformat()
    deals = [i for i in items if i["pct"] >= config.MIN_DROP_PCT]
    for i in items:  # página propia solo con historial que aporte algo (≥5 precios y que haya cambiado)
        if len(i["ps"]) >= 5 and max(i["ps"]) != min(i["ps"]):
            i["page"] = f"p/{slug(i['name'])[:60].strip('-')}-{i['id'].lower()}/"
    lists = build_listings(items)
    seasons = [(n, f"temporada/{s}/", when, season_items(items, rx)) for n, s, when, rx in SPECIAL]
    pages = {"": home(items, deals, lists, seasons), "buscar/": search_page(), **legal_pages()}
    for i in items:  # claves de filtro (temas y temporadas) para app.js
        i["k"] = []
    for p, n, k, sel in lists:
        if k == "t":
            for i in sel:
                i["k"].append(p[:-1])
    for n, p, when, sel in seasons:
        for i in sel:
            i["k"].append(p[:-1])
    cpath = {n: p for p, n, k, _ in lists if k == "c"}
    by_cat = {}
    for i in items:
        by_cat.setdefault(i["cat"], []).append(i)
    for i in items:
        if i.get("page"):
            rel_items = [r for r in by_cat[i["cat"]] if r is not i and not r["off"]][:8]
            pages[i["page"]] = product_page(i, rel_items, cpath.get(i["cat"]))
    for n, p, when, sel in seasons:
        what = "las mayores bajas de precio" if n in ("Buen Fin", "Hot Sale") else "los regalos y productos más buscados para esa fecha"
        lead = (f"{n} en México es {when}. Aquí juntamos {what}, "
                f"verificadas contra su historial y solo de vendedores confiables. {len(sel)} productos hoy; se actualiza a diario. Actualizado {today}.")
        pages.update(paged(p, "", [(config.SITE_NAME, ""), ("Temporadas", "temporada/"), (n, p)],
                           f"Ofertas de {n} en Mercado Libre México",
                           f"Ofertas de {n} en Mercado Libre México con precios verificados contra su historial. {len(sel)} productos. Actualizado {today}.",
                           f"Ofertas de {n}", lead, sel, robots="index, follow" if sel else "noindex, follow", key=p[:-1]))
    pages["temporada/"] = hub("temporada/", "", "Temporadas", "Ofertas por temporada y fechas especiales",
                              "Buen Fin, Hot Sale, Navidad, Reyes, Día de las Madres y más: ofertas reales para cada fecha especial en Mercado Libre México.",
                              [(n, p, s) for n, p, when, s in seasons if s])
    fcrumb, fld = crumbs([(config.SITE_NAME, ""), ("Favoritos", "favoritos/")])
    pages["favoritos/"] = layout("favoritos/", f"Mis favoritos | {config.SITE_NAME}", "Los productos que guardaste en este navegador.",
                                 f'<section class="wrap">{fcrumb}<h1 class="lh">♡ Mis favoritos</h1>'
                                 '<p class="lead lh">Se guardan solo en este navegador. Toca ♡ en cualquier producto para agregarlo.</p>'
                                 '<div class="grid" id="fav"></div><p class="none" id="fnone" hidden>Aún no tienes favoritos. '
                                 '<a class="chip" href="../ofertas/">Ver ofertas</a></p></section>', "♡ Favoritos", [fld], robots="noindex, follow")
    lo = lambda s: money(min(i["now"] for i in s))
    
    flash_deals = [d for d in deals if d.get("is_flash")]
    pages.update(paged(
        "relampago/", "Relámpago", [(config.SITE_NAME, ""), ("Relámpago", "relampago/")],
        "Ofertas Relámpago en Mercado Libre",
        f"{len(flash_deals)} ofertas relámpago activas hoy. Precios verificados. Actualizado {today}.",
        "⚡ Ofertas Relámpago",
        f"Ofertas por tiempo limitado detectadas en la última actualización ({today}). Pueden haber terminado: verifica en la tienda." if flash_deals else "Por el momento no hay ofertas relámpago activas. Revisa más tarde.",
        flash_deals, robots="index, follow" if flash_deals else "noindex, follow", key="relampago"))

    pages.update(paged(
        "ofertas/", "Ofertas", [(config.SITE_NAME, ""), ("Ofertas", "ofertas/")],
        "Todas las ofertas en Mercado Libre México",
        f"{len(deals)} ofertas en Mercado Libre México con vendedores confiables, ordenadas de mayor a menor descuento. Actualizado {today}.",
        "Todas las ofertas en Mercado Libre",
        f"{len(deals)} productos con baja de precio, primero los de mayor descuento. Solo vendedores confiables. Actualizado {today}.",
        deals, key="ofertas"))
    for kind, tab, name, h1, lead in (
            ("c", "Categorías", "Categorías", "Ofertas por categoría",
             "Elige una categoría para ver sus mejores ofertas en Mercado Libre México, con vendedores confiables y precios verificados."),
            ("t", "Más buscados", "Más buscados", "Lo más buscado en Mercado Libre",
             "Pantallas, laptops, audífonos, electrodomésticos y consolas: las categorías con más ofertas hoy en Mercado Libre, con vendedores confiables y precios verificados.")):
        pages[f"{kind}/"] = hub(f"{kind}/", tab, name, h1, lead, [(n, p, s) for p, n, k, s in lists if k == kind])
    for path, name, kind, sel in lists:
        tab, hubname = ("Categorías", "Categorías") if kind == "c" else ("Más buscados", "Más buscados")
        if kind == "t":
            title = f"{name} más baratas en Mercado Libre (desde {lo(sel)})"
            desc = f"{name} más baratas en Mercado Libre México desde {lo(sel)} MXN. {len(sel)} opciones de vendedores confiables, de menor a mayor precio. Actualizado {today}."
            h1 = f"{name} más baratas en Mercado Libre"
        else:
            title = f"Ofertas en {name} en Mercado Libre México"
            desc = f"{len(sel)} ofertas en {name} en Mercado Libre México desde {lo(sel)} MXN, con vendedores confiables y precios verificados. Actualizado {today}."
            h1 = f"{name}: ofertas en Mercado Libre"
        lead = f"{len(sel)} opciones desde {lo(sel)} MXN. Solo vendedores confiables (nivel verde, MercadoLíder o tienda oficial); precios comparados con su historial. Actualizado {today}."
        key = path[:-1] if kind == "t" else "c:" + name
        trail = [(config.SITE_NAME, ""), (hubname, f"{kind}/"), (name, path)]
        if name == TV_ALL:
            lead += " Por tamaño: " + " ".join(f'<a class="chip" href="%UP%{q}">{n[len(TV_ALL) + 4:]}</a>' for q, n, k, _ in lists if n.startswith(TV_ALL + " de"))
        if kind == "t":  # páginas fijas por rango de precio ("laptops de menos de $10,000")
            rng = [(m, sub) for m in RANGES if 5 <= len(sub := [i for i in sel if i["now"] < m]) <= 0.8 * len(sel)][:3]
            if rng:
                lead += " Por precio: " + " ".join(f'<a class="chip" href="%UP%{path}menos-de-{m}/">Menos de {money(m)}</a>' for m, _ in rng)
            for m, sub in rng:
                rp = f"{path}menos-de-{m}/"
                pages.update(paged(rp, tab, trail + [(f"Menos de {money(m)}", rp)],
                                   f"{name} de menos de {money(m)} en Mercado Libre",
                                   f"{len(sub)} {name.lower()} de menos de {money(m)} MXN en Mercado Libre México, de vendedores confiables. Desde {lo(sub)}. Actualizado {today}.",
                                   f"{name} de menos de {money(m)}",
                                   f"{len(sub)} opciones de menos de {money(m)} MXN, desde {lo(sub)}. Solo vendedores confiables; precios comparados con su historial. Actualizado {today}.",
                                   sub, key=key, m=str(m)))
        pages.update(paged(path, tab, trail, title, desc, h1, lead, sel, key=key))
    return pages


def search_index(items):
    return [dict(n=i["name"], c=i["cat"], p=round(i["now"]), t=round(i["top"]), d=round(i["pct"], 1),
                 l=aff(i["link"]), i=i["image"] or "", r=i["rep"], g=i["tag"], id=i["id"], f=int(bool(i.get("is_flash"))),
                 k=i.get("k", []), u=i.get("page", "")) for i in items]


def main():
    out = config.OUT_DIR
    out.mkdir(exist_ok=True)
    items = load()
    pages = build(items)
    # borra solo las páginas que ya no existen (paginación o categorías viejas)
    keep = {(out / p / "index.html").resolve() for p in pages}
    for d in ("ofertas", "c", "t", "relampago", "p", "temporada", "favoritos"):
        for f in (out / d).rglob("index.html") if (out / d).exists() else ():
            if f.resolve() not in keep:
                f.unlink()
                for parent in f.parents:  # quita carpetas que quedaron vacías
                    if parent == out or any(parent.iterdir()):
                        break
                    parent.rmdir()
    # escribe solo lo que cambió: menos disco, commits más chicos y el sitemap conserva su fecha real
    old_sm = (out / "sitemap.xml").read_text(encoding="utf-8") if (out / "sitemap.xml").exists() else ""
    lastmod = dict(re.findall(rf"<loc>{re.escape(config.SITE_URL)}/([^<]*)</loc><lastmod>([^<]+)</lastmod>", old_sm))
    today, changed = date.today().isoformat(), 0
    for path, html in pages.items():
        f = out / path / "index.html"
        if f.exists() and f.read_text(encoding="utf-8") == html:
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(html, encoding="utf-8")
        lastmod[path], changed = today, changed + 1
    print(f"Páginas modificadas: {changed} de {len(pages)}")
    (out / "search.json").write_text(json.dumps(search_index(items), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    now = datetime.now(timezone.utc)
    nxt = min((now.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(days=d) for d in (0, 1) for h in config.RUN_HOURS_UTC),
              key=lambda t: (t <= now, t))
    # "next" = arranque de la próxima corrida; la página tarda unos minutos más en publicarse
    (out / "status.json").write_text(json.dumps({"updated": now.isoformat(), "next": nxt.isoformat()}), encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {config.SITE_URL}/sitemap.xml\n")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"\n<url><loc>{config.SITE_URL}/{p}</loc><lastmod>{lastmod.get(p, today)}</lastmod>"
                  "<changefreq>daily</changefreq></url>" for p in pages if "noindex" not in pages[p]) + "\n</urlset>\n")
    (out / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#00e57a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 21V3h7.5a5 5 0 0 1 0 10H6"/><path d="M10 13l8 8"/><path d="M18 15v6h-6"/></svg>',
        encoding="utf-8"
    )
    
    manifest = {
        "name": config.SITE_NAME,
        "short_name": config.SITE_NAME,
        "start_url": "./",
        "display": "standalone",
        "background_color": "#07080d",
        "theme_color": "#07080d",
        "description": "Ofertas reales en Mercado Libre",
        "icons": [
            {"src": "icon.svg", "sizes": "512x512", "type": "image/svg+xml"},
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"}
        ]
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    
    
    print(f"Sitio generado en {out}: {len(pages)} páginas")


if __name__ == "__main__":
    main()
