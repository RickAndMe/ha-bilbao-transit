"""Acceso a los datos GTFS de las redes de Bizkaia.

Redes soportadas: Metro Bilbao, tranvía de Euskotren, Bizkaibus y Bilbobus.

Todo es stdlib: las descargas son bloqueantes y se ejecutan siempre en el
executor de Home Assistant.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import math
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Any

from .const import DEPARTURE_GRACE, NETWORKS, STATIC_TTL
from .pb import departure_time, parse_feed

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "HomeAssistant-BilbaoTransit/1.2 (+https://github.com/RickAndMe/ha-bilbao-transit)"

# Caché de horarios estáticos por (red, paradas). Vive a nivel de módulo porque
# los datos son inmutables y los comparten todas las entradas de la red.
_CACHE: dict[tuple[str, tuple[str, ...] | None], "StaticFeed"] = {}

# Los zip pesados (Bizkaibus son ~35 MB de stop_times) se cachean un rato para
# no descargarlos dos veces entre el índice de paradas y el horario filtrado.
_RAW_CACHE: dict[str, tuple[float, bytes]] = {}
_RAW_TTL = 30 * 60
_RAW_MAX_BYTES = 40 * 1024 * 1024


def clean_headsign(value: str | None) -> str:
    """Limpia destinos compuestos.

    Bilbobus publica cabeceras del estilo "PT-Semana / (LA PEÑA)": se queda con
    lo que hay detrás de la barra y quita los paréntesis.
    """
    text = (value or "").strip()
    if " / " in text:
        text = text.split(" / ")[-1].strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text


# --- estructuras -------------------------------------------------------------


@dataclass(slots=True)
class Stop:
    """Parada lógica (agrupa andenes/plataformas de una misma parada)."""

    stop_id: str
    name: str
    lat: float
    lon: float
    stop_ids: frozenset[str]


@dataclass(slots=True)
class TripMeta:
    """Datos de un viaje que no vienen en el feed en tiempo real."""

    direction: str
    headsign: str
    route_id: str = ""
    line: str | None = None
    service_id: str = ""
    origin: str | None = None
    terminus: str | None = None


@dataclass(slots=True)
class Line:
    """Línea de una red."""

    route_id: str
    short: str
    long: str = ""


@dataclass(slots=True)
class Service:
    """Vigencia de un service_id del GTFS."""

    days: frozenset[int]
    start: dt.date
    end: dt.date


@dataclass(slots=True)
class StaticFeed:
    """Horario estático ya reducido a lo que usa la integración."""

    network: str
    stops: dict[str, Stop] = field(default_factory=dict)
    trip_meta: dict[str, TripMeta] = field(default_factory=dict)
    stop_trips: dict[str, set[str]] = field(default_factory=dict)
    stop_departures: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    lines: dict[str, Line] = field(default_factory=dict)
    services: dict[str, Service] = field(default_factory=dict)
    exceptions: dict[tuple[str, dt.date], int] = field(default_factory=dict)
    fetched_at: float = 0.0

    # -- consultas ---------------------------------------------------------

    def service_ids(self, now: dt.datetime) -> set[str]:
        """Service ids activos en la fecha indicada."""
        today = now.date()
        weekday = today.weekday()
        active = {
            service_id
            for service_id, service in self.services.items()
            if weekday in service.days and service.start <= today <= service.end
        }
        for (service_id, day), exception in self.exceptions.items():
            if day != today:
                continue
            if exception == 1:
                active.add(service_id)
            elif exception == 2:
                active.discard(service_id)
        return active

    def options(self, stop: Stop) -> dict[str, str]:
        """Opciones seleccionables de una parada: {clave: etiqueta}.

        En metro y tranvía la clave es el sentido ("0"/"1") y la etiqueta sale
        de las etiquetas fijas de la red o del destino más frecuente. En los
        buses hay varias líneas por parada, así que la clave es
        "route_id|direction_id" y la etiqueta incluye la línea.
        """
        config = NETWORKS[self.network]
        fixed = config.get("direction_labels") or {}
        multi_line = bool(config.get("multi_line"))

        counts: dict[str, dict[str, int]] = {}
        for stop_id in stop.stop_ids:
            for trip_id in self.stop_trips.get(stop_id, ()):  # noqa: B007
                meta = self.trip_meta.get(trip_id)
                if not meta:
                    continue
                key = f"{meta.route_id}|{meta.direction}" if multi_line else meta.direction
                counts.setdefault(key, {})
                counts[key][meta.headsign] = counts[key].get(meta.headsign, 0) + 1

        labels: dict[str, str] = {}
        for key, headsigns in counts.items():
            top = max(headsigns.items(), key=lambda item: item[1])[0]
            if multi_line:
                route_id, _ = split_key(key)
                line = self.lines.get(route_id)
                short = line.short if line else route_id
                labels[key] = f"{short} · {top}"
            elif key in fixed:
                labels[key] = fixed[key]
            else:
                labels[key] = top
        return labels

    def lines_at(self, stop: Stop) -> dict[str, Line]:
        """Líneas que pasan por la parada, ordenadas por número de viajes."""
        counts: dict[str, int] = {}
        for stop_id in stop.stop_ids:
            for trip_id in self.stop_trips.get(stop_id, ()):
                meta = self.trip_meta.get(trip_id)
                if meta and meta.route_id:
                    counts[meta.route_id] = counts.get(meta.route_id, 0) + 1
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        result: dict[str, Line] = {}
        for route_id, _ in ordered:
            line = self.lines.get(route_id)
            if line is None:
                line = Line(route_id=route_id, short=route_id)
            result[route_id] = line
        return result


def split_key(key: str) -> tuple[str, str]:
    """Separa "route_id|direction" en sus dos partes ("" si no hay línea)."""
    if "|" in key:
        route_id, _, direction = key.partition("|")
        return route_id, direction
    return "", key


# --- utilidades --------------------------------------------------------------


def _download(url: str, timeout: int = 120, cache: bool = False) -> bytes:
    if cache:
        cached = _RAW_CACHE.get(url)
        if cached is not None and time.time() - cached[0] < _RAW_TTL:
            return cached[1]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        raw = response.read()
    if cache and len(raw) <= _RAW_MAX_BYTES:
        _RAW_CACHE[url] = (time.time(), raw)
    return raw


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


def _seconds(value: str | None) -> int | None:
    """Convierte "HH:MM:SS" (puede pasar de 24h) a segundos desde medianoche."""
    parts = (value or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _date(value: str | None) -> dt.date | None:
    try:
        return dt.datetime.strptime((value or "").strip(), "%Y%m%d").date()
    except ValueError:
        return None


# --- horario estático --------------------------------------------------------


def _derive_line(
    terminals: dict[str, set[str]], origin: str | None, terminus: str | None
) -> str | None:
    """Deduce la línea por los extremos del viaje.

    Manda el origen: la L1 sale de Etxebarri y la L2 de Basauri, aunque los
    destinos se crucen en servicios puntuales.
    """
    for line, names in terminals.items():
        if origin in names:
            return line
    for line, names in terminals.items():
        if terminus in names:
            return line
    return None


def parse_static(
    network: str, raw: bytes, stop_ids: list[str] | tuple[str, ...] | None = None
) -> StaticFeed:
    """Convierte el zip GTFS de la red en un StaticFeed reducido.

    Si se pasan `stop_ids`, solo se guardan los stop_times de esas paradas: el
    GTFS de Bizkaibus tiene 34 MB de stop_times y no cabe entero en memoria de
    un HA modesto.
    """
    config = NETWORKS[network]
    feed = StaticFeed(network=network, fetched_at=time.time())
    wanted = set(stop_ids) if stop_ids else None

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        all_stops = _rows(zf, "stops.txt")
        name_by_id = {
            (row.get("stop_id") or "").strip(): (row.get("stop_name") or "").strip()
            for row in all_stops
        }

        for row in _rows(zf, "routes.txt"):
            route_id = (row.get("route_id") or "").strip()
            feed.lines[route_id] = Line(
                route_id=route_id,
                short=(row.get("route_short_name") or route_id).strip(),
                long=(row.get("route_long_name") or "").strip(),
            )

        agency_filter = config.get("agency_filter")
        if agency_filter:
            agency_routes = {
                (row.get("route_id") or "").strip()
                for row in _rows(zf, "routes.txt")
                if (row.get("agency_id") or "").strip() == agency_filter
            }
        else:
            agency_routes = set(feed.lines)

        trip_meta: dict[str, TripMeta] = {}
        for row in _rows(zf, "trips.txt"):
            route_id = (row.get("route_id") or "").strip()
            if agency_routes and route_id not in agency_routes:
                continue
            line = feed.lines.get(route_id)
            trip_meta[(row.get("trip_id") or "").strip()] = TripMeta(
                direction=(row.get("direction_id") or "0").strip(),
                headsign=clean_headsign(row.get("trip_headsign")),
                route_id=route_id,
                line=line.short if line else None,
                service_id=(row.get("service_id") or "").strip(),
            )

        stop_trips: dict[str, set[str]] = {}
        stop_departures: dict[str, list[tuple[str, int]]] = {}
        first_stop: dict[str, tuple[int, str]] = {}
        last_stop: dict[str, tuple[int, str]] = {}

        if "stop_times.txt" in zf.namelist():
            with zf.open("stop_times.txt") as handle:
                reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8-sig"))
                header = next(reader, None) or []
                index = {name: position for position, name in enumerate(header)}
                i_trip = index.get("trip_id")
                i_stop = index.get("stop_id")
                i_dep = index.get("departure_time")
                i_seq = index.get("stop_sequence")
                if None not in (i_trip, i_stop, i_dep, i_seq):
                    for row in reader:
                        if len(row) <= max(i_trip, i_stop, i_dep, i_seq):
                            continue
                        trip_id = row[i_trip].strip()
                        if trip_id not in trip_meta:
                            continue
                        stop_id = row[i_stop].strip()
                        if wanted is not None and stop_id not in wanted:
                            continue
                        stop_trips.setdefault(stop_id, set()).add(trip_id)

                        seconds = _seconds(row[i_dep])
                        if seconds is not None:
                            stop_departures.setdefault(stop_id, []).append((trip_id, seconds))

                        try:
                            sequence = int(row[i_seq].strip())
                        except ValueError:
                            sequence = 0
                        current = first_stop.get(trip_id)
                        if current is None or sequence < current[0]:
                            first_stop[trip_id] = (sequence, stop_id)
                        current = last_stop.get(trip_id)
                        if current is None or sequence > current[0]:
                            last_stop[trip_id] = (sequence, stop_id)

        feed.stop_trips = stop_trips
        feed.stop_departures = stop_departures

        # Origen, destino final y línea de cada viaje
        line_terminals = config.get("line_terminals")
        for trip_id, meta in trip_meta.items():
            meta.origin = name_by_id.get(first_stop.get(trip_id, (0, ""))[1])
            meta.terminus = name_by_id.get(last_stop.get(trip_id, (0, ""))[1])
            if line_terminals:
                meta.line = _derive_line(line_terminals, meta.origin, meta.terminus)
        feed.trip_meta = trip_meta

        # Calendario (para el horario programado)
        for row in _rows(zf, "calendar.txt"):
            start = _date(row.get("start_date"))
            end = _date(row.get("end_date"))
            if start is None or end is None:
                continue
            days = frozenset(
                position
                for position, name in enumerate(
                    (
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    )
                )
                if (row.get(name) or "0").strip() == "1"
            )
            feed.services[(row.get("service_id") or "").strip()] = Service(
                days=days, start=start, end=end
            )
        for row in _rows(zf, "calendar_dates.txt"):
            day = _date(row.get("date"))
            if day is None:
                continue
            try:
                exception = int((row.get("exception_type") or "0").strip())
            except ValueError:
                continue
            feed.exceptions[((row.get("service_id") or "").strip(), day)] = exception

        # Agrupa plataformas/andenes en paradas lógicas usando parent_station
        raw_stops = [
            row
            for row in all_stops
            if (row.get("location_type") or "0").strip() in ("", "0")
        ]
        groups: dict[str, list[dict[str, str]]] = {}
        for row in raw_stops:
            stop_id = (row.get("stop_id") or "").strip()
            if stop_id not in stop_trips:
                continue
            parent = (row.get("parent_station") or "").strip() or stop_id
            groups.setdefault(parent, []).append(row)

        for group_id, members in groups.items():
            lat = next(
                (_float(m.get("stop_lat")) for m in members if _float(m.get("stop_lat"))),
                None,
            )
            lon = next(
                (_float(m.get("stop_lon")) for m in members if _float(m.get("stop_lon"))),
                None,
            )
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
        "%s: %s paradas, %s viajes, %s líneas",
        config["name"],
        len(feed.stops),
        len(feed.trip_meta),
        len(feed.lines),
    )
    return feed


def load_static(
    network: str, stop_ids: list[str] | tuple[str, ...] | None = None
) -> StaticFeed:
    """Descarga y parsea el GTFS estático (bloqueante), con caché por paradas."""
    key = (network, tuple(sorted(stop_ids)) if stop_ids else None)
    cached = _CACHE.get(key)
    if cached is not None and time.time() - cached.fetched_at < STATIC_TTL:
        return cached

    config = NETWORKS[network]
    _LOGGER.debug("Descargando GTFS estático de %s", config["name"])
    feed = parse_static(network, _download(config["gtfs_url"], cache=True), stop_ids)
    _CACHE[key] = feed
    return feed


def load_stops(network: str) -> StaticFeed:
    """Horario estático completo (sin filtro): sirve para listar paradas y líneas."""
    return load_static(network, None)


_STOP_INDEX: dict[str, dict[str, Stop]] = {}


def load_stop_index(network: str) -> dict[str, Stop]:
    """Paradas de la red sin horarios (barato), para ordenarlas por distancia.

    Se cachea en memoria para siempre: las paradas de una red no cambian.
    """
    cached = _STOP_INDEX.get(network)
    if cached is not None:
        return cached

    config = NETWORKS[network]
    _LOGGER.debug("Descargando índice de paradas de %s", config["name"])
    raw = _download(config["gtfs_url"], cache=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        rows = [
            row
            for row in _rows(zf, "stops.txt")
            if (row.get("location_type") or "0").strip() in ("", "0")
        ]

    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        stop_id = (row.get("stop_id") or "").strip()
        parent = (row.get("parent_station") or "").strip() or stop_id
        groups.setdefault(parent, []).append(row)

    stops: dict[str, Stop] = {}
    for group_id, members in groups.items():
        lat = next(
            (_float(m.get("stop_lat")) for m in members if _float(m.get("stop_lat"))), None
        )
        lon = next(
            (_float(m.get("stop_lon")) for m in members if _float(m.get("stop_lon"))), None
        )
        if lat is None or lon is None:
            continue
        stops[group_id] = Stop(
            stop_id=group_id,
            name=(members[0].get("stop_name") or group_id).strip(),
            lat=lat,
            lon=lon,
            stop_ids=frozenset((m.get("stop_id") or "").strip() for m in members),
        )

    _STOP_INDEX[network] = stops
    return stops


def fetch_realtime(network: str) -> tuple[int | None, list[dict[str, Any]]]:
    """Descarga el feed GTFS-RT (bloqueante). Redes sin RT devuelven vacío."""
    config = NETWORKS[network]
    if not config.get("rt_url"):
        return None, []
    raw = _download(config["rt_url"], timeout=45)
    if not raw:
        _LOGGER.debug("%s: el feed en tiempo real viene vacío", config["name"])
        return None, []
    feed_timestamp, updates = parse_feed(raw)
    _LOGGER.debug(
        "%s: %s actualizaciones en tiempo real (feed %s)",
        config["name"],
        len(updates),
        feed_timestamp,
    )
    return feed_timestamp, updates


# --- salidas -----------------------------------------------------------------


def upcoming_departures(
    feed: StaticFeed,
    updates: list[dict[str, Any]],
    stop: Stop,
    direction: str | None,
    now: float | None = None,
    limit: int = 5,
    route_id: str | None = None,
) -> list[dict[str, Any]]:
    """Próximas salidas reales de una parada, filtradas por línea y sentido."""
    now = time.time() if now is None else now
    found: dict[tuple[str, int], dict[str, Any]] = {}
    for update in updates:
        meta = feed.trip_meta.get(update.get("trip_id") or "")
        if not meta:
            continue
        if direction is not None and meta.direction != direction:
            continue
        if route_id and meta.route_id != route_id:
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
                "headsign": meta.headsign,
                "destination": meta.headsign,
                "line": meta.line,
                "route_id": meta.route_id,
                "origin": meta.origin,
                "terminus": meta.terminus,
                "direction": meta.direction,
                "delay": (stop_time.get("departure") or {}).get("delay"),
            }
    departures = sorted(found.values(), key=lambda item: item["timestamp"])
    return departures[:limit]


def scheduled_departures(
    feed: StaticFeed,
    stop: Stop,
    route_id: str | None = None,
    direction: str | None = None,
    now: dt.datetime | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Próximas salidas según el horario programado (sin tiempo real)."""
    if now is None:
        now = dt.datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    active = feed.service_ids(now)
    found: list[dict[str, Any]] = []
    for stop_id in stop.stop_ids:
        for trip_id, seconds in feed.stop_departures.get(stop_id, ()):  # noqa: B007
            meta = feed.trip_meta.get(trip_id)
            if not meta or meta.service_id not in active:
                continue
            if route_id and meta.route_id != route_id:
                continue
            if direction is not None and meta.direction != direction:
                continue
            when = midnight + dt.timedelta(seconds=seconds)
            if when.timestamp() < now.timestamp() - DEPARTURE_GRACE:
                continue
            found.append(
                {
                    "trip_id": trip_id,
                    "timestamp": when.timestamp(),
                    "in_seconds": int(when.timestamp() - now.timestamp()),
                    "in_minutes": round((when.timestamp() - now.timestamp()) / 60),
                    "headsign": meta.headsign,
                    "destination": meta.headsign,
                    "line": meta.line,
                    "route_id": meta.route_id,
                    "origin": meta.origin,
                    "terminus": meta.terminus,
                    "direction": meta.direction,
                    "delay": None,
                }
            )
    found.sort(key=lambda item: item["timestamp"])
    return found[:limit]


def departures_for(
    feed: StaticFeed,
    updates: list[dict[str, Any]],
    stop: Stop,
    key: str,
    now: float | None = None,
    limit: int = 5,
) -> tuple[list[dict[str, Any]], str]:
    """Salidas de una opción (línea+sentido) con su origen de datos.

    Devuelve (salidas, origen) donde origen es "realtime", "schedule" o "none".
    Se usa el tiempo real cuando hay datos; si no, el horario programado.
    """
    route_id, direction = split_key(key)
    now_ts = time.time() if now is None else now
    config = NETWORKS[feed.network]

    if not config.get("schedule_only"):
        realtime = upcoming_departures(
            feed,
            updates,
            stop,
            direction,
            now=now_ts,
            limit=limit,
            route_id=route_id or None,
        )
        if realtime:
            return realtime, "realtime"

    scheduled = scheduled_departures(
        feed,
        stop,
        route_id=route_id or None,
        direction=direction,
        now=dt.datetime.fromtimestamp(now_ts).astimezone(),
        limit=limit,
    )
    return scheduled, ("schedule" if scheduled else "none")
