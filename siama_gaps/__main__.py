"""CLI:  python -m siama_gaps {sinteticos|run|todo}"""
import argparse

from . import pipeline, sinteticos


def main():
    p = argparse.ArgumentParser(prog="siama_gaps", description="Relleno de huecos climatológicos para SIAMA")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sinteticos", help="Genera un paquete de datos sintético con el formato oficial")
    s.add_argument("--destino", default="datos")
    r = sub.add_parser("run", help="Ejecuta el pipeline completo")
    r.add_argument("--datos", default="datos")
    r.add_argument("--salida", default="salidas")
    t = sub.add_parser("todo", help="sinteticos + run")
    t.add_argument("--datos", default="datos")
    t.add_argument("--salida", default="salidas")
    a = p.parse_args()
    if a.cmd == "sinteticos":
        sinteticos.generar(a.destino)
    elif a.cmd == "run":
        pipeline.ejecutar(a.datos, a.salida)
    else:
        sinteticos.generar(a.datos)
        pipeline.ejecutar(a.datos, a.salida)


if __name__ == "__main__":
    main()
