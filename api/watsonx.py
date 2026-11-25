"""Cliente mínimo de IBM watsonx.ai (modelos IBM Granite) para el asistente de IA de SIAMA.

No requiere dependencias adicionales: usa la API REST de watsonx.ai con la biblioteca estándar.
Si no hay credenciales, o watsonx.ai no responde, la API sigue funcionando con el texto de plantilla.

Variables de entorno:
  WATSONX_APIKEY       API key de IBM Cloud (obligatoria para activar watsonx.ai)
  WATSONX_PROJECT_ID   ID del proyecto de watsonx.ai (o WATSONX_SPACE_ID para un espacio de despliegue)
  WATSONX_URL          URL regional, por defecto https://us-south.ml.cloud.ibm.com (Dallas)
  WATSONX_MODEL_ID     Modelo Granite, por defecto ibm/granite-4-h-small
  WATSONX_API_VERSION  Versión de la API REST, por defecto 2024-10-08

Prueba rápida de credenciales:  python -m api.watsonx
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

IAM_URL = os.environ.get("WATSONX_IAM_URL", "https://iam.cloud.ibm.com/identity/token")
MODELO_POR_DEFECTO = "ibm/granite-4-h-small"

INSTRUCCIONES = (
    "Eres el asistente de IA de SIAMA, el sistema de información del agua y medio ambiente de Guanajuato. "
    "Respondes en español, con lenguaje claro para personas que no son especialistas en clima. "
    "Usa EXCLUSIVAMENTE los datos que se te entregan en el contexto: no inventes cifras, estaciones ni fechas, "
    "y si la información no alcanza para responder, dilo. Distingue siempre entre datos medidos y datos estimados: "
    "un dato estimado nunca es una medición. No uses formato Markdown ni listas."
)


class ErrorWatsonx(RuntimeError):
    pass


class Watsonx:
    def __init__(self):
        self.apikey = os.environ.get("WATSONX_APIKEY", "")
        self.project_id = os.environ.get("WATSONX_PROJECT_ID", "")
        self.space_id = os.environ.get("WATSONX_SPACE_ID", "")
        self.url = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com").rstrip("/")
        self.modelo = os.environ.get("WATSONX_MODEL_ID", MODELO_POR_DEFECTO)
        self.version = os.environ.get("WATSONX_API_VERSION", "2024-10-08")
        self.timeout = float(os.environ.get("WATSONX_TIMEOUT", "30"))
        self._token, self._expira = None, 0.0
        self._lock = threading.Lock()

    @property
    def configurado(self):
        return bool(self.apikey and (self.project_id or self.space_id))

    def estado(self):
        return {"configurado": self.configurado, "modelo": self.modelo if self.configurado else None,
                "region": self.url if self.configurado else None}

    # --- HTTP ---------------------------------------------------------------------------------------------
    def _peticion(self, url, datos, cabeceras):
        req = urllib.request.Request(url, data=datos, headers=cabeceras, method="POST" if datos else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:300]
            raise ErrorWatsonx(f"watsonx.ai respondió {e.code}: {detalle}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise ErrorWatsonx(f"no se pudo contactar a watsonx.ai: {e}") from None

    def _token_iam(self):
        with self._lock:
            if self._token and time.time() < self._expira - 120:
                return self._token
            cuerpo = urllib.parse.urlencode({"grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                                             "apikey": self.apikey}).encode()
            r = self._peticion(IAM_URL, cuerpo, {"Content-Type": "application/x-www-form-urlencoded",
                                                 "Accept": "application/json"})
            self._token = r["access_token"]
            self._expira = float(r.get("expiration", time.time() + 3600))
            return self._token

    def _cabeceras(self):
        return {"Authorization": f"Bearer {self._token_iam()}", "Content-Type": "application/json",
                "Accept": "application/json"}

    # --- Chat con Granite ---------------------------------------------------------------------------------
    def chat(self, mensajes, max_tokens=400):
        if not self.configurado:
            raise ErrorWatsonx("watsonx.ai no está configurado (faltan WATSONX_APIKEY y WATSONX_PROJECT_ID)")
        cuerpo = {"model_id": self.modelo, "messages": mensajes, "max_tokens": max_tokens,
                  "temperature": 0, "time_limit": int(self.timeout * 1000)}
        if self.project_id:
            cuerpo["project_id"] = self.project_id
        else:
            cuerpo["space_id"] = self.space_id
        url = f"{self.url}/ml/v1/text/chat?version={self.version}"
        r = self._peticion(url, json.dumps(cuerpo).encode("utf-8"), self._cabeceras())
        try:
            return r["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError):
            raise ErrorWatsonx(f"respuesta inesperada de watsonx.ai: {str(r)[:300]}") from None

    def redactar_resumen(self, contexto):
        return self.chat([
            {"role": "system", "content": INSTRUCCIONES},
            {"role": "user", "content":
                "Redacta un resumen de un solo párrafo (3 a 5 oraciones) sobre qué tan completa está la información "
                "de esta estación climatológica y qué tan confiables son los datos estimados. Conserva las cifras "
                f"exactamente como aparecen.\n\nContexto:\n{contexto}"},
        ])

    def responder(self, contexto, pregunta):
        return self.chat([
            {"role": "system", "content": INSTRUCCIONES},
            {"role": "user", "content": f"Contexto de la estación:\n{contexto}\n\nPregunta del usuario: {pregunta}\n\n"
                                        "Responde en máximo 4 oraciones."},
        ])

    def modelos_granite(self):
        url = f"{self.url}/ml/v1/foundation_model_specs?version={self.version}&limit=200"
        r = self._peticion(url, None, {"Accept": "application/json"})
        return sorted(m["model_id"] for m in r.get("resources", []) if "granite" in m["model_id"]
                      and any(f.get("id") == "text_chat" for f in m.get("functions", [])))


_cliente = None


def cliente():
    global _cliente
    if _cliente is None:
        _cliente = Watsonx()
    return _cliente


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from siama_gaps.entorno import cargar_env

    cargar_env()
    w = cliente()
    print("Región:", w.url)
    try:
        print("Modelos Granite de chat en la región:", ", ".join(w.modelos_granite()) or "ninguno")
    except ErrorWatsonx as e:
        print("No se pudo listar modelos:", e)
    if not w.configurado:
        sys.exit("Faltan WATSONX_APIKEY y WATSONX_PROJECT_ID (ver .env.example).")
    print("Modelo configurado:", w.modelo)
    print("Respuesta de prueba:", w.chat([{"role": "user", "content": "Responde solo: conexión correcta"}], 20))
