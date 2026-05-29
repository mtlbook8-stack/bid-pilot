"""
webhook_notification.py — HTTP trigger that receives Microsoft Graph
change-notification callbacks and turns them into an immediate ingestion poll
(build doc 8.1; webhook receiver in section 3).

WHY this trigger exists: a Graph mail subscription pushes a notification when new
mail arrives, letting BidPilot ingest in near-real-time instead of waiting for
the 30-minute timer. Graph has two interaction shapes this endpoint must handle:

1. SUBSCRIPTION VALIDATION HANDSHAKE — when a subscription is created/renewed,
   Graph issues a GET/POST carrying a ``validationToken`` query parameter and
   expects that exact token echoed back as ``text/plain`` with HTTP 200 within
   seconds, or the subscription is rejected. We answer this first, before any
   other work.
2. CHANGE NOTIFICATION — a POST whose body lists changed resources. Each item
   carries the ``clientState`` we set at subscription time (the linked-account
   id — see ``GraphWebhookManager.create_subscription``), which doubles as a
   shared secret and a correlator. We resolve the affected account from
   ``clientState`` (falling back to ``subscriptionId``) and kick off an ingestion
   poll for it, then return ``202 Accepted`` promptly — Graph only needs an
   acknowledgement, not the ingestion result.

THIN trigger: handshake, parse, resolve, delegate, acknowledge. Errors are
logged once at the top (Rule 8); a per-notification failure is isolated so one
bad item cannot fail the whole callback (which would make Graph retry the batch).
"""

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
    Attach the Graph webhook-receiver HTTP trigger to ``app``.

    Anonymous auth: Graph cannot present a function key, so the endpoint is open
    at the HTTP layer and instead authenticates each notification by matching the
    echoed ``clientState`` against a known active account (a value only Graph and
    BidPilot share). Accepts POST (notifications) and GET (some validation
    probes). Defined inside ``register`` to close over ``get_container`` (Rule 3).
    """

    @app.route(
        route="webhooks/graph",
        methods=[func.HttpMethod.POST, func.HttpMethod.GET],
        auth_level=func.AuthLevel.ANONYMOUS,
    )
    async def webhook_notification(req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle the Graph validation handshake or a change notification.

        Returns the ``validationToken`` verbatim (text/plain 200) when present;
        otherwise resolves the affected account(s) from the notification body and
        triggers an ingestion poll for each, returning 202. Failures are logged
        once (Rule 8) and still answered with 202 so Graph does not hammer us with
        retries for a notification we have already recorded.
        """
        # 1. Subscription validation handshake — must echo the token immediately.
        validation_token = req.params.get("validationToken")
        if validation_token is not None:
            return func.HttpResponse(
                body=validation_token,
                status_code=200,
                mimetype="text/plain",
            )

        # 2. Change notification — parse, resolve account(s), trigger ingestion.
        try:
            payload = req.get_json()
        except ValueError:
            # A malformed body is not retryable; acknowledge so Graph stops, but
            # record it for investigation (Rule 8).
            logger.error("Graph webhook received a non-JSON notification body")
            return func.HttpResponse(status_code=202)

        notifications = payload.get("value") or []
        if not notifications:
            return func.HttpResponse(status_code=202)

        container = await get_container()
        accounts = await container.linked_account_store.list_all_active()
        by_client_state = {a.id: a for a in accounts}
        by_subscription = {
            a.webhook_subscription_id: a
            for a in accounts
            if a.webhook_subscription_id
        }

        for notification in notifications:
            account = _resolve_account(notification, by_client_state, by_subscription)
            if account is None:
                # Unknown clientState/subscriptionId: either a spoofed callback or
                # an account that was unlinked. Drop it (do not poll arbitrary
                # mailboxes) but log for visibility.
                logger.warning(
                    "Graph webhook notification did not match an active account "
                    "(subscriptionId=%s)",
                    notification.get("subscriptionId"),
                )
                continue
            await _poll_account(container, account)

        # Graph only needs acknowledgement; ingestion runs to completion above but
        # its outcome is not part of the contract.
        return func.HttpResponse(status_code=202)


def _resolve_account(
    notification: dict,
    by_client_state: dict[str, LinkedAccount],
    by_subscription: dict[str, LinkedAccount],
) -> LinkedAccount | None:
    """
    Map one Graph notification to its LinkedAccount, authenticating by clientState.

    ``clientState`` was set to the account id at subscription time, so a match
    both identifies the account and proves the callback is genuine (only Graph
    knows the value). We fall back to ``subscriptionId`` when ``clientState`` is
    absent. Returns None when neither resolves an active account.
    """
    client_state = notification.get("clientState")
    if client_state and client_state in by_client_state:
        return by_client_state[client_state]
    subscription_id = notification.get("subscriptionId")
    if subscription_id and subscription_id in by_subscription:
        return by_subscription[subscription_id]
    return None


async def _poll_account(container: "AppContainer", account: LinkedAccount) -> None:
    """
    Run an ingestion poll for one account and advance its watermark.

    Mirrors the timer poll: ``process_account`` ingests new mail, then we advance
    ``last_processed_at`` to the returned ``latest_received_at`` and upsert. A
    failure is logged via the AppError chain (Rule 8) and swallowed so a single
    bad notification cannot fail the whole callback batch.
    """
    try:
        result = await container.email_ingestion_orchestrator.process_account(account)
        latest = result.get("latest_received_at")
        if latest is not None and latest != account.last_processed_at:
            account.mark_processed(latest)
            await container.linked_account_store.upsert(account)
    except AppError as err:
        logger.error(
            "Webhook-triggered poll failed for account %s: %s",
            account.id,
            err.get_full_chain(),
        )
