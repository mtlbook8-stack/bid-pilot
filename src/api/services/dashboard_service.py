"""
DashboardService — aggregates portfolio stats and answers NL questions (Agent 12).

WHY this exists: the dashboard needs two things — a cheap, code-computed snapshot
of the user's portfolio (counts by status, projects, jobs, rejected, needs-review,
recent bids) and a natural-language Q&A endpoint. Per the build doc, the
DashboardAnalyst agent does NOT query Cosmos; it receives a pre-aggregated JSON
blob. So this service owns the aggregation (code only) and feeds it to the agent.

One job per method (Rule 2): `get_stats` aggregates, `ask` answers. All
collaborators injected (Rule 3); store failures wrapped as AppError (Rules 7, 8).
"""

import json
from collections import Counter

from src.agents.insights.dashboard_analyst import DashboardAnalyst
from src.core.errors.app_error import AppError
from src.core.interfaces.bid_store import IBidStore
from src.core.interfaces.job_store import IJobStore
from src.core.interfaces.project_store import IProjectStore
from src.core.interfaces.rejected_store import IRejectedEmailStore
from src.core.interfaces.session_store import IComparisonSessionStore

# How many most-recent bids to surface on the dashboard. Small — the UI shows a
# glanceable list, not the full history.
_RECENT_BIDS_LIMIT = 10


class DashboardService:
    """Builds dashboard aggregates and routes portfolio questions to Agent 12."""

    def __init__(
        self,
        bid_store: IBidStore,
        project_store: IProjectStore,
        job_store: IJobStore,
        session_store: IComparisonSessionStore,
        rejected_store: IRejectedEmailStore,
        dashboard_analyst: DashboardAnalyst,
    ) -> None:
        # Pure DI (Rule 3): the container passes every wired store + the agent.
        self._bid_store = bid_store
        self._project_store = project_store
        self._job_store = job_store
        self._session_store = session_store
        self._rejected_store = rejected_store
        self._dashboard_analyst = dashboard_analyst

    async def get_stats(self) -> dict:
        """
        Compute the portfolio snapshot the dashboard renders.

        Aggregates (all code, no LLM): total bids, a breakdown by status, project
        and job counts, rejected-email count, the count of bids needing review
        (any low-confidence agent result), and a small recent-bids list. Each
        store read is wrapped so a failure is attributable to its source.
        """
        bids = await self._safe(self._bid_store.list_all(), "DASHBOARD_LIST_BIDS")
        projects = await self._safe(
            self._project_store.list_all(), "DASHBOARD_LIST_PROJECTS"
        )
        sessions = await self._safe(
            self._session_store.list_all(), "DASHBOARD_LIST_SESSIONS"
        )
        rejected = await self._safe(
            self._rejected_store.list_all(), "DASHBOARD_LIST_REJECTED"
        )

        # Jobs are partitioned by project, so there is no single "list all jobs"
        # query; sum the per-project job lists. At this scale (a handful of
        # projects) the fan-out is negligible.
        total_jobs = 0
        for project in projects:
            jobs = await self._safe(
                self._job_store.list_for_project(project.id),
                "DASHBOARD_LIST_JOBS",
            )
            total_jobs += len(jobs)

        status_counts = Counter(bid.status.value for bid in bids)
        needs_review = sum(1 for bid in bids if bid.needs_review)

        # Most recent bids first; the model exposes created_at on every bid.
        recent = sorted(bids, key=lambda b: b.created_at, reverse=True)[
            :_RECENT_BIDS_LIMIT
        ]
        recent_bids = [
            {
                "id": bid.id,
                "vendorName": bid.vendor_name,
                "subject": bid.email_subject,
                "status": bid.status.value,
                "tradeCategory": (
                    bid.trade_category.value if bid.trade_category else None
                ),
                "totalPrice": bid.total_price,
                "createdAt": bid.created_at.isoformat(),
            }
            for bid in recent
        ]

        return {
            "totalBids": len(bids),
            "bidsByStatus": dict(status_counts),
            "totalProjects": len(projects),
            "totalJobs": total_jobs,
            "totalSessions": len(sessions),
            "totalRejected": len(rejected),
            "needsReview": needs_review,
            "recentBids": recent_bids,
        }

    async def ask(self, question: str) -> dict:
        """
        Answer a natural-language portfolio question via DashboardAnalyst.

        Builds the pre-aggregated stats JSON (the agent never queries Cosmos) and
        hands it to Agent 12. Returns the agent's parsed dict (answer, data_points,
        suggested_actions, visualization_hint). Agent failures already surface as
        AppError from inside the agent; serialization is wrapped here.
        """
        stats = await self.get_stats()
        try:
            aggregated_stats_json = json.dumps(stats)
        except Exception as exc:
            raise AppError(
                code="DASHBOARD_SERIALIZE_STATS",
                message="Failed to serialize aggregated stats for the analyst",
                cause=exc,
            )

        return await self._dashboard_analyst.analyze(
            user_question=question,
            aggregated_stats_json=aggregated_stats_json,
        )

    @staticmethod
    async def _safe(awaitable, code: str):
        """
        Await a store call, wrapping any failure with `code` (Rule 7).

        Centralizes the try/except so each aggregation read does not repeat the
        boilerplate (Rule 5). AppErrors from below pass through unchanged.
        """
        try:
            return await awaitable
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code=code,
                message="Dashboard aggregation store call failed",
                cause=exc,
            )
