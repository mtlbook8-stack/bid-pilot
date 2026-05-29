"""
connectivity_check.py — daily timer that probes Graph reachability for every
active linked mailbox (build doc section 3).

WHY this trigger exists: a linked mailbox can quietly become unusable — its
stored refresh token gets revoked, the user changes their password, or consent is
withdrawn — and the only symptom would be polls that fetch nothing or fail. This
daily probe performs the cheapest possible reachability check (acquiring a Graph
access token via ``GraphTokenManager.get_access_token``, which exercises the Key
Vault secret + the AAD refresh-token exchange WITHOUT touching mailbox data) and
records the outcome on the account (``last_health_check_at`` / ``last_health_ok``)
so the settings UI can flag broken connections for re-authentication.

BEST-EFFORT per account: a token failure for one account is expected signal (not
an error to abort on), so it is recorded as ``last_health_ok = False`` and logged,
and the sweep continues. THIN trigger: list, probe, record, upsert, isolate.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
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
    Attach the daily connectivity-check timer to ``app``.

    Schedule ``0 0 6 * * *`` (every day 06:00 UTC). Defined inside ``register`` so
    it closes over the injected ``get_container`` (Rule 3) while attaching to the
    shared ``app``.
    """

    @app.timer_trigger(
        arg_name="timer",
        schedule="0 0 6 * * *",
        run_on_startup=False,
    )
    async def connectivity_check(timer: func.TimerRequest) -> None:
        """
        Probe Graph reachability for every active account and record the result.

        For each active account, attempt a lightweight token acquisition. Whether
        it succeeds or fails, stamp ``last_health_check_at`` and set
        ``last_health_ok`` accordingly, then upsert. A failed probe is recorded
        (``ok = False``) and logged rather than raised, because a broken account is
        a known operational state this check exists to detect — not a reason to
        abort probing the others.
        """
        container = await get_container()
        account_store = container.linked_account_store
        token_manager = container.token_manager

        accounts = await account_store.list_all_active()
        for account in accounts:
            ok = await _probe(token_manager, account)
            _record(account, ok)
            try:
                await account_store.upsert(account)
            except AppError as err:
                # Persisting the health stamp failed — log once (Rule 8) and move
                # on; the next daily run will re-probe and re-attempt the write.
                logger.error(
                    "Failed to persist health result for account %s: %s",
                    account.id,
                    err.get_full_chain(),
                )


async def _probe(token_manager: object, account: LinkedAccount) -> bool:
    """
    Return True if a Graph access token can be acquired for ``account``.

    This is the cheapest reachability signal: it touches Key Vault and the AAD
    token endpoint but no mailbox. An AppError (the manager's own typed failure)
    or any other exception means the connection is unhealthy — we log it for
    visibility and return False rather than propagating, so the per-account
    best-effort contract holds.
    """
    try:
        await token_manager.get_access_token(account)  # type: ignore[attr-defined]
        return True
    except AppError as err:
        logger.warning(
            "Connectivity probe failed for account %s: %s",
            account.id,
            err.get_full_chain(),
        )
        return False
    except Exception as exc:
        logger.warning(
            "Connectivity probe errored for account %s: %s", account.id, exc
        )
        return False


def _record(account: LinkedAccount, ok: bool) -> None:
    """Stamp the probe outcome onto the account in-memory; the caller upserts."""
    account.last_health_check_at = datetime.now(UTC)
    account.last_health_ok = ok
    account.updated_at = datetime.now(UTC)
