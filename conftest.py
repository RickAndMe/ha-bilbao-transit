"""Configuración de pytest para probar el custom component."""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Necesario para que HA cargue custom_components/ durante los tests."""
    yield
