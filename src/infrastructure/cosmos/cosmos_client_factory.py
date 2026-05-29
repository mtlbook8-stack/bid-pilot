"""CosmosClientFactory — builds and shares the async Cosmos client + containers."""

import logging

from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.identity.aio import DefaultAzureCredential

from src.api.config import Settings
from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)


class CosmosClientFactory:
    """
    Owns the single async `CosmosClient` and hands out container proxies by name.

    Why it exists: per Rule 3, stores never create their own client — they receive
    container proxies through their constructors. This factory is the one place
    that wires the SDK together, so the composition root (main.py) creates exactly
    one factory, opens it once, and injects the resulting containers everywhere.

    Authentication is managed-identity only (`DefaultAzureCredential`); no account
    keys ever touch the code or config (build doc — keyless access). The factory
    does NOT create databases or containers — Bicep provisions them — it only
    returns proxies that point at the already-existing resources.
    """

    # Container name -> partition key path. Kept here as the single source of
    # truth (build doc section 6.1) so callers reference names, not raw strings
    # scattered across stores. The partition key paths are documentation here:
    # the proxies returned by Cosmos do not require the path to be re-specified.
    CONTAINERS: dict[str, str] = {
        "bids": "/id",
        "projects": "/id",
        "jobs": "/projectId",
        "linked-accounts": "/userId",
        "prompts": "/agentName",
        "learned-rules": "/agentName",
        "corrections": "/bidId",
        "rejected-emails": "/id",
        "comparison-sessions": "/projectId",
        "audit": "/entityType",
        "error-logs": "/pipeline",
        "leases": "/id",
    }

    def __init__(self, settings: Settings) -> None:
        """
        Store config and prepare lazy handles. The client and credential are NOT
        opened here — construction stays cheap and side-effect free; `connect()`
        performs the actual network-capable setup so the composition root controls
        the lifecycle (open on startup, close on shutdown).
        """
        self._settings = settings
        self._credential: DefaultAzureCredential | None = None
        self._client: CosmosClient | None = None
        self._database: DatabaseProxy | None = None

    def connect(self) -> None:
        """
        Build the credential, client, and database proxy.

        Why separate from __init__: the aio `CosmosClient` and credential allocate
        underlying transport resources that must be closed; doing this in an
        explicit method (paired with `close()`) lets the app manage their lifetime
        deterministically rather than relying on object construction.
        """
        try:
            # DefaultAzureCredential resolves the Container App / Function managed
            # identity at runtime — no secrets in code (build doc keyless access).
            self._credential = DefaultAzureCredential()
            self._client = CosmosClient(
                url=self._settings.cosmos_endpoint,
                credential=self._credential,
            )
            self._database = self._client.get_database_client(
                self._settings.cosmos_database_name
            )
        except Exception as e:
            raise AppError(
                code="COSMOS_FACTORY_CONNECT",
                message="Failed to initialize the Cosmos client",
                context={
                    "endpoint": self._settings.cosmos_endpoint,
                    "database": self._settings.cosmos_database_name,
                },
                cause=e,
            )

    def get_container(self, name: str) -> ContainerProxy:
        """
        Return a proxy for an existing container by name.

        Raises if `connect()` has not run or the name is unknown — these are
        programming errors (bad wiring), so failing loudly at startup is correct
        rather than letting a None propagate into a store.
        """
        if self._database is None:
            raise AppError(
                code="COSMOS_FACTORY_NOT_CONNECTED",
                message="get_container called before connect()",
                context={"container": name},
            )
        if name not in self.CONTAINERS:
            raise AppError(
                code="COSMOS_FACTORY_UNKNOWN_CONTAINER",
                message="Requested an unknown Cosmos container",
                context={"container": name, "known": list(self.CONTAINERS)},
            )
        try:
            return self._database.get_container_client(name)
        except Exception as e:
            raise AppError(
                code="COSMOS_FACTORY_GET_CONTAINER",
                message="Failed to obtain a Cosmos container proxy",
                context={"container": name},
                cause=e,
            )

    async def close(self) -> None:
        """
        Close the client and credential transports.

        Called from the app's shutdown hook. Wrapped so a shutdown-time failure is
        surfaced with context instead of escaping as a raw SDK error.
        """
        try:
            if self._client is not None:
                await self._client.close()
            if self._credential is not None:
                await self._credential.close()
        except Exception as e:
            raise AppError(
                code="COSMOS_FACTORY_CLOSE",
                message="Failed to close the Cosmos client",
                context={},
                cause=e,
            )
