"""IJobStore — persistence contract for JobSummary documents."""

from typing import Protocol

from src.core.models.job import JobSummary


class IJobStore(Protocol):
    """Partition key `/projectId`, so list_for_project is single-partition."""

    async def get(self, job_id: str, project_id: str) -> JobSummary | None: ...

    async def upsert(self, job: JobSummary) -> JobSummary: ...

    async def list_for_project(self, project_id: str) -> list[JobSummary]: ...
