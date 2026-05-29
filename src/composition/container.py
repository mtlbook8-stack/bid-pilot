"""
AppContainer — the single composition root for BidPilot's backend.

This is the ONE place where concrete classes are instantiated and wired together
(Rule 3). Both hosting entry points reuse it so the wiring is defined once (Rule
5): the FastAPI app (`src/api/main.py`) builds its request services + routers on
top of this container, and the Azure Functions host (`src/functions/`) drives the
orchestrators it exposes.

Lifecycle: construct cheaply, then `await startup()` to open network-capable
resources (Cosmos client, HTTP client, credential), then use, then
`await shutdown()` to release them. Nothing here logs — failures wrap as AppError
and surface to the host's top-level handler (Rule 8).
"""

import logging

import httpx
from azure.identity.aio import DefaultAzureCredential

from src.agents.comparison.comparison_orchestrator import ComparisonOrchestrator
from src.agents.comparison.context_compactor import ContextCompactor
from src.agents.comparison.cost_comparator import CostComparator
from src.agents.comparison.data_query_agent import DataQueryAgent
from src.agents.comparison.feature_analyst import FeatureAnalyst
from src.agents.comparison.unit_normalizer import UnitNormalizer
from src.agents.insights.dashboard_analyst import DashboardAnalyst
from src.agents.insights.decision_explainer import DecisionExplainer
from src.agents.insights.session_summarizer import SessionSummarizer
from src.agents.learning.correction_distiller import CorrectionDistiller
from src.agents.pipeline.job_categorizer import JobCategorizer
from src.agents.pipeline.project_matcher import ProjectMatcher
from src.agents.pipeline.quote_validator import QuoteValidator
from src.agents.response_parser import ResponseParser
from src.api.config import Settings, get_settings
from src.core.errors.app_error import AppError
from src.core.models.linked_account import LinkedAccount
from src.infrastructure.ai.foundry_client import AnthropicFoundryClient
from src.infrastructure.ai.foundry_client_router import FoundryClientRouter
from src.infrastructure.ai.openai_foundry_client import OpenAIFoundryClient
from src.infrastructure.cosmos.bid_store import CosmosBidStore
from src.infrastructure.cosmos.correction_store import CosmosCorrectionStore
from src.infrastructure.cosmos.cosmos_client_factory import CosmosClientFactory
from src.infrastructure.cosmos.job_store import CosmosJobStore
from src.infrastructure.cosmos.linked_account_store import CosmosLinkedAccountStore
from src.infrastructure.cosmos.project_store import CosmosProjectStore
from src.infrastructure.cosmos.prompt_store import CosmosPromptStore
from src.infrastructure.cosmos.rejected_store import CosmosRejectedEmailStore
from src.infrastructure.cosmos.rule_store import CosmosRuleStore
from src.infrastructure.cosmos.session_store import CosmosComparisonSessionStore
from src.infrastructure.documents.document_parser import AzureDocumentParser
from src.infrastructure.documents.email_filter import EmailFilter
from src.infrastructure.email.graph_mail_client import GraphMailClient
from src.infrastructure.email.token_manager import GraphTokenManager
from src.infrastructure.email.webhook_manager import GraphWebhookManager
from src.infrastructure.geocoding.azure_maps_service import AzureMapsService
from src.infrastructure.sandbox.python_sandbox import SubprocessPythonSandbox
from src.infrastructure.secrets.keyvault_secret_store import KeyVaultSecretStore
from src.infrastructure.storage.blob_service import AzureBlobService
from src.infrastructure.telemetry.otel_service import OpenTelemetryService
from src.orchestration.bid_processing_orchestrator import BidProcessingOrchestrator
from src.orchestration.comparison_pipeline import ComparisonPipeline
from src.orchestration.email_ingestion_orchestrator import EmailIngestionOrchestrator

logger = logging.getLogger(__name__)


class AppContainer:
    """Builds and owns every wired singleton in the backend."""

    def __init__(self, settings: Settings | None = None) -> None:
        # Cheap construction only — no network resources opened yet.
        self.settings: Settings = settings or get_settings()
        self._factory = CosmosClientFactory(self.settings)
        self._credential: DefaultAzureCredential | None = None
        self._http: httpx.AsyncClient | None = None
        self._secret_store: KeyVaultSecretStore | None = None
        self._blob: AzureBlobService | None = None
        self._started = False

    async def startup(self) -> None:
        """Open shared resources and wire every object. Idempotent."""
        if self._started:
            return
        try:
            self._credential = DefaultAzureCredential()
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
            self._factory.connect()
            self._wire()
            self._started = True
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="CONTAINER_STARTUP",
                message="Failed to start the application container",
                cause=exc,
            )

    async def shutdown(self) -> None:
        """Release all opened transports in reverse order of acquisition."""
        if self._blob is not None:
            await self._blob.close()
        if self._secret_store is not None:
            await self._secret_store.close()
        await self._factory.close()
        if self._http is not None:
            await self._http.aclose()
        if self._credential is not None:
            await self._credential.close()
        self._started = False

    # -- wiring ----------------------------------------------------------------

    def _wire(self) -> None:
        """Instantiate every component once, in dependency order."""
        cred = self._credential
        http = self._http
        settings = self.settings

        # --- Stores (receive container proxies — Rule 3) ---------------------
        self.bid_store = CosmosBidStore(self._factory.get_container("bids"))
        self.project_store = CosmosProjectStore(self._factory.get_container("projects"))
        self.job_store = CosmosJobStore(self._factory.get_container("jobs"))
        self.prompt_store = CosmosPromptStore(self._factory.get_container("prompts"))
        self.rule_store = CosmosRuleStore(self._factory.get_container("learned-rules"))
        self.correction_store = CosmosCorrectionStore(
            self._factory.get_container("corrections")
        )
        self.rejected_store = CosmosRejectedEmailStore(
            self._factory.get_container("rejected-emails")
        )
        self.session_store = CosmosComparisonSessionStore(
            self._factory.get_container("comparison-sessions")
        )
        self.linked_account_store = CosmosLinkedAccountStore(
            self._factory.get_container("linked-accounts")
        )

        # --- Storage + secrets ----------------------------------------------
        self.blob_service = AzureBlobService(settings)
        self._blob = self.blob_service
        self.secret_store = KeyVaultSecretStore(settings)
        self._secret_store = self.secret_store

        # --- Telemetry (pricing table drives cost estimates) -----------------
        pricing = OpenTelemetryService.load_pricing("data/model_pricing.json")
        self.telemetry = OpenTelemetryService(pricing)

        # --- AI clients (router dispatches claude-* vs gpt-*) ----------------
        anthropic = AnthropicFoundryClient(http, cred, settings)
        openai = OpenAIFoundryClient(http, cred, settings)
        self.foundry = FoundryClientRouter(anthropic, openai)
        self.response_parser = ResponseParser()
        self.sandbox = SubprocessPythonSandbox()

        # --- Other infra services -------------------------------------------
        self.geocoder = AzureMapsService(http, cred, settings)
        self.document_parser = AzureDocumentParser(cred, settings)
        self.email_filter = EmailFilter()
        self.token_manager = GraphTokenManager(
            settings,
            self.secret_store.get_secret,
            self.secret_store.set_secret,
        )
        self.graph_client = GraphMailClient(
            self.token_manager, http, self._resolve_account
        )
        self.webhook_manager = GraphWebhookManager(
            self.token_manager, settings, http, self._resolve_account
        )

        # --- Agents (all share the foundry router + stores + telemetry) ------
        agent_deps = (
            self.foundry,
            self.prompt_store,
            self.rule_store,
            self.telemetry,
            self.response_parser,
        )
        self.quote_validator = QuoteValidator(*agent_deps)
        self.project_matcher = ProjectMatcher(*agent_deps)
        self.job_categorizer = JobCategorizer(*agent_deps)
        self.comparison_orchestrator = ComparisonOrchestrator(*agent_deps)
        self.unit_normalizer = UnitNormalizer(*agent_deps)
        self.cost_comparator = CostComparator(*agent_deps, self.sandbox)
        self.feature_analyst = FeatureAnalyst(*agent_deps)
        self.context_compactor = ContextCompactor(*agent_deps)
        self.data_query_agent = DataQueryAgent(*agent_deps, self.sandbox)
        self.correction_distiller = CorrectionDistiller(*agent_deps)
        self.session_summarizer = SessionSummarizer(*agent_deps)
        self.dashboard_analyst = DashboardAnalyst(*agent_deps)
        self.decision_explainer = DecisionExplainer(*agent_deps)

        # --- Orchestrators ---------------------------------------------------
        self.bid_processing_orchestrator = BidProcessingOrchestrator(
            self.quote_validator,
            self.project_matcher,
            self.job_categorizer,
            self.geocoder,
            self.bid_store,
            self.project_store,
            self.job_store,
            self.rejected_store,
            self.telemetry,
            settings,
        )
        self.email_ingestion_orchestrator = EmailIngestionOrchestrator(
            self.graph_client,
            self.email_filter,
            self.blob_service,
            self.document_parser,
            self.bid_store,
            self.rejected_store,
            settings,
        )
        self.comparison_pipeline = ComparisonPipeline(
            self.unit_normalizer,
            self.cost_comparator,
            self.feature_analyst,
            self.bid_store,
            self.session_store,
            self.telemetry,
        )

    async def _resolve_account(self, account_id: str) -> LinkedAccount:
        """
        Resolve a LinkedAccount by id for the Graph clients.

        The IGraphMailClient interface passes only an account id, but Graph calls
        need the full account (mailbox address + token secret name). Accounts are
        partitioned by userId, so this does a cross-partition scan of active
        accounts — fine at this scale (a handful of linked mailboxes).
        """
        accounts = await self.linked_account_store.list_all_active()
        for account in accounts:
            if account.id == account_id:
                return account
        raise AppError(
            code="CONTAINER_ACCOUNT_RESOLVE",
            message="No active linked account found for id",
            context={"account_id": account_id},
        )
