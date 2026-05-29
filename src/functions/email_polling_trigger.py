"""
email_polling_trigger.py — timer trigger that polls every active linked mailbox
for new bid emails (build doc 8.1, decision I3: 30-minute interval).

WHY this trigger exists: webhook notifications are best-effort (subscriptions
lapse, callbacks get dropped), so a steady 30-minute sweep guarantees no mailbox
goes unpolled. For each active account it calls
``EmailIngestionOrchestrator.process_account`` — which fetches mail newer than
the account watermark, filters it in code (no AI), and writes ``Parsed`` bids
that the change-feed trigger then picks up. The orchestrator deliberately does
NOT advance the watermark (so a crash mid-poll cannot skip unprocessed mail);
this trigger owns that, advancing ``last_processed_at`` to the returned
``latest_received_at`` only after a successful poll, then upserting the account.

THIN trigger: list accounts, delegate each to the orchestrator, persist the
watermark, isolate per-account failures so one bad mailbox does not abort the
sweep, and log once at the top (Rule 8).
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
    Attach the 30-minute email-polling timer to ``app``.

    Schedule ``0 */30 * * * *`` (every 30 minutes — decision I3). Defined inside
    ``register`` so it closes over the injected ``get_container`` (Rule 3) while
    attaching to the shared ``app``.
    """

    @app.timer_trigger(
        arg_name="timer",
        schedule="0 */30 * * * *",
        run_on_startup=False,
    )
    async def email_polling_trigger(timer: func.TimerRequest) -> None:
        """
        Poll every active linked mailbox and advance its watermark on success.

        For each active account: run ``process_account``; on success advance
        ``last_processed_at`` to the returned ``latest_received_at`` and upsert the
        account. A failure on one account is logged via the AppError chain (Rule 8)
        and swallowed so the remaining mailboxes still get polled — the failed
        account keeps its old watermark and is retried on the next sweep.
        """
        container = await get_container()
        account_store = container.linked_account_store
        orchestrator = container.email_ingestion_orchestrator

        accounts = await account_store.list_all_active()
        for account in accounts:
            try:
                result = await orchestrator.process_account(account)
                await _advance_watermark(account, result, account_store)
            except AppError as err:
                logger.error(
                    "Email poll failed for account %s: %s",
                    account.id,
                    err.get_full_chain(),
                )


async def _advance_watermark(
    account: LinkedAccount,
    result: dict,
    account_store: object,
) -> None:
    """
    Persist the new poll watermark from a successful ``process_account`` result.

    The orchestrator returns the highest ``received_at`` it observed across all
    fetched mail (even filtered-out emails) as ``latest_received_at``. Advancing
    the account to that value bounds the next Graph delta query so already-seen
    mail is never re-fetched. A ``None`` result (no mail seen) leaves the
    watermark untouched. The store upsert is the only mutation persisted.
    """
    latest = result.get("latest_received_at")
    if latest is None or latest == account.last_processed_at:
        return
    account.mark_processed(latest)
    await account_store.upsert(account)  # type: ignore[attr-defined]
