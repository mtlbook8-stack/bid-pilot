"""
FeatureAnalyst — Agent 7 of the comparison subsystem.

WHY this agent exists: cost is only half of a bid decision. Schedule, warranty,
payment terms, inclusions/exclusions, qualifications, insurance, experience, and
logistics often decide a GC's choice — and a low price that excludes demolition
is not actually low. This agent reads all the bid documents and extracts the
NON-cost differentiators, scoring each per-bid sentiment and flagging red flags
(section 7, Agent 7).

Its user template shares the EXACT repeated per-bid block used by UnitNormalizer,
so it reuses `UnitNormalizer.render_bid_block` rather than redefining the layout
(Rule 5). Like Agent 5, the variable per-bid section is caller-assembled and
passed as a single `bids_block` string.
"""

from src.agents.base_agent import BaseAgent
from src.agents.comparison.unit_normalizer import UnitNormalizer
from src.core.enums import AgentName
from src.core.errors.app_error import AppError


class FeatureAnalyst(BaseAgent):
    """
    Compares non-cost differentiators across multiple bids (Agent 7).

    A thin BaseAgent subclass (Rules 1/4) with one job (Rule 2): shape the
    feature-analysis inputs into the Agent 7 prompt and return the parsed result.
    Adds no collaborators beyond BaseAgent's injected ones (Rule 3) and reuses the
    shared per-bid block renderer for template assembly (Rule 5).
    """

    # Re-export the shared per-bid block renderer so callers can build this
    # agent's repeated section without importing UnitNormalizer directly. It is
    # the identical block (the two templates match verbatim), so reusing it keeps
    # a single source of truth (Rule 5).
    render_bid_block = staticmethod(UnitNormalizer.render_bid_block)

    async def analyze(
        self,
        *,
        project_name: str,
        job_name: str,
        trade_category: str,
        bids_block: str,
        session_id: str,
        project_id: str,
    ) -> dict:
        """
        Analyze non-cost features across all bids in `bids_block`.

        `bids_block` is the caller-assembled repeated per-bid section (built from
        `render_bid_block`); the fixed header fields are passed separately. Runs
        the agent and returns the parsed dict with keys: feature_rows, red_flags,
        summary.

        Any unexpected error while assembling the template values is wrapped as an
        AppError with a unique code (Rules 7, 8).
        """
        try:
            template_values = {
                "project_name": project_name,
                "job_name": job_name,
                "trade_category": trade_category,
                "bids_block": bids_block,
            }
        except Exception as exc:
            raise AppError(
                code="AGENT_FEATURE_ANALYST_TEMPLATE",
                message="Failed to build FeatureAnalyst template values",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.FEATURE_ANALYST.value,
            template_values,
            session_id=session_id,
            project_id=project_id,
            max_tokens_override=8000,
        )
