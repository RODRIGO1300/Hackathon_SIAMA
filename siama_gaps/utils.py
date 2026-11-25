"""Funciones auxiliares: lectura, distancias, rachas, climatología."""
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CODIGO_FALTANTE, CLASES_HUECO, VARIABLES


def cargar_estaciones(ruta):
    est = pd.read_csv(ruta, dtype={"clave": str})
    return est.sort_values("clave").reset_index(drop=True)


def cargar_series(ruta):
    ruta = Path(ruta)
    if ruta.suffix == ".parquet":
        df = pd.read_parquet(ruta)
    else:
        df = pd.read_csv(ruta, dtype={"clave": str})
    df["fecha"] = pd.to_datetime(df["fecha"])
    for v in VARIABLES:
        df[v] = pd.to_numeric(df[v], errors="coerce")
        df.loc[np.isclose(df[v], CODIGO_FALTANTE), v] = np.nan
    return df


def a_matrices(df, fechas, claves):
    """Convierte la tabla larga en matrices (días x estaciones) por variable."""
    out = {}
    for v in VARIABLES:
        m = df.pivot_table(index="fecha", columns="clave", values=v, aggfunc="first")
        m = m.reindex(index=fechas, columns=claves)
        out[v] = m.to_numpy(dtype=float)
    return out


def haversine_matriz(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def rachas(mascara):
    """Inicios y longitudes de las rachas True de un vector booleano."""
    m = np.concatenate([[False], np.asarray(mascara, bool), [False]])
    d = np.diff(m.astype(int))
    inicios = np.nonzero(d == 1)[0]
    fines = np.nonzero(d == -1)[0]
    return inicios, fines - inicios


def info_huecos(M):
    """Para cada celda: índice del último dato observado antes, del siguiente después
    y longitud del hueco que la contiene (0 si está observada)."""
    T, S = M.shape
    obs = ~np.isnan(M)
    idx = np.repeat(np.arange(T)[:, None], S, axis=1)
    prev = np.maximum.accumulate(np.where(obs, idx, -1), axis=0)
    nxt = np.minimum.accumulate(np.where(obs, idx, T)[::-1], axis=0)[::-1]
    largo = np.where(obs, 0, nxt - prev - 1)
    return prev, nxt, largo


def clase_vector(largo):
    out = np.full(np.shape(largo), "ninguno", dtype=object)
    for nombre, lo, hi in CLASES_HUECO:
        out[(largo >= lo) & (largo <= hi)] = nombre
    return out


def armonicos(doy, n=3):
    w = 2 * np.pi * np.asarray(doy) / 365.25
    cols = [np.ones_like(w)]
    for k in range(1, n + 1):
        cols += [np.cos(k * w), np.sin(k * w)]
    return np.column_stack(cols)


def climatologia(M, doy, n_armonicos=3):
    """Ciclo anual suave por estación (regresión armónica sobre los datos observados)."""
    H = armonicos(doy, n_armonicos)
    C = np.full(M.shape, np.nan)
    for j in range(M.shape[1]):
        ok = ~np.isnan(M[:, j])
        if ok.sum() < 60:
            continue
        coef, *_ = np.linalg.lstsq(H[ok], M[ok, j], rcond=None)
        C[:, j] = H @ coef
    return C
