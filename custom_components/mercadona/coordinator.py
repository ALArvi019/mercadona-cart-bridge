"""Coordinador: mantiene el carrito, los habituales y el buzón de voz.

Concentra aquí todo lo que habla con el exterior para que las entidades y el panel se
limiten a pintar. Nada de esto debe bloquear el bucle de eventos de Home Assistant.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    AMBIGUITY_EVENT,
    CATALOG_INTERVAL,
    CONF_GKEEP_EMAIL,
    CONF_GKEEP_LIST,
    CONF_GKEEP_TOKEN,
    CONF_MAX_BATCH,
    CONF_POLL_SECONDS,
    DEFAULT_MAX_BATCH,
    DEFAULT_POLL_SECONDS,
    DOMAIN,
    REGULARS_INTERVAL,
    UPDATE_INTERVAL,
)
from .core.catalog import Catalog
from .core.client import MercadonaClient, SessionExpired
from .core.keep import KeepInbox, normalize_list_names, poll_loop
from .core.matching import (
    AMBIGUITY_GAP,
    CONFIDENT_SCORE,
    Matcher,
    parse_intent,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class CartLine:
    product_id: str
    name: str
    quantity: float
    price: float | None
    packaging: str
    thumbnail: str
    unavailable: bool


@dataclass
class MercadonaData:
    """Lo que ven las entidades y el panel."""

    lines: list[CartLine] = field(default_factory=list)
    total: float | None = None
    regulars: list[dict[str, Any]] = field(default_factory=list)
    catalog_size: int = 0
    last_voice: str = ""


def _slim(product: dict[str, Any]) -> dict[str, Any]:
    price = product.get("price_instructions") or {}
    return {
        "id": str(product["id"]),
        "name": product.get("display_name", ""),
        "packaging": product.get("packaging") or "",
        "thumbnail": product.get("thumbnail") or "",
        "price": price.get("unit_price"),
        "unavailable": product.get("status") == "unavailable"
        or not product.get("published", True),
    }


class MercadonaCoordinator(DataUpdateCoordinator[MercadonaData]):
    """Un único punto de verdad para toda la integración."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: MercadonaClient, catalog: Catalog
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.catalog = catalog
        self.aliases: dict[str, str] = {}
        self._regulars: list[dict[str, Any]] = []
        self._regulars_at: datetime | None = None
        self._history: list[dict[str, Any]] = []
        self._catalog_at: datetime | None = None
        self._tasks: list[asyncio.Task] = []
        self.matcher = Matcher(
            catalog,
            lambda: self._regulars,
            lambda: self._history,
            self.aliases.get,
        )

    # ------------------------------------------------------------ refresco

    async def _async_update_data(self) -> MercadonaData:
        try:
            cart = await self.client.get_cart()
        except SessionExpired as err:
            # Home Assistant pedirá un token nuevo por la interfaz.
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(f"no se pudo leer el carrito: {err}") from err

        lines = [
            CartLine(
                product_id=str(line["product"]["id"]),
                name=line["product"].get("display_name", ""),
                quantity=float(line["quantity"]),
                price=(line["product"].get("price_instructions") or {}).get("unit_price"),
                packaging=line["product"].get("packaging") or "",
                thumbnail=line["product"].get("thumbnail") or "",
                unavailable=line["product"].get("status") == "unavailable",
            )
            for line in cart.get("lines", [])
        ]

        now = dt_util.utcnow()
        if self._regulars_at is None or now - self._regulars_at > REGULARS_INTERVAL:
            try:
                self._regulars = await self.client.my_regulars()
                self._regulars_at = now
            except Exception as err:
                _LOGGER.warning("no se pudieron leer los habituales: %s", err)

        total = (cart.get("summary") or {}).get("total")
        return MercadonaData(
            lines=lines,
            total=float(total) if total is not None else None,
            regulars=[_slim(p) for p in self._regulars],
            catalog_size=len(self.catalog.products),
            last_voice=self.data.last_voice if self.data else "",
        )

    # ------------------------------------------------------- tareas de fondo

    async def async_start_background(self, entry: ConfigEntry) -> None:
        """Catálogo, historial y buzón de voz, sin bloquear el arranque."""
        self._tasks.append(entry.async_create_background_task(
            self.hass, self._catalog_loop(), f"{DOMAIN}_catalog"
        ))

        email = entry.data.get(CONF_GKEEP_EMAIL)
        token = entry.data.get(CONF_GKEEP_TOKEN)
        list_names = normalize_list_names(entry.data.get(CONF_GKEEP_LIST))
        if email and token and list_names:
            inbox = KeepInbox(
                email,
                token,
                list_names,
                max_batch=entry.options.get(CONF_MAX_BATCH, DEFAULT_MAX_BATCH),
            )
            interval = entry.options.get(CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS)
            self._tasks.append(entry.async_create_background_task(
                self.hass, poll_loop(inbox, self.async_handle_phrase, interval),
                f"{DOMAIN}_keep",
            ))
            _LOGGER.info("buzón de voz activo sobre %s", ", ".join(list_names))
        else:
            _LOGGER.info("sin Google Keep configurado: la voz queda desactivada")

    async def _catalog_loop(self) -> None:
        while True:
            try:
                await self.catalog.refresh_if_stale(self.client)
                await self._refresh_history()
                self._catalog_at = dt_util.utcnow()
            except Exception as err:
                _LOGGER.warning("no se pudo refrescar el catálogo: %s", err)
            await asyncio.sleep(CATALOG_INTERVAL.total_seconds())

    async def _refresh_history(self) -> None:
        """Lo comprado en los últimos pedidos, para que el emparejador lo prefiera."""
        products: dict[str, dict[str, Any]] = {}
        try:
            for order in (await self.client.orders())[:5]:
                oid = order.get("id")
                if oid is None:
                    continue
                detail = await self.client.order_detail(oid)
                for line in detail.get("lines", []) or []:
                    if product := line.get("product"):
                        products[str(product["id"])] = product
                await asyncio.sleep(0.2)
        except Exception as err:
            _LOGGER.debug("no se pudo leer el historial: %s", err)
            return
        self._history = list(products.values())

    async def async_shutdown_tasks(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    # --------------------------------------------------------- operaciones

    async def async_add_product(self, product_id: str, quantity: float = 1.0) -> None:
        try:
            await self.client.add_product(product_id, quantity)
        except Exception as err:
            raise HomeAssistantError(f"no se pudo añadir al carrito: {err}") from err
        await self.async_request_refresh()

    async def async_set_quantity(self, product_id: str, quantity: float) -> None:
        try:
            await self.client.set_quantity(product_id, quantity)
        except Exception as err:
            raise HomeAssistantError(f"no se pudo actualizar el carrito: {err}") from err
        await self.async_request_refresh()

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Busca con el mismo criterio que usa la voz."""
        match, alternatives, _ = self.matcher.resolve(query)
        found = ([match] if match else []) + alternatives
        return [
            {**_slim(m.product), "score": round(m.score, 3), "source": m.source}
            for m in found[:limit]
        ]

    # ---------------------------------------------------------------- voz

    async def async_handle_phrase(self, text: str) -> None:
        """Aplica al carrito una frase dictada."""
        request = parse_intent(text)

        if request.intent == "remove":
            await self._handle_remove(text, request)
            return

        match, alternatives, qty = self.matcher.resolve(text)
        if match is None:
            _LOGGER.info("sin coincidencia clara para %r", text)
            self._fire_event("no_encontrado", frase=request.query)
            return

        await self.async_add_product(match.product_id, qty)
        self.data.last_voice = f"{match.name} x{qty:g}" if self.data else ""
        _LOGGER.info("añadido %s x%g (%s, %.2f)", match.name, qty, match.source, match.score)

        # Se ha añadido, pero puede no ser lo que se pedía.
        rival = alternatives[0] if alternatives else None
        close_call = rival is not None and (match.score - rival.score) < AMBIGUITY_GAP
        if close_call or match.score < CONFIDENT_SCORE:
            self._fire_event(
                "ambiguo",
                frase=request.query,
                producto=match.name,
                producto_id=match.product_id,
                imagen=match.product.get("thumbnail") or "",
                precio=(match.product.get("price_instructions") or {}).get("unit_price"),
                alternativa=rival.name if rival else "",
            )

    async def _handle_remove(self, text: str, request: Any) -> None:
        cart = await self.client.get_cart()
        lines = cart.get("lines", [])
        products = [line["product"] for line in lines]
        match, _alternatives = self.matcher.resolve_in_cart(products, text)

        if match is None:
            _LOGGER.info("no encuentro %r en el carrito", request.query)
            self._fire_event("no_encontrado", frase=request.query, en_carrito=True)
            return

        current = next(
            (float(l["quantity"]) for l in lines if str(l["product"]["id"]) == match.product_id),
            0.0,
        )
        # "quita 1 mantequilla" resta una; "quita mantequilla" saca la línea entera.
        new_qty = max(0.0, current - request.quantity) if request.explicit_quantity else 0.0
        await self.async_set_quantity(match.product_id, new_qty)
        _LOGGER.info("quitado %s: de %g a %g", match.name, current, new_qty)

    def _fire_event(self, tipo: str, **data: Any) -> None:
        """Avisa en el bus de eventos.

        Se deja en manos de una automatización qué hacer con esto (notificación al
        móvil, voz en un altavoz...), en vez de fijarlo aquí.
        """
        self.hass.bus.async_fire(AMBIGUITY_EVENT, {"tipo": tipo, **data})
