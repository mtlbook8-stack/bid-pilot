"""
/api/corrections — apply a user correction to a bid (build doc 8.4).

Thin router (Rule 2): the correction type is a path segment validated against the
CorrectionType enum; the body carries the corrected value + reason. All logic
(snapshot, persist, update bid, distill rule) lives in CorrectionService.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.api.dependencies import (
    UserContext,
    get_correction_service,
    get_current_user,
)
from src.api.services.correction_service import CorrectionService
from src.core.enums import CorrectionType
from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/corrections", tags=["corrections"])


class CorrectionRequest(BaseModel):
    """Body for a correction — the new value and the user's reason."""

    corrected_value: str = Field(alias="correctedValue")
    reason: str = ""

    model_config = {"populate_by_name": True}


@router.post("/{bid_id}/{correction_type}")
async def apply_correction(
    bid_id: str,
    correction_type: str,
    body: CorrectionRequest,
    corrections: CorrectionService = Depends(get_correction_service),
    user: UserContext = Depends(get_current_user),
):
    """
    Apply a project/trade/validation correction to a bid (build doc 8.4).

    Validates the correction type against the enum (an unknown type is a client
    error), then delegates to the service which persists the correction, updates
    the bid, and triggers the CorrectionDistiller. Returns the updated bid.
    """
    try:
        parsed_type = CorrectionType(correction_type)
    except ValueError as exc:
        raise AppError(
            code="CORRECTIONS_BAD_TYPE",
            message="Unknown correction type",
            context={"correction_type": correction_type},
            cause=exc,
        )
    return await corrections.apply_correction(
        bid_id=bid_id,
        correction_type=parsed_type,
        corrected_value=body.corrected_value,
        reason=body.reason,
        user_id=user.user_id,
    )
