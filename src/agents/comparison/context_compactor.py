"""
ContextCompactor — Agent 8 of the comparison subsystem.

WHY this agent exists: a comparison chat grows unbounded, but the model's context
and the user's costs do not. Once a session passes ~20 messages, this agent
compresses the raw history into a structured summary that preserves every
conclusion, decision, table edit, preference, open thread, and data correction
while discarding pleasantries and intermediate reasoning. The structured output
replaces the raw history in the session document, and downstream agents are fed
the specific sections they need (section 7, Agent 8).

A thin BaseAgent subclass (Rules 1/4) with one job (Rule 2): shape the history
into the Agent 8 prompt and return the parsed summary dict.
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError


class ContextCompactor(BaseAgent):
    """
    Compresses a long comparison-session history into structured state (Agent 8).

    Inherits all collaborators from BaseAgent via constructor injection (Rule 3)
    and adds none. The single public method `compact` builds the Agent 8 template
    values and returns the parsed summary; fallback, telemetry, rule injection,
    and JSON parsing all live in BaseAgent (Rule 5).
    """

    async def compact(
        self,
        *,
        project_name: str,
        job_name: str,
        vendor_list: str,
        message_count: int,
        full_conversation_history: str,
        session_id: str,
        project_id: str,
    ) -> dict:
        """
        Compress the session's conversation into a structured summary.

        Builds the Agent 8 template values (keys mirror the user-message template
        tokens exactly), runs the agent, and returns the parsed dict with keys:
        session_state, conclusions, table_edits, user_preferences, open_threads,
        data_corrections, compressed_from_message_count.

        Any unexpected error while assembling the template values is wrapped as an
        AppError with a unique code (Rules 7, 8).
        """
        try:
            template_values = {
                "project_name": project_name,
                "job_name": job_name,
                "vendor_list": vendor_list,
                "message_count": message_count,
                "full_conversation_history": full_conversation_history,
            }
        except Exception as exc:
            raise AppError(
                code="AGENT_CONTEXT_COMPACTOR_TEMPLATE",
                message="Failed to build ContextCompactor template values",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.CONTEXT_COMPACTOR.value,
            template_values,
            session_id=session_id,
            project_id=project_id,
        )
