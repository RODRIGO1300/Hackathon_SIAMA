# Despliega el prototipo en IBM Cloud Code Engine a partir del Dockerfile del proyecto.
#
# Requisitos: IBM Cloud CLI (https://cloud.ibm.com/docs/cli) y haber iniciado sesión:
#     ibmcloud login --sso        (o: ibmcloud login --apikey <API_KEY>)
#
# Uso (desde cualquier carpeta):
#     powershell -ExecutionPolicy Bypass -File ibm\code-engine\desplegar.ps1
#     powershell -ExecutionPolicy Bypass -File ibm\code-engine\desplegar.ps1 -Region eu-de -GrupoRecursos MiGrupo
#
# Si existe un archivo .env en la raíz, sus variables con valor (watsonx.ai, PostgreSQL) se suben
# como secreto de Code Engine y la aplicación las recibe como variables de entorno.
param(
    [string]$Region = "us-south",
    [string]$GrupoRecursos = "Default",
    [string]$Proyecto = "siama-huecos",
    [string]$App = "siama-huecos",
    [string]$Secreto = "siama-ibm"
)
$ErrorActionPreference = "Stop"
$raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $raiz

function Paso($texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }
function Ejecutar { & ibmcloud @args; if ($LASTEXITCODE -ne 0) { throw "Falló: ibmcloud $args" } }
function Existe { & ibmcloud @args *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command ibmcloud -ErrorAction SilentlyContinue)) {
    throw "No se encontró IBM Cloud CLI. Instálelo desde https://cloud.ibm.com/docs/cli e inicie sesión con: ibmcloud login --sso"
}

Paso "Plugin de Code Engine"
if (-not (Existe plugin show code-engine)) { Ejecutar plugin install code-engine -f }

Paso "Región $Region, grupo de recursos $GrupoRecursos"
& ibmcloud target -r $Region -g $GrupoRecursos
if ($LASTEXITCODE -ne 0) { throw "No hay sesión activa o el grupo no existe. Ejecute: ibmcloud login --sso" }

Paso "Proyecto de Code Engine '$Proyecto'"
if (Existe ce project get --name $Proyecto) { Ejecutar ce project select --name $Proyecto }
else { Ejecutar ce project create --name $Proyecto }

$usarSecreto = $false
$envLocal = Join-Path $raiz ".env"
if (Test-Path $envLocal) {
    Paso "Secreto '$Secreto' a partir de .env"
    # Solo variables con valor; la ruta local del certificado no sirve dentro del contenedor (use SIAMA_PG_CA_CERT_B64).
    $lineas = Get-Content $envLocal -Encoding UTF8 | Where-Object {
        $_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.+)$' -and $Matches[1] -ne 'SIAMA_PG_CA_CERT'
    } | ForEach-Object { $_.Trim() }
    if ($lineas) {
        $tmp = Join-Path $env:TEMP "siama-ce.env"
        [IO.File]::WriteAllLines($tmp, [string[]]$lineas)
        try {
            if (Existe ce secret get --name $Secreto) { Ejecutar ce secret update --name $Secreto --from-env-file $tmp }
            else { Ejecutar ce secret create --name $Secreto --from-env-file $tmp }
        } finally { Remove-Item $tmp -Force }
        $usarSecreto = $true
        Write-Host ("Variables subidas: " + (($lineas | ForEach-Object { $_.Split('=')[0] }) -join ", "))
    } else { Write-Host ".env no tiene variables con valor; se despliega sin integraciones." }
} else {
    Write-Host "`nNo hay .env: se despliega sin watsonx.ai ni PostgreSQL (la API usa los archivos generados en la imagen)."
}

Paso "Aplicación '$App' (sube el código, construye la imagen con el Dockerfile y la publica)"
Write-Host "La construcción ejecuta el pipeline completo; puede tardar varios minutos."
if (Existe ce application get --name $App) {
    $extra = @(); if ($usarSecreto) { $extra = @("--env-from-secret", $Secreto) }
    Ejecutar ce application update --name $App --build-source . @extra
} else {
    $extra = @(); if ($usarSecreto) { $extra = @("--env-from-secret", $Secreto) }
    Ejecutar ce application create --name $App --build-source . --build-strategy dockerfile `
        --build-size large --build-timeout 1800 --port 8000 --cpu 1 --memory 4G --min-scale 0 --max-scale 2 @extra
}

$url = (& ibmcloud ce application get --name $App --output url).Trim()
Paso "Listo"
Write-Host "Demo:          $url/web/demo.html"
Write-Host "API (OpenAPI): $url/docs"
Write-Host "Estado:        $url/api/v1/salud"
