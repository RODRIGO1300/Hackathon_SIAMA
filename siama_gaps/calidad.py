"""Etapa 2: control de calidad previo. Los valores marcados se retiran (pasan a ser hueco)
y quedan registrados con la regla que los marcó; nunca se borran sin rastro."""
import numpy as np
import pandas as pd

from . import config as cfg
from .utils import rachas


def aplicar(M, fechas, claves):
    out = {v: m.copy() for v, m in M.items()}
    registros = []
    mes = fechas.month.to_numpy()

    def marcar(var, mascara, regla):
        mascara = mascara & ~np.isnan(out[var])
        t, s = np.nonzero(mascara)
        if len(t):
            registros.append(pd.DataFrame({
                "fecha": fechas[t], "clave": np.asarray(claves)[s], "variable": var,
                "valor_original": out[var][t, s], "regla": regla,
            }))
        return mascara

    with np.errstate(invalid="ignore"):
        P = out["precipitacion"]
        out["precipitacion"][marcar("precipitacion", P < 0, "precipitacion_negativa")] = np.nan
        out["precipitacion"][marcar("precipitacion", P > cfg.PRECIP_MAX, "precipitacion_extrema")] = np.nan

        for v in cfg.TEMPERATURAS:
            X = out[v]
            m = marcar(v, (X < cfg.RANGO_TEMP[0]) | (X > cfg.RANGO_TEMP[1]), "fuera_de_rango_fisico")
            out[v][m] = np.nan

        inv = out["tmax"] < out["tmin"]
        m1 = marcar("tmax", inv, "tmax_menor_que_tmin")
        m2 = marcar("tmin", inv, "tmax_menor_que_tmin")
        out["tmax"][m1] = np.nan
        out["tmin"][m2] = np.nan

        # Atípicos robustos por estación y mes (mediana / MAD)
        for v in cfg.TEMPERATURAS:
            X = out[v]
            z = np.zeros_like(X)
            for k in range(1, 13):
                f = mes == k
                med = np.nanmedian(X[f], axis=0)
                mad = np.nanmedian(np.abs(X[f] - med), axis=0) * 1.4826
                z[f] = np.abs(X[f] - med) / np.where(mad > 0, mad, np.nan)
            out[v][marcar(v, z > cfg.Z_ATIPICO, "atipico_estadistico")] = np.nan

        # Valor repetido (sensor trabado)
        for v in cfg.TEMPERATURAS:
            X = out[v]
            mask = np.zeros_like(X, bool)
            for j in range(X.shape[1]):
                igual = np.r_[False, X[1:, j] == X[:-1, j]]
                ini, lon = rachas(igual)
                for a, n in zip(ini, lon):
                    if n + 1 >= cfg.DIAS_VALOR_REPETIDO:
                        mask[a - 1:a + n, j] = True
            out[v][marcar(v, mask, "valor_repetido")] = np.nan

        # Ceros sospechosos: racha larga de ceros en temporada de lluvias mientras la región sí llueve
        P = out["precipitacion"]
        regional = np.nanmedian(P, axis=1)
        mask = np.zeros_like(P, bool)
        for j in range(P.shape[1]):
            ini, lon = rachas(P[:, j] == 0)
            for a, n in zip(ini, lon):
                if n < cfg.DIAS_CEROS_SOSPECHOSOS:
                    continue
                tramo = slice(a, a + n)
                en_temporada = np.isin(mes[tramo], [6, 7, 8, 9]).mean() > 0.5
                if en_temporada and np.nansum(regional[tramo]) > 40 and np.nanmean(regional[tramo] > 1) > 0.3:
                    mask[tramo, j] = True
        out["precipitacion"][marcar("precipitacion", mask, "ceros_sospechosos")] = np.nan

    banderas = pd.concat(registros, ignore_index=True) if registros else pd.DataFrame(
        columns=["fecha", "clave", "variable", "valor_original", "regla"])
    return out, banderas
