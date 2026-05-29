"""
QuoteValidator — Agent 1 of the ingestion pipeline.

WHY this agent exists: it is the gate that keeps the bid pipeline clean. Every
document that survives the code-only EmailFilter still needs a semantic decision
— "is this actually a construction bid?" — before the system spends effort
matching it to a project and a job. QuoteValidator makes that binary call,
emits a confidence and a document_type, and (on rejection) a rejection_category
the pipeline uses to file lightweight metadata into the rejected-emails
container.

This class is a thin BaseAgent subclass (Rule 1/Rule 4: one class, one file). It
owns exactly one responsibility: shape the validation inputs into the Agent 1
user-message template and return the parsed decision dict. Fallback, telemetry,
rule injection, and JSON parsing all live in BaseAgent and are never duplicated
here (Rule 5).
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError

# WHY 3000: the Agent 1 user-message template explicitly states "DOCUMENT TEXT
# (first 3000 chars)". The slice is enforced here so the rendered prompt matches
# the template contract and the call stays within the agent's 500-token budget.
_DOCUMENT_TEXT_LIMIT = 3000


class QuoteValidator(BaseAgent):
    """
    Classifies whether an ingested document is a construction bid (Agent 1).

    Inherits all dependencies from BaseAgent via constructor injection (Rule 3);
    it adds no new collaborators. The single public method `validate` builds the
    template values for the Agent 1 prompt and returns the validated decision
    dict produced by the shared response parser.
    """

    async def validate(
        self,
        *,
        sender_email: str,
        email_subject: str,
        attachment_file_name: str,
        table_count: int,
        table_headers_summary: str,
        document_text: str,
        bid_id: str,
    ) -> dict:
        """
        Decide whether `document_text` (and its email metadata) is a bid.

        Builds the Agent 1 template values, runs the agent, and returns the
        parsed dict with keys: is_bid, confidence, document_type,
        rejection_category, reasoning.

        The document text is truncated to the first 3000 chars (template
        contract). Any unexpected error while assembling the template values is
        wrapped as an AppError so the pipeline gets a single, attributable code
        rather than a raw mapping/typing exception (Rules 7, 8).
        """
        try:
            template_values = {
                "sender_email": sender_email,
                "email_subject": email_subject,
                "attachment_file_name": attachment_file_name,
                "table_count": table_count,
                "table_headers_summary": table_headers_summary,
                "document_text": document_text[:_DOCUMENT_TEXT_LIMIT],
            }
        except Exception as exc:
            raise AppError(
                code="QUOTE_VALIDATOR_TEMPLATE",
                message="Failed to build QuoteValidator template values",
                context={"bid_id": bid_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.QUOTE_VALIDATOR.value,
            template_values,
            bid_id=bid_id,
        )
