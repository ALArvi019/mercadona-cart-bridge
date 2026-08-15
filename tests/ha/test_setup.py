"""Montaje completo de la integración.

Existe porque dos entidades se quedaron por el camino en la instalación real sin que
nada fallara a ojos del usuario: el config flow terminaba bien, la integración decía
estar cargada, y solo el log contaba que faltaba una entidad. Este test comprueba que
salen todas.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mercadona.const import CONF_REFRESH_TOKEN, DOMAIN

PERFIL = {"name": "Casa", "current_postal_code": "28001", "email": "x@y.z"}

CARRITO = {
    "id": "cart-1",
    "version": 3,
    "products_count": 2,
    "summary": {"total": 12.34},
    "lines": [
        {
            "quantity": 2.0,
            "sources": ["+CT"],
            "product": {
                "id": "20727",
                "display_name": "Mantequilla con sal Hacendado",
                "packaging": "Tarrina",
                "thumbnail": "https://example.invalid/m.jpg",
                "published": True,
                "status": None,
                "price_instructions": {"unit_price": 2.15},
            },
        },
        {
            "quantity": 1.0,
            "sources": ["+CT"],
            "product": {
                "id": "12912",
                "display_name": "Papel higiénico Suave Bosque Verde",
                "packaging": "Paquete",
                "thumbnail": "https://example.invalid/p.jpg",
                "published": True,
                "status": None,
                "price_instructions": {"unit_price": 3.70},
            },
        },
    ],
}

HABITUALES = [
    {
        "id": "10381",
        "display_name": "Leche semidesnatada Hacendado",
        "packaging": "Brick",
        "thumbnail": "",
        "published": True,
        "status": None,
        "price_instructions": {"unit_price": 0.85},
    }
]


@pytest.fixture
def panel_falso():
    """El panel levanta el servidor HTTP, que en los tests está capado.

    Aquí solo interesa comprobar que se registra; lo que sirve se prueba aparte.
    """
    with patch("custom_components.mercadona.async_register_panel") as panel, \
         patch("custom_components.mercadona.async_register_views") as views:
        yield panel, views


@pytest.fixture
def cliente_falso():
    """Un MercadonaClient que no toca la red.

    Sin autospec: `session` se crea en el __init__ real, así que autospec no la conoce.
    """
    with patch("custom_components.mercadona.MercadonaClient") as cls:
        client = cls.return_value
        client.ensure_token = AsyncMock()
        client.profile = AsyncMock(return_value=PERFIL)
        client.get_cart = AsyncMock(return_value=CARRITO)
        client.my_regulars = AsyncMock(return_value=HABITUALES)
        client.orders = AsyncMock(return_value=[])
        client.categories = AsyncMock(return_value=[])
        client.close = AsyncMock()
        client.session = SimpleNamespace(
            warehouse="", postal_code="28001", customer_id="00000000",
            access_token="a", refresh_token="r",
        )
        yield client


async def _montar(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Mercadona (Casa)",
        data={CONF_REFRESH_TOKEN: "un-token"},
        unique_id="00000000",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.usefixtures("socket_enabled")
async def test_crea_todas_las_entidades(hass: HomeAssistant, cliente_falso, panel_falso) -> None:
    """Ninguna entidad debe quedarse por el camino.

    Se mira el registro por su clave, no el entity_id: los nombres dependen del idioma
    de quien lo instale.
    """
    entry = await _montar(hass)
    registro = er.async_get(hass)
    claves = {
        e.unique_id.removeprefix(f"{entry.entry_id}_")
        for e in er.async_entries_for_config_entry(registro, entry.entry_id)
    }
    assert claves == {"cart", "cart_total", "cart_items", "session"}, f"registradas: {claves}"


def _buscar(hass: HomeAssistant, entry, clave: str) -> str:
    """entity_id de una entidad a partir de su clave, sea cual sea el idioma."""
    registro = er.async_get(hass)
    for e in er.async_entries_for_config_entry(registro, entry.entry_id):
        if e.unique_id.endswith(f"_{clave}"):
            return e.entity_id
    raise AssertionError(f"no está registrada la entidad {clave}")


@pytest.mark.usefixtures("socket_enabled")
async def test_el_carrito_sale_en_la_lista(hass: HomeAssistant, cliente_falso, panel_falso) -> None:
    await _montar(hass)

    entry = hass.config_entries.async_entries(DOMAIN)[0]

    estado = hass.states.get(_buscar(hass, entry, "cart"))
    assert estado is not None
    assert estado.state == "2"          # dos líneas pendientes

    total = hass.states.get(_buscar(hass, entry, "cart_total"))
    assert total.state == "12.34"


@pytest.mark.usefixtures("socket_enabled")
async def test_la_sesion_se_reporta_sana(hass: HomeAssistant, cliente_falso, panel_falso) -> None:
    entry = await _montar(hass)
    problema = hass.states.get(_buscar(hass, entry, "session"))
    assert problema is not None
    assert problema.state == "off"      # off = sin problema


@pytest.mark.usefixtures("socket_enabled")
async def test_descargar_al_quitar_la_integracion(hass: HomeAssistant, cliente_falso, panel_falso) -> None:
    entry = await _montar(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    cliente_falso.close.assert_awaited()


@pytest.mark.usefixtures("socket_enabled")
async def test_registra_el_panel_y_su_api(hass: HomeAssistant, cliente_falso, panel_falso) -> None:
    """El panel de la cocina y sus rutas tienen que quedar dados de alta."""
    panel, views = panel_falso
    await _montar(hass)
    panel.assert_awaited_once()
    views.assert_called_once()
