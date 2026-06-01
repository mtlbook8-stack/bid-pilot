"""
GraphTokenManager — Microsoft Graph OAuth refresh-token exchange via MSAL.

Each linked mailbox was connected once through the interactive OAuth consent
flow, which yielded a long-lived refresh token stored in Key Vault (the
LinkedAccount only holds `token_secret_name`, a pointer to that secret). To call
Graph on the user's behalf this manager exchanges the stored refresh token for a
short-lived access token, and persists any rotated refresh token Azure AD hands
back so the next exchange keeps working.

MSAL's `ConfidentialClientApplication` is synchronous, so every MSAL call is run
on a worker thread via `asyncio.to_thread` to avoid blocking the event loop in
the async API/worker host. Every external interaction (secret read/write, token
acquisition) is wrapped and re-raised as AppError "GRAPH_TOKEN" (Rules 7/8); the
manager never logs.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import msal

from src.api.config import Settings
from src.core.errors.app_error import AppError
from src.core.models.linked_account import LinkedAccount

logger = logging.getLogger(__name__)

# Type aliases for the injected secret-store callables. They are async because
# the real implementation talks to Key Vault over the network; making the
# contract async keeps the manager non-blocking end to end.
SecretReader = Callable[[str], Awaitable[str]]
SecretWriter = Callable[[str, str], Awaitable[None]]


class GraphTokenManager:
    """
    Acquires Microsoft Graph access tokens from stored per-mailbox refresh tokens.

    Why it exists: Graph calls need a fresh access token, but BidPilot must never
    hold the user's password or re-prompt for consent on every poll. The OAuth
    refresh-token grant is the supported way to get an access token silently, and
    Azure AD may rotate the refresh token on each exchange — if we drop the
    rotated value, the mailbox silently stops working a few days later. This
    class owns that exchange-and-persist cycle so callers (GraphMailClient,
    GraphWebhookManager) just ask for a token.

    Dependencies are injected (Rule 3): `settings` supplies the Entra app
    registration (client id/secret/tenant), and the two callables read/write the
    refresh-token secret. Rather than define a new interface here (which would
    add a second public type to this file and break Rule 4), the secret store is
    expressed as plain async callables, documented below.

    secret_reader(secret_name) -> str:
        Returns the current refresh token stored under `secret_name`.
    secret_writer(secret_name, value) -> None:
        Overwrites the secret under `secret_name` with a rotated refresh token.
    """

    def __init__(
        self,
        settings: Settings,
        secret_reader: SecretReader,
        secret_writer: SecretWriter,
    ) -> None:
        self._settings = settings
        self._secret_reader = secret_reader
        self._secret_writer = secret_writer
        # The MSAL client is built lazily on first use, not here. Why: the
        # composition root constructs this manager unconditionally at startup, but
        # a dev/no-email deployment may run with empty Entra settings (the API's
        # dev-auth mode). Eagerly building MSAL with an empty tenant raises and
        # would block the whole app from starting; deferring construction means
        # only an actual Graph call fails when email integration is unconfigured.
        self._app: msal.ConfidentialClientApplication | None = None

    def _get_app(self) -> msal.ConfidentialClientApplication:
        """
        Build (once) and return the MSAL confidential client.

        The authority encodes the tenant; the client id/secret authenticate
        BidPilot's app registration so Azure AD trusts the refresh-token exchange.
        Constructed on first use so an unconfigured deployment fails only when it
        actually tries to use Graph (see __init__).
        """
        if self._app is None:
            try:
                # Multi-tenant by design: refresh tokens were issued under each
                # linked user's HOME tenant (anyexcel, vetdist, ...). /common
                # lets MSAL route the refresh exchange to that tenant; pinning
                # to BidPilot's tenant here would invalidate every cross-tenant
                # mailbox.
                self._app = msal.ConfidentialClientApplication(
                    client_id=self._settings.entra_client_id,
                    client_credential=self._settings.entra_client_secret,
                    authority="https://login.microsoftonline.com/common",
                )
            except Exception as exc:
                raise AppError(
                    code="GRAPH_TOKEN",
                    message="Failed to initialize the MSAL confidential client",
                    context={},
                    cause=exc,
                )
        return self._app

    async def get_access_token(self, account: LinkedAccount) -> str:
        """
        Return a valid Graph access token for `account`.

        Flow:
        1. Read the stored refresh token from the secret store (Key Vault).
        2. Exchange it for an access token via MSAL on a worker thread.
        3. If Azure AD returned a NEW refresh token, persist it before returning
           so the rotation is not lost.

        The configured `graph_scopes` setting is a space-delimited string; the
        refresh-token grant expects a list of resource scopes, so it is split
        here. A non-`.default` scope set would also work, but `.default` requests
        exactly the permissions the app registration was consented for.
        """
        secret_name = account.token_secret_name

        try:
            refresh_token = await self._secret_reader(secret_name)
        except Exception as exc:
            raise AppError(
                code="GRAPH_TOKEN",
                message="Failed to read the stored refresh token",
                context={"account_id": account.id, "secret_name": secret_name},
                cause=exc,
            )

        scopes = [s for s in self._settings.graph_scopes.split() if s]

        try:
            # MSAL is synchronous and does network I/O; offload to a thread so the
            # event loop stays responsive for other concurrent account polls.
            result = await self._to_thread_acquire(refresh_token, scopes)
        except Exception as exc:
            raise AppError(
                code="GRAPH_TOKEN",
                message="MSAL refresh-token exchange failed",
                context={"account_id": account.id, "scopes": scopes},
                cause=exc,
            )

        # MSAL signals failure by returning a dict WITHOUT "access_token" (it does
        # not raise on auth errors), so we must inspect the payload explicitly to
        # avoid a silent failure (Rule 7).
        if not result or "access_token" not in result:
            raise AppError(
                code="GRAPH_TOKEN",
                message="MSAL returned no access token for the refresh grant",
                context={
                    "account_id": account.id,
                    # Surface AAD's own error code/description for diagnosis without
                    # leaking the tokens themselves.
                    "error": (result or {}).get("error"),
                    "error_description": (result or {}).get("error_description"),
                },
            )

        # Azure AD rotates refresh tokens: when a new one comes back we MUST store
        # it, otherwise the old token is invalidated and the mailbox breaks on the
        # next poll. Only write when it actually changed to avoid needless Key
        # Vault versions.
        rotated = result.get("refresh_token")
        if rotated and rotated != refresh_token:
            try:
                await self._secret_writer(secret_name, rotated)
            except Exception as exc:
                raise AppError(
                    code="GRAPH_TOKEN",
                    message="Failed to persist the rotated refresh token",
                    context={"account_id": account.id, "secret_name": secret_name},
                    cause=exc,
                )

        return result["access_token"]

    async def _to_thread_acquire(
        self, refresh_token: str, scopes: list[str]
    ) -> dict:
        """
        Run the blocking MSAL `acquire_token_by_refresh_token` on a worker thread.

        Isolated into its own method so the offload boundary is explicit and the
        surrounding async logic in `get_access_token` reads linearly.
        """
        return await asyncio.to_thread(
            self._get_app().acquire_token_by_refresh_token,
            refresh_token,
            scopes=scopes,
        )
