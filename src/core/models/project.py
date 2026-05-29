"""ProjectSummary — a construction project bids are matched against."""

from datetime import UTC, datetime

from pydantic import Field

from src.core.models.base import CamelModel


class ProjectSummary(CamelModel):
    """
    A project groups jobs (trade scopes) and the bids competing on them.

    `normalized_address` is the canonical Azure Maps address used for code-first
    matching: a new bid whose geocoded address equals this skips Agent 2
    entirely (build doc section 8.2).
    """

    id: str
    name: str
    address: str | None = None
    normalized_address: str | None = None
    client_name: str | None = None
    client_contact: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)
