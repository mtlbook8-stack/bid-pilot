"""
/api/stats — dashboard aggregates and natural-language portfolio Q&A.

Thin router (Rule 2): GET / returns the code-computed snapshot; POST /ask routes
a question to the DashboardAnalyst (Agent 12) via the service. All logic lives in
DashboardService.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.dependencies import (
    UserContext,
    get_current_user,
    get_dashboard_service,
)
from src.api.services.dashboard_service import DashboardService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])


class AskRequest(BaseModel):
    """Body for POST /stats/ask — a single natural-language question."""

    question: str


@router.get("")
async def get_stats(
    dashboard: DashboardService = Depends(get_dashboard_service),
    user: UserContext = Depends(get_current_user),
) -> dict:
    """Return the dashboard portfolio snapshot (counts + recent bids)."""
    return await dashboard.get_stats()


@router.post("/ask")
async def ask(
    body: AskRequest,
    dashboard: DashboardService = Depends(get_dashboard_service),
    user: UserContext = Depends(get_current_user),
) -> dict:
    """Answer a portfolio question; returns the analyst's structured dict."""
    return await dashboard.ask(body.question)
