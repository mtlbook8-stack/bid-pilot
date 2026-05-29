"""
BidProcessingOrchestrator — the stateless driver of the 3-agent bid pipeline.

WHY this class exists (build doc section 8.2): a parsed bid must pass through
three sequential decisions — Validate (Agent 1) -> Match-to-project (Agent 2,
preceded by a code-only address match) -> Categorize-into-a-job (Agent 3). Each
step is expensive (an LLM call, sometimes a geocode), so the work cannot simply
be re-run wholesale on a crash. This orchestrator implements the checkpoint
pattern the build doc mandates: BEFORE each agent runs, it writes an
in-progress status to the bid's Cosmos document, then runs the agent, then
writes the completed status. Because the Cosmos document IS the orchestrator's
only memory (the class holds no per-bid state — Rule 2/6.2), a crash mid-agent
leaves a durable "Validating" / "MatchingProject" / "CategorizingJob" marker,
and the 15-minute retry trigger simply calls `process_bid` again. The method is
written to be RESUMABLE: it inspects the current status and skips any step that
is already complete, so a re-invocation continues from the exact checkpoint
rather than re-paying for finished agents.

This is pure orchestration (Rule 2): it knows nothing about HTTP or Cosmos
internals. Every collaborator is an interface injected through the constructor
(Rule 3); the class never constructs a dependency. Every external/agent call is
wrapped and re-raised as an AppError with a unique code (Rules 7, 8).
"""

import json
import logging
import re
import time

from src.agents.pipeline.job_categorizer import JobCategorizer
from src.agents.pipeline.project_matcher import ProjectMatcher
from src.agents.pipeline.quote_validator import QuoteValidator
from src.api.config import Settings
from src.core.enums import (
    BidStatus,
    MatchType,
    RejectionCategory,
    TradeCategory,
)
from src.core.errors.app_error import AppError
from src.core.interfaces.bid_store import IBidStore
from src.core.interfaces.geocoding_service import IGeocodingService
from src.core.interfaces.job_store import IJobStore
from src.core.interfaces.project_store import IProjectStore
from src.core.interfaces.rejected_store import IRejectedEmailStore
from src.core.interfaces.telemetry_service import ITelemetryService
from src.core.models.bid import AgentResult, IngestedBid
from src.core.models.job import JobSummary
from src.core.models.project import ProjectSummary
from src.core.models.rejected_email import RejectedEmailMetadata

logger = logging.getLogger(__name__)

# US-style street-address heuristic: a leading street number followed by a
# street name and a common street-type suffix. This is deliberately conservative
# — a false negative just routes the bid to Agent 2 (the normal path), whereas a
# false positive could geocode garbage. We only need ONE plausible hint; the
# geocoder and (if needed) Agent 2 do the real work of resolving it.
_ADDRESS_HINT_RE = re.compile(
    r"\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s){0,5}"
    r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|"
    r"Way|Court|Ct|Place|Pl|Terrace|Ter|Circle|Cir|Highway|Hwy|Parkway|Pkwy|"
    r"Square|Sq|Trail|Trl|Suite|Ste)\b"
    r"(?:[,\s]+(?:[A-Za-z.'-]+\s?){0,3},?\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?)?",
    re.IGNORECASE,
)


class BidProcessingOrchestrator:
    """
    Drives a single bid through Validate -> Match -> Categorize with checkpoints.

    The orchestrator is completely stateless: the only mutable state lives on the
    `IngestedBid` Cosmos document, which is read at entry and saved at every
    checkpoint. `process_bid` is idempotent and resumable — calling it again on a
    partially-processed bid skips already-completed steps based on `bid.status`,
    which is exactly how the retry trigger recovers from a crash (build doc 8.2
    "Crash recovery").
    """

    def __init__(
        self,
        validator: QuoteValidator,
        matcher: ProjectMatcher,
        categorizer: JobCategorizer,
        geocoder: IGeocodingService,
        bid_store: IBidStore,
        project_store: IProjectStore,
        job_store: IJobStore,
        rejected_store: IRejectedEmailStore,
        telemetry: ITelemetryService,
        settings: Settings,
    ) -> None:
        # Pure DI (Rule 3): every collaborator is an injected interface/agent.
        # Nothing is constructed here.
        self._validator = validator
        self._matcher = matcher
        self._categorizer = categorizer
        self._geocoder = geocoder
        self._bid_store = bid_store
        self._project_store = project_store
        self._job_store = job_store
        self._rejected_store = rejected_store
        self._telemetry = telemetry
        self._settings = settings

    async def process_bid(self, bid: IngestedBid) -> IngestedBid:
        """
        Run the bid through the full pipeline, resuming from its current status.

        Resumability (the crash-recovery contract): each agent step is guarded by
        a status check, so this method can be called repeatedly on the same bid.
        - A fresh bid (Parsed) runs all three steps.
        - A bid left at Validating/Validated re-enters at Agent 1 / project
          matching respectively.
        - A bid at MatchingProject/ProjectMatched skips Agent 1 and resumes at
          matching / categorization.
        - A bid at CategorizingJob skips Agents 1 and 2 and resumes at Agent 3.
        This is what lets the retry trigger simply re-call `process_bid` without
        any separate resume logic.

        On ANY AppError raised by a step, the bid's retry_count is incremented and
        — once it reaches settings.max_bid_retries — the status is set to FAILED
        and saved before the error is re-raised (Rules 7, 8). The error always
        propagates so the single top-level handler logs it exactly once.
        """
        started = time.perf_counter()
        agents_called: list[str] = []

        try:
            # --- Step 1: validation (Agent 1) -----------------------------------
            # Skip if the bid is already past validation (resume case). A bid that
            # is still Parsed/Validating has not been confirmed a bid yet.
            if bid.status in (BidStatus.PARSED, BidStatus.VALIDATING):
                rejected = await self._run_validation(bid, agents_called)
                if rejected:
                    # Not a bid: metadata filed, status REJECTED, terminal — stop.
                    self._track_run(bid, started, agents_called)
                    return bid

            # If a prior run rejected this bid, there is nothing more to do.
            if bid.status == BidStatus.REJECTED:
                return bid

            # --- Step 2: project matching (code-first, then Agent 2) ------------
            # Resume guard: only run while the project is not yet assigned. Once a
            # bid is PROJECT_MATCHED/CategorizingJob/Categorized we skip this.
            if bid.status in (BidStatus.VALIDATED, BidStatus.MATCHING_PROJECT):
                await self._run_project_matching(bid, agents_called)

            # --- Step 3: job categorization (Agent 3) ---------------------------
            if bid.status in (BidStatus.PROJECT_MATCHED, BidStatus.CATEGORIZING_JOB):
                await self._run_categorization(bid, agents_called)

            self._track_run(bid, started, agents_called)
            return bid

        except AppError as err:
            # A pipeline step failed. The checkpoint is already persisted (we save
            # BEFORE each agent), so we only need to record the retry budget here.
            await self._handle_failure(bid, err)
            raise

    async def _run_validation(
        self, bid: IngestedBid, agents_called: list[str]
    ) -> bool:
        """
        Run Agent 1 and apply its decision. Returns True if the bid was rejected.

        Writes the VALIDATING checkpoint BEFORE calling the agent so a crash
        mid-call leaves a resumable marker. On `is_bid == False` it files
        lightweight metadata into the rejected-emails container (no document text
        or attachment — build doc 6.4), flips the bid to REJECTED, and returns
        True so the caller stops. On `is_bid == True` it advances to VALIDATED.

        The bid only stores `document_text` and `table_count`; it does not retain
        the per-table headers, so `table_headers_summary` is passed empty per the
        task contract (the agent still has the table count and full text).
        """
        agents_called.append("QuoteValidator")
        bid.advance_to(BidStatus.VALIDATING)  # checkpoint
        await self._save(bid, "BID_PIPELINE_SAVE_VALIDATING")

        try:
            result = await self._validator.validate(
                sender_email=bid.sender_email,
                email_subject=bid.email_subject,
                attachment_file_name=bid.attachment_filename,
                table_count=bid.table_count,
                # Headers are not retained on the bid document; pass empty.
                table_headers_summary="",
                document_text=bid.document_text,
                bid_id=bid.id,
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_VALIDATE",
                message="QuoteValidator step failed",
                context={"bid_id": bid.id},
                cause=exc,
            )

        confidence = self._safe_confidence(result.get("confidence"))
        bid.is_bid = bool(result.get("is_bid"))
        bid.record_agent_result(
            AgentResult(
                agent_name="QuoteValidator",
                confidence=confidence,
                reasoning=str(result.get("reasoning", "")),
                raw_output=result,
            )
        )

        if not bid.is_bid:
            await self._reject(bid, result, confidence)
            return True

        bid.advance_to(BidStatus.VALIDATED)
        await self._save(bid, "BID_PIPELINE_SAVE_VALIDATED")
        return False

    async def _reject(
        self, bid: IngestedBid, result: dict, confidence: float
    ) -> None:
        """
        File rejected-email metadata and mark the bid REJECTED (terminal).

        The agent's `rejection_category` is mapped onto the RejectionCategory enum
        defensively: an unknown/None value falls back to NOT_CONSTRUCTION rather
        than crashing the pipeline on a minor agent formatting drift.
        """
        rejection_reason = self._map_rejection_category(result.get("rejection_category"))
        metadata = RejectedEmailMetadata(
            id=RejectedEmailMetadata.make_id(bid.message_id),
            message_id=bid.message_id,
            linked_account_id=bid.linked_account_id,
            sender_email=bid.sender_email,
            subject=bid.email_subject,
            received_at=bid.received_at,
            rejection_reason=rejection_reason,
            agent_confidence=confidence,
        )
        try:
            await self._rejected_store.add(metadata)
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_REJECT_WRITE",
                message="Failed to write rejected-email metadata",
                context={"bid_id": bid.id, "message_id": bid.message_id},
                cause=exc,
            )

        bid.advance_to(BidStatus.REJECTED)
        await self._save(bid, "BID_PIPELINE_SAVE_REJECTED")

    async def _run_project_matching(
        self, bid: IngestedBid, agents_called: list[str]
    ) -> None:
        """
        Resolve the bid's project: address-first in code, Agent 2 only if needed.

        Per build doc 8.2, we try the cheap path first:
          1. Heuristically extract an address hint from the document text.
          2. Geocode it to a canonical normalized address (Azure Maps).
          3. If the normalized address EXACTLY matches an existing project, assign
             it and SKIP Agent 2 entirely — this saves ~$0.01 per bid.
        Only when no exact match is found do we write the MatchingProject
        checkpoint and call Agent 2. When Agent 2 returns match_type "new", we
        geocode the new project's address too and persist its normalizedAddress so
        future bids to the same site match in code and never reach Agent 2 again.
        """
        hint = self._extract_address_hint(bid.document_text)
        normalized_address: str | None = None
        geocode_status = "not_attempted"

        if hint:
            geocode = await self._geocode(hint, bid.id, "BID_PIPELINE_GEOCODE")
            normalized_address = geocode.normalized_address
            geocode_status = geocode.status
            bid.address_from_bid = hint
            bid.normalized_address = normalized_address

        # Code-first exact match — no LLM cost when the site is already known.
        if normalized_address:
            existing = await self._find_project_by_address(normalized_address, bid.id)
            if existing is not None:
                bid.matched_project_id = existing.id
                bid.advance_to(BidStatus.PROJECT_MATCHED)
                await self._save(bid, "BID_PIPELINE_SAVE_MATCHED_CODE")
                return

        # No code match — fall back to Agent 2. Checkpoint BEFORE the call.
        agents_called.append("ProjectMatcher")
        bid.advance_to(BidStatus.MATCHING_PROJECT)
        await self._save(bid, "BID_PIPELINE_SAVE_MATCHING")

        existing_projects_json = await self._existing_projects_json(bid.id)

        try:
            result = await self._matcher.match(
                normalized_address=normalized_address or "",
                geocode_status=geocode_status,
                existing_projects_json=existing_projects_json,
                sender_email=bid.sender_email,
                email_subject=bid.email_subject,
                attachment_file_name=bid.attachment_filename,
                document_text=bid.document_text,
                bid_id=bid.id,
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_MATCH",
                message="ProjectMatcher step failed",
                context={"bid_id": bid.id},
                cause=exc,
            )

        bid.record_agent_result(
            AgentResult(
                agent_name="ProjectMatcher",
                confidence=self._safe_confidence(result.get("confidence")),
                reasoning=str(result.get("reasoning", "")),
                raw_output=result,
            )
        )
        if result.get("address_from_bid"):
            bid.address_from_bid = str(result["address_from_bid"])

        match_type = str(result.get("match_type", "")).strip().lower()
        if match_type == MatchType.EXISTING.value and result.get("project_id"):
            bid.matched_project_id = str(result["project_id"])
        else:
            # Treat anything that is not a confirmed existing match as "new" so a
            # missing/garbled match_type never strands the bid without a project.
            new_project = await self._create_project(result, bid)
            bid.matched_project_id = new_project.id

        bid.advance_to(BidStatus.PROJECT_MATCHED)
        await self._save(bid, "BID_PIPELINE_SAVE_PROJECT_MATCHED")

    async def _create_project(self, result: dict, bid: IngestedBid) -> ProjectSummary:
        """
        Build, geocode, and persist a new project from Agent 2's `new_project`.

        Geocoding the new project's address and storing its normalizedAddress is
        what prevents future duplicates: the next bid to the same site will match
        it in code and skip Agent 2 (build doc 8.2 pre-agent step 6). A geocode
        failure here is non-fatal — we still create the project, just without a
        normalized address — because a missing dedupe hint is better than failing
        an otherwise-successful match.
        """
        details = result.get("new_project") or {}
        address = self._opt_str(details.get("address"))
        normalized_address: str | None = None
        if address:
            geocode = await self._geocode(
                address, bid.id, "BID_PIPELINE_GEOCODE_NEW_PROJECT"
            )
            normalized_address = geocode.normalized_address

        project = ProjectSummary(
            id=IngestedBid.make_id(bid.id, "project"),
            name=self._opt_str(details.get("name")) or (address or "Untitled Project"),
            address=address,
            normalized_address=normalized_address,
            client_name=self._opt_str(details.get("client_name")),
            client_contact=self._opt_str(details.get("client_contact")),
        )
        try:
            return await self._project_store.upsert(project)
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_PROJECT_UPSERT",
                message="Failed to persist new project",
                context={"bid_id": bid.id, "project_id": project.id},
                cause=exc,
            )

    async def _run_categorization(
        self, bid: IngestedBid, agents_called: list[str]
    ) -> None:
        """
        Run Agent 3 to assign a trade + job, extract the vendor, and summarize.

        Writes the CategorizingJob checkpoint BEFORE the call. Loads the project
        (for the prompt's name/address) and the project's existing jobs as the
        candidate set. After the agent returns it either reuses an existing job or
        creates a new one, then registers this bid on that job (job.add_bid +
        upsert) so the job's bid_ids drive the eventual comparison. total_price is
        NOT part of Agent 3's output, so it is intentionally left as-is (None).
        """
        agents_called.append("JobCategorizer")
        bid.advance_to(BidStatus.CATEGORIZING_JOB)  # checkpoint
        await self._save(bid, "BID_PIPELINE_SAVE_CATEGORIZING")

        project = await self._load_project(bid)
        existing_jobs = await self._list_jobs(bid, project.id)
        existing_jobs_json = self._jobs_to_json(existing_jobs)

        try:
            result = await self._categorizer.categorize(
                project_name=project.name,
                project_address=project.address or "",
                existing_jobs_json=existing_jobs_json,
                sender_email=bid.sender_email,
                email_subject=bid.email_subject,
                attachment_file_name=bid.attachment_filename,
                document_text=bid.document_text,
                bid_id=bid.id,
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_CATEGORIZE",
                message="JobCategorizer step failed",
                context={"bid_id": bid.id},
                cause=exc,
            )

        trade = TradeCategory.from_label(str(result.get("trade_category", "")))
        bid.record_agent_result(
            AgentResult(
                agent_name="JobCategorizer",
                confidence=self._safe_confidence(result.get("confidence")),
                reasoning=str(result.get("reasoning", "")),
                raw_output=result,
            )
        )

        job = await self._resolve_job(bid, project.id, result, trade, existing_jobs)
        job.add_bid(bid.id)
        try:
            await self._job_store.upsert(job)
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_JOB_UPSERT",
                message="Failed to persist job assignment",
                context={"bid_id": bid.id, "job_id": job.id},
                cause=exc,
            )

        # Project Agent 3's structured output onto the bid. total_price is not in
        # Agent 3's schema, so it is deliberately left untouched (stays None).
        bid.matched_job_id = job.id
        bid.trade_category = trade
        bid.secondary_trades = self._str_list(result.get("secondary_trades"))
        bid.vendor_name = self._opt_str(result.get("vendor_name"))
        bid.scope_summary = self._opt_str(result.get("scope_summary"))

        bid.advance_to(BidStatus.CATEGORIZED)
        await self._save(bid, "BID_PIPELINE_SAVE_CATEGORIZED")

    async def _resolve_job(
        self,
        bid: IngestedBid,
        project_id: str,
        result: dict,
        trade: TradeCategory,
        existing_jobs: list[JobSummary],
    ) -> JobSummary:
        """
        Return the JobSummary this bid belongs to — an existing one or a new one.

        When Agent 3 says it is NOT a new job and names an existing_job_id that we
        actually loaded, reuse it. Otherwise create a new job (the job_name comes
        from the scope summary if available, else the trade label) so an absent or
        stale existing_job_id can never strand the bid.
        """
        is_new = bool(result.get("is_new_job"))
        existing_id = self._opt_str(result.get("existing_job_id"))

        if not is_new and existing_id:
            match = next((j for j in existing_jobs if j.id == existing_id), None)
            if match is not None:
                return match

        # A job's identity is (project, trade): one trade scope per project. The id
        # is therefore deterministic, which also guards against clobbering — if a
        # job for this trade already exists (e.g. Agent 3 mislabeled this as "new"),
        # reuse it so its existing bid_ids are preserved rather than overwritten by
        # a fresh, empty JobSummary on upsert.
        new_id = IngestedBid.make_id(project_id, f"job::{trade.value}")
        collision = next((j for j in existing_jobs if j.id == new_id), None)
        if collision is not None:
            return collision

        scope = self._opt_str(result.get("scope_summary"))
        return JobSummary(
            id=new_id,
            project_id=project_id,
            trade_category=trade,
            job_name=scope or trade.value,
        )

    async def _handle_failure(self, bid: IngestedBid, err: AppError) -> None:
        """
        Increment the retry budget and mark FAILED once it is exhausted.

        We do not flip to FAILED on the first error: the bid is left at its
        in-progress checkpoint so the retry trigger can resume it. Only when
        retry_count reaches settings.max_bid_retries do we set FAILED (so the bid
        stops being retried and surfaces for human attention). The persistence of
        this bookkeeping must not mask the original error — a save failure here is
        wrapped but the original `err` still propagates from `process_bid`.
        """
        bid.retry_count += 1
        if bid.retry_count >= self._settings.max_bid_retries:
            bid.advance_to(BidStatus.FAILED)
        else:
            bid.touch()
        try:
            await self._bid_store.upsert(bid)
        except Exception as save_exc:
            # Do not raise: we are already unwinding `err`, which is the real
            # cause. Log-worthy detail is attached to a wrapped error the caller
            # would see only if it inspected, but we must let `err` win.
            logger.warning(
                "Failed to persist retry bookkeeping for bid %s (%s); "
                "original error %s will propagate",
                bid.id,
                save_exc,
                err.code,
            )

    # ----------------------------- helpers ---------------------------------

    @staticmethod
    def _extract_address_hint(text: str) -> str | None:
        """
        Heuristically pull a US-style street address out of the document text.

        Pure code, no LLM (build doc 8.2 pre-agent step 1). Returns the first
        plausible match or None. A miss is harmless: the pipeline then geocodes
        nothing and goes straight to Agent 2, which is the standard path.
        """
        if not text:
            return None
        match = _ADDRESS_HINT_RE.search(text)
        if not match:
            return None
        return " ".join(match.group(0).split()).strip(" ,")

    async def _geocode(self, address: str, bid_id: str, code: str):
        """Normalize an address via the geocoder, wrapping failures (Rule 7)."""
        try:
            return await self._geocoder.normalize(address)
        except Exception as exc:
            raise AppError(
                code=code,
                message="Geocoding call failed",
                context={"bid_id": bid_id},
                cause=exc,
            )

    async def _find_project_by_address(self, normalized_address: str, bid_id: str):
        try:
            return await self._project_store.find_by_normalized_address(
                normalized_address
            )
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_ADDRESS_LOOKUP",
                message="Project address lookup failed",
                context={"bid_id": bid_id},
                cause=exc,
            )

    async def _existing_projects_json(self, bid_id: str) -> str:
        """
        Serialize all projects (id+name+address+normalizedAddress+clientName) for
        Agent 2. The agent receives pre-shaped data; it never queries Cosmos.
        """
        try:
            projects = await self._project_store.list_all()
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_LIST_PROJECTS",
                message="Failed to list projects for matching",
                context={"bid_id": bid_id},
                cause=exc,
            )
        payload = [
            {
                "id": p.id,
                "name": p.name,
                "address": p.address,
                "normalizedAddress": p.normalized_address,
                "clientName": p.client_name,
            }
            for p in projects
        ]
        return json.dumps(payload)

    async def _load_project(self, bid: IngestedBid) -> ProjectSummary:
        if not bid.matched_project_id:
            raise AppError(
                code="BID_PIPELINE_NO_PROJECT",
                message="Categorization reached without a matched project",
                context={"bid_id": bid.id},
            )
        try:
            project = await self._project_store.get(bid.matched_project_id)
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_LOAD_PROJECT",
                message="Failed to load matched project",
                context={"bid_id": bid.id, "project_id": bid.matched_project_id},
                cause=exc,
            )
        if project is None:
            raise AppError(
                code="BID_PIPELINE_PROJECT_MISSING",
                message="Matched project no longer exists",
                context={"bid_id": bid.id, "project_id": bid.matched_project_id},
            )
        return project

    async def _list_jobs(self, bid: IngestedBid, project_id: str) -> list[JobSummary]:
        try:
            return await self._job_store.list_for_project(project_id)
        except Exception as exc:
            raise AppError(
                code="BID_PIPELINE_LIST_JOBS",
                message="Failed to list jobs for project",
                context={"bid_id": bid.id, "project_id": project_id},
                cause=exc,
            )

    @staticmethod
    def _jobs_to_json(jobs: list[JobSummary]) -> str:
        payload = [
            {
                "id": j.id,
                "tradeCategory": j.trade_category.value,
                "jobName": j.job_name,
                "bidCount": j.bid_count,
            }
            for j in jobs
        ]
        return json.dumps(payload)

    async def _save(self, bid: IngestedBid, code: str) -> None:
        """Persist the bid's current checkpoint, wrapping store errors (Rule 7)."""
        try:
            await self._bid_store.upsert(bid)
        except Exception as exc:
            raise AppError(
                code=code,
                message="Failed to save bid checkpoint",
                context={"bid_id": bid.id, "status": bid.status.value},
                cause=exc,
            )

    def _track_run(
        self, bid: IngestedBid, started: float, agents_called: list[str]
    ) -> None:
        """
        Emit a single pipeline-run telemetry span on success.

        total_tokens is reported as 0 here: per-call token usage is tracked inside
        BaseAgent via track_llm_call (build doc section 5), so the orchestrator
        does not double-count it at the pipeline level. The agents_called list and
        final status are the orchestration-level signal.
        """
        duration_ms = (time.perf_counter() - started) * 1000.0
        try:
            self._telemetry.track_pipeline_run(
                bid_id=bid.id,
                status=bid.status.value,
                duration_ms=duration_ms,
                agents_called=agents_called,
                total_tokens=0,
            )
        except Exception:
            # Telemetry must never break the pipeline. A failed span is acceptable
            # to swallow because the bid itself is already durably saved.
            logger.warning("Failed to emit pipeline telemetry for bid %s", bid.id)

    @staticmethod
    def _map_rejection_category(value: object) -> RejectionCategory:
        """Map an agent string to RejectionCategory, defaulting to NOT_CONSTRUCTION."""
        try:
            return RejectionCategory(str(value))
        except (ValueError, TypeError):
            return RejectionCategory.NOT_CONSTRUCTION

    @staticmethod
    def _safe_confidence(value: object) -> float:
        """Coerce an agent confidence into the [0,1] range, defaulting to 0.0."""
        try:
            return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _opt_str(value: object) -> str | None:
        """Return a non-empty trimmed string or None."""
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _str_list(value: object) -> list[str]:
        """Coerce an agent list field into a list of non-empty strings."""
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
