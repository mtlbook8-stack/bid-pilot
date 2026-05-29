"""
SessionSummarizer — Agent 11.

WHY this agent exists: a comparison session is a working conversation, but the
output a project manager actually wants is a shareable summary they can read on
their phone. SessionSummarizer takes the final comparison-table state plus the
session conversation (or a compacted summary of it) and produces a structured
summary — overview, cost findings, non-cost factors, decisions made, open
items, and where the recommendation stands — that can be pasted into a status
update.

Thin BaseAgent subclass (Rule 1/Rule 4); no extra dependencies (Rule 3); reuses
the BaseAgent engine rather than duplicating it (Rule 5). This agent operates in
the session/project context, so it passes session_id and project_id (not bid_id)
to the telemetry span.
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError


class SessionSummarizer(BaseAgent):
    """
    Produces a shareable summary of a comparison session (Agent 11).

    Inherits BaseAgent's injected collaborators unchanged (Rule 3). The single
    public method `summarize` builds the Agent 11 template values and returns
    the parsed summary dict.
    """

    async def summarize(
        self,
        *,
        project_name: str,
        job_name: str,
        trade_category: str,
        vendor_list: str,
        comparison_table_json: str,
        conversation_history_or_compacted_summary: str,
        session_id: str,
        project_id: str,
    ) -> dict:
        """
        Summarize a comparison session for a stakeholder who wasn't present.

        `comparison_table_json` and the conversation history are
        caller-serialized strings. No truncation is applied: the conversation is
        either already compacted by ContextCompactor or short enough to send
        whole, so the caller controls the size.

        Returns the parsed summary dict (title, overview, cost_summary,
        feature_summary, decisions, open_items, recommendation_status,
        recommended_vendor, one_liner). Template-assembly failures are wrapped
        as AppError (Rules 7, 8).
        """
        try:
            template_values = {
                "project_name": project_name,
                "job_name": job_name,
                "trade_category": trade_category,
                "vendor_list": vendor_list,
                "comparison_table_json": comparison_table_json,
                "conversation_history_or_compacted_summary": (
                    conversation_history_or_compacted_summary
                ),
            }
        except Exception as exc:
            raise AppError(
                code="SESSION_SUMMARIZER_TEMPLATE",
                message="Failed to build SessionSummarizer template values",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.SESSION_SUMMARIZER.value,
            template_values,
            session_id=session_id,
            project_id=project_id,
        )
