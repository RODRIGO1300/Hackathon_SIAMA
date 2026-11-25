"""Métricas del reto: RMSE, MAE, BIAS, KGE, POD/FAR y cobertura del intervalo."""
import numpy as np

from .config import UMBRAL_LLUVIA


def kge(sim, obs):
    sim, obs = np.asarray(sim, float), np.asarray(obs, float)
    if len(obs) < 3 or np.std(obs) == 0 or np.std(sim) == 0 or np.mean(obs) == 0:
        return np.nan
    r = np.corrcoef(sim, obs)[0, 1]
    alfa = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return float(1 - np.sqrt((r - 1) ** 2 + (alfa - 1) ** 2 + (beta - 1) ** 2))


def calcular(sim, obs, variable, li=None, ls=None):
    sim, obs = np.asarray(sim, float), np.asarray(obs, float)
    ok = ~np.isnan(sim) & ~np.isnan(obs)
    sim, obs = sim[ok], obs[ok]
    if len(obs) == 0:
        return {"n": 0}
    e = sim - obs
    out = {"n": int(len(obs)), "mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e**2))),
           "bias": float(np.mean(e)), "kge": kge(sim, obs)}
    if variable == "precipitacion":
        ps, po = sim >= UMBRAL_LLUVIA, obs >= UMBRAL_LLUVIA
        aciertos, fallos, falsas = (ps & po).sum(), (~ps & po).sum(), (ps & ~po).sum()
        out["pod"] = float(aciertos / (aciertos + fallos)) if aciertos + fallos else np.nan
        out["far"] = float(falsas / (aciertos + falsas)) if aciertos + falsas else np.nan
    if li is not None:
        li, ls = np.asarray(li, float)[ok], np.asarray(ls, float)[ok]
        out["cobertura"] = float(np.mean((obs >= li - 1e-9) & (obs <= ls + 1e-9)))
        out["ancho_medio"] = float(np.mean(ls - li))
    return {k: (round(v, 4) if isinstance(v, float) and not np.isnan(v) else (None if isinstance(v, float) else v))
            for k, v in out.items()}
