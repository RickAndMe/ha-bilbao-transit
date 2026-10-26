"""Config flow: elegir red, parada cercana y sentidos."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_DIRECTION_LABELS,
    CONF_DIRECTIONS,
    CONF_NETWORK,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DOMAIN,
    NETWORKS,
)
from .gtfs import StaticFeed, haversine, load_static

_LOGGER = logging.getLogger(__name__)


class BilbaoTransitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Alta de una parada."""

    VERSION = 2

    def __init__(self) -> None:
        self._network: str | None = None
        self._static: StaticFeed | None = None
        self._stop_key: str | None = None
        self._directions: dict[str, str] = {}

    # -- helpers -------------------------------------------------------------

    async def _async_load(self) -> None:
        """Descarga el horario estático de la red elegida."""
        if self._static is None and self._network is not None:
            self._static = await self.hass.async_add_executor_job(
                load_static, self._network
            )

    def _sorted_stops(self) -> list[tuple[str, str, float]]:
        """[(stop_id, etiqueta con distancia, distancia)] ordenado por cercanía."""
        assert self._static is not None
        home_lat = self.hass.config.latitude
        home_lon = self.hass.config.longitude
        rows: list[tuple[str, str, float]] = []
        for stop in self._static.stops.values():
            distance = haversine(home_lat, home_lon, stop.lat, stop.lon)
            label = f"{stop.name} — {distance:.0f} m" if distance < 5000 else stop.name
            rows.append((stop.stop_id, label, distance))
        rows.sort(key=lambda row: row[2])
        return rows

    # -- pasos ---------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._network = user_input[CONF_NETWORK]
            try:
                await self._async_load()
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("No se pudo descargar el horario: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_stop()

        schema = vol.Schema(
            {
                vol.Required(CONF_NETWORK, default="metro"): vol.In(
                    {key: value["name"] for key, value in NETWORKS.items()}
                )
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        assert self._static is not None
        if user_input is not None:
            self._stop_key = user_input[CONF_STOP_ID]
            self._directions = self._static.directions(
                self._static.stops[self._stop_key]
            )
            await self.async_set_unique_id(
                f"{self._network}:{self._stop_key}", raise_on_progress=False
            )
            self._abort_if_unique_id_configured()
            return await self.async_step_directions()

        options = {
            stop_id: label for stop_id, label, _distance in self._sorted_stops()
        }
        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_ID): vol.In(options),
                }
            ),
            description_placeholders={
                "network": NETWORKS[self._network or "metro"]["name"],
            },
        )

    async def async_step_directions(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        assert self._static is not None and self._stop_key is not None
        stop = self._static.stops[self._stop_key]
        if user_input is not None:
            chosen = user_input[CONF_DIRECTIONS]
            return self.async_create_entry(
                title=f"{stop.name} ({NETWORKS[self._network or 'metro']['name']})",
                data={
                    CONF_NETWORK: self._network,
                    CONF_STOP_ID: stop.stop_id,
                    CONF_STOP_NAME: stop.name,
                    CONF_DIRECTIONS: chosen,
                    CONF_DIRECTION_LABELS: {
                        direction: self._directions[direction] for direction in chosen
                    },
                },
            )

        choices = {
            direction: f"hacia {label}" for direction, label in self._directions.items()
        }
        return self.async_show_form(
            step_id="directions",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DIRECTIONS, default=list(choices)
                    ): cv.multi_select(choices),
                }
            ),
            description_placeholders={"stop": stop.name},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "BilbaoTransitOptionsFlow":
        return BilbaoTransitOptionsFlow()


class BilbaoTransitOptionsFlow(config_entries.OptionsFlow):
    """Permite cambiar los sentidos mostrados sin borrar la integración."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self.config_entry
        network = entry.data[CONF_NETWORK]
        stop_id = entry.data[CONF_STOP_ID]

        try:
            static = await self.hass.async_add_executor_job(load_static, network)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("No se pudo descargar el horario: %s", err)
            return self.async_abort(reason="cannot_connect")

        stop = static.stops.get(stop_id)
        if stop is None:
            return self.async_abort(reason="stop_not_found")

        labels = static.directions(stop)
        choices = {direction: f"hacia {label}" for direction, label in labels.items()}

        if user_input is not None:
            chosen = user_input[CONF_DIRECTIONS]
            new_data = dict(entry.data)
            new_data[CONF_DIRECTION_LABELS] = {
                direction: labels[direction] for direction in chosen
            }
            self.hass.config_entries.async_update_entry(entry, data=new_data)
            return self.async_create_entry(
                title="", data={CONF_DIRECTIONS: chosen}
            )

        current = entry.options.get(
            CONF_DIRECTIONS, entry.data.get(CONF_DIRECTIONS, list(choices))
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DIRECTIONS, default=list(current)
                    ): cv.multi_select(choices),
                }
            ),
        )
