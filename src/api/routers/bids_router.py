"""
/api/bids — list bids, fetch one, and proxy a bid's original PDF.

Thin router (Rule 2): each handler parses HTTP input, calls an injected store or
service, and formats output. The store returns camelCase-serializing models;
returning them lets FastAPI emit camelCase via `by_alias`. The PDF endpoint
streams bytes through the PdfProxyService so storage stays server-side (I1).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.api.dependencies import (
    UserContext,
    get_container,
    get_current_user,
    get_pdf_proxy_service,
)
from src.api.services.pdf_proxy_service import PdfProxyService
from src.composition.container import AppContainer
from src.core.enums import BidStatus
from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bids", tags=["bids"])


@router.get("")
async def list_bids(
    project_id: Optional[str] = Query(None, alias="projectId"),
    job_id: Optional[str] = Query(None, alias="jobId"),
    status: Optional[str] = Query(None),
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
) -> list:
    """
    List bids, optionally filtered by project, job, or status.

    Filters are mutually-narrowing query params; the most specific provided wins
    (job > project > status > all) so the store does the cheapest applicable
    query. An invalid status value is rejected as a client error (AppError ->
    handled), keeping the router free of business logic.
    """
    store = container.bid_store
    if job_id is not None:
        bids = await store.list_for_job(job_id)
    elif project_id is not None:
        bids = await store.list_for_project(project_id)
    elif status is not None:
        try:
            parsed = BidStatus(status)
        except ValueError as exc:
            raise AppError(
                code="BIDS_BAD_STATUS",
                message="Unknown bid status filter",
                context={"status": status},
                cause=exc,
            )
        bids = await store.list_by_status(parsed)
    else:
        bids = await store.list_all()
    return bids


@router.get("/{bid_id}")
async def get_bid(
    bid_id: str,
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
):
    """Return one bid by id, or a 404-class AppError if it does not exist."""
    bid = await container.bid_store.get(bid_id)
    if bid is None:
        raise AppError(
            code="BIDS_NOT_FOUND",
            message="No bid found for the requested id",
            context={"bid_id": bid_id},
        )
    return bid


@router.get("/{bid_id}/pdf")
async def get_bid_pdf(
    bid_id: str,
    pdf_proxy: PdfProxyService = Depends(get_pdf_proxy_service),
    user: UserContext = Depends(get_current_user),
) -> StreamingResponse:
    """
    Stream the bid's original PDF from Blob to the browser (I1).

    The service resolves the blob and returns `(content_type, byte_iterator)`;
    we wrap it in a StreamingResponse so the bytes flow chunk-by-chunk without
    buffering the whole file in the API.
    """
    content_type, stream = await pdf_proxy.stream(bid_id)
    return StreamingResponse(stream, media_type=content_type)
