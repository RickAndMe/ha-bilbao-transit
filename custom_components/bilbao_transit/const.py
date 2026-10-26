"""Constantes de la integración Bilbao Transit."""

from __future__ import annotations

DOMAIN = "bilbao_transit"

CONF_NETWORK = "network"
CONF_STOP_ID = "stop_id"
CONF_STOP_NAME = "stop_name"
CONF_STOP_IDS = "stop_ids"
CONF_DIRECTIONS = "directions"
CONF_DIRECTION_LABELS = "direction_labels"
CONF_LINES = "lines"
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
        "emoji": "🚇",
        # El GTFS solo publica una ruta ("MB"): el sentido es global
        # (0 = norte hacia Bilbao, 1 = sur) y se etiqueta por su significado real,
        # porque cada tren puede terminar en un destino distinto.
        "direction_labels": {"0": "Bilbao (norte)", "1": "Basauri/Etxarri (sur)"},
        # Línea deducida del origen del viaje: L1 arranca en Etxebarri y L2 en Basauri.
        # Los extremos cortos (Bidezabal, Sopela, Larrabasterra...) son de la L1;
        # Kabiezes y Basauri son de la L2.
        "line_terminals": {
            "L1": {
                "Etxebarri",
                "Plentzia",
                "Ibarbengoa",
                "Larrabasterra",
                "Sopela",
                "Bidezabal",
                "Urduliz",
            },
            "L2": {"Basauri", "Kabiezes"},
        },
        "multi_line": False,
        "schedule_only": False,
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
        "emoji": "🚊",
        "direction_labels": None,
        "line_terminals": None,
        "multi_line": False,
        "schedule_only": False,
    },
    "bizkaibus": {
        "name": "Bizkaibus",
        "gtfs_url": (
            "https://opendata.euskadi.eus/transport/moveuskadi/bizkaibus/"
            "gtfs_bizkaibus.zip"
        ),
        "rt_url": (
            "https://opendata.euskadi.eus/transport/moveuskadi/bizkaibus/"
            "gtfsrt_bizkaibus_trip_updates.pb"
        ),
        "agency_filter": None,
        "icon": "mdi:bus",
        "emoji": "🚌",
        "direction_labels": None,
        "line_terminals": None,
        # Varias líneas por parada: hay que elegir línea y sentido.
        "multi_line": True,
        "schedule_only": False,
    },
    "bilbobus": {
        "name": "Bilbobus",
        "gtfs_url": (
            "https://opendata.euskadi.eus/transport/moveuskadi/bilbobus/"
            "gtfs_bilbobus.zip"
        ),
        # Bilbobus no publica estimaciones de llegada, solo posiciones de
        # vehículos (y a menudo vacías), así que se usa el horario programado.
        "rt_url": None,
        "agency_filter": None,
        "icon": "mdi:bus-side",
        "emoji": "🚌",
        "direction_labels": None,
        "line_terminals": None,
        "multi_line": True,
        "schedule_only": True,
    },
}
