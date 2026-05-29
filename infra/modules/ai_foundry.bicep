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

// --- Anthropic model provider data ---
// Azure requires these legal/onboarding fields when deploying partner Anthropic
// models (Claude). They are passed verbatim into modelProviderData on the
// Claude deployment resource. Defaults are placeholders — override via Bicep
// parameters in non-trivial environments.
@description('Legal organization name registered to consume Anthropic models on Azure.')
param anthropicOrganizationName string = 'BidPilot'

@description('Industry the deploying organization operates in (e.g. Technology, Construction, Financial Services).')
param anthropicIndustry string = 'Technology'

@description('ISO 3166-1 alpha-2 country code for the deploying organization (e.g. US, GB).')
@minLength(2)
@maxLength(2)
param anthropicCountryCode string = 'US'

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
// Claude Sonnet deployment intentionally omitted from this Bicep.
// Anthropic partner models require interactive onboarding (industry / orgName /
// countryCode) that the ARM control plane only honors via the AI Foundry portal
// or the AI Foundry SDK. After the infra deploy, add the Claude deployment via:
//   Portal: AI Foundry → this account → Models + endpoints → Deploy model → Claude Sonnet 4.6
// or:
//   az cognitiveservices account deployment create \
//     -n <aiAccountName> -g <rg> --deployment-name claude-sonnet-4-6 \
//     --model-name claude-sonnet-4-6 --model-version 1 --model-format Anthropic \
//     --sku-name GlobalStandard --sku-capacity 50
// (CLI succeeds for follow-up deployments once the account has been onboarded.)

// GPT-5 deployment. Standard OpenAI-format deployment.
resource gptDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: gptDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: 30
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5'
      version: '2025-08-07'
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
