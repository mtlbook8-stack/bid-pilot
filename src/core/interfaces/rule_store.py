"""IRuleStore — persistence contract for learned rules."""

from typing import Protocol

from src.core.models.correction import LearnedRule


class IRuleStore(Protocol):
    """Partition key `/agentName`, so a single query fetches an agent's rules."""

    async def list_active_for_agent(self, agent_name: str) -> list[LearnedRule]: ...

    async def upsert(self, rule: LearnedRule) -> LearnedRule: ...
