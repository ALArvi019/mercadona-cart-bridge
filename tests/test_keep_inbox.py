"""Pruebas del buzón de Keep.

Lo que se protege aquí: una lista usada antes a mano acumula cientos de elementos
tachados de compras pasadas. Procesarlos volcaría todo ese historial al carrito.
"""
from __future__ import annotations

from app.core.keep import KeepInbox


class FakeItem:
    def __init__(self, text: str, checked: bool = False) -> None:
        self.text = text
        self.checked = checked
        self.deleted = False

    def delete(self) -> None:
        self.deleted = True


class FakeNote:
    def __init__(self, title: str, items: list[FakeItem]) -> None:
        self.title = title
        self.items = items
        self.trashed = False


class FakeKeep:
    def __init__(self, notes: list[FakeNote]) -> None:
        self._notes = notes
        self.syncs = 0

    def all(self) -> list[FakeNote]:
        return self._notes

    def sync(self) -> None:
        self.syncs += 1


def inbox_with(note: FakeNote, max_batch: int = 15) -> KeepInbox:
    inbox = KeepInbox("x@y.z", "token", note.title, max_batch=max_batch)
    inbox._keep = FakeKeep([note])
    return inbox


def test_ignora_los_elementos_tachados():
    note = FakeNote("Lista", [
        FakeItem("papel higiénico"),
        FakeItem("leche comprada hace un mes", checked=True),
        FakeItem("pan de 2024", checked=True),
    ])
    inbox = inbox_with(note)

    assert inbox._drain_sync() == ["papel higiénico"]
    # El historial tachado se queda donde está.
    assert note.items[1].deleted is False
    assert note.items[2].deleted is False


def test_borra_lo_que_procesa():
    note = FakeNote("Lista", [FakeItem("mantequilla"), FakeItem("puerro")])
    inbox = inbox_with(note)

    assert inbox._drain_sync() == ["mantequilla", "puerro"]
    assert all(i.deleted for i in note.items)


def test_limita_el_volumen_por_ciclo():
    note = FakeNote("Lista", [FakeItem(f"producto {n}") for n in range(50)])
    inbox = inbox_with(note, max_batch=15)

    first = inbox._drain_sync()
    assert len(first) == 15
    assert sum(1 for i in note.items if i.deleted) == 15

    # El resto no se pierde: entra en los siguientes sondeos.
    note.items = [i for i in note.items if not i.deleted]
    assert len(inbox._drain_sync()) == 15


def test_ignora_elementos_vacios():
    note = FakeNote("Lista", [FakeItem("  "), FakeItem("sal")])
    assert inbox_with(note)._drain_sync() == ["sal"]


def test_lista_inexistente_no_rompe():
    note = FakeNote("Otra cosa", [FakeItem("x")])
    inbox = KeepInbox("x@y.z", "token", "Lista que no está")
    inbox._keep = FakeKeep([note])
    assert inbox._drain_sync() == []
    assert note.items[0].deleted is False


def test_titulo_insensible_a_mayusculas_y_espacios():
    note = FakeNote(" Mi Lista De La Compra ", [FakeItem("arroz")])
    inbox = KeepInbox("x@y.z", "token", "mi lista de la compra")
    inbox._keep = FakeKeep([note])
    assert inbox._drain_sync() == ["arroz"]
