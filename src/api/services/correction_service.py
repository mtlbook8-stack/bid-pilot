"""
CorrectionService — applies user corrections and drives learning (8.4, 8.5).

WHY this exists: when a user overrides an agent decision (wrong project, wrong
trade, or "this WAS a bid"), two things must happen: the bid is corrected and the
mistake is distilled into a reusable rule so the agent improves (real-time
learning, decision I4). This service owns both flows:
  - `apply_correction` (8.4): snapshot the original agent result, persist a
    Correction, update the bid's corrected field, then run CorrectionDistiller
    (Agent 10) and save the resulting LearnedRule.
  - `restore_rejected` (8.5): re-ingest a wrongly-rejected email by pulling it
    from Graph, uploading + parsing its attachments, creating a VALIDATED bid
    (skipping Agent 1), recording a validation correction, distilling a rule, and
    deleting the rejected-email metadata.

One job (Rule 2): correction + learning orchestration. All collaborators injected
(Rule 3); every external call wrapped as AppError (Rules 7, 8).
"""

import json
import logging
import uuid

from src.agents.learning.correction_distiller import CorrectionDistiller
from src.core.enums import BidStatus, CorrectionType, TradeCategory
from src.core.errors.app_error import AppError
from src.core.interfaces.bid_store import IBidStore
from src.core.interfaces.blob_service import IBlobService
from src.core.interfaces.correction_store import ICorrectionStore
from src.core.interfaces.document_parser import IDocumentParser
from src.core.interfaces.graph_client import GraphEmail, IGraphMailClient
from src.core.interfaces.rejected_store import IRejectedEmailStore
from src.core.interfaces.rule_store import IRuleStore
from src.core.models.bid import IngestedBid
from src.core.models.correction import Correction, LearnedRule
from src.core.models.rejected_email import RejectedEmailMetadata
from src.orchestration.bid_processing_orchestrator import BidProcessingOrchestrator

logger = logging.getLogger(__name__)

# The agent each correction type teaches. A project correction trains the
# ProjectMatcher, a trade correction the JobCategorizer, a validation correction
# the QuoteValidator (build doc 8.4 — rules inject into the offending agent).
_CORRECTION_AGENT = {
    CorrectionType.PROJECT: "ProjectMatcher",
    CorrectionType.TRADE: "JobCategorizer",
    CorrectionType.VALIDATION: "QuoteValidator",
}

# How much document text to feed the distiller (template caps at 2000 chars).
_DOC_SNIPPET_LIMIT = 2000


class CorrectionService:
    """Applies corrections, restores rejected emails, and triggers learning."""

    def __init__(
        self,
        correction_store: ICorrectionStore,
        bid_store: IBidStore,
        rule_store: IRuleStore,
        correction_distiller: CorrectionDistiller,
        rejected_store: IRejectedEmailStore,
        graph_client: IGraphMailClient,
        document_parser: IDocumentParser,
        blob_service: IBlobService,
        bid_processing_orchestrator: BidProcessingOrchestrator,
    ) -> None:
        # Pure DI (Rule 3): every store, agent, and orchestrator is injected.
        self._correction_store = correction_store
        self._bid_store = bid_store
        self._rule_store = rule_store
        self._distiller = correction_distiller
        self._rejected_store = rejected_store
        self._graph_client = graph_client
        self._document_parser = document_parser
        self._blob_service = blob_service
        self._orchestrator = bid_processing_orchestrator

    # ------------------------------------------------------------- 8.4 apply

    async def apply_correction(
        self,
        bid_id: str,
        correction_type: CorrectionType,
        corrected_value: str,
        reason: str,
        user_id: str,
    ) -> IngestedBid:
        """
        Apply a correction to a bid and distill a learned rule (build doc 8.4).

        Steps:
          1. Load the bid.
          2. Snapshot the offending agent's original result for audit.
          3. Persist a Correction record (partition `/bidId`).
          4. Update the bid's corrected field (project / trade / validation).
          5. Run CorrectionDistiller and save the resulting LearnedRule so the
             agent's next run picks it up via the `{learned_rules}` placeholder.

        Returns the updated bid. `user_id` is accepted for auditing/telemetry
        symmetry with the auth context.
        """
        bid = await self._load_bid(bid_id)
        agent_name = _CORRECTION_AGENT[correction_type]
        original_result = bid.agent_results.get(agent_name)
        original_value = (
            original_result.raw_output if original_result is not None else {}
        )

        correction = Correction(
            id=str(uuid.uuid4()),
            bid_id=bid_id,
            correction_type=correction_type,
            agent_name=agent_name,
            original_value=original_value,
            corrected_value=corrected_value,
            reason=reason,
        )
        await self._save_correction(correction)

        self._apply_to_bid(bid, correction_type, corrected_value)
        await self._save_bid(bid, "CORRECTION_SAVE_BID")

        await self._distill_and_save(
            bid=bid,
            agent_name=agent_name,
            correction=correction,
        )
        return bid

    def _apply_to_bid(
        self, bid: IngestedBid, correction_type: CorrectionType, corrected_value: str
    ) -> None:
        """
        Mutate the bid's corrected field in place.

        - PROJECT: set the matched project id directly to the corrected value.
        - TRADE: map the corrected label onto the TradeCategory enum (tolerant of
          casing) so the job/trade reflects the user's choice.
        - VALIDATION: mark the bid a real bid (the user said "this IS a bid").
        Bumps the update timestamp via the model's `touch`.
        """
        if correction_type == CorrectionType.PROJECT:
            bid.matched_project_id = corrected_value
        elif correction_type == CorrectionType.TRADE:
            bid.trade_category = TradeCategory.from_label(corrected_value)
        elif correction_type == CorrectionType.VALIDATION:
            bid.is_bid = True
        bid.touch()

    # ----------------------------------------------------------- 8.5 restore

    async def restore_rejected(self, rejected_id: str) -> IngestedBid:
        """
        Restore a wrongly-rejected email back into the pipeline (build doc 8.5).

        Steps:
          1. Load the rejected-email metadata (id + messageId + account).
          2. Re-fetch the full email + attachments from Graph by messageId.
          3. For each attachment: upload to Blob, parse via Doc Intelligence,
             build an IngestedBid in status VALIDATED (skipping Agent 1), save it.
          4. Record a validation Correction ("is_bid=true") and distill a rule so
             QuoteValidator learns from the miss.
          5. Delete the rejected-email metadata.

        Returns the restored bid (the first attachment's, which is the common
        single-attachment case). Saving the VALIDATED bid lets the change feed
        resume the pipeline from Agent 2 onward.
        """
        metadata = await self._load_rejected(rejected_id)
        email = await self._fetch_email(metadata)

        if not email.attachments:
            raise AppError(
                code="RESTORE_NO_ATTACHMENTS",
                message="Rejected email has no attachments to restore",
                context={"rejected_id": rejected_id, "message_id": metadata.message_id},
            )

        restored: IngestedBid | None = None
        for attachment in email.attachments:
            bid = await self._restore_attachment(metadata, email, attachment)
            if restored is None:
                restored = bid

        # Learn from the mistake: a validation correction + distilled rule.
        correction = Correction(
            id=str(uuid.uuid4()),
            bid_id=restored.id,  # type: ignore[union-attr]
            correction_type=CorrectionType.VALIDATION,
            agent_name="QuoteValidator",
            original_value={"is_bid": False},
            corrected_value="is_bid=true",
            reason="User restored a rejected email — it is a bid.",
        )
        await self._save_correction(correction)
        await self._distill_and_save(
            bid=restored,  # type: ignore[arg-type]
            agent_name="QuoteValidator",
            correction=correction,
        )

        await self._delete_rejected(rejected_id)
        return restored  # type: ignore[return-value]

    async def _restore_attachment(
        self,
        metadata: RejectedEmailMetadata,
        email: GraphEmail,
        attachment,
    ) -> IngestedBid:
        """
        Upload, parse, and persist one restored attachment as a VALIDATED bid.

        The blob path mirrors the ingestion orchestrator (account/message/
        filename) and the bid id is the same deterministic hash, so a restore is
        idempotent with the original ingest. Status is VALIDATED — Agent 1 is
        skipped because the user just confirmed it is a bid.
        """
        blob_path = (
            f"{metadata.linked_account_id}/{email.message_id}/{attachment.filename}"
        )
        try:
            stored_path = await self._blob_service.upload(
                blob_path, attachment.content_bytes, attachment.content_type
            )
        except Exception as exc:
            raise AppError(
                code="RESTORE_BLOB_UPLOAD",
                message="Failed to upload restored attachment to Blob",
                context={
                    "rejected_id": metadata.id,
                    "filename": attachment.filename,
                },
                cause=exc,
            )

        try:
            parsed = await self._document_parser.parse(
                attachment.filename, attachment.content_bytes
            )
        except Exception as exc:
            raise AppError(
                code="RESTORE_PARSE",
                message="Failed to parse restored attachment",
                context={
                    "rejected_id": metadata.id,
                    "filename": attachment.filename,
                },
                cause=exc,
            )

        bid = IngestedBid(
            id=IngestedBid.make_id(email.message_id, attachment.filename),
            message_id=email.message_id,
            linked_account_id=metadata.linked_account_id,
            sender_email=email.sender_email,
            email_subject=email.subject,
            received_at=email.received_at,
            attachment_filename=attachment.filename,
            blob_path=stored_path,
            document_text=parsed.full_text,
            table_count=len(parsed.tables),
            # Skip Agent 1: the user has confirmed this IS a bid (build doc 8.5).
            status=BidStatus.VALIDATED,
            is_bid=True,
        )
        await self._save_bid(bid, "RESTORE_BID_UPSERT")
        return bid

    # ------------------------------------------------------- learning helper

    async def _distill_and_save(
        self,
        bid: IngestedBid,
        agent_name: str,
        correction: Correction,
    ) -> None:
        """
        Run CorrectionDistiller (Agent 10) and persist the LearnedRule (Rule 5).

        Loads the agent's existing rules (so the distiller can flag conflicts),
        runs the distiller, and builds a LearnedRule from its dict. Distillation
        is part of the correction's value, so a failure surfaces (wrapped); it is
        not swallowed.
        """
        current_rules = await self._current_rules_text(agent_name)
        result = await self._distiller.distill(
            agent_name=agent_name,
            original_output_json=self._encode(correction.original_value),
            correction_type=correction.correction_type.value,
            corrected_value=correction.corrected_value,
            correction_reason=correction.reason,
            sender_email=bid.sender_email,
            email_subject=bid.email_subject,
            attachment_file_name=bid.attachment_filename,
            document_text_snippet=bid.document_text[:_DOC_SNIPPET_LIMIT],
            current_rules=current_rules,
            bid_id=bid.id,
        )

        # The distiller names the target agent; trust it but fall back to the
        # corrected agent so a missing field never strands the rule.
        target_agent = str(result.get("target_agent") or agent_name).strip() or agent_name
        rule = LearnedRule(
            id=str(uuid.uuid4()),
            agent_name=target_agent,
            rule_text=str(result.get("rule_text", "")),
            pattern_identified=str(result.get("pattern_identified", "")),
            specificity=str(result.get("specificity", "general")),
            source_correction_id=correction.id,
            conflicts_with_existing=self._opt_str(
                result.get("conflicts_with_existing")
            ),
            confidence=self._safe_confidence(result.get("confidence")),
        )
        try:
            await self._rule_store.upsert(rule)
        except Exception as exc:
            raise AppError(
                code="CORRECTION_RULE_UPSERT",
                message="Failed to persist the distilled learned rule",
                context={"bid_id": bid.id, "agent_name": target_agent},
                cause=exc,
            )

    async def _current_rules_text(self, agent_name: str) -> str:
        """Render the agent's active rules as bullet lines for the distiller."""
        try:
            rules = await self._rule_store.list_active_for_agent(agent_name)
        except Exception as exc:
            raise AppError(
                code="CORRECTION_LIST_RULES",
                message="Failed to list existing rules for the agent",
                context={"agent_name": agent_name},
                cause=exc,
            )
        if not rules:
            return "(none)"
        return "\n".join(rule.as_prompt_line() for rule in rules)

    # ----------------------------------------------------------- store calls

    async def _load_bid(self, bid_id: str) -> IngestedBid:
        try:
            bid = await self._bid_store.get(bid_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="CORRECTION_LOAD_BID",
                message="Failed to load bid for correction",
                context={"bid_id": bid_id},
                cause=exc,
            )
        if bid is None:
            raise AppError(
                code="CORRECTION_BID_MISSING",
                message="No bid found to correct",
                context={"bid_id": bid_id},
            )
        return bid

    async def _load_rejected(self, rejected_id: str) -> RejectedEmailMetadata:
        try:
            metadata = await self._rejected_store.get(rejected_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="RESTORE_LOAD_REJECTED",
                message="Failed to load rejected-email metadata",
                context={"rejected_id": rejected_id},
                cause=exc,
            )
        if metadata is None:
            raise AppError(
                code="RESTORE_REJECTED_MISSING",
                message="No rejected email found to restore",
                context={"rejected_id": rejected_id},
            )
        return metadata

    async def _fetch_email(self, metadata: RejectedEmailMetadata) -> GraphEmail:
        try:
            return await self._graph_client.fetch_email(
                metadata.linked_account_id, metadata.message_id
            )
        except Exception as exc:
            raise AppError(
                code="RESTORE_FETCH_EMAIL",
                message="Failed to re-fetch the rejected email from Graph",
                context={
                    "rejected_id": metadata.id,
                    "message_id": metadata.message_id,
                },
                cause=exc,
            )

    async def _save_correction(self, correction: Correction) -> None:
        try:
            await self._correction_store.add(correction)
        except Exception as exc:
            raise AppError(
                code="CORRECTION_SAVE_RECORD",
                message="Failed to persist the correction record",
                context={"bid_id": correction.bid_id},
                cause=exc,
            )

    async def _save_bid(self, bid: IngestedBid, code: str) -> None:
        try:
            await self._bid_store.upsert(bid)
        except Exception as exc:
            raise AppError(
                code=code,
                message="Failed to persist the corrected bid",
                context={"bid_id": bid.id},
                cause=exc,
            )

    async def _delete_rejected(self, rejected_id: str) -> None:
        try:
            await self._rejected_store.delete(rejected_id)
        except Exception as exc:
            raise AppError(
                code="RESTORE_DELETE_REJECTED",
                message="Failed to delete restored rejected-email metadata",
                context={"rejected_id": rejected_id},
                cause=exc,
            )

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _encode(value: object) -> str:
        """JSON-encode a value for an agent template input."""
        return json.dumps(value)

    @staticmethod
    def _opt_str(value: object) -> str | None:
        """Return a non-empty trimmed string or None."""
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _safe_confidence(value: object) -> float:
        """Coerce a confidence into [0,1], defaulting to 1.0 (distiller default)."""
        try:
            return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return 1.0
