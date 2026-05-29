"""
Entra ID JWT validation for the API (build doc decision C2).

WHY this exists: every protected route must run as an authenticated user so
telemetry and per-user data are attributable. This module owns the ONE place
that turns an inbound `Authorization: Bearer <jwt>` header into a `UserContext`.
It validates the token against Microsoft Entra ID: it fetches the tenant's JWKS
(cached), verifies the RS256 signature, and checks the audience
(`settings.entra_client_id`) and issuer. A bad/absent token is a client problem,
so it raises `fastapi.HTTPException(401)` (FastAPI answers it directly) rather
than an AppError (which would become a 500).

Dev mode: when `settings.entra_tenant_id` is empty there is no tenant to validate
against, so the validator accepts an `X-Dev-User` header naming the user id. This
is DEV-ONLY — it exists so the SPA + API can run against local/dev resources
without a full Entra app registration. In any deployed environment the tenant id
is always set, which disables this path entirely.
"""

import logging
import time

import httpx
import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from src.api.config import Settings, get_settings
from src.core.models.base import CamelModel

logger = logging.getLogger(__name__)

# How long a fetched JWKS is trusted before refetch. Entra rotates signing keys
# infrequently; an hour balances freshness against hammering the discovery URL.
_JWKS_TTL_SECONDS = 3600


class UserContext(CamelModel):
    """
    The authenticated principal for one request.

    Small, deliberately: routes only need a stable user id (for per-user data
    partitioning) and the email (for display + linking accounts). Populated by
    `get_current_user` from validated token claims (or the dev header).
    """

    user_id: str
    email: str


class EntraTokenValidator:
    """
    Validates Entra ID bearer tokens and produces a UserContext.

    One job (Rule 2): authentication. It owns a cached `PyJWKClient` per tenant so
    signing keys are fetched once and reused across requests, and exposes a single
    `validate` that either returns a UserContext or raises HTTPException(401). The
    dev-mode branch (empty tenant) is contained here so callers never special-case
    it.
    """

    def __init__(self, settings: Settings) -> None:
        # Pure config in; no network resources opened at construction (Rule 3).
        self._settings = settings
        self._jwks_client: PyJWKClient | None = None
        self._jwks_fetched_at: float = 0.0

    @property
    def _dev_mode(self) -> bool:
        """True when no tenant is configured — accept the X-Dev-User header."""
        return not self._settings.entra_tenant_id

    @property
    def _issuer(self) -> str:
        """The expected token issuer for the configured tenant (v2.0 endpoint)."""
        return (
            f"https://login.microsoftonline.com/"
            f"{self._settings.entra_tenant_id}/v2.0"
        )

    @property
    def _jwks_uri(self) -> str:
        """Tenant JWKS discovery URL (build doc auth section)."""
        return (
            f"https://login.microsoftonline.com/"
            f"{self._settings.entra_tenant_id}/discovery/v2.0/keys"
        )

    def _get_jwks_client(self) -> PyJWKClient:
        """
        Return a cached PyJWKClient, refetching keys after the TTL expires.

        PyJWKClient does its own per-key caching, but we additionally bound the
        client's lifetime so a key rotation is eventually picked up without a
        process restart. This is the only network dependency of validation.
        """
        now = time.monotonic()
        if (
            self._jwks_client is None
            or (now - self._jwks_fetched_at) > _JWKS_TTL_SECONDS
        ):
            self._jwks_client = PyJWKClient(self._jwks_uri)
            self._jwks_fetched_at = now
        return self._jwks_client

    def validate(self, request: Request) -> UserContext:
        """
        Authenticate `request` and return its UserContext.

        Dev mode (no tenant configured): trust the `X-Dev-User` header as the user
        id. Otherwise: extract the Bearer token, verify its signature against the
        tenant JWKS, and check audience + issuer. Any failure raises
        HTTPException(401) — an unauthenticated request is a client problem, not a
        server fault, so it must not flow into the AppError 500 path.
        """
        if self._dev_mode:
            return self._dev_user(request)

        token = self._extract_bearer(request)
        try:
            signing_key = self._get_jwks_client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._settings.entra_client_id,
                issuer=self._issuer,
            )
        except HTTPException:
            raise
        except Exception as exc:
            # Do NOT wrap as AppError: a token problem is a 401, and we must not
            # leak validation detail to the client. The reason is logged for ops.
            logger.warning("Token validation failed: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return self._user_from_claims(claims)

    @staticmethod
    def _extract_bearer(request: Request) -> str:
        """Pull the raw token from the Authorization header or 401."""
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=401, detail="Missing bearer token"
            )
        return token.strip()

    @staticmethod
    def _dev_user(request: Request) -> UserContext:
        """
        Build a UserContext from the dev-only X-Dev-User header.

        Used solely when no tenant is configured. A missing header is still a 401
        so dev requests must explicitly identify themselves, mirroring prod.
        """
        dev_user = request.headers.get("X-Dev-User", "").strip()
        if not dev_user:
            raise HTTPException(
                status_code=401,
                detail="X-Dev-User header required in dev mode",
            )
        return UserContext(user_id=dev_user, email=dev_user)

    @staticmethod
    def _user_from_claims(claims: dict) -> UserContext:
        """
        Map validated Entra claims onto a UserContext.

        `oid` is the stable per-tenant object id (preferred user id — it never
        changes even if the email does); `sub` is the fallback. Email comes from
        the `preferred_username`/`email`/`upn` claims in priority order.
        """
        user_id = claims.get("oid") or claims.get("sub") or ""
        email = (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("upn")
            or ""
        )
        if not user_id:
            raise HTTPException(
                status_code=401, detail="Token missing subject claim"
            )
        return UserContext(user_id=user_id, email=email)


# Module-level validator singleton. The validator holds only the cached JWKS
# client and immutable settings, so a single instance is safe to share across
# requests and avoids re-fetching signing keys per call (Rule 5).
_validator = EntraTokenValidator(get_settings())


def get_current_user(request: Request) -> UserContext:
    """
    FastAPI dependency that resolves the authenticated user for a request.

    Thin wrapper over the shared `EntraTokenValidator` so routers can simply
    `Depends(get_current_user)`. Kept as a function (the FastAPI DI convention)
    while all logic lives in the validator class (Rule 1/2).
    """
    return _validator.validate(request)
