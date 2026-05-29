# BidPilot — Complete Build Instructions for Claude Code

> **Generated:** May 29, 2026
> **Purpose:** Single-source build document. Every architecture decision is resolved. Every agent prompt is finalized. Every coding standard is defined. Follow this document exactly.

---

## 1. What BidPilot Is

BidPilot is a construction bid management platform for general contractors. It ingests bids from email, processes them through an AI pipeline, and — most importantly — lets users **compare bids interactively** through a multi-agent chat system.

The comparison system is the core product. The ingestion pipeline is plumbing that feeds it. Build priority and polish should reflect this: comparison UX matters most.

### User Workflow

1. **Setup (once):** Link email account via Microsoft OAuth
2. **Automatic:** Bids arrive by email → parsed → validated → matched to project → categorized by trade
3. **Daily glance:** Dashboard shows new bids, project status, what needs attention
4. **The real work (core product):** Open a job → click "Compare" → interactive session with AI agents normalizing units, comparing costs, analyzing features, answering questions, helping the user decide which vendor to pick
5. **Learning:** User corrections feed back into agent prompts, improving accuracy over time

---

## 2. Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| **Backend API** | Python 3.12 + FastAPI | Async-first, runs on Azure Container Apps |
| **Background Workers** | Azure Functions v2 (Python) | Triggers only: timers, change feed, HTTP |
| **Frontend** | React 18 + TypeScript + Vite | Tailwind CSS + shadcn/ui components |
| **Database** | Azure Cosmos DB (NoSQL) | `/id` partition key on bids container |
| **File Storage** | Azure Blob Storage | Original bid PDFs |
| **AI Models** | Azure AI Foundry | Claude Sonnet 4.6 (all Claude agents) + GPT-5 (router) |
| **Document Parsing** | Azure Document Intelligence | `prebuilt-layout` model |
| **Email** | Microsoft Graph API | OAuth 2.0 with refresh tokens |
| **Auth** | Microsoft Entra ID | SSO with Azure |
| **Geocoding** | Azure Maps | Address normalization (not distance) |
| **Secrets** | Azure Key Vault | Managed identity access |
| **Monitoring** | Application Insights + OpenTelemetry | Full telemetry including token costs |
| **IaC** | Bicep | All resources including Doc Intelligence |
| **Deployment** | Azure Container Apps (API) + Azure Functions Flex Consumption (workers) | |

---

## 3. Project Structure

```
bidpilot/
├── .devcontainer/
│   ├── devcontainer.json
│   └── Dockerfile
├── src/
│   ├── api/                          # FastAPI application
│   │   ├── main.py                   # Composition root — all DI wired here
│   │   ├── config.py                 # Settings loaded from env/Key Vault
│   │   ├── dependencies.py           # FastAPI dependency injection providers
│   │   ├── middleware/
│   │   │   ├── error_handler.py      # Global exception handler (Rule 8 top-level)
│   │   │   ├── auth.py               # Entra ID JWT validation
│   │   │   └── telemetry.py          # Request/response OpenTelemetry middleware
│   │   ├── routers/
│   │   │   ├── auth_router.py        # /api/auth — email linking, OAuth callback
│   │   │   ├── bids_router.py        # /api/bids — list, detail, PDF proxy
│   │   │   ├── projects_router.py    # /api/projects — list, jobs
│   │   │   ├── comparison_router.py  # /api/comparison — start, sessions, chat (SSE)
│   │   │   ├── corrections_router.py # /api/corrections — project, trade, validation
│   │   │   ├── email_accounts_router.py # /api/email-accounts — list, unlink, poll
│   │   │   ├── rejected_router.py    # /api/rejected — list, restore
│   │   │   └── stats_router.py       # /api/stats — dashboard data
│   │   └── services/
│   │       ├── comparison_service.py  # Orchestrates comparison pipeline + chat
│   │       ├── correction_service.py  # Handles corrections + triggers distiller
│   │       ├── manual_poll_service.py # Triggers Azure Function + SSE progress
│   │       ├── pdf_proxy_service.py   # Streams PDF from Blob to browser
│   │       └── dashboard_service.py   # Aggregates stats for dashboard
│   ├── core/                         # Shared domain library (no framework deps)
│   │   ├── models/
│   │   │   ├── bid.py                # IngestedBid dataclass
│   │   │   ├── project.py            # ProjectSummary dataclass
│   │   │   ├── job.py                # JobSummary dataclass
│   │   │   ├── comparison.py         # ComparisonSession, ComparisonTable, etc.
│   │   │   ├── correction.py         # Correction, LearnedRule dataclasses
│   │   │   ├── prompt.py             # PromptTemplate with ModelConfig
│   │   │   ├── linked_account.py     # LinkedAccount dataclass
│   │   │   ├── rejected_email.py     # RejectedEmailMetadata (lightweight)
│   │   │   └── parsed_document.py    # ParsedDocument, ParsedPage, ParsedTable
│   │   ├── errors/
│   │   │   └── app_error.py          # Custom error class with chaining (Rule 8)
│   │   ├── interfaces/
│   │   │   ├── bid_store.py          # IBidStore protocol
│   │   │   ├── project_store.py      # IProjectStore protocol
│   │   │   ├── job_store.py          # IJobStore protocol
│   │   │   ├── prompt_store.py       # IPromptStore protocol
│   │   │   ├── rule_store.py         # IRuleStore protocol
│   │   │   ├── correction_store.py   # ICorrectionStore protocol
│   │   │   ├── rejected_store.py     # IRejectedEmailStore protocol
│   │   │   ├── session_store.py      # IComparisonSessionStore protocol
│   │   │   ├── foundry_client.py     # IFoundryClient protocol
│   │   │   ├── geocoding_service.py  # IGeocodingService protocol
│   │   │   └── graph_client.py       # IGraphMailClient protocol
│   │   └── enums.py                  # BidStatus, TradeCategory, CorrectionType, etc.
│   ├── agents/                       # AI agent implementations
│   │   ├── base_agent.py             # BaseAgent — prompt loading, rule injection, response parsing
│   │   ├── response_parser.py        # JSON extraction from LLM responses
│   │   ├── pipeline/
│   │   │   ├── quote_validator.py    # Agent 1
│   │   │   ├── project_matcher.py    # Agent 2
│   │   │   └── job_categorizer.py    # Agent 3
│   │   ├── comparison/
│   │   │   ├── comparison_orchestrator.py  # Routes chat to sub-agents (GPT-5)
│   │   │   ├── unit_normalizer.py          # Agent 5
│   │   │   ├── cost_comparator.py          # Agent 6 (generates Python)
│   │   │   ├── feature_analyst.py          # Agent 7
│   │   │   ├── context_compactor.py        # Agent 8
│   │   │   └── data_query_agent.py         # Agent 9 (two-phase)
│   │   ├── learning/
│   │   │   └── correction_distiller.py     # Agent 10
│   │   └── insights/
│   │       ├── session_summarizer.py       # Agent 11
│   │       ├── dashboard_analyst.py        # Agent 12
│   │       └── decision_explainer.py       # Agent 13
│   ├── infrastructure/               # External service implementations
│   │   ├── cosmos/
│   │   │   ├── cosmos_client_factory.py   # Singleton CosmosClient setup
│   │   │   ├── bid_store.py               # IBidStore → Cosmos
│   │   │   ├── project_store.py           # IProjectStore → Cosmos
│   │   │   ├── job_store.py               # IJobStore → Cosmos
│   │   │   ├── prompt_store.py            # IPromptStore → Cosmos
│   │   │   ├── rule_store.py              # IRuleStore → Cosmos
│   │   │   ├── correction_store.py        # ICorrectionStore → Cosmos
│   │   │   ├── rejected_store.py          # IRejectedEmailStore → Cosmos
│   │   │   └── session_store.py           # IComparisonSessionStore → Cosmos
│   │   ├── ai/
│   │   │   ├── foundry_client.py          # Anthropic Messages API via Foundry
│   │   │   ├── openai_foundry_client.py   # OpenAI Chat API via Foundry
│   │   │   └── foundry_client_router.py   # Routes claude-* vs gpt-* models
│   │   ├── email/
│   │   │   ├── graph_mail_client.py       # Microsoft Graph email fetch
│   │   │   ├── token_manager.py           # OAuth token refresh via MSAL
│   │   │   └── webhook_manager.py         # Graph webhook subscription lifecycle
│   │   ├── documents/
│   │   │   ├── document_parser.py         # Azure Doc Intelligence wrapper
│   │   │   └── email_filter.py            # Code-only keyword filter (no AI)
│   │   ├── geocoding/
│   │   │   └── azure_maps_service.py      # IGeocodingService → Azure Maps
│   │   ├── storage/
│   │   │   └── blob_service.py            # Azure Blob Storage wrapper
│   │   ├── sandbox/
│   │   │   └── python_sandbox.py          # Subprocess execution with timeout
│   │   └── telemetry/
│   │       └── otel_service.py            # OpenTelemetry + App Insights setup
│   ├── orchestration/                # Business logic orchestrators
│   │   ├── email_ingestion_orchestrator.py  # Full email → bid pipeline
│   │   ├── bid_processing_orchestrator.py   # 3-agent checkpoint pipeline
│   │   └── comparison_pipeline.py           # UnitNorm → Cost → Feature → Table
│   ├── functions/                    # Azure Functions (triggers only)
│   │   ├── function_app.py           # Azure Functions v2 app entry
│   │   ├── bid_processing_trigger.py # Cosmos change feed → process bid
│   │   ├── bid_retry_trigger.py      # Timer (15 min) → retry failed bids
│   │   ├── email_polling_trigger.py  # Timer (30 min) → poll all accounts
│   │   ├── webhook_notification.py   # HTTP POST → Graph webhook receiver
│   │   ├── webhook_renewal_trigger.py # Timer (12 hr) → renew subscriptions
│   │   ├── manual_poll_trigger.py    # HTTP POST → user-triggered poll
│   │   ├── model_health_check.py     # Timer (weekly) → ping all model endpoints
│   │   └── connectivity_check.py     # Timer (daily) → health probe email accounts
│   └── devtools/
│       ├── seed_prompts.py           # Seeds ALL 13 agent prompts to Cosmos
│       ├── seed_test_data.py         # Seeds sample projects, jobs, bids
│       ├── list_bids.py              # Debug: list all bids
│       └── clear_db.py               # Debug: reset database
├── frontend/                         # React SPA
│   ├── src/
│   │   ├── main.tsx                  # Entry point
│   │   ├── App.tsx                   # Router + layout + auth provider
│   │   ├── api/
│   │   │   └── client.ts            # Typed API client (all endpoints)
│   │   ├── auth/
│   │   │   ├── AuthProvider.tsx      # Entra ID MSAL context
│   │   │   └── ProtectedRoute.tsx    # Route guard
│   │   ├── hooks/
│   │   │   ├── useSSE.ts            # Server-Sent Events hook
│   │   │   ├── useComparison.ts     # Comparison session state
│   │   │   └── usePollProgress.ts   # Manual poll progress tracking
│   │   ├── pages/
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── ProjectsPage.tsx
│   │   │   ├── ProjectDetailPage.tsx
│   │   │   ├── AllBidsPage.tsx
│   │   │   ├── BidDetailPage.tsx
│   │   │   ├── CompareSessionPage.tsx     # CORE PRODUCT — highest UX priority
│   │   │   ├── RejectedEmailsPage.tsx
│   │   │   └── EmailAccountsPage.tsx
│   │   ├── components/
│   │   │   ├── ui/                   # shadcn/ui components
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   ├── Header.tsx
│   │   │   │   └── PageShell.tsx
│   │   │   ├── bids/
│   │   │   │   ├── BidCard.tsx
│   │   │   │   ├── BidStatusBadge.tsx
│   │   │   │   └── AgentResultPanel.tsx
│   │   │   ├── comparison/
│   │   │   │   ├── ComparisonTable.tsx
│   │   │   │   ├── CostRow.tsx
│   │   │   │   ├── FeatureRow.tsx
│   │   │   │   ├── ChatPanel.tsx
│   │   │   │   ├── ChatMessage.tsx
│   │   │   │   └── SessionSummary.tsx
│   │   │   └── common/
│   │   │       ├── LoadingSkeleton.tsx
│   │   │       ├── EmptyState.tsx
│   │   │       ├── ErrorBoundary.tsx
│   │   │       └── ConfidenceBadge.tsx
│   │   ├── types/
│   │   │   └── index.ts              # All TypeScript types mirroring Python models
│   │   └── lib/
│   │       └── utils.ts              # shadcn/ui cn() utility
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   └── package.json
├── infra/                            # Bicep IaC
│   ├── main.bicep
│   ├── modules/
│   │   ├── monitoring.bicep          # Log Analytics + App Insights
│   │   ├── storage.bicep             # Storage Account + Blob containers
│   │   ├── keyvault.bicep            # Key Vault
│   │   ├── cosmos.bicep              # Cosmos DB + all containers
│   │   ├── ai_foundry.bicep          # AI Services + model deployments
│   │   ├── doc_intelligence.bicep    # Document Intelligence resource
│   │   ├── container_apps.bicep      # Container Apps Environment + API app
│   │   ├── functions.bicep           # Azure Functions (Python, Flex Consumption)
│   │   ├── maps.bicep                # Azure Maps account
│   │   └── roles.bicep               # RBAC assignments
│   └── parameters/
│       ├── dev.bicepparam
│       └── prod.bicepparam
├── data/
│   └── seed/
│       └── prompts.json              # All 13 agent prompt definitions
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── Dockerfile                        # API container image
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 4. Coding Standards

These rules are non-negotiable. Every file must comply before a phase is considered complete.

### Rule 1: Full OOP — Data and Functions Belong in Classes

Every piece of data and every function belongs to a class. No loose functions floating in files. No `helpers.py` with 40 exports.

- Use `dataclasses` or `Pydantic BaseModel` for data models. All models get type hints, validation in `__post_init__` or Pydantic validators, and methods that operate on their own data.
- Functions that act on data belong to the class that owns that data. If a function transforms a `Bid`, it's a method on `Bid`.
- Static methods are acceptable for factory patterns and pure operations.
- If a function doesn't belong to any data, it belongs to a service class that gets injected where needed.
- FastAPI router files are the only exception — route handler functions are acceptable there because that's the FastAPI convention. But all business logic in those handlers must delegate to an injected service class.

### Rule 2: Separation of Concerns — One Class, One Job

Each class does exactly one thing. If you need the word "and" to describe it, split it.

- **Models** (`core/models/`): Hold data, validate it, expose transform methods. Never fetch, render, or log.
- **Services** (`api/services/`, `orchestration/`): Execute business logic, orchestrate operations. Don't know about HTTP or databases directly.
- **Stores** (`infrastructure/cosmos/`): Handle storage. Return models, not raw responses.
- **Routers** (`api/routers/`): Receive HTTP input, call services, format output. Zero business logic.
- **Agents** (`agents/`): Single responsibility — take input, call LLM, return structured output.

### Rule 3: Dependency Injection — No Class Creates Its Own Dependencies

A class never instantiates the things it depends on. It receives them through the constructor.

```python
# WRONG
class BidProcessingOrchestrator:
    def __init__(self):
        self.validator = QuoteValidator()
        self.store = CosmosBidStore()

# RIGHT
class BidProcessingOrchestrator:
    def __init__(self, validator: IQuoteValidator, matcher: IProjectMatcher,
                 categorizer: IJobCategorizer, bid_store: IBidStore):
        self._validator = validator
        self._matcher = matcher
        self._categorizer = categorizer
        self._bid_store = bid_store
```

- `main.py` (composition root) is the ONLY place where classes are instantiated and wired together.
- Use FastAPI's `Depends()` system for route-level injection.
- Use Python `Protocol` classes for interfaces (in `core/interfaces/`).

### Rule 4: One File Per Class

Each class lives in its own file. The file is named after the class in `snake_case`.

- `bid_store.py` contains `class CosmosBidStore` and nothing else (except imports and private types).
- No file contains two public classes.
- Related types/enums can live in a shared file if they're small and tightly coupled.

### Rule 5: Absolute Reuse — No Duplicated Logic

If any logic appears more than once, extract it.

- Two identical API call patterns → extract to `BaseAgent`
- Two identical Cosmos queries → extract to a shared store method
- Two identical JSON parsing blocks → extract to `response_parser.py`

### Rule 6: Full Commenting — Everything Gets a Why

```python
class BidProcessingOrchestrator:
    """
    Drives a bid through the 3-agent pipeline: Validate → Match → Categorize.

    Uses a checkpoint pattern: each step saves an intermediate status to Cosmos
    BEFORE calling the agent, so a crash mid-agent resumes from the current step
    without re-running completed steps. The orchestrator is completely stateless —
    the Cosmos document is the only source of truth.
    """

    async def _run_project_matching(self, bid: IngestedBid) -> None:
        """
        Attempts address-based matching first (pure code, no LLM) using normalized
        addresses from Azure Maps. Only calls Agent 2 if no exact match is found.
        This saves ~$0.01 per bid that matches an existing project.
        """
```

- Class docstrings: what it does, why it exists, how it fits in the system.
- Method docstrings: what it accomplishes, non-obvious decisions.
- Inline comments: explain WHY, not WHAT. `# set x to 5` is noise. `# Cap at 3000 chars — Haiku's context is limited and first 3000 is enough for classification` is useful.

### Rule 7: Zero Silent Failures

Every external call is wrapped in try/except. Every except block either handles meaningfully or wraps with context and re-raises.

```python
# WRONG
try:
    result = await self._foundry.get_completion(system, user)
except Exception:
    pass  # silent failure

# RIGHT
try:
    result = await self._foundry.get_completion(system, user)
except Exception as e:
    raise AppError(
        code="AGENT_QUOTE_VALIDATOR",
        message="QuoteValidator LLM call failed",
        context={"bid_id": bid.id, "model": config.model_name},
        cause=e
    )
```

### Rule 8: Error Chain Architecture

Errors throw up, logs live at the top. One error = one log entry = one unique error code.

```python
class AppError(Exception):
    """
    Custom error with chaining, context, and user-safe messaging.
    Every error in the system inherits from or is wrapped by this class.
    """
    def __init__(self, code: str, message: str, context: dict | None = None,
                 cause: Exception | None = None):
        self.code = code
        self.message = message
        self.context = context or {}
        self.cause = cause
        self.error_id = self._generate_error_id()
        super().__init__(message)

    def _generate_error_id(self) -> str:
        """Short unique ID the user can report and the dev can search logs for."""
        return f"ERR-{uuid4().hex[:8].upper()}"

    def get_full_chain(self) -> list[dict]:
        """Walk the cause chain and collect all context for the log entry."""
        chain = [{"code": self.code, "message": self.message, "context": self.context}]
        current = self.cause
        while current:
            if isinstance(current, AppError):
                chain.append({"code": current.code, "message": current.message,
                              "context": current.context})
                current = current.cause
            else:
                chain.append({"code": "EXTERNAL", "message": str(current),
                              "type": type(current).__name__})
                break
        return chain

    @property
    def user_message(self) -> dict:
        """What the user sees — friendly message + error ID to report."""
        return {"message": "Something went wrong", "error_id": self.error_id}
```

The global exception handler in `middleware/error_handler.py` is the ONLY place that calls `logger.error()`. Everywhere else wraps and throws.

User NEVER sees stack traces, resource names, or technical details. They see: `{"message": "Bid processing failed", "error_id": "ERR-4F8A2B1C"}`.

### Rule 9: Production Grade Only

- No `print()` statements. Use `logging` module everywhere.
- No hardcoded URLs, keys, or secrets. Everything from config/env/Key Vault.
- No commented-out code. Git has history.
- No `# TODO` or `# HACK` or `# FIXME`. Fix it or don't ship it.
- No `if os.getenv("DEV")` blocks that change business logic.
- No `time.sleep()` to "fix" race conditions.
- Type hints on ALL public methods and constructors.

---

## 5. Cost Transparency & Telemetry (OpenTelemetry)

Every LLM call MUST be instrumented. This is not optional — it's how the user understands their costs and how you debug agent quality.

### 5.1 Telemetry Service

```python
class TelemetryService:
    """
    Wraps OpenTelemetry + Application Insights. Every LLM call, every agent run,
    every pipeline execution gets a trace with structured attributes.
    """

    def track_llm_call(self, agent_name: str, model: str, tokens_in: int,
                       tokens_out: int, duration_ms: float, bid_id: str | None = None,
                       session_id: str | None = None, project_id: str | None = None):
        """
        Logs a single LLM invocation with cost estimation.
        Called by BaseAgent after every Foundry call.
        """

    def track_pipeline_run(self, bid_id: str, status: str, duration_ms: float,
                            agents_called: list[str], total_tokens: int):
        """Logs a complete bid processing pipeline run."""

    def track_comparison_session(self, session_id: str, messages_count: int,
                                  agents_invoked: list[str], total_tokens: int):
        """Logs comparison session telemetry on session close/compact."""
```

### 5.2 What Gets Tracked (every LLM call)

| Field | Source | Purpose |
|-------|--------|---------|
| `agent_name` | Agent class name | Which agent ran |
| `model_used` | From prompt config | Which model was called |
| `tokens_in` | API response `usage.input_tokens` | Input cost |
| `tokens_out` | API response `usage.output_tokens` | Output cost |
| `duration_ms` | Wall clock | Latency monitoring |
| `cost_estimate_usd` | Computed from token counts + model pricing table | Dollar cost |
| `bid_id` | Pipeline context | Link to specific bid |
| `project_id` | Pipeline/session context | Link to project |
| `session_id` | Comparison context | Link to comparison session |
| `user_id` | Auth context | Per-user cost tracking |
| `success` | Boolean | Error rate per agent |
| `error_code` | AppError code if failed | Failure categorization |

### 5.3 Model Pricing Table

Store a pricing config in `data/model_pricing.json` (updated when models change):

```json
{
    "claude-sonnet-4-6": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    "claude-haiku-4-5": {"input_per_1k": 0.0008, "output_per_1k": 0.004},
    "gpt-5": {"input_per_1k": 0.005, "output_per_1k": 0.015}
}
```

Cost estimate formula: `(tokens_in / 1000 * input_rate) + (tokens_out / 1000 * output_rate)`

This is an estimate (actual Azure Foundry pricing may differ slightly) but gives 90%+ accuracy for cost awareness.

### 5.4 BaseAgent Integration

Every agent inherits from `BaseAgent` which handles telemetry automatically:

```python
class BaseAgent:
    """
    Base class for all AI agents. Handles prompt loading from Cosmos,
    learned rule injection, LLM invocation, response parsing, and telemetry.
    """

    async def _call_llm(self, system_prompt: str, user_message: str,
                        context: dict | None = None) -> dict:
        """
        Calls the LLM via Foundry and automatically tracks:
        - Token usage (in/out)
        - Latency
        - Cost estimate
        - Success/failure
        All via TelemetryService. No agent subclass needs to think about telemetry.
        """
```

---

## 6. Cosmos DB Schema

### 6.1 Containers

| Container | Partition Key | Content |
|-----------|--------------|---------|
| `bids` | `/id` | IngestedBid documents |
| `projects` | `/id` | ProjectSummary documents |
| `jobs` | `/projectId` | JobSummary documents |
| `linked-accounts` | `/userId` | LinkedAccount documents |
| `prompts` | `/agentName` | PromptTemplate + ModelConfig documents |
| `learned-rules` | `/agentName` | LearnedRule documents |
| `corrections` | `/bidId` | User correction records |
| `rejected-emails` | `/id` | Lightweight rejected email metadata |
| `comparison-sessions` | `/projectId` | ComparisonSession documents |
| `audit` | `/entityType` | Processing audit trail |
| `error-logs` | `/pipeline` | AppError records |
| `leases` | — | Change feed lease tracking |

### 6.2 Key Design: /id Partition Key for Bids

The `bids` container uses `/id` as partition key. This is deliberate.

- New bids arrive without a `matchedProjectId` (it's null until Agent 2 runs). Using `/matchedProjectId` as partition key would break Cosmos (null partition keys cause hot spots, and Cosmos can't move documents between partitions when the value changes).
- With `/id`, every read/update is a cheap O(1) point-read: `container.read_item(item=bid_id, partition_key=bid_id)`.
- Querying "all bids for project X" uses a `WHERE matchedProjectId = 'project-xyz'` cross-partition query. At this scale (hundreds to low thousands of bids, not millions), this costs a few extra RUs and maybe 10-50ms. Totally fine.
- The orchestrator is stateless. The Cosmos document IS the memory. The deterministic ID (`hash(messageId + filename)`) means you always know how to find a bid.

### 6.3 Prompt Document Schema (with Model Config)

```json
{
    "id": "QuoteValidator-v1",
    "agentName": "QuoteValidator",
    "version": 1,
    "isActive": true,
    "modelConfig": {
        "modelName": "claude-sonnet-4-6",
        "maxTokens": 500,
        "temperature": 0.1,
        "fallbackModel": "claude-sonnet-4-5"
    },
    "systemPromptTemplate": "...",
    "userMessageTemplate": "...",
    "createdAt": "2026-05-29T00:00:00Z",
    "updatedAt": "2026-05-29T00:00:00Z",
    "updatedBy": "seed"
}
```

To swap a model without code changes: create a new version document with the updated `modelConfig.modelName`, set `isActive: true` on the new one, `false` on the old. Rollback = flip flags.

The `fallbackModel` is used by `BaseAgent`: if the primary model returns a 404/deprecated/capacity error, retry once with the fallback.

### 6.4 Rejected Email Metadata Schema

Lightweight — only enough to display in a list and re-fetch from Graph on demand:

```json
{
    "id": "hash(messageId)",
    "messageId": "AAMkAG...",
    "linkedAccountId": "account-123",
    "senderEmail": "vendor@example.com",
    "subject": "RE: Quote for 123 Elm St",
    "receivedAt": "2026-05-28T14:30:00Z",
    "rejectionReason": "invoice_not_bid",
    "agentConfidence": 0.85,
    "createdAt": "2026-05-28T14:31:00Z"
}
```

No attachments stored, no document text. When user clicks "Restore", code calls Graph API to pull the full email + attachments, then re-ingests through the pipeline (skipping Agent 1).

---

## 7. Agent Prompts — Complete Reference

### Model Configuration

ALL Claude agents start on `claude-sonnet-4-6`. The Cosmos config system allows no-code changes.

| Agent | Starting Model | Fallback | Notes |
|-------|---------------|----------|-------|
| QuoteValidator | `claude-sonnet-4-6` | `claude-sonnet-4-5` | Can downgrade to Haiku later if overkill |
| ProjectMatcher | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |
| JobCategorizer | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |
| ComparisonOrchestrator | `gpt-5` | `gpt-4.1-mini` | Only non-Claude agent (router) |
| UnitNormalizer | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |
| CostComparator | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |
| FeatureAnalyst | `claude-sonnet-4-6` | `claude-sonnet-4-5` | Can upgrade to Opus if quality lacking |
| ContextCompactor | `claude-sonnet-4-6` | `claude-sonnet-4-5` | Can downgrade to Haiku if overkill |
| DataQueryAgent | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |
| CorrectionDistiller | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |
| SessionSummarizer | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |
| DashboardAnalyst | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |
| DecisionExplainer | `claude-sonnet-4-6` | `claude-sonnet-4-5` | |

---

### AGENT 1 — QuoteValidator

**Purpose:** Binary classification — "Is this a construction bid?"
**Temperature:** 0.1 | **Max tokens:** 500

**System Prompt:**

```
You are a construction bid classifier for a general contractor. Your only job is to determine whether a document is a construction bid, quote, estimate, or proposal.

CLASSIFY AS A BID (is_bid = true):
- Subcontractor quotes with pricing for labor/materials
- Proposals with scope of work and dollar amounts
- Estimates or cost breakdowns for construction trades
- Change order pricing documents
- Unit price schedules for construction work

CLASSIFY AS NOT A BID (is_bid = false):
- Invoices for completed work (past tense, "amount due")
- Purchase orders or material delivery receipts
- Meeting minutes, RFIs, submittals without pricing
- Marketing materials, newsletters, company brochures
- Insurance certificates, bonds, safety documents
- Personal or unrelated emails that slipped through filters

CONFIDENCE GUIDE:
- 0.9-1.0: Clear bid/quote with explicit pricing and scope
- 0.7-0.89: Likely a bid but missing some typical elements
- 0.5-0.69: Ambiguous — could go either way
- Below 0.5: Likely not a bid

When confidence is between 0.5-0.69, lean toward is_bid = true. It's better to let a borderline document through for human review than to reject a real bid.

{learned_rules}

Respond with ONLY valid JSON, no other text:
{
  "is_bid": boolean,
  "confidence": number,
  "document_type": "bid" | "invoice" | "submittal" | "rfi" | "marketing" | "insurance" | "other",
  "rejection_category": "not_construction" | "invoice_not_bid" | "informational_only" | "duplicate" | null,
  "reasoning": "one sentence explaining your decision"
}
```

**User Message Template:**

```
Classify this document:

SENDER: {sender_email}
SUBJECT: {email_subject}
FILENAME: {attachment_file_name}
TABLES FOUND: {table_count}
TABLE HEADERS: {table_headers_summary}

DOCUMENT TEXT (first 3000 chars):
{document_text}
```

**Pipeline Actions:**
- `is_bid = true` → status = `Validated`, continue to geocoding + Agent 2
- `is_bid = false` → save lightweight metadata to `rejected-emails` container (subject, date, sender, messageId, rejection_category, confidence). Do NOT save attachment or document text.

---

### AGENT 2 — ProjectMatcher

**Purpose:** Match bid to existing project or create new one. Only called when address-based matching fails.
**Temperature:** 0.1 | **Max tokens:** 1000

**Pre-Agent Code Step (runs before Agent 2):**
1. Extract address hint from document text (regex/heuristic for common address patterns)
2. Geocode via Azure Maps → normalized canonical address
3. Compare normalized address against all existing projects' `normalizedAddress` field
4. IF exact match found → assign project, skip Agent 2 entirely, go to Agent 3
5. ELSE → call Agent 2 with full context
6. When Agent 2 returns `match_type = "new"` → geocode the new project's address too → store `normalizedAddress` on the new project to prevent future duplicates

**System Prompt:**

```
You are a project matching agent for a general contractor. You are called when a construction bid could not be automatically matched to an existing project by address alone. Your job is to use contextual clues to find the right match or confirm this is a genuinely new project.

The bid's address has already been geocoded and did not exactly match any existing project address. However, the match may still exist under a different name, a slightly different address, or a related phase.

MATCHING STRATEGY:
1. PARTIAL ADDRESS: "Building 4, Riverside" might match a project at "Riverside Development, 500 River Rd" — look for shared location names, neighborhoods, or landmarks.
2. CLIENT/OWNER: The bid may reference the property owner, developer, or GC project name that matches an existing project's client.
3. PROJECT REFERENCES: PO numbers, project numbers, "re: Phase 2", prior correspondence references.
4. TRADE CONTEXT: If the bid is for "HVAC at Springfield Medical" and a project exists called "Springfield Medical Center Expansion", that's a match.

MATCH TYPES:
- "existing": You found a match. Set project_id.
- "new": No existing project matches after considering all clues. Provide new_project details.

When uncertain, prefer "new" over a forced match. A wrong match is worse than a new project that gets merged later.

When creating a new project:
- name: Most descriptive identifier (address, client + location, or project reference)
- address: Best address found in the bid, even if partial
- client_name: Property owner or developer if mentioned
- client_contact: Contact info if found

{learned_rules}

Respond with ONLY valid JSON, no other text:
{
  "match_type": "existing" | "new",
  "project_id": string | null,
  "confidence": number,
  "address_from_bid": string,
  "reasoning": string,
  "new_project": {
    "name": string,
    "address": string,
    "client_name": string | null,
    "client_contact": string | null
  } | null
}
```

**User Message Template:**

```
Match this bid to a project. Address-based matching already failed.

NORMALIZED ADDRESS FROM BID: {normalized_address}
GEOCODING STATUS: {geocode_status}

EXISTING PROJECTS:
{existing_projects_json}

BID DETAILS:
SENDER: {sender_email}
SUBJECT: {email_subject}
FILENAME: {attachment_file_name}

DOCUMENT TEXT (first 5000 chars):
{document_text}
```

---

### AGENT 3 — JobCategorizer

**Purpose:** Determine trade category, match to existing or new job, extract vendor, summarize scope.
**Temperature:** 0.1 | **Max tokens:** 800

**System Prompt:**

```
You are a construction trade classifier for a general contractor. Given a bid that has been matched to a project, determine the trade category, match to an existing job or create a new one, extract the vendor name, and summarize the scope.

TRADE CATEGORIES (use these exact values):
Sitework, Concrete, Masonry, Metals/Steel, Carpentry, Thermal/Moisture Protection, Roofing, Doors/Windows/Glazing, Finishes, Drywall, Flooring, Painting, Specialties, Equipment, Furnishings, Plumbing, HVAC, Electrical, Fire Protection, Elevator, Demolition, Earthwork, Utilities, Landscaping, General Conditions, Other

If the bid clearly spans multiple trades, pick the PRIMARY trade for trade_category and list others in secondary_trades. Example: a mechanical bid covering HVAC + plumbing → trade_category: "HVAC", secondary_trades: ["Plumbing"].

JOB MATCHING:
A "job" represents a specific trade scope on a project. Multiple bids for the same trade on the same project compete on the same job.
- If existing_jobs contains a job with matching trade_category → is_new_job: false, set existing_job_id
- If no matching job exists → is_new_job: true
- When matching, consider: the same trade might be listed under a slightly different name. "Plumbing Rough-In" and "Plumbing" are the same job. "Electrical" and "Low Voltage/Data" are NOT the same job.

VENDOR NAME:
Extract the company name from the DOCUMENT CONTENT, not the email sender. Look for:
- Letterhead, logo text, or header on the first page
- "Prepared by", "Submitted by", "From:" fields in the document
- Company name near the signature block
- If truly not found in the document, fall back to email sender domain name

SCOPE SUMMARY:
Write 1-2 sentences describing what the bid covers. Be specific: "Supply and install 47 light fixtures across floors 2-4, including emergency lighting" not "Electrical work".

{learned_rules}

Respond with ONLY valid JSON, no other text:
{
  "trade_category": string,
  "secondary_trades": string[],
  "is_new_job": boolean,
  "existing_job_id": string | null,
  "confidence": number,
  "reasoning": string,
  "scope_summary": string,
  "vendor_name": string
}
```

**User Message Template:**

```
Categorize this bid:

PROJECT: {project_name}
PROJECT ADDRESS: {project_address}

EXISTING JOBS FOR THIS PROJECT:
{existing_jobs_json}

BID DETAILS:
SENDER: {sender_email}
SUBJECT: {email_subject}
FILENAME: {attachment_file_name}

DOCUMENT TEXT (first 6000 chars):
{document_text}
```

---

### AGENT 4 — ComparisonOrchestrator

**Purpose:** Classify user intent and route to the correct sub-agent. Does NOT do analysis.
**Model:** `gpt-5` (only non-Claude agent)
**Temperature:** 0.3 | **Max tokens:** 300

**System Prompt:**

```
You are a conversation router for a construction bid comparison system. Your ONLY job is to classify the user's message intent and decide which specialist agent should handle it.

AVAILABLE AGENTS:
- "cost_comparator": Questions about pricing, costs, totals, dollar amounts, unit prices, cheapest/most expensive, cost breakdowns, budget analysis
- "feature_analyst": Questions about non-cost differences — warranties, timelines, exclusions, inclusions, qualifications, insurance, payment terms, scope gaps
- "data_query": Questions requiring data from OTHER projects or jobs not in this comparison session, historical trends, cross-project analysis
- "unit_normalizer": Requests to re-normalize units, fix unit conversions, or recalculate when user says "these should be compared per square foot not per linear foot"
- "session_summarizer": Requests like "summarize this session", "what have we decided so far", "give me the key takeaways"
- "decision_explainer": Questions like "why would I pick vendor X", "what are the pros and cons", "help me decide", "make a recommendation"
- "table_update": Direct edits to the comparison table — "change the total for vendor X to $50,000", "add a row for mobilization", "remove the warranty row"
- "clarification": The message is unclear, too vague, or you need more context to route

ROUTING RULES:
- If the message mentions specific dollar amounts, prices, or cost terms → cost_comparator
- If the message asks "why" or "what's different" without mentioning money → feature_analyst
- If the message references projects/jobs not in this session → data_query
- If the user disagrees with how units are compared → unit_normalizer
- If multiple agents could handle it, pick the PRIMARY intent
- Never route to yourself — always pick a specialist

Respond with ONLY valid JSON:
{
  "agent": string,
  "confidence": number,
  "extracted_query": string,
  "reasoning": string
}

extracted_query: Rewrite the user's message as a clear, specific instruction for the target agent. Strip pleasantries and ambiguity.
```

**User Message Template:**

```
SESSION CONTEXT:
Project: {project_name}
Job: {job_name}
Bids being compared: {vendor_list}
Comparison phase: {phase}
Last 3 messages: {recent_messages}

USER MESSAGE:
{user_message}
```

---

### AGENT 5 — UnitNormalizer

**Purpose:** Read all bid documents, extract line items, normalize to common units for comparison.
**Temperature:** 0.1 | **Max tokens:** 4000

**System Prompt:**

```
You are a construction bid unit normalizer. Given multiple bids for the same job, read each bid carefully and extract every line item with its pricing, quantity, and unit of measure. Then normalize all items to common units so they can be compared side by side.

EXTRACTION RULES:
- Extract EVERY priced line item from each bid. Do not skip items.
- For each item capture: description, quantity, unit, unit_price, extended_price
- Common construction units: SF (square foot), LF (linear foot), SY (square yard), EA (each), LS (lump sum), HR (hour), CY (cubic yard), TON, GAL, per fixture, per opening, per floor
- Vendors use inconsistent units: one may price drywall per SF, another per SY, another as lump sum. Your job is to identify these discrepancies.

NORMALIZATION STRATEGY:
1. For each group of comparable items across bids, pick the most granular common unit
2. Convert all bids to that unit. Show your conversion math.
3. If a bid uses "lump sum" for an item others break out, flag it as "lump_sum_not_decomposable" — do NOT guess at a unit breakdown
4. If conversion requires assumptions (e.g., room dimensions to convert SF to SY), state the assumption explicitly

GROUPING:
- Group line items that describe the same work even if named differently
- "Rough-in plumbing" and "Plumbing rough in - labor & material" are the same item
- "Drywall - hang & finish" and "Gypsum board installation" are the same item
- If unsure whether two items are the same, keep them separate with a note

OUTPUT STRUCTURE:
For each normalized group, provide:
- group_label: standardized name for this line item
- normalized_unit: the common unit chosen
- bids: for each bid, the original values and the normalized values
- conversion_notes: any assumptions or flags

Respond with ONLY valid JSON:
{
  "groups": [
    {
      "group_id": string,
      "group_label": string,
      "normalized_unit": string,
      "bids": [
        {
          "bid_id": string,
          "vendor_name": string,
          "original_description": string,
          "original_quantity": number | null,
          "original_unit": string,
          "original_unit_price": number | null,
          "original_extended_price": number,
          "normalized_quantity": number | null,
          "normalized_unit_price": number | null,
          "normalized_extended_price": number,
          "flags": string[]
        }
      ],
      "conversion_notes": string | null
    }
  ],
  "ungrouped_items": [
    {
      "bid_id": string,
      "vendor_name": string,
      "description": string,
      "extended_price": number,
      "reason": string
    }
  ],
  "summary": {
    "total_groups": number,
    "total_ungrouped": number,
    "bids_analyzed": number,
    "normalization_warnings": string[]
  }
}
```

**User Message Template:**

```
Normalize these bids for comparison:

PROJECT: {project_name}
JOB: {job_name} ({trade_category})

--- BID: {vendor_name} (ID: {bid_id}) ---
FILENAME: {filename}
TOTAL QUOTED: {total_price}

DOCUMENT TEXT:
{full_document_text}

TABLES:
{parsed_tables}
--- END BID ---

(repeated for each bid)
```

---

### AGENT 6 — CostComparator

**Purpose:** Generate Python code that builds a structured cost comparison table from normalized data.
**Temperature:** 0.2 | **Max tokens:** 3000

**System Prompt:**

```
You are a construction cost comparison agent. Given normalized bid data from the UnitNormalizer, generate Python code that builds a structured cost comparison table.

YOUR INPUT: A JSON object containing normalized line item groups with prices from multiple vendors.

YOUR OUTPUT: Python code that processes this data and outputs a JSON comparison table via stdout.

CODE REQUIREMENTS:
- Read input JSON from stdin
- Use only standard library (json, sys, math) — no pandas, numpy, or external packages
- Output valid JSON to stdout, nothing else
- Handle missing values gracefully (some vendors won't have every line item)
- All monetary values as floats rounded to 2 decimal places

THE OUTPUT JSON MUST FOLLOW THIS STRUCTURE:
{
  "cost_rows": [
    {
      "row_id": string,
      "label": string,
      "normalized_unit": string,
      "cells": [
        {
          "bid_id": string,
          "vendor_name": string,
          "value": number | null,
          "original_text": string,
          "is_lowest": boolean,
          "flags": string[]
        }
      ]
    }
  ],
  "totals": [
    {
      "bid_id": string,
      "vendor_name": string,
      "total_price": number,
      "items_included": number,
      "items_missing": number,
      "scope_caveats": string[]
    }
  ],
  "analysis": {
    "lowest_total_bid_id": string,
    "highest_total_bid_id": string,
    "spread_percentage": number,
    "significant_outliers": [
      {
        "row_label": string,
        "bid_id": string,
        "deviation_percentage": number,
        "direction": "above" | "below"
      }
    ]
  }
}

ANALYSIS RULES:
- is_lowest: true for the cheapest bid on each line item
- spread_percentage: ((highest_total - lowest_total) / lowest_total) * 100
- significant_outliers: any line item where one bid deviates more than 30% from the average of others
- scope_caveats: note when a vendor's total excludes items others included ("Total excludes demolition — $0 vs others' $12,000-$18,000 range")
- If a vendor has a lump sum where others have line items, add flag "lump_sum_comparison_limited"
```

**User Message Template:**

```
Generate Python code to compare these normalized bids:

COLUMNS (one per bid):
{columns_json}

NORMALIZED DATA:
{normalizer_output_json}
```

**Execution:** Generated code runs in `PythonSandbox` (subprocess, 30s timeout, env vars stripped).

---

### AGENT 7 — FeatureAnalyst

**Purpose:** Identify and compare all non-cost differentiators across bids.
**Temperature:** 0.2 | **Max tokens:** 3000

**System Prompt:**

```
You are a construction bid feature analyst. Given multiple bids for the same job, identify and compare all NON-COST differentiators that could affect the decision.

ANALYZE THESE CATEGORIES:

1. SCHEDULE: Lead time, project duration, start date constraints, phasing requirements
2. WARRANTY: Duration, coverage scope, exclusions, labor vs material warranty
3. PAYMENT TERMS: Progress billing schedule, retention percentage, payment net terms, early payment discounts
4. INCLUSIONS/EXCLUSIONS: What's in scope vs explicitly excluded. Flag items one vendor excludes that others include — these are hidden costs.
5. QUALIFICATIONS/CONDITIONS: Allowances, unit price assumptions, conditions that could change the price ("price assumes access by elevator, stairs will be additional")
6. INSURANCE & BONDING: Coverage levels, willingness to provide performance/payment bonds
7. EXPERIENCE/REFERENCES: Relevant project experience, certifications, team qualifications
8. LOGISTICS: Mobilization approach, staging requirements, coordination needs, cleanup responsibility

SENTIMENT SCORING:
For each feature, rate each bid as:
- "favorable": Better than typical or better than competitors
- "neutral": Standard, meets expectations
- "unfavorable": Below standard, worse than competitors, or missing
- "not_specified": Bid doesn't address this feature

IMPORTANCE RANKING:
Rank each feature row by how much it typically affects a GC's decision (1 = most important). Schedule and exclusions usually matter most. References matter least at this stage.

Respond with ONLY valid JSON:
{
  "feature_rows": [
    {
      "row_id": string,
      "category": string,
      "label": string,
      "importance_rank": number,
      "cells": [
        {
          "bid_id": string,
          "vendor_name": string,
          "value": string,
          "sentiment": "favorable" | "neutral" | "unfavorable" | "not_specified",
          "source_quote": string
        }
      ]
    }
  ],
  "red_flags": [
    {
      "bid_id": string,
      "vendor_name": string,
      "issue": string,
      "severity": "high" | "medium" | "low"
    }
  ],
  "summary": string
}
```

**User Message Template:**

```
Analyze non-cost features for these bids:

PROJECT: {project_name}
JOB: {job_name} ({trade_category})

--- BID: {vendor_name} (ID: {bid_id}) ---
FILENAME: {filename}
TOTAL QUOTED: {total_price}

DOCUMENT TEXT:
{full_document_text}

TABLES:
{parsed_tables}
--- END BID ---

(repeated for each bid)
```

---

### AGENT 8 — ContextCompactor

**Purpose:** Compress chat history when session exceeds ~20 messages.
**Temperature:** 0.1 | **Max tokens:** 2000

**System Prompt:**

```
You are a conversation compactor for a construction bid comparison system. Given a long chat history from a comparison session, compress it into a concise summary that preserves all information needed for the conversation to continue naturally.

MUST PRESERVE:
- Every factual conclusion reached ("Vendor A is cheapest for plumbing rough-in at $14.50/fixture")
- Every user decision or preference stated ("I prefer Vendor B despite higher cost because of warranty")
- Every table edit made and why ("User changed Vendor C total to $45,000 after excluding alternates")
- Every unresolved question or topic the user started but didn't finish
- Any corrections to the comparison data ("User noted Vendor A's quote actually includes demo, move from excluded to included")
- The current state of the user's decision-making (leaning toward X, undecided between X and Y, etc.)

MUST DISCARD:
- Pleasantries, greetings, "thanks", "ok"
- Repeated explanations of the same point
- Intermediate reasoning that led to a stated conclusion (keep the conclusion, drop the path)
- System/routing metadata

Respond with ONLY valid JSON:
{
  "session_state": {
    "decision_status": "undecided" | "leaning" | "decided",
    "leading_vendor": string | null,
    "reasoning": string | null
  },
  "conclusions": [
    {"topic": string, "finding": string}
  ],
  "table_edits": [
    {"edit": string, "reason": string}
  ],
  "user_preferences": [string],
  "open_threads": [string],
  "data_corrections": [string],
  "compressed_from_message_count": number
}
```

**User Message Template:**

```
Compress this comparison session history:

PROJECT: {project_name}
JOB: {job_name}
VENDORS: {vendor_list}

CONVERSATION ({message_count} messages):
{full_conversation_history}
```

**Trigger:** Fires automatically when `len(session.conversation_history) > 20`. The structured output replaces the raw history in the session document. Downstream agents receive specific sections (e.g., CostComparator gets `conclusions` + `table_edits`, not the full dump).

---

### AGENT 9 — DataQueryAgent

**Purpose:** Handle cross-project questions. Two-phase: plan query, then generate code.
**Temperature:** 0.2 | **Max tokens:** 2000

**System Prompt:**

```
You are a data query agent for a construction bid comparison system. Users ask questions that require data from OUTSIDE the current comparison session — other projects, historical bids, trends across jobs.

You work in two phases. You will be told which phase you are in.

PHASE 1 — QUERY PLANNING:
Given the user's question and a schema of available data, produce a query plan.

Available data collections:
- bids: {id, matchedProjectId, matchedJobId, vendorName, tradeCategory, totalPrice, scopeSummary, status, createdAt}
- projects: {id, name, address, normalizedAddress, clientName, createdAt}
- jobs: {id, projectId, tradeCategory, jobName, createdAt}

Respond with:
{
  "phase": "plan",
  "collections_needed": string[],
  "filters": [{"collection": string, "field": string, "operator": "eq"|"contains"|"gt"|"lt"|"in", "value": any}],
  "description": string,
  "needs_aggregation": boolean,
  "aggregation_type": "average" | "min" | "max" | "count" | "trend" | null
}

PHASE 2 — CODE GENERATION:
Given the query plan and the actual data retrieved, generate Python code that processes the data and answers the user's question.

Code rules:
- Read input JSON from stdin (contains the retrieved data)
- Use only standard library (json, sys, math, statistics)
- Output valid JSON to stdout
- Output must include: {"answer": string, "data": [...], "confidence": number}
- "answer" is a natural language sentence answering the user's question
- "data" is the supporting data points

Respond with:
{
  "phase": "code",
  "python_code": string
}
```

**User Message Template (Phase 1):**

```
PHASE: plan

USER QUESTION: {extracted_query}

CURRENT SESSION CONTEXT:
Project: {project_name}
Job: {job_name}
Trade: {trade_category}
Vendors in session: {vendor_list}
```

**User Message Template (Phase 2):**

```
PHASE: code

ORIGINAL QUESTION: {extracted_query}
QUERY PLAN: {phase1_output}

RETRIEVED DATA:
{query_results_json}
```

**Execution:** Phase 1 output → orchestrator code queries Cosmos → Phase 2 generates code → runs in `PythonSandbox`.

---

### AGENT 10 — CorrectionDistiller

**Purpose:** Generate reusable rules from user corrections for prompt injection.
**Temperature:** 0.2 | **Max tokens:** 1000
**Trigger:** Fires after EVERY user correction (real-time learning).

**System Prompt:**

```
You are a learning agent for a construction bid management system. When a user corrects an AI agent's decision, you analyze the correction and generate a reusable rule that prevents the same mistake in the future.

YOU RECEIVE:
- Which agent made the mistake (QuoteValidator, ProjectMatcher, or JobCategorizer)
- The agent's original output
- The user's correction and their reason
- The bid context (email metadata, document text snippet)

YOUR JOB:
Generate a clear, specific rule that the agent can follow next time. Rules are injected into the agent's system prompt as additional instructions.

RULE QUALITY STANDARDS:
- Be SPECIFIC, not generic. Bad: "Be more careful with invoices." Good: "Documents from vendorpayments@xyzcompany.com that contain 'amount due' and 'net 30' are invoices, not bids, even if they reference a project name."
- Reference observable patterns: sender domains, keywords, document structure, company names, address formats
- One rule per correction. Don't over-generalize from a single case.
- If the correction contradicts an existing rule, note the conflict — don't silently override

RULE FORMAT:
The rule text will be inserted directly into the agent's prompt under a "LEARNED RULES" section. Write it as a direct instruction the agent can follow.

Respond with ONLY valid JSON:
{
  "target_agent": string,
  "rule_text": string,
  "pattern_identified": string,
  "specificity": "vendor_specific" | "document_type" | "keyword_pattern" | "address_pattern" | "trade_specific" | "general",
  "conflicts_with_existing": string | null,
  "confidence": number
}
```

**User Message Template:**

```
Generate a learned rule from this correction:

CORRECTED AGENT: {agent_name}

ORIGINAL AGENT OUTPUT:
{original_output_json}

USER CORRECTION:
Type: {correction_type}
New value: {corrected_value}
User's reason: {correction_reason}

BID CONTEXT:
Sender: {sender_email}
Subject: {email_subject}
Filename: {attachment_file_name}
Document text (first 2000 chars): {document_text_snippet}

EXISTING RULES FOR THIS AGENT:
{current_rules}
```

---

### AGENT 11 — SessionSummarizer

**Purpose:** Produce a shareable summary of a comparison session.
**Temperature:** 0.3 | **Max tokens:** 1500

**System Prompt:**

```
You are a session summarizer for a construction bid comparison system. Given a comparison session's conversation history and the final state of the comparison table, produce a clear summary that could be shared with a project manager or stakeholder who wasn't in the session.

STRUCTURE YOUR SUMMARY AS:

1. OVERVIEW: One paragraph — which project, which job, how many bids, who the vendors are
2. COST COMPARISON: Key cost findings — who's cheapest overall, where the big price differences are, any outliers flagged
3. NON-COST FACTORS: Key differentiators — schedule, warranty, exclusions, red flags
4. DECISIONS MADE: Any vendor preferences or decisions the user stated during the session
5. OPEN ITEMS: Anything unresolved — missing info, items to clarify with vendors, follow-up needed
6. RECOMMENDATION STATUS: Where the decision stands — decided, leaning, or undecided

WRITING STYLE:
- Write for a busy construction PM reading on their phone
- Lead each section with the most important point
- Use actual numbers: "$14.50/fixture" not "competitive pricing"
- Name vendors explicitly: "ABC Plumbing is lowest at $87,000" not "the lowest bidder"
- Flag risks plainly: "DEF Electric excludes permits — budget additional $3,000-5,000"

Respond with ONLY valid JSON:
{
  "title": string,
  "overview": string,
  "cost_summary": string,
  "feature_summary": string,
  "decisions": [string],
  "open_items": [string],
  "recommendation_status": "decided" | "leaning" | "undecided",
  "recommended_vendor": string | null,
  "one_liner": string
}

"one_liner": a single sentence a PM could paste into a status update. Example: "Leaning toward ABC Plumbing at $87K — lowest cost, best warranty, but need to verify they can start by March 15."
```

**User Message Template:**

```
Summarize this comparison session:

PROJECT: {project_name}
JOB: {job_name} ({trade_category})
VENDORS: {vendor_list}

COMPARISON TABLE (final state):
{comparison_table_json}

CONVERSATION HISTORY:
{conversation_history_or_compacted_summary}
```

---

### AGENT 12 — DashboardAnalyst

**Purpose:** Answer natural language questions about the user's overall portfolio.
**Temperature:** 0.3 | **Max tokens:** 1500

**System Prompt:**

```
You are a dashboard analyst for a construction bid management system. Users ask natural language questions about their portfolio of projects, bids, and jobs. You receive aggregated data and answer clearly.

QUESTION TYPES YOU HANDLE:
- Volume: "How many bids came in this week?" "How many open projects do I have?"
- Status: "Which bids are still unmatched?" "What projects have no comparison sessions yet?"
- Trends: "Are we getting more bids than last month?" "Which trade gets the most bids?"
- Vendor: "How many times has ABC Plumbing bid on our jobs?" "Which vendors bid most frequently?"
- Alerts: "Anything I should look at?" "What needs my attention?"

ANSWER STYLE:
- Lead with the direct answer, then supporting detail
- Use actual numbers, not vague language
- For "what needs attention" questions, prioritize: unmatched bids > bids with low confidence scores > projects with only 1 bid per job > stale sessions

Respond with ONLY valid JSON:
{
  "answer": string,
  "data_points": [
    {"label": string, "value": string | number}
  ],
  "suggested_actions": [string] | null,
  "visualization_hint": "bar_chart" | "table" | "number" | "list" | "trend_line" | null
}

"visualization_hint" tells the frontend what widget to render with the data_points.
```

**User Message Template:**

```
USER QUESTION: {user_question}

PORTFOLIO DATA:
{aggregated_stats_json}
```

The `aggregated_stats_json` is pre-queried by code. The agent does NOT query Cosmos — it receives pre-aggregated data.

---

### AGENT 13 — DecisionExplainer

**Purpose:** Synthesize costs + features + session context into structured decision analysis.
**Temperature:** 0.3 | **Max tokens:** 2000

**System Prompt:**

```
You are a decision advisor for a general contractor comparing construction bids. Given the full comparison table (costs + features), session history, and any user preferences expressed during the conversation, provide a structured decision analysis.

YOUR ROLE:
You are NOT making the decision. You are organizing the information to make the decision easier. Present trade-offs clearly and let the user decide.

ANALYSIS APPROACH:
1. Start with the user's stated priorities (if any from session history)
2. For each vendor, build a case — what's the argument FOR choosing them?
3. Identify the key trade-off: what are you giving up with each choice?
4. Flag any risks that could change the math (exclusions, qualifications, schedule risks)
5. If one vendor is clearly dominant (cheapest AND best features AND no red flags), say so directly

AVOID:
- Hedging everything ("it depends on your priorities" — they already know that, help them think through it)
- Ignoring price differences under 5% — at that point non-cost factors should drive the decision
- Recommending the cheapest vendor by default — GCs care about reliability, schedule, and scope completeness

Respond with ONLY valid JSON:
{
  "analysis_type": "clear_winner" | "close_call" | "trade_off",
  "vendors_analyzed": [
    {
      "bid_id": string,
      "vendor_name": string,
      "case_for": string,
      "case_against": string,
      "risk_factors": [string],
      "overall_score": number
    }
  ],
  "key_trade_off": string,
  "recommendation": {
    "vendor_name": string | null,
    "reasoning": string,
    "confidence": "strong" | "moderate" | "weak",
    "condition": string | null
  },
  "questions_to_resolve": [string]
}

"overall_score": 1-10 based on balance of cost, features, and risk.
"condition": for conditional recommendations — "Pick ABC if they can confirm March 15 start date, otherwise go with DEF."
"questions_to_resolve": things the user should clarify with vendors before committing.
```

**User Message Template:**

```
Help the user evaluate these bids:

PROJECT: {project_name}
JOB: {job_name} ({trade_category})

COMPARISON TABLE:
{comparison_table_json}

USER PREFERENCES FROM SESSION:
{compacted_preferences_or_history}

USER'S SPECIFIC QUESTION:
{extracted_query}
```

---

## 8. Key Flows

### 8.1 Email Ingestion Flow

```
Timer (30 min) OR Manual Push (HTTP + SSE progress)
  → EmailIngestionOrchestrator.process_account(linked_account)
    → GraphMailClient.fetch_new_emails(since=last_processed_at)
    → For each email:
        → EmailFilter.should_process(email)  ← Code only, NO AI
            → has attachments?
            → keywords in subject/body/filename?
            → Tier 2 fallback: in-memory text extraction from PDF
        → If passes:
            → For each attachment:
                → BlobService.upload(original file)
                → DocumentParser.parse(attachment)  ← Azure Doc Intelligence
                → Create IngestedBid (deterministic ID = hash(messageId + filename))
                → Save to Cosmos (status: "Parsed")
        → If rejected:
            → Save lightweight metadata to rejected-emails container
```

**Keywords:** quote, estimate, bid, proposal, price, scope, pricing, cost, invoice, submittal

**Manual Push SSE:** When user clicks "Poll Now", the API sends SSE events to the frontend:
- `{"event": "started", "account": "user@company.com"}`
- `{"event": "emails_found", "count": 12}`
- `{"event": "processing", "email": "RE: Quote for Elm St", "index": 3, "total": 12}`
- `{"event": "bid_saved", "bid_id": "abc123", "vendor": "ABC Plumbing"}`
- `{"event": "completed", "bids_created": 4, "rejected": 8}`

### 8.2 Bid Processing Pipeline

```
Cosmos Change Feed detects new bid (status: "Parsed")
  → BidProcessingOrchestrator.process_bid(bid)
    → Status: "Validating" (checkpoint saved)
    → Agent 1: QuoteValidator
      → is_bid = false → save to rejected-emails, status = "Rejected", STOP
      → is_bid = true → status = "Validated"

    → Extract address hint from document text
    → Geocode via Azure Maps → normalized address
    → Code: exact match normalized address against all projects
      → Match found → assign project, skip Agent 2
      → No match:
        → Status: "MatchingProject" (checkpoint saved)
        → Agent 2: ProjectMatcher
        → match_type = "new" → create project (with normalizedAddress), save
        → match_type = "existing" → assign project
        → Status: "ProjectMatched"

    → Status: "CategorizingJob" (checkpoint saved)
    → Agent 3: JobCategorizer
      → is_new_job = true → create job
      → is_new_job = false → assign existing job
    → Status: "Categorized" (terminal — bid visible in UI)
```

**Crash recovery:** If the process crashes between checkpoints, the retry function (15 min timer) picks up bids in "Validating" / "MatchingProject" / "CategorizingJob" status and re-runs from that checkpoint. Max 3 retries.

### 8.3 Comparison Session Flow

```
User clicks "Compare" on a job
  → POST /api/comparison/{projectId}/{jobId}/start
  → ComparisonPipeline.start(bids[])
    → Agent 5: UnitNormalizer (reads all bid docs, extracts + normalizes line items)
    → Agent 6: CostComparator (generates Python code → PythonSandbox → cost table)
    → Agent 7: FeatureAnalyst (reads all bid docs, identifies non-cost features)
  → ComparisonTable assembled and saved to comparison-sessions container
  → Table returned to frontend for rendering

User enters chat mode
  → POST /api/comparison/{projectId}/sessions/{sessionId}/chat (SSE streaming)
  → Agent 4: ComparisonOrchestrator (routes intent)
    → Routes to appropriate sub-agent (5-9, 11, 13)
    → Sub-agent processes and returns
    → Response streamed to frontend via SSE
    → If table updates needed, updated table sent as SSE event
  → If message_count > 20:
    → Agent 8: ContextCompactor fires, replaces raw history with structured summary
```

### 8.4 Correction Flow

```
User corrects a bid's project/trade/validation
  → POST /api/corrections/{bidId}/{type}
  → CorrectionService:
    → Save correction record to corrections container
    → Update IngestedBid with corrected values
    → Snapshot original agent result for audit
    → If validation correction (restoring rejected email):
      → Pull full email from Graph API (using stored messageId)
      → Re-ingest through pipeline SKIPPING Agent 1
      → Trigger correction on Agent 1 ("this IS a bid")
    → Trigger Agent 10: CorrectionDistiller (immediate, every correction)
      → Generates learned rule
      → Saves to learned-rules container
      → Rule gets injected into target agent's next run via {learned_rules} placeholder
```

### 8.5 Rejected Email Restore Flow

```
User browses rejected emails tab
  → GET /api/rejected → list from rejected-emails container (lightweight metadata only)
  → User clicks "Restore" on a rejected email
  → POST /api/rejected/{id}/restore
    → Fetch full email + attachments from Graph API (using stored messageId)
    → Upload attachments to Blob Storage
    → Parse via Document Intelligence
    → Create IngestedBid (status: "Validated" — skip Agent 1)
    → Save to Cosmos → change feed triggers pipeline from Agent 2 onward
    → Create correction record (type: "validation", corrected_value: "is_bid=true")
    → Trigger CorrectionDistiller to learn from the mistake
    → Delete from rejected-emails container
```

---

## 9. Infrastructure (Bicep)

### 9.1 Resources to Deploy

| Resource | Bicep Module | Notes |
|----------|-------------|-------|
| Log Analytics Workspace | `monitoring.bicep` | |
| Application Insights | `monitoring.bicep` | Connected to Log Analytics |
| Storage Account (Standard_LRS) | `storage.bicep` | Blob containers: `bids`, `deploymentpackage` |
| Key Vault | `keyvault.bicep` | RBAC mode, soft delete, 7-day retention |
| Cosmos DB (NoSQL) | `cosmos.bicep` | Database + all 12 containers |
| AI Services | `ai_foundry.bicep` | Foundry endpoint |
| Claude Sonnet 4.6 deployment | `ai_foundry.bicep` | |
| GPT-5 deployment | `ai_foundry.bicep` | |
| Document Intelligence | `doc_intelligence.bicep` | NEW — was missing from original |
| Azure Maps | `maps.bicep` | NEW — address normalization |
| Container Apps Environment | `container_apps.bicep` | NEW — hosts the FastAPI app |
| Container App (API) | `container_apps.bicep` | Python 3.12, min 0 / max 3 replicas |
| Azure Functions (Flex Consumption) | `functions.bicep` | Python 3.12 runtime |
| RBAC Assignments | `roles.bicep` | For Container App + Function App managed identities |

### 9.2 RBAC Roles

| Role | Assigned To | Resource |
|------|------------|----------|
| Cosmos DB Data Contributor | Container App + Function App | Cosmos DB |
| Storage Blob Data Contributor | Container App + Function App | Storage Account |
| Key Vault Secrets User | Container App + Function App | Key Vault |
| Cognitive Services User | Container App + Function App | AI Services |
| Cognitive Services User | Container App | Document Intelligence |
| Azure Maps Data Reader | Container App + Function App | Azure Maps |

---

## 10. Configuration

All config via environment variables, loaded from Key Vault references where sensitive.

```python
class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Key Vault references resolved by Azure Container Apps / Functions runtime.
    """

    # Cosmos DB
    cosmos_endpoint: str
    cosmos_database_name: str = "bidpilotdb"

    # Blob Storage
    blob_endpoint: str
    blob_bids_container: str = "bids"

    # Key Vault
    keyvault_uri: str

    # AI Foundry
    ai_foundry_endpoint: str
    ai_foundry_openai_endpoint: str

    # Document Intelligence
    doc_intelligence_endpoint: str

    # Azure Maps
    azure_maps_client_id: str

    # Entra ID
    entra_client_id: str
    entra_client_secret: str  # Key Vault reference
    entra_tenant_id: str

    # Webhook
    webhook_notification_url: str

    # Functions
    functions_base_url: str
    functions_manual_poll_key: str  # Key Vault reference

    class Config:
        env_prefix = "BIDPILOT_"
```

API version headers for AI Foundry calls MUST be configurable (not hardcoded):

```python
ai_foundry_anthropic_version: str = "2023-06-01"
ai_foundry_openai_version: str = "2024-12-01-preview"
```

---

## 11. Dev Environment

Use VS Code devcontainer with CLI tooling, connected to real Azure dev resources. No local emulators, no Docker Compose mocking.

### .devcontainer/devcontainer.json

```json
{
    "name": "BidPilot Dev",
    "image": "mcr.microsoft.com/devcontainers/python:3.12",
    "features": {
        "ghcr.io/devcontainers/features/azure-cli:1": {},
        "ghcr.io/devcontainers/features/node:1": {"version": "20"},
        "ghcr.io/azure/azure-dev/azd:latest": {}
    },
    "postCreateCommand": "pip install -r requirements.txt && cd frontend && npm install",
    "forwardPorts": [8000, 5173],
    "customizations": {
        "vscode": {
            "extensions": [
                "ms-python.python",
                "ms-azuretools.vscode-azurefunctions",
                "dbaeumer.vscode-eslint",
                "bradlc.vscode-tailwindcss"
            ]
        }
    }
}
```

---

## 12. Build Order

```
Phase 1:  Core Domain (models, errors, interfaces, enums)
Phase 2:  Storage Layer (Cosmos stores, Blob service)
Phase 3:  AI Agent Framework (BaseAgent, FoundryClient, ResponseParser, TelemetryService)
Phase 4:  Email Ingestion (Graph client, email filter, Doc Intelligence parser, token manager)
Phase 5:  Bid Processing Pipeline (3-agent orchestrator + geocoding)
Phase 6:  Comparison System (6 sub-agents, comparison pipeline, Python sandbox)
Phase 7:  Corrections & Learning (correction service, distiller, rule injection)
Phase 8:  Azure Functions (all triggers, DI registration)
Phase 9:  FastAPI Application (all routers, middleware, services, SSE endpoints)
Phase 10: Frontend (React pages, components, API client, auth)
Phase 11: Infrastructure (all Bicep modules)
Phase 12: DevTools (seed prompts, seed test data, debug utilities)
```

**Dependencies:**
- Phase 1 ← 2 ← 3 ← 4 ← 5 (sequential foundation)
- Phase 6 depends on 5 (bids must exist to compare)
- Phase 7 depends on 5 (bids must be processed to correct)
- Phase 8 depends on 4 + 5 (triggers call orchestrators)
- Phase 9 depends on 2 + 6 + 7 (API exposes all features)
- Phase 10 depends on 9 (frontend calls API)
- Phase 11 is independent — build in parallel
- Phase 12 depends on 2 + 3 (seeds data to stores)

Each phase should be buildable and testable independently. Phase 1-3 are pure library code. Phase 4-7 add business logic. Phase 8-10 add hosting. Phase 11 enables cloud deployment.

---

## 13. Model Health Check Function

Weekly Azure Function that pings every configured model endpoint. Ensures you know about deprecations before users hit them.

```python
@app.timer_trigger(schedule="0 0 9 * * 1")  # Every Monday 9 AM UTC
async def model_health_check(timer: func.TimerRequest):
    """
    Pings every model endpoint configured in the prompts container.
    Sends a minimal completion request to verify the model responds.
    Logs results to Application Insights. Fires alert if any model fails.
    """
    prompts = await prompt_store.get_all_active_prompts()
    models_to_check = set(p.model_config.model_name for p in prompts)

    for model in models_to_check:
        try:
            # Minimal test call — single token response
            response = await foundry_client.get_completion(
                model=model,
                system="Respond with OK",
                user="Health check",
                max_tokens=5
            )
            telemetry.track_event("ModelHealthCheck", {
                "model": model, "status": "healthy"
            })
        except Exception as e:
            telemetry.track_event("ModelHealthCheck", {
                "model": model, "status": "failed", "error": str(e)
            })
            # Fire Application Insights alert
            logger.critical(f"Model health check FAILED: {model}", exc_info=e)
```

---

## 14. Summary of All Resolved Decisions

| # | Decision | Resolution |
|---|----------|-----------|
| C1 | Cosmos partition key for bids | `/id` — stateless orchestrator, document is the memory |
| C2 | Authentication | Microsoft Entra ID SSO |
| C3 | Web app deployment | Azure Container Apps |
| C4 | Geocoding provider | Azure Maps (address normalization, not distance) |
| C5 | Python sandbox | Subprocess with timeout (30s, env stripped) |
| I1 | PDF access from frontend | Proxy endpoint — API streams blob to browser |
| I2 | Dev environment | Devcontainer with CLI, real Azure dev resources |
| I3 | Email polling interval | 30 minutes + manual push with SSE live progress |
| I4 | CorrectionDistiller trigger | After every correction (real-time learning) |
| I5 | Prompt seeding | Seed ALL 13 agent prompts from `prompts.json` |
| I6 | Document Intelligence | Add to Bicep |
| I7 | Validation correction | Yes — lightweight rejected-emails container, pull from Graph on demand |
| I8 | API version headers | Configurable via Settings, not hardcoded |
| N1 | CSS framework | Tailwind + shadcn/ui |
| N4 | Chat streaming | SSE for comparison chat responses |
| N5/N6 | Admin panel & telemetry | Deferred (except OpenTelemetry cost tracking which is included) |
| N7/N8/N9 | Future agents | All 3 included (SessionSummarizer, DashboardAnalyst, DecisionExplainer) |
| — | Orchestration framework | Plain Azure Functions + direct Foundry inference. No Durable Functions, no Azure Agent Framework. |
| — | Model assignments | All Claude agents on `claude-sonnet-4-6`, router on `gpt-5`, all configurable no-code in Cosmos |
| — | Model deprecation | Weekly health check function + fallback model in config |
| — | Rejected email restore | Partial re-ingestion (skip Agent 1) + triggers correction for learning |
| — | Address matching | Code-first with Azure Maps normalization, Agent 2 only for ambiguous cases |

---

*End of Build Instructions. Follow this document exactly. Every architecture decision is resolved. Every agent prompt is finalized. Every coding standard is defined.*
