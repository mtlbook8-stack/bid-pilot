"""
Application settings loaded from environment variables (build doc section 10).

All values are read from the environment with the `BIDPILOT_` prefix. Sensitive
values (client secret, function keys) are Key Vault references that the Azure
Container Apps / Functions runtime resolves into the environment before the
process starts, so the application code only ever sees plain strings.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings. A missing required value fails fast at startup."""

    # Cosmos DB
    cosmos_endpoint: str = ""
    cosmos_database_name: str = "bidpilotdb"

    # Blob Storage
    blob_endpoint: str = ""
    blob_bids_container: str = "bids"

    # Key Vault
    keyvault_uri: str = ""

    # AI Foundry
    ai_foundry_endpoint: str = ""
    ai_foundry_openai_endpoint: str = ""
    # API versions are configurable, never hardcoded in clients (decision I8).
    ai_foundry_anthropic_version: str = "2023-06-01"
    ai_foundry_openai_version: str = "2024-12-01-preview"

    # Document Intelligence
    doc_intelligence_endpoint: str = ""

    # Azure Maps
    azure_maps_client_id: str = ""

    # Entra ID
    entra_client_id: str = ""
    entra_client_secret: str = ""  # Key Vault reference
    entra_tenant_id: str = ""

    # Microsoft Graph (uses the Entra app registration above)
    graph_scopes: str = "https://graph.microsoft.com/.default"

    # Webhook
    webhook_notification_url: str = ""

    # Functions
    functions_base_url: str = ""
    functions_manual_poll_key: str = ""  # Key Vault reference

    # Telemetry
    applicationinsights_connection_string: str = ""

    # Pipeline tuning
    max_bid_retries: int = 3

    model_config = SettingsConfigDict(
        env_prefix="BIDPILOT_",
        env_file=".env",
        extra="ignore",
        protected_namespaces=(),
    )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton accessor so settings are parsed exactly once."""
    return Settings()
