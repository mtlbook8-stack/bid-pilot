"""CosmosLinkedAccountStore — ILinkedAccountStore backed by `linked-accounts`."""

from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.core.errors.app_error import AppError
from src.core.models.linked_account import LinkedAccount


class CosmosLinkedAccountStore:
    """
    Cosmos-backed persistence for `LinkedAccount` (implements ILinkedAccountStore).

    Partition key is `/userId` (build doc 6.1): a user's linked mailboxes are read
    together (their settings page, per-user polling), so partitioning by user id
    makes `get` a point-read (needs both account id and user id) and
    `list_for_user` a single-partition query. `list_all_active` is the exception —
    the polling trigger fans out across all users, so it is a cross-partition
    query filtered on `is_active`. Container injected (Rule 3); SDK calls wrapped
    and re-raised (Rule 8); the store never logs.
    """

    def __init__(self, container: ContainerProxy) -> None:
        """Receive the resolved `linked-accounts` container proxy (Rule 3)."""
        self._container = container

    async def get(self, account_id: str, user_id: str) -> LinkedAccount | None:
        """
        Point-read an account. `user_id` is the partition key (required alongside
        the item id for a point-read). None when the account does not exist.
        """
        try:
            item = await self._container.read_item(
                item=account_id, partition_key=user_id
            )
            return LinkedAccount.model_validate(item)
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            raise AppError(
                code="STORE_LINKED_ACCOUNT_GET",
                message="Failed to read linked account",
                context={"account_id": account_id, "user_id": user_id},
                cause=e,
            )

    async def upsert(self, account: LinkedAccount) -> LinkedAccount:
        """Insert or replace a linked account (e.g. advancing the poll watermark)."""
        try:
            body = account.model_dump(mode="json", by_alias=True)
            saved = await self._container.upsert_item(body=body)
            return LinkedAccount.model_validate(saved)
        except Exception as e:
            raise AppError(
                code="STORE_LINKED_ACCOUNT_UPSERT",
                message="Failed to upsert linked account",
                context={"account_id": account.id, "user_id": account.user_id},
                cause=e,
            )

    async def list_for_user(self, user_id: str) -> list[LinkedAccount]:
        """
        All accounts a user has linked. Single-partition query on `/userId`, so it
        scopes to one physical partition and is fast and cheap.
        """
        query = "SELECT * FROM c WHERE c.userId = @uid"
        params = [{"name": "@uid", "value": user_id}]
        try:
            items = self._container.query_items(
                query=query,
                parameters=params,
                partition_key=user_id,
            )
            return [LinkedAccount.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_LINKED_ACCOUNT_LIST_FOR_USER",
                message="Failed to list linked accounts for user",
                context={"user_id": user_id},
                cause=e,
            )

    async def list_all_active(self) -> list[LinkedAccount]:
        """
        Every active linked account across all users (cross-partition).

        Used by the scheduled email-polling trigger, which must reach every
        mailbox regardless of owner; inactive accounts are excluded so an unlinked
        mailbox stops being polled without losing its historical record.
        """
        query = "SELECT * FROM c WHERE c.isActive = true"
        try:
            items = self._container.query_items(query=query)
            return [LinkedAccount.model_validate(item) async for item in items]
        except Exception as e:
            raise AppError(
                code="STORE_LINKED_ACCOUNT_LIST_ALL_ACTIVE",
                message="Failed to list active linked accounts",
                context={},
                cause=e,
            )

    async def delete(self, account_id: str, user_id: str) -> None:
        """
        Remove a linked account (hard unlink).

        A missing record is treated as success so a repeated unlink is idempotent
        rather than surfacing an error to the user.
        """
        try:
            await self._container.delete_item(
                item=account_id, partition_key=user_id
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            raise AppError(
                code="STORE_LINKED_ACCOUNT_DELETE",
                message="Failed to delete linked account",
                context={"account_id": account_id, "user_id": user_id},
                cause=e,
            )
