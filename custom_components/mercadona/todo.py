"""El carrito de Mercadona como lista de tareas de Home Assistant.

Con esto, el carrito se ve y se edita desde la tarjeta de listas, desde la app del
móvil y por voz con Assist, sin abrir la app de Mercadona.

Nota de diseño: **marcar un producto no confirma nada**. Un elemento "completado"
significa "ya no lo quiero en el carrito", así que se quita. Comprar sigue siendo algo
que se hace a mano en la app de Mercadona; esta integración nunca toca el checkout.
"""
from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MercadonaConfigEntry
from .const import DOMAIN
from .coordinator import MercadonaCoordinator
from .entity import MercadonaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MercadonaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([MercadonaCartTodo(entry.runtime_data, entry)])


class MercadonaCartTodo(MercadonaEntity, TodoListEntity):
    """El carrito, como lista de tareas."""

    _attr_translation_key = "cart"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: MercadonaCoordinator, entry: MercadonaConfigEntry) -> None:
        super().__init__(coordinator, entry, "cart")

    @property
    def todo_items(self) -> list[TodoItem]:
        """Un producto por línea. La cantidad va en el nombre cuando es más de uno."""
        if not self.coordinator.data:
            return []
        items = []
        for line in self.coordinator.data.lines:
            name = line.name if line.quantity == 1 else f"{line.quantity:g} × {line.name}"
            if line.unavailable:
                name = f"{name} (no disponible)"
            items.append(
                TodoItem(
                    uid=line.product_id,
                    summary=name,
                    status=TodoItemStatus.NEEDS_ACTION,
                )
            )
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Añadir escribiendo o dictando: se empareja igual que la voz."""
        text = (item.summary or "").strip()
        if not text:
            raise ServiceValidationError("Hay que decir qué producto añadir")

        match, _alternatives, quantity = self.coordinator.matcher.resolve(text)
        if match is None:
            raise ServiceValidationError(
                f"No encuentro ningún producto que se parezca a «{text}»"
            )
        await self.coordinator.async_add_product(match.product_id, quantity)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Marcar un producto lo saca del carrito.

        Completar aquí no compra nada: significa que ya no hace falta.
        """
        if item.status == TodoItemStatus.COMPLETED:
            await self.coordinator.async_set_quantity(item.uid, 0)
            return
        # Renombrar una línea no tiene sentido: el nombre lo pone Mercadona.
        raise HomeAssistantError(
            "Los productos del carrito no se pueden renombrar; quita este y añade otro"
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            await self.coordinator.async_set_quantity(uid, 0)
