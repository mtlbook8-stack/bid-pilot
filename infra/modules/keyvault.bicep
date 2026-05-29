// keyvault.bicep
// Key Vault in RBAC-authorization mode (no access policies). The apps reach
// secrets via the "Key Vault Secrets User" role assigned in roles.bicep. Soft
// delete is always on for new vaults; we set a 7-day retention window.

@description('Azure region for the key vault.')
param location string

@description('Globally unique key vault name (3-24 chars).')
param keyVaultName string

@description('Entra tenant ID that owns the vault.')
param tenantId string = subscription().tenantId

@description('Tags applied to every resource in this module.')
param tags object = {}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    // RBAC mode: authorization is driven by Azure role assignments, not the
    // legacy per-vault accessPolicies array.
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    // Purge protection is intentionally left off so dev vaults can be fully
    // removed; enable it in prod parameters if hard-delete protection is required.
    enablePurgeProtection: null
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

@description('Key Vault URI (e.g. https://vault.vault.azure.net/).')
output keyVaultUri string = keyVault.properties.vaultUri

@description('Resource ID of the key vault (used for RBAC scoping).')
output keyVaultId string = keyVault.id

@description('Key Vault name.')
output keyVaultName string = keyVault.name
