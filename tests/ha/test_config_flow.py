"""Pruebas del alta de la integración.

Reproducen lo que hace una persona en la interfaz: pegar el token y decidir si quiere
voz o no. El caso importante es el segundo paso vacío, que es donde falló en casa.
"""
from unittest.mock import patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.mercadona.const import (
    CONF_GKEEP_EMAIL,
    CONF_GKEEP_LIST,
    CONF_GKEEP_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

CUENTA = {
    "name": "Casa",
    "email": "alguien@example.com",
    "postal_code": "28001",
    "warehouse": "",
    "refresh_token": "token-renovado",
    "customer_id": "00000000-0000-0000-0000-000000000000",
}


@pytest.fixture
def validar_ok():
    with patch(
        "custom_components.mercadona.config_flow._validate_mercadona",
        return_value=CUENTA,
    ) as m:
        yield m


async def _empezar(hass: HomeAssistant) -> dict:
    resultado = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert resultado["type"] == data_entry_flow.FlowResultType.FORM
    assert resultado["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        resultado["flow_id"], {CONF_REFRESH_TOKEN: "un-token"}
    )


async def test_sin_voz_crea_la_entrada(hass: HomeAssistant, validar_ok) -> None:
    """Dejar Google Keep vacío debe terminar el alta, no romperla."""
    paso_keep = await _empezar(hass)
    assert paso_keep["type"] == data_entry_flow.FlowResultType.FORM
    assert paso_keep["step_id"] == "keep"

    final = await hass.config_entries.flow.async_configure(
        paso_keep["flow_id"], {CONF_GKEEP_EMAIL: "", CONF_GKEEP_TOKEN: ""}
    )

    assert final["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert final["title"] == "Mercadona (Casa)"
    assert final["data"][CONF_REFRESH_TOKEN] == "token-renovado"
    assert CONF_GKEEP_EMAIL not in final["data"]


async def test_sin_voz_enviando_el_formulario_vacio(hass: HomeAssistant, validar_ok) -> None:
    """El frontend puede no mandar las claves opcionales si nadie las toca."""
    paso_keep = await _empezar(hass)
    final = await hass.config_entries.flow.async_configure(paso_keep["flow_id"], {})
    assert final["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY


async def test_con_voz_deja_elegir_la_lista(hass: HomeAssistant, validar_ok) -> None:
    paso_keep = await _empezar(hass)
    with patch(
        "custom_components.mercadona.config_flow._list_keep_notes",
        return_value=[("Mi lista de la compra", 3), ("Recetas", 0)],
    ):
        paso_lista = await hass.config_entries.flow.async_configure(
            paso_keep["flow_id"],
            {CONF_GKEEP_EMAIL: "alguien@gmail.com", CONF_GKEEP_TOKEN: "aas_et/x"},
        )

    assert paso_lista["step_id"] == "keep_list"
    final = await hass.config_entries.flow.async_configure(
        paso_lista["flow_id"], {CONF_GKEEP_LIST: "Mi lista de la compra"}
    )
    assert final["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert final["data"][CONF_GKEEP_LIST] == "Mi lista de la compra"


async def test_token_rechazado_no_rompe_el_flujo(hass: HomeAssistant) -> None:
    from custom_components.mercadona.core.client import SessionExpired

    resultado = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.mercadona.config_flow._validate_mercadona",
        side_effect=SessionExpired("caducado"),
    ):
        con_error = await hass.config_entries.flow.async_configure(
            resultado["flow_id"], {CONF_REFRESH_TOKEN: "malo"}
        )

    # Debe volver a enseñar el formulario con el error, no abortar.
    assert con_error["type"] == data_entry_flow.FlowResultType.FORM
    assert con_error["errors"] == {"base": "token_rechazado"}


@pytest.mark.usefixtures("socket_enabled")
async def test_reconfigurar_activa_la_voz(hass) -> None:
    """Activar Google Keep después del alta, sin rehacer la integración."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_REFRESH_TOKEN: "token-guardado", "postal_code": "28001"},
        unique_id="00000000",
    )
    entry.add_to_hass(hass)

    inicio = await entry.start_reconfigure_flow(hass)
    assert inicio["step_id"] == "keep"

    with patch(
        "custom_components.mercadona.config_flow._list_keep_notes",
        return_value=[("Mi lista de la compra", 0)],
    ):
        paso_lista = await hass.config_entries.flow.async_configure(
            inicio["flow_id"],
            {CONF_GKEEP_EMAIL: "alguien@gmail.com", CONF_GKEEP_TOKEN: "aas_et/x"},
        )

    final = await hass.config_entries.flow.async_configure(
        paso_lista["flow_id"], {CONF_GKEEP_LIST: "Mi lista de la compra"}
    )

    assert final["type"] == data_entry_flow.FlowResultType.ABORT
    assert final["reason"] == "reconfigure_successful"
    # La voz queda configurada y la sesión de Mercadona intacta.
    assert entry.data[CONF_GKEEP_LIST] == "Mi lista de la compra"
    assert entry.data[CONF_REFRESH_TOKEN] == "token-guardado"
    assert entry.data["postal_code"] == "28001"
