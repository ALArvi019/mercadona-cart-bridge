"""Persistencia de la sesión dentro de Home Assistant.

El refresh token de Mercadona rota en cada renovación, así que no vale con guardarlo
en el config entry y olvidarse: hay que reescribirlo cada vez. Se usa el almacén de
Home Assistant, que además entra en sus copias de seguridad.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .core.client import Session


class HaSessionStore:
    """Implementa SessionStore sobre el almacén de Home Assistant."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}", private=True
        )
        self._cached = Session()

    async def async_load(self) -> Session:
        """Carga inicial. Hay que llamarla antes de crear el cliente."""
        data = await self._store.async_load()
        self._cached = Session.from_dict(data)
        return self._cached

    # --- interfaz que espera el núcleo ---

    def load(self) -> Session:
        return self._cached

    async def save(self, session: Session) -> None:
        self._cached = session
        await self._store.async_save(session.as_dict())

    async def async_remove(self) -> None:
        await self._store.async_remove()


class MemorySessionStore:
    """Sesión que no se guarda en ningún sitio, para validar credenciales."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session or Session()

    def load(self) -> Session:
        return self._session

    async def save(self, session: Session) -> None:
        self._session = session
