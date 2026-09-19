"""Cliente mínimo de la API oficial de Mercado Libre."""
import time

import requests

import config

API = "https://api.mercadolibre.com"


class MercadoLibre:
    def __init__(self):
        self.session = requests.Session()
        self._token = None
        self._expires = 0.0
        self._reps = {}

    def _auth(self):
        if self._token and time.time() < self._expires - 60:
            return
        r = self.session.post(
            f"{API}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": config.CLIENT_ID,
                "client_secret": config.CLIENT_SECRET,
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._expires = time.time() + data["expires_in"]

    def get(self, path, **params):
        for wait in (0, 30, 90, 180):
            self._auth()
            time.sleep(config.REQUEST_DELAY + wait)
            r = self.session.get(
                f"{API}/{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=20,
            )
            if r.status_code != 429:  # 429 = límite de peticiones: esperar y reintentar
                break
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def best_sellers(self, category_id, limit):
        """IDs de productos de catálogo más vendidos en una categoría."""
        data = self.get(f"highlights/{config.SITE}/category/{category_id}")
        if not data:
            return []
        ids = [c["id"] for c in data.get("content", []) if c.get("type") == "PRODUCT"]
        return ids[:limit]

    def product(self, product_id):
        data = self.get(f"products/{product_id}")
        if not data:
            return None
        return {
            "id": product_id,
            "name": data.get("name", product_id),
            "image": (data.get("pictures") or [{}])[0].get("url"),
            "link": data.get("permalink") or f"https://www.mercadolibre.com.mx/p/{product_id}",
        }

    def subcategories(self, category_id):
        data = self.get(f"categories/{category_id}")
        return [(c["id"], c["name"]) for c in (data or {}).get("children_categories", [])]

    def seller_rep(self, seller_id):
        """Etiqueta de reputación si el vendedor es confiable (nivel verde), si no None."""
        if seller_id not in self._reps:
            rep = ((self.get(f"users/{seller_id}") or {}).get("seller_reputation") or {})
            if rep.get("level_id") in ("4_light_green", "5_green"):
                power = rep.get("power_seller_status")
                self._reps[seller_id] = f"MercadoLíder {power.capitalize()}" if power else "Vendedor confiable"
            else:
                self._reps[seller_id] = None
        return self._reps[seller_id]

    def best_price(self, product_id):
        """(precio, original, reputación) de la oferta nueva más barata de un vendedor confiable; original es None sin promoción."""
        data = self.get(f"products/{product_id}/items", limit=50)
        if not data:
            return None
        items = [it for it in data.get("results", []) if it.get("condition") == "new" and it.get("price")]
        if not items:
            return None
        for best in sorted(items, key=lambda it: it["price"])[:8]:
            rep = "Tienda oficial" if best.get("official_store_id") else self.seller_rep(best["seller_id"])
            if rep:
                orig = best.get("original_price")
                return best["price"], (orig if orig and orig > best["price"] else None), rep
        return None
