"""
ComparisonOrchestrator — Agent 4 of the comparison subsystem.

WHY this agent exists: a comparison session is a free-form chat over a job's
bids, but the actual work is done by specialists (cost, features, cross-project
data, etc.). This agent is the router: it reads the user's message plus a little
session context and decides WHICH specialist should handle it, rewriting the
message into a clean instruction for that specialist. It performs no analysis of
its own — it only classifies intent and names the next agent (section 8.3).

It is the only non-Claude agent (runs on gpt-5 per section 7), but the model is
a property of the active prompt config, not something this class sets — so this
remains a thin BaseAgent subclass (Rules 1/4) that owns exactly one job (Rule 2):
shape the routing inputs and return the parsed routing decision.
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError


class ComparisonOrchestrator(BaseAgent):
    """
    Classifies a comparison-chat message and routes it to a specialist (Agent 4).

    Inherits all collaborators from BaseAgent via constructor injection (Rule 3)
    and adds none. The single public method `route` builds the Agent 4 user
    template values and returns the parsed routing dict; fallback, telemetry,
    rule injection, and JSON parsing all live in BaseAgent (Rule 5).
    """

    async def route(
        self,
        *,
        project_name: str,
        job_name: str,
        vendor_list: str,
        phase: str,
        recent_messages: str,
        user_message: str,
        session_id: str,
        project_id: str,
    ) -> dict:
        """
        Decide which specialist agent should handle `user_message`.

        Builds the Agent 4 template values (keys mirror the user-message template
        tokens exactly), runs the agent, and returns the parsed dict with keys:
        agent, confidence, extracted_query, reasoning.

        Any unexpected error while assembling the template values is wrapped as an
        AppError with a unique code so the caller gets one attributable failure
        rather than a raw mapping/typing exception (Rules 7, 8).
        """
        try:
            template_values = {
                "project_name": project_name,
                "job_name": job_name,
                "vendor_list": vendor_list,
                "phase": phase,
                "recent_messages": recent_messages,
                "user_message": user_message,
            }
        except Exception as exc:
            raise AppError(
                code="AGENT_ORCHESTRATOR_TEMPLATE",
                message="Failed to build ComparisonOrchestrator template values",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.COMPARISON_ORCHESTRATOR.value,
            template_values,
            session_id=session_id,
            project_id=project_id,
        )
