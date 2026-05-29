// prod.bicepparam — production environment parameters.
// Deploy: az deployment group create -g <rg> -f infra/main.bicep -p infra/parameters/prod.bicepparam
using '../main.bicep'

param namePrefix = 'bidpilot'
param environmentName = 'prod'
// location intentionally omitted — defaults to resourceGroup().location.

// Entra ID app registration values for the prod tenant.
param entraClientId = readEnvironmentVariable('BIDPILOT_ENTRA_CLIENT_ID', '00000000-0000-0000-0000-000000000000')
param entraTenantId = readEnvironmentVariable('BIDPILOT_ENTRA_TENANT_ID', '00000000-0000-0000-0000-000000000000')

// Secret: supplied only via the CI secret store / pipeline variable. Must be set
// in prod — an empty value should fail the deployment's downstream secret wiring.
param entraClientSecret = readEnvironmentVariable('BIDPILOT_ENTRA_CLIENT_SECRET', '')

// CD pipeline overrides this with the immutable, digest-pinned production image.
param apiContainerImage = readEnvironmentVariable('BIDPILOT_API_IMAGE', 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest')

// Public origin of the deployed SPA. Used by the API for CORS.
param frontendUrl = readEnvironmentVariable('BIDPILOT_FRONTEND_URL', '')
