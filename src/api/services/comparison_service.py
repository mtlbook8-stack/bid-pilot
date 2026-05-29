"""
ComparisonService — drives the core comparison product (build doc 8.3).

WHY this exists: the comparison is BidPilot's reason to exist. This service owns
the two server-side halves of the flow:
  1. `start` — build a ComparisonSession over a job's bids and run the assembly
     pipeline (Agents 5/6/7) so the frontend gets a table to render.
  2. `chat` — the live SSE loop: route the user's message through the
     ComparisonOrchestrator (Agent 4), dispatch to the named specialist (Agents
     5/6/7/9/11/13 or table-update/clarification), append the turn, compact when
     history grows past the threshold (Agent 8), and stream the result as SSE.
  3. `summarize` — produce a shareable session summary (Agent 11).

One job (Rule 2): comparison orchestration at the API layer. Every collaborator
is injected (Rule 3). Stores/agents are wrapped as AppError (Rules 7, 8); the
chat loop additionally emits an `error` SSE frame so the user sees failures live.
"""

import json
import logging
import uuid
from typing import AsyncIterator

from src.agents.comparison.comparison_orchestrator import ComparisonOrchestrator
from src.agents.comparison.context_compactor import ContextCompactor
from src.agents.comparison.cost_comparator import CostComparator
from src.agents.comparison.data_query_agent import DataQueryAgent
from src.agents.comparison.feature_analyst import FeatureAnalyst
from src.agents.comparison.unit_normalizer import UnitNormalizer
from src.agents.insights.decision_explainer import DecisionExplainer
from src.agents.insights.session_summarizer import SessionSummarizer
from src.core.enums import ChatRole, ComparisonPhase, DecisionStatus
from src.core.models.comparison import CompactedContext
from src.core.errors.app_error import AppError
from src.core.interfaces.bid_store import IBidStore
from src.core.interfaces.job_store import IJobStore
from src.core.interfaces.project_store import IProjectStore
from src.core.interfaces.session_store import IComparisonSessionStore
from src.core.interfaces.telemetry_service import ITelemetryService
from src.core.models.bid import IngestedBid
from src.core.models.comparison import ChatMessage, ComparisonSession
from src.core.models.job import JobSummary
from src.orchestration.comparison_pipeline import ComparisonPipeline

logger = logging.getLogger(__name__)

# How many recent turns to give the router for intent context (build doc Agent 4
# template: "Last 3 messages").
_RECENT_MESSAGES_FOR_ROUTING = 3


class ComparisonService:
    """Builds comparison sessions and runs the routed chat loop."""

    def __init__(
        self,
        comparison_pipeline: ComparisonPipeline,
        session_store: IComparisonSessionStore,
        bid_store: IBidStore,
        project_store: IProjectStore,
        job_store: IJobStore,
        comparison_orchestrator: ComparisonOrchestrator,
        unit_normalizer: UnitNormalizer,
        cost_comparator: CostComparator,
        feature_analyst: FeatureAnalyst,
        context_compactor: ContextCompactor,
        data_query_agent: DataQueryAgent,
        session_summarizer: SessionSummarizer,
        decision_explainer: DecisionExplainer,
        telemetry: ITelemetryService,
    ) -> None:
        # Pure DI (Rule 3): every store, agent, and the assembly pipeline are
        # injected by the composition root.
        self._pipeline = comparison_pipeline
        self._session_store = session_store
        self._bid_store = bid_store
        self._project_store = project_store
        self._job_store = job_store
        self._orchestrator = comparison_orchestrator
        self._unit_normalizer = unit_normalizer
        self._cost_comparator = cost_comparator
        self._feature_analyst = feature_analyst
        self._context_compactor = context_compactor
        self._data_query_agent = data_query_agent
        self._session_summarizer = session_summarizer
        self._decision_explainer = decision_explainer
        self._telemetry = telemetry

    # ------------------------------------------------------------------ start

    async def start(self, project_id: str, job_id: str) -> ComparisonSession:
        """
        Create a ComparisonSession for a job's bids and assemble its table.

        Loads the job (for name + bid ids + trade) and its bids (for vendor
        names), builds a fresh session with a uuid id, then delegates to the
        ComparisonPipeline which runs Agents 5/6/7, assembles the table, and saves
        the session with phase READY. Returns the populated session for the router
        to serialize.
        """
        job = await self._load_job(project_id, job_id)
        project = await self._load_project(project_id)
        bids = await self._load_bids_for_job(job)

        session = ComparisonSession(
            id=str(uuid.uuid4()),
            project_id=project_id,
            job_id=job_id,
            project_name=project.name,
            job_name=job.job_name,
            trade_category=job.trade_category.value,
            bid_ids=[bid.id for bid in bids],
            vendor_names=[bid.vendor_name or bid.sender_email for bid in bids],
            phase=ComparisonPhase.NORMALIZING,
        )

        # The pipeline owns the phase checkpoints + table assembly + the READY
        # save; we just hand it the session and return its result.
        return await self._pipeline.start(session=session)

    # ------------------------------------------------------------------- chat

    async def chat(
        self, project_id: str, session_id: str, user_message: str
    ) -> AsyncIterator[dict]:
        """
        Run one chat turn over a session, streaming SSE event dicts.

        Sequence:
          1. Load the session and append the user's message.
          2. Route via ComparisonOrchestrator (Agent 4) -> yield a `routed` event
             naming the chosen specialist.
          3. Dispatch to that specialist, producing the assistant content.
          4. Append the assistant turn (tagged with the handler).
          5. If history now exceeds the compaction threshold, run ContextCompactor
             (Agent 8) and trim the raw history.
          6. Save the session, yield the `message` event, then a final `done`.

        Any failure is wrapped as AppError AND emitted as an `error` SSE frame so
        the client sees the failure live (Rules 7, 8). The generator then ends.
        """
        try:
            session = await self._load_session(project_id, session_id)
            session.add_message(
                ChatMessage(role=ChatRole.USER, content=user_message)
            )

            routing = await self._route(session, user_message)
            agent = str(routing.get("agent", "clarification")).strip()
            extracted_query = str(routing.get("extracted_query", user_message))
            yield {"event": "routed", "agent": agent}

            content = await self._dispatch(session, agent, extracted_query)

            session.add_message(
                ChatMessage(
                    role=ChatRole.ASSISTANT, content=content, handled_by=agent
                )
            )

            await self._maybe_compact(session)
            await self._save(session)

            yield {"event": "message", "content": content, "handledBy": agent}
            yield {"event": "done"}
        except AppError as err:
            # Surface the failure as an SSE frame so the UI shows it inline, then
            # end the stream. The top-level handler does not see this (we consumed
            # it), but the error id is still reported to the user.
            logger.warning(
                "Comparison chat failed (%s) for session %s", err.code, session_id
            )
            yield {"event": "error", **err.user_message}
        except Exception as exc:  # pragma: no cover - defensive
            wrapped = AppError(
                code="COMPARISON_CHAT",
                message="Comparison chat turn failed",
                context={"project_id": project_id, "session_id": session_id},
                cause=exc,
            )
            logger.warning("Comparison chat crashed for session %s", session_id)
            yield {"event": "error", **wrapped.user_message}

    async def _route(
        self, session: ComparisonSession, user_message: str
    ) -> dict:
        """
        Ask Agent 4 which specialist should handle the message.

        Builds the router context (vendors, phase, last few turns) and returns its
        parsed dict {agent, confidence, extracted_query, reasoning}. The agent
        wraps its own LLM failures; assembly here is defensive.
        """
        recent = session.recent_messages(_RECENT_MESSAGES_FOR_ROUTING)
        recent_text = "\n".join(f"{m.role.value}: {m.content}" for m in recent)
        return await self._orchestrator.route(
            project_name=session.project_name,
            job_name=session.job_name,
            vendor_list=", ".join(session.vendor_names),
            phase=session.phase.value,
            recent_messages=recent_text,
            user_message=user_message,
            session_id=session.id,
            project_id=session.project_id,
        )

    async def _dispatch(
        self, session: ComparisonSession, agent: str, extracted_query: str
    ) -> str:
        """
        Route the message to the named specialist and return its text content.

        The routing map mirrors the ComparisonOrchestrator's agent vocabulary
        (build doc Agent 4). For agents whose natural output is structured (cost,
        feature, decision, data query, summarizer), we JSON-encode the result as
        the message content — the frontend renders it; the priority is a working,
        well-structured pipeline. `table_update` and `clarification` are handled
        as conversational responses without invoking a heavy agent.
        """
        # --- cost: re-run the cost comparison over the session's normalized data.
        # The session already holds an assembled table; for a chat cost question
        # we surface the existing cost section (cheap, deterministic) rather than
        # re-paying for a full re-normalize. If no table exists yet we say so.
        if agent == "cost_comparator":
            return self._encode(self._cost_section(session))

        # --- feature: surface the existing feature section similarly.
        if agent == "feature_analyst":
            return self._encode(self._feature_section(session))

        # --- unit_normalizer: re-normalize the bids and return the new groups.
        if agent == "unit_normalizer":
            return self._encode(await self._renormalize(session))

        # --- data_query: two-phase cross-project query (plan -> fetch -> code).
        if agent == "data_query":
            return self._encode(await self._data_query(session, extracted_query))

        # --- session_summarizer: produce a shareable summary inline.
        if agent == "session_summarizer":
            return self._encode(await self._summarize_session(session))

        # --- decision_explainer: structured decision analysis (Agent 13).
        if agent == "decision_explainer":
            return self._encode(await self._explain(session, extracted_query))

        # --- table_update: a direct edit request. Applying arbitrary edits is out
        # of scope for the server here; we acknowledge the request so the UI can
        # capture it as a conversational turn (the edit itself is a frontend table
        # mutation). Documented simplification.
        if agent == "table_update":
            return (
                "Noted the requested table change. Edit the comparison table "
                "directly to apply it."
            )

        # --- clarification (and any unknown agent): ask for more detail.
        return (
            "Could you clarify what you'd like to compare or decide? For example "
            "ask about costs, warranties, schedule, or a recommendation."
        )

    async def _renormalize(self, session: ComparisonSession) -> dict:
        """Re-run UnitNormalizer over the session's bids (build doc Agent 5)."""
        bids = await self._load_bids(session.bid_ids, session)
        bids_block = self._render_bids_block(bids)
        return await self._unit_normalizer.normalize(
            project_name=session.project_name,
            job_name=session.job_name,
            trade_category=session.trade_category,
            bids_block=bids_block,
            session_id=session.id,
            project_id=session.project_id,
        )

    async def _data_query(
        self, session: ComparisonSession, extracted_query: str
    ) -> dict:
        """
        Run the two-phase DataQueryAgent (build doc Agent 9).

        Phase 1 plans which collections/filters are needed; this service then
        fetches that data from Cosmos via the stores (best-effort: bids via
        list_all, projects via list_all, jobs per project) and Phase 2 generates
        + runs code over it in the sandbox to answer. Returns Phase 2's dict
        {answer, data, confidence}.
        """
        plan = await self._data_query_agent.plan(
            extracted_query=extracted_query,
            project_name=session.project_name,
            job_name=session.job_name,
            trade_category=session.trade_category,
            vendor_list=", ".join(session.vendor_names),
            session_id=session.id,
            project_id=session.project_id,
        )

        collections = plan.get("collections_needed") or []
        query_results = await self._gather_query_data(collections, session)

        return await self._data_query_agent.generate_and_run(
            extracted_query=extracted_query,
            phase1_output=self._encode(plan),
            query_results_json=self._encode(query_results),
            session_id=session.id,
            project_id=session.project_id,
        )

    async def _gather_query_data(
        self, collections: list, session: ComparisonSession
    ) -> dict:
        """
        Fetch the data collections the query plan asked for.

        Best-effort per the task contract: we load whole collections (bids,
        projects, jobs) the agent's Phase-2 code then filters in the sandbox. The
        collection names mirror the Agent 9 data dictionary. Each read is wrapped
        so a failure is attributable.
        """
        results: dict = {}
        wanted = {str(c).strip().lower() for c in collections}

        if "bids" in wanted:
            bids = await self._safe(
                self._bid_store.list_all(), "COMPARISON_QUERY_BIDS"
            )
            results["bids"] = [
                {
                    "id": b.id,
                    "matchedProjectId": b.matched_project_id,
                    "matchedJobId": b.matched_job_id,
                    "vendorName": b.vendor_name,
                    "tradeCategory": (
                        b.trade_category.value if b.trade_category else None
                    ),
                    "totalPrice": b.total_price,
                    "scopeSummary": b.scope_summary,
                    "status": b.status.value,
                    "createdAt": b.created_at.isoformat(),
                }
                for b in bids
            ]

        if "projects" in wanted:
            projects = await self._safe(
                self._project_store.list_all(), "COMPARISON_QUERY_PROJECTS"
            )
            results["projects"] = [
                {
                    "id": p.id,
                    "name": p.name,
                    "address": p.address,
                    "normalizedAddress": p.normalized_address,
                    "clientName": p.client_name,
                    "createdAt": p.created_at.isoformat(),
                }
                for p in projects
            ]
            # Jobs are partitioned by project; gather per project when requested.
            if "jobs" in wanted:
                jobs_out: list = []
                for project in projects:
                    jobs = await self._safe(
                        self._job_store.list_for_project(project.id),
                        "COMPARISON_QUERY_JOBS",
                    )
                    jobs_out.extend(
                        {
                            "id": j.id,
                            "projectId": j.project_id,
                            "tradeCategory": j.trade_category.value,
                            "jobName": j.job_name,
                            "createdAt": j.created_at.isoformat(),
                        }
                        for j in jobs
                    )
                results["jobs"] = jobs_out

        return results

    async def _summarize_session(self, session: ComparisonSession) -> dict:
        """Summarize via Agent 11, reusing the table + history (build doc)."""
        return await self._session_summarizer.summarize(
            project_name=session.project_name,
            job_name=session.job_name,
            trade_category=session.trade_category,
            vendor_list=", ".join(session.vendor_names),
            comparison_table_json=self._table_json(session),
            conversation_history_or_compacted_summary=self._history_text(session),
            session_id=session.id,
            project_id=session.project_id,
        )

    async def _explain(
        self, session: ComparisonSession, extracted_query: str
    ) -> dict:
        """Run DecisionExplainer (Agent 13) over the table + preferences."""
        return await self._decision_explainer.explain(
            project_name=session.project_name,
            job_name=session.job_name,
            trade_category=session.trade_category,
            comparison_table_json=self._table_json(session),
            compacted_preferences_or_history=self._history_text(session),
            extracted_query=extracted_query,
            session_id=session.id,
            project_id=session.project_id,
        )

    async def _maybe_compact(self, session: ComparisonSession) -> None:
        """
        Compact the conversation when it exceeds the threshold (Agent 8).

        Fires `ContextCompactor` and replaces the raw history with the structured
        CompactedContext, then trims the raw turns. Per build doc 8.3 this keeps
        the session document small and gives downstream agents only the sections
        they need. The compaction result is mapped onto the session's
        CompactedContext model.
        """
        if not session.needs_compaction:
            return

        result = await self._context_compactor.compact(
            project_name=session.project_name,
            job_name=session.job_name,
            vendor_list=", ".join(session.vendor_names),
            message_count=len(session.conversation_history),
            full_conversation_history=self._history_text(session),
            session_id=session.id,
            project_id=session.project_id,
        )

        state = result.get("session_state") or {}
        try:
            decision_status = DecisionStatus(str(state.get("decision_status")))
        except (ValueError, TypeError):
            decision_status = DecisionStatus.UNDECIDED

        session.compacted_context = CompactedContext(
            decision_status=decision_status,
            leading_vendor=state.get("leading_vendor"),
            reasoning=state.get("reasoning"),
            conclusions=list(result.get("conclusions") or []),
            table_edits=list(result.get("table_edits") or []),
            user_preferences=[str(p) for p in (result.get("user_preferences") or [])],
            open_threads=[str(t) for t in (result.get("open_threads") or [])],
            data_corrections=[
                str(d) for d in (result.get("data_corrections") or [])
            ],
            compressed_from_message_count=int(
                result.get("compressed_from_message_count", 0) or 0
            ),
        )
        # Trim raw history now that its content is preserved in the summary.
        session.conversation_history = []

    # -------------------------------------------------------------- summarize

    async def summarize(self, project_id: str, session_id: str) -> dict:
        """
        Produce a shareable summary of a session (Agent 11) for the summary route.

        Distinct from the in-chat summary branch: this loads the session fresh and
        returns the parsed summary dict directly (the router serializes it).
        """
        session = await self._load_session(project_id, session_id)
        return await self._summarize_session(session)

    # ----------------------------------------------------------- load helpers

    async def _load_session(
        self, project_id: str, session_id: str
    ) -> ComparisonSession:
        """Point-read a session, wrapping store errors and 404 (Rule 7)."""
        try:
            session = await self._session_store.get(session_id, project_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="COMPARISON_LOAD_SESSION",
                message="Failed to load comparison session",
                context={"project_id": project_id, "session_id": session_id},
                cause=exc,
            )
        if session is None:
            raise AppError(
                code="COMPARISON_SESSION_MISSING",
                message="No comparison session found",
                context={"project_id": project_id, "session_id": session_id},
            )
        return session

    async def _load_job(self, project_id: str, job_id: str) -> JobSummary:
        """Point-read a job, wrapping store errors and 404."""
        try:
            job = await self._job_store.get(job_id, project_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="COMPARISON_LOAD_JOB",
                message="Failed to load job for comparison",
                context={"project_id": project_id, "job_id": job_id},
                cause=exc,
            )
        if job is None:
            raise AppError(
                code="COMPARISON_JOB_MISSING",
                message="No job found to compare",
                context={"project_id": project_id, "job_id": job_id},
            )
        return job

    async def _load_project(self, project_id: str):
        """Point-read a project, wrapping store errors and 404."""
        try:
            project = await self._project_store.get(project_id)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="COMPARISON_LOAD_PROJECT",
                message="Failed to load project for comparison",
                context={"project_id": project_id},
                cause=exc,
            )
        if project is None:
            raise AppError(
                code="COMPARISON_PROJECT_MISSING",
                message="No project found to compare",
                context={"project_id": project_id},
            )
        return project

    async def _load_bids_for_job(self, job: JobSummary) -> list[IngestedBid]:
        """Load every bid attached to the job, in the job's recorded order."""
        return await self._load_bids(job.bid_ids, None, job_id=job.id)

    async def _load_bids(
        self,
        bid_ids: list[str],
        session: ComparisonSession | None,
        job_id: str | None = None,
    ) -> list[IngestedBid]:
        """
        Point-read each bid id, failing loudly on a missing bid (Rule 7).

        A missing bid makes the comparison meaningless, so we raise rather than
        silently compare a subset (mirrors the pipeline's contract).
        """
        context = {"job_id": job_id} if job_id else {"session_id": session.id if session else None}
        bids: list[IngestedBid] = []
        for bid_id in bid_ids:
            try:
                bid = await self._bid_store.get(bid_id)
            except AppError:
                raise
            except Exception as exc:
                raise AppError(
                    code="COMPARISON_LOAD_BID",
                    message="Failed to load a bid for comparison",
                    context={**context, "bid_id": bid_id},
                    cause=exc,
                )
            if bid is None:
                raise AppError(
                    code="COMPARISON_BID_MISSING",
                    message="A bid referenced by the comparison no longer exists",
                    context={**context, "bid_id": bid_id},
                )
            bids.append(bid)
        return bids

    async def _save(self, session: ComparisonSession) -> None:
        """Persist the session, wrapping store errors (Rule 7)."""
        try:
            await self._session_store.upsert(session)
        except Exception as exc:
            raise AppError(
                code="COMPARISON_SAVE_SESSION",
                message="Failed to save comparison session",
                context={"project_id": session.project_id, "session_id": session.id},
                cause=exc,
            )

    @staticmethod
    async def _safe(awaitable, code: str):
        """Await a store call, wrapping failures with `code` (Rule 5/7)."""
        try:
            return await awaitable
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code=code,
                message="Comparison data query store call failed",
                cause=exc,
            )

    # --------------------------------------------------------- view/encoding

    @staticmethod
    def _render_bids_block(bids: list[IngestedBid]) -> str:
        """
        Build the repeated per-bid block for Agents 5/7.

        Reuses UnitNormalizer.render_bid_block (the single source of truth for the
        block layout — Rule 5), mirroring the pipeline. Parsed table cells are not
        retained on the bid document, so parsed_tables is empty; document_text
        carries the line items.
        """
        blocks = [
            UnitNormalizer.render_bid_block(
                vendor_name=bid.vendor_name or bid.sender_email,
                bid_id=bid.id,
                filename=bid.attachment_filename,
                total_price=(
                    f"{bid.total_price}"
                    if bid.total_price is not None
                    else "Not specified"
                ),
                document_text=bid.document_text,
                parsed_tables="",
            )
            for bid in bids
        ]
        return "\n\n".join(blocks)

    @staticmethod
    def _cost_section(session: ComparisonSession) -> dict:
        """Return the session table's cost section, or a no-table notice."""
        if session.table is None:
            return {"note": "The comparison table is not ready yet."}
        return {
            "costRows": [r.model_dump(by_alias=True) for r in session.table.cost_rows],
            "totals": [t.model_dump(by_alias=True) for t in session.table.totals],
            "costAnalysis": session.table.cost_analysis.model_dump(by_alias=True),
        }

    @staticmethod
    def _feature_section(session: ComparisonSession) -> dict:
        """Return the session table's feature section, or a no-table notice."""
        if session.table is None:
            return {"note": "The comparison table is not ready yet."}
        return {
            "featureRows": [
                r.model_dump(by_alias=True) for r in session.table.feature_rows
            ],
            "redFlags": [f.model_dump(by_alias=True) for f in session.table.red_flags],
            "featureSummary": session.table.feature_summary,
        }

    @staticmethod
    def _table_json(session: ComparisonSession) -> str:
        """Serialize the full comparison table (camelCase) for an agent input."""
        if session.table is None:
            return "{}"
        return session.table.model_dump_json(by_alias=True)

    @staticmethod
    def _history_text(session: ComparisonSession) -> str:
        """
        Render the conversation for an agent input.

        Prefers the compacted context (once history has been summarized) so
        downstream agents read the dense summary; otherwise renders the raw turns.
        """
        if session.compacted_context is not None:
            return session.compacted_context.model_dump_json(by_alias=True)
        return "\n".join(
            f"{m.role.value}: {m.content}" for m in session.conversation_history
        )

    @staticmethod
    def _encode(value: object) -> str:
        """JSON-encode a structured agent result as message content."""
        return json.dumps(value)
