"""Indicadores agroclimáticos para productores, calculados sobre las series completadas.

Todos los cálculos usan la serie sin huecos, pero cada indicador informa qué parte se basa en días
MEDIDOS y qué parte en días ESTIMADOS (regla de SIAMA: lo estimado nunca se presenta como medido).

Indicadores (temporal de primavera-verano, 1 de junio a 31 de octubre):
  - Lluvia acumulada de la temporada vs. el promedio de los años disponibles.
  - Inicio de lluvias: primer día desde el 1 de mayo con >= 20 mm en 3 días y sin una racha seca
    de 10 días o más (< 1 mm/día) en los 30 días siguientes (definición agronómica usual).
  - Racha seca más larga (junio a septiembre; la "canícula").
  - Heladas (Tmin <= 0 °C): última de primavera, primera de otoño y periodo libre de heladas.
  - Calor útil para el cultivo: grados día de desarrollo (método para maíz: base 10 °C, tope 30 °C).
  - Días de calor extremo (Tmax >= 35 °C).
  - Evapotranspiración de referencia (Hargreaves-Samani, FAO-56 ec. 52) y balance lluvia - ET0.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

BASE_GDD, TOPE_GDD = 10.0, 30.0
UMBRAL_HELADA = 0.0
UMBRAL_CALOR = 35.0
DIA_LLUVIA = 1.0
INICIO_TEMPORADA, FIN_TEMPORADA = (6, 1), (10, 31)
SIEMBRA_POR_DEFECTO = (6, 15)
# Si en el periodo falta más de este porcentaje de días (no estimables), el indicador no se informa
MAX_FALTANTE = 0.05
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


# --- cálculos base ----------------------------------------------------------------------------------------
def radiacion_extraterrestre(lat_grados, doy):
    """Ra en mm/día de agua evaporada equivalente (FAO-56 ec. 21, multiplicada por 0.408)."""
    phi = np.radians(lat_grados)
    j = np.asarray(doy, float)
    dr = 1 + 0.033 * np.cos(2 * np.pi * j / 365)
    delta = 0.409 * np.sin(2 * np.pi * j / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    ra = (24 * 60 / np.pi) * 0.0820 * dr * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))
    return 0.408 * ra


def et0_hargreaves(tmax, tmin, lat, doy):
    tmed = (tmax + tmin) / 2
    return 0.0023 * (tmed + 17.8) * np.sqrt(np.clip(tmax - tmin, 0, None)) * radiacion_extraterrestre(lat, doy)


def grados_dia(tmax, tmin):
    tx = np.clip(tmax, BASE_GDD, TOPE_GDD)
    tn = np.clip(tmin, BASE_GDD, TOPE_GDD)
    return (tx + tn) / 2 - BASE_GDD


def racha_mas_larga(mascara):
    m = np.asarray(mascara, bool)
    if not m.any():
        return 0
    d = np.diff(np.concatenate([[0], m.astype(int), [0]]))
    return int((np.nonzero(d == -1)[0] - np.nonzero(d == 1)[0]).max())


def tabla_diaria(serie_estacion, lat):
    """De la serie larga de una estación (fecha, variable, valor, origen) a una tabla diaria."""
    s = serie_estacion
    piv = s.pivot(index="fecha", columns="variable", values="valor")
    org = s.pivot(index="fecha", columns="variable", values="origen")
    d = pd.DataFrame(index=pd.to_datetime(piv.index))
    for v in ("precipitacion", "tmax", "tmin"):
        d[v] = piv[v].to_numpy(float)
        d[f"med_{v}"] = (org[v] == "observado").to_numpy()
    doy = d.index.dayofyear.to_numpy()
    d["et0"] = et0_hargreaves(d["tmax"].to_numpy(), d["tmin"].to_numpy(), lat, doy)
    d["gdd"] = grados_dia(d["tmax"].to_numpy(), d["tmin"].to_numpy())
    d["anio"] = d.index.year
    d["doy"] = doy
    return d


def _fecha(anio, md):
    return pd.Timestamp(anio, *md)


def _fmt(ts):
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def _dia_mes(doy):
    """Día del año -> "15 jun" (año no bisiesto)."""
    if doy is None or (isinstance(doy, float) and np.isnan(doy)):
        return None
    f = date(2023, 1, 1) + timedelta(days=int(round(doy)) - 1)
    return f"{f.day} {MESES[f.month - 1]}"


def _pct_medido(d, cols):
    if not len(d):
        return None
    return round(100 * float(np.mean(np.column_stack([d[f"med_{c}"] for c in cols]))), 1)


def _suficiente(x):
    return len(x) > 0 and float(np.mean(np.isnan(np.asarray(x, float)))) <= MAX_FALTANTE


def _suma(x):
    """Suma de los días con dato, o None si faltan más del 5 % de los días del periodo."""
    return float(np.nansum(np.asarray(x, float))) if _suficiente(x) else None


def _pct_sin_dato(d, cols):
    if not len(d):
        return None
    return round(100 * float(np.mean(np.column_stack([d[c].isna() for c in cols]))), 1)


def _red(x, n=1):
    return None if x is None else round(x, n)


# --- indicadores por año --------------------------------------------------------------------------------
def inicio_lluvias(d, anio):
    sub = d[(d.index >= _fecha(anio, (5, 1))) & (d.index <= _fecha(anio, (9, 30)))]
    p = sub["precipitacion"].to_numpy()
    if not _suficiente(p):
        return None
    for i in range(len(p) - 3):
        if np.nansum(p[i:i + 3]) >= 20:
            siguiente = p[i + 3:i + 33]
            if len(siguiente) >= 10 and racha_mas_larga(siguiente < DIA_LLUVIA) < 10:
                return sub.index[i]
    return None


def heladas(d, anio):
    sub = d[d.index.year == anio]
    if not _suficiente(sub["tmin"]):
        return {"dias_helada": None, "ultima_primavera": None, "primera_otono": None, "periodo_libre_dias": None}
    h = sub["tmin"] <= UMBRAL_HELADA
    mitad = _fecha(anio, (7, 1))
    prim = sub.index[h & (sub.index < mitad)]
    oto = sub.index[h & (sub.index >= mitad)]
    ultima = prim.max() if len(prim) else None
    primera = oto.min() if len(oto) else None
    ini = ultima if ultima is not None else _fecha(anio, (1, 1))
    fin = primera if primera is not None else _fecha(anio, (12, 31))
    return {"dias_helada": int(h.sum()), "ultima_primavera": ultima, "primera_otono": primera,
            "periodo_libre_dias": int((fin - ini).days)}


def resumen_anual(d, anio):
    """Indicadores de una temporada completa (para el histórico y los promedios)."""
    t0, t1 = _fecha(anio, INICIO_TEMPORADA), _fecha(anio, FIN_TEMPORADA)
    temp = d[(d.index >= t0) & (d.index <= t1)]
    if temp[["precipitacion", "tmax", "tmin"]].notna().all(axis=1).sum() < 120:
        return None  # temporada casi sin datos (p. ej. estación suspendida): no se informa
    ini = inicio_lluvias(d, anio)
    siembra = ini if ini is not None else _fecha(anio, SIEMBRA_POR_DEFECTO)
    ciclo = temp[temp.index >= siembra]
    canicula = temp[temp.index <= _fecha(anio, (9, 30))]
    hel = heladas(d, anio)
    return {
        "anio": anio,
        "lluvia_temporada_mm": _red(_suma(temp["precipitacion"])),
        "inicio_lluvias": _fmt(ini),
        "inicio_lluvias_doy": ini.dayofyear if ini is not None else np.nan,
        "racha_seca_max_dias": racha_mas_larga(canicula["precipitacion"] < DIA_LLUVIA)
        if _suficiente(canicula["precipitacion"]) else None,
        "dias_helada": hel["dias_helada"],
        "ultima_helada_primavera": _fmt(hel["ultima_primavera"]),
        "ultima_helada_doy": hel["ultima_primavera"].dayofyear if hel["ultima_primavera"] is not None else np.nan,
        "primera_helada_otono": _fmt(hel["primera_otono"]),
        "primera_helada_doy": hel["primera_otono"].dayofyear if hel["primera_otono"] is not None else np.nan,
        "periodo_libre_heladas_dias": hel["periodo_libre_dias"],
        "grados_dia_ciclo": _red(_suma(ciclo["gdd"]), 0),
        "dias_calor_35": int((temp["tmax"] >= UMBRAL_CALOR).sum()) if _suficiente(temp["tmax"]) else None,
        "et0_temporada_mm": _red(_suma(temp["et0"])),
        "balance_temporada_mm": _red(_suma(temp["precipitacion"] - temp["et0"])),
        "pct_sin_dato_lluvia": _pct_sin_dato(temp, ["precipitacion"]),
        "pct_sin_dato_temperatura": _pct_sin_dato(temp, ["tmax", "tmin"]),
        "pct_dias_medidos_lluvia": _pct_medido(temp, ["precipitacion"]),
        "pct_dias_medidos_temperatura": _pct_medido(temp, ["tmax", "tmin"]),
    }


def indicadores_todas(serie, est):
    """Tabla estación x temporada para todas las estaciones (salida del pipeline)."""
    filas = []
    for e in est.itertuples():
        s = serie[serie["clave"] == e.clave]
        if s.empty:
            continue
        d = tabla_diaria(s, e.latitud)
        for anio in sorted(d["anio"].unique()):
            r = resumen_anual(d, int(anio))
            if r:
                filas.append({"clave": e.clave, "nombre": e.nombre, "municipio": e.municipio, **r})
    cols_doy = ["inicio_lluvias_doy", "ultima_helada_doy", "primera_helada_doy"]
    return pd.DataFrame(filas).drop(columns=cols_doy, errors="ignore")


# --- datos para el tablero (vista mensual, fácil de leer) ------------------------------------------------
def _redondear_lista(xs, n=1):
    return [None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n) for x in xs]


def tablero_mensual(d, anio, anios_otros, corte):
    """Por mes: lluvia, temperaturas, evaporación del cultivo y heladas de este año vs. lo normal.
    Un mes con más del 5 % de días sin dato no se informa; uno posterior a la fecha de corte tampoco."""
    x = d[d.index <= corte].copy()
    x["mes"] = x.index.month
    g = x.groupby(["anio", "mes"]).agg(
        lluvia=("precipitacion", "sum"), n_lluvia=("precipitacion", "count"),
        tmax=("tmax", "mean"), tmin=("tmin", "mean"), n_t=("tmin", "count"),
        et0=("et0", "sum"), heladas=("tmin", lambda s: int((s <= UMBRAL_HELADA).sum())),
        medidos=("med_precipitacion", "mean"), dias=("doy", "size"))
    g["dias_mes"] = [pd.Period(f"{a}-{m:02d}").days_in_month for a, m in g.index]
    ok_ll = g["n_lluvia"] >= (1 - MAX_FALTANTE) * g["dias_mes"]
    ok_t = g["n_t"] >= (1 - MAX_FALTANTE) * g["dias_mes"]
    for c in ("lluvia", "et0"):
        g.loc[~ok_ll, c] = np.nan
    for c in ("tmax", "tmin", "heladas"):
        g[c] = g[c].astype(float)
        g.loc[~ok_t, c] = np.nan

    def del_anio(c):
        s = g.xs(anio, level="anio")[c] if anio in g.index.get_level_values(0) else pd.Series(dtype=float)
        return [s.get(m, np.nan) for m in range(1, 13)]

    otros = g[g.index.get_level_values(0).isin(anios_otros)]

    def normal(c, func="mean"):
        s = otros[c].dropna().groupby(level="mes")
        s = getattr(s, func)() if isinstance(func, str) else s.apply(func)
        return [s.get(m, np.nan) for m in range(1, 13)]

    prob_helada = (otros["heladas"].dropna() > 0).groupby(level="mes").mean()
    return {
        "meses": MESES,
        "lluvia": _redondear_lista(del_anio("lluvia")), "lluvia_normal": _redondear_lista(normal("lluvia")),
        "tmax": _redondear_lista(del_anio("tmax")), "tmax_normal": _redondear_lista(normal("tmax")),
        "tmin": _redondear_lista(del_anio("tmin")), "tmin_normal": _redondear_lista(normal("tmin")),
        "evaporacion": _redondear_lista(del_anio("et0")),
        "heladas": _redondear_lista(del_anio("heladas"), 0),
        "prob_helada": [round(100 * float(prob_helada.get(m, 0))) for m in range(1, 13)],
        "pct_medido": _redondear_lista([100 * v if v == v else np.nan for v in del_anio("medidos")], 0),
    }


def lluvia_acumulada_temporada(d, anio, anios_otros, corte):
    """Lluvia acumulada día a día del 1 de junio al 31 de octubre: este año, lo normal y el rango de años normales."""
    t0, t1 = _fecha(anio, INICIO_TEMPORADA), _fecha(anio, FIN_TEMPORADA)
    dias = (t1 - t0).days + 1

    def curva(a):
        x = d[(d.index >= _fecha(a, INICIO_TEMPORADA)) & (d.index <= _fecha(a, FIN_TEMPORADA))]["precipitacion"]
        x = x.to_numpy()[:dias]
        return np.nancumsum(x) if len(x) == dias and _suficiente(x) else None

    otras = [c for c in (curva(a) for a in anios_otros) if c is not None]
    actual = d[(d.index >= t0) & (d.index <= min(t1, corte))]["precipitacion"]
    if len(actual) and _suficiente(actual):
        este = list(np.nancumsum(actual.to_numpy()))
    else:
        este = []
    M = np.vstack(otras) if otras else np.full((1, dias), np.nan)
    return {
        "fechas": [_dia_mes((t0 + pd.Timedelta(days=i)).dayofyear) for i in range(dias)],
        "este_anio": _redondear_lista(este, 0),
        "normal": _redondear_lista(np.nanmean(M, axis=0), 0),
        "rango_bajo": _redondear_lista(np.nanpercentile(M, 20, axis=0), 0),
        "rango_alto": _redondear_lista(np.nanpercentile(M, 80, axis=0), 0),
        "anios": len(otras),
    }


# --- panel para la interfaz -------------------------------------------------------------------------------
def _estado_lluvia(pct):
    if pct is None:
        return "sin_dato"
    return "debajo" if pct < 80 else "arriba" if pct > 120 else "normal"


def panel(serie_estacion, lat, anio=None, siembra=None, hasta=None):
    """Todo lo que necesita la vista del productor para una estación y una temporada."""
    d = tabla_diaria(serie_estacion, lat)
    completos = d[["precipitacion", "tmax", "tmin"]].notna().all(axis=1)
    con_datos = d[completos]
    if con_datos.empty:
        raise ValueError("La estación no tiene datos suficientes para indicadores agrícolas")
    ultimo = con_datos.index.max()
    anios = sorted(int(a) for a, n in con_datos.groupby("anio").size().items() if n >= 300 or a == ultimo.year)
    anio = int(anio or ultimo.year)
    if anio not in anios:
        raise ValueError(f"No hay datos para {anio}. Años disponibles: {anios}")
    fin_temp = _fecha(anio, FIN_TEMPORADA)
    corte = min(pd.Timestamp(hasta) if hasta else _fecha(anio, (12, 31)), ultimo, _fecha(anio, (12, 31)))
    ini_lluvias = inicio_lluvias(d, anio)
    if siembra:
        f_siembra, origen_siembra = pd.Timestamp(siembra), "productor"
    elif ini_lluvias is not None:
        f_siembra, origen_siembra = ini_lluvias, "inicio_de_lluvias"
    else:
        f_siembra, origen_siembra = _fecha(anio, SIEMBRA_POR_DEFECTO), "fecha_tipica"

    historico = [r for r in (resumen_anual(d, a) for a in anios) if r]
    hist = pd.DataFrame(historico)
    otros = hist[hist["anio"] != anio] if len(hist) > 1 else hist
    periodo = f"{min(anios)}–{max(anios)}"

    # Lluvia de temporada hasta la fecha de corte vs. lo acumulado a la misma fecha en otros años
    t0 = _fecha(anio, INICIO_TEMPORADA)
    corte_temp = min(corte, fin_temp)
    temp = d[(d.index >= t0) & (d.index <= corte_temp)]
    doy_corte = corte_temp.dayofyear

    def acumulado_otro(a, col, desde_md=INICIO_TEMPORADA, desde_doy=None):
        x = d[d["anio"] == a]
        ini = desde_doy if desde_doy is not None else _fecha(a, desde_md).dayofyear
        return _suma(x[(x["doy"] >= ini) & (x["doy"] <= doy_corte)][col])

    def promedio_otros(col, desde_doy=None):
        vals = [v for v in (acumulado_otro(a, col, desde_doy=desde_doy) for a in anios_otros) if v is not None]
        return (float(np.mean(vals)), len(vals)) if vals else (None, 0)

    anios_otros = [a for a in anios if a != anio] or anios
    lluvia = _suma(temp["precipitacion"]) if len(temp) else None
    lluvia_prom, n_lluvia = promedio_otros("precipitacion") if len(temp) else (None, 0)
    pct = round(100 * lluvia / lluvia_prom, 0) if lluvia is not None and lluvia_prom else None

    # Ciclo del cultivo desde la siembra
    ciclo = d[(d.index >= f_siembra) & (d.index <= corte_temp)]
    gdd = _suma(ciclo["gdd"]) if len(ciclo) else None
    gdd_prom, n_gdd = promedio_otros("gdd", f_siembra.dayofyear) if len(ciclo) else (None, 0)
    ult30 = d[(d.index > corte_temp - pd.Timedelta(days=30)) & (d.index <= corte_temp)]
    balance30 = _suma(ult30["precipitacion"] - ult30["et0"])
    hel = heladas(d, anio)

    def prom(col):
        v = otros[col].dropna() if col in otros else pd.Series(dtype=float)
        return float(v.mean()) if len(v) else None

    # Series semanales para las gráficas (semana = 7 días desde el 1 de enero)
    del_anio = d[d["anio"] == anio].copy()
    del_anio["semana"] = (del_anio["doy"] - 1) // 7
    semanal = del_anio.groupby("semana").agg(
        inicio=("doy", "min"), lluvia=("precipitacion", "sum"), con_dato=("precipitacion", "count"),
        dias=("doy", "size"), medidos=("med_precipitacion", "mean"))
    semanal.loc[semanal["con_dato"] < semanal["dias"], "lluvia"] = np.nan  # semana incompleta: no se grafica
    semanal.loc[semanal["inicio"] > corte.dayofyear, "lluvia"] = np.nan   # después de la fecha de corte
    todos = d.copy()
    todos["semana"] = (todos["doy"] - 1) // 7
    sem = todos[todos["anio"].isin(anios_otros)].groupby(["anio", "semana"]).agg(
        lluvia=("precipitacion", "sum"), n_lluvia=("precipitacion", "count"),
        tmin=("tmin", "min"), n_tmin=("tmin", "count"), dias=("doy", "size"))
    lluvia_prom_sem = sem.loc[sem["n_lluvia"] == sem["dias"], "lluvia"].groupby("semana").mean()
    validas = sem[sem["n_tmin"] == sem["dias"]]
    prob_helada = (validas["tmin"] <= UMBRAL_HELADA).groupby("semana").mean()
    semanal = semanal[semanal.index <= 51]

    # Curvas diarias acumuladas del ciclo: este año vs. promedio
    dias_ciclo = pd.date_range(f_siembra, max(f_siembra, min(fin_temp, corte)))
    largo = len(dias_ciclo)

    def curva(a, col):
        x = d[(d["anio"] == a) & (d["doy"] >= f_siembra.dayofyear)].sort_index()[col].to_numpy()[:largo]
        if len(x) < largo or not _suficiente(x):
            return None  # año incompleto: no entra al promedio
        return np.nancumsum(x)
    curvas_otros = [c for c in (curva(a, "gdd") for a in anios_otros) if c is not None]
    gdd_prom_curva = np.mean(np.vstack(curvas_otros), axis=0) if curvas_otros else np.full(largo, np.nan)
    ciclo_completo = d[(d.index >= f_siembra) & (d.index <= dias_ciclo[-1])]
    bal_curva = (ciclo_completo["precipitacion"] - ciclo_completo["et0"]).cumsum()
    tmin_diaria = del_anio[["tmin", "med_tmin"]]

    def r1(x):
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 1)

    # Racha seca de la temporada hasta la fecha de corte (en una temporada en curso, lo que va)
    canicula = d[(d.index >= t0) & (d.index <= min(corte, _fecha(anio, (9, 30))))]["precipitacion"].to_numpy()

    return {
        "anio": anio, "anios_disponibles": anios, "periodo_promedio": periodo, "fecha_corte": _fmt(corte),
        "ultimo_dato": _fmt(ultimo),
        "siembra": {"fecha": _fmt(f_siembra), "origen": origen_siembra},
        "lluvia": {
            "acumulada_mm": r1(lluvia), "promedio_mm": r1(lluvia_prom), "anios_promedio": n_lluvia,
            "pct_del_promedio": pct,
            "estado": _estado_lluvia(pct), "desde": _fmt(t0), "hasta": _fmt(corte_temp),
            "inicio_lluvias": _fmt(ini_lluvias), "inicio_lluvias_promedio": _dia_mes(prom("inicio_lluvias_doy")),
            "racha_seca_max_dias": racha_mas_larga(canicula < DIA_LLUVIA) if _suficiente(canicula) else None,
            "racha_seca_promedio_dias": r1(prom("racha_seca_max_dias")),
            "pct_dias_medidos": _pct_medido(temp, ["precipitacion"]),
            "pct_sin_dato": _pct_sin_dato(temp, ["precipitacion"]),
        },
        "heladas": {
            "dias_helada": hel["dias_helada"], "dias_helada_promedio": r1(prom("dias_helada")),
            "ultima_primavera": _fmt(hel["ultima_primavera"]), "primera_otono": _fmt(hel["primera_otono"]),
            "ultima_primavera_promedio": _dia_mes(prom("ultima_helada_doy")),
            "primera_otono_promedio": _dia_mes(prom("primera_helada_doy")),
            "periodo_libre_dias": hel["periodo_libre_dias"],
            "periodo_libre_promedio_dias": r1(prom("periodo_libre_heladas_dias")),
            "pct_dias_medidos": _pct_medido(d[d["anio"] == anio], ["tmin"]),
            "pct_sin_dato": _pct_sin_dato(d[d["anio"] == anio], ["tmin"]),
        },
        "calor": {
            "grados_dia": r1(gdd), "grados_dia_promedio": r1(gdd_prom), "anios_promedio": n_gdd,
            "pct_del_promedio": round(100 * gdd / gdd_prom, 0) if gdd is not None and gdd_prom else None,
            "dias_calor_35": int((ciclo["tmax"] >= UMBRAL_CALOR).sum()) if _suficiente(ciclo["tmax"]) else None,
            "pct_dias_medidos": _pct_medido(ciclo, ["tmax", "tmin"]),
            "pct_sin_dato": _pct_sin_dato(ciclo, ["tmax", "tmin"]),
        },
        "agua": {
            "lluvia_30d_mm": r1(_suma(ult30["precipitacion"])), "et0_30d_mm": r1(_suma(ult30["et0"])),
            "balance_30d_mm": r1(balance30), "hasta": _fmt(corte_temp),
            "estado": "sin_dato" if balance30 is None else "deficit" if balance30 < -50 else
            "justo" if balance30 < 0 else "suficiente",
            "pct_dias_medidos": _pct_medido(ult30, ["precipitacion", "tmax", "tmin"]),
            "pct_sin_dato": _pct_sin_dato(ult30, ["precipitacion", "tmax", "tmin"]),
        },
        "graficas": {
            "semanas": [_dia_mes(i) for i in semanal["inicio"]],
            "lluvia_semanal": [r1(x) for x in semanal["lluvia"]],
            "lluvia_semanal_promedio": [r1(lluvia_prom_sem.get(s)) for s in semanal.index],
            "pct_medido_semana": [round(100 * float(x)) for x in semanal["medidos"]],
            "prob_helada_semana": [round(100 * float(prob_helada.get(s, 0))) for s in semanal.index],
            "ciclo_fechas": [_fmt(x) for x in dias_ciclo],
            "grados_dia_acum": [r1(x) for x in ciclo_completo["gdd"].cumsum()],
            "grados_dia_acum_promedio": [r1(x) for x in gdd_prom_curva],
            "balance_acum": [r1(x) for x in bal_curva],
            "tmin_fechas": [_fmt(x) for x in tmin_diaria.index],
            "tmin": [r1(x) for x in tmin_diaria["tmin"]],
            "tmin_medido": [bool(x) for x in tmin_diaria["med_tmin"]],
        },
        "historico": [{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()
                       if not k.endswith("_doy")} | _categoria_anio(r, hist) for r in historico],
        "tablero": {
            "mensual": tablero_mensual(d, anio, anios_otros, corte),
            "lluvia_temporada": lluvia_acumulada_temporada(d, anio, anios_otros, corte),
        },
    }


def _categoria_anio(r, hist):
    """Clasifica la temporada de lluvias de cada año contra el promedio de todos los años: seca, normal o lluviosa."""
    v = r.get("lluvia_temporada_mm")
    prom = hist["lluvia_temporada_mm"].dropna().astype(float).mean() if "lluvia_temporada_mm" in hist else np.nan
    if v is None or not prom or np.isnan(prom):
        return {"pct_lluvia_promedio": None, "categoria_lluvia": "sin_dato"}
    pct = round(100 * v / prom)
    return {"pct_lluvia_promedio": pct, "categoria_lluvia": _estado_lluvia(pct)}
