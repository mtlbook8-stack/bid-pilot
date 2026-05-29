"""
PdfProxyService — streams an original bid PDF from Blob to the browser (I1).

WHY this exists: the frontend must never hold a Blob SAS or talk to storage
directly. Instead the API proxies the bytes: the router asks this service for the
content type + an async byte iterator, and streams it back. This keeps storage
credentials server-side and lets the API enforce auth on PDF access.

One job (Rule 2): resolve a bid to its blob and hand back a stream. All
collaborators are injected (Rule 3); store/blob failures are wrapped as AppError
(Rules 7, 8).
"""

from typing import AsyncIterator

from src.core.errors.app_error import AppError
from src.core.interfaces.bid_store import IBidStore
from src.core.interfaces.blob_service import IBlobService


class PdfProxyService:
    """Resolves a bid id to its stored PDF and returns a streaming reader."""

    def __init__(self, blob_service: IBlobService, bid_store: IBidStore) -> None:
        # Pure DI (Rule 3): the container passes the wired blob + bid stores.
        self._blob_service = blob_service
        self._bid_store = bid_store

    async def stream(self, bid_id: str) -> tuple[str, AsyncIterator[bytes]]:
        """
        Return `(content_type, byte_iterator)` for the bid's original PDF.

        Loads the bid (point-read), then opens a streaming reader over its
        `blob_path`. The content type is fixed to application/pdf — the bids
        container only stores parsed PDF attachments. A missing bid is a hard
        404-class error wrapped as AppError so the top-level handler logs it once.
        """
        try:
            bid = await self._bid_store.get(bid_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="PDF_PROXY_LOAD_BID",
                message="Failed to load bid for PDF streaming",
                context={"bid_id": bid_id},
                cause=exc,
            )
        if bid is None:
            raise AppError(
                code="PDF_PROXY_BID_MISSING",
                message="No bid found for the requested id",
                context={"bid_id": bid_id},
            )

        # The blob service returns an async iterator; opening it does not buffer
        # the whole file, so large PDFs stream chunk-by-chunk to the client.
        stream = self._blob_service.stream(bid.blob_path)
        return "application/pdf", stream
