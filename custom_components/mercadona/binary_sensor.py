"""Estado de la sesión con Mercadona.

Sirve para enterarse de que hay que renovar el token sin descubrirlo el día que
alguien dicta algo y no llega al carrito.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MercadonaConfigEntry
from .coordinator import MercadonaCoordinator
from .entity import MercadonaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MercadonaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([SessionProblem(entry.runtime_data, entry)])


class SessionProblem(MercadonaEntity, BinarySensorEntity):
    """Se enciende cuando la sesión deja de funcionar."""

    _attr_translation_key = "session"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MercadonaCoordinator, entry: MercadonaConfigEntry) -> None:
        super().__init__(coordinator, entry, "session")

    @property
    def is_on(self) -> bool:
        return not self.coordinator.last_update_success

    @property
    def available(self) -> bool:
        # Este sensor tiene que seguir informando justo cuando lo demás falla.
        return True
