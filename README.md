# Bilbao Transit para Home Assistant

Próximas salidas del **Metro Bilbao**, el **tranvía de Bilbao** (Euskotren Tranbia),
**Bizkaibus** y **Bilbobus** como sensores nativos de Home Assistant.

Un sensor = una parada + un sentido (y, en los buses, una línea). El estado es **los
minutos que faltan** para la próxima salida; los atributos llevan las siguientes salidas,
el destino final, la línea y la hora exacta de paso.

```
sensor.bolueta_metro_bilbao_hacia_bilbao_norte           3   → L2 Kabiezes 09:45
sensor.bolueta_metro_bilbao_hacia_basauri_etxarri_sur    4   → L1 Etxebarri 09:46
sensor.bolueta_euskotren_tranvia_bilbao_hacia_la_casilla 6
sensor.metro_bolueta_bizkaibus_a3613_ugao_miraballes     8   → A3613 OROZKO 09:50
```

## Redes y calidad del dato

| Red | Horario oficial | Tiempo real | Notas |
| --- | --- | --- | --- |
| Metro Bilbao | sí | **sí** (estimaciones) | el feed no trae sentido ni línea: se deducen del horario |
| Euskotren Tranvía | sí | **sí** (estimaciones) | el feed sí distingue andén |
| Bizkaibus | sí | **sí, pero parcial** | el feed solo publica la **próxima parada** de cada bus, así que verás el que está llegando; el resto sale del horario |
| Bilbobus | sí | **no** | solo publica posiciones de vehículos (a menudo vacías). Va con horario programado y el sensor lo indica (`service_status: horario (sin tiempo real)`) |

Cuando hay dato real, el sensor se marca `ok` y usa la estimación oficial. Si no, cae al
horario programado y lo dice en `data_source` (`realtime` / `schedule`) para que nunca
confundas una cosa con la otra.

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

1. Elige la red: *Metro Bilbao*, *Euskotren Tranvía Bilbao*, *Bizkaibus* o *Bilbobus*.
2. Elige la parada: la lista viene **ordenada por distancia** a la ubicación
   configurada en Home Assistant (la de `zone.home` / Ajustes → General); la primera
   es la más cercana.
3. **En los buses**, elige las líneas que paran ahí (varias a la vez si quieres).
4. Marca los sentidos que quieres. Cada uno genera un sensor.

Repite el proceso para añadir más paradas (por ejemplo metro y tranvía de la misma
estación). Los sentidos y el nombre de las entidades se pueden cambiar después
con **Configurar** en la tarjeta de la integración, o renombrando la entidad.

Ojo con los buses: en Bizkaibus y Bilbobus cada sentido de la calle suele ser una
parada distinta en el GTFS (p. ej. *METRO BOLUETA (290)* y *(285)*), así que para tener
los dos sentidos hay que dar de alta las dos paradas.

## Entidades

| Entidad | Estado | Atributos principales |
| --- | --- | --- |
| `sensor.<parada>_hacia_<sentido>` | minutos al próximo (o `unknown` si no hay servicio) | `next_departures` (hora, minutos, destino y línea de cada salida), `destination`, `service_status`, `feed_updated` |

**Los sentidos se nombran por su significado, no por un destino concreto.** En Metro
Bilbao un tren hacia el norte puede terminar en Kabiezes (L2) o en Plentzia, Bidezabal,
Sopela, Urduliz, Larrabasterra, Ibarbengoa, San Ignazio (L1), así que el sensor se llama
*hacia Bilbao (norte)* y **cada salida lleva su destino final y su línea**. La línea se
deduce del origen del viaje en el horario oficial: la L1 sale de Etxebarri y la L2 de
Basauri.

Actualización: cada 45 segundos (el feed oficial se refresca cada ~30 s).
El horario estático se descarga una vez cada 12 h y se cachea en memoria.

## Tarjeta con las 3 próximas salidas

El estado del sensor es solo el próximo bus/tren; los siguientes van en el atributo
`next_departures`. Esta tarjeta **descubre sola todas las entidades de la integración**
(así los buses que añadas después aparecen sin tocar nada) y pinta las 3 próximas de
cada una, con hora, línea, destino y minutos:

```yaml
type: markdown
title: Bolueta
content: |
  {%- set entidades = states.sensor | selectattr('attributes.network', 'defined')
       | selectattr('attributes.next_departures', 'defined') | list -%}
  {%- for e in entidades | sort(attribute='attributes.stop_name') %}
  {%- set salidas = (e.attributes.next_departures or [])[:3] %}
  {%- if salidas %}

  **{{ e.name }}**
  {% for s in salidas -%}
  · {{ s.departure }} · {{ s.line ~ ' ' if s.line }}{{ s.destination or s.headsign }} — **{{ s.minutes }} min**
  {% endfor %}
  {%- endif %}
  {%- endfor %}
```

Si prefieres una lista clásica de entidades (solo el próximo), sirve `type: entities`
con cada sensor.

## Cómo funciona (y límites)

- **Fuentes**: datos abiertos oficiales, sin API key.
  - Metro Bilbao: GTFS-RT y GTFS del Consorcio de Transportes de Bizkaia
    (<https://data.ctb.eus>), licencia CC-BY-4.0.
  - Tranvía: GTFS-RT y GTFS de Euskotren dentro de Moveuskadi
    (<https://opendata.euskadi.eus>).
- El feed GTFS-RT del metro **no incluye la dirección** del viaje: la integración
  cruza cada `trip_id` en tiempo real con el horario estático para conocer
  destino y sentido. Sin ese cruce, un sensor por parada mezclaría ambos andenes.
- La línea (L1/L2) tampoco viene en el feed: se deduce del **origen** del viaje en el
  horario estático (Basauri ⇒ L2, Etxebarri ⇒ L1) y, si el origen es una estación
  intermedia, del destino final.
- No hay dependencias externas: el protobuf de GTFS-RT se decodifica con un
  parser propio de ~100 líneas.
- El GTFS de Bizkaibus tiene 35 MB de `stop_times`: la integración **solo guarda las
  paradas que has dado de alta** (unos 35 MB de lectura, ~35 MB de pico de memoria), y
  cachea el zip descargado media hora para no bajarlo dos veces en el mismo alta.
- El horario programado (respaldo de todas las redes y única fuente en Bilbobus) se
  calcula con `calendar.txt`/`calendar_dates.txt`, así que respeta laborables, sábados,
  domingos y festivos.
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
