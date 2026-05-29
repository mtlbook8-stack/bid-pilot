"""list_bids — debug utility that prints every bid and its pipeline status."""

import asyncio
import logging

from src.devtools.dev_database import DevDatabase

logger = logging.getLogger(__name__)


class BidLister:
    """Reads all bids and renders a one-line-per-bid status table."""

    def __init__(self, db: DevDatabase) -> None:
        self._db = db

    async def run(self) -> None:
        bids = await self._db.bids.list_all()
        if not bids:
            print("(no bids)")
            return
        print(f"{'ID':<34} {'STATUS':<16} {'VENDOR':<22} {'TOTAL':>12}")
        for bid in sorted(bids, key=lambda b: b.created_at):
            total = f"${bid.total_price:,.0f}" if bid.total_price else "-"
            print(
                f"{bid.id:<34} {bid.status.value:<16} "
                f"{(bid.vendor_name or '-'):<22} {total:>12}"
            )


async def _main() -> None:
    logging.basicConfig(level=logging.WARNING)
    async with DevDatabase() as db:
        await BidLister(db).run()


if __name__ == "__main__":
    asyncio.run(_main())
