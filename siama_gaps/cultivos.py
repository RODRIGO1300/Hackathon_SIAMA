"""Ciclos agrícolas y calendario de siembra de referencia para el Bajío guanajuatense.

El calendario NO sale de los datos: es una referencia general de las épocas de siembra usuales en la región
y debe confirmarse con el técnico agrícola o con INIFAP según la variedad, el suelo y la disponibilidad de agua.
Lo que sí sale de los datos de la estación es la evaluación del mes: riesgo de helada y lluvia de un mes normal.
"""
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                "noviembre", "diciembre"]

# Ciclos agrícolas por época de siembra. Otoño-Invierno cruza el cambio de año.
CICLOS = {
    "primavera_verano": {"nombre": "Primavera-Verano", "meses": [3, 4, 5, 6, 7, 8, 9]},
    "otono_invierno": {"nombre": "Otoño-Invierno", "meses": [10, 11, 12, 1, 2]},
}

# agua: "temporal" (depende de la lluvia), "riego" o "humedad" (humedad que deja la temporada de lluvias)
# helada: True si una helada daña al cultivo en sus primeras semanas
CULTIVOS = [
    {"nombre": "Maíz de temporal", "agua": "temporal", "meses": [6, 7], "helada": True},
    {"nombre": "Sorgo de temporal", "agua": "temporal", "meses": [6, 7], "helada": True},
    {"nombre": "Frijol de temporal", "agua": "temporal", "meses": [6, 7], "helada": True},
    {"nombre": "Cebada de temporal", "agua": "temporal", "meses": [6, 7], "helada": False},
    {"nombre": "Maíz de riego", "agua": "riego", "meses": [3, 4, 5], "helada": True},
    {"nombre": "Sorgo de riego", "agua": "riego", "meses": [4, 5, 6], "helada": True},
    {"nombre": "Chile", "agua": "riego", "meses": [3, 4, 5], "helada": True},
    {"nombre": "Jitomate", "agua": "riego", "meses": [2, 3, 4], "helada": True},
    {"nombre": "Calabacita", "agua": "riego", "meses": [3, 4, 5, 6, 7, 8], "helada": True},
    {"nombre": "Brócoli", "agua": "riego", "meses": [7, 8, 9, 10], "helada": False},
    {"nombre": "Ajo", "agua": "riego", "meses": [9, 10], "helada": False},
    {"nombre": "Lechuga", "agua": "riego", "meses": [9, 10, 11, 12, 1, 2], "helada": False},
    {"nombre": "Garbanzo", "agua": "humedad", "meses": [10, 11], "helada": False},
    {"nombre": "Cebolla", "agua": "riego", "meses": [10, 11, 12], "helada": False},
    {"nombre": "Avena forrajera", "agua": "riego", "meses": [10, 11, 12], "helada": False},
    {"nombre": "Trigo", "agua": "riego", "meses": [11, 12, 1], "helada": False},
    {"nombre": "Cebada de riego", "agua": "riego", "meses": [11, 12, 1], "helada": False},
]
RIESGO_HELADA = 20      # % de años con helada en el mes (o el siguiente) a partir del cual se advierte
LLUVIA_TEMPORAL = 50    # mm en un mes normal para que un cultivo de temporal tenga agua suficiente
NOTA = "Calendario de referencia para el Bajío. Confirme fechas y variedades con su técnico o con INIFAP."


def _epoca(meses):
    nombres = [MESES_LARGOS[m - 1] for m in meses]
    return nombres[0] if len(nombres) == 1 else f"{nombres[0]} a {nombres[-1]}"


def evaluar_mes(mes, prob_helada, lluvia_normal, lluvia_actual=None):
    """Cultivos que se siembran en `mes` (1-12) y cómo está el clima para cada uno.
    prob_helada y lluvia_normal: listas de 12 meses (lo normal de la estación); lluvia_actual: ese mes del ciclo."""
    siguiente = mes % 12 + 1
    riesgo = max(prob_helada[mes - 1] or 0, prob_helada[siguiente - 1] or 0)
    ln = lluvia_normal[mes - 1]
    nom = MESES_LARGOS[mes - 1]
    salida = []
    for c in CULTIVOS:
        if mes not in c["meses"]:
            continue
        estado, motivo = "bien", "El clima de este mes suele ser adecuado para sembrarlo."
        if c["helada"] and riesgo >= RIESGO_HELADA:
            estado = "riesgo"
            motivo = (f"Puede helar: en {riesgo} de cada 100 años hubo heladas en {nom} o "
                      f"{MESES_LARGOS[siguiente - 1]}. Espere a que pase el riesgo o proteja la siembra.")
        elif c["agua"] == "temporal" and (ln is None or ln < LLUVIA_TEMPORAL):
            estado = "riego"
            motivo = (f"En un {nom} normal llueven {ln:.0f} mm: no alcanza sin riego." if ln is not None
                      else "No hay datos de lluvia suficientes para este mes.")
        elif c["agua"] == "temporal":
            motivo = f"En un {nom} normal llueven {ln:.0f} mm: buen momento si ya empezaron las lluvias."
        elif c["agua"] == "humedad":
            motivo = "Se siembra con la humedad que dejan las lluvias; conviene hacerlo pronto al terminar el temporal."
        elif c["agua"] == "riego":
            motivo = "Necesita riego. " + ("El riesgo de helada en esta época es bajo." if riesgo < RIESGO_HELADA
                                           else "Tolera el frío de esta época.")
        nota = None
        if c["agua"] == "temporal" and lluvia_actual is not None and ln:
            if lluvia_actual < 0.5 * ln:
                nota = f"En esta temporada llovió poco en {nom}: {lluvia_actual:.0f} mm."
            elif lluvia_actual > 1.5 * ln:
                nota = f"En esta temporada llovió mucho en {nom}: {lluvia_actual:.0f} mm."
        salida.append({"nombre": c["nombre"], "agua": c["agua"], "epoca": _epoca(c["meses"]),
                       "estado": estado, "motivo": motivo, "nota_anio": nota})
    orden = {"bien": 0, "riego": 1, "riesgo": 2}
    return sorted(salida, key=lambda x: (orden[x["estado"]], x["nombre"]))


def para_ciclo(clave, prob_helada, lluvia_normal, lluvia_del_ciclo):
    """Calendario y evaluación por mes de los cultivos que se siembran en el ciclo.
    lluvia_del_ciclo: {mes: mm o None} con la lluvia de cada mes del ciclo más reciente."""
    meses = CICLOS[clave]["meses"]
    por_mes = {m: evaluar_mes(m, prob_helada, lluvia_normal, lluvia_del_ciclo.get(m)) for m in meses}
    estados = {(c["nombre"], m): c["estado"] for m, lista in por_mes.items() for c in lista}
    cultivos = [{"nombre": c["nombre"], "agua": c["agua"],
                 "meses": {m: estados.get((c["nombre"], m)) for m in meses if m in c["meses"]}}
                for c in CULTIVOS if any(m in meses for m in c["meses"])]
    return {"por_mes": por_mes, "calendario": cultivos, "nota": NOTA}
