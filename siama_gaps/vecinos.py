"""Selección documentada de estaciones vecinas: radio máximo + correlación mínima.

Siguiendo a Tang et al. (2020): los vecinos se ordenan por correlación, no por distancia.
La temperatura se correlaciona en anomalías (sin ciclo anual, que inflaría la correlación);
la precipitación en raíz cúbica (reduce el peso de los extremos).
"""
import numpy as np
import pandas as pd

from . import config as cfg
from .utils import climatologia, haversine_matriz


def seleccionar(M, fechas, est):
    D = haversine_matriz(est["latitud"].to_numpy(), est["longitud"].to_numpy())
    alt = est["altitud"].to_numpy()
    claves = est["clave"].tolist()
    doy = fechas.dayofyear.to_numpy()
    filas = []
    for v in cfg.VARIABLES:
        X = M[v]
        Y = X - climatologia(X, doy) if v in cfg.TEMPERATURAS else np.cbrt(X)
        for i in range(len(claves)):
            cands = []
            for j in range(len(claves)):
                if i == j or D[i, j] > cfg.RADIO_MAX_KM:
                    continue
                ok = ~np.isnan(Y[:, i]) & ~np.isnan(Y[:, j])
                if ok.sum() < cfg.MIN_TRASLAPE_DIAS:
                    continue
                r = np.corrcoef(Y[ok, i], Y[ok, j])[0, 1]
                if r >= cfg.CORR_MIN[v]:
                    cands.append((r, j, int(ok.sum())))
            cands.sort(reverse=True)
            for rango, (r, j, n) in enumerate(cands[:cfg.K_VECINOS], start=1):
                filas.append({"clave": claves[i], "variable": v, "rango": rango, "vecino": claves[j],
                              "dist_km": round(D[i, j], 1), "dif_altitud_m": float(alt[j] - alt[i]),
                              "correlacion": round(r, 3), "dias_traslape": n})
    return pd.DataFrame(filas)


def a_arreglos(tabla, claves, variable):
    """Arreglos (estaciones x K) con índice del vecino (-1 = vacío), correlación, distancia y dif. de altitud."""
    S, K = len(claves), cfg.K_VECINOS
    pos = {c: i for i, c in enumerate(claves)}
    idx = -np.ones((S, K), int)
    corr, dist, dalt = (np.full((S, K), np.nan) for _ in range(3))
    for f in tabla[tabla["variable"] == variable].itertuples():
        i, k = pos[f.clave], f.rango - 1
        idx[i, k] = pos[f.vecino]
        corr[i, k], dist[i, k], dalt[i, k] = f.correlacion, f.dist_km, f.dif_altitud_m
    return {"idx": idx, "corr": corr, "dist": dist, "dalt": dalt}
