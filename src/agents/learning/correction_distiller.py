"""
CorrectionDistiller — Agent 10, the real-time learning loop.

WHY this agent exists: it is the write side of the learning loop that BaseAgent
reads on every run via the {learned_rules} placeholder. Whenever a user corrects
a pipeline agent's decision (a wrong validation, project match, or trade
categorization), this agent distills that single correction into one specific,
reusable rule that gets injected into the corrected agent's future prompts — so
the same mistake is not repeated. It deliberately produces ONE rule per
correction and flags (rather than silently overrides) any conflict with an
existing rule.

Thin BaseAgent subclass (Rule 1/Rule 4); no extra dependencies (Rule 3); the
engine logic (telemetry/fallback/parse) is reused, not duplicated (Rule 5).
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError

# WHY 2000: the Agent 10 user-message template states "Document text (first 2000
# chars)". Rule distillation keys off observable patterns (sender domain,
# keywords, header structure) that surface early in the document, so a small
# snippet is sufficient and keeps the call cheap.
_DOCUMENT_TEXT_LIMIT = 2000


class CorrectionDistiller(BaseAgent):
    """
    Turns a single user correction into one reusable learned rule (Agent 10).

    Inherits BaseAgent's injected collaborators unchanged (Rule 3). The single
    public method `distill` builds the Agent 10 template values and returns the
    parsed rule dict.
    """

    async def distill(
        self,
        *,
        agent_name: str,
        original_output_json: str,
        correction_type: str,
        corrected_value: str,
        correction_reason: str,
        sender_email: str,
        email_subject: str,
        attachment_file_name: str,
        document_text_snippet: str,
        current_rules: str,
        bid_id: str,
    ) -> dict:
        """
        Distill a correction into a learned rule for the offending agent.

        `agent_name` is the agent that was corrected (e.g. QuoteValidator).
        `original_output_json` and `current_rules` are caller-serialized
        strings. The document snippet is truncated to the first 2000 chars per
        the template contract.

        Returns the parsed dict with keys: target_agent, rule_text,
        pattern_identified, specificity, conflicts_with_existing, confidence.
        Template-assembly failures are wrapped as AppError (Rules 7, 8).
        """
        try:
            template_values = {
                "agent_name": agent_name,
                "original_output_json": original_output_json,
                "correction_type": correction_type,
                "corrected_value": corrected_value,
                "correction_reason": correction_reason,
                "sender_email": sender_email,
                "email_subject": email_subject,
                "attachment_file_name": attachment_file_name,
                "document_text_snippet": document_text_snippet[:_DOCUMENT_TEXT_LIMIT],
                "current_rules": current_rules,
            }
        except Exception as exc:
            raise AppError(
                code="CORRECTION_DISTILLER_TEMPLATE",
                message="Failed to build CorrectionDistiller template values",
                context={"bid_id": bid_id, "corrected_agent": agent_name},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.CORRECTION_DISTILLER.value,
            template_values,
            bid_id=bid_id,
        )
