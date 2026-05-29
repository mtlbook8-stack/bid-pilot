"""
OpenAIFoundryClient — GPT inference via Azure OpenAI on AI Foundry.

Calls GPT models (e.g. gpt-5, used only by the ComparisonOrchestrator router)
through the Azure OpenAI Chat Completions API. Auth is the same managed-identity
Cognitive Services bearer token used by the Anthropic client; the api-version is
supplied as a query parameter from Settings (decision I8) so the contract is
configurable, never hardcoded.
"""

import logging

import httpx
from azure.core.credentials_async import AsyncTokenCredential

from src.api.config import Settings
from src.core.errors.app_error import AppError
from src.core.interfaces.foundry_client import LlmResponse

logger = logging.getLogger(__name__)

# Same data-plane audience as the Anthropic client — Azure OpenAI on Foundry is
# also a Cognitive Services resource.
_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"


class OpenAIFoundryClient:
    """
    IFoundryClient implementation for GPT models on Azure OpenAI.

    Why separate from the Anthropic client: Azure OpenAI uses a different URL
    shape (deployment path + api-version query param), expresses the system
    prompt as a chat message, and reports token usage under
    prompt_tokens/completion_tokens. Isolating that wire protocol here keeps the
    router free of provider details (Rule 2).

    Dependencies are injected (Rule 3) so tests can swap the transport and
    credential.
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
        Acquire a fresh Cognitive Services token via managed identity.

        Per-call acquisition is intentional: azure-identity caches/refreshes
        internally, so this is cheap and never sends a stale token. Wrapped so an
        identity error becomes a typed AppError (Rule 7).
        """
        try:
            token = await self._credential.get_token(_COGNITIVE_SERVICES_SCOPE)
            return token.token
        except Exception as exc:
            raise AppError(
                code="FOUNDRY_OPENAI",
                message="Failed to acquire Azure AD token for OpenAI Foundry",
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
        Call Azure OpenAI Chat Completions once and normalize to LlmResponse.

        The system prompt becomes a system-role message and the user content a
        user-role message (the Chat Completions convention). Token counts are
        mapped from prompt_tokens -> input_tokens and completion_tokens ->
        output_tokens so the rest of the system stays provider-agnostic.

        Every external step is wrapped; failures surface as code "FOUNDRY_OPENAI"
        with context for the single top-level log entry (Rules 7, 8).
        """
        token = await self._get_bearer_token()

        # Azure OpenAI requires the api-version query parameter; it is read from
        # Settings so the contract version can change without code edits.
        url = (
            f"{self._settings.ai_foundry_openai_endpoint.rstrip('/')}"
            f"/openai/deployments/{model}/chat/completions"
            f"?api-version={self._settings.ai_foundry_openai_version}"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response = await self._http.post(url, headers=headers, json=body)
            response.raise_for_status()
        except Exception as exc:
            raise AppError(
                code="FOUNDRY_OPENAI",
                message="OpenAI Foundry HTTP request failed",
                context={"model": model, "url": url},
                cause=exc,
            )

        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
            usage = payload["usage"]
            return LlmResponse(
                text=text,
                model=payload.get("model", model),
                input_tokens=usage["prompt_tokens"],
                output_tokens=usage["completion_tokens"],
            )
        except Exception as exc:
            raise AppError(
                code="FOUNDRY_OPENAI",
                message="Could not parse OpenAI Foundry response",
                context={"model": model},
                cause=exc,
            )
