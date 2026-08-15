"""El panel de la cocina, servido desde dentro de Home Assistant.

Es la misma interfaz que servía el contenedor, pero como panel propio. Dos ventajas
sobre el iframe que había antes: la autenticación es la de Home Assistant (se acabó
llevar un token en la URL) y, al servirse desde el mismo origen, también funciona
desde fuera de casa por HTTPS.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

PANEL_DIR = Path(__file__).parent / "panel"
PANEL_JS = f"/{DOMAIN}_panel/panel.js"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Servir los estáticos y colgar el panel de la barra lateral."""
    if PANEL_URL in hass.data.get("frontend_panels", {}):
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"/{DOMAIN}_panel", str(PANEL_DIR), cache_headers=False)]
    )

    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL,
        require_admin=False,
        config={
            "_panel_custom": {
                "name": "mercadona-panel",
                "module_url": PANEL_JS,
                "embed_iframe": False,
                "trust_external": False,
            }
        },
    )
    _LOGGER.debug("panel registrado en /%s", PANEL_URL)


def async_remove_panel(hass: HomeAssistant) -> None:
    from homeassistant.components.frontend import async_remove_panel as _remove

    if PANEL_URL in hass.data.get("frontend_panels", {}):
        _remove(hass, PANEL_URL)


class MercadonaStateView(HomeAssistantView):
    """Todo lo que el panel necesita pintar, en una sola llamada."""

    url = f"/api/{DOMAIN}/state"
    name = f"api:{DOMAIN}:state"

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator

    async def get(self, request):
        data = self.coordinator.data
        in_cart = {line.product_id for line in data.lines} if data else set()
        return self.json(
            {
                "cart": [
                    {
                        "id": l.product_id,
                        "name": l.name,
                        "quantity": l.quantity,
                        "price": l.price,
                        "packaging": l.packaging,
                        "thumbnail": l.thumbnail,
                        "unavailable": l.unavailable,
                    }
                    for l in (data.lines if data else [])
                ],
                "cart_total": data.total if data else None,
                "regulars": [
                    {**p, "in_cart": p["id"] in in_cart} for p in (data.regulars if data else [])
                ],
                "catalog_size": data.catalog_size if data else 0,
                "ok": self.coordinator.last_update_success,
            }
        )


class MercadonaCartView(HomeAssistantView):
    """Añadir, cambiar cantidad o quitar desde el panel."""

    url = f"/api/{DOMAIN}/cart"
    name = f"api:{DOMAIN}:cart"

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator

    async def post(self, request):
        body = await request.json()
        product_id = str(body.get("product_id", ""))
        if not product_id:
            return self.json_message("falta product_id", 400)

        try:
            if "quantity" in body:
                await self.coordinator.async_set_quantity(product_id, float(body["quantity"]))
            else:
                await self.coordinator.async_add_product(product_id, float(body.get("add", 1)))
        except HomeAssistantError as err:
            return self.json_message(str(err), 502)
        return self.json({"ok": True})


class MercadonaSearchView(HomeAssistantView):
    """Buscar productos con el mismo criterio que la voz."""

    url = f"/api/{DOMAIN}/search"
    name = f"api:{DOMAIN}:search"

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator

    async def get(self, request):
        query = request.query.get("q", "").strip()
        if not query:
            return self.json([])
        return self.json(self.coordinator.search(query, limit=24))


def async_register_views(hass: HomeAssistant, coordinator: Any) -> None:
    hass.http.register_view(MercadonaStateView(coordinator))
    hass.http.register_view(MercadonaCartView(coordinator))
    hass.http.register_view(MercadonaSearchView(coordinator))
