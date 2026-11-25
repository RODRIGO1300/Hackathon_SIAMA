# Integración con tecnologías de IBM

El prototipo usa cuatro tecnologías de IBM. **Todas son opcionales**: sin cuenta de IBM Cloud, el prototipo funciona
exactamente igual que antes. Así se respeta el stack que piden las bases del reto (Python, FastAPI, PostgreSQL + PostGIS,
Docker) y el puntaje de integrabilidad no se ve afectado.

| Tecnología de IBM | Para qué se usa | Qué pasa sin ella |
|---|---|---|
| **watsonx.ai** con **IBM Granite** | El asistente de IA redacta el resumen de cada estación y responde preguntas en español | Se usa el resumen de plantilla y el cuadro de preguntas se desactiva |
| **IBM Cloud Databases for PostgreSQL** (con PostGIS) | Guarda las series completadas y el diagnóstico en una base de datos gestionada; la API lee de ahí | La API lee los archivos de `salidas/` |
| **IBM Cloud Code Engine** | Publica la demo y la API en una URL pública, a partir del `Dockerfile` | Se corre en tu computadora con `uvicorn` o Docker |
| **IBM Carbon Design System** | Estilo visual de la demo y tema opcional del componente (`tema="carbon"`) | Siempre está activo en la demo; el componente sigue neutro por defecto para SIAMA |

Las credenciales van en un archivo `.env` en la raíz del proyecto, que **nunca se sube a git**:

```powershell
copy .env.example .env      # luego abre .env y llena lo que vayas a usar
```

---

## 1. watsonx.ai (IBM Granite)

**Qué necesitas:** una cuenta de IBM Cloud (el plan Lite es gratuito) con un proyecto de watsonx.ai.

1. Entra a https://dataplatform.cloud.ibm.com/wx y crea un **proyecto**. Si te lo pide, asocia un servicio
   **watsonx.ai Runtime** (antes Watson Machine Learning).
2. En el proyecto, abre **Administrar → General** y copia el **ID del proyecto**.
3. Crea una **API key** en https://cloud.ibm.com/iam/apikeys.
4. Llena en `.env`:
   ```
   WATSONX_APIKEY=tu_api_key
   WATSONX_PROJECT_ID=tu_id_de_proyecto
   WATSONX_URL=https://us-south.ml.cloud.ibm.com
   ```
   `WATSONX_URL` debe ser la región de tu servicio watsonx.ai Runtime (Dallas `us-south`, Fráncfort `eu-de`,
   Londres `eu-gb`, Tokio `jp-tok`…).
5. Prueba la conexión:
   ```powershell
   .venv\Scripts\python.exe -m api.watsonx
   ```
   Muestra los modelos Granite de chat de tu región y una respuesta de prueba. El modelo por defecto es
   `ibm/granite-4-h-small`. Si IBM lo retira, cambia `WATSONX_MODEL_ID` por uno de la lista.
6. Reinicia `uvicorn`. En la demo, la tarjeta **Asistente de IA** mostrará la etiqueta morada **IBM Granite** y el
   cuadro **Preguntar** quedará activo.

**Cómo evita que la IA invente datos:** Granite solo recibe los datos calculados por el pipeline para esa estación:
porcentaje de vacíos, huecos, vecinos usados, métricas de validación y significado de las banderas. Se le indica que no
use cifras fuera de ese contexto y que nunca presente un dato estimado como medido. La respuesta incluye el campo
`fuente`, así siempre se sabe si el texto lo escribió Granite o la plantilla.

**Endpoints:**
- `GET /api/v1/estaciones/{clave}/resumen`: usa Granite si está configurado; con `?ia=false` fuerza la plantilla.
- `GET /api/v1/estaciones/{clave}/preguntar?q=...`: pregunta libre (máximo 300 caracteres). Requiere watsonx.ai.
- `GET /api/v1/salud`: indica si watsonx.ai está configurado y qué modelo usa.

---

## 2. IBM Cloud Databases for PostgreSQL

1. En https://cloud.ibm.com/catalog busca **Databases for PostgreSQL** y crea una instancia.
2. En la instancia, abre **Credenciales de servicio → Nueva credencial**. De la credencial:
   - copia `connection.postgres.composed[0]` (empieza con `postgresql://`) y reemplaza `$PASSWORD` por la contraseña;
   - copia `connection.postgres.certificate.certificate_base64`.
3. Llena en `.env`:
   ```
   SIAMA_DATABASE_URL=postgresql://admin:CONTRASEÑA@xxxx.databases.appdomain.cloud:31234/ibmclouddb?sslmode=verify-full
   SIAMA_PG_CA_CERT_B64=LS0tLS1CRUdJTi...
   ```
4. Instala el controlador y carga los resultados:
   ```powershell
   .venv\Scripts\pip.exe install -r requirements-ibm.txt
   .venv\Scripts\python.exe -m siama_gaps postgres --salida salidas
   ```
   Se crea el esquema `siama_huecos` con las tablas `estaciones` (con geometría PostGIS), `series_completadas`,
   `diagnostico_estaciones`, `diagnostico_anual`, `huecos`, `vecinos`, `homogeneidad`, `qc_banderas`,
   `predicciones_test_publico` y `metricas` (JSONB). Puedes volver a ejecutarlo: reemplaza los datos y no los duplica.
5. Reinicia `uvicorn`. `GET /api/v1/salud` debe decir `"fuente_datos": "postgresql"`.

Ejemplo de consulta espacial desde SIAMA:
```sql
SELECT e.nombre, s.fecha, s.valor, s.bandera
FROM siama_huecos.series_completadas s JOIN siama_huecos.estaciones e USING (clave)
WHERE s.variable = 'precipitacion' AND s.fecha = '2023-07-15'
  AND ST_DWithin(e.geom::geography, ST_MakePoint(-101.68, 21.12)::geography, 50000);
```

Funciona con **cualquier PostgreSQL con PostGIS**, como el de SIAMA o uno local. Solo cambia `SIAMA_DATABASE_URL`.

---

## 3. IBM Cloud Code Engine (URL pública)

**Qué necesitas:** [IBM Cloud CLI](https://cloud.ibm.com/docs/cli) instalado.

```powershell
ibmcloud login --sso
powershell -ExecutionPolicy Bypass -File ibm\code-engine\desplegar.ps1
```

Opciones: `-Region eu-de`, `-GrupoRecursos MiGrupo`, `-Proyecto`, `-App`. En Linux, Mac o
[IBM Cloud Shell](https://cloud.ibm.com/shell) usa `bash ibm/code-engine/desplegar.sh`.

El script:
1. instala el plugin de Code Engine si falta;
2. crea o selecciona el proyecto `siama-huecos`;
3. si tienes un `.env`, sube sus variables como **secreto** `siama-ibm`, así la app en la nube también usa watsonx.ai y PostgreSQL.
   La ruta local del certificado (`SIAMA_PG_CA_CERT`) no sirve dentro de la nube, así que usa `SIAMA_PG_CA_CERT_B64`;
4. sube el código, construye la imagen con el `Dockerfile` y crea la aplicación (1 vCPU, 4 GB, escala a cero cuando no
   se usa);
5. imprime la URL de la demo, de la documentación y de la verificación de salud.

La construcción ejecuta el pipeline completo, así que tarda varios minutos. Para publicar cambios, vuelve a correr el script.
`.ceignore` evita subir `.venv`, `salidas`, `.env` y certificados.

---

## 4. IBM Carbon Design System

- `web/demo.html` usa la estructura de Carbon (UI Shell, pestañas, mosaicos, etiquetas, tabla de datos), los
  tokens del tema **g10** y la tipografía **IBM Plex Sans / Plex Mono**.
- El componente `<siama-huecos>` acepta `tema="carbon"`: colores de Carbon para observado y estimado, colores de estado
  para el mapa y controles con estilo Carbon. Sin ese atributo conserva el estilo neutro, para no chocar con el
  diseño actual de Monitor Precipitaciones y Monitor Temperaturas.

```html
<siama-huecos api="https://SERVIDOR" variable="tmax" tema="carbon"></siama-huecos>
```
