"""
DevDatabase — shared wiring for the developer CLI tools.

The devtools (seed prompts, seed test data, list/clear) all need the same thing:
an opened Cosmos client plus the handful of stores they touch. Centralizing that
here keeps each script tiny and avoids duplicating the connect/close dance (Rule
5). This is dev tooling, not request-path code, so it is allowed to construct its
own dependencies — but it still routes everything through the production
CosmosClientFactory and stores so the seeded data matches runtime expectations.
"""

import logging

from src.api.config import Settings, get_settings
from src.infrastructure.cosmos.bid_store import CosmosBidStore
from src.infrastructure.cosmos.cosmos_client_factory import CosmosClientFactory
from src.infrastructure.cosmos.job_store import CosmosJobStore
from src.infrastructure.cosmos.project_store import CosmosProjectStore
from src.infrastructure.cosmos.prompt_store import CosmosPromptStore

logger = logging.getLogger(__name__)


class DevDatabase:
    """Opens a Cosmos connection and exposes the stores the devtools use."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._factory = CosmosClientFactory(self._settings)
        self._connected = False

    def connect(self) -> None:
        """Open the underlying Cosmos client once before any store is used."""
        if not self._connected:
            self._factory.connect()
            self._connected = True

    async def close(self) -> None:
        """Release the Cosmos client transport."""
        if self._connected:
            await self._factory.close()
            self._connected = False

    @property
    def factory(self) -> CosmosClientFactory:
        return self._factory

    @property
    def prompts(self) -> CosmosPromptStore:
        return CosmosPromptStore(self._factory.get_container("prompts"))

    @property
    def bids(self) -> CosmosBidStore:
        return CosmosBidStore(self._factory.get_container("bids"))

    @property
    def projects(self) -> CosmosProjectStore:
        return CosmosProjectStore(self._factory.get_container("projects"))

    @property
    def jobs(self) -> CosmosJobStore:
        return CosmosJobStore(self._factory.get_container("jobs"))

    async def __aenter__(self) -> "DevDatabase":
        self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()
