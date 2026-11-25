"""CLI:  python -m siama_gaps {actualizar|clicom|limpiar|sinteticos|run|todo|postgres}"""
import argparse

from . import pipeline, sinteticos
from .entorno import cargar_env


def main():
    cargar_env()
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
    cl = sub.add_parser("clicom", help="Convierte archivos diarios del SMN (dia*.txt) al formato de entrada")
    cl.add_argument("archivos", nargs="+", help="Archivos dia<clave>.txt del SMN")
    cl.add_argument("--destino", required=True, help="Carpeta del nuevo paquete de datos")
    cl.add_argument("--desde", type=int, default=None, help="Primer año a usar (p. ej. 1981)")
    cl.add_argument("--hasta", type=int, default=None, help="Último año a usar")
    cl.add_argument("--min-dias", type=int, default=0, help="Excluir estaciones con menos días con datos en el periodo")
    ac = sub.add_parser("actualizar", help="Descarga lo más reciente del SMN y, si hay cambios, reprocesa todo")
    ac.add_argument("--datos", default="datos_guanajuato", help="Paquete creado con el comando clicom")
    ac.add_argument("--salida", default="salidas_guanajuato")
    ac.add_argument("--forzar", action="store_true", help="Reprocesa aunque no haya datos nuevos")
    li = sub.add_parser("limpiar", help="Solo la limpieza de datos (etapa 0) y su reporte")
    li.add_argument("--datos", default="datos")
    li.add_argument("--salida", default="salidas")
    g = sub.add_parser("postgres", help="Carga las salidas en PostgreSQL/PostGIS (p. ej. IBM Cloud Databases)")
    g.add_argument("--salida", default="salidas")
    g.add_argument("--dsn", default=None, help="Cadena de conexión; por defecto SIAMA_DATABASE_URL")
    a = p.parse_args()
    if a.cmd == "sinteticos":
        sinteticos.generar(a.destino)
    elif a.cmd == "run":
        pipeline.ejecutar(a.datos, a.salida)
    elif a.cmd == "clicom":
        from . import clicom
        est, inf, fuente = clicom.preparar(a.archivos, a.destino, a.desde, a.hasta, a.min_dias)
        excl = inf[inf["excluida"] != ""]
        print(f"{len(est)} estaciones incluidas; {len(excl)} excluidas (ver {a.destino}/diccionario_datos.md).")
        print(f"Paquete listo en {a.destino}/ ({fuente['periodo']}). Siguiente paso:")
        print(f"  python -m siama_gaps run --datos {a.destino} --salida salidas_<nombre>")
    elif a.cmd == "actualizar":
        from . import clicom
        try:
            r = clicom.actualizar(a.datos, a.salida, a.forzar)
        except Exception as e:  # sin internet o el SMN no responde: se conservan los datos actuales
            raise SystemExit(f"No se pudo actualizar ({e}). Los datos actuales no se modificaron.")
        if r["cambios"]:
            print(f"Datos actualizados ({', '.join(r['cambios'])}). Datos hasta {r['datos_hasta']}.")
        else:
            print(f"Sin datos nuevos en el SMN. Los datos llegan hasta {r['datos_hasta']} (revisado {r['revisado']}).")
    elif a.cmd == "limpiar":
        from . import limpieza
        est, series, reg, conteo = limpieza.limpiar(a.datos)
        res = limpieza.guardar(reg, conteo, a.salida)
        print(f"{conteo['filas_leidas']:,} filas leídas -> {conteo['filas_finales']:,} limpias, "
              f"{conteo['estaciones']} estaciones.")
        print(res.to_string(index=False) if len(res) else "Sin problemas de formato.")
        print(f"Reporte: {a.salida}/limpieza_reporte.md")
    elif a.cmd == "postgres":
        from . import postgres
        postgres.cargar(a.salida, a.dsn)
    else:
        sinteticos.generar(a.datos)
        pipeline.ejecutar(a.datos, a.salida)


if __name__ == "__main__":
    main()
