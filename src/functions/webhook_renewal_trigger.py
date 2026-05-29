"""
webhook_renewal_trigger.py — timer trigger that extends Graph mail subscriptions
before they expire (build doc section 3).

WHY this trigger exists: Microsoft Graph mailbox subscriptions are short-lived
(Graph caps their lifetime), so a subscription left alone simply stops delivering
notifications when it lapses — silently degrading BidPilot to timer-only polling.
Every 12 hours this trigger PATCHes a fresh ``expirationDateTime`` onto each
active account's subscription via ``GraphWebhookManager.renew_subscription`` and
persists the returned expiry, keeping the push channel alive well ahead of the
deadline.

BEST-EFFORT per account: renewals are independent, so one account's failure (an
expired token, a deleted subscription) is logged once (Rule 8) and skipped rather
than aborting the others — the 30-minute poll is the safety net, and the next
renewal pass will retry. THIN trigger: list, delegate, persist, isolate, log.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
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
    Attach the 12-hour subscription-renewal timer to ``app``.

    Schedule ``0 0 */12 * * *`` (every 12 hours). Defined inside ``register`` so
    it closes over the injected ``get_container`` (Rule 3) while attaching to the
    shared ``app``.
    """

    @app.timer_trigger(
        arg_name="timer",
        schedule="0 0 */12 * * *",
        run_on_startup=False,
    )
    async def webhook_renewal_trigger(timer: func.TimerRequest) -> None:
        """
        Renew the Graph subscription for every active account that has one.

        Accounts without a ``webhook_subscription_id`` are skipped (nothing to
        renew). For the rest, ``renew_subscription`` returns the Graph resource
        whose ``expirationDateTime`` is persisted onto the account. Per-account
        failures are logged via the AppError chain (Rule 8) and swallowed.
        """
        container = await get_container()
        account_store = container.linked_account_store
        webhook_manager = container.webhook_manager

        accounts = await account_store.list_all_active()
        for account in accounts:
            if not account.webhook_subscription_id:
                continue
            try:
                resource = await webhook_manager.renew_subscription(account)
                _persist_expiry(account, resource)
                await account_store.upsert(account)
            except AppError as err:
                logger.error(
                    "Subscription renewal failed for account %s: %s",
                    account.id,
                    err.get_full_chain(),
                )


def _persist_expiry(account: LinkedAccount, resource: dict) -> None:
    """
    Copy the renewed ``expirationDateTime`` from the Graph resource onto the
    account in-memory; the caller upserts.

    Graph returns the new expiry as an ISO-8601 string. A missing/garbled value is
    left as-is (the renewal still succeeded server-side; we just keep the old
    locally-cached expiry rather than crash the per-account best-effort path).
    """
    raw_expiry = resource.get("expirationDateTime")
    if not raw_expiry:
        return
    try:
        account.webhook_expires_at = datetime.fromisoformat(
            str(raw_expiry).replace("Z", "+00:00")
        )
        account.updated_at = datetime.now(account.created_at.tzinfo)
    except (ValueError, TypeError):
        logger.warning(
            "Could not parse renewed expiry %r for account %s",
            raw_expiry,
            account.id,
        )
