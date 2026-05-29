"""
FoundryClientRouter — dispatches a completion to the right provider client.

BaseAgent depends on a single IFoundryClient and should not know whether a given
model is a Claude or a GPT deployment. This router resolves that at call time by
inspecting the model name prefix, so adding model versions never touches agent
code (Rule 5: one dispatch point instead of provider checks scattered around).
"""

import logging

from src.core.errors.app_error import AppError
from src.core.interfaces.foundry_client import IFoundryClient, LlmResponse

logger = logging.getLogger(__name__)

# GPT deployments are the only non-Claude models in the system (the
# ComparisonOrchestrator router uses gpt-5). Anything else is a Claude model.
_OPENAI_PREFIX = "gpt-"


class FoundryClientRouter:
    """
    IFoundryClient implementation that fans out to provider-specific clients.

    Routing is by model-name prefix: "gpt-*" goes to the OpenAI client, every
    other name (the "claude-*" family) goes to the Anthropic client. Both
    delegates implement IFoundryClient, so the router itself satisfies the same
    contract and is a drop-in dependency for BaseAgent.

    Dependencies are injected (Rule 3); the router never constructs the clients.
    """

    def __init__(
        self,
        anthropic_client: IFoundryClient,
        openai_client: IFoundryClient,
    ) -> None:
        self._anthropic_client = anthropic_client
        self._openai_client = openai_client

    def _resolve_client(self, model: str) -> IFoundryClient:
        """
        Select the provider client for a model name.

        We match on a prefix rather than an exact allow-list so new model
        versions (gpt-5, gpt-4.1-mini, claude-sonnet-4-6, claude-sonnet-4-5,
        future revisions) route correctly without a code change. An empty/unknown
        model name is the only unroutable case and raises so the failure is never
        silent (Rule 7).
        """
        if not model:
            raise AppError(
                code="FOUNDRY_ROUTER",
                message="Cannot route completion: empty model name",
                context={"model": model},
            )
        if model.startswith(_OPENAI_PREFIX):
            return self._openai_client
        # Default to Anthropic — all remaining models are the Claude family.
        return self._anthropic_client

    async def get_completion(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> LlmResponse:
        """
        Route to the correct provider client and return its LlmResponse.

        The router adds no wire logic of its own; it only selects the delegate.
        Provider clients raise their own typed AppErrors (FOUNDRY_ANTHROPIC /
        FOUNDRY_OPENAI), which propagate unchanged so the original code and
        context are preserved up the chain.
        """
        client = self._resolve_client(model)
        return await client.get_completion(
            model=model,
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
        )
