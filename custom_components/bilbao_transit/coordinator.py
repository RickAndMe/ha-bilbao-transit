"""Coordinador de datos: feed en tiempo real + caché del horario estático."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_NETWORK, DEFAULT_SCAN_INTERVAL, DOMAIN, NETWORKS, STATIC_TTL
from .gtfs import StaticFeed, fetch_realtime, load_static

_LOGGER = logging.getLogger(__name__)


class BilbaoTransitCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Descarga el GTFS-RT de la red y mantiene cacheado el horario estático."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.network: str = entry.data[CONF_NETWORK]
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.network}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    @property
    def static(self) -> StaticFeed:
        """Horario estático cargado en el último refresh."""
        return self.data["static"]

    async def _async_static(self) -> StaticFeed:
        """Horario estático cacheado en memoria, compartido entre entradas."""
        domain_data = self.hass.data.setdefault(DOMAIN, {})
        cache: dict[str, StaticFeed] = domain_data.setdefault("static", {})
        locks: dict[str, asyncio.Lock] = domain_data.setdefault("locks", {})

        cached = cache.get(self.network)
        if cached is not None and time.time() - cached.fetched_at < STATIC_TTL:
            return cached

        lock = locks.setdefault(self.network, asyncio.Lock())
        async with lock:
            cached = cache.get(self.network)
            if cached is not None and time.time() - cached.fetched_at < STATIC_TTL:
                return cached
            try:
                feed = await self.hass.async_add_executor_job(load_static, self.network)
            except Exception as err:  # noqa: BLE001 - cualquier fallo de red/parseo
                if cached is not None:
                    _LOGGER.warning(
                        "No se pudo actualizar el horario de %s, uso el cacheado: %s",
                        NETWORKS[self.network]["name"],
                        err,
                    )
                    return cached
                raise UpdateFailed(
                    f"No se pudo descargar el horario de {NETWORKS[self.network]['name']}: {err}"
                ) from err
            cache[self.network] = feed
            return feed

    async def _async_update_data(self) -> dict[str, Any]:
        static = await self._async_static()
        try:
            feed_timestamp, updates = await self.hass.async_add_executor_job(
                fetch_realtime, self.network
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(
                f"Error leyendo el tiempo real de {NETWORKS[self.network]['name']}: {err}"
            ) from err
        return {
            "static": static,
            "feed_timestamp": feed_timestamp,
            "updates": updates,
            "fetched_at": time.time(),
        }
