"""Genera el sitio estático en docs/ desde prices.db. Ejecutar: python generate_site.py"""
import json
import re
import unicodedata
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from collections import Counter
from html import escape
from urllib.parse import urlencode

import config

FAQ = [
    ("¿Cómo detectan las ofertas?",
     "Guardamos el precio de cada producto de forma periódica y lo comparamos con su historial. "
     "Es oferta lo que cuesta menos que su precio más alto registrado o que tiene una promoción "
     "activa en la tienda, sin importar el porcentaje."),
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
TOPICS = [
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
    rows = conn.execute(
        """SELECT p.name, p.link, p.category, p.image, p.id,
                  (SELECT price FROM prices WHERE product_id=p.id ORDER BY seen_at DESC, rowid DESC LIMIT 1),
                  (SELECT rep FROM prices WHERE product_id=p.id ORDER BY seen_at DESC, rowid DESC LIMIT 1),
                  MAX((SELECT MAX(price) FROM prices WHERE product_id=p.id),
                      COALESCE((SELECT orig FROM prices WHERE product_id=p.id ORDER BY seen_at DESC, rowid DESC LIMIT 1), 0)),
                  (SELECT is_flash FROM prices WHERE product_id=p.id ORDER BY seen_at DESC, rowid DESC LIMIT 1)
           FROM products p"""
    ).fetchall()
    items = []
    today = date.today().isoformat()
    for name, link, cat, image, pid, now, rep, top, is_flash in rows:
        if now is None or not rep:  # sin vendedor confiable verificado no se publica
            continue
        pct = (top - now) / top * 100 if top else 0
        hist = conn.execute("SELECT price, date(seen_at) FROM prices WHERE product_id=? ORDER BY seen_at, rowid",
                            (pid,)).fetchall()
        ps = [h[0] for h in hist]
        tag = ""
        if len(ps) > 1 and ps[-1] < ps[-2] and hist[-1][1] == today:
            tag = f"Bajó ${ps[-2] - ps[-1]:,.0f} hoy"
        elif len(ps) > 1 and now == min(ps) and pct > 0:
            tag = "Mínimo histórico"
        elif pct > 0:
            tag = "En promoción"
        items.append(dict(name=name, link=link, cat=cat, image=image, rep=rep, now=now, top=top, pct=pct, ps=ps, tag=tag, is_flash=bool(is_flash)))
    items.sort(key=lambda i: (-i["pct"], i["now"]))  # mejor promoción primero; a igualdad, el más barato
    return items


def aff(link):
    return link + ("&" if "?" in link else "?") + urlencode(config.AFFILIATE)


def money(x):
    return f"${x:,.0f}"


def spark(ps):
    if len(ps) < 2 or max(ps) == min(ps):
        return ""
    lo, hi, n = min(ps), max(ps), len(ps) - 1
    pts = " ".join(f"{k / n * 56:.1f},{16 - (p - lo) / (hi - lo) * 14:.1f}" for k, p in enumerate(ps))
    return (f'<svg class="sp" viewBox="0 0 56 18" width="56" height="18" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>')


def card(i):
    deal = i["pct"] >= config.MIN_DROP_PCT
    flash = i.get("is_flash")
    hot = i["pct"] >= 60 and not flash
    cls = " flash" if flash else (" hot" if hot else "")
    txt = "⚡ " if flash else ("🔥 " if hot else "")
    badge = f'<span class="badge{cls}">{txt}-{i["pct"]:.0f}%</span>' if deal else ""
    old = f'<s>{money(i["top"])}</s>' if deal else ""
    save = f'<p class="save">Ahorras {money(i["top"] - i["now"])}</p>' if deal else ""
    bar = f'<div class="bar"><i style="width:{min(i["pct"], 100):.0f}%"></i></div>' if deal else ""
    trend = (f'<p class="trend">{spark(i["ps"])}<span>{i["tag"]}</span></p>' if i["tag"] or spark(i["ps"]) else "")
    img = (f'<img src="{escape(i["image"])}" alt="{escape(i["name"])}" width="300" height="225" loading="lazy">'
           if i["image"] else "")
    return f"""<a class="card{cls}" href="{escape(aff(i['link']))}" target="_blank" rel="sponsored noopener">
  {badge}<div class="img">{img}</div>
  <div class="body"><span class="cat" title="{escape(i['cat'])}">{escape(i['cat'])}</span>
  <h3>{escape(i['name'])}</h3>
  <p class="price"><strong>{money(i['now'])}</strong><small>MXN</small> {old}</p>
  {bar}{save}{trend}
  <p class="rep">✓ {escape(i['rep'])}</p>
  <span class="go">Ver oferta →</span></div>
</a>"""


PER_PAGE = 24
TABS = [("Inicio", ""), ("Relámpago", "relampago/"), ("Ofertas", "ofertas/"), ("Categorías", "c/"), ("Más buscados", "t/")]
DISCLAIMER = ("es un rastreador independiente de ofertas. Los precios y la disponibilidad pueden variar rápidamente; "
              "por favor verifica el importe final en la página de la tienda antes de realizar tu compra. "
              "Como afiliado de Mercado Libre, podemos recibir una comisión por compras calificadas, sin costo extra para ti.")
LEGAL = [("Privacidad", "privacidad/"), ("Términos", "terminos/")]


def rel(path):
    """Prefijo relativo para volver a la raíz desde una ruta como 'c/x/2/' (funciona en subcarpetas de GitHub Pages)."""
    return "../" * path.count("/")


def layout(path, title, desc, body, active="", ld=(), robots="index, follow", prev=None, nxt=None):
    """Envoltorio común: head SEO, navbar con buscador y pestañas, footer y scripts."""
    up, url = rel(path), f"{config.SITE_URL}/{path}"
    links = "".join(f'<link rel="{r}" href="{config.SITE_URL}/{p}">' for r, p in (("prev", prev), ("next", nxt)) if p is not None)
    tabs = "".join(f'<a href="{up}{p}"{" class=on" if n == active else ""}>{n}</a>' for n, p in TABS)
    return f"""<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<link rel="icon" href="{up}icon.svg" type="image/svg+xml">
<link rel="manifest" href="{up}manifest.json">
<link rel="canonical" href="{url}">{links}
<meta name="robots" content="{robots}, max-image-preview:large">
<meta property="og:type" content="website">
<meta property="og:locale" content="es_MX">
<meta property="og:site_name" content="{config.SITE_NAME}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:url" content="{url}">
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
<div class="upd" id="upd" hidden></div>
<main>
{body}
</main>
<footer><div class="wrap">
  <nav class="fl">{tabs}</nav>
  <p>{config.SITE_NAME} {DISCLAIMER}</p>
  <p>{" · ".join(f'<a href="{up}{p}">{n}</a>' for n, p in LEGAL)}</p>
</div></footer>
<script src="{up}app.js" defer></script>
</body>
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


def paged(base, active, trail, title, desc, h1, lead, items, after="", robots="index, follow"):
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
  <p class="lead lh">{lead}</p>
  <div class="grid">{"".join(card(i) for i in chunk)}</div>
  {pager(base, n, total)}</section>{after}"""
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


def home(items, deals, lists):
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
    
    flash_deals = [d for d in deals if d.get("is_flash")]
    flash_rail = rail("⚡ Ofertas Relámpago", flash_deals[:16], '<a class="all" href="relampago/">Ver todas →</a>') if flash_deals else ""
    
    rails = "".join(rail(f"Lo mejor en {escape(c)}", [d for d in deals if d["cat"] == c][:15],
                         f'<a class="all" href="{cpath[c]}">Ver todo →</a>' if c in cpath else "") for c in cats)
    explore = "".join(f'<a class="chip" href="{p}">{escape(n)}</a>' for p, n, k, _ in lists if k == "t")
    explore_sec = f'<section class="wrap"><h2>Explora por categoría</h2><div class="chips wrapc"><a class="chip on" href="c/">Todas las categorías</a>{explore}</div></section>'
    faq = "".join(f"<details><summary>{escape(q)}</summary><p>{escape(a)}</p></details>" for q, a in FAQ)
    body = f"""<section class="hero"><div class="wrap">
  <p class="eyebrow"><span class="dot"></span> Mercado Libre México · {len(items)} productos vigilados · Actualizado {today}</p>
  <h1>Los precios cambian todo el tiempo.<br><em>Nosotros los vigilamos por ti.</em></h1>
  <p class="lead">Encuentra las <strong>ofertas relámpago</strong> y las bajas de precio que sí son reales, comparadas con el historial de cada producto. Cero descuentos inventados.</p>
  <ul class="perks"><li>⚡ Relámpago al momento</li><li>📉 Solo bajas verificadas</li><li>🔄 5 actualizaciones al día</li></ul>
  <div class="cta">
    <a class="btn big" href="ofertas/">Ver todas las ofertas</a>
    <a class="ghost" href="#como-funciona">Cómo funciona</a>
    <a class="btn" href="#" onclick="document.getElementById('wa-modal').style.display='flex'; return false;">📱 Únete a WhatsApp</a>
  </div>
</div></section>
{explore_sec}
{flash_rail}
{rail("Las mayores bajas", deals[:16], '<a class="all" href="ofertas/">Ver todas →</a>')}
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

<div id="wa-modal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.75); align-items: center; justify-content: center; z-index: 9999; backdrop-filter: blur(5px); opacity: 0; animation: fadeIn 0.3s forwards;">
  <div style="background: #0f111a; padding: 2.5rem 2rem; border-radius: 16px; max-width: 420px; width: 90%; text-align: center; border: 1px solid #2a2d3e; box-shadow: 0 20px 40px rgba(0,0,0,0.6); transform: translateY(20px); animation: slideUp 0.3s forwards ease-out;">
    <div style="font-size: 3rem; margin-bottom: 1rem;">📱</div>
    <h3 style="margin: 0 0 1rem 0; color: #fff; font-size: 1.5rem;">¡Próximamente!</h3>
    <p style="color: #a0a5b5; line-height: 1.6; margin: 0 0 2rem 0; font-size: 1.05rem;">
      ¡Gracias por tu interés! Estamos trabajando arduamente para crear este servicio y enviarte las mejores ofertas directamente a tu WhatsApp.
    </p>
    <button onclick="document.getElementById('wa-modal').style.display='none'" style="background: #00e57a; color: #07080d; border: none; padding: 1rem 2rem; border-radius: 8px; font-weight: bold; font-size: 1rem; cursor: pointer; width: 100%; transition: opacity 0.2s;">
      Entendido
    </button>
  </div>
</div>
<style>
  @keyframes fadeIn {{ to {{ opacity: 1; }} }}
  @keyframes slideUp {{ to {{ transform: translateY(0); }} }}
</style>
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
<p>El sitio no usa cookies propias, de publicidad ni de seguimiento, ni herramientas de analítica.</p>
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


def build(items):
    """Todas las páginas del sitio: {ruta: html}."""
    today = date.today().isoformat()
    deals = [i for i in items if i["pct"] >= config.MIN_DROP_PCT]
    lists = build_listings(items)
    pages = {"": home(items, deals, lists), "buscar/": search_page(), **legal_pages()}
    lo = lambda s: money(min(i["now"] for i in s))
    
    flash_deals = [d for d in deals if d.get("is_flash")]
    pages.update(paged(
        "relampago/", "Relámpago", [(config.SITE_NAME, ""), ("Relámpago", "relampago/")],
        "Ofertas Relámpago en Mercado Libre",
        f"{len(flash_deals)} ofertas relámpago activas hoy. Precios verificados. Actualizado {today}.",
        "⚡ Ofertas Relámpago",
        f"Ofertas por tiempo limitado detectadas en la última actualización ({today}). Pueden haber terminado: verifica en la tienda." if flash_deals else "Por el momento no hay ofertas relámpago activas. Revisa más tarde.",
        flash_deals, robots="index, follow" if flash_deals else "noindex, follow"))

    pages.update(paged(
        "ofertas/", "Ofertas", [(config.SITE_NAME, ""), ("Ofertas", "ofertas/")],
        "Todas las ofertas en Mercado Libre México",
        f"{len(deals)} ofertas en Mercado Libre México con vendedores confiables, ordenadas de mayor a menor descuento. Actualizado {today}.",
        "Todas las ofertas en Mercado Libre",
        f"{len(deals)} productos con baja de precio, primero los de mayor descuento. Solo vendedores confiables. Actualizado {today}.",
        deals))
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
        pages.update(paged(path, tab, [(config.SITE_NAME, ""), (hubname, f"{kind}/"), (name, path)], title, desc, h1, lead, sel))
    return pages


def search_index(items):
    return [dict(n=i["name"], c=i["cat"], p=round(i["now"]), t=round(i["top"]), d=round(i["pct"], 1),
                 l=aff(i["link"]), i=i["image"] or "", r=i["rep"], g=i["tag"]) for i in items]


def main():
    out = config.OUT_DIR
    out.mkdir(exist_ok=True)
    items = load()
    pages = build(items)
    for path, html in pages.items():
        (out / path).mkdir(parents=True, exist_ok=True)
        (out / path / "index.html").write_text(html, encoding="utf-8")
    (out / "search.json").write_text(json.dumps(search_index(items), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    now = datetime.now(timezone.utc)
    nxt = min((now.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(days=d) for d in (0, 1) for h in config.RUN_HOURS_UTC),
              key=lambda t: (t <= now, t))
    # "next" = arranque de la próxima corrida; la página tarda unos minutos más en publicarse
    (out / "status.json").write_text(json.dumps({"updated": now.isoformat(), "next": nxt.isoformat()}), encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {config.SITE_URL}/sitemap.xml\n")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{config.SITE_URL}/{p}</loc><lastmod>{date.today().isoformat()}</lastmod>"
                  "<changefreq>daily</changefreq></url>" for p in pages if "noindex" not in pages[p]) + "</urlset>\n")
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
            {"src": "icon.svg", "sizes": "512x512", "type": "image/svg+xml"}
        ]
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    
    
    print(f"Sitio generado en {out}: {len(pages)} páginas")


if __name__ == "__main__":
    main()
