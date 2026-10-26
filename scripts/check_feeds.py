#!/usr/bin/env python3
"""Comprobación contra los feeds oficiales reales de las cuatro redes.

Uso:
    PYTHONPATH=/ruta/a/ha python3 scripts/check_feeds.py

Verifica que los datos abiertos siguen accesibles y con el formato esperado,
y muestra las próximas salidas de las paradas cercanas a casa.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.bilbao_transit.gtfs import (  # noqa: E402
    departures_for,
    fetch_realtime,
    haversine,
    load_static,
    load_stop_index,
    upcoming_departures,
)

HOME = (43.2463746, -2.9071287)
CHECKS = 0
FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  OK   {name}")
    else:
        print(f"  FALLA {name} {detail}")
        FAILS.append(name)


def nearest_stop(network: str):
    """Parada más cercana a casa en la red indicada."""
    index = load_stop_index(network)
    return min(
        index.values(),
        key=lambda stop: haversine(HOME[0], HOME[1], stop.lat, stop.lon),
    )


def print_departures(departures) -> None:
    for dep in departures:
        when = datetime.fromtimestamp(dep["timestamp"]).strftime("%H:%M")
        print(
            f"    {when}  {dep['in_minutes']:>3} min  {dep['line'] or '--':<6} "
            f"{dep['destination']}"
        )


def main() -> int:
    print("== Metro Bilbao (GTFS estático) ==")
    metro = load_static("metro")
    check("descarga el zip GTFS", bool(metro.stops))
    check("hay >1000 viajes", len(metro.trip_meta) > 1000, str(len(metro.trip_meta)))
    bolueta = metro.stops.get("3")
    check("Bolueta existe como parada 3", bolueta is not None)
    if bolueta:
        check("Bolueta agrupa el andén 3.0", "3.0" in bolueta.stop_ids)
        options = metro.options(bolueta)
        check(
            "sentidos con nombre propio",
            options == {"0": "Bilbao (norte)", "1": "Basauri/Etxarri (sur)"},
            str(options),
        )

    print("== Metro Bilbao (tiempo real) ==")
    feed_ts, updates = fetch_realtime("metro")
    check("feed accesible", feed_ts is not None)
    check(
        "feed fresco (<15 min)",
        feed_ts is not None and abs(feed_ts - time.time()) < 900,
        str(feed_ts),
    )
    check("trae viajes", bool(updates), str(len(updates)))
    if bolueta:
        now = time.time()
        departures = upcoming_departures(metro, updates, bolueta, None, now=now, limit=6)
        print("  próximas salidas de Bolueta:")
        print_departures(departures)
        check("las horas son futuras", all(d["timestamp"] >= now - 60 for d in departures))
        check("cada salida trae línea", all(d["line"] for d in departures))
        check("cada salida trae destino", all(d["destination"] for d in departures))

    print("== Euskotren Tranvía Bilbao (GTFS estático) ==")
    tram = load_static("tram")
    boluetas = [s for s in tram.stops.values() if s.name == "Bolueta"]
    check("Bolueta existe en el tranvía", bool(boluetas))
    if boluetas:
        check(
            "incluye el andén 2674",
            any("2674" in sid for s in boluetas for sid in s.stop_ids),
        )
        options = tram.options(boluetas[0])
        check(
            "sentidos La Casilla / Bolueta",
            set(options.values()) == {"La Casilla", "Bolueta"},
            str(options),
        )

    print("== Euskotren Tranvía (tiempo real) ==")
    tram_ts, tram_updates = fetch_realtime("tram")
    check("feed accesible", tram_ts is not None)
    check("trae viajes", bool(tram_updates), str(len(tram_updates)))
    if boluetas:
        departures = upcoming_departures(
            tram, tram_updates, boluetas[0], None, now=time.time(), limit=6
        )
        print("  próximas salidas de Bolueta:")
        print_departures(departures)

    for network, label in (("bizkaibus", "Bizkaibus"), ("bilbobus", "Bilbobus")):
        print(f"== {label} (GTFS + horario/tiempo real) ==")
        stop = nearest_stop(network)
        distance = haversine(HOME[0], HOME[1], stop.lat, stop.lon)
        print(f"  parada más cercana: {stop.name} a {distance:.0f} m (id {stop.stop_id})")

        feed = load_static(network, sorted(stop.stop_ids))
        lines = feed.lines_at(stop)
        check(f"{label}: líneas en la parada", bool(lines), str(list(lines)))
        options = feed.options(stop)
        check(f"{label}: opciones línea/sentido", bool(options), str(options))
        print("  opciones:")
        for key, name in options.items():
            print(f"     {key:<12} {name}")

        realtime_ts, realtime = fetch_realtime(network)
        print(f"  tiempo real: {len(realtime)} viajes")
        for key, name in list(options.items())[:3]:
            departures, source = departures_for(feed, realtime, stop, key, limit=3)
            print(f"   {name} [{source}]")
            print_departures(departures)
        check(
            f"{label}: hay salidas en alguna opción",
            any(
                departures_for(feed, realtime, stop, key, limit=1)[0]
                for key in list(options)[:3]
            ),
        )

    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} comprobaciones OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
