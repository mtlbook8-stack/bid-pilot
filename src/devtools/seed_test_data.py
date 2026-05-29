"""
seed_test_data — populate Cosmos with a small, realistic sample so the UI and the
comparison flow can be exercised without a live mailbox.

Creates one project, one HVAC job, and three competing vendor bids already in the
Categorized state (so they appear in the UI and can be compared immediately).
"""

import asyncio
import logging
from datetime import UTC, datetime

from src.core.enums import BidStatus, TradeCategory
from src.core.models.bid import IngestedBid
from src.core.models.job import JobSummary
from src.core.models.project import ProjectSummary
from src.devtools.dev_database import DevDatabase

logger = logging.getLogger(__name__)


class TestDataSeeder:
    """Builds and persists a self-consistent project/job/bids sample set."""

    def __init__(self, db: DevDatabase) -> None:
        self._db = db

    async def run(self) -> dict[str, int]:
        project = ProjectSummary(
            id="proj-sample-elm",
            name="Elm Street Medical Office",
            address="123 Elm St, Springfield, IL 62701",
            normalized_address="123 elm st, springfield, il 62701, us",
            client_name="Springfield Health Partners",
        )
        await self._db.projects.upsert(project)

        job = JobSummary(
            id="job-sample-hvac",
            project_id=project.id,
            trade_category=TradeCategory.HVAC,
            job_name="HVAC — rooftop units + ductwork",
        )

        # Three vendors with different totals so cost comparison has spread.
        vendors = [
            ("ABC Mechanical", 87000.0, "Supply and install 4 rooftop units and "
             "associated ductwork for floors 1-3."),
            ("Delta Air Systems", 94500.0, "Furnish/install HVAC for the full "
             "building including controls and 1-year warranty."),
            ("Northwind HVAC", 102300.0, "Complete mechanical scope with premium "
             "high-efficiency units and 5-year parts/labor warranty."),
        ]
        for i, (vendor, total, scope) in enumerate(vendors):
            bid = IngestedBid(
                id=IngestedBid.make_id("sample-msg", f"{vendor}.pdf"),
                message_id=f"sample-msg-{i}",
                linked_account_id="account-sample",
                sender_email=f"estimating@{vendor.lower().replace(' ', '')}.com",
                email_subject=f"Quote — HVAC for {project.name}",
                received_at=datetime.now(UTC),
                attachment_filename=f"{vendor}.pdf",
                blob_path=f"account-sample/sample-msg-{i}/{vendor}.pdf",
                document_text=f"{vendor} proposal. {scope} Total: ${total:,.0f}.",
                table_count=1,
                status=BidStatus.CATEGORIZED,
                is_bid=True,
                matched_project_id=project.id,
                matched_job_id=job.id,
                trade_category=TradeCategory.HVAC,
                vendor_name=vendor,
                scope_summary=scope,
                total_price=total,
            )
            await self._db.bids.upsert(bid)
            job.add_bid(bid.id)

        await self._db.jobs.upsert(job)
        return {"projects": 1, "jobs": 1, "bids": len(vendors)}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with DevDatabase() as db:
        counts = await TestDataSeeder(db).run()
    print(f"Seeded sample data: {counts}")


if __name__ == "__main__":
    asyncio.run(_main())
