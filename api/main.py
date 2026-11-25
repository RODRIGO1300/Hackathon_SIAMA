"""API REST del módulo de relleno de huecos para SIAMA Web.

Ejecutar:  uvicorn api.main:app --reload
Documentación interactiva (OpenAPI): http://localhost:8000/docs
"""
import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

RAIZ = Path(__file__).resolve().parent.parent
SALIDAS = Path(os.environ.get("SIAMA_SALIDAS", RAIZ / "salidas"))
Variable = Literal["precipitacion", "tmax", "tmin"]
UNIDADES = {"precipitacion": "mm", "tmax": "°C", "tmin": "°C"}
NOMBRES = {"precipitacion": "Precipitación diaria", "tmax": "Temperatura máxima", "tmin": "Temperatura mínima"}

app = FastAPI(
    title="SIAMA · Datos climatológicos sin huecos",
    version="0.1.0",
    description=(
        "Diagnóstico de vacíos, series completadas con incertidumbre y métricas del modelo. "
        "Regla: ningún dato estimado se presenta como observado; cada registro trae `origen` y `bandera`."
    ),
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@lru_cache
def datos():
    if not (SALIDAS / "series_completadas.csv.gz").exists():
        raise RuntimeError("No hay salidas. Ejecute primero: python -m siama_gaps run")
    serie = pd.read_csv(SALIDAS / "series_completadas.csv.gz", dtype={"clave": str},
                        keep_default_na=False, na_values=[""], low_memory=False)
    for c in ("metodo", "motivo_no_estimable", "qc"):
        serie[c] = serie[c].fillna("")
    serie = serie.set_index(["clave", "variable"]).sort_index()
    est = pd.read_csv(SALIDAS / "estaciones.csv", dtype={"clave": str}).set_index("clave")
    diag = pd.read_csv(SALIDAS / "diagnostico_estaciones.csv", dtype={"clave": str})
    huecos = pd.read_csv(SALIDAS / "huecos.csv", dtype={"clave": str})
    vec = pd.read_csv(SALIDAS / "vecinos.csv", dtype={"clave": str, "vecino": str})
    homog = pd.read_csv(SALIDAS / "homogeneidad.csv", dtype={"clave": str})
    qc = pd.read_csv(SALIDAS / "qc_banderas.csv", dtype={"clave": str})
    metr = json.loads((SALIDAS / "metricas.json").read_text(encoding="utf-8"))
    return {"serie": serie, "est": est, "diag": diag, "huecos": huecos, "vec": vec,
            "homog": homog, "qc": qc, "metricas": metr}


def _limpio(df):
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _estacion(clave):
    d = datos()
    if clave not in d["est"].index:
        raise HTTPException(404, f"Estación {clave} no encontrada")
    e = d["est"].loc[clave]
    return {"clave": clave, "nombre": e["nombre"], "municipio": e["municipio"],
            "latitud": float(e["latitud"]), "longitud": float(e["longitud"]),
            "altitud": float(e["altitud"]), "estado_operativo": e["estado_operativo"]}


@app.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/web/demo.html")


@app.get("/api/v1/estaciones", tags=["Estaciones"],
         summary="Estaciones en GeoJSON con % de vacíos por variable (para el mapa)")
def estaciones():
    d = datos()
    piv = d["diag"].pivot(index="clave", columns="variable", values="pct_faltante")
    feats = []
    for clave, e in d["est"].iterrows():
        props = _estacion(clave)
        props.update({f"pct_faltante_{v}": float(piv.loc[clave, v]) for v in piv.columns})
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Point", "coordinates": [float(e["longitud"]), float(e["latitud"])]}})
    return {"type": "FeatureCollection", "features": feats}


@app.get("/api/v1/estaciones/{clave}/diagnostico", tags=["Obligatorios"],
         summary="Diagnóstico de vacíos de una estación")
def diagnostico(clave: str, incluir_huecos: bool = True):
    d = datos()
    info = _estacion(clave)
    res = d["diag"][d["diag"].clave == clave].drop(columns="clave")
    out = {"estacion": info, "variables": _limpio(res)}
    if incluir_huecos:
        out["huecos"] = _limpio(d["huecos"][d["huecos"].clave == clave].drop(columns="clave"))
    out["vecinos_usados"] = _limpio(d["vec"][d["vec"].clave == clave].drop(columns="clave"))
    out["control_calidad"] = d["qc"][d["qc"].clave == clave].groupby(["variable", "regla"]).size() \
        .rename("n").reset_index().to_dict("records")
    out["homogeneidad"] = _limpio(d["homog"][d["homog"].clave == clave].drop(columns="clave"))
    return out


@app.get("/api/v1/estaciones/{clave}/serie", tags=["Obligatorios"],
         summary="Serie completada por estación y periodo (observado vs. estimado, con intervalo)")
def serie(clave: str, variable: Variable = "precipitacion",
          desde: Optional[date] = Query(None, description="AAAA-MM-DD"),
          hasta: Optional[date] = Query(None, description="AAAA-MM-DD"),
          solo_estimados: bool = False):
    d = datos()
    info = _estacion(clave)
    try:
        s = d["serie"].loc[(clave, variable)]
    except KeyError:
        raise HTTPException(404, "Sin datos para esa estación/variable")
    if desde:
        s = s[s["fecha"] >= desde.isoformat()]
    if hasta:
        s = s[s["fecha"] <= hasta.isoformat()]
    if solo_estimados:
        s = s[s["origen"] != "observado"]
    s = s.replace({np.nan: None})
    return {
        "estacion": info, "variable": variable, "nombre_variable": NOMBRES[variable],
        "unidad": UNIDADES[variable], "nivel_intervalo": d["metricas"]["nivel_intervalo"],
        "conteo": s["bandera"].value_counts().to_dict(),
        "datos": _limpio(s[["fecha", "valor", "li", "ls", "origen", "bandera", "metodo", "motivo_no_estimable", "qc"]]),
    }


@app.get("/api/v1/metricas", tags=["Obligatorios"], summary="Métricas del modelo por variable, tipo de hueco y método")
def metricas(variable: Optional[Variable] = None,
             clase: Optional[Literal["corto", "medio", "largo", "todas"]] = None,
             metodo: Optional[str] = None):
    m = datos()["metricas"]
    res = [r for r in m["resultados_prueba"]
           if (variable is None or r["variable"] == variable) and (clase is None or r["clase"] == clase)
           and (metodo is None or r["metodo"] == metodo)]
    return {"nivel_intervalo": m["nivel_intervalo"], "configuracion": m["configuracion"],
            "metodo_recomendado": m["metodo_recomendado"], "nombres_metodo": m["nombres_metodo"],
            "cuantil_conformal": m["cuantil_conformal"], "por_bandera": m["por_bandera"],
            "puntos_validacion": m["puntos_validacion"], "resultados": res,
            "generado": m["generado"]}


@app.get("/api/v1/estaciones/{clave}/resumen", tags=["Asistente IA"],
         summary="Resumen en lenguaje natural (para el asistente de IA de SIAMA)")
def resumen(clave: str):
    d = datos()
    info = _estacion(clave)
    diag = d["diag"][d["diag"].clave == clave].set_index("variable")
    partes = []
    for v in ["precipitacion", "tmax", "tmin"]:
        r = diag.loc[v]
        s = d["serie"].loc[(clave, v)]["bandera"].value_counts()
        partes.append(
            f"{NOMBRES[v]}: {100 - r['pct_faltante']:.1f}% de días observados; "
            f"{int(r['huecos_cortos'])} huecos cortos, {int(r['huecos_medios'])} medios y {int(r['huecos_largos'])} largos "
            f"(el mayor de {int(r['hueco_mas_largo'])} días). Se estimaron {int(s.get('estimado_alta', 0) + s.get('estimado_baja', 0))} días "
            f"y {int(s.get('no_estimable', 0))} no se pudieron estimar con confianza.")
    h = d["homog"][(d["homog"].clave == clave) & d["homog"].cambio_detectado]
    if len(h):
        partes.append("Atención: posible cambio abrupto en " + ", ".join(
            f"{NOMBRES[r.variable].lower()} desde {r.fecha_cambio}" for r in h.itertuples()) + ".")
    texto = f"Estación {info['nombre']} ({info['municipio']}, {info['altitud']:.0f} m). " + " ".join(partes)
    return {"estacion": info, "texto": texto}


@app.get("/api/v1/salud", tags=["Operación"])
def salud():
    d = datos()
    return {"ok": True, "estaciones": len(d["est"]), "generado": d["metricas"]["generado"]}


app.mount("/web", StaticFiles(directory=RAIZ / "web", html=True), name="web")
