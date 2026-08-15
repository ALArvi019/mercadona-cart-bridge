"""Pruebas del emparejador: es la pieza que decide qué acaba en el carrito."""
from __future__ import annotations

import pytest

from app.core.matching import Matcher, parse_request, tokens


def product(pid: str, name: str, **extra):
    return {"id": pid, "display_name": name, "published": True, "thumbnail": "", **extra}


CATALOG_PRODUCTS = [
    product("1", "Papel higiénico doble rollo Bosque Verde"),
    product("2", "Papel de cocina Bosque Verde"),
    product("3", "Leche entera Hacendado"),
    product("4", "Leche semidesnatada Hacendado"),
    product("5", "Aceite de oliva virgen extra Hacendado"),
    product("6", "Yogur natural Hacendado"),
    product("7", "Papel higiénico húmedo Deliplus"),
]

REGULARS = [
    product("4", "Leche semidesnatada Hacendado"),
    product("10", "Papel higiénico 4 capas Bosque Verde"),
]

HISTORY = [product("5", "Aceite de oliva virgen extra Hacendado")]


class FakeCatalog:
    products = {p["id"]: p for p in CATALOG_PRODUCTS}


@pytest.fixture
def matcher():
    aliases: dict[str, str] = {}
    m = Matcher(FakeCatalog(), lambda: REGULARS, lambda: HISTORY, aliases.get)
    m._alias_store = aliases  # para las pruebas que necesiten sembrar un alias
    return m


# ------------------------------------------------------------ cantidades

@pytest.mark.parametrize("text,expected_query,expected_qty", [
    ("papel higienico", "papel higienico", 1),
    ("dos leches", "leches", 2),
    ("3 yogures", "yogures", 3),
    ("dos paquetes de arroz", "arroz", 2),
    ("una botella de aceite", "aceite", 1),
    ("añade a la lista de la compra papel higienico", "papel higienico", 1),
])
def test_parse_request(text, expected_query, expected_qty):
    query, qty = parse_request(text)
    assert query == expected_query
    assert qty == expected_qty


def test_tokens_quita_muletillas_y_tildes():
    assert tokens("Añade el papel higiénico") == ["papel", "higienico"]


# ----------------------------------------------------------- prioridades

def test_prefiere_habitual_sobre_catalogo(matcher):
    match, _, _ = matcher.resolve("papel higienico")
    assert match is not None
    # El habitual gana aunque el catálogo tenga un nombre más corto y parecido.
    assert match.product_id == "10"
    assert match.source == "regular"


def test_usa_historial_cuando_no_es_habitual(matcher):
    match, _, _ = matcher.resolve("aceite de oliva")
    assert match is not None
    assert match.product_id == "5"
    assert match.source == "history"


def test_cae_al_catalogo_para_algo_nuevo(matcher):
    match, _, _ = matcher.resolve("papel de cocina")
    assert match is not None
    assert match.product_id == "2"
    assert match.source == "catalog"


def test_alias_manda_sobre_todo_lo_demas():
    aliases = {"papel higienico": "7"}
    m = Matcher(FakeCatalog(), lambda: REGULARS, lambda: HISTORY, aliases.get)
    match, _, _ = m.resolve("papel higienico")
    assert match is not None
    assert match.product_id == "7"
    assert match.source == "alias"


def test_arrastra_la_cantidad_pedida(matcher):
    match, _, qty = matcher.resolve("dos leches semidesnatadas")
    assert qty == 2
    assert match is not None
    assert match.quantity == 2


# --------------------------------------------------------- casos límite

def test_sin_coincidencia_no_inventa(matcher):
    match, alternatives, _ = matcher.resolve("bujías para el coche")
    assert match is None       # mejor pendiente en el panel que meter cualquier cosa


def test_frase_vacia_no_rompe(matcher):
    match, alternatives, qty = matcher.resolve("añade a la lista")
    assert match is None
    assert alternatives == []


def test_ignora_productos_no_disponibles():
    catalog = type("C", (), {"products": {
        "1": product("1", "Papel higiénico doble rollo", status="unavailable"),
        "2": product("2", "Papel higiénico triple capa"),
    }})()
    m = Matcher(catalog, lambda: [], lambda: [], lambda _p: None)
    match, _, _ = m.resolve("papel higienico")
    assert match is not None
    assert match.product_id == "2"
