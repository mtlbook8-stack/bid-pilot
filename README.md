# BidPilot

Construction bid management platform for general contractors. BidPilot ingests
bids from email, runs them through an AI processing pipeline, and — the core of
the product — lets users **compare bids interactively** through a multi-agent
chat system.

> Built to the specification in [`BIDPILOT_BUILD_INSTRUCTIONS.md`](./BIDPILOT_BUILD_INSTRUCTIONS.md).

## What it does

1. **Setup (once):** link an email account via Microsoft OAuth.
2. **Automatic:** bids arrive by email → parsed → validated → matched to a
   project → categorized by trade.
3. **Daily glance:** a dashboard shows new bids, project status, and what needs
   attention.
4. **The real work:** open a job → **Compare** → an interactive session where AI
   agents normalize units, compare costs, analyze non-cost features, answer
   questions, and help decide which vendor to pick.
5. **Learning:** user corrections are distilled into rules that improve agent
   accuracy over time.

## Architecture

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.12 + FastAPI (Azure Container Apps) |
| Background workers | Azure Functions v2 (Python, Flex Consumption) |
| Frontend | React 18 + TypeScript + Vite + Tailwind + shadcn/ui |
| Database | Azure Cosmos DB (NoSQL) |
| File storage | Azure Blob Storage |
| AI models | Azure AI Foundry — Claude Sonnet 4.6 (agents) + GPT-5 (router) |
| Document parsing | Azure Document Intelligence (`prebuilt-layout`) |
| Email | Microsoft Graph API |
| Auth | Microsoft Entra ID |
| Geocoding | Azure Maps (address normalization) |
| Secrets | Azure Key Vault (managed identity) |
| Telemetry | Application Insights + OpenTelemetry (incl. per-call token cost) |
| IaC | Bicep |

### Source layout

```
src/
  core/            Domain library — models, enums, errors, interface Protocols
  agents/          The 13 AI agents (BaseAgent + pipeline/comparison/learning/insights)
  infrastructure/  External-service implementations (Cosmos, AI, email, docs, ...)
  orchestration/   Business-logic orchestrators (ingestion, processing, comparison)
  api/             FastAPI app — routers, services, middleware, composition root
  functions/       Azure Functions triggers
  devtools/        Seed + debug CLI scripts
frontend/          React SPA
infra/             Bicep IaC (modules + parameters)
data/seed/         Seed data — all 13 agent prompts
tests/             Unit + integration tests
```

### The 13 agents

Pipeline: **QuoteValidator** → **ProjectMatcher** → **JobCategorizer**.
Comparison: **ComparisonOrchestrator** (GPT-5 router) routes chat to
**UnitNormalizer**, **CostComparator** (generates sandboxed Python),
**FeatureAnalyst**, **ContextCompactor**, **DataQueryAgent** (two-phase, sandboxed).
Learning: **CorrectionDistiller**. Insights: **SessionSummarizer**,
**DashboardAnalyst**, **DecisionExplainer**.

Each agent's model + prompt is a versioned document in Cosmos, so models and
prompts can be swapped with **no code change** (set a new version active).

## Design principles

The codebase follows nine non-negotiable rules from the build doc: full OOP, one
job per class, constructor dependency injection (composition happens only in
`src/api/main.py`), one class per file, zero duplicated logic, full commenting,
zero silent failures, a single error-chain architecture (`AppError` — errors
throw up, logging happens once at the top), and production-grade code throughout.

### Storage schema casing

Cosmos documents are **camelCase** (matching the container partition-key paths
like `/projectId`, `/agentName`, and the build doc's document schemas). All
domain models inherit `CamelModel`, which serializes camelCase but still accepts
snake_case on input — so Python code stays idiomatic while the persisted shape
matches the infrastructure exactly.

## Development

### Backend

```bash
pip install -r requirements.txt

# Configure env (BIDPILOT_-prefixed; resolved from Key Vault in the cloud)
cp .env.example .env   # then fill in endpoints

# Seed the 13 agent prompts and some sample data
python -m src.devtools.seed_prompts
python -m src.devtools.seed_test_data

# Run the API
uvicorn src.api.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api → :8000
```

### Tests

```bash
python -m pytest tests/unit -q
```

The unit suite is dependency-light (pure domain logic: error chaining, JSON
parsing, enums, model serialization, the sandbox) and runs offline.

## Deployment

```bash
az deployment group create \
  --resource-group <rg> \
  --template-file infra/main.bicep \
  --parameters infra/parameters/dev.bicepparam
```

Provisions Cosmos (all containers), Storage, Key Vault, AI Foundry + model
deployments, Document Intelligence, Azure Maps, the Container App (API), the
Function App (workers), and all managed-identity RBAC assignments.
