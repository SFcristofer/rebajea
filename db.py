"""Historial de precios en SQLite."""
import sqlite3

import config


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=60)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY, name TEXT, link TEXT, category TEXT, image TEXT
        );
        CREATE TABLE IF NOT EXISTS prices (
            product_id TEXT, price REAL, seen_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_prices ON prices(product_id, seen_at);
        """
    )
    migrate(conn)
    return conn


def migrate(conn):
    """orig = precio tachado (promoción) que reporta la tienda; rep = reputación del vendedor; is_flash = oferta relámpago."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(prices)")]
    for col, typ in (("orig", "REAL"), ("rep", "TEXT"), ("is_flash", "INTEGER")):
        if col not in cols:
            conn.execute(f"ALTER TABLE prices ADD COLUMN {col} {typ}")


def known_product(conn, product_id):
    return conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone()


def save_product(conn, p, category):
    conn.execute(
        "INSERT OR REPLACE INTO products VALUES (?,?,?,?,?)",
        (p["id"], p["name"], p["link"], category, p["image"]),
    )


def last_price(conn, product_id):
    row = conn.execute(
        "SELECT price FROM prices WHERE product_id=? ORDER BY seen_at DESC, rowid DESC LIMIT 1",
        (product_id,),
    ).fetchone()
    return row[0] if row else None


def save_price(conn, product_id, price, orig=None, rep=None, is_flash=0):
    conn.execute("INSERT INTO prices (product_id, price, orig, rep, is_flash) VALUES (?,?,?,?,?)", (product_id, price, orig, rep, int(is_flash)))


def product_info(conn, product_id):
    return conn.execute("SELECT name, link FROM products WHERE id=?", (product_id,)).fetchone()
