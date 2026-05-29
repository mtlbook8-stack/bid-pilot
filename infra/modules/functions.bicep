// functions.bicep
// Python 3.12 Function App on a Flex Consumption plan (the modern serverless SKU
// that supports per-instance concurrency and managed-identity deployment).
// Triggers only: timers, Cosmos change feed, HTTP (see section 8 flows).
//
// The app runs with a system-assigned managed identity. AzureWebJobsStorage is
// configured for identity-based access (no connection string / account key), and
// the deployment package lives in the `deploymentpackage` blob container. All
// downstream RBAC is granted in roles.bicep against the principalId output here.

@description('Azure region for the Function App and its plan.')
param location string

@description('Name of the Function App.')
param functionAppName string

@description('Name of the Flex Consumption hosting plan.')
param hostingPlanName string

@description('Name of the backing storage account (already created by storage.bicep).')
param storageAccountName string

@description('Blob service endpoint of the backing storage account (for identity-based AzureWebJobsStorage).')
param storageBlobEndpoint string

@description('Name of the blob container that holds the deployment package.')
param deploymentContainerName string = 'deploymentpackage'

@description('Application Insights connection string.')
param appInsightsConnectionString string

@description('Python runtime version.')
param pythonVersion string = '3.12'

@description('Maximum number of instances for the Flex Consumption plan.')
param maximumInstanceCount int = 40

@description('Per-instance memory (MB) for Flex Consumption. Allowed: 512, 2048, 4096.')
@allowed([
  512
  2048
  4096
])
param instanceMemoryMB int = 2048

@description('Tags applied to every resource in this module.')
param tags object = {}

// --- Endpoints / config injected as BIDPILOT_ env vars ---
@description('Cosmos account document endpoint.')
param cosmosEndpoint string

@description('Cosmos SQL database name.')
param cosmosDatabaseName string = 'bidpilotdb'

@description('Blob service endpoint.')
param blobEndpoint string

@description('Key Vault URI.')
param keyVaultUri string

@description('AI Foundry account endpoint.')
param aiFoundryEndpoint string

@description('Azure OpenAI-compatible endpoint on the AI Foundry account.')
param aiFoundryOpenAiEndpoint string

@description('Document Intelligence endpoint.')
param docIntelligenceEndpoint string

@description('Azure Maps client id (x-ms-client-id).')
param azureMapsClientId string

// Reference the existing storage account so we can build the deployment-package URL.
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource hostingPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: hostingPlanName
  location: location
  tags: tags
  sku: {
    // FC1 is the Flex Consumption SKU tier.
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true // required for Linux
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          // Identity-based deployment storage — no SAS/keys; the app's managed
          // identity needs Storage Blob Data Contributor (granted in roles.bicep).
          type: 'blobContainer'
          value: '${storageBlobEndpoint}${deploymentContainerName}'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: maximumInstanceCount
        instanceMemoryMB: instanceMemoryMB
      }
      runtime: {
        name: 'python'
        version: pythonVersion
      }
    }
    siteConfig: {
      appSettings: [
        // Identity-based AzureWebJobsStorage (the __ syntax selects the blob URI
        // and credential mode instead of a connection string).
        {
          name: 'AzureWebJobsStorage__blobServiceUri'
          value: storageBlobEndpoint
        }
        {
          name: 'AzureWebJobsStorage__credential'
          value: 'managedidentity'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        // BIDPILOT_-prefixed config consumed by the shared Settings class.
        { name: 'BIDPILOT_COSMOS_ENDPOINT', value: cosmosEndpoint }
        { name: 'BIDPILOT_COSMOS_DATABASE_NAME', value: cosmosDatabaseName }
        { name: 'BIDPILOT_BLOB_ENDPOINT', value: blobEndpoint }
        { name: 'BIDPILOT_BLOB_BIDS_CONTAINER', value: 'bids' }
        { name: 'BIDPILOT_KEYVAULT_URI', value: keyVaultUri }
        { name: 'BIDPILOT_AI_FOUNDRY_ENDPOINT', value: aiFoundryEndpoint }
        { name: 'BIDPILOT_AI_FOUNDRY_OPENAI_ENDPOINT', value: aiFoundryOpenAiEndpoint }
        { name: 'BIDPILOT_DOC_INTELLIGENCE_ENDPOINT', value: docIntelligenceEndpoint }
        { name: 'BIDPILOT_AZURE_MAPS_CLIENT_ID', value: azureMapsClientId }
      ]
    }
  }
}

@description('System-assigned managed identity principalId of the Function App (for RBAC).')
output principalId string = functionApp.identity.principalId

@description('Default hostname of the Function App.')
output defaultHostName string = functionApp.properties.defaultHostName

@description('Full https URL of the Function App.')
output functionUrl string = 'https://${functionApp.properties.defaultHostName}'

@description('Function App name.')
output functionAppName string = functionApp.name
