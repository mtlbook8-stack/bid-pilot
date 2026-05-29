"""CosmosProjectStore — IProjectStore backed by the `projects` container (`/id`)."""

from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.core.errors.app_error import AppError
from src.core.models.project import ProjectSummary


class CosmosProjectStore:
    """
    Cosmos-backed persistence for `ProjectSummary` (implements IProjectStore).

    Partition key `/id`, so get/upsert are point operations. `list_all` and
    `find_by_normalized_address` are cross-partition queries; the latter powers
    the code-first matching path that lets a bid skip Agent 2 when its geocoded
    address already exists (build doc 8.2). Container injected (Rule 3); SDK calls
    wrapped and re-raised (Rule 8); no logging in the store.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the already-resolved `projects` container proxy (Rule 3)."""
        self._container = container

    async def get(self, project_id: str) -> ProjectSummary | None:
        """Point-read a project; None when it does not exist (normal outcome)."""
        try:
            item = await self._container.read_item(
                item=project_id, partition_key=project_id
            )
            return ProjectSummary.model_validate(item)
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            raise AppError(
                code="STORE_PROJECT_GET",
                message="Failed to read project",
                context={"project_id": project_id},
                cause=e,
            )

    async def upsert(self, project: ProjectSummary) -> ProjectSummary:
        """Insert or replace a project."""
        try:
            body = project.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return ProjectSummary.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_PROJECT_UPSERT",
                message="Failed to upsert project",
                context={"project_id": project.id},
                cause=e,
            )

    async def list_all(self) -> list[ProjectSummary]:
        """Every project (cross-partition)."""
        try:
            items = self._container.query_items(query="SELECT * FROM c")
            return [ProjectSummary.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_PROJECT_LIST_ALL",
                message="Failed to list projects",
                context={},
                cause=e,
            )

    async def find_by_normalized_address(
        self, normalized_address: str
    ) -> ProjectSummary | None:
        """
        Return the first project whose canonical address matches exactly, or None.

        Used before Agent 2 runs: an exact normalized-address hit assigns the
        project deterministically and skips the LLM match entirely. First-match is
        sufficient because the matcher stores `normalized_address` per project to
        prevent duplicates from forming in the first place.
        """
        query = "SELECT * FROM c WHERE c.normalizedAddress = @addr"
        params = [{"name": "@addr", "value": normalized_address}]
        try:
            items = self._container.query_items(query=query, parameters=params)
            async for item in items:
                # Return on the first hit — there should be at most one.
                return ProjectSummary.model_validate(item)
            return None
        except Exception as e:
            raise AppError(
                code="STORE_PROJECT_FIND_BY_ADDRESS",
                message="Failed to query project by normalized address",
                context={"normalized_address": normalized_address},
                cause=e,
            )
