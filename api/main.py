"""API REST del módulo de relleno de huecos para SIAMA Web.

Ejecutar:  uvicorn api.main:app --reload
Documentación interactiva (OpenAPI): http://localhost:8000/docs

Integraciones opcionales con IBM (ver ibm/README.md):
  - watsonx.ai (IBM Granite) redacta el resumen y responde preguntas del asistente de IA.
  - IBM Cloud Databases for PostgreSQL: si SIAMA_DATABASE_URL está definida, los datos se leen de PostgreSQL.
Sin esas variables, la API funciona igual leyendo los archivos de salidas/.
"""
import gzip
import threading
import io
import json
import os
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from siama_gaps.entorno import cargar_env

from . import watsonx

cargar_env()
RAIZ = Path(__file__).resolve().parent.parent
SALIDAS = Path(os.environ.get("SIAMA_SALIDAS", RAIZ / "salidas"))
Variable = Literal["precipitacion", "tmax", "tmin"]
UNIDADES = {"precipitacion": "mm", "tmax": "°C", "tmin": "°C"}
NOMBRES = {"precipitacion": "Precipitación diaria", "tmax": "Temperatura máxima", "tmin": "Temperatura mínima"}

app = FastAPI(
    title="Agro SIAMA · API de datos agroclimáticos",
    version="0.1.0",
    description=(
        "Diagnóstico de vacíos, series completadas con incertidumbre y métricas del modelo. "
        "Regla: ningún dato estimado se presenta como observado; cada registro trae `origen` y `bandera`."
    ),
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
FUENTE = "postgresql" if os.environ.get("SIAMA_DATABASE_URL") else "archivos"


def _abridor():
    """Devuelve una función nombre -> BytesIO, leyendo de PostgreSQL o de los archivos de salidas/."""
    if FUENTE == "postgresql":
        from siama_gaps import postgres
        crudo = postgres.leer_para_api()
        return lambda nombre: io.BytesIO(crudo[nombre])
    if not (SALIDAS / "series_completadas.csv.gz").exists():
        raise RuntimeError("No hay salidas. Ejecute primero: python -m siama_gaps run")

    def abrir(nombre):
        if nombre == "series_completadas.csv":
            return io.BytesIO(gzip.decompress((SALIDAS / "series_completadas.csv.gz").read_bytes()))
        return io.BytesIO((SALIDAS / nombre).read_bytes())
    return abrir


_cache_datos = {"marca": None, "valor": None}


def _marca_salidas():
    """Cambia cuando el pipeline vuelve a escribir resultados (p. ej. tras `python -m siama_gaps actualizar`)."""
    if FUENTE == "postgresql":
        return "postgresql"
    ruta = SALIDAS / "metricas.json"
    return ruta.stat().st_mtime_ns if ruta.exists() else None


def datos():
    """Resultados en memoria; se recargan solos si el pipeline generó resultados nuevos."""
    marca = _marca_salidas()
    if _cache_datos["valor"] is None or marca != _cache_datos["marca"]:
        _cache_datos["valor"], _cache_datos["marca"] = _cargar_datos(), marca
    return _cache_datos["valor"]


def _cargar_datos():
    abrir = _abridor()
    serie = pd.read_csv(abrir("series_completadas.csv"), dtype={"clave": str},
                        keep_default_na=False, na_values=[""], low_memory=False)
    for c in ("metodo", "motivo_no_estimable", "qc"):
        serie[c] = serie[c].fillna("")
    serie = serie.set_index(["clave", "variable"]).sort_index()
    est = pd.read_csv(abrir("estaciones.csv"), dtype={"clave": str}).set_index("clave")
    diag = pd.read_csv(abrir("diagnostico_estaciones.csv"), dtype={"clave": str})
    huecos = pd.read_csv(abrir("huecos.csv"), dtype={"clave": str})
    vec = pd.read_csv(abrir("vecinos.csv"), dtype={"clave": str, "vecino": str})
    homog = pd.read_csv(abrir("homogeneidad.csv"), dtype={"clave": str})
    qc = pd.read_csv(abrir("qc_banderas.csv"), dtype={"clave": str})
    metr = json.loads(abrir("metricas.json").read().decode("utf-8"))
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


@app.get("/agro", include_in_schema=False)
def inicio_agro():
    return RedirectResponse("/web/agro.html")


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


def _resumen_plantilla(clave):
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
    return info, texto


def _contexto_ia(clave, texto):
    """Contexto con datos verificables que se entrega a Granite (no puede citar nada fuera de esto)."""
    d = datos()
    lineas = [texto, "Estado de la estación: " + str(d["est"].loc[clave, "estado_operativo"]) + "."]
    for v in ["precipitacion", "tmax", "tmin"]:
        vec = d["vec"][(d["vec"].clave == clave) & (d["vec"].variable == v)]
        if len(vec):
            nombres = ", ".join(f"{d['est'].loc[r.vecino, 'nombre'] if r.vecino in d['est'].index else r.vecino} "
                                f"a {r.dist_km:.0f} km con correlación {r.correlacion:.2f}" for r in vec.itertuples())
            lineas.append(f"Estaciones vecinas usadas para {NOMBRES[v].lower()}: {nombres}.")
        else:
            lineas.append(f"Para {NOMBRES[v].lower()} no hay estaciones vecinas suficientemente correlacionadas.")
    m = d["metricas"]
    nivel = int(round(100 * m["nivel_intervalo"]))
    for r in m["resultados_prueba"]:
        if r["metodo"] == "recomendado" and r["clase"] == "todas":
            u = UNIDADES[r["variable"]]
            cob = (f", y el intervalo del {nivel}% contuvo el valor real en el {100 * r['cobertura']:.0f}% de los casos"
                   if r.get("cobertura") is not None else "")
            lineas.append(f"Validación del modelo para {NOMBRES[r['variable']].lower()} (todas las estaciones, "
                          f"huecos artificiales): error medio absoluto de {r['mae']:.2f} {u}{cob}.")
    lineas.append("Banderas: 'estimado alta' significa que hubo 3 o más vecinos con dato ese día o el hueco era corto; "
                  "'estimado baja' es el resto de estimaciones; 'no estimable' significa que no se publicó valor.")
    return "\n".join(lineas)


_cache_ia = {}


@app.get("/api/v1/estaciones/{clave}/resumen", tags=["Asistente IA"],
         summary="Resumen en lenguaje natural (para el asistente de IA de SIAMA)",
         description="Si watsonx.ai está configurado, el texto lo redacta un modelo IBM Granite a partir de los datos "
                     "de la estación; si no, se usa una plantilla. El campo `fuente` indica cuál se usó.")
def resumen(clave: str, ia: bool = Query(True, description="Usar watsonx.ai si está configurado")):
    info, base = _resumen_plantilla(clave)
    out = {"estacion": info, "texto": base, "texto_plantilla": base, "fuente": "plantilla"}
    w = watsonx.cliente()
    if ia and w.configurado:
        llave = (clave, datos()["metricas"]["generado"], w.modelo)
        try:
            if llave not in _cache_ia:
                _cache_ia[llave] = w.redactar_resumen(_contexto_ia(clave, base))
            out.update(texto=_cache_ia[llave], fuente=f"watsonx.ai · {w.modelo}")
        except watsonx.ErrorWatsonx as e:
            out["aviso"] = f"Se usó la plantilla porque watsonx.ai no respondió: {e}"
    return out


@app.get("/api/v1/estaciones/{clave}/preguntar", tags=["Asistente IA"],
         summary="Pregunta libre sobre una estación, respondida por IBM Granite (watsonx.ai)",
         description="Requiere watsonx.ai configurado. La respuesta se limita a los datos de la estación.")
def preguntar(clave: str, q: str = Query(..., min_length=3, max_length=300, description="Pregunta en español")):
    w = watsonx.cliente()
    if not w.configurado:
        raise HTTPException(503, "El asistente requiere watsonx.ai: defina WATSONX_APIKEY y WATSONX_PROJECT_ID")
    info, base = _resumen_plantilla(clave)
    try:
        texto = w.responder(_contexto_ia(clave, base), q)
    except watsonx.ErrorWatsonx as e:
        raise HTTPException(502, str(e))
    return {"estacion": info, "pregunta": q, "respuesta": texto, "fuente": f"watsonx.ai · {w.modelo}"}


# --- Vista agrícola ---------------------------------------------------------------------------------------
_cache_agro = {}


@app.get("/api/v1/agro/estaciones", tags=["Agro"],
         summary="Estaciones disponibles para la vista agrícola (filtro opcional por municipio)")
def agro_estaciones(municipio: Optional[str] = Query(None, description="Ej. Salamanca")):
    d = datos()
    est = d["est"]
    if municipio:
        est = est[est["municipio"].str.casefold() == municipio.strip().casefold()]
        if est.empty:
            raise HTTPException(404, f"No hay estaciones en el municipio {municipio}")
    return {"municipio": municipio, "estaciones": [_estacion(c) for c in est.index]}


_cache_mapa = {}
_candado_mapa = threading.Lock()


@app.on_event("startup")
def _preparar_mapa():
    import threading

    def trabajo():
        try:
            agro_mapa(None, None, None)
        except Exception:  # el mapa se calculará en la primera consulta
            pass
    threading.Thread(target=trabajo, daemon=True).start()


@app.get("/api/v1/agro/mapa", tags=["Agro"],
         summary="Mapa del estado: lluvia, calor, heladas y agua para el cultivo de una temporada (o un mes)",
         description="Valores por estación y una cuadrícula estimada entre estaciones (distancia inversa). "
                     "No se pinta a más de 25 km de una estación.")
def agro_mapa(ciclo: Optional[Literal["primavera_verano", "otono_invierno"]] = Query(None),
              inicio: Optional[int] = Query(None, description="Año en que empieza la temporada"),
              mes: Optional[int] = Query(None, ge=1, le=12, description="Mes dentro de la temporada")):
    from siama_gaps import mapa
    d = datos()
    gen = d["metricas"]["generado"]
    # Una sola preparación a la vez: si ya se está calculando (p. ej. al arrancar), esta consulta espera
    with _candado_mapa:
        if _cache_mapa.get("generado") != gen or "tablas" not in _cache_mapa:
            tablas = mapa.tablas_mensuales(d["serie"], d["est"].reset_index())
            _cache_mapa.clear()
            _cache_mapa.update(generado=gen, tablas=tablas)
        tablas = _cache_mapa["tablas"]
    llave = (ciclo, inicio, mes)
    if llave not in _cache_mapa:
        try:
            _cache_mapa[llave] = mapa.mapa(tablas, d["est"].reset_index(), ciclo, inicio, mes)
        except ValueError as e:
            raise HTTPException(404, str(e))
    return _cache_mapa[llave]


@app.get("/api/v1/agro/{clave}", tags=["Agro"],
         summary="Indicadores agroclimáticos de una estación para una temporada",
         description="Lluvia de temporada vs. promedio, inicio de lluvias, racha seca, heladas, grados día del "
                     "cultivo, evapotranspiración y balance de agua. Cada bloque informa el % de días medidos.")
def agro_panel(clave: str, anio: Optional[int] = Query(None, description="Temporada; por defecto la más reciente"),
               siembra: Optional[date] = Query(None, description="Fecha de siembra; por defecto el inicio de lluvias"),
               hasta: Optional[date] = Query(None, description="Fecha de corte; por defecto el último dato"),
               ciclo: Optional[Literal["primavera_verano", "otono_invierno"]] = Query(
                   None, description="Temporada agrícola; por defecto la más reciente"),
               inicio: Optional[int] = Query(None, description="Año en que empieza la temporada (p. ej. 2024)")):
    from siama_gaps import agro
    d = datos()
    info = _estacion(clave)
    llave = (clave, anio, siembra, hasta, ciclo, inicio, d["metricas"]["generado"])
    if llave not in _cache_agro:
        serie = d["serie"].loc[clave].reset_index()
        try:
            _cache_agro[llave] = agro.panel(serie, info["latitud"], anio, siembra, hasta, ciclo, inicio)
        except ValueError as e:
            raise HTTPException(404, str(e))
    return {"estacion": info, **_cache_agro[llave]}


@app.get("/api/v1/salud", tags=["Operación"])
def salud():
    d = datos()
    return {"ok": True, "estaciones": len(d["est"]), "generado": d["metricas"]["generado"],
            "fuente_datos": FUENTE, "origen_datos": d["metricas"].get("fuente", {"tipo": "desconocido"}),
            "watsonx": watsonx.cliente().estado()}


app.mount("/web", StaticFiles(directory=RAIZ / "web", html=True), name="web")
