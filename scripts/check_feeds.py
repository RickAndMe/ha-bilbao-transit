#!/usr/bin/env python3
"""Comprobación contra los feeds oficiales reales (metro y tranvía).

Uso:
    PYTHONPATH=/ruta/a/ha python3 scripts/check_feeds.py

Verifica que los datos abiertos siguen accesibles y con el formato esperado,
y muestra las próximas salidas de la parada indicada.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.bilbao_transit.gtfs import (  # noqa: E402
    fetch_realtime,
    load_static,
    upcoming_departures,
)

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


def main() -> int:
    print("== Metro Bilbao (GTFS estático) ==")
    metro = load_static("metro")
    check("descarga el zip GTFS", bool(metro.stops))
    check("hay >1000 viajes", len(metro.trip_meta) > 1000, str(len(metro.trip_meta)))
    bolueta = metro.stops.get("3")
    check("Bolueta existe como parada 3", bolueta is not None)
    if bolueta:
        check("Bolueta agrupa el andén 3.0", "3.0" in bolueta.stop_ids)
        directions = metro.directions(bolueta)
        check("dos sentidos distintos", set(directions) == {"0", "1"}, str(directions))

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
        for dep in departures:
            when = datetime.fromtimestamp(dep["timestamp"]).strftime("%H:%M:%S")
            sense = "hacia Bilbao" if dep["direction"] == "0" else "hacia el sur"
            print(
                f"    {when}  {dep['in_minutes']:>3} min  {sense:<14} {dep['headsign']}"
            )
        check("las horas son futuras", all(d["timestamp"] >= now - 60 for d in departures))

    print("== Euskotren Tranvía Bilbao (GTFS estático) ==")
    tram = load_static("tram")
    boluetas = [s for s in tram.stops.values() if s.name == "Bolueta"]
    check("Bolueta existe en el tranvía", bool(boluetas))
    if boluetas:
        check(
            "incluye el andén 2674",
            any("2674" in sid for s in boluetas for sid in s.stop_ids),
        )
        directions = tram.directions(boluetas[0])
        check(
            "sentidos La Casilla / Bolueta",
            set(directions.values()) == {"La Casilla", "Bolueta"},
            str(directions),
        )

    print("== Euskotren Tranvía (tiempo real) ==")
    tram_ts, tram_updates = fetch_realtime("tram")
    check("feed accesible", tram_ts is not None)
    check("trae viajes", bool(tram_updates), str(len(tram_updates)))
    if boluetas:
        now = time.time()
        departures = upcoming_departures(tram, tram_updates, boluetas[0], None, now=now, limit=6)
        print("  próximas salidas de Bolueta:")
        for dep in departures:
            when = datetime.fromtimestamp(dep["timestamp"]).strftime("%H:%M:%S")
            print(f"    {when}  {dep['in_minutes']:>3} min  {dep['headsign']}")

    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} comprobaciones OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
