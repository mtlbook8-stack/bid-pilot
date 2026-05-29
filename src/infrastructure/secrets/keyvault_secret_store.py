"""KeyVaultSecretStore — managed-identity access to Azure Key Vault secrets."""

import logging

from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient

from src.api.config import Settings
from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)


class KeyVaultSecretStore:
    """
    Reads and writes secrets (e.g. Graph refresh tokens) via Key Vault.

    Why it exists: the GraphTokenManager needs to read a stored refresh token and
    persist a rotated one, but must not know about Key Vault directly (Rule 3). It
    receives this store's `get_secret` / `set_secret` as injected async callables,
    so the token logic stays storage-agnostic. Auth is managed-identity only
    (`DefaultAzureCredential`); no secrets in code.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._credential = DefaultAzureCredential()
        self._client = SecretClient(
            vault_url=settings.keyvault_uri, credential=self._credential
        )

    async def get_secret(self, name: str) -> str:
        """Return a secret's value, wrapping any vault error with context."""
        try:
            secret = await self._client.get_secret(name)
            return secret.value or ""
        except Exception as exc:
            raise AppError(
                code="KEYVAULT_GET",
                message="Failed to read secret from Key Vault",
                context={"secret_name": name},
                cause=exc,
            )

    async def set_secret(self, name: str, value: str) -> None:
        """Create or update a secret value."""
        try:
            await self._client.set_secret(name, value)
        except Exception as exc:
            raise AppError(
                code="KEYVAULT_SET",
                message="Failed to write secret to Key Vault",
                context={"secret_name": name},
                cause=exc,
            )

    async def close(self) -> None:
        """Release the client + credential transports on shutdown."""
        await self._client.close()
        await self._credential.close()
