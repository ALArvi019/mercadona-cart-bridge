"""Cliente de la API privada de Mercadona.

Documentación de los endpoints en docs/api-mercadona.md. Dos cosas gobiernan el diseño
de este módulo:

1. El refresh token rota en cada renovación, así que hay que persistirlo o se pierde
   la sesión y toca volver a extraerlo del móvil.
2. El carrito solo se puede escribir entero (PUT). Toda modificación es un
   read-modify-write, y por eso se serializa con un lock y se reintenta si el carrito
   ha cambiado por debajo.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

BASE = "https://tienda.mercadona.es/api"
# Margen para renovar el access token antes de que caduque de verdad.
RENEW_MARGIN_S = 24 * 3600


class MercadonaError(RuntimeError):
    pass


class SessionExpired(MercadonaError):
    """El refresh token ya no sirve: hay que volver a extraerlo del móvil."""


@dataclass
class Session:
    access_token: str = ""
    refresh_token: str = ""
    customer_id: str = ""
    postal_code: str = ""
    warehouse: str = ""

    def as_dict(self) -> dict[str, str]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Session":
        if not data:
            return cls()
        known = {f: data.get(f, "") for f in cls.__dataclass_fields__}
        return cls(**known)


class SessionStore(Protocol):
    """Dónde se guarda la sesión.

    Existe porque el refresh token rota en cada renovación: hay que persistirlo o se
    pierde la sesión. El contenedor lo guarda en un fichero y Home Assistant en su
    propio almacén, así que el cliente no debe saber cuál de los dos es.
    """

    def load(self) -> Session: ...

    async def save(self, session: Session) -> None: ...


class FileSessionStore:
    """Sesión en un fichero JSON. La usa el contenedor."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Session:
        if self._path.exists():
            return Session.from_dict(json.loads(self._path.read_text()))
        return Session()

    async def save(self, session: Session) -> None:
        def write() -> None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(session.as_dict(), indent=2))
            self._path.chmod(0o600)

        # Fuera del bucle de eventos: escribir en disco lo bloquea.
        await asyncio.to_thread(write)


def _jwt_exp(token: str) -> int:
    """Caducidad de un JWT sin validar la firma (solo la usamos para saber cuándo renovar)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except Exception:
        return 0


class MercadonaClient:
    def __init__(self, store: SessionStore, bootstrap_refresh_token: str = "",
                 postal_code: str = "", warehouse: str = "",
                 http: httpx.AsyncClient | None = None) -> None:
        self._store = store
        self.session = store.load()
        # El token de la configuración solo se usa si no hay sesión guardada todavía.
        if not self.session.refresh_token and bootstrap_refresh_token:
            self.session.refresh_token = bootstrap_refresh_token
        self.session.postal_code = self.session.postal_code or postal_code
        self.session.warehouse = self.session.warehouse or warehouse
        # Crear el cliente lee los certificados del sistema, que es E/S de disco. En
        # Home Assistant hay que pasarle uno ya construido fuera del bucle de eventos.
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._auth_lock = asyncio.Lock()
        self._cart_lock = asyncio.Lock()

    async def close(self) -> None:
        # Si el cliente vino de fuera, es de quien lo creó: no se cierra aquí.
        if self._owns_http:
            await self._http.aclose()

    # ---------------------------------------------------------------- auth

    def _headers(self, auth: bool = True) -> dict[str, str]:
        h = {
            "Accept": "application/json",
            "Accept-Language": "es",
            "Content-Type": "application/json",
            "User-Agent": "okhttp/4.12.0",
        }
        if self.session.customer_id:
            h["X-Customer-Device-Id"] = self.session.customer_id
        if auth and self.session.access_token:
            h["Authorization"] = f"Bearer {self.session.access_token}"
        return h

    async def ensure_token(self) -> None:
        async with self._auth_lock:
            exp = _jwt_exp(self.session.access_token)
            if self.session.access_token and exp - time.time() > RENEW_MARGIN_S:
                return
            await self._refresh()

    async def _refresh(self) -> None:
        if not self.session.refresh_token:
            raise SessionExpired("no hay refresh token; extráelo del móvil (ver docs/obtener-token.md)")
        r = await self._http.post(
            f"{BASE}/auth/tokens/",
            headers=self._headers(auth=False),
            json={"refresh_token": self.session.refresh_token},
        )
        if r.status_code in (400, 401, 403):
            raise SessionExpired(f"refresh rechazado ({r.status_code}); hay que volver a extraer el token")
        r.raise_for_status()
        d = r.json()
        self.session.access_token = d["access_token"]
        # Rota: si no guardamos el nuevo, la siguiente renovación falla.
        if d.get("refresh_token"):
            self.session.refresh_token = d["refresh_token"]
        self.session.customer_id = d.get("customer_id") or self.session.customer_id
        await self._store.save(self.session)
        log.info("token renovado, caduca %s",
                 time.strftime("%Y-%m-%d %H:%M", time.localtime(_jwt_exp(self.session.access_token))))

    async def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        await self.ensure_token()
        r = await self._http.request(method, f"{BASE}{path}", headers=self._headers(), **kw)
        if r.status_code == 401:
            # Puede haber caducado antes de tiempo (cambio de contraseña, revocación...).
            async with self._auth_lock:
                await self._refresh()
            r = await self._http.request(method, f"{BASE}{path}", headers=self._headers(), **kw)
        r.raise_for_status()
        return r

    # ------------------------------------------------------------- cliente

    async def profile(self) -> dict[str, Any]:
        r = await self._request("GET", f"/customers/{self.session.customer_id}/")
        d = r.json()
        if d.get("current_postal_code"):
            self.session.postal_code = d["current_postal_code"]
            await self._store.save(self.session)
        return d

    # ------------------------------------------------------------- carrito

    async def get_cart(self) -> dict[str, Any]:
        r = await self._request("GET", f"/customers/{self.session.customer_id}/cart/")
        return r.json()

    @staticmethod
    def _to_lines(cart: dict[str, Any]) -> list[dict[str, Any]]:
        """Convierte las líneas que devuelve el GET al formato que espera el PUT."""
        return [
            {
                "product_id": str(l["product"]["id"]),
                "quantity": float(l["quantity"]),
                "sources": l.get("sources") or ["+CT"],
            }
            for l in cart.get("lines", [])
        ]

    async def _put_cart(self, cart: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
        r = await self._request(
            "PUT",
            f"/customers/{self.session.customer_id}/cart/",
            json={"version": cart["version"], "lines": lines},
        )
        return r.json()

    async def _modify(self, mutate, retries: int = 3) -> dict[str, Any]:
        """Read-modify-write serializado sobre el carrito.

        `mutate(lines)` recibe las líneas en formato PUT y devuelve las nuevas.
        Si devuelve None, no se escribe nada.
        """
        async with self._cart_lock:
            last: Exception | None = None
            for attempt in range(retries):
                cart = await self.get_cart()
                new_lines = mutate(self._to_lines(cart))
                if new_lines is None:
                    return cart
                try:
                    return await self._put_cart(cart, new_lines)
                except httpx.HTTPStatusError as e:
                    # 409/400 suele ser choque de versión: releemos y repetimos.
                    if e.response.status_code not in (400, 409) or attempt == retries - 1:
                        raise
                    last = e
                    await asyncio.sleep(0.5 * (attempt + 1))
            raise MercadonaError(f"no se pudo escribir el carrito: {last}")

    async def add_product(self, product_id: str, quantity: float = 1.0) -> dict[str, Any]:
        """Añade unidades de un producto; si ya estaba, suma a la cantidad existente."""
        product_id = str(product_id)

        def mutate(lines: list[dict[str, Any]]):
            for l in lines:
                if l["product_id"] == product_id:
                    l["quantity"] = l["quantity"] + quantity
                    return lines
            lines.append({"product_id": product_id, "quantity": quantity, "sources": ["+CT"]})
            return lines

        return await self._modify(mutate)

    async def set_quantity(self, product_id: str, quantity: float) -> dict[str, Any]:
        """Fija la cantidad de un producto. Con 0 lo elimina del carrito."""
        product_id = str(product_id)

        def mutate(lines: list[dict[str, Any]]):
            out = [l for l in lines if l["product_id"] != product_id]
            if quantity > 0:
                out.append({"product_id": product_id, "quantity": quantity, "sources": ["+CT"]})
            return out

        return await self._modify(mutate)

    async def remove_product(self, product_id: str) -> dict[str, Any]:
        return await self.set_quantity(product_id, 0)

    # ----------------------------------------------------------- habituales

    async def my_regulars(self) -> list[dict[str, Any]]:
        r = await self._request("GET", f"/customers/{self.session.customer_id}/recommendations/myregulars/")
        data = r.json()
        # Viene como lista de envoltorios {"product": {...}}; devolvemos los productos.
        out = []
        for item in data if isinstance(data, list) else data.get("results", []):
            p = item.get("product") if isinstance(item, dict) else None
            if p:
                out.append(p)
        return out

    async def orders(self) -> list[dict[str, Any]]:
        r = await self._request("GET", f"/customers/{self.session.customer_id}/orders/")
        d = r.json()
        return d.get("results", d) if isinstance(d, dict) else d

    async def order_detail(self, order_id: str | int) -> dict[str, Any]:
        r = await self._request("GET", f"/customers/{self.session.customer_id}/orders/{order_id}/")
        return r.json()

    # ------------------------------------------------------------ catálogo

    def _catalog_params(self) -> dict[str, str]:
        """Con sesión iniciada, Mercadona ya sabe de qué almacén servir.

        Comprobado: pedir una categoría con y sin `wh` devuelve exactamente los mismos
        productos, precios y disponibilidad. Solo se manda si se ha configurado a mano.
        """
        params = {"lang": "es"}
        if self.session.warehouse:
            params["wh"] = self.session.warehouse
        return params

    async def categories(self) -> list[dict[str, Any]]:
        r = await self._request("GET", "/categories/", params=self._catalog_params())
        return r.json().get("results", [])

    async def category(self, category_id: int) -> dict[str, Any]:
        r = await self._request("GET", f"/categories/{category_id}/",
                                params=self._catalog_params())
        return r.json()
