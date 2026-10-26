"""Sensores de próximas salidas."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DIRECTION_LABELS,
    CONF_DIRECTIONS,
    CONF_NETWORK,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DOMAIN,
    MAX_DEPARTURES,
    NETWORKS,
)
from .coordinator import BilbaoTransitCoordinator
from .gtfs import Stop, departures_for, split_key

_LOGGER = logging.getLogger(__name__)

STATUS_BY_SOURCE = {
    "realtime": "ok",
    "schedule": "horario (sin tiempo real)",
    "none": "sin servicio",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea un sensor por línea y sentido de la parada configurada."""
    coordinator: BilbaoTransitCoordinator = hass.data[DOMAIN][entry.entry_id]
    stop: Stop | None = coordinator.static.stops.get(entry.data[CONF_STOP_ID])
    if stop is None:
        _LOGGER.error(
            "La parada %s ya no existe en el horario de %s",
            entry.data.get(CONF_STOP_NAME),
            NETWORKS[coordinator.network]["name"],
        )
        return

    directions: list[str] = entry.options.get(
        CONF_DIRECTIONS, entry.data.get(CONF_DIRECTIONS, [])
    )
    labels: dict[str, str] = entry.data.get(CONF_DIRECTION_LABELS, {})
    multi_line = bool(NETWORKS[coordinator.network].get("multi_line"))

    entities = [
        TransitDepartureSensor(
            coordinator=coordinator,
            entry=entry,
            stop=stop,
            key=key,
            label=labels.get(key) or f"sentido {key}",
            multi_line=multi_line,
        )
        for key in directions
    ]
    async_add_entities(entities)


class TransitDepartureSensor(CoordinatorEntity[BilbaoTransitCoordinator], SensorEntity):
    """Minutos que faltan para la próxima salida de una línea y sentido."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "min"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: BilbaoTransitCoordinator,
        entry: ConfigEntry,
        stop: Stop,
        key: str,
        label: str,
        multi_line: bool = False,
    ) -> None:
        super().__init__(coordinator)
        self._stop = stop
        self._key = key
        self._label = label
        self._route_id, self._direction = split_key(key)
        network = NETWORKS[coordinator.network]
        self._network_name = network["name"]
        # En los buses la etiqueta ya incluye la línea ("A2610 · BILBAO").
        self._attr_name = label if multi_line else f"hacia {label}"
        self._attr_unique_id = f"{coordinator.network}:{stop.stop_id}:{key}"
        self._attr_icon = network["icon"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.network}:{stop.stop_id}")},
            name=f"{stop.name} ({network['name']})",
            manufacturer=network.get("manufacturer", "CTB / Euskotren / Bizkaibus"),
            model=network["name"],
            entry_type=DeviceEntryType.SERVICE,
            suggested_area=None,
        )
        self._entry_id = entry.entry_id

    @property
    def _departures(self) -> tuple[list[dict[str, Any]], str]:
        return departures_for(
            self.coordinator.static,
            self.coordinator.data.get("updates") or [],
            self._stop,
            self._key,
            limit=MAX_DEPARTURES,
        )

    @property
    def native_value(self) -> int | None:
        departures, _ = self._departures
        return departures[0]["in_minutes"] if departures else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        departures, source = self._departures
        feed_timestamp = self.coordinator.data.get("feed_timestamp")
        network = NETWORKS[self.coordinator.network]
        attributes: dict[str, Any] = {
            "stop_id": self._stop.stop_id,
            "stop_name": self._stop.name,
            "network": self._network_name,
            "network_emoji": network.get("emoji", "🚏"),
            "network_icon": network.get("icon"),
            "direction": self._direction,
            "direction_label": self._label,
            "line": departures[0]["line"] if departures else None,
            "route_id": self._route_id or None,
            "service_status": STATUS_BY_SOURCE.get(source, source),
            "data_source": source,
            # Numérico a propósito: permite ordenar entidades por cercanía desde
            # plantillas Jinja (el sandbox de HA no deja ordenar por `state`, que
            # es texto) y sirve para automatizaciones del tipo "si faltan <3 min".
            "next_minutes": departures[0]["in_minutes"] if departures else None,
            "next_departures": [
                {
                    "departure": dt_util.as_local(
                        dt_util.utc_from_timestamp(item["timestamp"])
                    ).strftime("%H:%M"),
                    "minutes": item["in_minutes"],
                    "destination": item["destination"],
                    "line": item["line"],
                    "trip_id": item["trip_id"],
                }
                for item in departures
            ],
            "feed_updated": (
                dt_util.as_local(dt_util.utc_from_timestamp(feed_timestamp)).isoformat()
                if feed_timestamp
                else None
            ),
        }
        if departures:
            attributes["destination"] = departures[0]["headsign"]
            attributes["next_departure_time"] = attributes["next_departures"][0][
                "departure"
            ]
        return attributes
