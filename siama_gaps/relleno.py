"""Etapa 3: relleno. Líneas base (interpolación lineal, IDW, razón/diferencia normal),
modelo de machine learning (gradient boosting), ensamble ponderado por KGE, selección
automática del método por tipo de hueco e intervalos conformales calibrados.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from . import config as cfg
from .metricas import kge
from .utils import clase_vector, climatologia, haversine_matriz, info_huecos
from .vecinos import a_arreglos

METODOS_BASE = {
    "precipitacion": ["idw", "normal", "ml"],
    "tmax": ["interp_lineal", "idw", "normal", "ml"],
    "tmin": ["interp_lineal", "idw", "normal", "ml"],
}
NOMBRE_METODO = {
    "interp_lineal": "Interpolación lineal (propia serie)",
    "idw": "IDW (inverso de la distancia)",
    "normal": "Razón normal / diferencia normal con vecinos",
    "ml": "Gradient boosting con vecinos correlacionados",
    "ensamble": "Ensamble ponderado por KGE",
}


class Contexto:
    """Todo lo que los modelos necesitan saber de la red de estaciones en un estado dado de datos."""

    def __init__(self, fechas, est, M, tabla_vecinos):
        self.fechas = fechas
        self.doy = fechas.dayofyear.to_numpy()
        self.mes = fechas.month.to_numpy()
        self.claves = est["clave"].tolist()
        self.lat = est["latitud"].to_numpy(float)
        self.lon = est["longitud"].to_numpy(float)
        self.alt = est["altitud"].to_numpy(float)
        self.D = haversine_matriz(self.lat, self.lon)
        self.M = M
        self.T, self.S = M["tmax"].shape
        self.clim = {v: climatologia(M[v], self.doy) for v in cfg.TEMPERATURAS}
        self.A = {v: M[v] - self.clim[v] for v in cfg.TEMPERATURAS}
        P = M["precipitacion"]
        self.freq_hum = np.full((12, self.S), np.nan)
        self.media_hum = np.full((12, self.S), np.nan)
        with np.errstate(invalid="ignore"):
            for k in range(12):
                f = self.mes == k + 1
                h = P[f] >= cfg.UMBRAL_LLUVIA
                self.freq_hum[k] = np.nansum(h, 0) / np.maximum((~np.isnan(P[f])).sum(0), 1)
                self.media_hum[k] = np.nanmean(np.where(h, P[f], np.nan), 0)
        self.media_diaria = np.nanmean(P, 0)
        self.dtr = M["tmax"] - M["tmin"]
        self.nb = {v: a_arreglos(tabla_vecinos, self.claves, v) for v in cfg.VARIABLES}
        self.huecos = {v: info_huecos(M[v]) for v in cfg.VARIABLES}

    # ------------------------------------------------------------------
    def _vecinos(self, var, V, t, s):
        nb = self.nb[var]
        idx = nb["idx"][s]
        vals = np.full(idx.shape, np.nan)
        ok = idx >= 0
        tt = np.broadcast_to(t[:, None], idx.shape)
        vals[ok] = V[tt[ok], idx[ok]]
        corr, dist, dalt = nb["corr"][s], nb["dist"][s], nb["dalt"][s]
        disp = ~np.isnan(vals)
        w = np.where(disp, np.nan_to_num(corr) ** 2, 0)
        ws = w.sum(1)
        wmean = np.where(ws > 0, (np.nan_to_num(vals) * w).sum(1) / np.where(ws > 0, ws, 1), np.nan)
        return vals, corr, dist, dalt, wmean, disp.sum(1), idx

    def _propia(self, var, V, t, s):
        prev, nxt, largo = self.huecos[var]
        p, n = prev[t, s], nxt[t, s]
        vp = np.where(p >= 0, V[np.clip(p, 0, None), s], np.nan)
        vn = np.where(n < self.T, V[np.clip(n, None, self.T - 1), s], np.nan)
        dp = np.where(p >= 0, t - p, np.nan)
        dn = np.where(n < self.T, n - t, np.nan)
        interp = vp + (vn - vp) * dp / (dp + dn)
        return vp, dp, vn, dn, interp, largo[t, s]

    def features(self, var, t, s):
        """Matriz de covariables + predicciones de las líneas base para los puntos (t, s)."""
        t, s = np.asarray(t), np.asarray(s)
        temp = var in cfg.TEMPERATURAS
        V = self.A[var] if temp else self.M[var]
        vals, corr, dist, dalt, wmean, ndisp, idx = self._vecinos(var, V, t, s)
        vp, dp, vn, dn, interp, largo = self._propia(var, V, t, s)
        w = 2 * np.pi * self.doy[t] / 365.25
        cols = [np.sin(w), np.cos(w), self.alt[s], self.lat[s], self.lon[s]]
        if temp:
            pv = self._vecinos("precipitacion", self.M["precipitacion"], t, s)[0]
            frac_lluvia_vec = np.nanmean(np.where(np.isnan(pv), np.nan, pv >= cfg.UMBRAL_LLUVIA), 1) \
                if pv.size else np.full(len(t), np.nan)
            cols += [self.clim[var][t, s], self.M["precipitacion"][t, s], frac_lluvia_vec]
        else:
            m = self.mes[t] - 1
            with np.errstate(invalid="ignore"):
                frac = np.where(ndisp > 0, np.nansum(vals >= cfg.UMBRAL_LLUVIA, 1) / np.maximum(ndisp, 1), np.nan)
            maxv = np.where(ndisp > 0, np.nanmax(np.where(np.isnan(vals), -1, vals), 1), np.nan)
            cols += [self.freq_hum[m, s], self.media_hum[m, s], frac, maxv, self.dtr[t, s]]
        X = np.column_stack(cols + [vals, corr, dist, dalt, wmean, ndisp, vp, dp, vn, dn, interp, largo])

        # ---- Líneas base ----
        base = {}
        Mv = self.M[var]
        if temp:
            prev, nxt, _ = self.huecos[var]
            p, n = prev[t, s], nxt[t, s]
            rp = np.where(p >= 0, Mv[np.clip(p, 0, None), s], np.nan)
            rn = np.where(n < self.T, Mv[np.clip(n, None, self.T - 1), s], np.nan)
            base["interp_lineal"] = rp + (rn - rp) * dp / (dp + dn)  # lineal pura sobre el valor bruto
            # Diferencia normal: climatología propia + anomalía media de los vecinos correlacionados
            base["normal"] = self.clim[var][t, s] + _media_segura(vals)
        else:
            ratio = np.where(idx >= 0, self.media_diaria[s][:, None] / self.media_diaria[np.clip(idx, 0, None)], np.nan)
            base["normal"] = _media_segura(vals * ratio)
        Vt = Mv[t]                                    # (n, S): todas las estaciones ese día
        Dk = self.D[s]
        W = np.where((Dk > 0) & (Dk <= cfg.RADIO_MAX_KM) & ~np.isnan(Vt), 1 / np.maximum(Dk, 1) ** 2, 0)
        sw = W.sum(1)
        base["idw"] = np.where(sw > 0, (np.nan_to_num(Vt) * W).sum(1) / np.where(sw > 0, sw, 1), np.nan)
        return X, base, ndisp, largo


def _media_segura(a):
    n = (~np.isnan(a)).sum(1)
    return np.where(n > 0, np.nansum(a, 1) / np.maximum(n, 1), np.nan)


def _hgb(**kw):
    return HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
                                         min_samples_leaf=30, l2_regularization=1.0,
                                         early_stopping=True, random_state=0, **kw)


class ModeloVariable:
    def __init__(self, var):
        self.var = var
        self.umbral = 0.5
        self.factor = 1.0

    def _x(self, X):
        # Columnas sin ningún dato en entrenamiento (p. ej. un 6.º vecino que nadie tiene) se fijan a constante
        X = X.copy()
        X[:, self.col_vacia] = -999.0
        return X

    def entrenar(self, ctx, t, s, y):
        X, *_ = ctx.features(self.var, t, s)
        self.col_vacia = np.isnan(X).all(0)
        X = self._x(X)
        if self.var in cfg.TEMPERATURAS:
            self.reg = _hgb().fit(X, y - ctx.clim[self.var][t, s])
        else:
            hum = y >= cfg.UMBRAL_LLUVIA
            self.clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
                                                      min_samples_leaf=30, l2_regularization=1.0,
                                                      early_stopping=True, random_state=0).fit(X, hum)
            self.reg = _hgb().fit(X[hum], np.log1p(y[hum]))
            a = (1 - cfg.NIVEL_INTERVALO) / 2
            self.q_lo = _hgb(loss="quantile", quantile=a).fit(X, y)
            self.q_hi = _hgb(loss="quantile", quantile=1 - a).fit(X, y)
        return self

    def predecir(self, ctx, t, s):
        X, base, ndisp, largo = ctx.features(self.var, t, s)
        X = self._x(X)
        df = pd.DataFrame(base)
        if self.var in cfg.TEMPERATURAS:
            df["ml"] = self.reg.predict(X) + ctx.clim[self.var][t, s]
        else:
            df["p_lluvia"] = self.clf.predict_proba(X)[:, 1]
            df["cantidad"] = np.clip(np.expm1(self.reg.predict(X)), 0, None)
            df["q_lo"] = np.clip(self.q_lo.predict(X), 0, None)
            df["q_hi"] = np.clip(self.q_hi.predict(X), 0, None)
            df["ml"] = self._precip_puntual(df)
        df["n_vecinos"] = ndisp
        df["largo_hueco"] = largo
        df["clase"] = clase_vector(largo)
        return df

    def _precip_puntual(self, df):
        return np.where(df["p_lluvia"] >= self.umbral, df["cantidad"] * self.factor, 0.0)

    def calibrar_ocurrencia(self, df, y):
        """Umbral de ocurrencia que reproduce la frecuencia observada de días con lluvia
        y factor que corrige el sesgo de la retransformación logarítmica."""
        freq = np.mean(y >= cfg.UMBRAL_LLUVIA)
        self.umbral = float(np.quantile(df["p_lluvia"], 1 - freq)) if 0 < freq < 1 else 0.5
        hum = (y >= cfg.UMBRAL_LLUVIA) & (df["p_lluvia"].to_numpy() >= self.umbral)
        if hum.sum() > 20:
            self.factor = float(np.mean(y[hum]) / max(np.mean(df["cantidad"].to_numpy()[hum]), 1e-6))
        df["ml"] = self._precip_puntual(df)


# ---------------------------------------------------------------------------
# Ensamble, selección por tipo de hueco, reglas de "no rellenar" e incertidumbre
# ---------------------------------------------------------------------------
CLASES = [c for c, *_ in cfg.CLASES_HUECO]


def _ensamble(df, metodos, pesos):
    num = np.zeros(len(df))
    den = np.zeros(len(df))
    for m in metodos:
        w = pesos.get(m, 0.0)
        v = df[m].to_numpy()
        ok = ~np.isnan(v)
        num[ok] += w * v[ok]
        den[ok] += w
    return np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)


def ajustar_seleccion(var, df, y):
    """En el conjunto de calibración: pesos del ensamble (∝ KGE) y ranking de métodos por clase."""
    metodos = METODOS_BASE[var]
    conf = {"pesos": {}, "ranking": {}, "kge_calibracion": {}}
    for c in CLASES + ["todas"]:
        f = (df["clase"] == c).to_numpy() if c != "todas" else np.ones(len(df), bool)
        if f.sum() < 30:
            f = np.ones(len(df), bool)
        k = {}
        for m in metodos:
            v = df[m].to_numpy()[f]
            ok = ~np.isnan(v)
            k[m] = kge(v[ok], y[f][ok]) if ok.sum() > 30 else np.nan
        pesos = {m: max(0.0, k[m]) if not np.isnan(k[m]) else 0.0 for m in metodos}
        conf["pesos"][c] = pesos
        ens = _ensamble(df[f], metodos, pesos)
        ok = ~np.isnan(ens)
        k["ensamble"] = kge(ens[ok], y[f][ok]) if ok.sum() > 30 else np.nan
        conf["kge_calibracion"][c] = {m: (None if np.isnan(x) else round(x, 4)) for m, x in k.items()}
        conf["ranking"][c] = sorted(k, key=lambda m: -np.inf if np.isnan(k[m]) else -k[m])
    return conf


def combinar(var, df, conf, suspendida=None):
    """Valor final por punto, método usado, decisión de no rellenar y bandera de confianza."""
    metodos = METODOS_BASE[var]
    n = len(df)
    clase = df["clase"].to_numpy()
    ens = np.full(n, np.nan)
    for c in CLASES:
        f = clase == c
        if f.any():
            ens[f] = _ensamble(df[f], metodos, conf["pesos"].get(c, conf["pesos"]["todas"]))
    df["ensamble"] = ens
    final = np.full(n, np.nan)
    metodo = np.full(n, "", dtype=object)
    for c in CLASES:
        f = clase == c
        for m in conf["ranking"].get(c, conf["ranking"]["todas"]):
            v = df[m].to_numpy()
            usar = f & np.isnan(final) & ~np.isnan(v)
            final[usar] = v[usar]
            metodo[usar] = m

    nv = df["n_vecinos"].to_numpy()
    largo = df["largo_hueco"].to_numpy()
    motivo = np.full(n, "", dtype=object)
    sin_vecinos = nv == 0
    if var in cfg.TEMPERATURAS:
        corto = sin_vecinos & (largo <= 3)
        interp = df["interp_lineal"].to_numpy()
        final[corto] = interp[corto]
        metodo[corto] = "interp_lineal"
        no_est = sin_vecinos & ((largo > 3) | np.isnan(interp))
    else:
        no_est = sin_vecinos
    motivo[no_est] = "sin_vecinos_correlacionados"
    if suspendida is not None:
        no_est |= suspendida
        motivo[suspendida] = "estacion_suspendida"
    no_est |= np.isnan(final)
    motivo[no_est & (motivo == "")] = "sin_metodo_disponible"
    final[no_est] = np.nan
    metodo[no_est] = ""
    if var == "precipitacion":
        final = np.clip(final, 0, None)

    alta = (nv >= 3) | ((nv >= 1) & (clase == "corto"))
    bandera = np.where(no_est, "no_estimable", np.where(alta, "estimado_alta", "estimado_baja"))
    df["valor"] = final
    df["metodo"] = metodo
    df["bandera"] = bandera
    df["motivo_no_estimable"] = motivo
    return df


def ajustar_conformal(var, df, y):
    """Cuantil conformal por clase de hueco (split conformal; CQR para precipitación)."""
    q = {}
    ok = ~np.isnan(df["valor"].to_numpy())
    for c in CLASES + ["todas"]:
        f = ok & ((df["clase"] == c).to_numpy() if c != "todas" else True)
        if f.sum() < 30:
            continue
        if var in cfg.TEMPERATURAS:
            score = np.abs(df["valor"].to_numpy()[f] - y[f])
        else:
            score = np.maximum(df["q_lo"].to_numpy()[f] - y[f], y[f] - df["q_hi"].to_numpy()[f])
        n = len(score)
        nivel = min(1.0, np.ceil((n + 1) * cfg.NIVEL_INTERVALO) / n)
        q[c] = float(np.quantile(score, nivel))
    return q


def intervalos(var, df, q):
    clase = df["clase"].to_numpy()
    qq = np.array([q.get(c, q["todas"]) for c in clase])
    v = df["valor"].to_numpy()
    if var in cfg.TEMPERATURAS:
        li, ls = v - qq, v + qq
    else:
        li = np.clip(df["q_lo"].to_numpy() - qq, 0, None)
        ls = df["q_hi"].to_numpy() + qq
        li, ls = np.minimum(li, v), np.maximum(ls, v)
    df["li"] = np.where(np.isnan(v), np.nan, li)
    df["ls"] = np.where(np.isnan(v), np.nan, ls)
    return df
