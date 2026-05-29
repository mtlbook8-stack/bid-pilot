// monitoring.bicep
// Deploys a Log Analytics Workspace and a workspace-based Application Insights
// component. Workspace-based App Insights is the only non-deprecated mode — the
// classic (non-workspace) mode has been retired by Azure, so we always link the
// component to the workspace via WorkspaceResourceId.

@description('Azure region for the monitoring resources.')
param location string

@description('Name of the Log Analytics workspace.')
param workspaceName string

@description('Name of the Application Insights component.')
param appInsightsName string

@description('Tags applied to every resource in this module.')
param tags object = {}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    // PerGB2018 is the current commitment-free pay-as-you-go tier.
    sku: {
      name: 'PerGB2018'
    }
    // 30 days is the free-tier default retention; raise per environment if needed.
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    // Link to the workspace — required for workspace-based App Insights.
    WorkspaceResourceId: workspace.id
    // Ingest telemetry over the public endpoint; tighten with Private Link later.
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

@description('Application Insights connection string (preferred over instrumentation key).')
output appInsightsConnectionString string = appInsights.properties.ConnectionString

@description('Application Insights instrumentation key (legacy SDKs).')
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey

@description('Resource ID of the Log Analytics workspace (used by Container Apps env).')
output workspaceId string = workspace.id

@description('Customer ID (GUID) of the Log Analytics workspace.')
output workspaceCustomerId string = workspace.properties.customerId

@description('Resource ID of the Application Insights component.')
output appInsightsId string = appInsights.id
