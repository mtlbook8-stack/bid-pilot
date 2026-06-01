"""
AnthropicFoundryClient — Claude inference via Azure AI Foundry.

Calls Claude (e.g. claude-sonnet-4-6) through Azure AI Foundry's Anthropic
Messages API. Authentication uses a managed-identity bearer token for the
Cognitive Services scope rather than a static key, so no secret ever lives in
config. The anthropic-version header is read from Settings (decision I8) so the
API contract can change without a code edit.
"""

import logging

import httpx
from azure.core.credentials_async import AsyncTokenCredential

from src.api.config import Settings
from src.core.errors.app_error import AppError
from src.core.interfaces.foundry_client import LlmResponse

logger = logging.getLogger(__name__)

# Token audience for all Azure AI / Cognitive Services data-plane calls. The
# same scope is used by both the Anthropic and OpenAI Foundry clients.
_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"


class AnthropicFoundryClient:
    """
    IFoundryClient implementation for Claude models on Azure AI Foundry.

    Why a dedicated client (vs one generic client): the Anthropic Messages API
    and Azure OpenAI Chat Completions API have different request/response
    shapes, auth header placement, and version mechanisms. Keeping them apart
    (Rule 2) lets the router (FoundryClientRouter) dispatch on model name while
    each client owns exactly one wire protocol.

    Dependencies are injected (Rule 3): the HTTP client, the credential, and
    settings all arrive through the constructor so tests can substitute fakes.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        credential: AsyncTokenCredential,
        settings: Settings,
    ) -> None:
        self._http = http_client
        self._credential = credential
        self._settings = settings

    async def _get_bearer_token(self) -> str:
        """
        Fetch a fresh Cognitive Services access token.

        Why per-call: azure-identity caches and refreshes tokens internally, so
        calling get_token each request is cheap and guarantees we never send an
        expired token. Wrapped so an identity failure surfaces as a typed
        AppError instead of an opaque azure-core exception.
        """
        try:
            token = await self._credential.get_token(_COGNITIVE_SERVICES_SCOPE)
            return token.token
        except Exception as exc:
            raise AppError(
                code="FOUNDRY_ANTHROPIC",
                message="Failed to acquire Azure AD token for Anthropic Foundry",
                context={"scope": _COGNITIVE_SERVICES_SCOPE},
                cause=exc,
            )

    async def get_completion(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> LlmResponse:
        """
        Call the Anthropic Messages API once and normalize the result.

        The system prompt is passed as the top-level `system` field (the
        Anthropic convention) rather than as a message, and the user content is
        the single user-role message. Token usage is read from
        `usage.input_tokens`/`usage.output_tokens` so TelemetryService can
        estimate cost without knowing the provider.

        Every external interaction (token, HTTP POST, JSON parse) is wrapped so
        no failure is silent (Rule 7) and all surface as code "FOUNDRY_ANTHROPIC"
        with enough context to debug from the single top-level log entry.
        """
        token = await self._get_bearer_token()

        # Anthropic Messages API contract. anthropic-version is configurable so a
        # provider API bump is a settings change, not a redeploy of code.
        # Azure Foundry hosts Anthropic models under /anthropic/v1/messages with
        # an Azure-side ?api-version query string (distinct from anthropic-version).
        url = (
            f"{self._settings.ai_foundry_endpoint.rstrip('/')}"
            "/anthropic/v1/messages?api-version=2024-08-01-preview"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-version": self._settings.ai_foundry_anthropic_version,
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response = await self._http.post(url, headers=headers, json=body)
            response.raise_for_status()
        except Exception as exc:
            raise AppError(
                code="FOUNDRY_ANTHROPIC",
                message="Anthropic Foundry HTTP request failed",
                context={"model": model, "url": url},
                cause=exc,
            )

        try:
            payload = response.json()
            # content is a list of blocks; the first text block holds the answer.
            text = payload["content"][0]["text"]
            usage = payload["usage"]
            return LlmResponse(
                text=text,
                model=payload.get("model", model),
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            )
        except Exception as exc:
            raise AppError(
                code="FOUNDRY_ANTHROPIC",
                message="Could not parse Anthropic Foundry response",
                context={"model": model},
                cause=exc,
            )
