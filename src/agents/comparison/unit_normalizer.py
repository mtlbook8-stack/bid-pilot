"""
UnitNormalizer — Agent 5 of the comparison subsystem.

WHY this agent exists: vendors price the same scope in inconsistent units (one
quotes drywall per SF, another per SY, a third as a lump sum). Before any cost
comparison is meaningful, every priced line item across every bid must be
extracted and normalized to common units. This agent reads all the bid documents
at once and returns normalized groups, ungrouped items, and a summary (section 7,
Agent 5).

The Agent 5 user template has fixed header fields (PROJECT, JOB, trade) followed
by a per-bid block that REPEATS once per bid. Since the repeated section is
caller-assembled, `normalize` accepts a pre-rendered `bids_block` string for that
section and the fixed fields as their own keys. The `render_bid_block` static
helper formats ONE bid block exactly as the template shows, so every caller (and
FeatureAnalyst, which shares the identical block) builds the repeated text the
same way (Rule 5 reuse).
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError


class UnitNormalizer(BaseAgent):
    """
    Extracts and normalizes line items across multiple bids (Agent 5).

    A thin BaseAgent subclass (Rules 1/4) with one job (Rule 2): shape the
    normalization inputs into the Agent 5 prompt and return the parsed result.
    It adds no collaborators beyond those BaseAgent injects (Rule 3).
    """

    @staticmethod
    def render_bid_block(
        vendor_name: str,
        bid_id: str,
        filename: str,
        total_price: str,
        document_text: str,
        parsed_tables: str,
    ) -> str:
        """
        Format ONE bid's block exactly as the Agent 5/7 user template specifies.

        Centralizes the repeated-block layout so callers assemble the variable
        per-bid section consistently and identically for both UnitNormalizer and
        FeatureAnalyst (whose templates share this block verbatim) — Rule 5. The
        caller joins the returned blocks (typically with blank lines) into the
        single `bids_block` string passed to `normalize`/`analyze`.
        """
        return (
            f"--- BID: {vendor_name} (ID: {bid_id}) ---\n"
            f"FILENAME: {filename}\n"
            f"TOTAL QUOTED: {total_price}\n"
            f"\n"
            f"DOCUMENT TEXT:\n"
            f"{document_text}\n"
            f"\n"
            f"TABLES:\n"
            f"{parsed_tables}\n"
            f"--- END BID ---"
        )

    async def normalize(
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
        Normalize all bids in `bids_block` to common units for comparison.

        `bids_block` is the caller-assembled repeated per-bid section (built from
        `render_bid_block`); the fixed header fields are passed separately. Runs
        the agent and returns the parsed dict with keys: groups, ungrouped_items,
        summary.

        Any unexpected error while assembling the template values is wrapped as an
        AppError with a unique code (Rules 7, 8).
        """
        try:
            template_values = {
                "project_name": project_name,
                "job_name": job_name,
                "trade_category": trade_category,
                # The repeated per-bid section, pre-rendered by the caller. It
                # collapses the template's variable-arity block into one token so
                # the static template can carry a single {bids_block} placeholder.
                "bids_block": bids_block,
            }
        except Exception as exc:
            raise AppError(
                code="AGENT_UNIT_NORMALIZER_TEMPLATE",
                message="Failed to build UnitNormalizer template values",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.UNIT_NORMALIZER.value,
            template_values,
            session_id=session_id,
            project_id=project_id,
            max_tokens_override=8000,
        )
