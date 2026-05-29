// container_apps.bicep
// Container Apps managed environment (wired to Log Analytics) + the FastAPI API
// Container App. The app runs with a system-assigned managed identity; all
// downstream RBAC (Cosmos, Blob, Key Vault, AI, Maps) is granted in roles.bicep
// against the principalId this module outputs.
//
// All resource endpoints are injected as BIDPILOT_-prefixed env vars so the
// app's pydantic BaseSettings (env_prefix = "BIDPILOT_") picks them up directly.

@description('Azure region for the Container Apps environment and app.')
param location string

@description('Name of the Container Apps managed environment.')
param environmentName string

@description('Name of the API Container App.')
param containerAppName string

@description('Resource ID of the Log Analytics workspace the environment ships logs to.')
param logAnalyticsWorkspaceId string

@description('Container image for the API. Defaults to the hello-world placeholder so the env deploys before the real image exists; override with the real image in CD.')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Login server of the Azure Container Registry hosting the API image (e.g. bidpilotprodacr.azurecr.io). Empty means pull from a public registry.')
param containerRegistryLoginServer string = ''

@description('Port the API listens on inside the container.')
param targetPort int = 8000

@description('Minimum replica count. 0 = scale-to-zero when idle.')
param minReplicas int = 0

@description('Maximum replica count.')
param maxReplicas int = 3

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

@description('Application Insights connection string.')
param appInsightsConnectionString string

@description('Entra ID application (client) id used by the API for SSO.')
param entraClientId string = ''

@description('Entra ID tenant id.')
param entraTenantId string = subscription().tenantId

@description('Public origin of the deployed frontend (e.g. https://app.bidpilot.com). Used by the API for CORS. Empty means only the local Vite dev origins are allowed.')
param frontendUrl string = ''

// Reference the existing workspace (created in monitoring.bicep) by id so we can
// read its customerId and shared key without passing them in as params.
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: last(split(logAnalyticsWorkspaceId, '/'))
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        // customerId/sharedKey are required by the Container Apps log shipper.
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: tags
  identity: {
    // System-assigned identity — this principal is granted data-plane RBAC.
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      // Only configure ACR auth when the image is actually pulled from our ACR.
      // First-time deploy uses the public MCR hello-world placeholder; wiring ACR
      // registries here would force credential validation against an empty registry
      // before AcrPull RBAC has propagated, causing "Operation expired".
      registries: (empty(containerRegistryLoginServer) || !contains(containerImage, containerRegistryLoginServer)) ? [] : [
        {
          server: containerRegistryLoginServer
          identity: 'system'
        }
      ]
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
    }
    template: {
      containers: [
        {
          name: 'api'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          // BIDPILOT_-prefixed env vars consumed by Settings(BaseSettings).
          env: [
            { name: 'BIDPILOT_COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'BIDPILOT_COSMOS_DATABASE_NAME', value: cosmosDatabaseName }
            { name: 'BIDPILOT_BLOB_ENDPOINT', value: blobEndpoint }
            { name: 'BIDPILOT_BLOB_BIDS_CONTAINER', value: 'bids' }
            { name: 'BIDPILOT_KEYVAULT_URI', value: keyVaultUri }
            { name: 'BIDPILOT_AI_FOUNDRY_ENDPOINT', value: aiFoundryEndpoint }
            { name: 'BIDPILOT_AI_FOUNDRY_OPENAI_ENDPOINT', value: aiFoundryOpenAiEndpoint }
            { name: 'BIDPILOT_DOC_INTELLIGENCE_ENDPOINT', value: docIntelligenceEndpoint }
            { name: 'BIDPILOT_AZURE_MAPS_CLIENT_ID', value: azureMapsClientId }
            { name: 'BIDPILOT_APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'BIDPILOT_ENTRA_CLIENT_ID', value: entraClientId }
            { name: 'BIDPILOT_ENTRA_TENANT_ID', value: entraTenantId }
            { name: 'BIDPILOT_FRONTEND_URL', value: frontendUrl }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            // Concurrent-HTTP scaling rule so the app can scale from 0..maxReplicas.
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

@description('System-assigned managed identity principalId of the API app (for RBAC).')
output principalId string = apiApp.identity.principalId

@description('Public FQDN of the API app.')
output fqdn string = apiApp.properties.configuration.ingress.fqdn

@description('Full https URL of the API app.')
output apiUrl string = 'https://${apiApp.properties.configuration.ingress.fqdn}'

@description('Container App name.')
output containerAppName string = apiApp.name
