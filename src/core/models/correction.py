"""Correction + LearnedRule — the real-time learning loop (Agent 10)."""

from datetime import UTC, datetime

from pydantic import Field

from src.core.models.base import CamelModel

from src.core.enums import CorrectionType


class Correction(CamelModel):
    """
    A user override of an agent decision. Partition key `/bidId`. Saving one
    snapshots the original agent output for audit and triggers the
    CorrectionDistiller to produce a reusable rule.
    """

    id: str
    bid_id: str
    correction_type: CorrectionType
    agent_name: str
    original_value: dict = Field(default_factory=dict)
    corrected_value: str
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LearnedRule(CamelModel):
    """
    A distilled, reusable instruction injected into a target agent's prompt via
    the `{learned_rules}` placeholder. Partition key `/agentName` so a single
    point-query fetches all rules for an agent before it runs.
    """

    id: str
    agent_name: str
    rule_text: str
    pattern_identified: str = ""
    specificity: str = "general"
    source_correction_id: str | None = None
    conflicts_with_existing: str | None = None
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def as_prompt_line(self) -> str:
        """Render as a single bullet for the LEARNED RULES prompt section."""
        return f"- {self.rule_text}"
