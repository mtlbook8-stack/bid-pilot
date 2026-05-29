// cosmos.bicep
// Cosmos DB for NoSQL (GlobalDocumentDB) account with Session consistency, a
// single database (bidpilotdb), and all 12 application containers with their
// partition keys per BIDPILOT_BUILD_INSTRUCTIONS section 6.1.
//
// Throughput model: shared (database-level) autoscale. At BidPilot's scale
// (hundreds to low thousands of bids) one shared autoscale bucket across all
// containers is far cheaper than provisioning each container separately, and it
// absorbs the cross-partition queries described in section 6.2.
//
// Data-plane access is via Cosmos SQL RBAC (managed identity), not keys — so we
// disable local (key) auth at the account level. The SQL role assignment that
// grants the apps data access lives in roles.bicep.

@description('Azure region for the Cosmos account.')
param location string

@description('Globally unique Cosmos account name (3-44 lowercase chars).')
param cosmosAccountName string

@description('Name of the SQL database.')
param databaseName string = 'bidpilotdb'

@description('Max RU/s for the shared autoscale throughput bucket.')
param maxThroughput int = 1000

@description('Tags applied to every resource in this module.')
param tags object = {}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: cosmosAccountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    // Session consistency is the recommended default for single-region OLTP
    // workloads — read-your-writes within a session, low latency.
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    // Force Entra ID / RBAC data-plane auth; no connection-string keys at runtime.
    disableLocalAuth: true
    enableAutomaticFailover: false
    minimalTlsVersion: 'Tls12'
    capabilities: []
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmosAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    // Shared autoscale throughput at the database level — all containers below
    // draw from this bucket unless they declare their own (none do).
    options: {
      autoscaleSettings: {
        maxThroughput: maxThroughput
      }
    }
  }
}

// Container definitions: name + partition key path, sourced from section 6.1.
// The `leases` container has no documented partition key; the change-feed
// processor library requires /id, so we use that.
var containers = [
  { name: 'bids', partitionKey: '/id' }
  { name: 'projects', partitionKey: '/id' }
  { name: 'jobs', partitionKey: '/projectId' }
  { name: 'linked-accounts', partitionKey: '/userId' }
  { name: 'prompts', partitionKey: '/agentName' }
  { name: 'learned-rules', partitionKey: '/agentName' }
  { name: 'corrections', partitionKey: '/bidId' }
  { name: 'rejected-emails', partitionKey: '/id' }
  { name: 'comparison-sessions', partitionKey: '/projectId' }
  { name: 'audit', partitionKey: '/entityType' }
  { name: 'error-logs', partitionKey: '/pipeline' }
  { name: 'leases', partitionKey: '/id' }
]

resource sqlContainers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [
  for c in containers: {
    parent: database
    name: c.name
    properties: {
      resource: {
        id: c.name
        partitionKey: {
          paths: [
            c.partitionKey
          ]
          kind: 'Hash'
          version: 2
        }
        // Default indexing policy indexes all paths — fine at this scale and
        // supports the cross-partition WHERE queries the app relies on.
        indexingPolicy: {
          indexingMode: 'consistent'
          automatic: true
          includedPaths: [
            {
              path: '/*'
            }
          ]
          excludedPaths: [
            {
              path: '/"_etag"/?'
            }
          ]
        }
      }
      // Containers inherit the database's shared autoscale throughput — no
      // per-container options block, so no dedicated RU/s is provisioned.
    }
  }
]

@description('Cosmos account document endpoint (https://acct.documents.azure.com:443/).')
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint

@description('Cosmos account name.')
output cosmosAccountName string = cosmosAccount.name

@description('Resource ID of the Cosmos account (used for SQL role assignment scope).')
output cosmosAccountId string = cosmosAccount.id

@description('SQL database name.')
output databaseName string = database.name
