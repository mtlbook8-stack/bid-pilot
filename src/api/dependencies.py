"""
FastAPI dependency providers (build doc section 3 — dependencies.py).

WHY this exists: the composition root (`main.py`) builds the AppContainer and the
request services once and stashes them on `app.state`. Routers must not reach into
the container or instantiate anything (Rule 3) — they declare what they need via
`Depends(...)`. These thin provider functions read the already-wired singletons
off `request.app.state` and hand them to routes. `get_current_user` is re-exported
here so routers import all their dependencies from one place.

These are functions (the FastAPI DI convention) rather than methods; they hold no
logic beyond attribute access, so there is nothing to test or reuse elsewhere.
"""

from fastapi import Request

from src.api.middleware.auth import UserContext, get_current_user
from src.api.services.comparison_service import ComparisonService
from src.api.services.correction_service import CorrectionService
from src.api.services.dashboard_service import DashboardService
from src.api.services.manual_poll_service import ManualPollService
from src.api.services.pdf_proxy_service import PdfProxyService
from src.composition.container import AppContainer

# Re-export so routers depend on a single module for auth + service injection.
__all__ = [
    "UserContext",
    "get_current_user",
    "get_container",
    "get_comparison_service",
    "get_correction_service",
    "get_manual_poll_service",
    "get_pdf_proxy_service",
    "get_dashboard_service",
]


def get_container(request: Request) -> AppContainer:
    """Return the wired AppContainer stored on the app at startup."""
    return request.app.state.container


def get_comparison_service(request: Request) -> ComparisonService:
    """Return the singleton ComparisonService built in the lifespan."""
    return request.app.state.comparison_service


def get_correction_service(request: Request) -> CorrectionService:
    """Return the singleton CorrectionService built in the lifespan."""
    return request.app.state.correction_service


def get_manual_poll_service(request: Request) -> ManualPollService:
    """Return the singleton ManualPollService built in the lifespan."""
    return request.app.state.manual_poll_service


def get_pdf_proxy_service(request: Request) -> PdfProxyService:
    """Return the singleton PdfProxyService built in the lifespan."""
    return request.app.state.pdf_proxy_service


def get_dashboard_service(request: Request) -> DashboardService:
    """Return the singleton DashboardService built in the lifespan."""
    return request.app.state.dashboard_service
