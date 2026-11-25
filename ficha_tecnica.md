# Ficha técnica de Agro SIAMA · Relleno de huecos climatológicos para SIAMA (borrador)

> Las cifras de esta versión provienen del **paquete sintético** de prueba. Se actualizan automáticamente en
> `salidas/reporte_metricas.md` al ejecutar el pipeline con los datos oficiales.

## 1. Objetivo
Completar las series diarias de **precipitación, Tmax y Tmin** de las estaciones de Guanajuato, declarando para cada
valor estimado un **intervalo del 90 %** y una **bandera de calidad**, y negarse a rellenar cuando no hay sustento.

## 2. Método
0. **Limpieza de formato.** Antes de cualquier cálculo se normalizan fechas, claves y números (coma decimal,
   códigos -99.9/-999, trazas «Inap» = 0 mm), se combinan filas duplicadas (si se contradicen, el valor queda faltante)
   y se corrigen coordenadas invertidas o sin signo. Cada corrección queda registrada (`limpieza_reporte.md`).
1. **Control de calidad previo.** Se retiran (y registran) precipitación < 0 o > 300 mm, temperaturas fuera de
   [-15, 48] °C, Tmax < Tmin, atípicos con |z robusto| > 5 por estación y mes, valores idénticos ≥ 6 días seguidos y
   rachas ≥ 20 días de ceros en jun–sep cuando la mediana regional sí registra lluvia.
2. **Selección de vecinos.** Hasta 6 estaciones a ≤ 120 km con correlación ≥ 0.60 (temperatura, en anomalías) o
   ≥ 0.35 (precipitación, raíz cúbica), con ≥ 365 días de traslape, **ordenadas por correlación** (Tang et al., 2020).
3. **Métodos candidatos.**
   - Líneas base: interpolación lineal (propia serie), IDW, razón normal (precipitación) / diferencia normal (temperatura).
   - ML: gradient boosting (scikit-learn) con valores de los vecinos, su correlación, distancia y **diferencia de
     altitud**, estacionalidad (seno/coseno del día del año), climatología propia y valores antes y después del hueco.
     Admite vecinos con huecos (Mital et al., 2020).
   - Precipitación en **dos etapas**: probabilidad de lluvia y cantidad en escala logarítmica. El umbral de ocurrencia
     se calibra para reproducir la frecuencia observada de días con lluvia.
   - Ensamble ponderado por KGE.
4. **Selección automática por tipo de hueco.** En un año de calibración se elige el método con mayor KGE para huecos
   cortos, medios y largos.
5. **Incertidumbre.** Predicción conformal por variable y tipo de hueco (CQR con cuantiles 5–95 % para precipitación).
6. **Restricciones físicas.** Precipitación ≥ 0 y Tmax − Tmin ≥ 0.5 °C en toda salida (si se viola, se ajusta solo el
   valor estimado).

## 3. Validación
Huecos artificiales por estación y por año de registro (4 cortos, 1.5 medios y 0.4 largos de 31–90 días por año)
sobre datos observados, en lluvias y en estiaje. División temporal automática: los 2 últimos años son prueba y el 10 %
anterior, calibración (con 2015–2024: entrenamiento ≤ 2021, calibración 2022, prueba 2023–2024).

| Variable | Línea base IDW (MAE / KGE) | Recomendado (MAE / KGE) | Cobertura del intervalo 90 % |
|---|---|---|---|
| Precipitación | 1.07 mm / 0.64 | 1.03 mm / 0.66 | 96 % |
| Tmax | 1.47 °C / 0.77 | 0.96 °C / 0.93 | 91 % |
| Tmin | 1.34 °C / 0.87 | 0.85 °C / 0.97 | 91 % |

*Datos sintéticos.* Hallazgo relevante: en temperatura, la **diferencia normal con vecinos correlacionados** iguala al ML,
y el sistema la elige automáticamente. El ML debe ganarse su lugar, como lo pide el reto.

## 4. Bandera de calidad
- `observado`: dato medido que pasó el control de calidad.
- `estimado_alta`: ≥ 3 vecinos correlacionados con dato ese día, o hueco corto con al menos 1 vecino.
- `estimado_baja`: el resto de los estimados.
- `no_estimable`: no se publica valor.

## 5. Cuándo NO rellenar
- No hay ningún vecino correlacionado con dato ese día (temperatura: salvo huecos ≤ 3 días, que se interpolan con
  confianza baja).
- La estación está **suspendida** y el periodo es posterior a su último dato.
- Ningún método tiene información disponible.

## 6. Limitaciones
- Los intervalos son marginales por tipo de hueco y aún no se ajustan a cada punto según el número de vecinos.
- La prueba de homogeneidad solo **señala** cambios abruptos; no los corrige.
- Falta incorporar covariables satelitales o de reanálisis (CHIRPS, ERA5-Land, NASA POWER) y el modelo digital de
  elevación del `covariables.gpkg`.
- El ensamble ponderado por KGE puede suavizar la precipitación (más días con llovizna, FAR alto). Por eso se elige
  por tipo de hueco y no se aplica a ciegas.

## 7. Uso agrícola (Salamanca)
Sobre la serie completada se calculan indicadores para productores: lluvia de temporada (jun–oct) contra el promedio,
inicio de lluvias, racha seca más larga, heladas (Tmin ≤ 0 °C), grados día de desarrollo (base 10 °C, tope 30 °C),
evapotranspiración de referencia (Hargreaves, FAO-56) y balance lluvia − evapotranspiración. Cada indicador informa
el % de días medidos para que el productor sepa cuánto se apoya en datos estimados. Vista: `/agro`.

## 8. Integración
API REST con FastAPI (puede migrarse a Django REST Framework) y documentación OpenAPI en `/docs`. Componente web
`<siama-huecos>` (Leaflet + Plotly) que se incrusta en Monitor Precipitaciones y Monitor Temperaturas sin rediseñarlos.
Docker. Los resultados se cargan en PostgreSQL + PostGIS (`python -m siama_gaps postgres`) y la API puede leer de ahí.

**Tecnologías de IBM (opcionales, no cambian el stack del reto):**
- **watsonx.ai con IBM Granite** para el asistente de IA: redacta el resumen de cada estación y responde preguntas
  usando solo los datos del pipeline. Nunca presenta un estimado como observado y declara su `fuente`.
- **IBM Cloud Databases for PostgreSQL** como base gestionada con PostGIS (esquema `siama_huecos`).
- **IBM Cloud Code Engine** para publicar la API y la demo desde el mismo `Dockerfile`, con escala a cero.
- **IBM Carbon Design System** en la demo y como tema opcional del componente (`tema="carbon"`).

Sin credenciales de IBM, todo funciona igual con archivos locales y el resumen de plantilla.
