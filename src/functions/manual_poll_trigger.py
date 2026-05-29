"""
manual_poll_trigger.py — HTTP trigger for a user-initiated "Poll Now" of a single
linked mailbox (build doc 8.1 "Manual Push"; referenced in section 3).

WHY this trigger exists: when a user wants their newest bids ingested immediately
rather than waiting for the 30-minute timer, the API's ``manual_poll_service``
calls this Function entry point. This is the plain request/response variant: it
runs ``EmailIngestionOrchestrator.process_account`` for the one requested account
and returns a JSON summary (bids created, emails processed). The LIVE SSE
progress version lives in the API layer (``manual_poll_service.py`` streams the
section-8.1 progress events); this function exists as the durable, key-protected
backend entry the API targets.

THIN trigger: parse ``{accountId}``, resolve the account, delegate, advance the
watermark, return JSON. Errors propagate to a single top-level handler that logs
the AppError chain once (Rule 8) and returns a user-safe payload.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import azure.functions as func

from src.core.errors.app_error import AppError
from src.core.models.linked_account import LinkedAccount

if TYPE_CHECKING:
    from src.composition.container import AppContainer

logger = logging.getLogger(__name__)

ContainerGetter = Callable[[], Awaitable["AppContainer"]]


def register(app: func.FunctionApp, get_container: ContainerGetter) -> None:
    """
    Attach the manual-poll HTTP trigger to ``app``.

    FUNCTION-level auth: this is an internal backend entry the API calls with the
    ``functions_manual_poll_key`` (build doc section 10), so it requires a
    function key rather than being anonymous. Accepts POST only. Defined inside
    ``register`` to close over ``get_container`` (Rule 3).
    """

    @app.route(
        route="poll",
        methods=[func.HttpMethod.POST],
        auth_level=func.AuthLevel.FUNCTION,
    )
    async def manual_poll_trigger(req: func.HttpRequest) -> func.HttpResponse:
        """
        Poll one account on demand and return a JSON ingestion summary.

        Body: ``{"accountId": "..."}``. Resolves the account, runs
        ``process_account``, advances ``last_processed_at`` to the returned
        ``latest_received_at`` on success, and returns the bids/emails counts.
        Bad input yields 400; a missing account yields 404; any AppError is logged
        once (Rule 8) and surfaced as a user-safe 500 with an error id.
        """
        container = await get_container()
        try:
            account = await _resolve_account(req, container)
            result = await container.email_ingestion_orchestrator.process_account(
                account
            )
            await _advance_watermark(account, result, container)
        except _BadRequest as bad:
            return func.HttpResponse(
                body=json.dumps({"error": bad.message}),
                status_code=bad.status_code,
                mimetype="application/json",
            )
        except AppError as err:
            # Single top-level log of the full chain (Rule 8); the user sees only a
            # friendly message plus a reportable error id.
            logger.error("Manual poll failed: %s", err.get_full_chain())
            return func.HttpResponse(
                body=json.dumps(err.user_message),
                status_code=500,
                mimetype="application/json",
            )

        summary = {
            "accountId": account.id,
            "bidsCreated": result.get("bids_created", 0),
            "emailsProcessed": result.get("emails_processed", 0),
        }
        return func.HttpResponse(
            body=json.dumps(summary),
            status_code=200,
            mimetype="application/json",
        )


class _BadRequest(Exception):
    """Internal signal for a client-side error mapped to a non-500 HTTP status."""

    def __init__(self, message: str, status_code: int) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def _resolve_account(
    req: func.HttpRequest, container: "AppContainer"
) -> LinkedAccount:
    """
    Parse ``accountId`` from the request body and load the active account.

    Accounts are partitioned by ``userId``, so the manual-poll entry resolves the
    account by scanning active accounts (the same approach the container uses for
    Graph calls) — fine at this scale (a handful of linked mailboxes). Raises a
    ``_BadRequest`` for missing/garbled input (400) or an unknown id (404) so the
    caller gets a precise status rather than an opaque 500.
    """
    try:
        body = req.get_json()
    except ValueError:
        raise _BadRequest("Request body must be JSON", 400)

    account_id = (body or {}).get("accountId")
    if not account_id:
        raise _BadRequest("Missing required field 'accountId'", 400)

    accounts = await container.linked_account_store.list_all_active()
    for account in accounts:
        if account.id == account_id:
            return account
    raise _BadRequest("No active linked account found for the given id", 404)


async def _advance_watermark(
    account: LinkedAccount, result: dict, container: "AppContainer"
) -> None:
    """Persist the new watermark from a successful poll (mirrors the timer poll)."""
    latest = result.get("latest_received_at")
    if latest is None or latest == account.last_processed_at:
        return
    account.mark_processed(latest)
    await container.linked_account_store.upsert(account)
