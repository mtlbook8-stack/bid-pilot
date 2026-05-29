"""JobSummary — a single trade scope within a project."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from src.core.enums import TradeCategory


class JobSummary(BaseModel):
    """
    A job is one trade scope on a project. Multiple bids for the same trade on
    the same project compete on the same job, which is the unit a comparison
    session operates over.

    Partition key is `/projectId`, so listing a project's jobs is a single-
    partition query.
    """

    id: str
    project_id: str
    trade_category: TradeCategory
    job_name: str
    bid_ids: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def add_bid(self, bid_id: str) -> None:
        """Attach a bid to this job, de-duplicating on the deterministic id."""
        if bid_id not in self.bid_ids:
            self.bid_ids.append(bid_id)
            self.updated_at = datetime.now(UTC)

    @property
    def bid_count(self) -> int:
        return len(self.bid_ids)
