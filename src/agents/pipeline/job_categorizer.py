"""
JobCategorizer — Agent 3 of the ingestion pipeline.

WHY this agent exists: once a bid is matched to a project, the system still
needs to know which trade scope it competes on. JobCategorizer picks the
canonical trade_category (one of the TradeCategory enum values), lists any
secondary trades, matches the bid to an existing job on the project or flags a
new one, extracts the vendor name from the document content (not the email
sender), and writes a specific scope summary. This is what lets multiple bids
for the same trade on the same project line up against one comparison.

Thin BaseAgent subclass (Rule 1/Rule 4); no extra dependencies (Rule 3), no
duplicated engine logic (Rule 5).
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError

# WHY 6000: the Agent 3 user-message template states "DOCUMENT TEXT (first 6000
# chars)". Categorization needs the most context of the three pipeline agents —
# the scope, line items, and vendor letterhead can be spread across the body —
# so it gets the widest window.
_DOCUMENT_TEXT_LIMIT = 6000


class JobCategorizer(BaseAgent):
    """
    Determines trade, job match, vendor, and scope for a matched bid (Agent 3).

    Inherits BaseAgent's injected collaborators unchanged (Rule 3). The single
    public method `categorize` builds the Agent 3 template values and returns
    the parsed dict.
    """

    async def categorize(
        self,
        *,
        project_name: str,
        project_address: str,
        existing_jobs_json: str,
        sender_email: str,
        email_subject: str,
        attachment_file_name: str,
        document_text: str,
        bid_id: str,
    ) -> dict:
        """
        Categorize a project-matched bid into a trade and a job.

        `existing_jobs_json` is a caller-serialized JSON string of the project's
        current jobs (the agent receives pre-shaped data). The document text is
        truncated to the first 6000 chars per the template contract.

        Returns the parsed dict with keys: trade_category, secondary_trades,
        is_new_job, existing_job_id, confidence, reasoning, scope_summary,
        vendor_name. Template-assembly failures are wrapped as AppError
        (Rules 7, 8).
        """
        try:
            template_values = {
                "project_name": project_name,
                "project_address": project_address,
                "existing_jobs_json": existing_jobs_json,
                "sender_email": sender_email,
                "email_subject": email_subject,
                "attachment_file_name": attachment_file_name,
                "document_text": document_text[:_DOCUMENT_TEXT_LIMIT],
            }
        except Exception as exc:
            raise AppError(
                code="JOB_CATEGORIZER_TEMPLATE",
                message="Failed to build JobCategorizer template values",
                context={"bid_id": bid_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.JOB_CATEGORIZER.value,
            template_values,
            bid_id=bid_id,
        )
