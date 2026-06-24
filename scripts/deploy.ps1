#!/usr/bin/env pwsh
# Deploy the API to Azure Container Apps.
#
# Usage: .\scripts\deploy.ps1
#
# Handles the Meshimer CA corporate SSL-inspection proxy automatically by using
# Windows Schannel (truststore) instead of Python's certifi bundle, which
# avoids the AKI-extension requirement that the proxy-issued certs fail.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- Config ---
$AZ_PYTHON    = "C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\python.exe"
$ACR_NAME     = "bidpilotdevacr7gjss5"
$IMAGE_NAME   = "bidpilot-api"
$APP_NAME     = "bidpilot-dev-api"
$RESOURCE_GROUP = "rg-bidpilot"

# --- Derive image tag from current git commit ---
$IMAGE_TAG = (git rev-parse --short HEAD).Trim()
$IMAGE_REF = "$ACR_NAME.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}"

Write-Host "==> Deploying $IMAGE_REF"

# --- Ensure truststore is installed (needed for corporate proxy SSL) ---
Write-Host "==> Checking truststore..."
& $AZ_PYTHON -m pip install truststore --quiet 2>$null
if ($LASTEXITCODE -ne 0) { throw "pip install truststore failed" }

# --- Write the az proxy wrapper to a temp file ---
$WRAPPER = "$env:TEMP\az_corp_proxy.py"
@'
# Injects Windows Schannel into Python ssl so az works through the Meshimer
# CA corporate proxy without the AKI-extension error (Python 3.13 strict check).
import truststore
truststore.inject_into_ssl()
import sys
sys.argv = ["az"] + sys.argv[1:]
import runpy
runpy.run_module("azure.cli", run_name="__main__", alter_sys=True)
'@ | Set-Content $WRAPPER -Encoding utf8

$env:PYTHONIOENCODING = "utf-8"

# --- Build and push image to ACR ---
Write-Host "==> Building image in ACR..."
& $AZ_PYTHON $WRAPPER acr build `
    --registry $ACR_NAME `
    --image "${IMAGE_NAME}:${IMAGE_TAG}" `
    --file Dockerfile `
    .
if ($LASTEXITCODE -ne 0) { throw "ACR build failed" }

# --- Update Container App ---
Write-Host "==> Updating Container App $APP_NAME..."
& $AZ_PYTHON $WRAPPER containerapp update `
    --name $APP_NAME `
    --resource-group $RESOURCE_GROUP `
    --image $IMAGE_REF
if ($LASTEXITCODE -ne 0) { throw "Container App update failed" }

Write-Host "==> Done. Live image: $IMAGE_REF"

# --- Frontend deployment ---
Write-Host ""
Write-Host "==> Building frontend..."

# Resolve the Container App FQDN so the frontend can reach the API in production.
$API_FQDN = (& $AZ_PYTHON $WRAPPER containerapp show `
    --name $APP_NAME --resource-group $RESOURCE_GROUP `
    --query "properties.configuration.ingress.fqdn" -o tsv 2>&1 |
    Where-Object { $_ -notmatch "UserWarning|Warning|site-packages|cryptography" })
$env:VITE_API_BASE_URL = "https://$($API_FQDN.Trim())/api"
Write-Host "    VITE_API_BASE_URL=$($env:VITE_API_BASE_URL)"

Push-Location "$PSScriptRoot\..\frontend"
try {
    & npm ci --quiet
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }

    Write-Host "==> Deploying frontend to Azure Static Web Apps..."
    $SWA_TOKEN = (& $AZ_PYTHON $WRAPPER staticwebapp secrets list `
        --name bidpilot-dev-swa `
        --resource-group $RESOURCE_GROUP `
        --query "properties.apiKey" -o tsv 2>&1 | Where-Object { $_ -notmatch "UserWarning|Warning|site-packages|cryptography" })
    & swa deploy ./dist --deployment-token $SWA_TOKEN --env production
    if ($LASTEXITCODE -ne 0) { throw "SWA deploy failed" }
    Write-Host "==> Frontend deployed."
} finally {
    Pop-Location
}
