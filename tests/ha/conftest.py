"""Configuración de los tests de la integración de Home Assistant."""
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Sin esto, Home Assistant no carga integraciones de custom_components."""
    yield
