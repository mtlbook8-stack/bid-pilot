"""
clear_db — destructive reset that deletes every document from all containers.

Intended only for development against a throwaway database. Requires an explicit
`--yes` flag so it cannot be run by accident; it never drops the containers
themselves (Bicep owns those) — it only empties them.
"""

import asyncio
import logging
import sys

from src.devtools.dev_database import DevDatabase

logger = logging.getLogger(__name__)


class DatabaseCleaner:
    """Empties every container by reading ids and deleting each item."""

    def __init__(self, db: DevDatabase) -> None:
        self._db = db

    async def run(self) -> dict[str, int]:
        deleted: dict[str, int] = {}
        for name in self._db.factory.CONTAINERS:
            container = self._db.factory.get_container(name)
            # Read id + partition-key value for every doc, then point-delete each.
            # Cross-partition read is fine here — this is a dev-only operation.
            count = 0
            query = "SELECT * FROM c"
            async for item in container.query_items(query=query):
                # Partition key path is documented in the factory; for deletion we
                # pass the document's own id as a safe default and fall back to the
                # known pk field when the container is not /id partitioned.
                pk = self._partition_value(name, item)
                await container.delete_item(item=item["id"], partition_key=pk)
                count += 1
            deleted[name] = count
        return deleted

    @staticmethod
    def _partition_value(container_name: str, item: dict) -> str:
        """
        Resolve the partition-key value for a document from its container.

        Maps each container's camelCase partition-key path (section 6.1) to the
        field on the stored document; containers partitioned on `/id` fall back to
        the document id.
        """
        field_by_container = {
            "jobs": "projectId",
            "linked-accounts": "userId",
            "prompts": "agentName",
            "learned-rules": "agentName",
            "corrections": "bidId",
            "comparison-sessions": "projectId",
            "audit": "entityType",
            "error-logs": "pipeline",
        }
        field = field_by_container.get(container_name, "id")
        return item.get(field, item["id"])


async def _main() -> None:
    if "--yes" not in sys.argv:
        print("Refusing to clear the database without --yes. This deletes ALL data.")
        return
    logging.basicConfig(level=logging.INFO)
    async with DevDatabase() as db:
        deleted = await DatabaseCleaner(db).run()
    print(f"Cleared documents: {deleted}")


if __name__ == "__main__":
    asyncio.run(_main())
