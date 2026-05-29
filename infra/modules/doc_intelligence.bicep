// doc_intelligence.bicep
// Azure Document Intelligence (Cognitive Services account of kind
// 'FormRecognizer'). Used with the prebuilt-layout model to parse bid PDFs.
// Managed-identity auth via Cognitive Services User RBAC (roles.bicep); local
// key auth disabled.

@description('Azure region for the Document Intelligence account.')
param location string

@description('Globally unique Document Intelligence account name.')
param docIntelligenceName string

@description('Custom subdomain — required for Entra ID auth. Defaults to the account name.')
param customSubDomainName string = docIntelligenceName

@description('Tags applied to every resource in this module.')
param tags object = {}

resource docIntelligence 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: docIntelligenceName
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: {
    // S0 standard tier — required for prebuilt-layout at production volumes.
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: customSubDomainName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

@description('Document Intelligence endpoint.')
output docIntelligenceEndpoint string = docIntelligence.properties.endpoint

@description('Resource ID of the Document Intelligence account (used for RBAC scoping).')
output docIntelligenceId string = docIntelligence.id

@description('Document Intelligence account name.')
output docIntelligenceName string = docIntelligence.name
