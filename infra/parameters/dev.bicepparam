// dev.bicepparam — development environment parameters.
// Deploy: az deployment group create -g <rg> -f infra/main.bicep -p infra/parameters/dev.bicepparam
using '../main.bicep'

param namePrefix = 'bidpilot'
param environmentName = 'dev'
// location intentionally omitted — defaults to resourceGroup().location.

// Entra ID app registration values for the dev tenant.
// Replace the placeholders, or supply via environment variables in CI.
param entraClientId = readEnvironmentVariable('BIDPILOT_ENTRA_CLIENT_ID', '00000000-0000-0000-0000-000000000000')
param entraTenantId = readEnvironmentVariable('BIDPILOT_ENTRA_TENANT_ID', 'c40c1d20-61e0-4cb1-8e3e-a2d533cdd8ed')

// Secret: never hardcode. Pulled from the environment at build time (CI secret /
// local export). The infra does not persist it to Key Vault automatically; load it
// into Key Vault out-of-band and reference it from app config.
param entraClientSecret = readEnvironmentVariable('BIDPILOT_ENTRA_CLIENT_SECRET', '')

// Placeholder image; CD overrides with the published API image.
param apiContainerImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// Public origin of the deployed SPA. Empty in dev means CORS allows only the
// local Vite origins baked into src/api/main.py.
param frontendUrl = readEnvironmentVariable('BIDPILOT_FRONTEND_URL', '')
