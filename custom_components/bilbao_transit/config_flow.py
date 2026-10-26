"""Config flow: elegir red, parada cercana, líneas y sentidos."""

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
    CONF_LINES,
    CONF_NETWORK,
    CONF_STOP_ID,
    CONF_STOP_IDS,
    CONF_STOP_NAME,
    DOMAIN,
    NETWORKS,
)
from .gtfs import (
    StaticFeed,
    Stop,
    haversine,
    load_static,
    load_stop_index,
    split_key,
)

_LOGGER = logging.getLogger(__name__)


class BilbaoTransitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Alta de una parada."""

    VERSION = 2

    def __init__(self) -> None:
        self._network: str | None = None
        self._stop_index: dict[str, Stop] = {}
        self._static: StaticFeed | None = None
        self._stop_key: str | None = None
        self._lines: list[str] = []
        self._options: dict[str, str] = {}

    # -- helpers -------------------------------------------------------------

    @property
    def _multi_line(self) -> bool:
        return bool(NETWORKS[self._network or ""].get("multi_line"))

    async def _async_load_index(self) -> None:
        """Paradas de la red (sin horarios), para ordenarlas por distancia."""
        if not self._stop_index and self._network is not None:
            self._stop_index = await self.hass.async_add_executor_job(
                load_stop_index, self._network
            )

    async def _async_load_static(self, stop_ids: list[str]) -> None:
        """Horario de la red limitado a las paradas que interesan."""
        if self._static is None and self._network is not None:
            self._static = await self.hass.async_add_executor_job(
                load_static, self._network, stop_ids
            )

    def _sorted_stops(self) -> list[tuple[str, str, float]]:
        """[(stop_id, etiqueta con distancia, distancia)] ordenado por cercanía."""
        home_lat = self.hass.config.latitude
        home_lon = self.hass.config.longitude
        rows: list[tuple[str, str, float]] = []
        for stop in self._stop_index.values():
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
                await self._async_load_index()
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("No se pudo descargar el listado de paradas: %s", err)
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
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._stop_key = user_input[CONF_STOP_ID]
            stop = self._stop_index[self._stop_key]
            try:
                await self._async_load_static(sorted(stop.stop_ids))
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("No se pudo descargar el horario: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if self._multi_line:
                    return await self.async_step_lines()
                return await self.async_step_directions()

        # La primera de la lista es la más cercana: el selector ya la propone.
        options = {stop_id: label for stop_id, label, _ in self._sorted_stops()}
        default = next(iter(options), None)
        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema(
                {vol.Required(CONF_STOP_ID, default=default): vol.In(options)}
            ),
            errors=errors,
            description_placeholders={
                "network": NETWORKS[self._network or "metro"]["name"],
            },
        )

    async def async_step_lines(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """En los buses hay varias líneas por parada: hay que elegir cuáles."""
        assert self._static is not None and self._stop_key is not None
        stop = self._static.stops.get(self._stop_key) or self._stop_index[self._stop_key]

        if user_input is not None:
            self._lines = user_input[CONF_LINES]
            self._options = {
                key: label
                for key, label in self._static.options(stop).items()
                if split_key(key)[0] in self._lines
            }
            return await self.async_step_directions()

        lines = self._static.lines_at(stop)
        if not lines:
            return self.async_abort(reason="no_lines")
        choices = {
            route_id: f"{line.short} · {line.long}" if line.long else line.short
            for route_id, line in lines.items()
        }
        return self.async_show_form(
            step_id="lines",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LINES, default=list(choices)): cv.multi_select(
                        choices
                    )
                }
            ),
            description_placeholders={"stop": stop.name},
        )

    async def async_step_directions(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        assert self._static is not None and self._stop_key is not None
        stop = self._static.stops.get(self._stop_key) or self._stop_index[self._stop_key]

        if user_input is not None:
            chosen = user_input[CONF_DIRECTIONS]
            await self.async_set_unique_id(
                f"{self._network}:{stop.stop_id}:{','.join(sorted(self._lines))}"
                if self._lines
                else f"{self._network}:{stop.stop_id}",
                raise_on_progress=False,
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{stop.name} ({NETWORKS[self._network or 'metro']['name']})",
                data={
                    CONF_NETWORK: self._network,
                    CONF_STOP_ID: stop.stop_id,
                    CONF_STOP_NAME: stop.name,
                    CONF_STOP_IDS: sorted(stop.stop_ids),
                    CONF_LINES: self._lines,
                    CONF_DIRECTIONS: chosen,
                    CONF_DIRECTION_LABELS: {
                        key: self._options[key] for key in chosen if key in self._options
                    },
                },
            )

        self._options = self._options or self._static.options(stop)
        if not self._options:
            return self.async_abort(reason="no_directions")
        prefix = "" if self._multi_line else "hacia "
        choices = {key: f"{prefix}{label}" for key, label in self._options.items()}
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
    """Permite cambiar las líneas y sentidos sin borrar la integración."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self.config_entry
        network = entry.data[CONF_NETWORK]
        stop_id = entry.data[CONF_STOP_ID]
        multi_line = bool(NETWORKS[network].get("multi_line"))

        try:
            static = await self.hass.async_add_executor_job(
                load_static, network, entry.data.get(CONF_STOP_IDS) or None
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("No se pudo descargar el horario: %s", err)
            return self.async_abort(reason="cannot_connect")

        stop = static.stops.get(stop_id)
        if stop is None:
            return self.async_abort(reason="stop_not_found")

        labels = static.options(stop)
        prefix = "" if multi_line else "hacia "
        choices = {key: f"{prefix}{label}" for key, label in labels.items()}

        if user_input is not None:
            chosen = user_input[CONF_DIRECTIONS]
            new_data = dict(entry.data)
            new_data[CONF_DIRECTION_LABELS] = {
                key: labels[key] for key in chosen if key in labels
            }
            self.hass.config_entries.async_update_entry(entry, data=new_data)
            return self.async_create_entry(title="", data={CONF_DIRECTIONS: chosen})

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
