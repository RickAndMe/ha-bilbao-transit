"""Tests de los módulos sin dependencias de Home Assistant."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.bilbao_transit import gtfs, pb  # noqa: E402


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _str_field(field: int, text: str) -> bytes:
    raw = text.encode()
    return _key(field, 2) + _varint(len(raw)) + raw


def _int_field(field: int, value: int) -> bytes:
    return _key(field, 0) + _varint(value)


def _build_feed(trip_id: str, stop_id: str, when: int, headsign_field: bool = False) -> bytes:
    stop_time = (
        _int_field(1, 7)  # stop_sequence
        + _str_field(4, stop_id)
        + _key(3, 2)
        + _varint(len(_int_field(2, when)))
        + _int_field(2, when)  # departure.time
    )
    trip = _str_field(1, trip_id)
    trip_update = (
        _key(1, 2)
        + _varint(len(trip))
        + trip
        + _key(2, 2)
        + _varint(len(stop_time))
        + stop_time
        + _int_field(4, when)
    )
    entity = _str_field(1, "entity") + _key(3, 2) + _varint(len(trip_update)) + trip_update
    header = _int_field(3, when)
    return (
        _key(1, 2)
        + _varint(len(header))
        + header
        + _key(2, 2)
        + _varint(len(entity))
        + entity
    )


def test_parse_feed_extrae_trip_updates() -> None:
    raw = _build_feed("trip-1", "3.0", 1_700_000_000)
    feed_timestamp, updates = pb.parse_feed(raw)
    assert feed_timestamp == 1_700_000_000
    assert len(updates) == 1
    assert updates[0]["trip_id"] == "trip-1"
    stop_times = updates[0]["stop_time_updates"]
    assert stop_times[0]["stop_id"] == "3.0"
    assert pb.departure_time(stop_times[0]) == 1_700_000_000


def _static() -> gtfs.StaticFeed:
    stop = gtfs.Stop(
        stop_id="3",
        name="Bolueta",
        lat=43.247,
        lon=-2.9057,
        stop_ids=frozenset({"3.0"}),
    )
    return gtfs.StaticFeed(
        network="metro",
        stops={"3": stop},
        trip_meta={
            "north": gtfs.TripMeta(
                direction="0", headsign="Kabiezes", line="L2", origin="Basauri"
            ),
            "south": gtfs.TripMeta(
                direction="1", headsign="Basauri", line="L2", origin="Kabiezes"
            ),
        },
        stop_trips={"3.0": {"north", "south"}},
        fetched_at=0.0,
    )


def test_upcoming_filtra_por_sentido() -> None:
    static = _static()
    now = 1_700_000_000
    updates = [
        {
            "trip_id": "north",
            "stop_time_updates": [{"stop_id": "3.0", "departure": {"time": now + 300}}],
        },
        {
            "trip_id": "south",
            "stop_time_updates": [{"stop_id": "3.0", "departure": {"time": now + 60}}],
        },
    ]
    north = gtfs.upcoming_departures(static, updates, static.stops["3"], "0", now=now)
    assert [dep["trip_id"] for dep in north] == ["north"]
    assert north[0]["in_minutes"] == 5
    assert north[0]["headsign"] == "Kabiezes"

    both = gtfs.upcoming_departures(static, updates, static.stops["3"], None, now=now)
    assert [dep["trip_id"] for dep in both] == ["south", "north"]


def test_upcoming_ignora_paradas_ajenas_y_trenes_pasados() -> None:
    static = _static()
    now = 1_700_000_000
    updates = [
        {
            "trip_id": "north",
            "stop_time_updates": [
                {"stop_id": "9.0", "departure": {"time": now + 60}},
                {"stop_id": "3.0", "departure": {"time": now - 600}},
            ],
        }
    ]
    assert gtfs.upcoming_departures(static, updates, static.stops["3"], None, now=now) == []


def test_haversine_metros() -> None:
    # Bolueta metro -> Bolueta tranvía, unos 130 m
    distance = gtfs.haversine(43.24700, -2.90573, 43.247252, -2.904919)
    assert 50 < distance < 200


def test_directions_usa_etiquetas_de_la_red() -> None:
    """En metro el sentido se llama por su significado, no por el destino."""
    static = _static()
    assert static.directions(static.stops["3"]) == {
        "0": "Bilbao (norte)",
        "1": "Basauri/Etxarri (sur)",
    }


def test_directions_sin_etiquetas_fijas_usa_destino_dominante() -> None:
    """En el tranvía la etiqueta sale del destino más frecuente."""
    static = _static()
    static.network = "tram"
    static.trip_meta["north2"] = gtfs.TripMeta(direction="0", headsign="Kabiezes")
    static.stop_trips["3.0"].add("north2")
    assert static.directions(static.stops["3"]) == {"0": "Kabiezes", "1": "Basauri"}


def test_linea_se_deriva_del_origen_y_del_destino() -> None:
    """La L1 sale de Etxebarri y la L2 de Basauri; el destino es el respaldo."""
    terminals = {
        "L1": {"Etxebarri", "Plentzia", "Bidezabal"},
        "L2": {"Basauri", "Kabiezes"},
    }
    assert gtfs._derive_line(terminals, "Basauri", "Kabiezes") == "L2"
    assert gtfs._derive_line(terminals, "Etxebarri", "Plentzia") == "L1"
    # un servicio L1 que acaba en Kabiezes sigue siendo L1: manda el origen
    assert gtfs._derive_line(terminals, "Etxebarri", "Kabiezes") == "L1"
    # origen intermedio (San Mamés): se resuelve por el destino
    assert gtfs._derive_line(terminals, "San Mamés", "Basauri") == "L2"
    assert gtfs._derive_line(terminals, "San Mamés", "Bidezabal") == "L1"
    assert gtfs._derive_line(terminals, "San Mamés", "Rara") is None


def test_upcoming_incluye_destino_y_linea() -> None:
    static = _static()
    now = 1_700_000_000
    updates = [
        {
            "trip_id": "north",
            "stop_time_updates": [{"stop_id": "3.0", "departure": {"time": now + 120}}],
        }
    ]
    departure = gtfs.upcoming_departures(
        static, updates, static.stops["3"], "0", now=now
    )[0]
    assert departure["destination"] == "Kabiezes"
    assert departure["line"] == "L2"
    assert departure["origin"] == "Basauri"
