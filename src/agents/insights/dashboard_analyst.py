"""
DashboardAnalyst — Agent 12.

WHY this agent exists: it answers natural-language questions about the user's
whole portfolio — volume, status, trends, vendor frequency, and "what needs my
attention" alerts. Critically, it does NOT query Cosmos: code pre-aggregates the
stats and hands them in as JSON, and the agent reasons over that snapshot. Its
output carries a visualization_hint so the frontend knows which widget to render
from the returned data_points.

Thin BaseAgent subclass (Rule 1/Rule 4); no extra dependencies (Rule 3); reuses
the BaseAgent engine (Rule 5). This is a portfolio-wide question with no single
bid/session/project, so no context ids are passed to the telemetry span.
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError


class DashboardAnalyst(BaseAgent):
    """
    Answers portfolio questions over pre-aggregated stats (Agent 12).

    Inherits BaseAgent's injected collaborators unchanged (Rule 3). The single
    public method `analyze` builds the Agent 12 template values and returns the
    parsed answer dict.
    """

    async def analyze(
        self,
        *,
        user_question: str,
        aggregated_stats_json: str,
    ) -> dict:
        """
        Answer a natural-language portfolio question.

        `aggregated_stats_json` is the caller-serialized, pre-queried portfolio
        snapshot (the agent does not query Cosmos itself). Nothing is truncated;
        the caller controls how much aggregated data to include.

        Returns the parsed dict with keys: answer, data_points,
        suggested_actions, visualization_hint. Template-assembly failures are
        wrapped as AppError (Rules 7, 8).
        """
        try:
            template_values = {
                "user_question": user_question,
                "aggregated_stats_json": aggregated_stats_json,
            }
        except Exception as exc:
            raise AppError(
                code="DASHBOARD_ANALYST_TEMPLATE",
                message="Failed to build DashboardAnalyst template values",
                context={"user_question": user_question[:200]},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.DASHBOARD_ANALYST.value,
            template_values,
        )
