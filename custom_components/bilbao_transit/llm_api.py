"""Herramienta para el asistente con IA (Assist + LLM)."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, llm

from .const import DOMAIN
from .queries import departures, describe, red_desde_texto

API_PROMPT = (
    "Tienes acceso a las paradas de transporte público de Bilbao que el usuario "
    "tiene configuradas (Metro Bilbao, Euskotren Tranvía, Bizkaibus y Bilbobus). "
    "Cuando pregunte cuándo pasa o cuánto falta para el metro, el tranvía o el bus, "
    "usa la herramienta antes de responder y contesta con el tiempo en minutos y "
    "el destino. Si el resultado dice que el dato viene del horario programado y no "
    "de tiempo real, dilo con naturalidad."
)


class NextDeparturesTool(llm.Tool):
    """Devuelve las próximas salidas de las paradas configuradas."""

    name = "bilbao_transit_next_departures"
    description = (
        "Próximas salidas de metro, tranvía, Bizkaibus y Bilbobus en las paradas "
        "del usuario, con los minutos que faltan. Úsala siempre que pregunte a qué "
        "hora pasa, cuánto falta o cuándo es el próximo metro, tranvía o bus."
    )
    parameters = vol.Schema(
        {
            vol.Optional(
                "transporte",
                description="Medio por el que pregunta: metro, tranvia, bus, bizkaibus o bilbobus. Omitir para todos.",
            ): cv.string,
            vol.Optional(
                "sentido",
                description=(
                    "Texto del destino o sentido, por ejemplo 'Bilbao', 'Basauri' "
                    "o el nombre de una parada. Omitir si no lo concreta."
                ),
            ): cv.string,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> dict:
        args = tool_input.tool_args or {}
        red = red_desde_texto(args.get("transporte"))
        filas = departures(hass, network=red, sentido=args.get("sentido"))

        if not filas:
            return {
                "success": True,
                "result": {
                    "departures": [],
                    "summary": (
                        "No hay salidas disponibles ahora mismo para lo que pide. "
                        "Puede ser fuera del horario de servicio o una parada que el "
                        "usuario no tiene configurada."
                    ),
                },
            }

        idioma = getattr(llm_context, "language", None) or hass.config.language or "es"
        resumen = f"{describe(filas[0], idioma).capitalize()}."
        if len(filas) > 1:
            siguientes = "; ".join(
                f"{fila['network']} hacia {fila['direction']} en {fila['minutes']} min"
                for fila in filas[1:4]
            )
            resumen += f" Después: {siguientes}."

        return {
            "success": True,
            "result": {
                "summary": resumen,
                "departures": [
                    {
                        "transport": fila["network"],
                        "line": fila["line"],
                        "direction": fila["direction"],
                        "stop": fila["stop_name"],
                        "minutes": fila["minutes"],
                        "time": fila["departure"],
                        "realtime": fila["realtime"],
                    }
                    for fila in filas[:6]
                ],
            },
        }


class BilbaoTransitAPI(llm.API):
    """Expone la herramienta de Bilbao Transit a los agentes con IA."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Inicializa la API."""
        super().__init__(hass=hass, id=f"{DOMAIN}_llm", name="Bilbao Transit")

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        """Devuelve las herramientas disponibles para este contexto."""
        return llm.APIInstance(
            api=self,
            api_prompt=API_PROMPT,
            llm_context=llm_context,
            tools=[NextDeparturesTool()],
        )
