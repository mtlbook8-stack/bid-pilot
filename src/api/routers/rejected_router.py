"""
/api/rejected — list rejected emails and restore one back into the pipeline.

Thin router (Rule 2): GET / lists the lightweight rejected-email metadata; POST
/{id}/restore delegates the full re-ingestion flow (build doc 8.5) to the
CorrectionService.
"""

import logging

from fastapi import APIRouter, Depends

from src.api.dependencies import (
    UserContext,
    get_container,
    get_correction_service,
    get_current_user,
)
from src.api.services.correction_service import CorrectionService
from src.composition.container import AppContainer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rejected", tags=["rejected"])


@router.get("")
async def list_rejected(
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
) -> list:
    """List rejected-email metadata (no attachments/text — build doc 6.4)."""
    return await container.rejected_store.list_all()


@router.post("/{rejected_id}/restore")
async def restore_rejected(
    rejected_id: str,
    corrections: CorrectionService = Depends(get_correction_service),
    user: UserContext = Depends(get_current_user),
):
    """
    Restore a wrongly-rejected email (build doc 8.5).

    The service re-fetches the email from Graph, re-ingests it as a VALIDATED bid
    (skipping Agent 1), records a validation correction, distills a learning rule,
    and deletes the rejected metadata. Returns the restored bid.
    """
    return await corrections.restore_rejected(rejected_id)
