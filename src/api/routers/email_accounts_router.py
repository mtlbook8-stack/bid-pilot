"""
/api/email-accounts — list linked mailboxes, unlink one, manually poll (SSE).

Thin router (Rule 2):
  - GET /                  list the requesting user's linked accounts.
  - DELETE /{accountId}    unlink: delete the account + best-effort cancel its
                           Graph webhook subscription.
  - POST /{accountId}/poll stream a manual poll's progress as SSE (build doc 8.1).

The poll handler bridges the ManualPollService's async event generator into an
EventSourceResponse, JSON-encoding each event's payload as the SSE `data` field.
"""

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from src.api.dependencies import (
    UserContext,
    get_container,
    get_current_user,
    get_manual_poll_service,
)
from src.api.services.manual_poll_service import ManualPollService
from src.composition.container import AppContainer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email-accounts", tags=["email-accounts"])


@router.get("")
async def list_accounts(
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
) -> list:
    """List the linked accounts owned by the requesting user (`/userId`)."""
    return await container.linked_account_store.list_for_user(user.user_id)


@router.delete("/{account_id}")
async def unlink_account(
    account_id: str,
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
) -> dict:
    """
    Unlink a mailbox: delete the account, then best-effort cancel its webhook.

    The Cosmos delete is the authoritative action — once gone, the account is
    unlinked. Cancelling the Graph subscription is best-effort: if the account had
    no subscription or Graph rejects the delete, the unlink still succeeds (a
    dangling subscription simply expires). We load the account first so the
    webhook manager has the mailbox context it needs.
    """
    account = await container.linked_account_store.get(account_id, user.user_id)
    await container.linked_account_store.delete(account_id, user.user_id)

    if account is not None and account.webhook_subscription_id:
        try:
            await container.webhook_manager.delete_subscription(account)
        except Exception:
            # Best-effort: a failed unsubscribe must not fail the unlink. The
            # subscription expires on its own; nothing user-visible breaks.
            logger.warning(
                "Failed to cancel webhook for unlinked account %s", account_id
            )

    return {"status": "unlinked", "accountId": account_id}


@router.get("/{account_id}/poll")
async def poll_account(
    account_id: str,
    manual_poll: ManualPollService = Depends(get_manual_poll_service),
    user: UserContext = Depends(get_current_user),
) -> EventSourceResponse:
    """
    Manually poll a mailbox, streaming progress as SSE (build doc 8.1).

    Each event dict from the service becomes one SSE frame whose `data` is the
    JSON-encoded payload. The frontend's useSSE hook parses these into live
    progress (started / emails_found / processing / bid_saved / completed / error).
    """

    async def event_stream() -> AsyncIterator[dict]:
        async for event in manual_poll.poll(account_id, user.user_id):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_stream())
