"""
EmailIngestionOrchestrator — turns a linked mailbox's new mail into bids.

WHY this class exists (build doc section 8.1): it is the plumbing that feeds the
comparison product. For one linked account it fetches mail newer than the
account's watermark, applies the cheap code-only EmailFilter, and for every
email that clears the filter it uploads each attachment to Blob, parses it with
Document Intelligence, and writes an IngestedBid with status "Parsed" — the
trigger state the bid-processing change feed reacts to. It deliberately does NOT
run any AI: bid/non-bid classification is Agent 1's job, downstream. An email
that fails the filter is skipped silently — it is not a rejected BID (rejection
only happens at Agent 1), it is just irrelevant mail.

Pure orchestration (Rule 2): all collaborators are injected interfaces (Rule 3),
nothing is constructed here, every external call is wrapped and re-raised as an
AppError with an INGEST_* code (Rules 7, 8). The orchestrator does NOT advance
the account watermark — the calling trigger owns that — but it returns the
latest received_at it saw so the caller can advance `last_processed_at` safely.
"""

import logging
from datetime import datetime
from typing import Awaitable, Callable

from src.api.config import Settings
from src.core.enums import BidStatus
from src.core.errors.app_error import AppError
from src.core.interfaces.blob_service import IBlobService
from src.core.interfaces.bid_store import IBidStore
from src.core.interfaces.document_parser import IDocumentParser
from src.core.interfaces.graph_client import EmailAttachment, GraphEmail, IGraphMailClient
from src.core.interfaces.rejected_store import IRejectedEmailStore
from src.core.models.bid import IngestedBid
from src.core.models.linked_account import LinkedAccount
from src.infrastructure.documents.email_filter import EmailFilter

logger = logging.getLogger(__name__)

# Type of the optional async SSE progress callback. It receives the section-8.1
# event dicts (started / emails_found / processing / bid_saved / completed). It
# is awaited but its result is ignored — progress reporting must never alter the
# ingestion outcome.
ProgressCallback = Callable[[dict], Awaitable[None]]


class EmailIngestionOrchestrator:
    """
    Ingests one linked account's new emails into Parsed bids (build doc 8.1).

    Stateless: it holds only its injected collaborators. The unit of work is a
    single account; the timer/manual-poll trigger calls `process_account` per
    account and persists the watermark using the returned value.
    """

    def __init__(
        self,
        graph_client: IGraphMailClient,
        email_filter: EmailFilter,
        blob_service: IBlobService,
        document_parser: IDocumentParser,
        bid_store: IBidStore,
        rejected_store: IRejectedEmailStore,
        settings: Settings,
    ) -> None:
        # Pure DI (Rule 3). The rejected_store is held for symmetry with the
        # ingestion contract even though Tier-1 ingestion never rejects a bid
        # (rejection is Agent 1's responsibility, downstream).
        self._graph_client = graph_client
        self._email_filter = email_filter
        self._blob_service = blob_service
        self._document_parser = document_parser
        self._bid_store = bid_store
        self._rejected_store = rejected_store
        self._settings = settings

    async def process_account(
        self,
        account: LinkedAccount,
        progress: ProgressCallback | None = None,
    ) -> dict:
        """
        Fetch and ingest new mail for one account, emitting optional SSE progress.

        Flow: fetch new emails since the watermark -> for each, apply the code-only
        filter -> for each attachment of a passing email, upload to Blob, parse,
        and upsert an IngestedBid in status Parsed. Emails that fail the filter are
        skipped silently (irrelevant mail, not rejected bids).

        Returns {"bids_created", "emails_processed", "latest_received_at"}. The
        watermark is NOT advanced here — the caller advances `last_processed_at`
        using `latest_received_at` after a successful poll, so a crash mid-poll
        does not skip unprocessed mail.
        """
        emails = await self._fetch(account)

        await self._emit(progress, {"event": "started", "account": account.email_address})
        await self._emit(progress, {"event": "emails_found", "count": len(emails)})

        bids_created = 0
        emails_processed = 0
        latest_received_at: datetime | None = account.last_processed_at

        for index, email in enumerate(emails, start=1):
            emails_processed += 1
            # Track the high-water mark across ALL fetched emails (even filtered
            # ones) so the caller's watermark advances past mail we have seen and
            # intentionally discarded, preventing endless re-fetching.
            if latest_received_at is None or email.received_at > latest_received_at:
                latest_received_at = email.received_at

            if not self._passes_filter(email):
                continue

            await self._emit(
                progress,
                {
                    "event": "processing",
                    "email": email.subject,
                    "index": index,
                    "total": len(emails),
                },
            )

            for attachment in email.attachments:
                bid = await self._ingest_attachment(account, email, attachment)
                bids_created += 1
                await self._emit(
                    progress,
                    {
                        "event": "bid_saved",
                        "bid_id": bid.id,
                        "vendor": bid.sender_email,
                    },
                )

        await self._emit(
            progress,
            {"event": "completed", "bids_created": bids_created, "rejected": 0},
        )

        return {
            "bids_created": bids_created,
            "emails_processed": emails_processed,
            "latest_received_at": latest_received_at,
        }

    async def _fetch(self, account: LinkedAccount) -> list[GraphEmail]:
        """Pull new mail bounded by the account watermark, wrapping failures."""
        try:
            return await self._graph_client.fetch_new_emails(
                account.id, account.last_processed_at
            )
        except Exception as exc:
            raise AppError(
                code="INGEST_FETCH",
                message="Failed to fetch new emails from Graph",
                context={"account_id": account.id},
                cause=exc,
            )

    def _passes_filter(self, email: GraphEmail) -> bool:
        """
        Tier-1 code-only filter (no AI). Tier-2 in-memory text extraction is out
        of scope here; only metadata (subject/body/filenames) is checked. The
        filter is defensive and never raises, so no wrapping is needed (Rule 7
        applies to external calls; this is pure in-process logic).
        """
        return self._email_filter.should_process(
            subject=email.subject,
            body=email.body_preview,
            attachment_filenames=[a.filename for a in email.attachments],
        )

    async def _ingest_attachment(
        self,
        account: LinkedAccount,
        email: GraphEmail,
        attachment: EmailAttachment,
    ) -> IngestedBid:
        """
        Upload, parse, and persist a single attachment as a Parsed bid.

        The Blob path is namespaced by account + message + filename so re-running
        ingestion overwrites the same blob rather than accumulating duplicates,
        mirroring the deterministic bid id (hash of messageId + filename). Each
        external call (upload, parse, upsert) is wrapped with its own INGEST_*
        code so the single top-level log entry pinpoints which step failed.
        """
        blob_path = f"{account.id}/{email.message_id}/{attachment.filename}"

        try:
            stored_path = await self._blob_service.upload(
                blob_path, attachment.content_bytes, attachment.content_type
            )
        except Exception as exc:
            raise AppError(
                code="INGEST_BLOB_UPLOAD",
                message="Failed to upload attachment to Blob",
                context={
                    "account_id": account.id,
                    "message_id": email.message_id,
                    "filename": attachment.filename,
                },
                cause=exc,
            )

        try:
            parsed = await self._document_parser.parse(
                attachment.filename, attachment.content_bytes
            )
        except Exception as exc:
            raise AppError(
                code="INGEST_PARSE",
                message="Failed to parse attachment with Document Intelligence",
                context={
                    "account_id": account.id,
                    "message_id": email.message_id,
                    "filename": attachment.filename,
                },
                cause=exc,
            )

        bid = IngestedBid(
            id=IngestedBid.make_id(email.message_id, attachment.filename),
            message_id=email.message_id,
            linked_account_id=account.id,
            sender_email=email.sender_email,
            email_subject=email.subject,
            received_at=email.received_at,
            attachment_filename=attachment.filename,
            blob_path=stored_path,
            document_text=parsed.full_text,
            table_count=len(parsed.tables),
            status=BidStatus.PARSED,
        )

        try:
            return await self._bid_store.upsert(bid)
        except Exception as exc:
            raise AppError(
                code="INGEST_BID_UPSERT",
                message="Failed to persist parsed bid",
                context={"bid_id": bid.id, "message_id": email.message_id},
                cause=exc,
            )

    @staticmethod
    async def _emit(progress: ProgressCallback | None, event: dict) -> None:
        """
        Deliver one SSE progress event if a callback was provided.

        Progress reporting is best-effort and must never break ingestion: a
        callback that raises is logged and swallowed, because the bids are the
        durable outcome and a dropped SSE frame is cosmetic.
        """
        if progress is None:
            return
        try:
            await progress(event)
        except Exception:
            logger.warning("Progress callback failed for event %s", event.get("event"))
