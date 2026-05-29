"""
GraphMailClient — IGraphMailClient over the Microsoft Graph REST API.

Reads mail for a single linked mailbox: `fetch_new_emails` pulls everything
newer than the poll watermark (with attachments expanded and decoded) for the
30-minute ingestion poll, and `fetch_email` re-pulls one message by id for the
rejected-email restore flow (build doc 8.1, 8.5).

Interface accommodation (documented for the caller):
The IGraphMailClient contract passes only `account_id` (+ `since` / `message_id`),
but calling Graph requires the LinkedAccount — both to acquire a token (the token
manager keys off `token_secret_name`) and to address the mailbox by its email.
Rather than widen the fixed interface, the constructor accepts an injected
`account_resolver` async callable (`account_id -> LinkedAccount`). The composition
root wires it to a lookup that knows the user partition; this client stays an
exact `IGraphMailClient` implementation. See `account_resolver` in `__init__`.

Every external call (resolve, token, HTTP) is wrapped and re-raised as AppError
"GRAPH_MAIL" (Rules 7/8); the client never logs.
"""

import base64
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

import httpx

from src.core.errors.app_error import AppError
from src.core.interfaces.graph_client import (
    EmailAttachment,
    GraphEmail,
)
from src.core.models.linked_account import LinkedAccount
from src.infrastructure.email.token_manager import GraphTokenManager

logger = logging.getLogger(__name__)

# Async resolver from the interface-only account id to the full LinkedAccount.
AccountResolver = Callable[[str], Awaitable[LinkedAccount]]

# Graph base. Addressing the mailbox by `/users/{email}` (application/delegated
# both accept it) rather than `/me` because polling runs in a background worker
# with no signed-in user context — `/me` is only meaningful for an interactive
# delegated session.
_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Page size for list calls. Graph caps `$top` at 1000 for messages; 50 keeps each
# page small enough to expand attachments without huge payloads while still
# clearing a typical 30-minute backlog in a few pages.
_PAGE_SIZE = 50

# The `@odata.type` Graph stamps on a file attachment (vs item/reference
# attachments, which carry no `contentBytes` and must be skipped).
_FILE_ATTACHMENT_TYPE = "#microsoft.graph.fileAttachment"


class GraphMailClient:
    """
    IGraphMailClient implementation backed by Microsoft Graph.

    Why a dedicated client: ingestion only needs "give me new mail with its
    attachments" and "re-fetch this one message". Centralizing the Graph URL
    shapes, paging, and attachment decoding here (Rule 2/5) keeps the
    orchestrator free of REST detail and gives one place to evolve the API
    version.

    Dependencies are injected (Rule 3): a `GraphTokenManager` for bearer tokens,
    an `httpx.AsyncClient` owned by the composition root, and the
    `account_resolver` described in the module docstring.
    """

    def __init__(
        self,
        token_manager: GraphTokenManager,
        http_client: httpx.AsyncClient,
        account_resolver: AccountResolver,
    ) -> None:
        self._tokens = token_manager
        self._http = http_client
        # account_resolver(account_id) -> LinkedAccount: resolves the id the
        # interface gives us into the full account needed for token + mailbox
        # addressing. Injected so this client never reaches into a store directly.
        self._resolve_account = account_resolver

    async def fetch_new_emails(
        self, account_id: str, since: datetime | None
    ) -> list[GraphEmail]:
        """
        Return all messages received after `since`, with attachments materialized.

        When `since` is None (first ever poll for an account) we fetch the most
        recent page rather than the entire mailbox history — a brand-new link
        should not replay years of mail. When `since` is set, results are bounded
        by a `receivedDateTime ge {since}` filter so the poll only sees genuinely
        new mail.

        Attachments are expanded inline (`$expand=attachments`) so each message
        arrives complete in one round-trip per page; file attachments have their
        base64 `contentBytes` decoded into raw bytes, and non-file attachments
        (item/reference) are skipped because they carry no document payload.

        Paging follows Graph's `@odata.nextLink` until exhausted so a large
        backlog is fully drained in one call.
        """
        account = await self._resolve(account_id)
        token = await self._get_token(account)

        params: dict[str, str] = {
            "$expand": "attachments",
            "$top": str(_PAGE_SIZE),
            "$orderby": "receivedDateTime desc",
        }
        if since is not None:
            # Graph expects an ISO-8601/RFC-3339 timestamp. `isoformat()` on an
            # aware datetime yields exactly that; the filter is server-side so we
            # never download mail older than the watermark.
            params["$filter"] = f"receivedDateTime ge {since.isoformat()}"

        url = f"{_GRAPH_BASE_URL}/users/{account.email_address}/messages"
        emails: list[GraphEmail] = []
        next_link: str | None = None

        try:
            while True:
                # First request uses the built params; subsequent requests follow
                # the server-provided nextLink verbatim (it already encodes the
                # paging cursor and original query options).
                if next_link is None:
                    response = await self._http.get(
                        url, headers=self._auth_header(token), params=params
                    )
                else:
                    response = await self._http.get(
                        next_link, headers=self._auth_header(token)
                    )
                response.raise_for_status()
                payload = response.json()

                for raw in payload.get("value", []) or []:
                    emails.append(self._map_email(raw))

                next_link = payload.get("@odata.nextLink")
                if not next_link:
                    break
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="GRAPH_MAIL",
                message="Failed to fetch new emails from Microsoft Graph",
                context={
                    "account_id": account_id,
                    "since": since.isoformat() if since else None,
                },
                cause=exc,
            )

        return emails

    async def fetch_email(self, account_id: str, message_id: str) -> GraphEmail:
        """
        Re-fetch a single message (with attachments) by id.

        Used by the rejected-email restore flow, which stores only lightweight
        metadata and pulls the full message + attachments on demand when the user
        clicks "Restore" (build doc 8.5).
        """
        account = await self._resolve(account_id)
        token = await self._get_token(account)

        url = f"{_GRAPH_BASE_URL}/users/{account.email_address}/messages/{message_id}"
        try:
            response = await self._http.get(
                url,
                headers=self._auth_header(token),
                params={"$expand": "attachments"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise AppError(
                code="GRAPH_MAIL",
                message="Failed to fetch a single email from Microsoft Graph",
                context={"account_id": account_id, "message_id": message_id},
                cause=exc,
            )

        return self._map_email(payload)

    async def _resolve(self, account_id: str) -> LinkedAccount:
        """Resolve the account id to a LinkedAccount, wrapping resolver failures."""
        try:
            return await self._resolve_account(account_id)
        except Exception as exc:
            raise AppError(
                code="GRAPH_MAIL",
                message="Failed to resolve the linked account",
                context={"account_id": account_id},
                cause=exc,
            )

    async def _get_token(self, account: LinkedAccount) -> str:
        """
        Acquire a Graph bearer token for the account.

        The token manager already wraps its own failures as AppError, so we let
        those propagate unchanged (no double-wrapping) and only translate any
        other surprise into a GRAPH_MAIL error.
        """
        try:
            return await self._tokens.get_access_token(account)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="GRAPH_MAIL",
                message="Failed to acquire a Graph access token",
                context={"account_id": account.id},
                cause=exc,
            )

    @staticmethod
    def _auth_header(token: str) -> dict[str, str]:
        """Build the Bearer auth header used on every Graph request."""
        return {"Authorization": f"Bearer {token}"}

    def _map_email(self, raw: dict) -> GraphEmail:
        """
        Map a Graph message JSON object to a GraphEmail.

        Defensive throughout: Graph omits empty fields, and `from`/`emailAddress`
        nesting can be absent on drafts or system messages, so each lookup falls
        back to a safe default rather than raising — a partially-formed message
        should still flow into the filter, which will decide its fate.
        """
        from_field = (raw.get("from") or {}).get("emailAddress") or {}
        sender_email = from_field.get("address") or ""

        attachments = [
            decoded
            for att in (raw.get("attachments") or [])
            if (decoded := self._map_attachment(att)) is not None
        ]

        return GraphEmail(
            message_id=raw.get("id") or "",
            sender_email=sender_email,
            subject=raw.get("subject") or "",
            body_preview=raw.get("bodyPreview") or "",
            received_at=self._parse_received(raw.get("receivedDateTime")),
            attachments=attachments,
        )

    @staticmethod
    def _map_attachment(att: dict) -> EmailAttachment | None:
        """
        Decode a single Graph attachment, or return None to skip it.

        Only `fileAttachment` entries carry `contentBytes` (base64) — the actual
        document we ingest. `itemAttachment` (an embedded message) and
        `referenceAttachment` (a cloud link) have no inline bytes, so we skip them
        rather than fabricate empty content. A file attachment missing its bytes
        is likewise skipped.
        """
        if att.get("@odata.type") != _FILE_ATTACHMENT_TYPE:
            return None

        content_b64 = att.get("contentBytes")
        if not content_b64:
            return None

        return EmailAttachment(
            filename=att.get("name") or "attachment",
            content_type=att.get("contentType") or "application/octet-stream",
            content_bytes=base64.b64decode(content_b64),
        )

    @staticmethod
    def _parse_received(value: str | None) -> datetime:
        """
        Parse Graph's `receivedDateTime` (RFC-3339, trailing 'Z') to a datetime.

        Graph emits UTC with a 'Z' suffix that `datetime.fromisoformat` did not
        accept before 3.11; normalizing 'Z' to '+00:00' keeps it robust. A
        missing/garbled value falls back to epoch so the model's required field
        is always populated rather than raising on a malformed message.
        """
        if not value:
            return datetime.fromtimestamp(0)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.fromtimestamp(0)
