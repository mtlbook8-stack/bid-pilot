"""CosmosBidStore — IBidStore backed by the `bids` container (`/id` PK)."""

from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.core.enums import BidStatus
from src.core.errors.app_error import AppError
from src.core.models.bid import IngestedBid


class CosmosBidStore:
    """
    Cosmos-backed persistence for `IngestedBid` (implements IBidStore).

    The `/id` partition key (build doc 6.2) makes `get`/`upsert` O(1) point
    operations: read/upsert always pass `partition_key=bid_id`. The list methods
    are cross-partition queries — cheap at this scale (hundreds to low thousands
    of bids). Per Rule 3 the container proxy is injected; per Rule 8 every SDK
    call is wrapped and re-raised as an AppError, and the store never logs.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the already-resolved `bids` container proxy (Rule 3)."""
        self._container = container

    async def get(self, bid_id: str) -> IngestedBid | None:
        """
        Point-read a bid by id. Returns None when the document does not exist —
        a missing bid is a normal control-flow outcome, not an error (the
        idempotent pipeline checks for existence routinely).
        """
        try:
            item = await self._container.read_item(item=bid_id, partition_key=bid_id)
            return IngestedBid.model_validate(item)
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            raise AppError(
                code="STORE_BID_GET",
                message="Failed to read bid",
                context={"bid_id": bid_id},
                cause=e,
            )

    async def upsert(self, bid: IngestedBid) -> IngestedBid:
        """
        Insert or replace a bid. Serializes with `by_alias` + JSON mode so dates
        and enums become Cosmos-safe primitives and field names match the query
        references used by the list methods.
        """
        try:
            body = bid.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return IngestedBid.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_BID_UPSERT",
                message="Failed to upsert bid",
                context={"bid_id": bid.id},
                cause=e,
            )

    async def list_for_project(self, project_id: str) -> list[IngestedBid]:
        """All bids matched to a project (cross-partition query on /id)."""
        query = "SELECT * FROM c WHERE c.matched_project_id = @pid"
        params = [{"name": "@pid", "value": project_id}]
        return await self._query(
            query, params, code="STORE_BID_LIST_FOR_PROJECT",
            context={"project_id": project_id},
        )

    async def list_for_job(self, job_id: str) -> list[IngestedBid]:
        """All bids matched to a job (cross-partition query on /id)."""
        query = "SELECT * FROM c WHERE c.matched_job_id = @jid"
        params = [{"name": "@jid", "value": job_id}]
        return await self._query(
            query, params, code="STORE_BID_LIST_FOR_JOB",
            context={"job_id": job_id},
        )

    async def list_by_status(self, status: BidStatus) -> list[IngestedBid]:
        """All bids in a given pipeline status (used by the retry trigger)."""
        query = "SELECT * FROM c WHERE c.status = @status"
        params = [{"name": "@status", "value": status.value}]
        return await self._query(
            query, params, code="STORE_BID_LIST_BY_STATUS",
            context={"status": status.value},
        )

    async def list_all(self) -> list[IngestedBid]:
        """Every bid (the All Bids page)."""
        return await self._query(
            "SELECT * FROM c", [], code="STORE_BID_LIST_ALL", context={},
        )

    async def _query(
        self, query: str, params: list[dict], code: str, context: dict
    ) -> list[IngestedBid]:
        """
        Shared cross-partition query runner (Rule 5 — one place for the loop).

        Wraps the async iteration so any individual list method only declares its
        SQL, its parameters, and its unique error code/context.
        """
        try:
            items = self._container.query_items(query=query, parameters=params)
            return [IngestedBid.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(code=code, message="Failed to query bids", context=context, cause=e)
