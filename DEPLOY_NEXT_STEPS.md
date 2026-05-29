# BidPilot deploy — resume state (2026-05-29)

## Azure context
- Sub: `adb4580f-cc0e-42ed-9d39-d06a49f81b9a`
- Tenant: `c40c1d20-61e0-4cb1-8e3e-a2d533cdd8ed` (anyexcel)
- RG: `rg-bidpilot` in `eastus2`

## Already deployed in Azure (persists across machines)
- AI Foundry: `bidpilot-dev-ai-7gjss5` with `gpt-5` deployment (Claude NOT deployed)
- Cosmos: `bidpilot-dev-cosmos-7gjss5` + 12 containers
- Key Vault: `bidpilot-dev-kv-7gjss5`
- Storage: `bidpilotdevst7gjss5`
- ACR: `bidpilotdevacr7gjss5` — has image `bidpilot-api:v1` (ch5 build succeeded)
- Doc Intel: `bidpilot-dev-docint-7gjss5`
- Maps: `bidpilot-dev-maps` (clientId `7a9cc3a0-a0ff-455d-bee6-e2d97ac2f3f7`)
- Log Analytics: `bidpilot-dev-log`; App Insights: `bidpilot-dev-appi`
- Container Apps Env: `bidpilot-dev-cae`
- Container App: `bidpilot-dev-api` — STILL ON HELLO-WORLD PLACEHOLDER
- Function App: `bidpilot-dev-func-7gjss5` + plan `bidpilot-dev-funcplan` — NO CODE DEPLOYED
- API URL: `https://bidpilot-dev-api.salmonriver-8c54ee03.eastus2.azurecontainerapps.io`

## Already pushed to GitHub `mtlbook8-stack/bid-pilot` main
- Working Dockerfile (Azure Linux Python 3.12, builds clean)
- All Bicep with fixes (Maps role GUID `bfa`, conditional ACR registries)
- .github/workflows/{ci,deploy}.yml

## Next steps — USE AZURE CLOUD SHELL (https://shell.azure.com, Bash)
No git/local terminal needed. From Cloud Shell:

```bash
# 1. Wire ACR auth (failed locally due to corp SSL)
az containerapp registry set -n bidpilot-dev-api -g rg-bidpilot \
  --server bidpilotdevacr7gjss5.azurecr.io --identity system

# 2. Roll Container App to the real image
az containerapp update -n bidpilot-dev-api -g rg-bidpilot \
  --image bidpilotdevacr7gjss5.azurecr.io/bidpilot-api:v1

# 3. Verify
curl https://bidpilot-dev-api.salmonriver-8c54ee03.eastus2.azurecontainerapps.io/health

# 4. Add Claude (was dropped from Bicep; needs Anthropic onboarding metadata)
# Try CLI first; if it fails with InvalidModelProviderData, use AI Foundry portal
# (portal prompts for industry/orgName/countryCode interactively).
az cognitiveservices account deployment create \
  -n bidpilot-dev-ai-7gjss5 -g rg-bidpilot \
  --deployment-name claude-sonnet-4-6 \
  --model-name claude-sonnet-4-6 --model-version 1 \
  --model-format Anthropic \
  --sku-name GlobalStandard --sku-capacity 50

# 5. Deploy Function App code
git clone https://github.com/mtlbook8-stack/bid-pilot.git
cd bid-pilot/src/functions
zip -r /tmp/funcapp.zip .
az functionapp deployment source config-zip \
  -g rg-bidpilot -n bidpilot-dev-func-7gjss5 --src /tmp/funcapp.zip
```

## Still pending (manual)
- Create single multi-tenant Entra app reg in anyexcel portal
  - SPA redirect: http://localhost:5173, http://localhost:5173/, prod URL
  - Web redirect: http://localhost:8000/api/auth/callback, prod /api/auth/callback
  - Graph delegated: User.Read, Mail.Read, MailboxSettings.Read, offline_access, openid, profile, email
  - Expose API: `api://<client-id>` scope `access_as_user`, pre-authorize same client
  - Manifest: `api.requestedAccessTokenVersion: 2`
  - Then: store secret in Key Vault, set tenant ID = `common` for multi-tenant authority

## Frontend
- Not deployed. Plan: `npm run build` in `frontend/` then upload to Static Web Apps
  or serve from Container App. Need to decide.

## Known fixes already applied (don't redo)
- Maps Data Reader role GUID: `423170ca-a8f6-4b0f-8487-9e4eb8f49bfa` (was `bfc`)
- Container App registries[] only attached when image is from our ACR
- entraTenantId default = real anyexcel tenant in dev.bicepparam
- Claude dropped from Bicep (Anthropic onboarding metadata blocked initial deploy)
- Dockerfile base: `mcr.microsoft.com/azurelinux/base/python:3.12` (Docker Hub rate limit workaround)
- Uses `python3` + tdnf + shadow-utils

## Corp network gotcha (this machine only)
- `az acr build` source upload fails with SSL cert verify (corporate inspection)
- `az containerapp registry set` / `az acr repository show-tags` fail same way
- ARM/control-plane calls work fine. Workaround was building from GitHub remote.
- On non-corp network or Cloud Shell: no workarounds needed.
