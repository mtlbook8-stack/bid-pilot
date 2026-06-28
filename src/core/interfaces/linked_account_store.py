"""ILinkedAccountStore — persistence contract for linked email accounts."""

from typing import Protocol

from src.core.models.linked_account import LinkedAccount


class ILinkedAccountStore(Protocol):
    """Partition key `/userId`."""

    async def get(self, account_id: str, user_id: str) -> LinkedAccount | None: ...

    async def get_by_email(self, email_address: str) -> LinkedAccount | None: ...

    async def upsert(self, account: LinkedAccount) -> LinkedAccount: ...

    async def list_for_user(self, user_id: str) -> list[LinkedAccount]: ...

    async def list_all_active(self) -> list[LinkedAccount]: ...

    async def delete(self, account_id: str, user_id: str) -> None: ...
