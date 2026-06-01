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

import base64
import logging
import uuid
from urllib.parse import urlencode

import msal
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

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

# Delegated Graph scopes for reading mail. MSAL automatically requests
# offline_access (and openid/profile), so we must NOT include them explicitly
# or AAD rejects the token request as containing reserved scopes.
_LINK_SCOPES = ["https://graph.microsoft.com/Mail.Read"]


def _encode_state(spa_user_id: str) -> str:
    nonce = uuid.uuid4().hex
    raw = f"{nonce}.{spa_user_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_state(state: str | None) -> str | None:
    if not state:
        return None
    try:
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        _, _, spa_user_id = raw.partition(".")
        return spa_user_id or None
    except Exception:
        return None


class _OAuthHelper:
    """
    Builds the authorize URL and exchanges codes, isolating MSAL here (Rule 2).

    A small helper so the route functions stay thin: it owns the authority/redirect
    construction and the synchronous MSAL call. Constructed per request from the
    container's settings (cheap; no network until a call is made).
    """

    def __init__(self, settings) -> None:
        self._settings = settings
        # Multi-tenant by design: each linked mailbox lives in its OWN home
        # tenant (e.g. anyexcel + vetdist). Forcing the BidPilot tenant here
        # makes guest-user sign-ins issue tokens with tid=bidpilot, which then
        # 404 on /users/{their-upn}/messages. /common lets MSAL route the user
        # to their home tenant so the issued token addresses their real mailbox.
        self._authority = "https://login.microsoftonline.com/common"

    @property
    def _redirect_uri(self) -> str:
        """Where Microsoft sends the user back with the auth code."""
        # Prefer the explicit API base URL. Fall back to deriving from the
        # webhook URL's origin for backward compatibility, then to a relative
        # path the SPA can resolve when no base is configured (dev).
        base = self._settings.api_base_url or self._settings.webhook_notification_url
        if base:
            origin = base.split("/api/")[0].rstrip("/")
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
    user: UserContext = Depends(get_current_user),
    container: AppContainer = Depends(get_container),
) -> dict:
    """
    Return the Microsoft OAuth authorize URL for linking a mailbox.

    The SPA opens this URL so the user consents to mailbox access. The OAuth
    `state` embeds the SPA user's oid so the callback can attribute the new
    LinkedAccount to the BidPilot user — not the oid from the mailbox's home
    tenant (which differs for cross-tenant guest scenarios like vetdist).
    """
    helper = _OAuthHelper(container.settings)
    state = _encode_state(user.user_id)
    return {"authorizeUrl": helper.authorize_url(state), "state": state}


def _frontend_redirect(settings, status: str, detail: str | None = None) -> RedirectResponse:
    """
    Build a 302 back to the SPA's /email-accounts page with status query params.

    The browser navigation that started the OAuth flow ends here, so the
    callback MUST redirect (not return JSON) to land the user back in the app.
    A `status=ok|error` query param lets the SPA toast success/failure without
    needing a second round-trip; `detail` carries a short, non-sensitive
    AAD error code when available.
    """
    base = (settings.frontend_url or "").rstrip("/") or "/"
    params = {"linked": status}
    if detail:
        params["detail"] = detail
    sep = "?" if "?" not in base else "&"
    return RedirectResponse(
        url=f"{base}/email-accounts{sep}{urlencode(params)}",
        status_code=303,
    )


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str | None = Query(None),
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    """
    Exchange the OAuth `code`, persist the refresh token, create a LinkedAccount,
    then redirect the browser back to the SPA.

    Flow:
      1. Exchange the code for tokens via MSAL.
      2. Read the mailbox identity from the id-token claims (preferred_username).
      3. Store the refresh token in Key Vault under a per-account secret name.
      4. Upsert a LinkedAccount pointing at that secret.
      5. Best-effort Graph subscription, then 303 redirect to the SPA.

    Idempotency: browsers (Edge in particular) may prefetch the callback URL,
    causing AAD to redeem the same code twice and return AADSTS54005/70008 on
    the second hit. We treat those as a benign duplicate and still redirect to
    the SPA with `linked=ok` so the user sees the just-created account rather
    than an error page.
    """
    helper = _OAuthHelper(container.settings)
    try:
        result = helper.exchange_code(code)
    except Exception as exc:
        logger.warning("OAuth code exchange raised", exc_info=True)
        return _frontend_redirect(container.settings, "error", "exchange_failed")

    if not result or "refresh_token" not in result:
        aad_error = (result or {}).get("error") or ""
        # Browser prefetch redeems the code first, so the real user request gets
        # "already redeemed" / "expired" — the account was created on the prefetch
        # request. Redirect to the SPA so the user sees the linked account.
        if aad_error == "invalid_grant":
            logger.info(
                "OAuth callback received already-redeemed code (likely prefetch); "
                "redirecting to SPA",
            )
            return _frontend_redirect(container.settings, "ok")
        logger.warning(
            "OAuth exchange returned no refresh token: %s / %s",
            aad_error,
            (result or {}).get("error_description"),
        )
        return _frontend_redirect(container.settings, "error", aad_error or "no_token")

    claims = result.get("id_token_claims") or {}
    email = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
        or ""
    )
    # Attribute the linked account to the BidPilot SPA user (carried in state),
    # not the oid from the mailbox's home tenant — those differ in cross-tenant
    # link flows and would otherwise hide the account from the SPA's list view.
    spa_user_id = _decode_state(state)
    user_id = spa_user_id or claims.get("oid") or claims.get("sub") or email
    if not email:
        logger.warning("OAuth token did not identify a mailbox")
        return _frontend_redirect(container.settings, "error", "no_mailbox")

    account_id = uuid.uuid4().hex
    secret_name = f"refresh-token-{account_id}"

    try:
        await container.secret_store.set_secret(secret_name, result["refresh_token"])
    except Exception:
        logger.exception("Failed to persist mailbox refresh token %s", secret_name)
        return _frontend_redirect(container.settings, "error", "persist_failed")

    account = LinkedAccount(
        id=account_id,
        user_id=user_id,
        email_address=email,
        token_secret_name=secret_name,
    )
    account = await container.linked_account_store.upsert(account)

    # Best-effort Graph webhook subscription so new mail is pushed to us.
    # Falls back to polling if subscription fails (e.g. notification URL
    # unreachable, tenant policy, etc.).
    try:
        sub = await container.webhook_manager.create_subscription(account)
        sub_id = sub.get("id") if isinstance(sub, dict) else None
        if sub_id:
            account.webhook_subscription_id = sub_id
            account = await container.linked_account_store.upsert(account)
    except Exception:
        logger.warning(
            "Webhook subscription creation failed for %s; falling back to polling",
            account_id,
            exc_info=True,
        )

    return _frontend_redirect(container.settings, "ok")


@router.get("/me")
async def me(user: UserContext = Depends(get_current_user)) -> UserContext:
    """Return the authenticated user's context (id + email)."""
    return user
