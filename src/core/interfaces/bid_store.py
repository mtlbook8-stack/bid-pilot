"""IBidStore — persistence contract for IngestedBid documents."""

from typing import Protocol

from src.core.enums import BidStatus
from src.core.models.bid import IngestedBid


class IBidStore(Protocol):
    """
    Storage operations for bids. The `/id` partition key makes get/upsert
    O(1) point operations; `list_for_project` and `list_by_status` are
    cross-partition queries (cheap at this scale — build doc 6.2).
    """

    async def get(self, bid_id: str) -> IngestedBid | None: ...

    async def upsert(self, bid: IngestedBid) -> IngestedBid: ...

    async def list_for_project(self, project_id: str) -> list[IngestedBid]: ...

    async def list_for_job(self, job_id: str) -> list[IngestedBid]: ...

    async def list_by_status(self, status: BidStatus) -> list[IngestedBid]: ...

    async def list_all(self) -> list[IngestedBid]: ...
