"""Tests de la voz: frases, intent y herramienta del asistente con IA."""

from __future__ import annotations

from pathlib import Path

import pytest

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent as intent_helper
from homeassistant.helpers import llm

from custom_components.bilbao_transit import FRONTEND_KEY, async_setup
from custom_components.bilbao_transit.intents import NextDepartureIntent
from custom_components.bilbao_transit.llm_api import BilbaoTransitAPI
from custom_components.bilbao_transit.queries import (
    departures,
    describe,
    red_desde_texto,
)
from custom_components.bilbao_transit.sentences import async_ensure_sentences


def _estado(hass, entity_id, minutos, **extra):
    atributos = {
        "network_key": "tram",
        "network": "Euskotren Tranvía Bilbao",
        "stop_name": "Bolueta",
        "direction_label": "La Casilla",
        "data_source": "realtime",
        "next_minutes": minutos,
        "next_departures": [
            {"minutes": minutos, "departure": "18:34", "line": "TR", "destination": "La Casilla", "trip_id": "1"}
        ],
    }
    atributos.update(extra)
    hass.states.async_set(entity_id, str(minutos), atributos)


def test_red_desde_texto() -> None:
    """Lo que dice el usuario se traduce a la clave de red."""
    assert red_desde_texto("tranvía") == "tram"
    assert red_desde_texto("TRANVIA") == "tram"
    assert red_desde_texto("el metro") == "metro"
    assert red_desde_texto("bizkaibus") == "bizkaibus"
    assert red_desde_texto("bilbobus") == "bilbobus"
    assert red_desde_texto("autobús") == "bus"
    assert red_desde_texto("") is None
    assert red_desde_texto(None) is None


@pytest.mark.asyncio
async def test_departures_filtra_y_ordena(hass: HomeAssistant) -> None:
    """Agrupa por red, busca en el sentido y ordena por cercanía."""
    _estado(hass, "sensor.tram", 7)
    _estado(hass, "sensor.tram_sur", 3, direction_label="Bolueta")
    _estado(hass, "sensor.metro", 2, network_key="metro", network="Metro Bilbao",
            direction_label="Bilbao (norte)", stop_name="Bolueta (Metro)")
    _estado(hass, "sensor.bus", 12, network_key="bizkaibus", network="Bizkaibus",
            direction_label="A3613 · BILBAO", stop_name="METRO BOLUETA (285)")

    assert [f["minutes"] for f in departures(hass)] == [2, 3, 7, 12]
    assert [f["minutes"] for f in departures(hass, network="tram")] == [3, 7]
    assert [f["minutes"] for f in departures(hass, network="bus")] == [12]
    assert [f["minutes"] for f in departures(hass, sentido="la casilla")] == [7]
    # el filtro busca también en el destino: "Bilbao" es del metro y del bus
    assert [f["minutes"] for f in departures(hass, sentido="bilbao")] == [2, 12]


def test_describe_en_castellano() -> None:
    """La frase que se oye."""
    fila = {
        "network": "tranvía",
        "direction": "La Casilla",
        "destination": "La Casilla",
        "minutes": 5,
        "departure": "18:34",
        "line": "TR",
    }
    assert describe(fila) == "el tranvía (TR) hacia La Casilla sale en 5 minutos, a las 18:34"
    assert "1 minuto" in describe({**fila, "minutes": 1})
    assert "ahora mismo" in describe({**fila, "minutes": 0})


@pytest.mark.asyncio
async def test_intent_responde_los_minutos(hass: HomeAssistant) -> None:
    """El intent dice cuánto falta y a qué hora."""
    _estado(hass, "sensor.tram", 5)
    handler = NextDepartureIntent()
    peticion = intent_helper.Intent(
        hass,
        intent_type="BilbaoTransitNextDeparture",
        platform="test",
        slots={"transporte": {"value": "tranvía"}},
        text_input="cuándo llega el tranvía",
        context=Context(),
        language="es",
    )
    respuesta = await handler.async_handle(peticion)
    discurso = respuesta.speech["plain"]["speech"]
    assert "tranvía" in discurso
    assert "5 minutos" in discurso
    assert "18:34" in discurso


@pytest.mark.asyncio
async def test_intent_sin_servicio(hass: HomeAssistant) -> None:
    """Sin entidades avisa en vez de inventar."""
    handler = NextDepartureIntent()
    peticion = intent_helper.Intent(
        hass,
        intent_type="BilbaoTransitNextDeparture",
        platform="test",
        slots={"transporte": {"value": "metro"}},
        text_input="cuándo llega el metro",
        context=Context(),
        language="es",
    )
    respuesta = await handler.async_handle(peticion)
    assert "no tengo salidas" in respuesta.speech["plain"]["speech"].lower()


@pytest.mark.asyncio
async def test_llm_tool_devuelve_resumen(hass: HomeAssistant) -> None:
    """La herramienta da al LLM un resumen y los datos."""
    hass.config.language = "es"
    _estado(hass, "sensor.tram", 5)
    _estado(hass, "sensor.metro", 9, network_key="metro", network="Metro Bilbao", direction_label="Bilbao (norte)")

    api = BilbaoTransitAPI(hass)
    contexto = llm.LLMContext(
        platform="test",
        context=Context(),
        language="es",
        assistant=None,
        device_id=None,
    )
    instancia = await api.async_get_api_instance(contexto)
    herramienta = instancia.tools[0]
    assert herramienta.name == "bilbao_transit_next_departures"

    resultado = await herramienta.async_call(
        hass,
        llm.ToolInput(tool_name=herramienta.name, tool_args={"transporte": "tranvía"}),
        contexto,
    )
    assert resultado["success"] is True
    assert "5 minutos" in resultado["result"]["summary"]
    assert len(resultado["result"]["departures"]) == 1
    assert resultado["result"]["departures"][0]["realtime"] is True


@pytest.mark.asyncio
async def test_frases_se_escriben_solo_una_vez(hass: HomeAssistant) -> None:
    """Deja las frases en config sin pisar lo que edite el usuario."""
    previo = Path(hass.config.path("custom_sentences", "es", "bilbao_transit.yaml"))
    previo.unlink(missing_ok=True)
    await async_ensure_sentences(hass)
    fichero = Path(hass.config.path("custom_sentences", "es", "bilbao_transit.yaml"))
    assert fichero.is_file()
    assert "BilbaoTransitNextDeparture" in fichero.read_text(encoding="utf-8")

    original = fichero.read_text(encoding="utf-8")
    fichero.write_text("# mío\nlanguage: es\n", encoding="utf-8")
    await async_ensure_sentences(hass)
    assert fichero.read_text(encoding="utf-8") == "# mío\nlanguage: es\n"
    # deja el entorno como estaba para no romper los tests de conversación
    fichero.write_text(original, encoding="utf-8")


@pytest.mark.asyncio
async def test_setup_registra_tarjeta_y_voz(hass: HomeAssistant) -> None:
    """async_setup deja todo listo una sola vez."""
    assert await async_setup(hass, {}) is True
    assert hass.data[FRONTEND_KEY]["voice"] is True
    assert "bilbao_transit_llm" in {api.id for api in llm.async_get_apis(hass)}
    assert NextDepartureIntent.intent_type in {
        handler.intent_type for handler in intent_helper.async_get(hass)
    }

    await async_setup(hass, {})
    assert hass.data[FRONTEND_KEY]["voice"] is True


@pytest.mark.asyncio
async def test_tarjeta_se_sirve_por_http(hass: HomeAssistant, monkeypatch) -> None:
    """Con HTTP en marcha, la tarjeta se publica y se añade al frontend."""
    import custom_components.bilbao_transit as integracion

    registradas: list = []
    urls: list = []

    async def _fake_static_paths(rutas):
        registradas.extend(rutas)

    monkeypatch.setattr(hass, "http", type("H", (), {"async_register_static_paths": staticmethod(_fake_static_paths)})(), raising=False)
    monkeypatch.setattr(
        "homeassistant.components.frontend.add_extra_js_url",
        lambda _hass, url: urls.append(url),
    )

    hass.config.components.add("http")
    await integracion._async_register_card(hass)

    assert urls == [integracion.CARD_URL]
    assert registradas and registradas[0].path == str(integracion.FRONTEND_DIR)
    assert (integracion.FRONTEND_DIR / "bilbao-transit-card.js").is_file()

    # una segunda llamada no duplica el recurso
    await integracion._async_register_card(hass)
    assert urls == [integracion.CARD_URL]
