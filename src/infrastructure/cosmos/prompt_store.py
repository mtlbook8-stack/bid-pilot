"""CosmosPromptStore — IPromptStore backed by the `prompts` container."""

from azure.cosmos.aio import ContainerProxy

from src.core.errors.app_error import AppError
from src.core.models.prompt import PromptTemplate


class CosmosPromptStore:
    """
    Cosmos-backed persistence for `PromptTemplate` (implements IPromptStore).

    Partition key `/agentName`; exactly one version per agent is active at a time
    (build doc 6.3), so `get_active` filters a single partition on `is_active`.
    The `PromptTemplate.model_config_` field serializes/deserializes through its
    `modelConfig` alias — `by_alias=True` on dump and `populate_by_name` on the
    model keep round-trips lossless. Container injected (Rule 3); SDK calls wrapped
    (Rule 8); no logging in the store.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the already-resolved `prompts` container proxy (Rule 3)."""
        self._container = container

    async def get_active(self, agent_name: str) -> PromptTemplate | None:
        """
        Return the single active prompt for an agent, or None if none is active.

        Single-partition query on `/agentName`. The stored field names are the
        model's snake_case names (`agent_name`, `is_active`): `by_alias=True` only
        renames fields that declare an alias, and only `model_config_` does
        (`modelConfig`) — all other fields dump under their snake_case names.
        """
        query = (
            "SELECT * FROM c WHERE c.agent_name = @name AND c.is_active = true"
        )
        params = [{"name": "@name", "value": agent_name}]
        try:
            items = self._container.query_items(
                query=query,
                parameters=params,
                partition_key=agent_name,
            )
            async for item in items:
                # At most one active version per agent — return the first.
                return PromptTemplate.model_validate(item)
            return None
        except Exception as e:
            raise AppError(
                code="STORE_PROMPT_GET_ACTIVE",
                message="Failed to read active prompt",
                context={"agent_name": agent_name},
                cause=e,
            )

    async def get_all_active(self) -> list[PromptTemplate]:
        """
        Every agent's active prompt (cross-partition). Used at startup to warm the
        prompt cache so each agent's first call avoids a round-trip.
        """
        query = "SELECT * FROM c WHERE c.is_active = true"
        try:
            items = self._container.query_items(query=query)
            return [PromptTemplate.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_PROMPT_GET_ALL_ACTIVE",
                message="Failed to list active prompts",
                context={},
                cause=e,
            )

    async def upsert(self, prompt: PromptTemplate) -> PromptTemplate:
        """
        Insert or replace a prompt version. Dumps with `by_alias` so the nested
        model config persists under `modelConfig` exactly as the seed format and
        schema expect.
        """
        try:
            body = prompt.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return PromptTemplate.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_PROMPT_UPSERT",
                message="Failed to upsert prompt",
                context={"prompt_id": prompt.id, "agent_name": prompt.agent_name},
                cause=e,
            )
