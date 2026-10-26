"""Consulta de las próximas salidas sobre las entidades de la integración.

Lo usan tanto los intents de voz como la herramienta del LLM, para que la
respuesta hablada y la del asistente sean siempre la misma.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from homeassistant.core import HomeAssistant, State

TRANSPORTE_POR_RED = {
    "metro": "metro",
    "tram": "tranvía",
    "bizkaibus": "Bizkaibus",
    "bilbobus": "Bilbobus",
}

# palabras que el usuario dice -> claves de red
ALIAS_RED: dict[str, tuple[str, ...]] = {
    "metro": ("metro", "metrobilbao", "subte"),
    "tram": ("tranvia", "tram", "euskotren", "tranvia"),
    "bizkaibus": ("bizkaibus", "bizkaia"),
    "bilbobus": ("bilbobus",),
    "bus": ("bus", "autobus", "autobuses", "buses"),
}

BUSES = ("bizkaibus", "bilbobus")


def normaliza(texto: str | None) -> str:
    """Minúsculas y sin acentos, para comparar lo que dice el usuario."""
    if not texto:
        return ""
    plano = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in plano if not unicodedata.combining(c)).strip()


def red_desde_texto(texto: str | None) -> str | None:
    """Traduce 'el tranvía' / 'autobús' a la clave de red de la integración."""
    limpio = normaliza(texto)
    if not limpio:
        return None
    for red, alias in ALIAS_RED.items():
        if any(limpio == a or limpio in a or a in limpio for a in alias):
            return red
    return None


def _sin_linea(texto: str | None, linea: str | None) -> str:
    """'A3613 · BILBAO' + línea A3613 -> 'BILBAO' (sin repetir la línea al hablar)."""
    if not texto:
        return ""
    if linea and texto.startswith(linea):
        limpio = texto[len(linea) :].lstrip(" ·-").strip()
        return limpio or texto
    return texto


def _salida(estado: State, salida: dict[str, Any]) -> dict[str, Any]:
    atributos = estado.attributes
    linea = salida.get("line")
    direccion = _sin_linea(atributos.get("direction_label"), linea)
    return {
        "entity_id": estado.entity_id,
        "network_key": atributos.get("network_key"),
        "network": TRANSPORTE_POR_RED.get(atributos.get("network_key"), atributos.get("network")),
        "stop_name": atributos.get("stop_name"),
        "direction": direccion,
        "minutes": salida.get("minutes"),
        "departure": salida.get("departure"),
        "line": salida.get("line"),
        "destination": _sin_linea(salida.get("destination"), linea) or direccion,
        "realtime": atributos.get("data_source") == "realtime",
    }


def departures(
    hass: HomeAssistant,
    network: str | None = None,
    sentido: str | None = None,
) -> list[dict[str, Any]]:
    """Todas las próximas salidas, ordenadas de la más cercana a la más lejana.

    ``network`` acepta una clave suelta ('metro', 'tram', ...) o 'bus' para
    agrupar Bizkaibus y Bilbobus. ``sentido`` es texto libre que se busca en el
    sentido o en la parada.
    """
    aguja = normaliza(sentido)
    filas: list[dict[str, Any]] = []
    for estado in hass.states.async_all("sensor"):
        atributos = estado.attributes
        clave = atributos.get("network_key")
        salidas = atributos.get("next_departures")
        if not clave or not salidas:
            continue
        if network == "bus":
            if clave not in BUSES:
                continue
        elif network and clave != network:
            continue
        if aguja:
            texto = normaliza(f"{atributos.get('direction_label')} {atributos.get('stop_name')}")
            if aguja not in texto:
                continue
        filas.append(_salida(estado, salidas[0]))

    filas.sort(key=lambda fila: fila["minutes"] if fila["minutes"] is not None else 9999)
    return filas


def describe(fila: dict[str, Any], language: str = "es") -> str:
    """Frase corta y natural: 'el metro hacia Bilbao en 5 minutos (18:34)'."""
    minutos = fila["minutes"]
    transporte = fila["network"] or "transporte"
    direccion = fila["direction"] or fila["destination"] or ""
    linea = f" ({fila['line']})" if fila["line"] else ""
    if minutos is None:
        return f"{transporte} hacia {direccion}"
    if language.startswith("es"):
        if minutos == 0:
            cuando = "ahora mismo"
            # decir "ahora mismo, a las 19:22" suena a contradecirse
            hora = f" ({fila['departure']})" if fila.get("departure") else ""
        else:
            cuando = "en 1 minuto" if minutos == 1 else f"en {minutos} minutos"
            hora = f", a las {fila['departure']}" if fila.get("departure") else ""
        return f"el {transporte}{linea} hacia {direccion} sale {cuando}{hora}"
    if minutos == 0:
        cuando = "right now"
        hora = f" ({fila['departure']})" if fila.get("departure") else ""
    else:
        cuando = "in 1 minute" if minutos == 1 else f"in {minutos} minutes"
        hora = f", at {fila['departure']}" if fila.get("departure") else ""
    return f"the {transporte}{linea} towards {direccion} leaves {cuando}{hora}"
