"""Etapa 0: limpieza de los archivos de entrada, antes del control de calidad.

Aquí se corrigen problemas de FORMATO, no de clima: fechas escritas de otra forma, claves con espacios,
texto en campos numéricos, decimales con coma, códigos de valor faltante, filas duplicadas y metadatos
de estaciones (coordenadas invertidas o sin signo, altitudes imposibles).
Los valores físicamente dudosos (lluvia negativa, Tmax < Tmin, atípicos) los revisa después calidad.py.

Regla: nada se corrige ni se descarta sin rastro. Cada acción queda en el registro de limpieza.

Uso independiente:  python -m siama_gaps limpiar --datos datos --salida salidas
"""
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg

# Códigos usados en bases climatológicas para "sin dato"
CODIGOS_FALTANTE = (-99.9, -99.0, -999.0, -9999.0, 9999.0, 999.9)
# En CLICOM, la lluvia "inapreciable" (trazas) se registra con texto: equivale a 0 mm
TEXTO_LLUVIA_INAPRECIABLE = {"inap", "inapreciable", "ip", "t", "tr", "traza", "trazas"}
TEXTO_VACIO = {"", "na", "n/a", "nan", "null", "none", "s/d", "sd", "-", "--"}
# Códigos de faltante escritos con texto (el SMN usa "NULO")
TEXTO_FALTANTE = {"nulo"}
# Nombres alternativos de columnas que se aceptan en series_diarias
ALIAS_COLUMNAS = {"clave_estacion": "clave", "estacion": "clave", "precip": "precipitacion", "precip_mm": "precipitacion",
                  "prec": "precipitacion", "lluvia": "precipitacion", "tmax_c": "tmax", "tmin_c": "tmin",
                  "temp_max": "tmax", "temp_min": "tmin", "evap": "evaporacion", "evap_mm": "evaporacion"}
# Caja que contiene al estado de Guanajuato (con margen de ~10 km)
LAT_GTO = (19.85, 21.95)
LON_GTO = (-102.15, -99.60)
ALTITUD_VALIDA = (0.0, 4000.0)
FORMATOS_FECHA = ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y%m%d"]
ESTADOS = {"operando": "operando", "operativa": "operando", "activa": "operando", "activo": "operando",
           "suspendida": "suspendida", "suspendido": "suspendida", "inactiva": "suspendida",
           "inactivo": "suspendida", "cerrada": "suspendida"}


class Registro:
    """Acumula cada acción de limpieza: un resumen por regla y el detalle fila por fila."""

    def __init__(self):
        self.resumen, self.detalle = [], []

    def anotar(self, archivo, regla, accion, filas, campo="", valores=None, fechas=None, claves=None):
        n = int(len(filas)) if not np.isscalar(filas) else int(filas)
        if n == 0:
            return
        ejemplo = ""
        if valores is not None and len(valores):
            ejemplo = str(list(pd.Series(valores).astype(str).unique()[:3]))
        self.resumen.append({"archivo": archivo, "regla": regla, "campo": campo, "accion": accion,
                             "filas": n, "ejemplo": ejemplo})
        if valores is not None:
            self.detalle.append(pd.DataFrame({
                "archivo": archivo, "fecha": fechas if fechas is not None else "",
                "clave": claves if claves is not None else "", "campo": campo,
                "valor_original": pd.Series(valores).astype(str).to_numpy(), "regla": regla, "accion": accion}))

    def tablas(self):
        resumen = pd.DataFrame(self.resumen, columns=["archivo", "regla", "campo", "accion", "filas", "ejemplo"])
        detalle = (pd.concat(self.detalle, ignore_index=True) if self.detalle else
                   pd.DataFrame(columns=["archivo", "fecha", "clave", "campo", "valor_original", "regla", "accion"]))
        return resumen, detalle


# --- utilidades -------------------------------------------------------------------------------------------
def _texto(s):
    """Serie de texto sin espacios extra; los vacíos quedan como cadena vacía."""
    return s.astype("string").fillna("").str.strip().str.replace(r"\s+", " ", regex=True)


def _clave(s):
    """Normaliza claves: sin espacios y sin el '.0' que deja una hoja de cálculo."""
    return _texto(s).str.replace(r"\.0+$", "", regex=True)


def _numero(s, archivo, campo, reg, es_lluvia=False, fechas=None, claves=None):
    """Convierte texto a número registrando lo que no lo era. Devuelve una serie float."""
    t = _texto(s)
    bajo = t.str.lower()
    vacio = bajo.isin(TEXTO_VACIO)
    coma = t.str.fullmatch(r"-?\d+,\d+").fillna(False)
    t = t.where(~coma, t.str.replace(",", ".", regex=False))
    reg.anotar(archivo, "decimal_con_coma", "se cambió la coma por punto", np.flatnonzero(coma), campo,
               s[coma], fechas[coma] if fechas is not None else None, claves[coma] if claves is not None else None)
    x = pd.to_numeric(t.where(~vacio, None), errors="coerce").astype(float)
    if es_lluvia:
        inap = bajo.isin(TEXTO_LLUVIA_INAPRECIABLE)
        x[inap] = 0.0
        reg.anotar(archivo, "lluvia_inapreciable", "texto de trazas convertido a 0 mm", np.flatnonzero(inap), campo,
                   s[inap], fechas[inap] if fechas is not None else None, claves[inap] if claves is not None else None)
    else:
        inap = pd.Series(False, index=s.index)
    nulo = bajo.isin(TEXTO_FALTANTE)
    texto = x.isna() & ~vacio & ~inap & ~nulo
    reg.anotar(archivo, "valor_no_numerico", "se dejó como faltante", np.flatnonzero(texto), campo,
               s[texto], fechas[texto] if fechas is not None else None, claves[texto] if claves is not None else None)
    codigo = x.isin(CODIGOS_FALTANTE) | np.isclose(x, cfg.CODIGO_FALTANTE) | nulo
    reg.anotar(archivo, "codigo_de_faltante", "se dejó como faltante", np.flatnonzero(codigo), campo,
               s[codigo], fechas[codigo] if fechas is not None else None, claves[codigo] if claves is not None else None)
    x[codigo] = np.nan
    return x


def _fechas(s, reg, archivo, claves):
    t = _texto(s)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    usados = {}
    for fmt in FORMATOS_FECHA:
        falta = out.isna() & (t != "")
        if not falta.any():
            break
        conv = pd.to_datetime(t[falta], format=fmt, errors="coerce")
        out[falta] = conv
        usados[fmt] = int(conv.notna().sum())
    otros = {f: n for f, n in usados.items() if n and f != FORMATOS_FECHA[0]}
    for fmt, n in otros.items():
        reg.anotar(archivo, "fecha_en_otro_formato", f"se interpretó como {fmt}", n, "fecha")
    malas = out.isna()
    reg.anotar(archivo, "fecha_ilegible", "fila descartada", np.flatnonzero(malas), "fecha", s[malas],
               s[malas], claves[malas])
    return out


# --- estaciones -------------------------------------------------------------------------------------------
def limpiar_estaciones(est, reg):
    a = "estaciones.csv"
    est = est.copy()
    faltan = {"clave", "nombre", "municipio", "latitud", "longitud", "altitud", "estado_operativo"} - set(est.columns)
    if faltan:
        raise ValueError(f"{a}: faltan columnas {sorted(faltan)}")
    est["clave"] = _clave(est["clave"])
    sin = est["clave"] == ""
    reg.anotar(a, "clave_vacia", "estación descartada", np.flatnonzero(sin), "clave", est.loc[sin, "nombre"])
    est = est[~sin]
    dup = est["clave"].duplicated(keep="first")
    reg.anotar(a, "clave_duplicada", "se conservó la primera aparición", np.flatnonzero(dup), "clave",
               est.loc[dup, "clave"])
    est = est[~dup].copy()
    for c in ("nombre", "municipio"):
        antes = est[c].astype("string").fillna("")
        est[c] = _texto(est[c])
        cambio = antes != est[c]
        reg.anotar(a, "espacios_de_mas", "se quitaron espacios sobrantes", np.flatnonzero(cambio), c, antes[cambio])
    for c in ("latitud", "longitud", "altitud"):
        est[c] = _numero(est[c], a, c, reg)
    lat, lon = est["latitud"], est["longitud"]
    sin_signo = lon.between(-LON_GTO[1], -LON_GTO[0])
    reg.anotar(a, "longitud_sin_signo", "se agregó el signo negativo", np.flatnonzero(sin_signo), "longitud",
               lon[sin_signo])
    est.loc[sin_signo, "longitud"] = -lon[sin_signo]
    lat, lon = est["latitud"], est["longitud"]
    invertidas = lat.between(*LON_GTO) & lon.between(*LAT_GTO)
    reg.anotar(a, "latitud_longitud_invertidas", "se intercambiaron", np.flatnonzero(invertidas), "latitud",
               est.loc[invertidas, "clave"])
    est.loc[invertidas, ["latitud", "longitud"]] = est.loc[invertidas, ["longitud", "latitud"]].to_numpy()
    sin_coord = est["latitud"].isna() | est["longitud"].isna()
    reg.anotar(a, "sin_coordenadas", "estación descartada (no se pueden buscar vecinas)",
               np.flatnonzero(sin_coord), "latitud", est.loc[sin_coord, "clave"])
    est = est[~sin_coord].copy()
    fuera = ~(est["latitud"].between(*LAT_GTO) & est["longitud"].between(*LON_GTO))
    reg.anotar(a, "fuera_de_guanajuato", "se conservó; revisar coordenadas", np.flatnonzero(fuera), "latitud",
               est.loc[fuera, "clave"])
    alt_mala = ~est["altitud"].between(*ALTITUD_VALIDA)
    if alt_mala.any():
        mediana = float(est.loc[~alt_mala, "altitud"].median())
        reg.anotar(a, "altitud_faltante_o_imposible", f"se usó la mediana de las estaciones ({mediana:.0f} m)",
                   np.flatnonzero(alt_mala), "altitud", est.loc[alt_mala, "clave"])
        est.loc[alt_mala, "altitud"] = mediana
    edo = _texto(est["estado_operativo"]).str.lower()
    norm = edo.map(ESTADOS)
    raro = norm.isna()
    reg.anotar(a, "estado_operativo_desconocido", "se marcó como 'desconocido'", np.flatnonzero(raro),
               "estado_operativo", est.loc[raro, "estado_operativo"])
    est["estado_operativo"] = norm.fillna("desconocido")
    return est.sort_values("clave").reset_index(drop=True)


# --- series diarias ---------------------------------------------------------------------------------------
def limpiar_series(df, claves_validas, reg, hoy=None):
    a = "series_diarias"
    faltan = {"fecha", "clave", *cfg.VARIABLES} - set(df.columns)
    if faltan:
        raise ValueError(f"{a}: faltan columnas {sorted(faltan)}")
    n0 = len(df)
    df = df.reset_index(drop=True)
    clave = _clave(df["clave"])
    fecha = _fechas(df["fecha"], reg, a, clave)
    out = pd.DataFrame({"fecha": fecha, "clave": clave})
    for v in cfg.VARIABLES:
        out[v] = _numero(df[v], a, v, reg, es_lluvia=(v == "precipitacion"),
                         fechas=df["fecha"].astype("string"), claves=clave)
    out = out[out["fecha"].notna()]

    hoy = pd.Timestamp(hoy or date.today())
    futura = out["fecha"] > hoy
    reg.anotar(a, "fecha_futura", "fila descartada", np.flatnonzero(futura), "fecha",
               out.loc[futura, "fecha"].dt.date, out.loc[futura, "fecha"].dt.date, out.loc[futura, "clave"])
    out = out[~futura]

    desconocida = ~out["clave"].isin(claves_validas)
    reg.anotar(a, "estacion_desconocida", "fila descartada (la clave no está en estaciones.csv)",
               np.flatnonzero(desconocida), "clave", out.loc[desconocida, "clave"],
               out.loc[desconocida, "fecha"].dt.date, out.loc[desconocida, "clave"])
    out = out[~desconocida]

    # Duplicados fecha + estación: se combinan; si dos registros dicen cosas distintas, ese valor queda faltante
    dup = out.duplicated(["fecha", "clave"], keep=False)
    if dup.any():
        d = out[dup]
        g = d.groupby(["fecha", "clave"])
        n_grupos = g.ngroups
        unico = out[~dup]
        comb = g[cfg.VARIABLES].first().reset_index()
        distintos = g[cfg.VARIABLES].nunique(dropna=True).reset_index(drop=True)
        for v in cfg.VARIABLES:
            choque = (distintos[v] > 1).to_numpy()
            if choque.any():
                vals = g[v].apply(lambda x: "/".join(map(str, x.dropna().unique()))).to_numpy()[choque]
                reg.anotar(a, "duplicado_contradictorio", "el valor se dejó como faltante", np.flatnonzero(choque), v,
                           vals, comb.loc[choque, "fecha"].dt.date, comb.loc[choque, "clave"])
                comb.loc[choque, v] = np.nan
        reg.anotar(a, "fila_duplicada", "se combinaron en un solo registro", int(dup.sum()) - n_grupos, "fecha")
        out = pd.concat([unico, comb], ignore_index=True)

    vacia = out[cfg.VARIABLES].isna().all(axis=1)
    reg.anotar(a, "fila_sin_ningun_dato", "fila descartada (el hueco se conserva en el calendario)",
               int(vacia.sum()), "")
    out = out[~vacia].sort_values(["fecha", "clave"]).reset_index(drop=True)
    return out, {"filas_leidas": n0, "filas_finales": len(out)}


# --- lectura cruda y punto de entrada ---------------------------------------------------------------------
def _leer_crudo(ruta):
    ruta = Path(ruta)
    if ruta.suffix == ".parquet":
        return pd.read_parquet(ruta).astype("string")
    return pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def limpiar(datos, hoy=None):
    """Lee estaciones y series de `datos/`, las limpia y devuelve (estaciones, series, registro, conteos)."""
    datos = Path(datos)
    reg = Registro()
    est = limpiar_estaciones(_leer_crudo(datos / "estaciones.csv"), reg)
    ruta = datos / "series_diarias.parquet"
    crudo = _leer_crudo(ruta if ruta.exists() else datos / "series_diarias.csv")
    crudo.columns = [re.sub(r"\s+", "_", c.strip().lower()) for c in crudo.columns]
    renombrar = {c: ALIAS_COLUMNAS[c] for c in crudo.columns if c in ALIAS_COLUMNAS and ALIAS_COLUMNAS[c] not in crudo.columns}
    if renombrar:
        reg.anotar("series_diarias", "columna_con_otro_nombre", "se renombró: " + ", ".join(f"{a}→{b}" for a, b in renombrar.items()),
                   len(renombrar), "")
        crudo = crudo.rename(columns=renombrar)
    series, conteo = limpiar_series(crudo, set(est["clave"]), reg, hoy)
    conteo["estaciones"] = len(est)
    return est, series, reg, conteo


def guardar(reg, conteo, salida):
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    resumen, detalle = reg.tablas()
    resumen.to_csv(salida / "limpieza_registro.csv", index=False)
    detalle.to_csv(salida / "limpieza_detalle.csv", index=False)
    lineas = ["# Limpieza de datos (etapa 0)", "",
              f"- Estaciones válidas: **{conteo['estaciones']}**",
              f"- Filas leídas de la serie diaria: **{conteo['filas_leidas']:,}**",
              f"- Filas después de limpiar: **{conteo['filas_finales']:,}**", ""]
    if len(resumen):
        lineas += ["| Archivo | Problema | Campo | Qué se hizo | Filas | Ejemplo |", "|---|---|---|---|---|---|"]
        lineas += [f"| {r.archivo} | {r.regla} | {r.campo} | {r.accion} | {r.filas:,} | {r.ejemplo} |"
                   for r in resumen.itertuples()]
    else:
        lineas.append("No se encontraron problemas de formato.")
    lineas += ["", "Detalle fila por fila: `limpieza_detalle.csv`. Los valores físicamente dudosos se revisan "
               "después, en el control de calidad (`qc_banderas.csv`)."]
    (salida / "limpieza_reporte.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen
