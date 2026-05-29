"""
seed_prompts — load all 13 agent prompts from data/seed/prompts.json into Cosmos.

This is decision I5: the system ships with every agent's finalized prompt as a
versioned, active document so the runtime can swap models/prompts with no code
change. Run once against a fresh database (and again after editing prompts.json,
which upserts by id).
"""

import asyncio
import json
import logging
from pathlib import Path

from src.core.models.prompt import PromptTemplate
from src.devtools.dev_database import DevDatabase

logger = logging.getLogger(__name__)

# Repo-relative path to the seed file (repo_root/data/seed/prompts.json).
_PROMPTS_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "prompts.json"


class PromptSeeder:
    """Validates the seed file into PromptTemplate models and upserts each one."""

    def __init__(self, db: DevDatabase, prompts_path: Path = _PROMPTS_PATH) -> None:
        self._db = db
        self._prompts_path = prompts_path

    async def run(self) -> int:
        """Upsert every prompt document; return the count seeded."""
        raw = json.loads(self._prompts_path.read_text(encoding="utf-8"))
        store = self._db.prompts
        count = 0
        for entry in raw:
            # Validate by alias so the camelCase `modelConfig` maps onto the model.
            prompt = PromptTemplate.model_validate(entry)
            await store.upsert(prompt)
            count += 1
            logger.info("seeded prompt %s", prompt.id)
        return count


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with DevDatabase() as db:
        seeded = await PromptSeeder(db).run()
    print(f"Seeded {seeded} prompt documents.")


if __name__ == "__main__":
    asyncio.run(_main())
