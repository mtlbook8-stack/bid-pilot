// storage.bicep
// Storage Account (Standard_LRS) with two blob containers:
//   - bids:              original bid PDFs ingested from email
//   - deploymentpackage: zip package used by the Flex Consumption Function App
// Access is via managed identity + Storage Blob Data Contributor RBAC, so we
// disable shared-key auth where the platform allows it. The Function App's
// deployment storage still requires the account to exist; the Function uses its
// own managed identity to reach the deploymentpackage container.

@description('Azure region for the storage account.')
param location string

@description('Globally unique storage account name (3-24 lowercase alphanumeric chars).')
param storageAccountName string

@description('Tags applied to every resource in this module.')
param tags object = {}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    // Prefer Entra ID (managed identity) auth. Shared keys remain enabled because
    // the Flex Consumption deployment-storage flow can still depend on them in some
    // regions; RBAC is what the apps actually use at runtime.
    allowSharedKeyAccess: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource bidsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'bids'
  properties: {
    publicAccess: 'None'
  }
}

resource deploymentPackageContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'deploymentpackage'
  properties: {
    publicAccess: 'None'
  }
}

@description('Primary blob service endpoint (e.g. https://acct.blob.core.windows.net/).')
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob

@description('Storage account name.')
output storageAccountName string = storageAccount.name

@description('Resource ID of the storage account (used for RBAC scoping).')
output storageAccountId string = storageAccount.id

@description('Name of the deployment package container (consumed by functions module).')
output deploymentPackageContainerName string = deploymentPackageContainer.name
