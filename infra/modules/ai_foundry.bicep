// ai_foundry.bicep
// Azure AI Services account of kind 'AIServices' — this is the unified
// (Foundry) account that exposes both the Azure OpenAI surface and the
// model-inference / Foundry surface from a single resource and endpoint.
// We deploy two model deployments under it:
//   - a Claude Sonnet deployment (claude-sonnet-4-6)
//   - a GPT-5 deployment (gpt-5)
//
// Access is via managed identity + Cognitive Services User RBAC (roles.bicep);
// local key auth is disabled.

@description('Azure region for the AI Services account.')
param location string

@description('Globally unique AI Services account name.')
param aiServicesName string

@description('Custom subdomain — required for token-based (Entra) auth. Defaults to the account name.')
param customSubDomainName string = aiServicesName

@description('Tags applied to every resource in this module.')
param tags object = {}

@description('Claude model deployment name as referenced by prompt configs.')
param claudeDeploymentName string = 'claude-sonnet-4-6'

@description('GPT model deployment name as referenced by prompt configs.')
param gptDeploymentName string = 'gpt-5'

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiServicesName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    // S0 is the standard pay-as-you-go tier for AIServices accounts.
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    // Custom subdomain is mandatory for Entra ID / managed-identity auth.
    customSubDomainName: customSubDomainName
    // Force token-based auth; the apps authenticate with managed identity.
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

// Claude Sonnet deployment.
// NOTE: The exact model "format"/version for partner (Anthropic) models served
// through Azure AI Foundry varies by region and onboarding. We use the
// model name from the doc with publisher format 'Anthropic'. Adjust
// `format`/`version` to match what `az cognitiveservices account list-models`
// returns for the target region if deployment fails.
resource claudeDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: claudeDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: 1
  }
  properties: {
    model: {
      format: 'Anthropic'
      name: 'claude-sonnet-4-6'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// GPT-5 deployment. Standard OpenAI-format deployment. Deploy serially after the
// Claude one — the control plane rejects concurrent deployment writes on a single
// account.
resource gptDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: gptDeploymentName
  dependsOn: [
    claudeDeployment
  ]
  sku: {
    name: 'GlobalStandard'
    capacity: 1
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

@description('AI Services / Foundry account endpoint.')
output aiFoundryEndpoint string = aiServices.properties.endpoint

@description('Azure OpenAI-compatible endpoint surfaced by the same account.')
output aiFoundryOpenAiEndpoint string = 'https://${customSubDomainName}.openai.azure.com/'

@description('Resource ID of the AI Services account (used for RBAC scoping).')
output aiServicesId string = aiServices.id

@description('AI Services account name.')
output aiServicesName string = aiServices.name
