"""Integración de Mercadona: carrito, habituales y lista de la compra por voz."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.httpx_client import get_async_client

from .const import (
    CONF_POSTAL_CODE,
    CONF_REFRESH_TOKEN,
    CONF_WAREHOUSE,
    DOMAIN,
)
from .core.catalog import Catalog
from .core.client import MercadonaClient, SessionExpired
from .coordinator import MercadonaCoordinator
from .panel import (
    async_register_panel,
    async_register_views,
    async_remove_panel,
)
from .services import async_register_services
from .storage import HaSessionStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.TODO]

type MercadonaConfigEntry = ConfigEntry[MercadonaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MercadonaConfigEntry) -> bool:
    """Levantar la integración."""
    store = HaSessionStore(hass, entry.entry_id)
    await store.async_load()

    client = MercadonaClient(
        store,
        bootstrap_refresh_token=entry.data.get(CONF_REFRESH_TOKEN, ""),
        postal_code=entry.data.get(CONF_POSTAL_CODE, ""),
        warehouse=entry.data.get(CONF_WAREHOUSE, ""),
        http=get_async_client(hass),
    )

    try:
        await client.ensure_token()
        profile = await client.profile()
    except SessionExpired as err:
        await client.close()
        # Dispara el flujo de reautenticación: pedirá un token nuevo por la interfaz.
        raise ConfigEntryAuthFailed(str(err)) from err
    except Exception as err:
        await client.close()
        raise ConfigEntryNotReady(f"no se pudo contactar con Mercadona: {err}") from err

    _LOGGER.info(
        "sesión de %s (%s), almacén %s",
        profile.get("name"),
        profile.get("current_postal_code"),
        client.session.warehouse or "por detectar",
    )

    catalog = Catalog(
        Path(hass.config.path(f".storage/{DOMAIN}_catalog_{entry.entry_id}.json")),
        refresh_hours=24,
    )
    await catalog.async_load()

    coordinator = MercadonaCoordinator(hass, entry, client, catalog)
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_start_background(entry)

    entry.runtime_data = coordinator

    # El panel de la cocina y su API, servidos por Home Assistant.
    async_register_views(hass, coordinator)
    await async_register_panel(hass)
    await async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MercadonaConfigEntry) -> bool:
    """Parar la integración y soltar lo que tenga abierto."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = entry.runtime_data
        await coordinator.async_shutdown_tasks()
        await coordinator.client.close()
        # El panel solo sobra cuando ya no queda ninguna cuenta configurada.
        if len(hass.config_entries.async_entries(DOMAIN)) <= 1:
            async_remove_panel(hass)
    return unloaded


async def _async_reload_on_options(hass: HomeAssistant, entry: MercadonaConfigEntry) -> None:
    """Cambiar el ritmo del buzón o el tope por sondeo exige rearrancar las tareas."""
    await hass.config_entries.async_reload(entry.entry_id)
