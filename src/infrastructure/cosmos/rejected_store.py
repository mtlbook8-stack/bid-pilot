"""CosmosRejectedEmailStore — IRejectedEmailStore backed by `rejected-emails`."""

from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.core.errors.app_error import AppError
from src.core.models.rejected_email import RejectedEmailMetadata


class CosmosRejectedEmailStore:
    """
    Cosmos-backed persistence for `RejectedEmailMetadata` (implements
    IRejectedEmailStore).

    Partition key is `/id` (build doc 6.1, 6.4): records are lightweight metadata
    only — no attachment bytes or document text — so get/add/delete are O(1)
    point operations keyed on the deterministic message-id hash. `delete` is used
    by the restore flow: once the email is re-ingested through the pipeline, its
    rejected record is removed. Container injected (Rule 3); SDK calls wrapped and
    re-raised (Rule 8); the store never logs.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the already-resolved `rejected-emails` container proxy (Rule 3)."""
        self._container = container

    async def add(self, rejected: RejectedEmailMetadata) -> RejectedEmailMetadata:
        """
        Persist a rejection record. Uses upsert (idempotent on the deterministic
        id derived from the message id) so re-processing the same non-bid email
        does not raise a conflict.
        """
        try:
            body = rejected.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return RejectedEmailMetadata.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_REJECTED_ADD",
                message="Failed to add rejected-email metadata",
                context={"rejected_id": rejected.id},
                cause=e,
            )

    async def get(self, rejected_id: str) -> RejectedEmailMetadata | None:
        """Point-read a rejection record; None when absent (normal outcome)."""
        try:
            item = await self._container.read_item(
                item=rejected_id, partition_key=rejected_id
            )
            return RejectedEmailMetadata.model_validate(item)
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            raise AppError(
                code="STORE_REJECTED_GET",
                message="Failed to read rejected-email metadata",
                context={"rejected_id": rejected_id},
                cause=e,
            )

    async def list_all(self) -> list[RejectedEmailMetadata]:
        """Every rejected-email record (cross-partition) for the Rejected page."""
        try:
            items = self._container.query_items(query="SELECT * FROM c")
            return [RejectedEmailMetadata.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_REJECTED_LIST_ALL",
                message="Failed to list rejected-email metadata",
                context={},
                cause=e,
            )

    async def delete(self, rejected_id: str) -> None:
        """
        Remove a rejection record (the restore flow, after re-ingestion).

        A missing record is treated as success: restore is idempotent, so
        deleting an already-deleted record should not surface an error.
        """
        try:
            await self._container.delete_item(
                item=rejected_id, partition_key=rejected_id
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            raise AppError(
                code="STORE_REJECTED_DELETE",
                message="Failed to delete rejected-email metadata",
                context={"rejected_id": rejected_id},
                cause=e,
            )
