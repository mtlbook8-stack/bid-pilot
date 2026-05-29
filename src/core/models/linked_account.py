"""LinkedAccount — a user's mailbox linked via Microsoft Graph OAuth."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class LinkedAccount(BaseModel):
    """
    An email account BidPilot polls for bids. Partition key `/userId`.

    Refresh tokens are NOT stored here in plaintext — `token_secret_name` points
    at a Key Vault secret. `last_processed_at` bounds the Graph delta query so
    polling only fetches mail newer than the last successful run.
    """

    id: str
    user_id: str
    email_address: str
    token_secret_name: str
    webhook_subscription_id: str | None = None
    webhook_expires_at: datetime | None = None
    last_processed_at: datetime | None = None
    is_active: bool = True
    last_health_check_at: datetime | None = None
    last_health_ok: bool | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def mark_processed(self, at: datetime) -> None:
        """Advance the polling watermark after a successful poll."""
        self.last_processed_at = at
        self.updated_at = datetime.now(UTC)
