"""CosmosRuleStore — IRuleStore backed by the `learned-rules` container."""

from azure.cosmos.aio import ContainerProxy

from src.core.errors.app_error import AppError
from src.core.models.correction import LearnedRule


class CosmosRuleStore:
    """
    Cosmos-backed persistence for `LearnedRule` (implements IRuleStore).

    Partition key is `/agentName` (build doc 6.1), so fetching all of an agent's
    active rules — which BaseAgent does on every run to fill the `{learned_rules}`
    prompt slot — is a single-partition query rather than a fan-out. Container
    injected (Rule 3); every SDK call wrapped and re-raised as an AppError
    (Rule 8); the store itself never logs.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the already-resolved `learned-rules` container proxy (Rule 3)."""
        self._container = container

    async def list_active_for_agent(self, agent_name: str) -> list[LearnedRule]:
        """
        Return an agent's active learned rules.

        Single-partition query on `/agentName` filtered by `is_active`: this runs
        before the agent's LLM call, so keeping it scoped to one partition keeps
        the per-run overhead minimal. Inactive rules are excluded so a retired
        rule stops influencing the prompt without being deleted (audit trail).
        """
        query = "SELECT * FROM c WHERE c.agent_name = @name AND c.is_active = true"
        params = [{"name": "@name", "value": agent_name}]
        try:
            items = self._container.query_items(
                query=query,
                parameters=params,
                partition_key=agent_name,
            )
            return [LearnedRule.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_RULE_LIST_ACTIVE_FOR_AGENT",
                message="Failed to list active rules for agent",
                context={"agent_name": agent_name},
                cause=e,
            )

    async def upsert(self, rule: LearnedRule) -> LearnedRule:
        """
        Insert or replace a learned rule. Serialized with `by_alias` + JSON mode
        so timestamps/enums become Cosmos-safe primitives and the persisted field
        names match the snake_case references the query above uses.
        """
        try:
            body = rule.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return LearnedRule.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_RULE_UPSERT",
                message="Failed to upsert learned rule",
                context={"rule_id": rule.id, "agent_name": rule.agent_name},
                cause=e,
            )
