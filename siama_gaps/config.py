"""Parámetros del módulo. Todos documentados en la ficha técnica."""

VARIABLES = ["precipitacion", "tmax", "tmin"]
TEMPERATURAS = ["tmax", "tmin"]
UNIDADES = {"precipitacion": "mm", "tmax": "°C", "tmin": "°C"}

# Código de valor faltante del paquete (ver diccionario_datos.md)
CODIGO_FALTANTE = -99.9

# Clasificación de huecos exigida por el reto
CLASES_HUECO = [("corto", 1, 3), ("medio", 4, 30), ("largo", 31, 10**9)]

# Selección de vecinos: radio máximo + correlación mínima (no solo distancia)
RADIO_MAX_KM = 120.0
CORR_MIN = {"precipitacion": 0.35, "tmax": 0.60, "tmin": 0.60}
K_VECINOS = 6
MIN_TRASLAPE_DIAS = 365

# Incertidumbre: intervalo de predicción del 90 %
NIVEL_INTERVALO = 0.90

# Umbral de día con lluvia (mm) para POD/FAR y para el clasificador de ocurrencia
UMBRAL_LLUVIA = 0.1

# Huecos artificiales para validar, POR ESTACIÓN Y POR AÑO de registro: (cantidad, días mín., días máx.)
# Con 10 años equivale a 40 cortos, 15 medios y 4 largos por estación.
HUECOS_ARTIFICIALES_POR_ANIO = {"corto": (4.0, 1, 3), "medio": (1.5, 4, 30), "largo": (0.4, 31, 90)}
# División temporal automática: los últimos años son prueba y una fracción anterior es calibración.
# Con 2015-2024: entrenamiento <= 2021, calibración 2022, prueba 2023-2024.
ANIOS_PRUEBA = 2
FRACCION_CALIBRACION = 0.10

# Control de calidad
RANGO_TEMP = (-15.0, 48.0)
PRECIP_MAX = 300.0
Z_ATIPICO = 5.0
DIAS_VALOR_REPETIDO = 6
DIAS_CEROS_SOSPECHOSOS = 20
SEPARACION_MIN_TMAX_TMIN = 0.5


def clase_hueco(n_dias):
    for nombre, lo, hi in CLASES_HUECO:
        if lo <= n_dias <= hi:
            return nombre
    return "ninguno"
