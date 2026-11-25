# Ficha técnica · Relleno de huecos climatológicos para SIAMA (borrador)

> Las cifras de esta versión provienen del **paquete sintético** de prueba. Se actualizan automáticamente en
> `salidas/reporte_metricas.md` al ejecutar el pipeline con los datos oficiales.

## 1. Objetivo
Completar las series diarias de **precipitación, Tmax y Tmin** de las estaciones de Guanajuato, declarando para cada
valor estimado un **intervalo del 90 %** y una **bandera de calidad**, y negarse a rellenar cuando no hay sustento.

## 2. Método
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
Huecos artificiales por estación (40 cortos, 15 medios, 4 largos de 31–90 días) sobre datos observados, en lluvias y
en estiaje. División temporal: entrenamiento ≤ 2021, calibración 2022, prueba 2023–2024.

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

## 7. Integración
API REST con FastAPI (puede migrarse a Django REST Framework) y documentación OpenAPI en `/docs`. Componente web
`<siama-huecos>` (Leaflet + Plotly) que se incrusta en Monitor Precipitaciones y Monitor Temperaturas sin rediseñarlos.
Docker. Siguiente paso: cargar `series_completadas` en PostgreSQL/PostGIS.
