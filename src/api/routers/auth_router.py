"""
/api/auth — Microsoft OAuth for linking a mailbox + current-user info.

Thin router (Rule 2). Three endpoints:
  - GET /login    return the Microsoft OAuth authorize URL (the SPA redirects the
                  user there to consent to mailbox access).
  - GET /callback exchange the returned `?code` for tokens via MSAL, persist the
                  refresh token to Key Vault, and create a LinkedAccount.
  - GET /me       return the authenticated UserContext.

OAuth simplification (documented): the authorize-URL build and the code->token
exchange are done inline here with MSAL's ConfidentialClientApplication rather
than extending the GraphTokenManager (which only handles the refresh-token grant
used by the pollers). `state` is not cryptographically validated here — in a full
implementation the SPA would generate + verify a CSRF `state`; this endpoint
accepts and echoes it but does not persist it. `/login` and `/callback` are NOT
behind the auth dependency (the user is not yet authenticated to BidPilot when
linking), so they are mounted without `get_current_user`.
"""

import logging
import uuid
from urllib.parse import urlencode

import msal
from fastapi import APIRouter, Depends, Query

from src.api.dependencies import (
    UserContext,
    get_container,
    get_current_user,
)
from src.composition.container import AppContainer
from src.core.errors.app_error import AppError
from src.core.models.linked_account import LinkedAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Delegated Graph scopes for reading mail. offline_access yields a refresh token
# so the pollers can run without the user present (build doc instruction 9).
_LINK_SCOPES = ["offline_access", "https://graph.microsoft.com/Mail.Read"]


class _OAuthHelper:
    """
    Builds the authorize URL and exchanges codes, isolating MSAL here (Rule 2).

    A small helper so the route functions stay thin: it owns the authority/redirect
    construction and the synchronous MSAL call. Constructed per request from the
    container's settings (cheap; no network until a call is made).
    """

    def __init__(self, settings) -> None:
        self._settings = settings
        self._authority = (
            f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
            if settings.entra_tenant_id
            else "https://login.microsoftonline.com/common"
        )

    @property
    def _redirect_uri(self) -> str:
        """Where Microsoft sends the user back with the auth code."""
        # The webhook_notification_url shares the API base; derive the callback
        # from the configured client by convention. Falls back to a relative path
        # the SPA can resolve when no base is configured (dev).
        base = self._settings.webhook_notification_url
        if base:
            origin = base.split("/api/")[0]
            return f"{origin}/api/auth/callback"
        return "/api/auth/callback"

    def authorize_url(self, state: str) -> str:
        """Construct the Microsoft authorize URL the SPA redirects to."""
        params = {
            "client_id": self._settings.entra_client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "response_mode": "query",
            "scope": " ".join(_LINK_SCOPES),
            "state": state,
        }
        return f"{self._authority}/oauth2/v2.0/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """
        Exchange an auth code for tokens via MSAL (synchronous call).

        Returns MSAL's raw result dict. MSAL signals failure by omitting
        "access_token" rather than raising, so the caller must inspect the payload
        (Rule 7).
        """
        app = msal.ConfidentialClientApplication(
            client_id=self._settings.entra_client_id,
            client_credential=self._settings.entra_client_secret,
            authority=self._authority,
        )
        return app.acquire_token_by_authorization_code(
            code, scopes=_LINK_SCOPES, redirect_uri=self._redirect_uri
        )


@router.get("/login")
async def login(
    container: AppContainer = Depends(get_container),
) -> dict:
    """
    Return the Microsoft OAuth authorize URL for linking a mailbox.

    The SPA opens this URL so the user consents to mailbox access. A random
    `state` is included for the SPA to round-trip; see the module note on the CSRF
    simplification.
    """
    helper = _OAuthHelper(container.settings)
    state = uuid.uuid4().hex
    return {"authorizeUrl": helper.authorize_url(state), "state": state}


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str | None = Query(None),
    container: AppContainer = Depends(get_container),
) -> dict:
    """
    Exchange the OAuth `code`, persist the refresh token, create a LinkedAccount.

    Flow:
      1. Exchange the code for tokens via MSAL.
      2. Read the mailbox identity from the id-token claims (preferred_username).
      3. Store the refresh token in Key Vault under a per-account secret name.
      4. Upsert a LinkedAccount pointing at that secret.

    Returns the created account. A missing token in MSAL's result is surfaced as
    an AppError with AAD's own error description (without leaking the tokens).
    """
    helper = _OAuthHelper(container.settings)
    try:
        result = helper.exchange_code(code)
    except Exception as exc:
        raise AppError(
            code="AUTH_CODE_EXCHANGE",
            message="Failed to exchange the OAuth authorization code",
            cause=exc,
        )

    if not result or "refresh_token" not in result:
        raise AppError(
            code="AUTH_NO_REFRESH_TOKEN",
            message="OAuth exchange returned no refresh token",
            context={
                "error": (result or {}).get("error"),
                "error_description": (result or {}).get("error_description"),
            },
        )

    claims = result.get("id_token_claims") or {}
    email = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
        or ""
    )
    user_id = claims.get("oid") or claims.get("sub") or email
    if not email:
        raise AppError(
            code="AUTH_NO_MAILBOX_IDENTITY",
            message="OAuth token did not identify a mailbox",
        )

    account_id = uuid.uuid4().hex
    secret_name = f"refresh-token-{account_id}"

    try:
        await container.secret_store.set_secret(secret_name, result["refresh_token"])
    except Exception as exc:
        raise AppError(
            code="AUTH_PERSIST_TOKEN",
            message="Failed to persist the mailbox refresh token",
            context={"secret_name": secret_name},
            cause=exc,
        )

    account = LinkedAccount(
        id=account_id,
        user_id=user_id,
        email_address=email,
        token_secret_name=secret_name,
    )
    return await container.linked_account_store.upsert(account)


@router.get("/me")
async def me(user: UserContext = Depends(get_current_user)) -> UserContext:
    """Return the authenticated user's context (id + email)."""
    return user
