"""Acceso a los datos GTFS de Metro Bilbao y del tranvía de Euskotren.

Todo es stdlib: las descargas son bloqueantes y se ejecutan siempre en el
executor de Home Assistant.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Any

from .const import DEPARTURE_GRACE, NETWORKS
from .pb import departure_time, parse_feed

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "HomeAssistant-BilbaoTransit/1.0 (+https://github.com/RickAndMe/ha-bilbao-transit)"


# --- estructuras -------------------------------------------------------------


@dataclass(slots=True)
class Stop:
    """Parada lógica (agrupa andenes/plataformas de una misma estación)."""

    stop_id: str
    name: str
    lat: float
    lon: float
    stop_ids: frozenset[str]


@dataclass(slots=True)
class StaticFeed:
    """Horario estático ya reducido a lo que usa la integración."""

    network: str
    stops: dict[str, Stop] = field(default_factory=dict)
    trip_meta: dict[str, tuple[str, str]] = field(default_factory=dict)
    stop_trips: dict[str, set[str]] = field(default_factory=dict)
    fetched_at: float = 0.0

    def directions(self, stop: Stop) -> dict[str, str]:
        """Devuelve {direction_id: etiqueta} de una parada, por destino dominante."""
        counts: dict[str, dict[str, int]] = {}
        for stop_id in stop.stop_ids:
            for trip_id in self.stop_trips.get(stop_id, ()):  # noqa: B007
                meta = self.trip_meta.get(trip_id)
                if not meta:
                    continue
                direction, headsign = meta
                counts.setdefault(direction, {})
                counts[direction][headsign] = counts[direction].get(headsign, 0) + 1
        labels: dict[str, str] = {}
        for direction, headsigns in counts.items():
            top = max(headsigns.items(), key=lambda item: item[1])[0]
            labels[direction] = top
        return labels


# --- utilidades --------------------------------------------------------------


def _download(url: str, timeout: int = 90) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def _float(value: str | None) -> float | None:
    try:
        return float((value or "").strip())
    except (TypeError, ValueError):
        return None


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros."""
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _rows(zf: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    if name not in zf.namelist():
        return []
    with zf.open(name) as handle:
        return list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig")))


# --- horario estático --------------------------------------------------------


def parse_static(network: str, raw: bytes) -> StaticFeed:
    """Convierte el zip GTFS de la red en un StaticFeed reducido."""
    config = NETWORKS[network]
    feed = StaticFeed(network=network, fetched_at=time.time())

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        routes = _rows(zf, "routes.txt")
        agency_filter = config.get("agency_filter")
        if agency_filter:
            route_ids = {
                row["route_id"]
                for row in routes
                if (row.get("agency_id") or "").strip() == agency_filter
            }
        else:
            route_ids = {row["route_id"] for row in routes}

        trip_meta: dict[str, tuple[str, str]] = {}
        for row in _rows(zf, "trips.txt"):
            if route_ids and (row.get("route_id") or "").strip() not in route_ids:
                continue
            trip_meta[(row.get("trip_id") or "").strip()] = (
                (row.get("direction_id") or "0").strip(),
                (row.get("trip_headsign") or "").strip(),
            )
        feed.trip_meta = trip_meta

        stop_trips: dict[str, set[str]] = {}
        for row in _rows(zf, "stop_times.txt"):
            trip_id = (row.get("trip_id") or "").strip()
            if trip_id not in trip_meta:
                continue
            stop_id = (row.get("stop_id") or "").strip()
            stop_trips.setdefault(stop_id, set()).add(trip_id)
        feed.stop_trips = stop_trips

        # Agrupa plataformas/andenes en paradas lógicas usando parent_station
        raw_stops = [
            row
            for row in _rows(zf, "stops.txt")
            if (row.get("location_type") or "0").strip() in ("", "0")
        ]
        by_id = {(row.get("stop_id") or "").strip(): row for row in raw_stops}
        groups: dict[str, list[dict[str, str]]] = {}
        for row in raw_stops:
            stop_id = (row.get("stop_id") or "").strip()
            if stop_id not in stop_trips:
                continue
            parent = (row.get("parent_station") or "").strip() or stop_id
            groups.setdefault(parent, []).append(row)

        for group_id, members in groups.items():
            lat = next((_float(m.get("stop_lat")) for m in members if _float(m.get("stop_lat"))), None)
            lon = next((_float(m.get("stop_lon")) for m in members if _float(m.get("stop_lon"))), None)
            if lat is None or lon is None:
                continue
            name = (members[0].get("stop_name") or group_id).strip()
            feed.stops[group_id] = Stop(
                stop_id=group_id,
                name=name,
                lat=lat,
                lon=lon,
                stop_ids=frozenset((m.get("stop_id") or "").strip() for m in members),
            )

    _LOGGER.debug(
        "%s: %s paradas, %s viajes, %s registros de stop_times",
        config["name"],
        len(feed.stops),
        len(feed.trip_meta),
        sum(len(v) for v in feed.stop_trips.values()),
    )
    return feed


def load_static(network: str) -> StaticFeed:
    """Descarga y parsea el GTFS estático (bloqueante)."""
    config = NETWORKS[network]
    _LOGGER.debug("Descargando GTFS estático de %s", config["name"])
    return parse_static(network, _download(config["gtfs_url"]))


def fetch_realtime(network: str) -> tuple[int | None, list[dict[str, Any]]]:
    """Descarga el feed GTFS-RT (bloqueante)."""
    config = NETWORKS[network]
    raw = _download(config["rt_url"], timeout=45)
    feed_timestamp, updates = parse_feed(raw)
    _LOGGER.debug(
        "%s: %s actualizaciones en tiempo real (feed %s)",
        config["name"],
        len(updates),
        feed_timestamp,
    )
    return feed_timestamp, updates


def upcoming_departures(
    feed: StaticFeed,
    updates: list[dict[str, Any]],
    stop: Stop,
    direction: str | None,
    now: float | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Próximas salidas reales de una parada, filtradas por sentido."""
    now = time.time() if now is None else now
    found: dict[tuple[str, int], dict[str, Any]] = {}
    for update in updates:
        meta = feed.trip_meta.get(update.get("trip_id") or "")
        if not meta:
            continue
        trip_direction, headsign = meta
        if direction is not None and trip_direction != direction:
            continue
        for stop_time in update.get("stop_time_updates") or ():
            if (stop_time.get("stop_id") or "") not in stop.stop_ids:
                continue
            when = departure_time(stop_time)
            if not when or when < now - DEPARTURE_GRACE:
                continue
            found[(update["trip_id"], when)] = {
                "trip_id": update["trip_id"],
                "timestamp": when,
                "in_seconds": int(when - now),
                "in_minutes": round((when - now) / 60),
                "headsign": headsign,
                "direction": trip_direction,
                "delay": (stop_time.get("departure") or {}).get("delay"),
            }
    departures = sorted(found.values(), key=lambda item: item["timestamp"])
    return departures[:limit]
