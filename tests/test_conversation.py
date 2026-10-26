"""Prueba de extremo a extremo con el agente de conversación de Home Assistant.

Comprueba que la frase que diría Iñigo se reconoce y se responde con los
minutos, usando el agente local (sin IA) tal y como lo hace Assist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.bilbao_transit import async_setup


def _estado(hass: HomeAssistant, entity_id: str, minutos: int, **extra) -> None:
    atributos = {
        "network_key": "tram",
        "network": "Euskotren Tranvía Bilbao",
        "stop_name": "Bolueta",
        "direction_label": "La Casilla",
        "data_source": "realtime",
        "next_minutes": minutos,
        "next_departures": [
            {
                "minutes": minutos,
                "departure": "18:34",
                "line": "TR",
                "destination": "La Casilla",
                "trip_id": "1",
            }
        ],
    }
    atributos.update(extra)
    hass.states.async_set(entity_id, str(minutos), atributos)


async def _preparar(hass: HomeAssistant) -> None:
    hass.config.language = "es"
    # parte siempre de las frases que genera la integración
    for idioma in ("es", "en"):
        Path(hass.config.path("custom_sentences", idioma, "bilbao_transit.yaml")).unlink(
            missing_ok=True
        )
    assert await async_setup_component(hass, "homeassistant", {})
    await async_setup(hass, {})
    assert await async_setup_component(hass, "conversation", {})
    await hass.async_block_till_done()
    _estado(hass, "sensor.tram", 5)
    _estado(
        hass,
        "sensor.metro",
        12,
        network_key="metro",
        network="Metro Bilbao",
        direction_label="Bilbao (norte)",
    )
    _estado(
        hass,
        "sensor.bus",
        21,
        network_key="bizkaibus",
        network="Bizkaibus",
        direction_label="A3613 · BILBAO",
    )


async def _pregunta(hass: HomeAssistant, frase: str) -> str:
    resultado = await conversation.async_converse(
        hass, frase, None, Context(), language="es"
    )
    return resultado.response.speech["plain"]["speech"]


@pytest.mark.asyncio
async def test_frase_con_transporte(hass: HomeAssistant) -> None:
    """'¿Cuándo llega el tranvía?' -> 'sale en 5 minutos'."""
    await _preparar(hass)
    respuesta = await _pregunta(hass, "¿cuándo llega el tranvía?")
    assert "5 minutos" in respuesta, respuesta
    assert "La Casilla" in respuesta, respuesta


@pytest.mark.asyncio
async def test_frase_cuanto_falta(hass: HomeAssistant) -> None:
    """'¿Cuánto falta para el metro?' también entra."""
    await _preparar(hass)
    respuesta = await _pregunta(hass, "cuánto falta para el metro")
    assert "12 minutes" in respuesta or "12 minutos" in respuesta, respuesta


@pytest.mark.asyncio
async def test_frase_con_destino(hass: HomeAssistant) -> None:
    """'el próximo tranvía hacia La Casilla' usa el sentido."""
    await _preparar(hass)
    respuesta = await _pregunta(hass, "cuándo llega el próximo tranvía hacia La Casilla")
    assert "5 minutos" in respuesta, respuesta


@pytest.mark.parametrize(
    "frase",
    [
        "cuándo pasa el tren",
        "falta mucho para el bus",
        "dime el próximo tranvía",
        "qué hora es el próximo tranvía",
        "a qué hora sale el metro",
        "próximo bizkaibus",
        "cuándo viene el autobús",
        "el próximo metro a Bilbao",
        "cuánto falta para el próximo autobús",
        "dime cuándo llega el metro",
    ],
)
async def test_frases_normales(hass: HomeAssistant, frase: str) -> None:
    """Frases como las que se dicen de verdad, no solo la canónica."""
    await _preparar(hass)
    respuesta = await _pregunta(hass, frase)
    assert "no he entendido" not in respuesta.lower(), f"«{frase}» -> {respuesta}"
    assert "no conozco" not in respuesta.lower(), f"«{frase}» -> {respuesta}"
    assert "minuto" in respuesta.lower(), f"«{frase}» -> {respuesta}"
