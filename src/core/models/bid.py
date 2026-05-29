"""IngestedBid — the central document of the system."""

import hashlib
from datetime import UTC, datetime

from pydantic import Field

from src.core.models.base import CamelModel

from src.core.enums import BidStatus, TradeCategory


class AgentResult(CamelModel):
    """
    Snapshot of one agent's structured output, stored on the bid for audit and
    for the UI's AgentResultPanel. Confidence drives review prioritization.
    """

    agent_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = ""
    raw_output: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IngestedBid(CamelModel):
    """
    A construction bid parsed from an email attachment and driven through the
    3-agent pipeline.

    The Cosmos document IS the orchestrator's memory (partition key `/id`): the
    pipeline is stateless and every checkpoint mutates `status` here before
    calling the next agent, so a crash resumes from the persisted status.
    """

    id: str
    # Provenance
    message_id: str
    linked_account_id: str
    sender_email: str
    email_subject: str
    received_at: datetime
    attachment_filename: str
    blob_path: str

    # Parsed content (kept so comparison agents can re-read without re-parsing)
    document_text: str = ""
    table_count: int = 0

    # Pipeline state
    status: BidStatus = BidStatus.PARSED
    retry_count: int = 0

    # Agent 1 output
    is_bid: bool | None = None

    # Agent 2 output
    matched_project_id: str | None = None
    address_from_bid: str | None = None
    normalized_address: str | None = None

    # Agent 3 output
    matched_job_id: str | None = None
    trade_category: TradeCategory | None = None
    secondary_trades: list[str] = Field(default_factory=list)
    vendor_name: str | None = None
    scope_summary: str | None = None

    # Extracted economics
    total_price: float | None = None

    # Per-agent audit snapshots, keyed by agent name
    agent_results: dict[str, AgentResult] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def make_id(message_id: str, filename: str) -> str:
        """
        Deterministic id from (messageId, filename). Re-processing the same
        attachment yields the same id, making ingestion idempotent and giving
        the stateless orchestrator a stable handle (build doc section 6.2).
        """
        digest = hashlib.sha256(f"{message_id}::{filename}".encode()).hexdigest()
        return digest[:32]

    def record_agent_result(self, result: AgentResult) -> None:
        """Attach an agent snapshot and bump the update timestamp."""
        self.agent_results[result.agent_name] = result
        self.touch()

    def advance_to(self, status: BidStatus) -> None:
        """Move to a new pipeline status (the checkpoint write)."""
        self.status = status
        self.touch()

    def touch(self) -> None:
        """Refresh the update timestamp on any mutation."""
        self.updated_at = datetime.now(UTC)

    @property
    def needs_review(self) -> bool:
        """
        True if any agent finished with low confidence. The dashboard surfaces
        these ahead of high-confidence bids.
        """
        return any(r.confidence < 0.7 for r in self.agent_results.values())
