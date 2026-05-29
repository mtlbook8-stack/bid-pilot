"""IRejectedEmailStore — persistence contract for rejected-email metadata."""

from typing import Protocol

from src.core.models.rejected_email import RejectedEmailMetadata


class IRejectedEmailStore(Protocol):
    """Partition key `/id`. Lightweight records only (no attachments)."""

    async def add(self, rejected: RejectedEmailMetadata) -> RejectedEmailMetadata: ...

    async def get(self, rejected_id: str) -> RejectedEmailMetadata | None: ...

    async def list_all(self) -> list[RejectedEmailMetadata]: ...

    async def delete(self, rejected_id: str) -> None: ...
