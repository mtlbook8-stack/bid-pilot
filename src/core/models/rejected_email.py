"""RejectedEmailMetadata — lightweight record of a non-bid email."""

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from src.core.enums import RejectionCategory


class RejectedEmailMetadata(BaseModel):
    """
    Just enough to list a rejected email and re-fetch it from Graph on restore.

    Deliberately stores NO attachment bytes or document text (build doc 6.4):
    on restore, code pulls the full email from Graph using `message_id` and
    re-ingests it, skipping Agent 1.
    """

    id: str
    message_id: str
    linked_account_id: str
    sender_email: str
    subject: str
    received_at: datetime
    rejection_reason: RejectionCategory
    agent_confidence: float = Field(..., ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def make_id(message_id: str) -> str:
        """Deterministic id from the message id, for idempotent rejection writes."""
        return hashlib.sha256(message_id.encode()).hexdigest()[:32]
