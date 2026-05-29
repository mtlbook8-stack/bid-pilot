"""
ProjectMatcher — Agent 2 of the ingestion pipeline.

WHY this agent exists: address-based matching (Azure Maps geocode + exact
normalizedAddress compare) handles the easy cases in code before any LLM call.
ProjectMatcher is the fallback for the hard cases — when the normalized address
did not exactly match any existing project but a match may still exist under a
different name, a partial address, a related phase, or a shared client. It
either points the bid at an existing project_id or confirms a genuinely new
project (with the new_project details code then geocodes and persists).

Thin BaseAgent subclass (Rule 1/Rule 4). It adds no dependencies (Rule 3) and
duplicates no engine logic (Rule 5): its only job is to render the Agent 2
template and return the parsed match dict.
"""

from src.agents.base_agent import BaseAgent
from src.core.enums import AgentName
from src.core.errors.app_error import AppError

# WHY 5000: the Agent 2 user-message template states "DOCUMENT TEXT (first 5000
# chars)". Matching may rely on contextual clues (client names, PO numbers,
# phase references) that appear deeper in the document than validation needs,
# hence the larger window than Agent 1.
_DOCUMENT_TEXT_LIMIT = 5000


class ProjectMatcher(BaseAgent):
    """
    Matches a bid to an existing project or proposes a new one (Agent 2).

    Inherits BaseAgent's injected collaborators unchanged (Rule 3). The single
    public method `match` builds the Agent 2 template values and returns the
    parsed dict.
    """

    async def match(
        self,
        *,
        normalized_address: str,
        geocode_status: str,
        existing_projects_json: str,
        sender_email: str,
        email_subject: str,
        attachment_file_name: str,
        document_text: str,
        bid_id: str,
    ) -> dict:
        """
        Find the project this bid belongs to, or confirm it is new.

        `existing_projects_json` is a JSON string the caller has already
        serialized (the agent receives pre-shaped data, it does not query
        Cosmos). The document text is truncated to the first 5000 chars per the
        template contract.

        Returns the parsed dict with keys: match_type, project_id, confidence,
        address_from_bid, reasoning, new_project. Template-assembly failures are
        wrapped as AppError (Rules 7, 8).
        """
        try:
            template_values = {
                "normalized_address": normalized_address,
                "geocode_status": geocode_status,
                "existing_projects_json": existing_projects_json,
                "sender_email": sender_email,
                "email_subject": email_subject,
                "attachment_file_name": attachment_file_name,
                "document_text": document_text[:_DOCUMENT_TEXT_LIMIT],
            }
        except Exception as exc:
            raise AppError(
                code="PROJECT_MATCHER_TEMPLATE",
                message="Failed to build ProjectMatcher template values",
                context={"bid_id": bid_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.PROJECT_MATCHER.value,
            template_values,
            bid_id=bid_id,
        )
