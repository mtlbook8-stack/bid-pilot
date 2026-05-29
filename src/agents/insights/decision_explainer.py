"""
DecisionExplainer — Agent 13.

WHY this agent exists: at the end of a comparison session the user has a table of
costs and features plus whatever priorities they voiced along the way, and they
need help thinking it through — not a decision made for them. DecisionExplainer
synthesizes the comparison table, the session preferences/history, and the user's
specific question into a structured analysis: a case for/against each vendor, the
single key trade-off, a (possibly conditional) recommendation, and the open
questions to resolve with vendors before committing.

Thin BaseAgent subclass (Rule 1/Rule 4); no extra dependencies (Rule 3); the
engine logic (telemetry/fallback/parse) is reused, not duplicated (Rule 5). This
agent operates in the session/project context, so it passes session_id and
project_id (not bid_id) to the telemetry span.
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError


class DecisionExplainer(BaseAgent):
    """
    Synthesizes costs, features, and session context into a decision analysis
    (Agent 13).

    Inherits BaseAgent's injected collaborators unchanged (Rule 3). The single
    public method `explain` builds the Agent 13 template values and returns the
    parsed analysis dict.
    """

    async def explain(
        self,
        *,
        project_name: str,
        job_name: str,
        trade_category: str,
        comparison_table_json: str,
        compacted_preferences_or_history: str,
        extracted_query: str,
        session_id: str,
        project_id: str,
    ) -> dict:
        """
        Organize the comparison so the user can decide more easily.

        `comparison_table_json` and `compacted_preferences_or_history` are
        caller-serialized strings (the preferences/history are either already
        compacted by ContextCompactor or short enough to send whole, so the
        caller controls the size). No truncation is applied here.

        Returns the parsed dict with keys: analysis_type, vendors_analyzed,
        key_trade_off, recommendation, questions_to_resolve. Template-assembly
        failures are wrapped as AppError (Rules 7, 8).
        """
        try:
            template_values = {
                "project_name": project_name,
                "job_name": job_name,
                "trade_category": trade_category,
                "comparison_table_json": comparison_table_json,
                "compacted_preferences_or_history": (
                    compacted_preferences_or_history
                ),
                "extracted_query": extracted_query,
            }
        except Exception as exc:
            raise AppError(
                code="DECISION_EXPLAINER_TEMPLATE",
                message="Failed to build DecisionExplainer template values",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.DECISION_EXPLAINER.value,
            template_values,
            session_id=session_id,
            project_id=project_id,
        )
