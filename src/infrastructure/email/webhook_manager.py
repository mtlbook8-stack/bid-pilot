"""
GraphWebhookManager — Microsoft Graph change-notification subscription lifecycle.

Instead of polling every mailbox on a timer alone, BidPilot subscribes to Graph
change notifications so a newly-arrived message can push a notification to the
webhook receiver almost immediately (build doc section 3 / functions:
webhook_notification + webhook_renewal_trigger). Graph subscriptions are
short-lived for mail (a few days max) and must be renewed before they expire, so
this manager owns the full create / renew / delete cycle for one mailbox.

Every external call (resolve, token, HTTP) is wrapped and re-raised as AppError
"GRAPH_WEBHOOK" (Rules 7/8); the manager never logs.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx

from src.api.config import Settings
from src.core.errors.app_error import AppError
from src.core.models.linked_account import LinkedAccount
from src.infrastructure.email.token_manager import GraphTokenManager

logger = logging.getLogger(__name__)

# Async resolver from account id to the full LinkedAccount (same accommodation as
# GraphMailClient — the lifecycle needs the mailbox email + token secret).
AccountResolver = Callable[[str], Awaitable[LinkedAccount]]

_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# The mailbox change source and the change type we care about. "created" fires on
# new mail arriving — exactly the ingestion trigger. "me/messages" is interpreted
# relative to the subscribed mailbox.
_SUBSCRIPTION_RESOURCE = "me/messages"
_SUBSCRIPTION_CHANGE_TYPE = "created"

# Graph caps mail-subscription lifetime at ~4230 minutes (under 3 days). We
# request ~2 days so the 12-hour renewal timer always has comfortable headroom to
# extend before expiry, even if a renewal run is skipped.
_SUBSCRIPTION_LIFETIME = timedelta(days=2)


class GraphWebhookManager:
    """
    Manages the create/renew/delete lifecycle of a Graph mail subscription.

    Why it exists: webhook subscriptions are the low-latency path for ingestion,
    but they are ephemeral and tied to a notification URL and client state. This
    class encapsulates the POST/PATCH/DELETE shapes and the expiry math so the
    Azure Functions triggers (create on link, renew on a 12-hour timer, delete on
    unlink) stay thin.

    Dependencies are injected (Rule 3): a `GraphTokenManager` for bearer tokens,
    `Settings` for the notification URL, an `httpx.AsyncClient` owned by the
    composition root, and the `account_resolver` async callable
    (`account_id -> LinkedAccount`) — the same interface accommodation used by
    GraphMailClient, since the lifecycle also needs the mailbox + token secret.
    """

    def __init__(
        self,
        token_manager: GraphTokenManager,
        settings: Settings,
        http_client: httpx.AsyncClient,
        account_resolver: AccountResolver,
    ) -> None:
        self._tokens = token_manager
        self._settings = settings
        self._http = http_client
        self._resolve_account = account_resolver

    async def create_subscription(self, account: LinkedAccount) -> dict:
        """
        Create a new change-notification subscription for the mailbox.

        Returns the parsed Graph subscription resource (caller persists `id` and
        `expirationDateTime` onto the LinkedAccount). The `clientState` is set to
        the account id so the webhook receiver can correlate an inbound
        notification back to the linked account and reject spoofed callbacks.
        """
        token = await self._get_token(account)
        expiry = self._expiry()
        body = {
            "changeType": _SUBSCRIPTION_CHANGE_TYPE,
            "notificationUrl": self._settings.webhook_notification_url,
            "resource": _SUBSCRIPTION_RESOURCE,
            "expirationDateTime": expiry.isoformat(),
            # Echoed back on every notification; used as a shared secret/correlator.
            "clientState": account.id,
        }

        try:
            response = await self._http.post(
                f"{_GRAPH_BASE_URL}/subscriptions",
                headers=self._auth_header(token),
                json=body,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise AppError(
                code="GRAPH_WEBHOOK",
                message="Failed to create a Graph subscription",
                context={
                    "account_id": account.id,
                    "notification_url": self._settings.webhook_notification_url,
                },
                cause=exc,
            )

    async def renew_subscription(self, account: LinkedAccount) -> dict:
        """
        Extend an existing subscription's expiry (PATCH expirationDateTime).

        Called by the 12-hour renewal timer. Requires the account to already hold
        a `webhook_subscription_id`; renewing without one is a logic error
        surfaced as a typed AppError rather than a confusing 404 from Graph.
        """
        if not account.webhook_subscription_id:
            raise AppError(
                code="GRAPH_WEBHOOK",
                message="Cannot renew a subscription that does not exist",
                context={"account_id": account.id},
            )

        token = await self._get_token(account)
        expiry = self._expiry()

        try:
            response = await self._http.patch(
                f"{_GRAPH_BASE_URL}/subscriptions/{account.webhook_subscription_id}",
                headers=self._auth_header(token),
                json={"expirationDateTime": expiry.isoformat()},
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise AppError(
                code="GRAPH_WEBHOOK",
                message="Failed to renew a Graph subscription",
                context={
                    "account_id": account.id,
                    "subscription_id": account.webhook_subscription_id,
                },
                cause=exc,
            )

    async def delete_subscription(self, account: LinkedAccount) -> None:
        """
        Delete the subscription when a mailbox is unlinked.

        A 404 is treated as success: the goal state is "no subscription", and a
        subscription that already expired or was removed satisfies that — failing
        on 404 would block an unlink for no benefit. Other errors are wrapped.
        """
        if not account.webhook_subscription_id:
            # Nothing to delete; the desired end state (no subscription) already
            # holds, so this is a no-op rather than an error.
            return

        token = await self._get_token(account)

        try:
            response = await self._http.delete(
                f"{_GRAPH_BASE_URL}/subscriptions/{account.webhook_subscription_id}",
                headers=self._auth_header(token),
            )
            if response.status_code == httpx.codes.NOT_FOUND:
                return
            response.raise_for_status()
        except Exception as exc:
            raise AppError(
                code="GRAPH_WEBHOOK",
                message="Failed to delete a Graph subscription",
                context={
                    "account_id": account.id,
                    "subscription_id": account.webhook_subscription_id,
                },
                cause=exc,
            )

    async def _get_token(self, account: LinkedAccount) -> str:
        """
        Acquire a Graph bearer token, letting the token manager's own AppErrors
        propagate unchanged and wrapping anything else as GRAPH_WEBHOOK.
        """
        try:
            return await self._tokens.get_access_token(account)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="GRAPH_WEBHOOK",
                message="Failed to acquire a Graph access token",
                context={"account_id": account.id},
                cause=exc,
            )

    @staticmethod
    def _expiry() -> datetime:
        """
        Compute the subscription expiry timestamp.

        Anchored to UTC `now` plus the fixed lifetime so the value Graph receives
        is unambiguous and always within Graph's allowed mail-subscription window.
        """
        return datetime.now(UTC) + _SUBSCRIPTION_LIFETIME

    @staticmethod
    def _auth_header(token: str) -> dict[str, str]:
        """Build the Bearer auth header used on every Graph request."""
        return {"Authorization": f"Bearer {token}"}
