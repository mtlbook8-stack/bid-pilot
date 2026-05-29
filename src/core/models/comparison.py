"""
Comparison domain models — the heart of the product.

A ComparisonSession owns a ComparisonTable (cost rows + feature rows assembled
by Agents 5/6/7) and a conversation history that the orchestrator (Agent 4)
routes through specialist sub-agents. When history grows past the compaction
threshold, ContextCompactor (Agent 8) replaces the raw history with a
CompactedContext summary.
"""

from datetime import UTC, datetime

from pydantic import Field

from src.core.models.base import CamelModel

from src.core.enums import ChatRole, ComparisonPhase, DecisionStatus, Sentiment

# History longer than this triggers ContextCompactor (build doc 8.3).
COMPACTION_THRESHOLD = 20


class CostCell(CamelModel):
    """One vendor's value for a single cost row."""

    bid_id: str
    vendor_name: str
    value: float | None = None
    original_text: str = ""
    is_lowest: bool = False
    flags: list[str] = Field(default_factory=list)


class CostRow(CamelModel):
    """A normalized line item compared across vendors."""

    row_id: str
    label: str
    normalized_unit: str = ""
    cells: list[CostCell] = Field(default_factory=list)


class VendorTotal(CamelModel):
    """Roll-up total and scope completeness for one vendor."""

    bid_id: str
    vendor_name: str
    total_price: float
    items_included: int = 0
    items_missing: int = 0
    scope_caveats: list[str] = Field(default_factory=list)


class CostOutlier(CamelModel):
    """A line item where one vendor deviates sharply from the others."""

    row_label: str
    bid_id: str
    deviation_percentage: float
    direction: str  # "above" | "below"


class CostAnalysis(CamelModel):
    """Aggregate cost findings produced by CostComparator (Agent 6)."""

    lowest_total_bid_id: str | None = None
    highest_total_bid_id: str | None = None
    spread_percentage: float = 0.0
    significant_outliers: list[CostOutlier] = Field(default_factory=list)


class FeatureCell(CamelModel):
    """One vendor's value + sentiment for a single feature row."""

    bid_id: str
    vendor_name: str
    value: str = ""
    sentiment: Sentiment = Sentiment.NOT_SPECIFIED
    source_quote: str = ""


class FeatureRow(CamelModel):
    """A non-cost differentiator compared across vendors (Agent 7)."""

    row_id: str
    category: str
    label: str
    importance_rank: int = 99
    cells: list[FeatureCell] = Field(default_factory=list)


class RedFlag(CamelModel):
    """A vendor-specific risk surfaced by FeatureAnalyst."""

    bid_id: str
    vendor_name: str
    issue: str
    severity: str  # "high" | "medium" | "low"


class ComparisonTable(CamelModel):
    """
    The assembled comparison: cost rows (with totals + analysis) and feature
    rows (with red flags). This is what the frontend renders and what chat
    sub-agents read and mutate.
    """

    cost_rows: list[CostRow] = Field(default_factory=list)
    totals: list[VendorTotal] = Field(default_factory=list)
    cost_analysis: CostAnalysis = Field(default_factory=CostAnalysis)
    feature_rows: list[FeatureRow] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    feature_summary: str = ""


class ChatMessage(CamelModel):
    """One turn in the comparison conversation."""

    role: ChatRole
    content: str
    # Which specialist handled an assistant turn (for the UI + telemetry).
    handled_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CompactedContext(CamelModel):
    """
    Structured replacement for raw history once it exceeds the threshold.
    Downstream agents receive only the sections they need.
    """

    decision_status: DecisionStatus = DecisionStatus.UNDECIDED
    leading_vendor: str | None = None
    reasoning: str | None = None
    conclusions: list[dict] = Field(default_factory=list)
    table_edits: list[dict] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    data_corrections: list[str] = Field(default_factory=list)
    compressed_from_message_count: int = 0


class ComparisonSession(CamelModel):
    """
    A live comparison of the bids on one job. Partition key `/projectId`.

    Holds the assembled table, the running conversation, and (after compaction)
    the structured context summary that stands in for old turns.
    """

    id: str
    project_id: str
    job_id: str
    project_name: str
    job_name: str
    trade_category: str
    bid_ids: list[str] = Field(default_factory=list)
    vendor_names: list[str] = Field(default_factory=list)

    phase: ComparisonPhase = ComparisonPhase.NORMALIZING
    table: ComparisonTable | None = None
    conversation_history: list[ChatMessage] = Field(default_factory=list)
    compacted_context: CompactedContext | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def add_message(self, message: ChatMessage) -> None:
        """Append a turn and refresh the timestamp."""
        self.conversation_history.append(message)
        self.updated_at = datetime.now(UTC)

    @property
    def needs_compaction(self) -> bool:
        """True once raw history exceeds the compaction threshold."""
        return len(self.conversation_history) > COMPACTION_THRESHOLD

    def recent_messages(self, n: int = 3) -> list[ChatMessage]:
        """Last `n` turns, for the orchestrator's routing context."""
        return self.conversation_history[-n:]
