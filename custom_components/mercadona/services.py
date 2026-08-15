"""Servicios propios: añadir y quitar dictando, y vaciar el carrito.

`todo.add_item` ya permite añadir, pero estos aceptan la frase tal cual ("dos paquetes
de arroz"), con su cantidad y su intención, igual que la voz.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

SERVICE_ADD = "anadir"
SERVICE_REMOVE = "quitar"
SERVICE_EMPTY = "vaciar_carrito"

ADD_SCHEMA = vol.Schema(
    {
        vol.Required("producto"): cv.string,
        vol.Optional("cantidad"): vol.Coerce(float),
    }
)
REMOVE_SCHEMA = vol.Schema({vol.Required("producto"): cv.string})


def _coordinators(hass: HomeAssistant) -> list:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


async def async_register_services(hass: HomeAssistant) -> None:
    """Registrar los servicios una sola vez, no por cada cuenta configurada."""
    if hass.services.has_service(DOMAIN, SERVICE_ADD):
        return

    async def handle_add(call: ServiceCall) -> None:
        text = call.data["producto"]
        quantity = call.data.get("cantidad")
        for coordinator in _coordinators(hass):
            if quantity is None:
                await coordinator.async_handle_phrase(text)
            else:
                match, _alt, _qty = coordinator.matcher.resolve(text)
                if match is None:
                    raise ServiceValidationError(f"No encuentro nada parecido a «{text}»")
                await coordinator.async_add_product(match.product_id, float(quantity))

    async def handle_remove(call: ServiceCall) -> None:
        text = call.data["producto"]
        for coordinator in _coordinators(hass):
            # El prefijo asegura que se interprete como quitar, diga lo que diga la frase.
            await coordinator.async_handle_phrase(f"quita {text}")

    async def handle_empty(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass):
            if not coordinator.data:
                continue
            for line in list(coordinator.data.lines):
                await coordinator.async_set_quantity(line.product_id, 0)

    hass.services.async_register(DOMAIN, SERVICE_ADD, handle_add, schema=ADD_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE, handle_remove, schema=REMOVE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_EMPTY, handle_empty)
