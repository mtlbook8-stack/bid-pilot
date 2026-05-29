"""IProjectStore — persistence contract for ProjectSummary documents."""

from typing import Protocol

from src.core.models.project import ProjectSummary


class IProjectStore(Protocol):
    async def get(self, project_id: str) -> ProjectSummary | None: ...

    async def upsert(self, project: ProjectSummary) -> ProjectSummary: ...

    async def list_all(self) -> list[ProjectSummary]: ...

    async def find_by_normalized_address(
        self, normalized_address: str
    ) -> ProjectSummary | None:
        """Exact-match lookup used for code-first project matching (skips Agent 2)."""
        ...
