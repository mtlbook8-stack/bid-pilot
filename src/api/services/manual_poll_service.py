"""
ManualPollService — user-triggered mailbox poll with live SSE progress (I3, 8.1).

WHY this exists: besides the 30-minute timer, a user can click "Poll Now" and
watch the ingestion happen. This service runs `EmailIngestionOrchestrator.
process_account` as a background task and bridges the orchestrator's async
progress callback into an `asyncio.Queue`, draining the queue as Server-Sent
Events in the exact section-8.1 shapes (started / emails_found / processing /
bid_saved / completed). After a successful poll it advances the account's
watermark (`last_processed_at`) to the latest received_at seen and upserts.

One job (Rule 2): orchestrate one manual poll and stream its progress. All
collaborators injected (Rule 3); failures wrapped as AppError but also surfaced
as an SSE `error` frame so the user sees the failure live (Rules 7, 8).
"""

import asyncio
import logging
from typing import AsyncIterator

from src.core.errors.app_error import AppError
from src.core.models.linked_account import LinkedAccount
from src.infrastructure.cosmos.linked_account_store import CosmosLinkedAccountStore
from src.orchestration.email_ingestion_orchestrator import EmailIngestionOrchestrator

logger = logging.getLogger(__name__)

# Sentinel pushed onto the queue when the ingestion task finishes, so the drainer
# knows to stop waiting for more progress events.
_DONE = object()


class ManualPollService:
    """Runs one account poll as a task and streams its 8.1 progress events."""

    def __init__(
        self,
        email_ingestion_orchestrator: EmailIngestionOrchestrator,
        linked_account_store: CosmosLinkedAccountStore,
    ) -> None:
        # Pure DI (Rule 3): the container passes the wired orchestrator + store.
        self._orchestrator = email_ingestion_orchestrator
        self._account_store = linked_account_store

    async def poll(self, account_id: str, user_id: str) -> AsyncIterator[dict]:
        """
        Poll one account, yielding SSE event dicts as ingestion progresses.

        Flow:
          1. Load the account (scoped to the requesting user so a user can only
             poll their own mailbox).
          2. Run `process_account` in a background task, feeding its progress
             callback into a queue.
          3. Yield every queued progress event as it arrives; the orchestrator
             already emits the started/emails_found/processing/bid_saved/completed
             shapes verbatim.
          4. On completion, advance the watermark to the latest received_at and
             upsert the account.

        Any failure is wrapped as AppError and also emitted as an `{"event":
        "error", ...}` SSE frame so the client sees it live; the generator then
        ends cleanly (the error id lets the user report the failure).
        """
        account = await self._load_account(account_id, user_id)

        queue: asyncio.Queue = asyncio.Queue()

        async def progress(event: dict) -> None:
            """Bridge the orchestrator's progress callback into the SSE queue."""
            await queue.put(event)

        # Kick off ingestion concurrently. We do NOT await it here — we await the
        # queue so progress streams as it happens; the task result is collected at
        # the end to advance the watermark.
        task: asyncio.Task = asyncio.create_task(
            self._run(account, progress, queue)
        )

        while True:
            item = await queue.get()
            if item is _DONE:
                break
            yield item

        # The task has signaled completion; surface any error it captured, or
        # advance the watermark on success.
        try:
            result = await task
        except AppError as err:
            yield {"event": "error", **err.user_message}
            return
        except Exception as exc:  # pragma: no cover - defensive
            wrapped = AppError(
                code="MANUAL_POLL_RUN",
                message="Manual poll task failed",
                context={"account_id": account_id},
                cause=exc,
            )
            yield {"event": "error", **wrapped.user_message}
            return

        await self._advance_watermark(account, result)

    async def _run(
        self,
        account: LinkedAccount,
        progress,
        queue: asyncio.Queue,
    ) -> dict:
        """
        Execute ingestion and always push the DONE sentinel afterwards.

        Wrapping the orchestrator call lets the drainer terminate deterministically
        (via the sentinel) whether ingestion succeeds or raises. The exception is
        re-raised so `poll` can read it off the awaited task and emit an SSE error
        frame; the sentinel guarantees the drain loop exits first.
        """
        try:
            return await self._orchestrator.process_account(account, progress)
        finally:
            # Always unblock the drain loop, even on failure, so `poll` proceeds to
            # await the task and handle the error.
            await queue.put(_DONE)

    async def _load_account(
        self, account_id: str, user_id: str
    ) -> LinkedAccount:
        """Load the user's account, wrapping store errors and 404 (Rule 7)."""
        try:
            account = await self._account_store.get(account_id, user_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="MANUAL_POLL_LOAD_ACCOUNT",
                message="Failed to load linked account for poll",
                context={"account_id": account_id, "user_id": user_id},
                cause=exc,
            )
        if account is None:
            raise AppError(
                code="MANUAL_POLL_ACCOUNT_MISSING",
                message="No linked account found for this user",
                context={"account_id": account_id, "user_id": user_id},
            )
        return account

    async def _advance_watermark(
        self, account: LinkedAccount, result: dict
    ) -> None:
        """
        Advance `last_processed_at` to the latest mail seen and persist.

        The orchestrator deliberately does NOT move the watermark — it returns the
        high-water `latest_received_at` so the caller advances it only after a
        successful poll (so a crash mid-poll never skips unprocessed mail). A
        watermark save failure is wrapped: it is not cosmetic — losing it would
        cause endless re-fetching — so it must surface.
        """
        latest = result.get("latest_received_at")
        if latest is None:
            return
        account.mark_processed(latest)
        try:
            await self._account_store.upsert(account)
        except Exception as exc:
            raise AppError(
                code="MANUAL_POLL_WATERMARK",
                message="Failed to persist the advanced poll watermark",
                context={"account_id": account.id},
                cause=exc,
            )
