"""Genera un paquete de datos SINTÉTICO con el mismo formato que el paquete oficial del reto.

Sirve para desarrollar y probar el flujo completo antes de recibir los datos de SIAMA.
Simula: ciclo anual, gradiente por altitud, campos de anomalía espacialmente correlacionados,
temporada de lluvias (jun-oct) con ocurrencia y cantidad correlacionadas entre estaciones,
huecos reales (fallas, suspensiones), errores de captura y un cambio abrupto (reubicación).
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .config import CODIGO_FALTANTE
from .utils import haversine_matriz

MUNICIPIOS = [
    "León", "Irapuato", "Celaya", "Salamanca", "Guanajuato", "Dolores Hidalgo",
    "San Miguel de Allende", "Silao", "Pénjamo", "Acámbaro", "San Luis de la Paz",
    "Valle de Santiago", "Salvatierra", "Yuriria", "Cortazar", "San Felipe", "Ocampo",
    "Victoria", "Xichú", "Apaseo el Grande", "Abasolo", "Moroleón", "Tarimoro",
    "Comonfort", "Romita", "Jerécuaro", "Doctor Mora", "Santa Catarina",
]
FECHA_INI, FECHA_FIN = "2015-01-01", "2024-12-31"


def _ar1(rng, n, phi, sd, cols=None):
    shape = (n,) if cols is None else (n, cols)
    e = rng.normal(0, sd * np.sqrt(1 - phi**2), size=shape)
    x = np.zeros(shape)
    x[0] = rng.normal(0, sd, size=shape[1:] or None)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + e[t]
    return x


def generar(destino="datos", n_estaciones=28, semilla=42):
    rng = np.random.default_rng(semilla)
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    S = n_estaciones

    # --- Estaciones -------------------------------------------------------
    lat = rng.uniform(20.1, 21.75, S)
    lon = rng.uniform(-101.95, -99.8, S)
    sierra_gto = 950 * np.exp(-(((lat - 21.05) / 0.25) ** 2 + ((lon + 101.25) / 0.35) ** 2))
    sierra_gorda = 1000 * np.exp(-(((lat - 21.35) / 0.30) ** 2 + ((lon + 100.15) / 0.30) ** 2))
    alt = np.round(1720 + sierra_gto + sierra_gorda + rng.normal(0, 60, S))
    claves = [f"11{i + 1:03d}" for i in range(S)]
    municipios = (MUNICIPIOS * 2)[:S]
    estado = ["operando"] * S
    estado[S - 1] = "suspendida"
    est = pd.DataFrame({
        "clave": claves,
        "nombre": [f"{m} ({c})" for m, c in zip(municipios, claves)],
        "municipio": municipios,
        "latitud": lat.round(4), "longitud": lon.round(4), "altitud": alt,
        "estado_operativo": estado,
    })

    # --- Clima "verdadero" ----------------------------------------------
    fechas = pd.date_range(FECHA_INI, FECHA_FIN, freq="D")
    T = len(fechas)
    doy, mes = fechas.dayofyear.to_numpy(), fechas.month.to_numpy()
    D = haversine_matriz(lat, lon)

    p_mes = np.array([.03, .03, .03, .05, .12, .40, .55, .55, .45, .20, .06, .04])[mes - 1]
    p_lluvia = np.clip(p_mes[:, None] * (1 + 0.25 * (alt - 1900) / 500)[None, :], 0.01, 0.9)
    L = np.linalg.cholesky(np.exp(-D / 90.0) + 1e-6 * np.eye(S))
    reg = _ar1(rng, T, 0.6, 1.0)
    z_occ = 0.6 * reg[:, None] + 0.8 * (rng.normal(size=(T, S)) @ L.T)
    lluvia = stats.norm.cdf(z_occ) < p_lluvia
    z_amt = 0.5 * reg[:, None] + 0.866 * (rng.normal(size=(T, S)) @ L.T)
    u = np.clip(stats.norm.cdf(z_amt), 1e-4, 0.9995)
    media_humeda = np.array([3, 3, 4, 5, 7, 10, 11, 10, 9, 6, 4, 3.])[mes - 1][:, None] \
        * (1 + 0.2 * (alt - 1900) / 500)[None, :]
    forma = 0.75
    cantidad = stats.gamma.ppf(u, a=forma, scale=media_humeda / forma)
    precip = np.where(lluvia, np.maximum(cantidad, 0.2), 0.0).round(1)

    x = (lon - lon.mean())
    y = (lat - lat.mean())
    A, B, C = _ar1(rng, T, .75, 1.6), _ar1(rng, T, .8, .8), _ar1(rng, T, .8, .8)
    anom = A[:, None] + B[:, None] * x + C[:, None] * y + _ar1(rng, T, .5, .7, S)
    clim = 16.5 + 4.2 * np.sin(2 * np.pi * (doy - 105) / 365.25)[:, None] - 0.0062 * (alt - 1800)[None, :]
    tmedia = clim + anom - 1.0 * lluvia
    temporada = (p_mes / 0.55)[:, None]
    dtr = np.clip(13.5 - 3.5 * temporada - 3.0 * lluvia + rng.normal(0, 1.2, (T, S)), 2.5, None)
    tmax = (tmedia + dtr / 2).round(1)
    tmin = (tmedia - dtr / 2).round(1)
    # Cambio abrupto: reubicación de la estación 10 en marzo de 2020
    tmin[fechas >= "2020-03-01", 9] += 1.3

    verdad = {"precipitacion": precip, "tmax": tmax, "tmin": tmin}
    obs = {k: v.copy() for k, v in verdad.items()}

    # --- Huecos reales ----------------------------------------------------
    for s in range(S):
        for _ in range(rng.poisson(rng.uniform(8, 35))):
            r = rng.random()
            L_h = rng.integers(1, 4) if r < .6 else rng.integers(4, 31) if r < .9 else rng.integers(31, 200)
            t0 = rng.integers(0, T - L_h)
            q = rng.random()
            vs = ["precipitacion", "tmax", "tmin"] if q < .7 else ["tmax", "tmin"] if q < .85 else ["precipitacion"]
            for v in vs:
                obs[v][t0:t0 + L_h, s] = np.nan
    susp = (fechas >= "2019-06-01") & (fechas <= "2021-03-15")
    for v in obs:
        obs[v][susp, 5] = np.nan                   # estación suspendida temporalmente
        obs[v][fechas >= "2023-07-01", S - 1] = np.nan  # estación suspendida (sin datos recientes)

    # --- test_publico: el "comité" retira valores conocidos --------------
    filas_test = []
    candidatas = rng.choice(np.arange(S - 1), 10, replace=False)
    ventana = np.nonzero(fechas >= "2023-01-01")[0]
    for s in candidatas:
        for L_h in [*rng.integers(1, 4, 3), *rng.integers(4, 31, 2), rng.integers(31, 61)]:
            t0 = rng.integers(ventana[0], T - L_h)
            for v in obs:
                for t in range(t0, t0 + L_h):
                    if not np.isnan(obs[v][t, s]):
                        filas_test.append((fechas[t], claves[s], v, obs[v][t, s]))
                        obs[v][t, s] = np.nan
    test = pd.DataFrame(filas_test, columns=["fecha", "clave", "variable", "valor_real"])
    test = test.drop_duplicates(["fecha", "clave", "variable"])

    # --- Errores de captura / sensor (para el control de calidad) ---------
    def celdas(v, n, cond=None):
        ok = ~np.isnan(obs[v])
        if cond is not None:
            ok &= cond
        t, s = np.nonzero(ok)
        i = rng.choice(len(t), n, replace=False)
        return t[i], s[i]

    t, s = celdas("tmax", 25, (obs["tmax"] - obs["tmin"]) > 3)
    obs["tmax"][t, s], obs["tmin"][t, s] = obs["tmin"][t, s].copy(), obs["tmax"][t, s].copy()
    t, s = celdas("precipitacion", 8)
    obs["precipitacion"][t, s] = -rng.uniform(1, 5, 8).round(1)
    t, s = celdas("tmax", 6)
    obs["tmax"][t, s] = 58.0
    blq = np.nonzero(fechas == "2018-04-10")[0][0]
    obs["tmax"][blq:blq + 8, 2] = 27.5                       # sensor trabado
    blq = np.nonzero(fechas == "2017-07-01")[0][0]
    m = ~np.isnan(obs["precipitacion"][blq:blq + 35, 11])
    obs["precipitacion"][blq:blq + 35, 11][m] = 0.0          # ceros sospechosos en plena temporada

    # --- Escritura ----------------------------------------------------------
    serie = pd.DataFrame({
        "fecha": np.repeat(fechas.strftime("%Y-%m-%d"), S),
        "clave": np.tile(claves, T),
        **{v: np.nan_to_num(obs[v], nan=CODIGO_FALTANTE).ravel() for v in ["precipitacion", "tmax", "tmin"]},
    })
    est.to_csv(destino / "estaciones.csv", index=False)
    serie.to_csv(destino / "series_diarias.csv", index=False)
    test["fecha"] = pd.to_datetime(test["fecha"]).dt.strftime("%Y-%m-%d")
    test[["fecha", "clave", "variable"]].sort_values(["clave", "variable", "fecha"]).to_csv(
        destino / "test_publico.csv", index=False)
    test.to_csv(destino / "_verdad_test_publico.csv", index=False)  # solo existe porque los datos son sintéticos
    (destino / "diccionario_datos.md").write_text(DICCIONARIO, encoding="utf-8")
    print(f"Datos sintéticos: {S} estaciones, {T} días, {len(test)} valores en test_publico -> {destino}/")


DICCIONARIO = f"""# Diccionario de datos (paquete SINTÉTICO de prueba)

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

Valor faltante: `{CODIGO_FALTANTE}`.

## test_publico.csv
`fecha, clave, variable` a estimar. `_verdad_test_publico.csv` solo existe en el paquete sintético
para poder calificar localmente.
"""
