"""Test de integración: config flow + sensores, con datos sintéticos."""

from __future__ import annotations

import time

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bilbao_transit.const import DOMAIN
from custom_components.bilbao_transit.gtfs import StaticFeed, Stop, TripMeta

STOP = Stop(
    stop_id="3",
    name="Bolueta",
    lat=43.247,
    lon=-2.90573,
    stop_ids=frozenset({"3.0"}),
)

LABELS = {"0": "Bilbao (norte)", "1": "Basauri/Etxarri (sur)"}


def _static() -> StaticFeed:
    return StaticFeed(
        network="metro",
        stops={"3": STOP},
        trip_meta={
            "north": TripMeta(
                direction="0", headsign="Kabiezes", line="L2", origin="Basauri"
            ),
            "north2": TripMeta(
                direction="0", headsign="Plentzia", line="L1", origin="Etxebarri"
            ),
            "south": TripMeta(
                direction="1", headsign="Basauri", line="L2", origin="Kabiezes"
            ),
        },
        stop_trips={"3.0": {"north", "north2", "south"}},
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
                "trip_id": "north2",
                "stop_time_updates": [
                    {"stop_id": "3.0", "departure": {"time": now + 420}}
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
    # el sentido se etiqueta por su significado, no por el destino dominante
    assert result["data"]["direction_labels"] == LABELS


async def test_sensores_dan_minutos_destino_y_linea(
    hass: HomeAssistant, patch_network
) -> None:
    """Cada sentido da los minutos y las salidas con destino final y línea."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Bolueta (Metro Bilbao)",
        data={
            "network": "metro",
            "stop_id": "3",
            "stop_name": "Bolueta",
            "directions": ["0", "1"],
            "direction_labels": LABELS,
        },
        options={},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    sensors = list(hass.states.async_all("sensor"))
    assert len(sensors) == 2, [s.entity_id for s in sensors]

    north = next(s for s in sensors if s.attributes.get("direction") == "0")
    south = next(s for s in sensors if s.attributes.get("direction") == "1")

    # estado = minutos al próximo
    assert int(north.state) == 3
    assert int(south.state) == 10

    # las dos salidas del norte, con destino final y línea distintos
    departures = north.attributes["next_departures"]
    assert [d["destination"] for d in departures] == ["Kabiezes", "Plentzia"]
    assert [d["line"] for d in departures] == ["L2", "L1"]
    assert [d["minutes"] for d in departures] == [3, 7]

    assert north.attributes["destination"] == "Kabiezes"
    assert north.attributes["service_status"] == "ok"
    assert north.attributes["unit_of_measurement"] == "min"
    assert south.attributes["destination"] == "Basauri"


async def test_sin_servicio_deja_sensor_unknown(hass: HomeAssistant, patch_network) -> None:
    """Si el feed no trae trenes, el estado queda vacío pero el atributo lo explica."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Bolueta (Metro Bilbao)",
        data={
            "network": "metro",
            "stop_id": "3",
            "stop_name": "Bolueta",
            "directions": ["0"],
            "direction_labels": {"0": LABELS["0"]},
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

    sensor = next(
        s for s in hass.states.async_all("sensor") if s.attributes.get("direction") == "0"
    )
    assert sensor.state == "unknown"
    assert sensor.attributes["service_status"] == "sin servicio"
    assert sensor.attributes["next_departures"] == []


async def test_migracion_v1_a_v2_renombra_sentidos(
    hass: HomeAssistant, patch_network
) -> None:
    """Una entrada antigua con "Kabiezes"/"Basauri" pasa a las etiquetas nuevas."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
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

    assert entry.version == 2
    assert entry.data["direction_labels"] == LABELS

    names = {s.attributes.get("friendly_name", "") for s in hass.states.async_all("sensor")}
    assert any("Bilbao (norte)" in name for name in names), names
