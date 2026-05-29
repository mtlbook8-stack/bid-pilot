// main.bicep
// Resource-group-scoped entry point for BidPilot's Azure infrastructure (Phase 11).
// Composes every module, wires resource endpoints into the Container App and
// Function App as BIDPILOT_ env vars, and grants the managed-identity RBAC in
// roles.bicep. Deploy with:
//   az deployment group create -g <rg> -f infra/main.bicep -p infra/parameters/dev.bicepparam

targetScope = 'resourceGroup'

@description('Short prefix used to derive all resource names (lowercase, 3-11 chars).')
@minLength(2)
@maxLength(11)
param namePrefix string = 'bidpilot'

@description('Environment short name (e.g. dev, prod) appended to resource names.')
param environmentName string = 'dev'

@description('Azure region for all regional resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Entra ID application (client) id used by the API for SSO. Optional at infra time.')
param entraClientId string = ''

@description('Entra ID tenant id.')
param entraTenantId string = subscription().tenantId

@description('Entra ID client secret. Passed as a secure param; stored in Key Vault out-of-band, never emitted as output.')
@secure()
param entraClientSecret string = ''

@description('Container image for the API. Override in CD once the real image is published.')
param apiContainerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Common tags applied to every resource.')
param tags object = {
  application: 'bidpilot'
  environment: environmentName
  managedBy: 'bicep'
}

// --- Derived names ---
// A short, deterministic suffix keeps globally-unique names stable across redeploys
// of the same RG while avoiding collisions between environments/subscriptions.
var uniqueSuffix = take(uniqueString(resourceGroup().id, namePrefix, environmentName), 6)
var baseName = '${namePrefix}-${environmentName}'

// Storage account names: lowercase alphanumeric only, max 24 chars — strip hyphens.
var storageAccountName = take(toLower('${namePrefix}${environmentName}st${uniqueSuffix}'), 24)
// Key Vault names: 3-24 chars, alphanumeric + hyphens.
var keyVaultName = take('${namePrefix}-${environmentName}-kv-${uniqueSuffix}', 24)
// Cosmos account names: lowercase, 3-44 chars.
var cosmosAccountName = toLower('${baseName}-cosmos-${uniqueSuffix}')

var logAnalyticsName = '${baseName}-log'
var appInsightsName = '${baseName}-appi'
var aiServicesName = toLower('${baseName}-ai-${uniqueSuffix}')
var docIntelligenceName = toLower('${baseName}-docint-${uniqueSuffix}')
var mapsAccountName = '${baseName}-maps'
var containerAppEnvName = '${baseName}-cae'
var containerAppName = '${baseName}-api'
var functionAppName = '${baseName}-func-${uniqueSuffix}'
var functionPlanName = '${baseName}-funcplan'

// ---------------------------------------------------------------------------
// Monitoring (Log Analytics + workspace-based App Insights)
// ---------------------------------------------------------------------------
module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    workspaceName: logAnalyticsName
    appInsightsName: appInsightsName
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// Storage (blob containers: bids, deploymentpackage)
// ---------------------------------------------------------------------------
module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    storageAccountName: storageAccountName
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// Key Vault (RBAC mode)
// ---------------------------------------------------------------------------
module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    keyVaultName: keyVaultName
    tenantId: entraTenantId
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB (database + 12 containers)
// ---------------------------------------------------------------------------
module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  params: {
    location: location
    cosmosAccountName: cosmosAccountName
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// AI Foundry (AI Services account + Claude Sonnet + GPT-5 deployments)
// ---------------------------------------------------------------------------
module aiFoundry 'modules/ai_foundry.bicep' = {
  name: 'aiFoundry'
  params: {
    location: location
    aiServicesName: aiServicesName
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// Document Intelligence
// ---------------------------------------------------------------------------
module docIntelligence 'modules/doc_intelligence.bicep' = {
  name: 'docIntelligence'
  params: {
    location: location
    docIntelligenceName: docIntelligenceName
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// Azure Maps (global account for geocoding)
// ---------------------------------------------------------------------------
module maps 'modules/maps.bicep' = {
  name: 'maps'
  params: {
    mapsAccountName: mapsAccountName
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// Container Apps environment + API app
// ---------------------------------------------------------------------------
module containerApps 'modules/container_apps.bicep' = {
  name: 'containerApps'
  params: {
    location: location
    environmentName: containerAppEnvName
    containerAppName: containerAppName
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    containerImage: apiContainerImage
    cosmosEndpoint: cosmos.outputs.cosmosEndpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    blobEndpoint: storage.outputs.blobEndpoint
    keyVaultUri: keyvault.outputs.keyVaultUri
    aiFoundryEndpoint: aiFoundry.outputs.aiFoundryEndpoint
    aiFoundryOpenAiEndpoint: aiFoundry.outputs.aiFoundryOpenAiEndpoint
    docIntelligenceEndpoint: docIntelligence.outputs.docIntelligenceEndpoint
    azureMapsClientId: maps.outputs.mapsClientId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    entraClientId: entraClientId
    entraTenantId: entraTenantId
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// Function App (Flex Consumption, Python 3.12)
// ---------------------------------------------------------------------------
module functions 'modules/functions.bicep' = {
  name: 'functions'
  params: {
    location: location
    functionAppName: functionAppName
    hostingPlanName: functionPlanName
    storageAccountName: storage.outputs.storageAccountName
    storageBlobEndpoint: storage.outputs.blobEndpoint
    deploymentContainerName: storage.outputs.deploymentPackageContainerName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    cosmosEndpoint: cosmos.outputs.cosmosEndpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    blobEndpoint: storage.outputs.blobEndpoint
    keyVaultUri: keyvault.outputs.keyVaultUri
    aiFoundryEndpoint: aiFoundry.outputs.aiFoundryEndpoint
    aiFoundryOpenAiEndpoint: aiFoundry.outputs.aiFoundryOpenAiEndpoint
    docIntelligenceEndpoint: docIntelligence.outputs.docIntelligenceEndpoint
    azureMapsClientId: maps.outputs.mapsClientId
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// RBAC — runs after both identities exist so principalIds are resolvable.
// ---------------------------------------------------------------------------
module roles 'modules/roles.bicep' = {
  name: 'roles'
  params: {
    containerAppPrincipalId: containerApps.outputs.principalId
    functionAppPrincipalId: functions.outputs.principalId
    cosmosAccountName: cosmos.outputs.cosmosAccountName
    storageAccountId: storage.outputs.storageAccountId
    keyVaultId: keyvault.outputs.keyVaultId
    aiServicesId: aiFoundry.outputs.aiServicesId
    docIntelligenceId: docIntelligence.outputs.docIntelligenceId
    mapsAccountId: maps.outputs.mapsAccountId
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
@description('Public URL of the FastAPI Container App.')
output apiUrl string = containerApps.outputs.apiUrl

@description('Public URL of the Function App.')
output functionUrl string = functions.outputs.functionUrl

@description('Cosmos DB account endpoint.')
output cosmosEndpoint string = cosmos.outputs.cosmosEndpoint

@description('Blob service endpoint.')
output blobEndpoint string = storage.outputs.blobEndpoint

@description('Key Vault URI.')
output keyVaultUri string = keyvault.outputs.keyVaultUri

@description('AI Foundry account endpoint.')
output aiFoundryEndpoint string = aiFoundry.outputs.aiFoundryEndpoint

@description('Document Intelligence endpoint.')
output docIntelligenceEndpoint string = docIntelligence.outputs.docIntelligenceEndpoint

@description('Azure Maps client id.')
output azureMapsClientId string = maps.outputs.mapsClientId

@description('Application Insights connection string.')
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
