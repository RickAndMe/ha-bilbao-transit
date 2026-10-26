"""Coordinador de datos: feed en tiempo real + horario estático."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_NETWORK,
    CONF_STOP_IDS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    NETWORKS,
)
from .gtfs import StaticFeed, fetch_realtime, load_static

_LOGGER = logging.getLogger(__name__)


class BilbaoTransitCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Descarga el GTFS-RT de la red y mantiene el horario estático cacheado."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.network: str = entry.data[CONF_NETWORK]
        self.stop_ids: list[str] | None = entry.data.get(CONF_STOP_IDS) or None
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.network}",
            update_interval=timedelta(
                seconds=DEFAULT_SCAN_INTERVAL
                if not NETWORKS[self.network].get("schedule_only")
                else 300
            ),
        )

    @property
    def static(self) -> StaticFeed:
        """Horario estático cargado en el último refresh."""
        return self.data["static"]

    @property
    def schedule_only(self) -> bool:
        """True si la red no publica estimaciones en tiempo real."""
        return bool(NETWORKS[self.network].get("schedule_only"))

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            static = await self.hass.async_add_executor_job(
                load_static, self.network, self.stop_ids
            )
        except Exception as err:  # noqa: BLE001 - cualquier fallo de red/parseo
            raise UpdateFailed(
                f"No se pudo cargar el horario de {NETWORKS[self.network]['name']}: {err}"
            ) from err

        feed_timestamp: int | None = None
        updates: list[dict[str, Any]] = []
        if not self.schedule_only:
            try:
                feed_timestamp, updates = await self.hass.async_add_executor_job(
                    fetch_realtime, self.network
                )
            except Exception as err:  # noqa: BLE001
                # El tiempo real es un extra: si falla, seguimos con el horario.
                _LOGGER.warning(
                    "Tiempo real de %s no disponible, uso el horario programado: %s",
                    NETWORKS[self.network]["name"],
                    err,
                )

        return {
            "static": static,
            "feed_timestamp": feed_timestamp,
            "updates": updates,
            "fetched_at": time.time(),
        }
