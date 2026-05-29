"""
bid_processing_trigger.py — Cosmos DB change-feed trigger that drives a newly
parsed bid through the 3-agent pipeline (build doc 8.2).

WHY this trigger exists: the EmailIngestionOrchestrator writes each parsed
attachment as an ``IngestedBid`` in status ``Parsed``. That write lands in the
``bids`` Cosmos container, whose change feed this trigger watches. For every
changed document it deserialises the bid and, if the document is in a state that
warrants processing (a fresh ``Parsed`` bid or an in-progress checkpoint left by
a crash), calls ``BidProcessingOrchestrator.process_bid`` — which is itself
resumable and idempotent and gates on ``bid.status`` (build doc 8.2 crash
recovery). The trigger is THIN: parse, gate, delegate.

POISON-DOCUMENT ISOLATION: a change-feed batch can contain many documents. If
one document is malformed or its processing raises, swallowing-and-recording that
single failure keeps the rest of the batch flowing — otherwise one poison bid
would wedge the whole lease and stall every other bid. We therefore catch
per-document errors, log them once here (Rule 8: this trigger entrypoint is a
top-level handler, so logging the AppError chain is correct), and continue. A
document we never let ``process_bid`` mutate stays at its checkpoint, so the
15-minute retry trigger will pick it up again.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import azure.functions as func

from src.core.enums import BidStatus
from src.core.errors.app_error import AppError
from src.core.models.bid import IngestedBid

if TYPE_CHECKING:
    from src.composition.container import AppContainer

logger = logging.getLogger(__name__)

ContainerGetter = Callable[[], Awaitable["AppContainer"]]


def register(app: func.FunctionApp, get_container: ContainerGetter) -> None:
    """
    Attach the Cosmos change-feed trigger for the ``bids`` container to ``app``.

    Bound to database ``bidpilotdb``, container ``bids``, with lease container
    ``leases`` (build doc 6.1). ``CosmosDbConnection`` names the app setting that
    holds the Cosmos connection used by the change-feed binding. The trigger
    function is defined inside ``register`` so it closes over the injected
    ``get_container`` (Rule 3) while still attaching to the shared ``app``.
    """

    @app.cosmos_db_trigger(
        arg_name="documents",
        connection="CosmosDbConnection",
        database_name="bidpilotdb",
        container_name="bids",
        lease_container_name="leases",
        create_lease_container_if_not_exists=True,
    )
    async def bid_processing_trigger(documents: func.DocumentList) -> None:
        """
        Process each changed bid document, isolating per-document failures.

        For every document in the change-feed batch: deserialise to IngestedBid,
        skip it unless its status warrants processing, then call
        ``process_bid`` (resumable/idempotent). A failure on one document is
        logged via the AppError chain and swallowed so the rest of the batch — and
        the lease — keep moving (build doc 8.2). Documents left untouched remain at
        their checkpoint for the 15-minute retry trigger to recover.
        """
        if not documents:
            return

        container = await get_container()
        orchestrator = container.bid_processing_orchestrator

        for document in documents:
            bid_id = "unknown"
            try:
                bid = IngestedBid.model_validate(document.to_dict())
                bid_id = bid.id

                # Gate: only a fresh Parsed bid or an in-progress checkpoint needs
                # work. Everything else (terminal or intermediate-done) is a no-op.
                if not _should_process(bid.status):
                    continue

                await orchestrator.process_bid(bid)

            except AppError as err:
                # Top-level handler for this document: log the full chain once
                # (Rule 8) and continue so one poison doc cannot block the batch.
                logger.error(
                    "Bid processing failed for change-feed document %s: %s",
                    bid_id,
                    err.get_full_chain(),
                )
            except Exception as exc:
                # A non-AppError here means a malformed document or an unexpected
                # bug. Record it and move on rather than poisoning the lease.
                logger.error(
                    "Unexpected error processing change-feed document %s: %s",
                    bid_id,
                    exc,
                )


def _should_process(status: BidStatus) -> bool:
    """
    True when a bid still needs pipeline work from the change feed.

    A fresh ingest arrives as ``Parsed``; an in-progress checkpoint
    (``is_in_progress``) is a crash remnant worth resuming. Terminal and
    intermediate-"done" states are skipped so the change feed never re-runs
    finished steps.
    """
    return status == BidStatus.PARSED or status.is_in_progress
