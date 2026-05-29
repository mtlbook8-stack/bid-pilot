// maps.bicep
// Azure Maps account, used for address normalization (geocoding), not routing.
// Apps authenticate with managed identity + Azure Maps Data Reader RBAC
// (roles.bicep). The unique principal/account id (the "x-ms-client-id" the Maps
// SDK needs alongside an Entra token) is surfaced as the uniqueId output and
// wired into the apps as BIDPILOT_AZURE_MAPS_CLIENT_ID.

@description('Azure region for the Maps account. Maps accounts are typically created in "global".')
param location string = 'global'

@description('Azure Maps account name.')
param mapsAccountName string

@description('SKU for the Maps account (G2 = gen2 pay-as-you-go).')
@allowed([
  'G2'
  'S1'
])
param skuName string = 'G2'

@description('Tags applied to every resource in this module.')
param tags object = {}

resource maps 'Microsoft.Maps/accounts@2023-06-01' = {
  name: mapsAccountName
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  kind: 'Gen2'
  properties: {
    // Disable shared-key auth — the apps use Entra token + client id instead.
    disableLocalAuth: true
  }
}

@description('The Maps account client id (x-ms-client-id) used with Entra token auth.')
output mapsClientId string = maps.properties.uniqueId

@description('Resource ID of the Maps account (used for RBAC scoping).')
output mapsAccountId string = maps.id

@description('Maps account name.')
output mapsAccountName string = maps.name
