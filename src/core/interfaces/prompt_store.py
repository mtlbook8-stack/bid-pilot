"""IPromptStore — persistence contract for versioned prompt templates."""

from typing import Protocol

from src.core.models.prompt import PromptTemplate


class IPromptStore(Protocol):
    """Partition key `/agentName`. Exactly one active version per agent."""

    async def get_active(self, agent_name: str) -> PromptTemplate | None: ...

    async def get_all_active(self) -> list[PromptTemplate]: ...

    async def upsert(self, prompt: PromptTemplate) -> PromptTemplate: ...
