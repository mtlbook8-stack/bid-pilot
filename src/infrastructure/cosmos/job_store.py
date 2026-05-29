"""CosmosJobStore — IJobStore backed by the `jobs` container (`/projectId` PK)."""

from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.core.errors.app_error import AppError
from src.core.models.job import JobSummary


class CosmosJobStore:
    """
    Cosmos-backed persistence for `JobSummary` (implements IJobStore).

    Partition key is `/projectId`, so `get` requires the owning project id to form
    a point-read, and `list_for_project` is a cheap single-partition query rather
    than a fan-out. Container injected (Rule 3); SDK calls wrapped (Rule 8); no
    logging in the store.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the already-resolved `jobs` container proxy (Rule 3)."""
        self._container = container

    async def get(self, job_id: str, project_id: str) -> JobSummary | None:
        """
        Point-read a job. `project_id` is the partition key (not redundant): a
        point-read needs both the item id and the partition key. None when absent.
        """
        try:
            item = await self._container.read_item(
                item=job_id, partition_key=project_id
            )
            return JobSummary.model_validate(item)
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            raise AppError(
                code="STORE_JOB_GET",
                message="Failed to read job",
                context={"job_id": job_id, "project_id": project_id},
                cause=e,
            )

    async def upsert(self, job: JobSummary) -> JobSummary:
        """Insert or replace a job."""
        try:
            body = job.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return JobSummary.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_JOB_UPSERT",
                message="Failed to upsert job",
                context={"job_id": job.id, "project_id": job.project_id},
                cause=e,
            )

    async def list_for_project(self, project_id: str) -> list[JobSummary]:
        """
        All jobs for a project. Single-partition query (partitioned by
        `/projectId`), so it scopes to one physical partition and is fast/cheap.
        """
        query = "SELECT * FROM c WHERE c.project_id = @pid"
        params = [{"name": "@pid", "value": project_id}]
        try:
            items = self._container.query_items(
                query=query,
                parameters=params,
                partition_key=project_id,
            )
            return [JobSummary.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_JOB_LIST_FOR_PROJECT",
                message="Failed to list jobs for project",
                context={"project_id": project_id},
                cause=e,
            )
