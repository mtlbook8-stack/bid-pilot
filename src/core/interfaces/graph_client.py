"""IGraphMailClient — contract for Microsoft Graph email access."""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class EmailAttachment(BaseModel):
    """A single attachment's bytes + metadata."""

    filename: str
    content_type: str
    content_bytes: bytes


class GraphEmail(BaseModel):
    """A fetched email with its attachments materialized."""

    message_id: str
    sender_email: str
    subject: str
    body_preview: str
    received_at: datetime
    attachments: list[EmailAttachment] = []


class IGraphMailClient(Protocol):
    """
    Reads mail for one linked account. `fetch_new_emails` bounds results by the
    account's last-processed watermark; `fetch_email` re-pulls a single message
    by id for the rejected-email restore flow.
    """

    async def fetch_new_emails(
        self, account_id: str, since: datetime | None
    ) -> list[GraphEmail]: ...

    async def fetch_email(self, account_id: str, message_id: str) -> GraphEmail: ...
