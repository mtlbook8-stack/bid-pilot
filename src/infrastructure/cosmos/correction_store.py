"""CosmosCorrectionStore — ICorrectionStore backed by the `corrections` container."""

from azure.cosmos.aio import ContainerProxy

from src.core.errors.app_error import AppError
from src.core.models.correction import Correction


class CosmosCorrectionStore:
    """
    Cosmos-backed persistence for `Correction` (implements ICorrectionStore).

    Partition key is `/bidId` (build doc 6.1): corrections are always read in the
    context of the bid they amend, so partitioning by bid id makes
    `list_for_bid` a single-partition query and keeps a bid's correction history
    physically co-located. Container injected (Rule 3); every SDK call wrapped and
    re-raised as an AppError (Rule 8); the store never logs.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the already-resolved `corrections` container proxy (Rule 3)."""
        self._container = container

    async def add(self, correction: Correction) -> Correction:
        """
        Persist a new correction. Uses upsert (idempotent on the deterministic id)
        rather than create so a retried write does not raise a conflict — the
        distiller fires off the same correction at-least-once.
        """
        try:
            body = correction.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return Correction.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_CORRECTION_ADD",
                message="Failed to add correction",
                context={"correction_id": correction.id, "bid_id": correction.bid_id},
                cause=e,
            )

    async def list_for_bid(self, bid_id: str) -> list[Correction]:
        """
        All corrections recorded against a bid. Single-partition query on
        `/bidId`, so it scopes to one physical partition and is fast and cheap.
        """
        query = "SELECT * FROM c WHERE c.bidId = @bid"
        params = [{"name": "@bid", "value": bid_id}]
        try:
            items = self._container.query_items(
                query=query,
                parameters=params,
                partition_key=bid_id,
            )
            return [Correction.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_CORRECTION_LIST_FOR_BID",
                message="Failed to list corrections for bid",
                context={"bid_id": bid_id},
                cause=e,
            )
