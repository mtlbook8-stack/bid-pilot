// roles.bicep
// All RBAC for the API Container App and the Function App managed identities,
// per section 9.2. Two distinct mechanisms are used:
//
//   1. Cosmos DB DATA-plane access is NOT Azure RBAC. It is granted via
//      Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments, binding the
//      principal to the built-in "Cosmos DB Built-in Data Contributor" SQL role
//      definition (id ...0002) scoped to the account.
//
//   2. Everything else (Blob, Key Vault, AI Services, Doc Intelligence, Maps) is
//      standard Azure RBAC via Microsoft.Authorization/roleAssignments, scoped to
//      each target resource and named with guid() for idempotency.

@description('Principal id (system-assigned MI) of the API Container App.')
param containerAppPrincipalId string

@description('Principal id (system-assigned MI) of the Function App.')
param functionAppPrincipalId string

@description('Cosmos account name (parent for the SQL role assignments).')
param cosmosAccountName string

@description('Resource id of the Storage Account.')
param storageAccountId string

@description('Resource id of the Key Vault.')
param keyVaultId string

@description('Resource id of the AI Services (Foundry) account.')
param aiServicesId string

@description('Resource id of the Document Intelligence account.')
param docIntelligenceId string

@description('Resource id of the Azure Maps account.')
param mapsAccountId string

// --- Built-in role definition GUIDs (Azure RBAC) ---
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var azureMapsDataReaderRoleId = '423170ca-a8f6-4b0f-8487-9e4eb8f49bfc'

// --- Cosmos SQL (data-plane) built-in role: Cosmos DB Data Contributor ---
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

// Convenience array so each role assignment is declared once per principal.
var principals = [
  { name: 'containerapp', principalId: containerAppPrincipalId }
  { name: 'functionapp', principalId: functionAppPrincipalId }
]

// Reference the existing target resources for scoping.
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: last(split(storageAccountId, '/'))
}
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: last(split(keyVaultId, '/'))
}
resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: last(split(aiServicesId, '/'))
}
resource docIntelligence 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: last(split(docIntelligenceId, '/'))
}
resource maps 'Microsoft.Maps/accounts@2023-06-01' existing = {
  name: last(split(mapsAccountId, '/'))
}

// ---------------------------------------------------------------------------
// Cosmos DB Data Contributor (data-plane SQL role) for both identities.
// ---------------------------------------------------------------------------
resource cosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for p in principals: {
    parent: cosmosAccount
    // Deterministic GUID name keyed on account + principal + role.
    name: guid(cosmosAccount.id, p.principalId, cosmosDataContributorRoleId)
    properties: {
      roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
      principalId: p.principalId
      scope: cosmosAccount.id
    }
  }
]

// ---------------------------------------------------------------------------
// Storage Blob Data Contributor for both identities.
// ---------------------------------------------------------------------------
resource storageBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in principals: {
    scope: storageAccount
    name: guid(storageAccount.id, p.principalId, storageBlobDataContributorRoleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
      principalId: p.principalId
      principalType: 'ServicePrincipal'
    }
  }
]

// ---------------------------------------------------------------------------
// Key Vault Secrets User for both identities.
// ---------------------------------------------------------------------------
resource keyVaultSecretsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in principals: {
    scope: keyVault
    name: guid(keyVault.id, p.principalId, keyVaultSecretsUserRoleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
      principalId: p.principalId
      principalType: 'ServicePrincipal'
    }
  }
]

// ---------------------------------------------------------------------------
// Cognitive Services User on the AI Services (Foundry) account for both identities.
// ---------------------------------------------------------------------------
resource aiServicesRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in principals: {
    scope: aiServices
    name: guid(aiServices.id, p.principalId, cognitiveServicesUserRoleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
      principalId: p.principalId
      principalType: 'ServicePrincipal'
    }
  }
]

// ---------------------------------------------------------------------------
// Cognitive Services User on Document Intelligence — Container App ONLY
// (the API parses PDFs; the workers do not call Doc Intelligence directly).
// ---------------------------------------------------------------------------
resource docIntelligenceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: docIntelligence
  name: guid(docIntelligence.id, containerAppPrincipalId, cognitiveServicesUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Azure Maps Data Reader for both identities.
// ---------------------------------------------------------------------------
resource mapsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in principals: {
    scope: maps
    name: guid(maps.id, p.principalId, azureMapsDataReaderRoleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMapsDataReaderRoleId)
      principalId: p.principalId
      principalType: 'ServicePrincipal'
    }
  }
]
