"""Extra: detección de cambios abruptos (homogeneidad) con la prueba de Pettitt.

Para temperatura se usa una serie RELATIVA (anomalía de la estación menos la media de sus vecinos),
que elimina la señal climática regional y deja visibles cambios de instrumento o reubicaciones.
"""
import numpy as np
import pandas as pd
from scipy.stats import rankdata

from . import config as cfg
from .utils import climatologia


def pettitt(x):
    x = np.asarray(x, float)
    pos = np.nonzero(~np.isnan(x))[0]
    x = x[pos]
    n = len(x)
    if n < 24:
        return None, np.nan
    r = rankdata(x)
    U = 2 * np.cumsum(r) - np.arange(1, n + 1) * (n + 1)
    k = int(np.argmax(np.abs(U)))
    K = np.abs(U[k])
    p = min(1.0, 2 * np.exp(-6 * K**2 / (n**3 + n**2)))
    return pos[k], p


def evaluar(M, fechas, claves, vecinos_tabla):
    doy = fechas.dayofyear.to_numpy()
    periodo = fechas.to_period("M")
    meses = periodo.unique()
    pos = {c: i for i, c in enumerate(claves)}
    filas = []
    for v in cfg.VARIABLES:
        X = M[v]
        if v in cfg.TEMPERATURAS:
            A = X - climatologia(X, doy)
        else:
            A = X
        for j, c in enumerate(claves):
            if v in cfg.TEMPERATURAS:
                vec = vecinos_tabla[(vecinos_tabla.clave == c) & (vecinos_tabla.variable == v)]["vecino"]
                idx = [pos[x] for x in vec]
                if not idx:
                    continue
                serie_d = A[:, j] - np.nanmean(A[:, idx], axis=1)
            else:
                serie_d = A[:, j]
            df = pd.DataFrame({"p": periodo, "x": serie_d})
            g = df.groupby("p")["x"]
            mensual = g.mean() if v in cfg.TEMPERATURAS else g.sum(min_count=25)
            mensual = mensual.where(g.count() >= 20).reindex(meses)
            if v == "precipitacion":  # estandarizar por mes calendario
                mm = mensual.index.month
                mensual = (mensual - mensual.groupby(mm).transform("mean")) / mensual.groupby(mm).transform("std")
            k, p = pettitt(mensual.to_numpy())
            if k is None:
                continue
            antes, despues = mensual.iloc[:k + 1].mean(), mensual.iloc[k + 1:].mean()
            filas.append({"clave": c, "variable": v, "fecha_cambio": str(meses[k] + 1),
                          "p_valor": float(p), "magnitud": round(float(despues - antes), 3),
                          "cambio_detectado": bool(p < 0.01)})
    return pd.DataFrame(filas)
