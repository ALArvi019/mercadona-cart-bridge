"""Interpretación de la frase dictada: cantidad e intención de quitar."""
from __future__ import annotations

import pytest

from app.core.matching import Matcher, parse_intent


def product(pid: str, name: str, **extra):
    return {"id": pid, "display_name": name, "published": True, "thumbnail": "", **extra}


# ------------------------------------------------------------- cantidades

@pytest.mark.parametrize("text,query,qty,explicit", [
    # El caso que falló en casa: el número va detrás de la muletilla.
    ("añade 2 mantequillas", "mantequillas", 2, True),
    ("añade dos mantequillas", "mantequillas", 2, True),
    ("apunta 3 yogures", "yogures", 3, True),
    ("añade a la lista de la compra 4 leches", "leches", 4, True),
    ("2 mantequillas", "mantequillas", 2, True),
    ("añade dos paquetes de arroz", "arroz", 2, True),
    # Sin número: una unidad, pero no es una cantidad dicha por nadie.
    ("añade mantequilla", "mantequilla", 1, False),
    ("papel higienico", "papel higienico", 1, False),
])
def test_cantidades(text, query, qty, explicit):
    r = parse_intent(text)
    assert r.intent == "add"
    assert r.query == query
    assert r.quantity == qty
    assert r.explicit_quantity is explicit


# -------------------------------------------------------------- intención

@pytest.mark.parametrize("text,query,qty", [
    ("quita la mantequilla", "mantequilla", 1),
    ("quita 2 mantequillas", "mantequillas", 2),
    ("elimina el papel higienico de la lista", "papel higienico", 1),
    ("borra los yogures", "yogures", 1),
    ("saca la leche del carrito", "leche", 1),
    ("retira una barra de pan", "pan", 1),
])
def test_detecta_que_hay_que_quitar(text, query, qty):
    r = parse_intent(text)
    assert r.intent == "remove"
    assert r.query == query
    assert r.quantity == qty


def test_no_confunde_anadir_con_quitar():
    assert parse_intent("añade quitanieves").intent == "add"
    assert parse_intent("mantequilla").intent == "add"


# -------------------------------------------------- emparejar en el carrito

CART = [
    product("1", "Mantequilla con sal Hacendado"),
    product("2", "Leche semidesnatada Hacendado"),
    product("3", "Papel higiénico Suave Bosque Verde", status="unavailable"),
]


@pytest.fixture
def matcher():
    catalog = type("C", (), {"products": {}})()
    return Matcher(catalog, lambda: [], lambda: [], lambda _p: None)


def test_encuentra_lo_que_hay_en_el_carrito(matcher):
    match, _ = matcher.resolve_in_cart(CART, "quita la mantequilla")
    assert match is not None
    assert match.product_id == "1"


def test_permite_quitar_algo_agotado(matcher):
    # Un producto sin stock sigue en el carrito y hay que poder sacarlo.
    match, _ = matcher.resolve_in_cart(CART, "quita el papel higienico")
    assert match is not None
    assert match.product_id == "3"


def test_no_inventa_si_no_esta_en_el_carrito(matcher):
    match, _ = matcher.resolve_in_cart(CART, "quita el chorizo")
    assert match is None


def test_carrito_vacio(matcher):
    match, alternatives = matcher.resolve_in_cart([], "quita la mantequilla")
    assert match is None and alternatives == []
