# Bilbao Transit para Home Assistant

Próximas salidas **en tiempo real** del **Metro Bilbao** y del **tranvía de Bilbao**
(Euskotren Tranbia) como sensores nativos de Home Assistant.

Un sensor = una parada + un sentido. El estado es **los minutos que faltan** para
la próxima salida; los atributos llevan las siguientes salidas, el destino y la
hora exacta de paso.

```
sensor.bolueta_metro_a_kabiezes        3   → destino: Kabiezes, 09:45
sensor.bolueta_metro_a_basauri         4
sensor.bolueta_tranvia_a_la_casilla    6
```

## Instalación

### HACS (recomendado)

1. HACS → menú → **Repositorios personalizados**.
2. Añade `https://github.com/RickAndMe/ha-bilbao-transit` con tipo **Integration**.
3. Instala **Bilbao Transit** y reinicia Home Assistant.

### Manual

Copia la carpeta `custom_components/bilbao_transit` a `config/custom_components/`
y reinicia Home Assistant.

## Configuración

**Ajustes → Dispositivos y servicios → Añadir integración → Bilbao Transit**

1. Elige la red: *Metro Bilbao* o *Euskotren Tranvía Bilbao*.
2. Elige la parada: la lista viene **ordenada por distancia** a la ubicación
   configurada en Home Assistant (la de `zone.home` / Ajustes → General).
3. Marca los sentidos que quieres. Cada uno genera un sensor.

Repite el proceso para añadir más paradas (por ejemplo metro y tranvía de la misma
estación). Los sentidos y el nombre de las entidades se pueden cambiar después
con **Configurar** en la tarjeta de la integración, o renombrando la entidad.

## Entidades

| Entidad | Estado | Atributos principales |
| --- | --- | --- |
| `sensor.<parada>_a_<destino>` | minutos al próximo (o `unknown` si no hay servicio) | `next_departures` (hora, minutos, destino), `destination`, `service_status`, `feed_updated` |

Actualización: cada 45 segundos (el feed oficial se refresca cada ~30 s).
El horario estático se descarga una vez cada 12 h y se cachea en memoria.

## Ejemplo de tarjeta

```yaml
type: entities
title: Bolueta
entities:
  - entity: sensor.bolueta_metro_a_kabiezes
    name: Metro a Bilbao
  - entity: sensor.bolueta_metro_a_basauri
    name: Metro a Basauri
  - entity: sensor.bolueta_tranvia_a_la_casilla
    name: Tranvía al centro
```

Para ver las siguientes salidas en una tarjeta, usa el atributo:

```yaml
type: markdown
content: >
  {% set d = state_attr('sensor.bolueta_metro_a_kabiezes', 'next_departures') %}
  {% for dep in d %}{{ dep.departure }} · {{ dep.headsign }} · {{ dep.minutes }} min
  {% endfor %}
```

## Cómo funciona (y límites)

- **Fuentes**: datos abiertos oficiales, sin API key.
  - Metro Bilbao: GTFS-RT y GTFS del Consorcio de Transportes de Bizkaia
    (<https://data.ctb.eus>), licencia CC-BY-4.0.
  - Tranvía: GTFS-RT y GTFS de Euskotren dentro de Moveuskadi
    (<https://opendata.euskadi.eus>).
- El feed GTFS-RT del metro **no incluye la dirección** del viaje: la integración
  cruza cada `trip_id` en tiempo real con el horario estático para conocer
  destino y sentido. Sin ese cruce, un sensor por parada mezclaría ambos andenes.
- No hay dependencias externas: el protobuf de GTFS-RT se decodifica con un
  parser propio de ~100 líneas.
- El feed en tiempo real solo publica los trenes próximos (30-40 min de vista).
  Fuera de ese margen, o cuando no hay servicio (noche), el sensor queda en
  `unknown` con `service_status: sin servicio`.
- Los tiempos son estimaciones del operador, no el horario teórico: pueden
  cambiar entre refrescos.

## Desarrollo

```bash
pip install -r requirements_test.txt
pytest -q                     # tests unitarios y de flujo (8 tests, sin red)
```

Comprobación contra los feeds oficiales reales (requiere red):

```bash
python3 scripts/check_feeds.py
```
