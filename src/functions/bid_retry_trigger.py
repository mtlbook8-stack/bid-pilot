"""
bid_retry_trigger.py — timer trigger that resumes bids stuck mid-pipeline
(build doc 8.2 "Crash recovery").

WHY this trigger exists: the bid pipeline checkpoints its status to Cosmos BEFORE
each agent runs, so a crash mid-agent leaves a bid durably parked in an
in-progress status (``Validating`` / ``MatchingProject`` / ``CategorizingJob``).
The change-feed trigger reacts to writes, but a crashed process produces no new
write, so those bids would otherwise sit forever. Every 15 minutes this trigger
sweeps the in-progress statuses and re-calls ``process_bid``, which is resumable
and continues from the exact checkpoint. The orchestrator owns the retry budget:
it increments ``retry_count`` and flips a bid to ``Failed`` once
``settings.max_bid_retries`` is reached, so this trigger never needs to reason
about max retries itself.

THIN trigger: query the stuck bids, delegate each to ``process_bid``, isolate
per-bid failures so one bad bid does not abort the sweep, log once at the top
(Rule 8).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import azure.functions as func

from src.core.enums import BidStatus
from src.core.errors.app_error import AppError

if TYPE_CHECKING:
    from src.composition.container import AppContainer

logger = logging.getLogger(__name__)

ContainerGetter = Callable[[], Awaitable["AppContainer"]]

# The three in-progress checkpoint statuses the pipeline can crash inside. These
# mirror ``BidStatus.is_in_progress`` and are exactly the states the retry sweep
# must resume (build doc 8.2).
_RETRYABLE_STATUSES = (
    BidStatus.VALIDATING,
    BidStatus.MATCHING_PROJECT,
    BidStatus.CATEGORIZING_JOB,
)


def register(app: func.FunctionApp, get_container: ContainerGetter) -> None:
    """
    Attach the 15-minute bid-retry timer to ``app``.

    Schedule ``0 */15 * * * *`` (every 15 minutes). Defined inside ``register`` so
    it closes over the injected ``get_container`` (Rule 3) while attaching to the
    shared ``app``.
    """

    @app.timer_trigger(
        arg_name="timer",
        schedule="0 */15 * * * *",
        run_on_startup=False,
    )
    async def bid_retry_trigger(timer: func.TimerRequest) -> None:
        """
        Re-run every bid parked in an in-progress checkpoint status.

        Queries the bid store for each retryable status and calls ``process_bid``,
        which resumes from the checkpoint and applies the retry/FAILED budget. A
        failure on one bid is logged (Rule 8) and swallowed so the remaining stuck
        bids in the sweep still get a chance to advance.
        """
        container = await get_container()
        bid_store = container.bid_store
        orchestrator = container.bid_processing_orchestrator

        for status in _RETRYABLE_STATUSES:
            stuck = await bid_store.list_by_status(status)
            for bid in stuck:
                try:
                    await orchestrator.process_bid(bid)
                except AppError as err:
                    # Top-level log for this bid's failure (Rule 8). The bid stays
                    # at its checkpoint (or flips to FAILED once retries are spent
                    # inside the orchestrator), so the next sweep is well-defined.
                    logger.error(
                        "Retry of bid %s (status %s) failed: %s",
                        bid.id,
                        status.value,
                        err.get_full_chain(),
                    )
