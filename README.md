# Agro SIAMA · Prototipo agroclimático para SIAMA

[Pitch de cinco minutos · Agro SIAMA y el sector agrícola](docs/pitch/README.md)

Módulo para SIAMA Web que **detecta vacíos** en las series diarias de estaciones climatológicas de Guanajuato,
**los rellena** con métodos estadísticos y de machine learning, y entrega **cada dato estimado con su intervalo
de incertidumbre y su bandera de calidad**. Ningún dato estimado se presenta como observado.

> ⚠️ El prototipo trae un **paquete de datos sintético** con el mismo formato que el paquete oficial
> (`estaciones.csv`, `series_diarias.csv`, `test_publico.csv`, `diccionario_datos.md`). Al recibir los datos
> reales basta con colocarlos en `datos/` y volver a ejecutar el pipeline.

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
```

## Uso (un solo comando)

```bash
python -m siama_gaps run --datos datos --salida salidas      # datos oficiales
python -m siama_gaps todo                                    # genera datos sintéticos + ejecuta
python -m siama_gaps limpiar --datos datos --salida salidas  # solo la limpieza y su reporte
```

Luego la API y la demo:

```bash
uvicorn api.main:app --reload
```

- Demo del componente incrustado: http://localhost:8000/web/demo.html
- **Clima para el campo** (vista para productores, Salamanca): http://localhost:8000/agro
- Documentación OpenAPI: http://localhost:8000/docs

Con Docker: `docker build -t siama-huecos . && docker run -p 8000:8000 siama-huecos`

## Datos reales de Salamanca (SMN · CLICOM)

`datos/dia11096.txt` (Salamanca) y `datos/dia11136.txt` (La Joyita) son los archivos diarios originales del Servicio
Meteorológico Nacional. El comando `clicom` los convierte al formato de entrada, sin modificar los valores:

```powershell
python -m siama_gaps clicom datos/dia11096.txt datos/dia11136.txt --destino datos_salamanca --desde 1981
python -m siama_gaps run --datos datos_salamanca --salida salidas_salamanca
$env:SIAMA_SALIDAS = "salidas_salamanca"; uvicorn api.main:app --reload    # la API sirve los datos reales
```

Luego abre http://localhost:8000/agro: un tablero pensado para productores, con una frase de resumen, cuatro
indicadores tipo semáforo y gráficas que responden preguntas («¿Cuánto llovió cada mes?», «¿En qué meses puede helar?»).
Tiene dos filtros: **Temporada** (ciclo agrícola: Primavera-Verano, siembras de marzo a septiembre, u Otoño-Invierno, de octubre a febrero; siempre el ciclo más reciente) y **Mes**. Con un mes elegido muestra ese mes contra un mes normal y «¿Qué se puede sembrar?»: los cultivos de esa época según un calendario de referencia del Bajío (`siama_gaps/cultivos.py`), evaluados con el riesgo de helada y la lluvia de la estación.
Siempre abre en el año y la fecha más recientes disponibles.

**Mantener los datos al día.** El comando `actualizar` descarga del SMN los archivos más recientes de las estaciones del
paquete y, solo si cambiaron, vuelve a correr todo el proceso; la API toma los resultados nuevos sin reiniciarse.
Si no hay internet o el SMN no responde, los datos actuales no se tocan.

```powershell
python -m siama_gaps actualizar                       # usa datos_salamanca y salidas_salamanca
# Revisarlo todos los días a las 6:00 con el Programador de tareas de Windows:
schtasks /create /tn "SIAMA actualizar" /sc daily /st 06:00 /tr "cmd /c cd /d C:\ruta\del\proyecto && .venv\Scripts\python.exe -m siama_gaps actualizar"
```

El SMN publica su base histórica con varios meses de retraso (la publicación del 20/11/2026 llega al 31/12/2025);
el tablero lo explica y muestra siempre hasta qué fecha llegan los datos.
`datos/clicom_gto_salamanca_lajoyita_1981_2025.csv` coincide valor por valor con los `.txt` en 1981–2025; la
limpieza también acepta ese formato (renombra `clave_estacion`, `precip_mm`, `tmax_c`, `tmin_c`).

Lo que se encontró en los datos reales (ver `salidas_salamanca/`):
- Los huecos son días que **no aparecen** en el archivo (4 % en Salamanca y 11 % en La Joyita desde 1981; La Joyita
  no tiene 2007 ni 2021), no `NULO`.
- Las temperaturas son lecturas manuales redondeadas a 0.5–1 °C y la diferencia entre ambas estaciones cambia con los
  años (posibles cambios de instrumento o ubicación). Su correlación en anomalías (0.41–0.54) no alcanza el mínimo de
  0.60, así que **la temperatura no se rellena con la estación vecina** y los huecos de más de 3 días quedan como no
  estimables. Los indicadores agrícolas lo informan como «datos insuficientes» en vez de dar una cifra engañosa.

## Mapa de Guanajuato (todas las estaciones del SMN)

El paquete `datos_guanajuato/` reúne las estaciones climatológicas del SMN en Guanajuato (162 publicadas; entran las
145 con al menos 5 años de datos desde 1981). Se descargan y procesan así:

```powershell
python -c "from siama_gaps import clicom; clicom.descargar_estado('datos_guanajuato/originales', [str(c) for c in range(11001, 11201)])"
python -m siama_gaps clicom datos_guanajuato/originales/dia*.txt --destino datos_guanajuato --desde 1981 --min-dias 1826
python -m siama_gaps run --datos datos_guanajuato --salida salidas_guanajuato
$env:SIAMA_SALIDAS = "salidas_guanajuato"; uvicorn api.main:app --reload
python -m siama_gaps actualizar          # después: trae lo más reciente del SMN (por defecto, este paquete)
```

El tablero `/agro` muestra un **mapa con 4 capas**, una a la vez: «¿Dónde llovió?» (lluvia contra lo normal),
«¿Dónde hizo calor?» (temperatura de la tarde contra lo normal), «¿Dónde heló?» (días con helada) y «¿Dónde faltó
agua?» (lluvia menos el agua que pierde el cultivo). Siguen los filtros de temporada y mes. Los puntos son las
estaciones (lo medido); el color entre ellas es **estimado** por distancia inversa (`siama_gaps/mapa.py`) y no se
pinta a más de 25 km de una estación. La interpolación no usa el relieve. API: `GET /api/v1/agro/mapa?ciclo=&inicio=&mes=`.

## Tecnologías de IBM (opcionales)

Guía completa: [`ibm/README.md`](ibm/README.md). Sin credenciales, el prototipo funciona igual.

| Tecnología | Uso en el prototipo |
|---|---|
| **watsonx.ai · IBM Granite** | El asistente de IA redacta el resumen de cada estación y responde preguntas (`/resumen`, `/preguntar`) usando solo los datos del pipeline |
| **IBM Cloud Databases for PostgreSQL** (PostGIS) | `python -m siama_gaps postgres` carga los resultados; con `SIAMA_DATABASE_URL`, la API lee de la base |
| **IBM Cloud Code Engine** | `ibm\code-engine\desplegar.ps1` publica la demo y la API en una URL pública a partir del `Dockerfile` |
| **IBM Carbon Design System** | Estilo de la demo (IBM Plex, tokens g10) y tema opcional del componente: `tema="carbon"` |

```powershell
copy .env.example .env                          # credenciales de IBM Cloud (no se sube a git)
.venv\Scripts\pip.exe install -r requirements-ibm.txt
.venv\Scripts\python.exe -m api.watsonx          # prueba la conexión con watsonx.ai
```

## Flujo de etapas

| Etapa | Módulo | Qué hace |
|---|---|---|
| 0. Limpieza de datos | `limpieza.py` | Corrige problemas de formato antes de todo: fechas en otro formato o ilegibles, claves con espacios, texto en campos numéricos, decimales con coma, lluvia «inapreciable» (trazas → 0 mm), códigos de faltante (-99.9, -999…), filas duplicadas (las contradictorias quedan como faltante), estaciones desconocidas, coordenadas invertidas o sin signo. Todo queda en `limpieza_reporte.md` |
| 1. Diagnóstico | `diagnostico.py` | % faltante, longitud y fecha de cada hueco, clasificación corto (1–3), medio (4–30), largo (>30), % faltante por año |
| 2. Control de calidad | `calidad.py` | Precipitación negativa o extrema, temperatura fuera de rango físico, Tmax < Tmin, atípicos robustos (mediana/MAD por mes), sensor trabado, rachas de ceros sospechosos en temporada de lluvias. Lo marcado se retira y queda registrado en `qc_banderas.csv` |
| 3. Relleno | `vecinos.py`, `relleno.py` | Vecinos por **radio máximo + correlación mínima**; líneas base (interpolación lineal, IDW, razón/diferencia normal); gradient boosting con vecinos, altitud y estacionalidad; precipitación en dos etapas (ocurrencia + cantidad); ensamble ponderado por KGE; **selección automática del método por tipo de hueco**; intervalos **conformales** al 90 % |
| 4. Integración | `api/main.py`, `web/siama-huecos.js` | API REST + componente web `<siama-huecos>` que se incrusta con una etiqueta |
| 5. Agro | `agro.py`, `web/agro.html` | Indicadores para productores sobre la serie completada: lluvia de temporada vs. promedio, inicio de lluvias, racha seca, heladas, grados día del cultivo, evapotranspiración (Hargreaves) y balance de agua, cada uno con su % de días medidos |

Extras incluidos: bandera de calidad (observado / estimado alta / estimado baja / no estimable), recomendación de método
según longitud del hueco, prueba de homogeneidad de Pettitt, Dockerfile y endpoint de resumen para el asistente de IA.

## Salidas (`salidas/`)

| Archivo | Contenido |
|---|---|
| `series_completadas.csv.gz` | fecha, clave, variable, valor, li, ls, origen, bandera, metodo, motivo_no_estimable, qc |
| `predicciones_test_publico.csv` | estimado, limite_inferior, limite_superior por fila de `test_publico.csv` |
| `diagnostico_estaciones.csv`, `huecos.csv`, `diagnostico_anual.csv` | Diagnóstico de vacíos |
| `limpieza_reporte.md`, `limpieza_registro.csv`, `limpieza_detalle.csv` | Correcciones de formato de la etapa 0 (resumen y fila por fila) |
| `qc_banderas.csv` | Valores retirados por control de calidad y regla aplicada |
| `agro_indicadores.csv` | Indicadores agroclimáticos por estación y temporada |
| `vecinos.csv` | Vecinos usados por estación/variable (distancia, dif. de altitud, correlación) |
| `homogeneidad.csv` | Cambios abruptos detectados |
| `metricas.json`, `reporte_metricas.md` | MAE, RMSE, BIAS, KGE, POD/FAR, cobertura por variable × tipo de hueco × método |

## API

| Endpoint | Descripción |
|---|---|
| `GET /api/v1/estaciones/{clave}/diagnostico` | **Obligatorio.** Vacíos, huecos, vecinos usados, QC y homogeneidad |
| `GET /api/v1/estaciones/{clave}/serie?variable=&desde=&hasta=` | **Obligatorio.** Serie completada con `origen`, `bandera`, `li`, `ls`, `metodo` |
| `GET /api/v1/metricas?variable=&clase=&metodo=` | **Obligatorio.** Métricas del modelo vs. línea base |
| `GET /api/v1/estaciones` | GeoJSON con % de vacíos por variable (para el mapa) |
| `GET /api/v1/estaciones/{clave}/resumen` | Texto en lenguaje natural (asistente de IA de SIAMA); lo redacta IBM Granite si watsonx.ai está configurado |
| `GET /api/v1/estaciones/{clave}/preguntar?q=` | Pregunta libre sobre la estación, respondida por IBM Granite (requiere watsonx.ai) |
| `GET /api/v1/agro/estaciones?municipio=` | Estaciones para la vista agrícola (p. ej. `Salamanca`) |
| `GET /api/v1/agro/{clave}?anio=&siembra=&hasta=` | Indicadores agroclimáticos de una temporada, con gráficas semanales e histórico |
| `GET /api/v1/salud` | Estado: fuente de datos (archivos o PostgreSQL) y configuración de watsonx.ai |

## Estructura

```
siama_gaps/   pipeline (config, utils, calidad, diagnostico, vecinos, relleno, homogeneidad, metricas, sinteticos)
api/          FastAPI (+ watsonx.py: cliente de watsonx.ai / IBM Granite)
ibm/          guía de IBM Cloud y scripts de despliegue en Code Engine
web/          componente web embebible + demo
datos/        paquete de entrada (sintético por ahora)
salidas/      resultados (se regeneran)
ficha_tecnica.md
```

## Licencia

MIT. Solo bibliotecas de código abierto (numpy, pandas, scipy, scikit-learn, FastAPI, Leaflet, Plotly).
#   H a c k a t h o n _ S I A M A 
 
 #   H a c k a t h o n _ S I A M A 
 
 #   H a c k a t h o n _ S I A M A 
 
 
