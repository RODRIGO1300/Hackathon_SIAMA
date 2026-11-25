"""Pipeline reproducible: series_diarias.csv -> diagnóstico, QC, validación, series completadas,
predicciones de test_publico y métricas. Se ejecuta con un solo comando:

    python -m siama_gaps run --datos datos --salida salidas
"""
import json
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import calidad, config as cfg, diagnostico, homogeneidad, vecinos
from .metricas import calcular
from .relleno import (CLASES, METODOS_BASE, NOMBRE_METODO, Contexto, ModeloVariable, ajustar_conformal,
                      ajustar_seleccion, combinar, intervalos)
from .utils import a_matrices, cargar_estaciones, cargar_series, climatologia

warnings.filterwarnings("ignore", category=RuntimeWarning)


def huecos_artificiales(M, fechas, rng):
    """Retira datos observados simulando huecos reales (cortos, medios, largos, en lluvias y estiaje).
    split: 1 = entrenamiento, 2 = calibración, 3 = prueba (por año de inicio del hueco)."""
    T, S = M["tmax"].shape
    mascara = np.zeros((T, S), bool)
    split = np.zeros((T, S), np.int8)
    anios = fechas.year.to_numpy()
    for s in range(S):
        for _, (n, lo, hi) in cfg.HUECOS_ARTIFICIALES.items():
            for _ in range(n):
                L = int(rng.integers(lo, hi + 1))
                t0 = int(rng.integers(0, T - L))
                a = anios[t0]
                k = 1 if a <= cfg.ANIO_FIN_ENTRENAMIENTO else 2 if a == cfg.ANIO_CALIBRACION else 3
                mascara[t0:t0 + L, s] = True
                split[t0:t0 + L, s] = k
    return mascara, split


def _corregir_tmax_tmin(V, EST, LI, LS, clim_dtr):
    """Garantiza Tmax > Tmin en toda salida ajustando solo valores estimados."""
    tx, tn = V["tmax"], V["tmin"]
    ex, en = EST["tmax"], EST["tmin"]
    with np.errstate(invalid="ignore"):
        viol = (tx - tn < cfg.SEPARACION_MIN_TMAX_TMIN) & (ex | en)
    n = int(viol.sum())
    ambos = viol & ex & en
    mitad = np.maximum(np.nan_to_num(clim_dtr, nan=10.0) / 2, cfg.SEPARACION_MIN_TMAX_TMIN)
    centro = (tx + tn) / 2
    nuevo_x = np.where(ambos, centro + mitad, np.where(viol & ex & ~en, tn + cfg.SEPARACION_MIN_TMAX_TMIN, tx))
    nuevo_n = np.where(ambos, centro - mitad, np.where(viol & en & ~ex, tx - cfg.SEPARACION_MIN_TMAX_TMIN, tn))
    for v, nuevo in (("tmax", nuevo_x), ("tmin", nuevo_n)):
        delta = np.nan_to_num(nuevo - V[v])
        V[v] = nuevo
        LI[v] = LI[v] + delta
        LS[v] = LS[v] + delta
    return n


def ejecutar(datos="datos", salida="salidas", semilla=0):
    inicio = time.time()
    datos, salida = Path(datos), Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    est = cargar_estaciones(datos / "estaciones.csv")
    ruta_series = datos / "series_diarias.parquet"
    df = cargar_series(ruta_series if ruta_series.exists() else datos / "series_diarias.csv")
    fechas = pd.date_range(df["fecha"].min(), df["fecha"].max(), freq="D")
    claves = est["clave"].tolist()
    Mraw = a_matrices(df, fechas, claves)

    print("[1/6] Control de calidad...")
    M, banderas_qc = calidad.aplicar(Mraw, fechas, claves)
    banderas_qc.to_csv(salida / "qc_banderas.csv", index=False)
    print(f"      {len(banderas_qc)} valores marcados y retirados: "
          f"{banderas_qc['regla'].value_counts().to_dict()}")

    print("[2/6] Diagnóstico de vacíos...")
    resumen, huecos, anual = diagnostico.calcular(M, fechas, claves)
    resumen.to_csv(salida / "diagnostico_estaciones.csv", index=False)
    huecos.to_csv(salida / "huecos.csv", index=False)
    anual.to_csv(salida / "diagnostico_anual.csv", index=False)

    print("[3/6] Selección de vecinos y homogeneidad...")
    tabla_vec = vecinos.seleccionar(M, fechas, est)
    tabla_vec.to_csv(salida / "vecinos.csv", index=False)
    homog = homogeneidad.evaluar(M, fechas, claves, tabla_vec)
    homog.to_csv(salida / "homogeneidad.csv", index=False)

    print("[4/6] Validación con huecos artificiales (entrenar / calibrar / probar)...")
    rng = np.random.default_rng(semilla)
    mascara, split = huecos_artificiales(M, fechas, rng)
    Mm = {v: np.where(mascara, np.nan, M[v]) for v in cfg.VARIABLES}
    ctx_val = Contexto(fechas, est, Mm, tabla_vec)
    modelos, configs, resultados, por_bandera, n_puntos = {}, {}, [], [], {}
    for var in cfg.VARIABLES:
        verdad = M[var]
        pts = {k: np.nonzero(mascara & (split == k) & ~np.isnan(verdad)) for k in (1, 2, 3)}
        n_puntos[var] = {"entrenamiento": len(pts[1][0]), "calibracion": len(pts[2][0]), "prueba": len(pts[3][0])}
        t, s = pts[1]
        modelo = ModeloVariable(var).entrenar(ctx_val, t, s, verdad[t, s])
        t, s = pts[2]
        dfc, yc = modelo.predecir(ctx_val, t, s), verdad[t, s]
        if var == "precipitacion":
            modelo.calibrar_ocurrencia(dfc, yc)
        conf = ajustar_seleccion(var, dfc, yc)
        dfc = combinar(var, dfc, conf)
        conf["q"] = ajustar_conformal(var, dfc, yc)
        t, s = pts[3]
        dft, yt = modelo.predecir(ctx_val, t, s), verdad[t, s]
        dft = intervalos(var, combinar(var, dft, conf), conf["q"])
        for c in CLASES + ["todas"]:
            f = (dft["clase"] == c).to_numpy() if c != "todas" else np.ones(len(dft), bool)
            for m in METODOS_BASE[var] + ["ensamble"]:
                resultados.append({"variable": var, "clase": c, "metodo": m,
                                   **calcular(dft[m].to_numpy()[f], yt[f], var)})
            r = calcular(dft["valor"].to_numpy()[f], yt[f], var, dft["li"].to_numpy()[f], dft["ls"].to_numpy()[f])
            r["pct_no_estimable"] = round(100 * float(np.mean(dft["bandera"].to_numpy()[f] == "no_estimable")), 2)
            resultados.append({"variable": var, "clase": c, "metodo": "recomendado", **r})
        for b in ("estimado_alta", "estimado_baja"):
            f = (dft["bandera"] == b).to_numpy()
            por_bandera.append({"variable": var, "bandera": b,
                                **calcular(dft["valor"].to_numpy()[f], yt[f], var,
                                           dft["li"].to_numpy()[f], dft["ls"].to_numpy()[f])})
        modelos[var], configs[var] = modelo, conf
        rec = {c: conf["ranking"][c][0] for c in CLASES}
        print(f"      {var}: método recomendado por tipo de hueco -> {rec}")

    print("[5/6] Relleno de los huecos reales...")
    ctx = Contexto(fechas, est, M, tabla_vec)
    T, S = M["tmax"].shape
    ultimo_obs = np.array([np.max(np.nonzero(~np.isnan(M["tmax"][:, j]) | ~np.isnan(M["precipitacion"][:, j]))[0],
                                  initial=-1) for j in range(S)])
    suspendida = (est["estado_operativo"].str.lower() == "suspendida").to_numpy()
    V, LI, LS, EST = {}, {}, {}, {}
    BAND, MET, MOT = {}, {}, {}
    for var in cfg.VARIABLES:
        V[var], LI[var], LS[var] = M[var].copy(), np.full((T, S), np.nan), np.full((T, S), np.nan)
        BAND[var] = np.where(np.isnan(M[var]), "", "observado").astype(object)
        MET[var] = np.full((T, S), "", dtype=object)
        MOT[var] = np.full((T, S), "", dtype=object)
        t, s = np.nonzero(np.isnan(M[var]))
        dfp = modelos[var].predecir(ctx, t, s)
        susp = suspendida[s] & (t > ultimo_obs[s])
        dfp = intervalos(var, combinar(var, dfp, configs[var], suspendida=susp), configs[var]["q"])
        V[var][t, s] = dfp["valor"].to_numpy()
        LI[var][t, s], LS[var][t, s] = dfp["li"].to_numpy(), dfp["ls"].to_numpy()
        BAND[var][t, s] = dfp["bandera"].to_numpy()
        MET[var][t, s] = dfp["metodo"].to_numpy()
        MOT[var][t, s] = dfp["motivo_no_estimable"].to_numpy()
        EST[var] = np.isnan(M[var]) & ~np.isnan(V[var])
    clim_dtr = climatologia(M["tmax"] - M["tmin"], fechas.dayofyear.to_numpy())
    n_corr = _corregir_tmax_tmin(V, EST, LI, LS, clim_dtr)
    print(f"      Correcciones para garantizar Tmax > Tmin: {n_corr}")

    qc_map = banderas_qc.assign(fecha=banderas_qc["fecha"].dt.strftime("%Y-%m-%d")) \
        .drop_duplicates(["fecha", "clave", "variable"]).set_index(["fecha", "clave", "variable"])["regla"]
    partes = []
    f_str = np.repeat(fechas.strftime("%Y-%m-%d").to_numpy(), S)
    c_rep = np.tile(np.asarray(claves, dtype=object), T)
    for var in cfg.VARIABLES:
        b = BAND[var].ravel()
        partes.append(pd.DataFrame({
            "fecha": f_str, "clave": c_rep, "variable": var,
            "valor": np.round(V[var].ravel(), 1), "li": np.round(LI[var].ravel(), 2), "ls": np.round(LS[var].ravel(), 2),
            "origen": np.where(b == "observado", "observado", np.where(b == "no_estimable", "no_estimable", "estimado")),
            "bandera": b, "metodo": MET[var].ravel(), "motivo_no_estimable": MOT[var].ravel(),
        }))
    serie = pd.concat(partes, ignore_index=True)
    idx = pd.MultiIndex.from_arrays([serie["fecha"], serie["clave"], serie["variable"]])
    serie["qc"] = qc_map.reindex(idx).fillna("").to_numpy()
    serie.to_csv(salida / "series_completadas.csv.gz", index=False, compression="gzip")
    # Resguardo: ningún estimado sale como observado, sin precipitación negativa, Tmax > Tmin
    assert not ((serie["origen"] == "observado") & (serie["metodo"] != "")).any()
    assert (serie.loc[serie.variable == "precipitacion", "valor"].dropna() >= 0).all()

    print("[6/6] Predicciones sobre test_publico.csv y métricas...")
    test_local = None
    ruta_test = datos / "test_publico.csv"
    if ruta_test.exists():
        test = pd.read_csv(ruta_test, dtype={"clave": str})
        pred = test.merge(serie, on=["fecha", "clave", "variable"], how="left")
        pred = pred.rename(columns={"valor": "estimado", "li": "limite_inferior", "ls": "limite_superior"})
        pred[["fecha", "clave", "variable", "estimado", "limite_inferior", "limite_superior", "bandera", "metodo"]] \
            .to_csv(salida / "predicciones_test_publico.csv", index=False)
        ruta_verdad = datos / "_verdad_test_publico.csv"
        if ruta_verdad.exists():
            ver = pd.read_csv(ruta_verdad, dtype={"clave": str}).merge(pred, on=["fecha", "clave", "variable"])
            test_local = {v: calcular(g["estimado"], g["valor_real"], v, g["limite_inferior"], g["limite_superior"])
                          for v, g in ver.groupby("variable")}

    metricas = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "nivel_intervalo": cfg.NIVEL_INTERVALO,
        "configuracion": {
            "radio_max_km": cfg.RADIO_MAX_KM, "correlacion_minima": cfg.CORR_MIN, "k_vecinos": cfg.K_VECINOS,
            "min_traslape_dias": cfg.MIN_TRASLAPE_DIAS, "huecos_artificiales_por_estacion": cfg.HUECOS_ARTIFICIALES,
            "division": {"entrenamiento": f"<= {cfg.ANIO_FIN_ENTRENAMIENTO}", "calibracion": cfg.ANIO_CALIBRACION,
                         "prueba": f">= {cfg.ANIO_CALIBRACION + 1}"},
        },
        "nombres_metodo": NOMBRE_METODO,
        "puntos_validacion": n_puntos,
        "resultados_prueba": resultados,
        "por_bandera": por_bandera,
        "metodo_recomendado": {v: {c: configs[v]["ranking"][c][0] for c in CLASES} for v in cfg.VARIABLES},
        "pesos_ensamble": {v: configs[v]["pesos"] for v in cfg.VARIABLES},
        "kge_calibracion": {v: configs[v]["kge_calibracion"] for v in cfg.VARIABLES},
        "cuantil_conformal": {v: configs[v]["q"] for v in cfg.VARIABLES},
        "umbral_ocurrencia_lluvia": modelos["precipitacion"].umbral,
        "correcciones_tmax_tmin": n_corr,
        "valores_qc_retirados": banderas_qc["regla"].value_counts().to_dict(),
        "test_publico_local": test_local,
        "resumen_relleno": serie.groupby(["variable", "bandera"]).size().unstack(fill_value=0).to_dict("index"),
    }
    (salida / "metricas.json").write_text(json.dumps(metricas, ensure_ascii=False, indent=2, default=str),
                                          encoding="utf-8")
    est.to_csv(salida / "estaciones.csv", index=False)
    _reporte_md(metricas, salida / "reporte_metricas.md")
    print(f"Listo en {time.time() - inicio:.0f} s -> {salida}/")
    return metricas


def _reporte_md(m, ruta):
    r = pd.DataFrame(m["resultados_prueba"])
    lineas = ["# Reporte de métricas (conjunto de prueba con huecos artificiales)", ""]
    for v in cfg.VARIABLES:
        lineas += [f"## {v}", ""]
        cols = ["clase", "metodo", "n", "mae", "rmse", "bias", "kge"]
        if v == "precipitacion":
            cols += ["pod", "far"]
        cols += ["cobertura", "ancho_medio", "pct_no_estimable"]
        sub = r[r.variable == v].reindex(columns=cols)
        try:
            tabla = sub.to_markdown(index=False)
        except ImportError:
            tabla = "```\n" + sub.to_string(index=False) + "\n```"
        lineas += [tabla, ""]
    lineas += ["## Método recomendado por tipo de hueco", "", "```", json.dumps(m["metodo_recomendado"], indent=2), "```"]
    if m.get("test_publico_local"):
        lineas += ["", "## test_publico (calificación local, solo datos sintéticos)", "", "```",
                   json.dumps(m["test_publico_local"], indent=2, ensure_ascii=False), "```"]
    Path(ruta).write_text("\n".join(lineas), encoding="utf-8")
