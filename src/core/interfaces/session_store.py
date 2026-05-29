"""IComparisonSessionStore — persistence contract for comparison sessions."""

from typing import Protocol

from src.core.models.comparison import ComparisonSession


class IComparisonSessionStore(Protocol):
    """Partition key `/projectId`."""

    async def get(self, session_id: str, project_id: str) -> ComparisonSession | None: ...

    async def upsert(self, session: ComparisonSession) -> ComparisonSession: ...

    async def list_for_project(self, project_id: str) -> list[ComparisonSession]: ...

    async def list_all(self) -> list[ComparisonSession]: ...
