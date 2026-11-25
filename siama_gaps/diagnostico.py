"""Etapa 1: diagnóstico de vacíos por estación y variable."""
import numpy as np
import pandas as pd

from . import config as cfg
from .utils import rachas


def calcular(M, fechas, claves):
    resumen, huecos, anual = [], [], []
    anios = fechas.year.to_numpy()
    for v in cfg.VARIABLES:
        X = M[v]
        for j, c in enumerate(claves):
            falta = np.isnan(X[:, j])
            ini, lon = rachas(falta)
            clases = [cfg.clase_hueco(n) for n in lon]
            for a, n, k in zip(ini, lon, clases):
                huecos.append({"clave": c, "variable": v,
                               "inicio": fechas[a].strftime("%Y-%m-%d"),
                               "fin": fechas[a + n - 1].strftime("%Y-%m-%d"),
                               "dias": int(n), "clase": k})
            obs = np.nonzero(~falta)[0]
            resumen.append({
                "clave": c, "variable": v, "dias_totales": len(falta),
                "dias_faltantes": int(falta.sum()),
                "pct_faltante": round(100 * falta.mean(), 2),
                "huecos_cortos": clases.count("corto"),
                "huecos_medios": clases.count("medio"),
                "huecos_largos": clases.count("largo"),
                "hueco_mas_largo": int(lon.max()) if len(lon) else 0,
                "primer_dato": fechas[obs[0]].strftime("%Y-%m-%d") if len(obs) else None,
                "ultimo_dato": fechas[obs[-1]].strftime("%Y-%m-%d") if len(obs) else None,
            })
            for a in np.unique(anios):
                f = anios == a
                anual.append({"clave": c, "variable": v, "anio": int(a),
                              "pct_faltante": round(100 * falta[f].mean(), 2)})
    return pd.DataFrame(resumen), pd.DataFrame(huecos), pd.DataFrame(anual)
