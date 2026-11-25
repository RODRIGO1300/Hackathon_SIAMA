# Agro SIAMA · Pitch de cinco minutos

Guion oral para presentar el prototipo. Los tiempos incluyen las pausas y el recorrido por la demo. Los encabezados y las indicaciones entre corchetes sirven como guía.

## 0:00–0:50 · Una pregunta desde el campo

Don Miguel es un Agricultor de alimentos, y al final de la temporada quiere comprender por que su cultivo no dio el rendimiento esperado. ¿Que fue lo que paso?, ante esto recuerda que no ha llovido recientemente y quisiera saber exactamente cuantos dias no llovieron.

Esa es la situacion que origino la idea de Agro SIAMA. ¿Cómo podemos aprovechar mejor los datos que ya existen y decirle a quien los consulta cuánta evidencia hay detrás de cada cifra?

## 0:50–1:40 · Qué aportamos a SIAMA

Agro SIAMA es un prototipo que amplía lo que SIAMA puede ofrecer a productores y personal técnico. Proponemos integrar un módulo a sus monitores actuales para identificar vacíos en los registros diarios de lluvia y temperaturas máxima y mínima. SIAMA sigue siendo el punto de consulta y el módulo añade una forma de interpretar esos vacíos.

Primero revisamos los registros. Cuando falta un dato, buscamos evidencia en la historia de la estación y en estaciones cercanas cuyo comportamiento ha sido parecido. Probamos distintos métodos de estimación y elegimos según la variable y la duración del hueco. Cada valor estimado se identifica como tal y se acompaña de un intervalo de incertidumbre y una bandera de calidad. Si la evidencia es insuficiente, el día queda marcado como no estimable.

## 1:40–3:00 · Qué ve una persona productora

[Abrir la vista **Clima para el campo**. Seleccionar Salamanca y una temporada con datos. Señalar la lluvia de temporada y el porcentaje de días medidos.]

Volvamos a la pregunta inicial. En esta vista podemos comparar la lluvia de una temporada con el promedio histórico y revisar cuánto duró su racha seca más larga. Si la productora recuerda varias semanas complicadas, puede consultar si la estación registró una racha similar y usar ese antecedente al planear la siguiente temporada.

Junto a los indicadores aparece el porcentaje de días medidos. Ese número ayuda a interpretar la comparación. Si la proporción de mediciones es baja, conviene revisar el detalle antes de usar el resultado para tomar una decisión.

[Señalar las heladas y el balance de agua.]

También podemos consultar cuántos días con helada hubo y ver un balance que compara la lluvia con la demanda atmosférica de agua estimada. Estos indicadores dan contexto para conversar con un técnico sobre fechas de siembra o revisar si vale la pena prever riego de apoyo. El historial de la estación es una referencia. La decisión también depende del cultivo, del suelo y de lo que se observa en la parcela.

## 3:00–4:15 · Qué probamos en Salamanca

[Abrir el monitor del prototipo y señalar un punto estimado y sus límites de incertidumbre.]

Para probar el módulo usamos registros históricos de las estaciones Salamanca y La Joyita, provenientes de CLICOM, la base climatológica del Servicio Meteorológico Nacional. Ocultamos temporalmente algunos datos que sí se habían medido y comparamos las estimaciones con los valores reales.

En esa prueba, para la lluvia, el error absoluto medio fue de alrededor de un milímetro y medio entre los días que se pudieron estimar. Cerca de una cuarta parte de los días de prueba quedó como no estimable. Las dos cifras importan juntas. Una indica qué tan cerca quedaron las estimaciones cuando hubo información para hacerlas. La otra muestra cuántas veces la información disponible fue insuficiente.

En la gráfica se puede revisar ese detalle día por día. Así, quien consulta un indicador agrícola puede volver a los datos que lo sustentan y distinguir qué se midió, qué se estimó y dónde sigue habiendo un vacío.

## 4:15–5:00 · Invitación a un piloto con SIAMA

Proponemos un piloto en Salamanca con el equipo de SIAMA, productores y personal técnico agrícola. Queremos probar el módulo dentro del flujo de consulta de SIAMA y revisar con usuarios si los indicadores responden a preguntas que realmente se hacen en el campo. También queremos comprobar si las marcas de calidad se entienden y en qué estaciones hay suficiente información para extender el piloto.

Queremos que, al volver a su historial, la productora pueda responder tres preguntas antes de usarlo para planear su siguiente temporada. ¿Qué registró la estación? ¿Qué se pudo estimar con los datos disponibles? ¿Dónde sigue faltando información? Eso es lo que proponemos sumar a SIAMA.

## Referencias para preparar la presentación

- [Vista Clima para el campo](../../web/agro.html) disponible en la ruta `/agro` de la demo local.
- [Componente de monitoreo](../../web/demo.html) disponible en la ruta `/web/demo.html`.
- [Origen de los registros de Salamanca y La Joyita](../../datos_salamanca/diccionario_datos.md).
- [Reporte de la prueba con huecos artificiales](../../salidas_salamanca/reporte_metricas.md). Las cifras del guion corresponden a la fila de precipitación, clase `todas`, método `recomendado`.
