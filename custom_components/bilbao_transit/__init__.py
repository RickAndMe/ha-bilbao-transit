"""Integración Bilbao Transit: próximas salidas de metro y tranvía en tiempo real."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_DIRECTION_LABELS, CONF_NETWORK, DOMAIN, NETWORKS
from .coordinator import BilbaoTransitCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migra entradas antiguas.

    v1 -> v2: las etiquetas de sentido pasan a describir el sentido real
    ("Bilbao (norte)") en vez del destino más frecuente ("Kabiezes"), porque
    cada tren puede terminar en un destino distinto.
    """
    if entry.version > 2:
        return False

    if entry.version < 2:
        network = entry.data.get(CONF_NETWORK, "")
        fixed = (NETWORKS.get(network) or {}).get("direction_labels")
        if fixed:
            current = entry.data.get(CONF_DIRECTION_LABELS) or {
                direction: direction for direction in entry.data.get("directions", [])
            }
            new_labels = {
                direction: fixed.get(direction, label)
                for direction, label in current.items()
            }
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_DIRECTION_LABELS: new_labels}, version=2
            )
            _LOGGER.info(
                "Entrada %s migrada a v2: sentidos %s", entry.title, new_labels
            )
        else:
            hass.config_entries.async_update_entry(entry, version=2)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura una parada a partir de una config entry."""
    coordinator = BilbaoTransitCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga una config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la entrada cuando cambian las opciones."""
    await hass.config_entries.async_reload(entry.entry_id)
