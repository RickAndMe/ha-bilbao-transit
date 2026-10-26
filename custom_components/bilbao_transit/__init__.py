"""Integración Bilbao Transit: próximas salidas de metro y tranvía en tiempo real."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DIRECTION_LABELS, CONF_NETWORK, DOMAIN, NETWORKS
from .coordinator import BilbaoTransitCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

FRONTEND_KEY = f"{DOMAIN}_frontend"
CARD_URL = "/bilbao_transit/bilbao-transit-card.js"
FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra la tarjeta del dashboard y la voz (no depende de config entries)."""
    await _async_register_card(hass)
    await _async_register_voice(hass)
    return True


async def _async_register_voice(hass: HomeAssistant) -> None:
    """Registra el intent de voz y la herramienta para el asistente con IA."""
    store = hass.data.setdefault(FRONTEND_KEY, {})
    if store.get("voice"):
        return

    from homeassistant.helpers import intent as intent_helper

    from .intents import NextDepartureIntent
    from .llm_api import BilbaoTransitAPI
    from .sentences import async_ensure_sentences

    try:
        intent_helper.async_register(hass, NextDepartureIntent())
    except ValueError:
        # ya registrado (recarga en caliente)
        _LOGGER.debug("Intent de voz ya registrado")

    try:
        from homeassistant.helpers import llm as llm_helper

        store["llm_unregister"] = llm_helper.async_register_api(
            hass, BilbaoTransitAPI(hass)
        )
    except Exception:  # noqa: BLE001 - la voz local sigue funcionando sin IA
        _LOGGER.exception("No se pudo registrar la herramienta del asistente con IA")

    await async_ensure_sentences(hass)
    store["voice"] = True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Sirve el JS de la tarjeta y lo añade al frontend una sola vez.

    Se sirve desde la propia integración para que el usuario no tenga que
    descargar nada aparte: al actualizar la integración la tarjeta aparece.
    """
    store = hass.data.setdefault(FRONTEND_KEY, {})
    if store.get("registered"):
        return

    if "http" not in hass.config.components:
        # en tests (o en un arranque sin frontend) no hay servidor HTTP
        return

    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/bilbao_transit", str(FRONTEND_DIR), cache_headers=False)]
        )
    except RuntimeError:
        # ya registrada por una recarga anterior
        _LOGGER.debug("Ruta estática de la tarjeta ya registrada")

    add_extra_js_url(hass, CARD_URL)
    await _async_ensure_lovelace_resource(hass)
    store["registered"] = True
    _LOGGER.debug("Tarjeta Bilbao Transit disponible en %s", CARD_URL)


async def _async_ensure_lovelace_resource(hass: HomeAssistant) -> None:
    """Registra la tarjeta como recurso de Lovelace (si no está ya).

    Inyectar el módulo con ``add_extra_js_url`` no basta: el dashboard necesita
    la tarjeta en la lista de recursos para reconocerla (si falta, la tarjeta da
    "Configuration error"). Se hace una sola vez y sin tocar los recursos del
    usuario.
    """
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace.resources import ResourceStorageCollection

        datos = hass.data.get(LOVELACE_DATA)
        if datos is None:
            return
        recursos = datos.resources
        if not isinstance(recursos, ResourceStorageCollection):
            # Lovelace en modo YAML: no se pueden añadir recursos desde aquí
            return
        if not recursos.loaded:
            await recursos.async_load()
        existentes = await recursos.async_items()
        if any(item.get("url") == CARD_URL for item in existentes):
            return
        await recursos.async_create_item({"res_type": "module", "url": CARD_URL})
        _LOGGER.info("Tarjeta registrada como recurso de Lovelace (%s)", CARD_URL)
    except Exception:  # noqa: BLE001 - nunca debe impedir que arranque la integración
        _LOGGER.exception("No se pudo registrar la tarjeta como recurso de Lovelace")


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
