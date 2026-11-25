"""Carga de resultados en PostgreSQL + PostGIS (p. ej. IBM Cloud Databases for PostgreSQL).

Uso:
    python -m siama_gaps postgres --salida salidas              # usa SIAMA_DATABASE_URL
    python -m siama_gaps postgres --dsn "postgresql://..."

Conexión:
  SIAMA_DATABASE_URL      postgresql://usuario:clave@host:puerto/ibmclouddb?sslmode=verify-full
  SIAMA_PG_CA_CERT        ruta al certificado de la instancia (IBM Cloud lo entrega en las credenciales)
  SIAMA_PG_CA_CERT_B64    alternativa: el certificado en base64 tal como viene en las credenciales
                          (útil en IBM Cloud Code Engine, donde no hay archivos locales)
  SIAMA_PG_ESQUEMA        esquema de base de datos, por defecto siama_huecos

La API lee de PostgreSQL en lugar de los CSV cuando SIAMA_DATABASE_URL está definida.
"""
import base64
import io
import json
import os
import re
import tempfile
from pathlib import Path

import pandas as pd

# tabla -> (archivo de salidas/, columnas con tipo, llave primaria)
TABLAS = {
    "estaciones": ("estaciones.csv", {
        "clave": "text", "nombre": "text", "municipio": "text", "latitud": "double precision",
        "longitud": "double precision", "altitud": "double precision", "estado_operativo": "text"}, "clave"),
    "series_completadas": ("series_completadas.csv.gz", {
        "fecha": "date", "clave": "text", "variable": "text", "valor": "double precision",
        "li": "double precision", "ls": "double precision", "origen": "text", "bandera": "text",
        "metodo": "text", "motivo_no_estimable": "text", "qc": "text"}, "clave, variable, fecha"),
    "diagnostico_estaciones": ("diagnostico_estaciones.csv", {
        "clave": "text", "variable": "text", "dias_totales": "integer", "dias_faltantes": "integer",
        "pct_faltante": "double precision", "huecos_cortos": "integer", "huecos_medios": "integer",
        "huecos_largos": "integer", "hueco_mas_largo": "integer", "primer_dato": "date",
        "ultimo_dato": "date"}, "clave, variable"),
    "diagnostico_anual": ("diagnostico_anual.csv", {
        "clave": "text", "variable": "text", "anio": "integer", "pct_faltante": "double precision"},
        "clave, variable, anio"),
    "huecos": ("huecos.csv", {
        "clave": "text", "variable": "text", "inicio": "date", "fin": "date", "dias": "integer",
        "clase": "text"}, "clave, variable, inicio"),
    "vecinos": ("vecinos.csv", {
        "clave": "text", "variable": "text", "rango": "integer", "vecino": "text",
        "dist_km": "double precision", "dif_altitud_m": "double precision", "correlacion": "double precision",
        "dias_traslape": "integer"}, "clave, variable, rango"),
    "homogeneidad": ("homogeneidad.csv", {
        "clave": "text", "variable": "text", "fecha_cambio": "text", "p_valor": "double precision",
        "magnitud": "double precision", "cambio_detectado": "boolean"}, "clave, variable"),
    "qc_banderas": ("qc_banderas.csv", {
        "fecha": "date", "clave": "text", "variable": "text", "valor_original": "double precision",
        "regla": "text"}, None),
    "predicciones_test_publico": ("predicciones_test_publico.csv", {
        "fecha": "date", "clave": "text", "variable": "text", "estimado": "double precision",
        "limite_inferior": "double precision", "limite_superior": "double precision", "bandera": "text",
        "metodo": "text"}, "clave, variable, fecha"),
}


def esquema_bd():
    nombre = os.environ.get("SIAMA_PG_ESQUEMA", "siama_huecos")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", nombre):
        raise ValueError(f"Nombre de esquema no válido: {nombre}")
    return nombre


def conectar(dsn=None):
    import psycopg  # dependencia opcional: pip install -r requirements-ibm.txt

    dsn = dsn or os.environ.get("SIAMA_DATABASE_URL")
    if not dsn:
        raise RuntimeError("Defina SIAMA_DATABASE_URL o use --dsn")
    extra = {}
    if os.environ.get("SIAMA_PG_CA_CERT"):
        extra["sslrootcert"] = os.environ["SIAMA_PG_CA_CERT"]
    elif os.environ.get("SIAMA_PG_CA_CERT_B64"):
        ruta = Path(tempfile.gettempdir()) / "siama_pg_ca.crt"
        ruta.write_bytes(base64.b64decode(os.environ["SIAMA_PG_CA_CERT_B64"]))
        extra["sslrootcert"] = str(ruta)
    return psycopg.connect(dsn, **extra)


def ddl(esq):
    sentencias = [f"CREATE SCHEMA IF NOT EXISTS {esq}"]
    for tabla, (_, cols, pk) in TABLAS.items():
        defs = [f"{c} {t}" for c, t in cols.items()]
        if pk:
            defs.append(f"PRIMARY KEY ({pk})")
        sentencias.append(f"CREATE TABLE IF NOT EXISTS {esq}.{tabla} ({', '.join(defs)})")
    sentencias += [
        f"ALTER TABLE {esq}.estaciones ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326)",
        f"CREATE INDEX IF NOT EXISTS estaciones_geom_idx ON {esq}.estaciones USING gist (geom)",
        f"CREATE TABLE IF NOT EXISTS {esq}.metricas (id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1), "
        "generado timestamp, contenido jsonb NOT NULL)",
    ]
    return sentencias


def _csv_normalizado(ruta, cols):
    """Lee un CSV de salidas/ y lo reescribe con enteros sin '.0' para que COPY lo acepte."""
    df = pd.read_csv(ruta, dtype={"clave": str, "vecino": str}, keep_default_na=False, na_values=[""],
                     low_memory=False)
    faltan = set(cols) - set(df.columns)
    if faltan:
        raise ValueError(f"{ruta.name}: faltan columnas {sorted(faltan)}")
    df = df[list(cols)]
    for c, t in cols.items():
        if t == "integer":
            df[c] = pd.to_numeric(df[c]).round().astype("Int64")
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8"), len(df)


def cargar(salida="salidas", dsn=None):
    salida = Path(salida)
    if not (salida / "metricas.json").exists():
        raise SystemExit(f"No hay resultados en {salida}/. Ejecute primero: python -m siama_gaps run")
    esq = esquema_bd()
    with conectar(dsn) as con, con.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        for s in ddl(esq):
            cur.execute(s)
        for tabla, (archivo, cols, _) in TABLAS.items():
            datos, n = _csv_normalizado(salida / archivo, cols)
            cur.execute(f"TRUNCATE {esq}.{tabla}")
            with cur.copy(f"COPY {esq}.{tabla} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, HEADER true)") as cp:
                cp.write(datos)
            print(f"  {esq}.{tabla}: {n:,} filas")
        cur.execute(f"UPDATE {esq}.estaciones SET geom = ST_SetSRID(ST_MakePoint(longitud, latitud), 4326)")
        metr = json.loads((salida / "metricas.json").read_text(encoding="utf-8"))
        cur.execute(f"INSERT INTO {esq}.metricas (id, generado, contenido) VALUES (1, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET generado = EXCLUDED.generado, contenido = EXCLUDED.contenido",
                    (metr.get("generado"), json.dumps(metr, ensure_ascii=False)))
        print(f"  {esq}.metricas: 1 fila")
    print("Carga completa.")


def leer_para_api(dsn=None):
    """Devuelve {archivo: bytes CSV} con el mismo formato que salidas/, leído desde PostgreSQL."""
    esq = esquema_bd()
    archivos = {}
    with conectar(dsn) as con, con.cursor() as cur:
        cur.execute("SET DateStyle TO ISO")
        for tabla, (archivo, cols, pk) in TABLAS.items():
            sel = ", ".join(f"{c}::text AS {c}" if t == "boolean" else c for c, t in cols.items())
            orden = f" ORDER BY {pk}" if pk else ""
            buf = io.BytesIO()
            with cur.copy(f"COPY (SELECT {sel} FROM {esq}.{tabla}{orden}) TO STDOUT WITH (FORMAT csv, HEADER true)") as cp:
                for bloque in cp:
                    buf.write(bloque)
            archivos[archivo.removesuffix(".gz")] = buf.getvalue()
        cur.execute(f"SELECT contenido::text FROM {esq}.metricas WHERE id = 1")
        fila = cur.fetchone()
        if not fila:
            raise RuntimeError(f"La tabla {esq}.metricas está vacía. Ejecute: python -m siama_gaps postgres")
        archivos["metricas.json"] = fila[0].encode("utf-8")
    return archivos
