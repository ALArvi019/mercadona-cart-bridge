"""Sensores del carrito."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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
    coordinator = entry.runtime_data
    async_add_entities([CartTotalSensor(coordinator, entry), CartItemsSensor(coordinator, entry)])


class CartTotalSensor(MercadonaEntity, SensorEntity):
    """Lo que suma el carrito ahora mismo."""

    _attr_translation_key = "cart_total"
    _attr_native_unit_of_measurement = "EUR"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: MercadonaCoordinator, entry: MercadonaConfigEntry) -> None:
        super().__init__(coordinator, entry, "cart_total")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.total if self.coordinator.data else None


class CartItemsSensor(MercadonaEntity, SensorEntity):
    """Cuántos productos distintos hay en el carrito."""

    _attr_translation_key = "cart_items"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cart-outline"

    def __init__(self, coordinator: MercadonaCoordinator, entry: MercadonaConfigEntry) -> None:
        super().__init__(coordinator, entry, "cart_items")

    @property
    def native_value(self) -> int | None:
        return len(self.coordinator.data.lines) if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        if not self.coordinator.data:
            return {}
        return {
            "productos": [
                {"nombre": l.name, "cantidad": l.quantity, "precio": l.price}
                for l in self.coordinator.data.lines
            ],
            "habituales": len(self.coordinator.data.regulars),
            "catalogo": self.coordinator.data.catalog_size,
            "ultimo_por_voz": self.coordinator.data.last_voice,
        }
