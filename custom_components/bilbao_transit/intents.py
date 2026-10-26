"""Intents de voz de Bilbao Transit (Assistant local y frases fijas)."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, intent

from .queries import departures, describe, red_desde_texto

_LOGGER = logging.getLogger(__name__)

INTENT_NEXT_DEPARTURE = "BilbaoTransitNextDeparture"

SLOT_TRANSPORTE = "transporte"
SLOT_SENTIDO = "sentido"


class NextDepartureIntent(intent.IntentHandler):
    """Responde '¿cuándo llega el próximo tranvía?'."""

    intent_type = INTENT_NEXT_DEPARTURE
    description = "Dice cuánto falta para la próxima salida de metro, tranvía o bus"
    slot_schema = {
        vol.Optional(SLOT_TRANSPORTE): cv.string,
        vol.Optional(SLOT_SENTIDO): cv.string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass: HomeAssistant = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots or {})
        dicho = slots.get(SLOT_TRANSPORTE, {}).get("value")
        sentido = slots.get(SLOT_SENTIDO, {}).get("value")

        red = red_desde_texto(dicho)
        filas = departures(hass, network=red, sentido=sentido)

        respuesta = intent_obj.create_response()

        if not filas:
            nombre = dicho or "transporte"
            texto = f"Ahora mismo no tengo salidas de {nombre} en tus paradas."
            respuesta.async_set_speech(texto)
            respuesta.async_set_error(
                intent.IntentResponseErrorCode.NO_VALID_TARGETS, texto
            )
            _LOGGER.debug("Intent sin resultados (transporte=%s, sentido=%s)", dicho, sentido)
            return respuesta

        cercana = filas[0]
        if red == "bus":
            cercana = dict(cercana)
            cercana["network"] = cercana["network"] or "autobús"

        idioma = getattr(intent_obj, "language", None) or hass.config.language or "es"
        frase = describe(cercana, idioma)
        texto = f"{frase[0].upper()}{frase[1:]}."
        if len(filas) > 1:
            siguiente = filas[1]
            texto += (
                f" Luego, {siguiente['network']} hacia {siguiente['direction']}"
                f" en {siguiente['minutes']} minutos."
            )
        respuesta.async_set_speech(texto)
        _LOGGER.debug("Intent respondido: %s", texto)
        return respuesta
