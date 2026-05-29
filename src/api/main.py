"""
FastAPI composition root for BidPilot (build doc section 3, Phase 9).

WHY this file is special: it is the ONE place in the API where the AppContainer
is instantiated, the request services are built from its wired singletons, and
everything is attached to `app.state` (Rule 3 — composition root). Routers and
dependency providers only READ from `app.state`; they never construct anything.

Lifespan: on startup we build + start the container, construct the five request
services from its building blocks, and stash them; on shutdown we release the
container's transports. The global error handlers (the single Rule 8 logging
site), the request-tracing middleware, and CORS for the Vite dev origin are
registered here. All eight API routers mount under `/api`; every router except
auth login/callback and the health probes runs behind `get_current_user`.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import get_current_user
from src.api.middleware.error_handler import register_error_handlers
from src.api.middleware.telemetry import TelemetryMiddleware
from src.api.routers import (
    auth_router,
    bids_router,
    comparison_router,
    corrections_router,
    email_accounts_router,
    projects_router,
    rejected_router,
    stats_router,
)
from src.api.services.comparison_service import ComparisonService
from src.api.services.correction_service import CorrectionService
from src.api.services.dashboard_service import DashboardService
from src.api.services.manual_poll_service import ManualPollService
from src.api.services.pdf_proxy_service import PdfProxyService
from src.composition.container import AppContainer

logger = logging.getLogger(__name__)

# Allowed browser origins. The Vite dev server runs on 5173 (build doc section
# 11 forwards that port); production origins are added via the same list when
# deployed. Kept explicit rather than "*" so credentialed requests are permitted.
_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Build + start the container, construct services, and clean up on shutdown.

    This is the composition root's lifecycle. We construct the AppContainer,
    `await startup()` (opens Cosmos/HTTP/credential), then wire the five request
    services from the container's already-wired building blocks and store both the
    container and the services on `app.state` for the dependency providers. On
    shutdown we `await shutdown()` to release every transport in reverse order.
    """
    container = AppContainer()
    await container.startup()

    # Construct the request services from the container's building blocks. The
    # container owns infrastructure singletons; the API owns these HTTP-facing
    # services (Rule 2) and is the only place that assembles them (Rule 3).
    app.state.container = container
    app.state.comparison_service = ComparisonService(
        comparison_pipeline=container.comparison_pipeline,
        session_store=container.session_store,
        bid_store=container.bid_store,
        project_store=container.project_store,
        job_store=container.job_store,
        comparison_orchestrator=container.comparison_orchestrator,
        unit_normalizer=container.unit_normalizer,
        cost_comparator=container.cost_comparator,
        feature_analyst=container.feature_analyst,
        context_compactor=container.context_compactor,
        data_query_agent=container.data_query_agent,
        session_summarizer=container.session_summarizer,
        decision_explainer=container.decision_explainer,
        telemetry=container.telemetry,
    )
    app.state.correction_service = CorrectionService(
        correction_store=container.correction_store,
        bid_store=container.bid_store,
        rule_store=container.rule_store,
        correction_distiller=container.correction_distiller,
        rejected_store=container.rejected_store,
        graph_client=container.graph_client,
        document_parser=container.document_parser,
        blob_service=container.blob_service,
        bid_processing_orchestrator=container.bid_processing_orchestrator,
    )
    app.state.manual_poll_service = ManualPollService(
        email_ingestion_orchestrator=container.email_ingestion_orchestrator,
        linked_account_store=container.linked_account_store,
    )
    app.state.pdf_proxy_service = PdfProxyService(
        blob_service=container.blob_service,
        bid_store=container.bid_store,
    )
    app.state.dashboard_service = DashboardService(
        bid_store=container.bid_store,
        project_store=container.project_store,
        job_store=container.job_store,
        session_store=container.session_store,
        rejected_store=container.rejected_store,
        dashboard_analyst=container.dashboard_analyst,
    )

    try:
        yield
    finally:
        await container.shutdown()


def create_app() -> FastAPI:
    """
    Build the FastAPI application with all middleware, handlers, and routers.

    A factory (rather than a module-level app) so tests can build isolated
    instances. Health probes are mounted without auth; every business router is
    protected by `get_current_user`, except the auth login/callback endpoints,
    which must be reachable before the user is authenticated to BidPilot.
    """
    app = FastAPI(title="BidPilot API", version="1.0.0", lifespan=lifespan)

    # The single Rule 8 logging site — registered before anything can raise.
    register_error_handlers(app)

    # Request tracing (best-effort) + CORS for the SPA dev origin.
    app.add_middleware(TelemetryMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health probes — no auth, no body work. Two paths for platform conventions
    # (Container Apps probes /healthz; load balancers often hit /health).
    @app.get("/health")
    async def health() -> dict:
        """Liveness probe — always cheap, never authenticated."""
        return {"status": "ok"}

    @app.get("/healthz")
    async def healthz() -> dict:
        """Alias of /health for platforms that probe /healthz."""
        return {"status": "ok"}

    # Auth login/callback are intentionally unauthenticated; /me inside the auth
    # router declares its own get_current_user dependency.
    app.include_router(auth_router.router, prefix="/api")

    # Every other router is protected: the user must be authenticated. The
    # dependency is attached at include time so individual handlers stay clean.
    auth_dep = [Depends(get_current_user)]
    app.include_router(bids_router.router, prefix="/api", dependencies=auth_dep)
    app.include_router(projects_router.router, prefix="/api", dependencies=auth_dep)
    app.include_router(comparison_router.router, prefix="/api", dependencies=auth_dep)
    app.include_router(corrections_router.router, prefix="/api", dependencies=auth_dep)
    app.include_router(
        email_accounts_router.router, prefix="/api", dependencies=auth_dep
    )
    app.include_router(rejected_router.router, prefix="/api", dependencies=auth_dep)
    app.include_router(stats_router.router, prefix="/api", dependencies=auth_dep)

    return app


# Module-level app for uvicorn (`uvicorn src.api.main:app`).
app = create_app()
