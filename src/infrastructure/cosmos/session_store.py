"""CosmosComparisonSessionStore — IComparisonSessionStore backed by `comparison-sessions`."""

from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.core.errors.app_error import AppError
from src.core.models.comparison import ComparisonSession


class CosmosComparisonSessionStore:
    """
    Cosmos-backed persistence for `ComparisonSession` (implements
    IComparisonSessionStore).

    Partition key is `/projectId` (build doc 6.1): a session is always opened in
    the context of a project, so partitioning by project id makes `get` a
    point-read (needs both session id and project id) and `list_for_project` a
    single-partition query. The session document carries the full comparison
    table and conversation history, so it is read and re-upserted on every chat
    turn — keeping these operations partition-scoped matters for the core
    product's responsiveness. Container injected (Rule 3); SDK calls wrapped and
    re-raised (Rule 8); the store never logs.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the resolved `comparison-sessions` container proxy (Rule 3)."""
        self._container = container

    async def get(
        self, session_id: str, project_id: str
    ) -> ComparisonSession | None:
        """
        Point-read a session. `project_id` is the partition key (required for a
        point-read alongside the item id). None when the session does not exist.
        """
        try:
            item = await self._container.read_item(
                item=session_id, partition_key=project_id
            )
            return ComparisonSession.model_validate(item)
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            raise AppError(
                code="STORE_SESSION_GET",
                message="Failed to read comparison session",
                context={"session_id": session_id, "project_id": project_id},
                cause=e,
            )

    async def upsert(self, session: ComparisonSession) -> ComparisonSession:
        """Insert or replace a session (every chat turn re-upserts the document)."""
        try:
            body = session.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return ComparisonSession.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_SESSION_UPSERT",
                message="Failed to upsert comparison session",
                context={"session_id": session.id, "project_id": session.project_id},
                cause=e,
            )

    async def list_for_project(self, project_id: str) -> list[ComparisonSession]:
        """
        All comparison sessions for a project. Single-partition query on
        `/projectId`, so it scopes to one physical partition and is fast/cheap.
        """
        query = "SELECT * FROM c WHERE c.project_id = @pid"
        params = [{"name": "@pid", "value": project_id}]
        try:
            items = self._container.query_items(
                query=query,
                parameters=params,
                partition_key=project_id,
            )
            return [ComparisonSession.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_SESSION_LIST_FOR_PROJECT",
                message="Failed to list comparison sessions for project",
                context={"project_id": project_id},
                cause=e,
            )

    async def list_all(self) -> list[ComparisonSession]:
        """Every comparison session (cross-partition)."""
        try:
            items = self._container.query_items(query="SELECT * FROM c")
            return [ComparisonSession.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_SESSION_LIST_ALL",
                message="Failed to list comparison sessions",
                context={},
                cause=e,
            )
