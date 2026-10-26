"""Decodificador GTFS-Realtime mínimo (protobuf wire format) sin dependencias.

Home Assistant no trae soporte nativo de GTFS-RT y añadir `gtfs-realtime-bindings`
ha demostrado ser frágil entre versiones de protobuf, así que aquí se decodifica
solo lo que necesitamos: FeedMessage -> FeedEntity -> TripUpdate -> StopTimeUpdate.

Referencia: https://gtfs.org/documentation/realtime/proto/
"""

from __future__ import annotations

import struct
from typing import Any

# --- wire format -------------------------------------------------------------


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    """Lee un varint y devuelve (valor, nueva_posicion)."""
    result = 0
    shift = 0
    while True:
        byte = buf[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes) -> list[tuple[int, int, Any]]:
    """Devuelve [(numero_campo, wire_type, valor)] de un mensaje protobuf."""
    out: list[tuple[int, int, Any]] = []
    i = 0
    end = len(buf)
    while i < end:
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 0x7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 2:
            length, i = _varint(buf, i)
            value = buf[i : i + length]
            i += length
        elif wire == 5:
            value = struct.unpack("<I", buf[i : i + 4])[0]
            i += 4
        elif wire == 1:
            value = struct.unpack("<Q", buf[i : i + 8])[0]
            i += 8
        else:  # pragma: no cover - feeds no usan groups
            raise ValueError(f"wire type no soportado: {wire}")
        out.append((field, wire, value))
    return out


def _sub(buf: bytes, num: int) -> list[bytes]:
    return [v for f, w, v in _fields(buf) if f == num and w == 2]


def _string(buf: bytes, num: int) -> str | None:
    values = _sub(buf, num)
    return values[0].decode("utf-8", "replace") if values else None


def _int(buf: bytes, num: int) -> int | None:
    values = [v for f, w, v in _fields(buf) if f == num and w == 0]
    return values[0] if values else None


# --- GTFS-Realtime -----------------------------------------------------------


def _stop_time_event(buf: bytes | None) -> dict[str, int]:
    if not buf:
        return {}
    event: dict[str, int] = {}
    time_value = _int(buf, 2)
    if time_value is not None:
        event["time"] = time_value
    delay = _int(buf, 1)
    if delay is not None:
        event["delay"] = delay
    return event


def _stop_time_update(buf: bytes) -> dict[str, Any]:
    arrival = _sub(buf, 2)
    departure = _sub(buf, 3)
    return {
        "stop_sequence": _int(buf, 1),
        "stop_id": _string(buf, 4),
        "arrival": _stop_time_event(arrival[0] if arrival else None),
        "departure": _stop_time_event(departure[0] if departure else None),
    }


def _trip_update(entity: bytes) -> dict[str, Any] | None:
    trip_update = _sub(entity, 3)
    if not trip_update:
        return None
    body = trip_update[0]
    trip = _sub(body, 1)
    trip_id = route_id = None
    direction_id = None
    if trip:
        trip_id = _string(trip[0], 1)
        route_id = _string(trip[0], 2)
        direction_id = _int(trip[0], 3)
    stop_time_updates = [
        _stop_time_update(value)
        for field, wire, value in _fields(body)
        if field == 2 and wire == 2
    ]
    return {
        "trip_id": trip_id,
        "route_id": route_id,
        "direction_id": direction_id,
        "timestamp": _int(body, 4),
        "stop_time_updates": stop_time_updates,
    }


def parse_feed(raw: bytes) -> tuple[int | None, list[dict[str, Any]]]:
    """Devuelve (feed_timestamp, [trip_updates])."""
    root = _fields(raw)
    header = [v for f, w, v in root if f == 1 and w == 2]
    feed_timestamp = _int(header[0], 3) if header else None
    updates = []
    for field, wire, value in root:
        if field == 2 and wire == 2:
            update = _trip_update(value)
            if update is not None:
                updates.append(update)
    return feed_timestamp, updates


def departure_time(stop_time_update: dict[str, Any]) -> int | None:
    """Hora de paso por la parada: salida si existe, si no llegada."""
    departure = stop_time_update.get("departure") or {}
    arrival = stop_time_update.get("arrival") or {}
    return departure.get("time") or arrival.get("time")
