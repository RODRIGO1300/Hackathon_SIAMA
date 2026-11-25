"""Capas del mapa de Guanajuato: lluvia, calor, heladas y agua para el cultivo.

Cada estación aporta su valor de la temporada (o del mes) elegida, comparado con lo normal de esos mismos meses.
Entre estaciones, el valor se ESTIMA con distancia inversa al cuadrado (IDW) sobre una cuadrícula de ~3 km.
Lejos de cualquier estación (más de RADIO_KM) no se pinta: no hay información para decir algo.
Limitación declarada: la interpolación no usa el relieve (no hay modelo de elevación en el paquete), así que
en sierras la temperatura estimada entre estaciones es menos confiable.
"""
import numpy as np
import pandas as pd

from . import agro, cultivos

RESOLUCION = 0.025      # grados (~2.7 km)
RADIO_KM = 25.0         # distancia máxima a la estación más cercana para pintar una celda
MARGEN = 0.12           # grados alrededor de las estaciones
CAPAS = ("lluvia", "calor", "heladas", "agua")


COLUMNAS = ("lluvia", "tmax", "et0", "heladas", "medidos")


class Estacion:
    """Valores mensuales de una estación en diccionarios, para consultas rápidas."""

    def __init__(self, g, ultimo):
        self.ultimo = ultimo
        self.valores = {c: {k: float(v) for k, v in g[c].dropna().items()} for c in COLUMNAS}
        self.suma, self.cuenta = {}, {}
        for c in COLUMNAS:
            for (a, m), v in self.valores[c].items():
                self.suma[(c, m)] = self.suma.get((c, m), 0.0) + v
                self.cuenta[(c, m)] = self.cuenta.get((c, m), 0) + 1
        self.anios = sorted({a for a, _ in self.valores["lluvia"]})

    def valor(self, a, m, col):
        return self.valores[col].get((a, m))

    def normal(self, col, m, excluir):
        """Promedio del mes en los demás años (sin contar `excluir`)."""
        s, n = self.suma.get((col, m), 0.0), self.cuenta.get((col, m), 0)
        x = self.valor(excluir, m, col)
        if x is not None:
            s, n = s - x, n - 1
        return s / n if n > 0 else None


def tablas_mensuales(serie, est):
    """{clave: Estacion} para todas las estaciones."""
    salida = {}
    for e in est.itertuples():
        s = serie.loc[e.clave].reset_index() if isinstance(serie.index, pd.MultiIndex) else serie[serie["clave"] == e.clave]
        if s.empty:
            continue
        d = agro.tabla_diaria(s, e.latitud)
        completos = d[["precipitacion", "tmax", "tmin"]].notna().all(axis=1)
        if not completos.any():
            continue
        ultimo = d.index[completos].max()
        salida[e.clave] = Estacion(agro._tabla_mensual(d[d.index <= ultimo]), ultimo)
    return salida


def valores_estacion(g, celdas):
    """Valores de la estación en las celdas (año, mes); None si falta algún mes de esa variable."""
    def todos(col):
        vs = [g.valor(a, m, col) for a, m in celdas]
        return None if any(v is None for v in vs) else vs

    def normales(col):
        vs = [g.normal(col, m, a) for a, m in celdas]
        return None if any(v is None for v in vs) else vs

    ll, lln, tx, txn = todos("lluvia"), normales("lluvia"), todos("tmax"), normales("tmax")
    he, hen, et = todos("heladas"), normales("heladas"), todos("et0")
    med = [g.valor(a, m, "medidos") for a, m in celdas]
    med = [v for v in med if v is not None]
    out = {"lluvia": None, "lluvia_normal": None, "tmax": None, "tmax_normal": None, "heladas": None,
           "heladas_normal": None, "evaporacion": None,
           "pct_medido": round(100 * float(np.mean(med))) if med else None}
    if ll and lln:
        out["lluvia"], out["lluvia_normal"] = round(sum(ll), 1), round(sum(lln), 1)
    if tx and txn:
        out["tmax"], out["tmax_normal"] = round(float(np.mean(tx)), 1), round(float(np.mean(txn)), 1)
    if he and hen:
        out["heladas"], out["heladas_normal"] = int(sum(he)), round(sum(hen), 1)
    if ll and et:
        out["evaporacion"] = round(sum(et), 1)
    return out


def indicadores(v):
    """Valor de cada capa para una estación."""
    lluvia = None
    if v["lluvia"] is not None:
        n = v["lluvia_normal"]
        lluvia = round(100 * v["lluvia"] / n) if n >= 10 else (100 if v["lluvia"] < 10 else 200)
    return {
        "lluvia": lluvia,
        "calor": round(v["tmax"] - v["tmax_normal"], 1) if v["tmax"] is not None else None,
        "heladas": v["heladas"],
        "agua": round(v["lluvia"] - v["evaporacion"]) if v["lluvia"] is not None and v["evaporacion"] is not None else None,
    }


def _distancias_km(lat_c, lon_c, lat_e, lon_e):
    lat_c, lon_c, lat_e, lon_e = map(np.radians, (lat_c, lon_c, lat_e, lon_e))
    dlat = lat_c[:, None] - lat_e[None, :]
    dlon = lon_c[:, None] - lon_e[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat_c)[:, None] * np.cos(lat_e)[None, :] * np.sin(dlon / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def cuadricula(est, valores, decimales=1):
    """IDW de los valores por estación sobre una cuadrícula. Devuelve dict con origen, paso y valores (None = sin pintar)."""
    lat_e = est["latitud"].to_numpy(float)
    lon_e = est["longitud"].to_numpy(float)
    lat0, lat1 = lat_e.min() - MARGEN, lat_e.max() + MARGEN
    lon0, lon1 = lon_e.min() - MARGEN, lon_e.max() + MARGEN
    lats = np.arange(lat1, lat0, -RESOLUCION)          # de norte a sur (filas de la imagen)
    lons = np.arange(lon0, lon1, RESOLUCION)
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    v = np.array([np.nan if x is None else x for x in valores], float)
    ok = ~np.isnan(v)
    out = {"norte": float(lat1 + RESOLUCION / 2), "sur": float(lats[-1] - RESOLUCION / 2),
           "oeste": float(lon0 - RESOLUCION / 2), "este": float(lons[-1] + RESOLUCION / 2),
           "filas": len(lats), "columnas": len(lons), "valores": [None] * (len(lats) * len(lons)), "cercania": []}
    if not ok.any():
        return out
    D = _distancias_km(LA.ravel(), LO.ravel(), lat_e[ok], lon_e[ok])
    w = 1.0 / np.maximum(D, 0.5) ** 2
    z = (w * v[ok]).sum(axis=1) / w.sum(axis=1)
    dmin = D.min(axis=1)
    z[dmin > RADIO_KM] = np.nan
    out["valores"] = [None if np.isnan(x) else round(float(x), decimales) for x in z]
    # Cercanía a la estación más cercana (1 = encima de la estación, 0 = en el límite): sirve para desvanecer
    out["cercania"] = [None if d > RADIO_KM else round(1 - d / RADIO_KM, 2) for d in dmin]
    return out


def temporadas_disponibles(tablas):
    vistas = {}
    for g in tablas.values():
        if not g.anios:
            continue
        con_lluvia = g.valores["lluvia"]
        for clave in cultivos.CICLOS:
            y_max = agro._anio_inicio_reciente(clave, g.ultimo)
            for ys in range(g.anios[0] - 1, y_max + 1):
                con = [c for c in agro._ciclo_celdas(clave, ys) if c in con_lluvia]
                if con:
                    fin = max(con)
                    previo = vistas.get((clave, ys))
                    vistas[(clave, ys)] = max(previo, fin) if previo else fin
    lista = [{"ciclo": c, "inicio": y, "etiqueta": agro._etiqueta_ciclo(c, y), "_orden": fin}
             for (c, y), fin in vistas.items()]
    lista.sort(key=lambda t: (t["_orden"], t["ciclo"] == "otono_invierno"), reverse=True)
    for t in lista:
        t.pop("_orden")
    return lista


def mapa(tablas, est, temporada=None, inicio=None, mes=None):
    disponibles = temporadas_disponibles(tablas)
    if not disponibles:
        raise ValueError("No hay temporadas con datos")
    elegida = next((t for t in disponibles if t["ciclo"] == temporada and t["inicio"] == inicio), None) or disponibles[0]
    clave, y0 = elegida["ciclo"], elegida["inicio"]
    todas = agro._ciclo_celdas(clave, y0)
    # Solo meses ya terminados con datos (en una temporada en curso, lo que va)
    ultimo = max(g.ultimo for g in tablas.values())
    fin_de_mes = lambda a, m: pd.Timestamp(a, m, 1) + pd.offsets.MonthEnd(0)
    con_datos = [(a, m) for a, m in todas if fin_de_mes(a, m) <= ultimo]
    sin_datos = [(a, m) for a, m in todas if (a, m) not in con_datos]
    celdas = con_datos
    if mes:
        celdas = [c for c in todas if c[1] == mes]
    est = est.set_index("clave") if "clave" in est.columns else est
    filas = []
    for c, g in tablas.items():
        v = valores_estacion(g, celdas)
        e = est.loc[c]
        filas.append({"clave": c, "nombre": e["nombre"], "municipio": e["municipio"], "latitud": float(e["latitud"]),
                      "longitud": float(e["longitud"]), "altitud": float(e["altitud"]),
                      **v, "capas": indicadores(v)})
    est_df = pd.DataFrame(filas)
    capas = {c: cuadricula(est_df, [f["capas"][c] for f in filas], 0 if c in ("lluvia", "agua") else 1) for c in CAPAS}
    return {"temporada": {**elegida, "meses": [{"anio": a, "mes": m} for a, m in celdas],
                          "meses_sin_datos": [{"anio": a, "mes": m} for a, m in sin_datos],
                          "mes": mes if mes and any(m == mes for _, m in celdas) else None},
            "temporadas": disponibles, "estaciones": filas, "capas": capas,
            "radio_km": RADIO_KM, "nota": "Las zonas de color entre estaciones son estimadas por distancia; "
            "los puntos son las estaciones. No se pinta a más de 25 km de una estación."}
