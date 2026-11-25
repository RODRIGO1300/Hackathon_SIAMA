"""Lectura de los archivos diarios del Servicio Meteorológico Nacional (Base de Datos Climatológica Nacional, CLICOM).

Formato de entrada (dia<clave>.txt): un encabezado con "CAMPO : valor" (ESTACIÓN, NOMBRE, MUNICIPIO, SITUACIÓN,
LATITUD, LONGITUD, ALTITUD, EMISIÓN) y después una tabla separada por tabuladores:
    FECHA  PRECIP(mm)  EVAP(mm)  TMAX(°C)  TMIN(°C)       con "NULO" como valor faltante.
En estos archivos casi todos los huecos son DÍAS QUE NO APARECEN, no "NULO".

Salida: un paquete con el mismo formato que el paquete oficial del reto, listo para el pipeline:
    estaciones.csv, series_diarias.csv (incluye la evaporación medida), fuente.json, diccionario_datos.md

Uso:
    python -m siama_gaps clicom datos/dia11096.txt datos/dia11136.txt --destino datos_salamanca --desde 1981
Los valores se copian tal como vienen (incluido "NULO"): la limpieza (etapa 0) los convierte y los registra.
"""
import json
import re
from pathlib import Path

import pandas as pd

# Archivos diarios públicos del SMN, por estado (gto = Guanajuato)
URL_SMN = "https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Diarios/{estado}/dia{clave}.txt"
ESTADO_SMN = "gto"
CAMPOS = {"ESTACION": "clave", "NOMBRE": "nombre", "ESTADO": "estado", "MUNICIPIO": "municipio",
          "SITUACION": "situacion", "LATITUD": "latitud", "LONGITUD": "longitud", "ALTITUD": "altitud",
          "EMISION": "emision"}
SIN_ACENTO = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")
PALABRAS_MENORES = {"de", "del", "la", "las", "el", "los", "y"}


def _leer_texto(ruta):
    for cod in ("utf-8-sig", "latin-1"):
        try:
            return Path(ruta).read_text(encoding=cod)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"No se pudo leer {ruta}")


def _titulo(texto):
    """'LA JOYITA' -> 'La Joyita'; 'SAN MIGUEL DE ALLENDE' -> 'San Miguel de Allende'."""
    palabras = str(texto).strip().lower().split()
    return " ".join(p if i and p in PALABRAS_MENORES else p.capitalize() for i, p in enumerate(palabras))


def leer_archivo(ruta):
    """Devuelve (metadatos de la estación, tabla de datos como texto, conteos de lectura)."""
    lineas = _leer_texto(ruta).splitlines()
    meta, inicio = {}, None
    for i, linea in enumerate(lineas):
        if re.match(r"^\s*FECHA\b", linea):
            inicio = i + 1
            break
        m = re.match(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$", linea)
        if m:
            campo = m.group(1).upper().translate(SIN_ACENTO).strip()
            if campo in CAMPOS:
                valor = m.group(2)
                if CAMPOS[campo] in ("latitud", "longitud", "altitud"):
                    valor = re.sub(r"[^\d.\-]", "", valor)
                meta[CAMPOS[campo]] = valor.strip()
    if inicio is None or "clave" not in meta:
        raise ValueError(f"{ruta}: no parece un archivo diario del SMN (falta ESTACIÓN o la línea FECHA)")
    filas, ignoradas = [], 0
    for linea in lineas[inicio:]:
        partes = linea.rstrip("\n").split("\t")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", partes[0].strip()):
            partes = (partes + [""] * 5)[:5]
            filas.append([p.strip() for p in partes])
        elif linea.strip():
            ignoradas += 1  # renglón de unidades u otras notas
    datos = pd.DataFrame(filas, columns=["fecha", "precipitacion", "evaporacion", "tmax", "tmin"])
    datos.insert(1, "clave", meta["clave"])
    return meta, datos, {"filas": len(datos), "lineas_no_datos": ignoradas}


def preparar(archivos, destino, desde=None, hasta=None, min_dias=0):
    """min_dias: estaciones con menos días con algún dato en el periodo se excluyen (quedan en el informe)."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    estaciones, series, informe, usados = [], [], [], []
    for ruta in archivos:
        meta, datos, conteo = leer_archivo(ruta)
        f = pd.to_datetime(datos["fecha"], errors="coerce")
        f_ini, f_fin = f.min(), f.max()
        mascara = pd.Series(True, index=datos.index)
        if desde:
            mascara &= f >= pd.Timestamp(f"{desde}-01-01")
        if hasta:
            mascara &= f <= pd.Timestamp(f"{hasta}-12-31")
        datos = datos[mascara]
        fd = pd.to_datetime(datos["fecha"])
        dias_calendario = len(pd.date_range(fd.min(), fd.max())) if len(fd) else 0
        nulos = {c: int((datos[c].str.upper() == "NULO").sum()) for c in ["precipitacion", "evaporacion", "tmax", "tmin"]}
        informe.append({"archivo": Path(ruta).name, "clave": meta["clave"], "nombre": meta.get("nombre", ""),
                        "periodo_archivo": f"{f_ini.date()} a {f_fin.date()}",
                        "periodo_usado": f"{fd.min().date()} a {fd.max().date()}" if len(fd) else "",
                        "filas_usadas": len(datos), "dias_ausentes_del_archivo": dias_calendario - fd.nunique(),
                        **{f"nulo_{c}": n for c, n in nulos.items()}})
        con_dato = datos[["precipitacion", "tmax", "tmin"]].apply(
            lambda c: pd.to_numeric(c, errors="coerce").notna()).any(axis=1).sum()
        informe[-1]["dias_con_dato"] = int(con_dato)
        if con_dato < min_dias or not meta.get("latitud") or not meta.get("longitud"):
            informe[-1]["excluida"] = (f"solo {con_dato} días con datos (mínimo {min_dias})" if con_dato < min_dias
                                       else "sin coordenadas")
            continue
        informe[-1]["excluida"] = ""
        usados.append(ruta)
        situacion = meta.get("situacion", "").strip().lower()
        estaciones.append({
            "clave": meta["clave"], "nombre": f"{_titulo(meta.get('nombre', meta['clave']))} ({meta['clave']})",
            "municipio": _titulo(meta.get("municipio", "")), "latitud": meta.get("latitud", ""),
            "longitud": meta.get("longitud", ""), "altitud": meta.get("altitud", ""),
            "estado_operativo": "operando" if situacion.startswith("operando") else situacion or "desconocido",
        })
        series.append(datos)
    est = pd.DataFrame(estaciones)
    ser = pd.concat(series, ignore_index=True)
    est.to_csv(destino / "estaciones.csv", index=False)
    ser.to_csv(destino / "series_diarias.csv", index=False)
    emisiones = sorted({leer_archivo(r)[0].get("emision", "") for r in usados} - {""})
    fechas = pd.to_datetime(ser["fecha"])
    fuente = {"tipo": "oficial", "origen": "SMN · Base de Datos Climatológica Nacional (CLICOM)",
              "emision": ", ".join(emisiones), "archivos": [Path(r).name for r in usados], "min_dias": min_dias,
              "claves": [e["clave"] for e in estaciones], "estado_smn": ESTADO_SMN, "desde": desde, "hasta": hasta,
              "periodo": f"{fechas.min().year}–{fechas.max().year}", "datos_hasta": str(fechas.max().date())}
    (destino / "fuente.json").write_text(json.dumps(fuente, ensure_ascii=False, indent=2), encoding="utf-8")
    inf = pd.DataFrame(informe)
    (destino / "diccionario_datos.md").write_text(_diccionario(fuente, inf), encoding="utf-8")
    return est, inf, fuente


def _diccionario(fuente, inf):
    filas = "\n".join(f"| {r.clave} | {r.nombre} | {r.periodo_usado} | {r.filas_usadas:,} | {r.dias_ausentes_del_archivo:,} | "
                      f"{r.nulo_precipitacion} / {r.nulo_tmax} / {r.nulo_tmin} | {r.excluida or 'sí'} |"
                      for r in inf.itertuples())
    return f"""# Diccionario de datos (paquete OFICIAL convertido de CLICOM)

Origen: {fuente['origen']}. Emisión: {fuente['emision']}. Archivos: {', '.join(fuente['archivos'])}.
Generado con `python -m siama_gaps clicom`. Los valores se copian sin modificar; la limpieza (etapa 0) los procesa.

| Clave | Estación | Periodo usado | Filas | Días que no aparecen | NULO (lluvia / Tmax / Tmin) | ¿Incluida? |
|---|---|---|---|---|---|---|
{filas}

## estaciones.csv
clave, nombre, municipio, latitud, longitud (grados decimales), altitud (m s.n.m.), estado_operativo.

## series_diarias.csv
| Campo | Unidad |
|---|---|
| fecha | AAAA-MM-DD |
| clave | Clave de estación |
| precipitacion | mm/día |
| evaporacion | mm/día (tanque evaporímetro; no la usa el relleno) |
| tmax, tmin | °C |

Valor faltante: `NULO` (como en el archivo original) o día ausente.
"""


# --- actualización desde el SMN -----------------------------------------------------------------------------
def descargar(clave, destino, estado=ESTADO_SMN, timeout=120):
    """Descarga dia<clave>.txt del SMN. Devuelve la ruta guardada."""
    import urllib.request

    url = URL_SMN.format(estado=estado, clave=clave)
    req = urllib.request.Request(url, headers={"User-Agent": "siama-prototipo/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        contenido = r.read()
    if b"FECHA" not in contenido[:5000]:
        raise ValueError(f"{url} no devolvió un archivo diario del SMN")
    ruta = Path(destino) / f"dia{clave}.txt"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".descarga")
    temporal.write_bytes(contenido)
    return temporal, ruta


def actualizar(destino, salida, forzar=False):
    """Descarga del SMN los archivos más recientes de las estaciones del paquete y, si cambiaron,
    vuelve a preparar el paquete y a correr el pipeline. Si algo falla, los datos actuales no se tocan."""
    import hashlib
    from datetime import datetime

    destino, salida = Path(destino), Path(salida)
    fuente = json.loads((destino / "fuente.json").read_text(encoding="utf-8"))
    claves = fuente.get("claves") or [re.sub(r"\D", "", a) for a in fuente["archivos"]]
    originales = destino / "originales"
    cambios, descargas = [], []
    for clave in claves:
        temporal, ruta = descargar(clave, originales, fuente.get("estado_smn", ESTADO_SMN))
        descargas.append((temporal, ruta))
        nuevo = hashlib.sha256(temporal.read_bytes()).hexdigest()
        viejo = hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None
        if nuevo != viejo:
            cambios.append(clave)
    for temporal, ruta in descargas:  # solo se reemplazan cuando TODAS las descargas salieron bien
        temporal.replace(ruta)
    ahora = datetime.now().isoformat(timespec="seconds")
    if not cambios and not forzar and (salida / "metricas.json").exists():
        fuente["revisado"] = ahora
        (destino / "fuente.json").write_text(json.dumps(fuente, ensure_ascii=False, indent=2), encoding="utf-8")
        ruta_m = salida / "metricas.json"  # la API muestra cuándo se revisó por última vez
        metr = json.loads(ruta_m.read_text(encoding="utf-8"))
        metr["fuente"] = fuente
        ruta_m.write_text(json.dumps(metr, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return {"cambios": [], "datos_hasta": fuente.get("datos_hasta"), "revisado": ahora}
    archivos = [originales / f"dia{c}.txt" for c in claves]
    _, _, fuente_nueva = preparar(archivos, destino, fuente.get("desde"), fuente.get("hasta"), fuente.get("min_dias", 0))
    fuente_nueva["revisado"] = ahora
    (destino / "fuente.json").write_text(json.dumps(fuente_nueva, ensure_ascii=False, indent=2), encoding="utf-8")
    from . import pipeline
    pipeline.ejecutar(destino, salida)
    return {"cambios": cambios or ["(forzado)"], "datos_hasta": fuente_nueva["datos_hasta"], "revisado": ahora}


# --- descarga de todas las estaciones de un estado ---------------------------------------------------------
def existe_en_smn(clave, estado=ESTADO_SMN, timeout=30):
    """True si el SMN publica dia<clave>.txt (consulta solo encabezados, sin descargar el archivo)."""
    import urllib.error
    import urllib.request

    url = URL_SMN.format(estado=estado, clave=clave)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "siama-prototipo/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200 and "text/plain" in r.headers.get("Content-Type", "")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return False


def descargar_estado(destino, claves, estado=ESTADO_SMN, pausa=0.3, avisar=print):
    """Descarga los dia<clave>.txt que existan entre `claves`. Devuelve la lista de rutas guardadas."""
    import time

    destino = Path(destino)
    guardados = []
    for clave in claves:
        ruta = destino / f"dia{clave}.txt"
        if not ruta.exists():
            if not existe_en_smn(clave, estado):
                time.sleep(pausa)
                continue
            temporal, ruta = descargar(clave, destino, estado)
            temporal.replace(ruta)
            time.sleep(pausa)
        guardados.append(ruta)
        avisar(f"  {clave}: {ruta.stat().st_size // 1024} KB")
    return guardados
