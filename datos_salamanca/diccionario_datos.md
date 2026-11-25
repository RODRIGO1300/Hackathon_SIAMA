# Diccionario de datos (paquete OFICIAL convertido de CLICOM)

Origen: SMN · Base de Datos Climatológica Nacional (CLICOM). Emisión: 20/11/2026. Archivos: dia11096.txt, dia11136.txt.
Generado con `python -m siama_gaps clicom`. Los valores se copian sin modificar; la limpieza (etapa 0) los procesa.

| Clave | Estación | Periodo usado | Filas | Días que no aparecen | NULO (lluvia / Tmax / Tmin) |
|---|---|---|---|---|---|
| 11096 | SALAMANCA | 1981-05-01 a 2025-12-31 | 15,733 | 583 | 1 / 13 / 13 |
| 11136 | LA JOYITA | 1981-01-01 a 2025-07-31 | 14,707 | 1,576 | 1 / 72 / 72 |

## estaciones.csv
clave, nombre, municipio, latitud, longitud (grados decimales), altitud (m s.n.m.), estado_operativo.

## series_diarias.csv
| Campo | Unidad |
|---|---|
| fecha | AAAA-MM-DD |
| clave | Clave de estación |
| precipitacion | mm/día |
| evaporacion | mm/día (tanque evaporímetro; no la usa el relleno) |
| tmax, tmin | °C |

Valor faltante: `NULO` (como en el archivo original) o día ausente.
