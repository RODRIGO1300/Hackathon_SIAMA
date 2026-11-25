# Diccionario de datos (paquete SINTÉTICO de prueba)

> Estos datos son simulados para desarrollar el prototipo. Sustituir por el paquete oficial de SIAMA.

## estaciones.csv
| Campo | Descripción |
|---|---|
| clave | Clave de la estación (texto) |
| nombre, municipio | Identificación |
| latitud, longitud | Grados decimales (WGS84) |
| altitud | m s.n.m. |
| estado_operativo | `operando` / `suspendida` |

## series_diarias.csv
| Campo | Unidad |
|---|---|
| fecha | AAAA-MM-DD |
| clave | Clave de estación |
| precipitacion | mm/día |
| tmax, tmin | °C |

Valor faltante: `-99.9`.

## test_publico.csv
`fecha, clave, variable` a estimar. `_verdad_test_publico.csv` solo existe en el paquete sintético
para poder calificar localmente.
