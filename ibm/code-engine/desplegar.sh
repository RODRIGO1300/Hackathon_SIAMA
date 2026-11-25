#!/usr/bin/env bash
# Despliega el prototipo en IBM Cloud Code Engine (Linux, Mac o IBM Cloud Shell).
#
# Requisitos: IBM Cloud CLI e inicio de sesión:  ibmcloud login --sso
# Uso:  REGION=us-south GRUPO=Default bash ibm/code-engine/desplegar.sh
set -euo pipefail

REGION="${REGION:-us-south}"
GRUPO="${GRUPO:-Default}"
PROYECTO="${PROYECTO:-siama-huecos}"
APP="${APP:-siama-huecos}"
SECRETO="${SECRETO:-siama-ibm}"
cd "$(dirname "$0")/../.."

paso() { printf '\n==> %s\n' "$*"; }
existe() { ibmcloud "$@" >/dev/null 2>&1; }

command -v ibmcloud >/dev/null || { echo "Instale IBM Cloud CLI: https://cloud.ibm.com/docs/cli"; exit 1; }

paso "Plugin de Code Engine"
existe plugin show code-engine || ibmcloud plugin install code-engine -f

paso "Región $REGION, grupo de recursos $GRUPO"
ibmcloud target -r "$REGION" -g "$GRUPO" || { echo "Inicie sesión con: ibmcloud login --sso"; exit 1; }

paso "Proyecto '$PROYECTO'"
if existe ce project get --name "$PROYECTO"; then ibmcloud ce project select --name "$PROYECTO"
else ibmcloud ce project create --name "$PROYECTO"; fi

EXTRA=()
if [[ -f .env ]]; then
  TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
  grep -E '^[[:space:]]*[A-Z0-9_]+[[:space:]]*=[[:space:]]*[^[:space:]]' .env | grep -v '^[[:space:]]*SIAMA_PG_CA_CERT=' | sed 's/^[[:space:]]*//' > "$TMP" || true
  if [[ -s "$TMP" ]]; then
    paso "Secreto '$SECRETO' a partir de .env"
    if existe ce secret get --name "$SECRETO"; then ibmcloud ce secret update --name "$SECRETO" --from-env-file "$TMP"
    else ibmcloud ce secret create --name "$SECRETO" --from-env-file "$TMP"; fi
    EXTRA=(--env-from-secret "$SECRETO")
  fi
fi

paso "Aplicación '$APP' (la construcción ejecuta el pipeline; puede tardar varios minutos)"
if existe ce application get --name "$APP"; then
  ibmcloud ce application update --name "$APP" --build-source . "${EXTRA[@]}"
else
  ibmcloud ce application create --name "$APP" --build-source . --build-strategy dockerfile \
    --build-size large --build-timeout 1800 --port 8000 --cpu 1 --memory 4G --min-scale 0 --max-scale 2 "${EXTRA[@]}"
fi

URL="$(ibmcloud ce application get --name "$APP" --output url)"
paso "Listo"
echo "Demo:          $URL/web/demo.html"
echo "API (OpenAPI): $URL/docs"
echo "Estado:        $URL/api/v1/salud"
