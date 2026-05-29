// container_registry.bicep
// Azure Container Registry that hosts the BidPilot API image. The Container App
// pulls from this registry using its system-assigned managed identity (no admin
// user, no passwords) — RBAC is granted in roles.bicep via AcrPull.

@description('Azure region for the registry.')
param location string

@description('Globally-unique registry name (alphanumeric, 5-50 chars).')
param registryName string

@description('SKU. Basic is fine for a single-image app; bump to Standard/Premium for geo-replication or private endpoints.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param sku string = 'Basic'

@description('Tags applied to the registry.')
param tags object = {}

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    // Admin user disabled — only managed-identity (AcrPull) access is allowed.
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

@description('Resource id of the registry (used to scope the AcrPull role assignment).')
output registryId string = registry.id

@description('Login server hostname, e.g. bidpilotprodacr.azurecr.io.')
output loginServer string = registry.properties.loginServer

@description('Registry name.')
output registryName string = registry.name
