"""ICorrectionStore — persistence contract for user corrections."""

from typing import Protocol

from src.core.models.correction import Correction


class ICorrectionStore(Protocol):
    """Partition key `/bidId`."""

    async def add(self, correction: Correction) -> Correction: ...

    async def list_for_bid(self, bid_id: str) -> list[Correction]: ...
