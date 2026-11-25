"""Carga opcional de variables de entorno desde un archivo `.env` en la raíz del proyecto.

Sirve para guardar las credenciales de IBM Cloud (watsonx.ai, Databases for PostgreSQL) sin escribirlas
en el código. Las variables que ya existan en el entorno tienen prioridad sobre las del archivo.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def cargar_env(ruta=None):
    ruta = Path(ruta or os.environ.get("SIAMA_ENV_FILE", RAIZ / ".env"))
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if clave and valor:
            os.environ.setdefault(clave, valor)
