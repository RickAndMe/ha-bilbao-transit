"""Test de integración: config flow + sensores, con datos sintéticos."""

from __future__ import annotations

import time

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bilbao_transit.const import DOMAIN
from custom_components.bilbao_transit.gtfs import StaticFeed, Stop

STOP = Stop(
    stop_id="3",
    name="Bolueta",
    lat=43.247,
    lon=-2.90573,
    stop_ids=frozenset({"3.0"}),
)


def _static() -> StaticFeed:
    return StaticFeed(
        network="metro",
        stops={"3": STOP},
        trip_meta={"north": ("0", "Kabiezes"), "south": ("1", "Basauri")},
        stop_trips={"3.0": {"north", "south"}},
        fetched_at=time.time(),
    )


def _realtime():
    now = int(time.time())
    return (
        now,
        [
            {
                "trip_id": "north",
                "stop_time_updates": [
                    {"stop_id": "3.0", "departure": {"time": now + 180}}
                ],
            },
            {
                "trip_id": "south",
                "stop_time_updates": [
                    {"stop_id": "3.0", "departure": {"time": now + 600}}
                ],
            },
        ],
    )


@pytest.fixture
def patch_network(monkeypatch):
    """Evita la red: estático y tiempo real sintéticos."""
    monkeypatch.setattr(
        "custom_components.bilbao_transit.config_flow.load_static",
        lambda network: _static(),
    )
    monkeypatch.setattr(
        "custom_components.bilbao_transit.coordinator.load_static",
        lambda network: _static(),
    )
    monkeypatch.setattr(
        "custom_components.bilbao_transit.coordinator.fetch_realtime",
        lambda network: _realtime(),
    )


async def test_config_flow_completo(hass: HomeAssistant, patch_network) -> None:
    """El flujo de alta crea la entrada con parada y sentidos."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"network": "metro"}
    )
    assert result["step_id"] == "stop"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"stop_id": "3"}
    )
    assert result["step_id"] == "directions"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"directions": ["0", "1"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["stop_id"] == "3"
    assert result["data"]["directions"] == ["0", "1"]
    assert result["data"]["direction_labels"] == {"0": "Kabiezes", "1": "Basauri"}


async def test_sensores_dan_minutos_y_atributos(
    hass: HomeAssistant, patch_network
) -> None:
    """Cada sentido genera un sensor con los minutos y las siguientes salidas."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bolueta (Metro Bilbao)",
        data={
            "network": "metro",
            "stop_id": "3",
            "stop_name": "Bolueta",
            "directions": ["0", "1"],
            "direction_labels": {"0": "Kabiezes", "1": "Basauri"},
        },
        options={},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    sensors = [state for state in hass.states.async_all("sensor")]
    values = {state.entity_id: state for state in sensors}
    assert len(values) == 2, [s.entity_id for s in sensors]

    north = next(
        state for state in values.values() if state.attributes.get("direction") == "0"
    )
    south = next(
        state for state in values.values() if state.attributes.get("direction") == "1"
    )

    assert int(north.state) == 3
    assert north.attributes["destination"] == "Kabiezes"
    assert north.attributes["service_status"] == "ok"
    assert north.attributes["next_departures"][0]["headsign"] == "Kabiezes"

    assert int(south.state) == 10
    assert south.attributes["destination"] == "Basauri"

    device = north.attributes["device_class"] if "device_class" in north.attributes else None
    assert device is None  # es un sensor de medida, no de clase device
    assert north.attributes["unit_of_measurement"] == "min"


async def test_sin_servicio_deja_sensor_unknown(hass: HomeAssistant, patch_network) -> None:
    """Si el feed no trae trenes, el estado queda vacío pero el atributo lo explica."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bolueta (Metro Bilbao)",
        data={
            "network": "metro",
            "stop_id": "3",
            "stop_name": "Bolueta",
            "directions": ["0"],
            "direction_labels": {"0": "Kabiezes"},
        },
        options={},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_set_updated_data(
        {
            "static": _static(),
            "feed_timestamp": None,
            "updates": [],
            "fetched_at": time.time(),
        }
    )
    await hass.async_block_till_done()

    sensor = hass.states.get("sensor.bolueta_metro_bilbao_a_kabiezes")
    assert sensor is not None
    assert sensor.state == "unknown"
    assert sensor.attributes["service_status"] == "sin servicio"
    assert sensor.attributes["next_departures"] == []
