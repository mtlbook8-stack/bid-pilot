"""IFoundryClient — contract for LLM inference via Azure AI Foundry."""

from typing import Protocol

from pydantic import BaseModel


class LlmResponse(BaseModel):
    """
    Normalized completion result. Both the Anthropic and OpenAI Foundry clients
    return this shape so BaseAgent and TelemetryService are model-agnostic.
    """

    text: str
    model: str
    input_tokens: int
    output_tokens: int


class IFoundryClient(Protocol):
    """
    Single-completion interface. The router implementation dispatches to the
    Anthropic or OpenAI client based on the model name prefix (claude-* vs gpt-*).
    """

    async def get_completion(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> LlmResponse: ...
