"""Constantes de la integración Bilbao Transit."""

from __future__ import annotations

DOMAIN = "bilbao_transit"

CONF_NETWORK = "network"
CONF_STOP_ID = "stop_id"
CONF_STOP_NAME = "stop_name"
CONF_DIRECTIONS = "directions"
CONF_DIRECTION_LABELS = "direction_labels"
CONF_MAX_DEPARTURES = "max_departures"

DEFAULT_SCAN_INTERVAL = 45  # segundos
STATIC_TTL = 12 * 3600  # el horario estático se refresca cada 12 h
MAX_DEPARTURES = 5
DEPARTURE_GRACE = 30  # segundos de margen para no mostrar un tren que acaba de salir

# Redes soportadas. Los feeds son datos abiertos sin clave.
NETWORKS: dict[str, dict] = {
    "metro": {
        "name": "Metro Bilbao",
        "gtfs_url": "https://ctb-gtfs.s3.eu-south-2.amazonaws.com/metrobilbao.zip",
        "rt_url": (
            "https://ctb-gtfs-rt.s3.eu-south-2.amazonaws.com/"
            "metro-bilbao-trip-updates.pb"
        ),
        "agency_filter": None,
        "icon": "mdi:train-variant",
        "stop_prefix": "",
    },
    "tram": {
        "name": "Euskotren Tranvía Bilbao",
        "gtfs_url": (
            "https://opendata.euskadi.eus/transport/moveuskadi/euskotren/"
            "gtfs_euskotren.zip"
        ),
        "rt_url": (
            "https://opendata.euskadi.eus/transport/moveuskadi/euskotren/"
            "gtfsrt_euskotren_trip_updates.pb"
        ),
        # Solo las líneas del tranvía de Bilbao dentro del feed de Euskotren
        "agency_filter": "ES:Euskotren:Operator:EUS_TrBi:",
        "icon": "mdi:tram",
        "stop_prefix": "",
    },
}
