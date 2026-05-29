"""
ComparisonPipeline — assembles a job's comparison table (build doc 8.3 start).

WHY this class exists: the comparison is the core product. When a user clicks
"Compare" on a job, three agents must run in sequence over the same set of bids
— UnitNormalizer (Agent 5) reconciles every line item to common units,
CostComparator (Agent 6) turns that into a deterministic cost table, and
FeatureAnalyst (Agent 7) extracts the non-cost differentiators — and their
outputs must be assembled into a single ComparisonTable persisted on the
session. This pipeline drives that "start" phase. Live chat (Agent 4 routing)
is a separate concern handled elsewhere; this class only builds the initial
table.

It is phase-checkpointed like the bid pipeline: it writes NORMALIZING ->
COMPARING -> READY onto the session as it advances, and FAILED on any error, so
the session document reflects where the build got to and the UI can show
progress. Pure orchestration (Rule 2); all collaborators injected (Rule 3);
external/agent calls wrapped and re-raised as AppError (Rules 7, 8). The
dict->model assembly is isolated in a single private helper (Rule 5).
"""

import json
import logging
import time

from src.agents.comparison.cost_comparator import CostComparator
from src.agents.comparison.feature_analyst import FeatureAnalyst
from src.agents.comparison.unit_normalizer import UnitNormalizer
from src.core.enums import ComparisonPhase, Sentiment
from src.core.errors.app_error import AppError
from src.core.interfaces.bid_store import IBidStore
from src.core.interfaces.session_store import IComparisonSessionStore
from src.core.interfaces.telemetry_service import ITelemetryService
from src.core.models.bid import IngestedBid
from src.core.models.comparison import (
    ComparisonSession,
    ComparisonTable,
    CostAnalysis,
    CostCell,
    CostOutlier,
    CostRow,
    FeatureCell,
    FeatureRow,
    RedFlag,
    VendorTotal,
)

logger = logging.getLogger(__name__)


class ComparisonPipeline:
    """
    Runs Agents 5/6/7 over a job's bids and assembles the ComparisonTable.

    Stateless: it holds only its injected collaborators; the ComparisonSession
    document carries all phase state. `start` is the single public method.
    """

    def __init__(
        self,
        unit_normalizer: UnitNormalizer,
        cost_comparator: CostComparator,
        feature_analyst: FeatureAnalyst,
        bid_store: IBidStore,
        session_store: IComparisonSessionStore,
        telemetry: ITelemetryService,
    ) -> None:
        # Pure DI (Rule 3): agents and stores are interfaces injected by the
        # composition root; nothing is constructed here.
        self._unit_normalizer = unit_normalizer
        self._cost_comparator = cost_comparator
        self._feature_analyst = feature_analyst
        self._bid_store = bid_store
        self._session_store = session_store
        self._telemetry = telemetry

    async def start(self, *, session: ComparisonSession) -> ComparisonSession:
        """
        Build the comparison table for `session` from its bids.

        Steps, each fronted by a phase checkpoint saved to the session:
          1. Load every bid in session.bid_ids.
          2. NORMALIZING: render the shared per-bid block for each bid and run
             UnitNormalizer.
          3. COMPARING: build the columns + normalizer-output JSON, run
             CostComparator, then run FeatureAnalyst over the same bid blocks.
          4. Assemble a ComparisonTable from the two dicts and save it with phase
             READY.

        On ANY failure the session phase is set to FAILED and saved before the
        wrapped AppError "COMPARISON_PIPELINE" is re-raised (Rules 7, 8), so the
        UI sees the failure and the single top-level handler logs it once.
        """
        started = time.perf_counter()
        agents_invoked: list[str] = []
        try:
            bids = await self._load_bids(session)

            # The per-bid block is identical for Agents 5 and 7, so it is built
            # once and reused for both (Rule 5). Bids store document_text and a
            # table_count only — the parsed table CELLS are not retained on the
            # bid document — so parsed_tables is passed empty; the full document
            # text still carries the pricing the agents reason over.
            bids_block = self._render_bids_block(bids)

            session.phase = ComparisonPhase.NORMALIZING
            await self._save(session, "COMPARISON_SAVE_NORMALIZING")

            agents_invoked.append("UnitNormalizer")
            normalizer_output = await self._normalize(session, bids_block)

            session.phase = ComparisonPhase.COMPARING
            await self._save(session, "COMPARISON_SAVE_COMPARING")

            columns_json = self._build_columns_json(bids)
            normalizer_output_json = json.dumps(normalizer_output)

            agents_invoked.append("CostComparator")
            cost = await self._compare_cost(
                session, columns_json, normalizer_output_json
            )

            agents_invoked.append("FeatureAnalyst")
            feature = await self._analyze_features(session, bids_block)

            session.table = self._assemble_table(cost, feature)
            session.phase = ComparisonPhase.READY
            await self._save(session, "COMPARISON_SAVE_READY")

            self._track(session, started, agents_invoked)
            return session

        except Exception as exc:
            # Mark FAILED so the UI reflects the broken build, then re-raise. We
            # best-effort persist the failed phase; if even that save fails we
            # still surface the original error (it is the real cause).
            session.phase = ComparisonPhase.FAILED
            try:
                await self._session_store.upsert(session)
            except Exception:
                logger.warning(
                    "Failed to persist FAILED phase for session %s", session.id
                )
            if isinstance(exc, AppError):
                raise
            raise AppError(
                code="COMPARISON_PIPELINE",
                message="Comparison pipeline failed",
                context={"session_id": session.id, "project_id": session.project_id},
                cause=exc,
            )

    async def _load_bids(self, session: ComparisonSession) -> list[IngestedBid]:
        """
        Point-read every bid in the session, wrapping store errors.

        A missing bid is a hard error: the comparison is meaningless if a vendor
        the session was opened over has vanished, so we fail loudly rather than
        silently compare a subset (Rule 7).
        """
        bids: list[IngestedBid] = []
        for bid_id in session.bid_ids:
            try:
                bid = await self._bid_store.get(bid_id)
            except Exception as exc:
                raise AppError(
                    code="COMPARISON_LOAD_BID",
                    message="Failed to load a bid for comparison",
                    context={"session_id": session.id, "bid_id": bid_id},
                    cause=exc,
                )
            if bid is None:
                raise AppError(
                    code="COMPARISON_BID_MISSING",
                    message="A bid referenced by the session no longer exists",
                    context={"session_id": session.id, "bid_id": bid_id},
                )
            bids.append(bid)
        return bids

    def _render_bids_block(self, bids: list[IngestedBid]) -> str:
        """
        Build the repeated per-bid section shared by Agents 5 and 7.

        Uses UnitNormalizer.render_bid_block (the single source of truth for the
        block layout — Rule 5) and joins per-bid blocks with blank lines. Vendor
        name falls back to the sender email when Agent 3 left it unset; total
        price renders as "Not specified" when None (it is not part of Agent 3's
        output and may legitimately be absent).
        """
        blocks = [
            UnitNormalizer.render_bid_block(
                vendor_name=bid.vendor_name or bid.sender_email,
                bid_id=bid.id,
                filename=bid.attachment_filename,
                total_price=(
                    f"{bid.total_price}" if bid.total_price is not None else "Not specified"
                ),
                document_text=bid.document_text,
                # Parsed table cells are not retained on the bid document; the
                # full document text carries the line items the agents read.
                parsed_tables="",
            )
            for bid in bids
        ]
        return "\n\n".join(blocks)

    async def _normalize(self, session: ComparisonSession, bids_block: str) -> dict:
        try:
            return await self._unit_normalizer.normalize(
                project_name=session.project_name,
                job_name=session.job_name,
                trade_category=session.trade_category,
                bids_block=bids_block,
                session_id=session.id,
                project_id=session.project_id,
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="COMPARISON_NORMALIZE",
                message="UnitNormalizer step failed",
                context={"session_id": session.id, "project_id": session.project_id},
                cause=exc,
            )

    async def _compare_cost(
        self,
        session: ComparisonSession,
        columns_json: str,
        normalizer_output_json: str,
    ) -> dict:
        try:
            return await self._cost_comparator.compare(
                columns_json=columns_json,
                normalizer_output_json=normalizer_output_json,
                session_id=session.id,
                project_id=session.project_id,
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="COMPARISON_COST",
                message="CostComparator step failed",
                context={"session_id": session.id, "project_id": session.project_id},
                cause=exc,
            )

    async def _analyze_features(
        self, session: ComparisonSession, bids_block: str
    ) -> dict:
        try:
            return await self._feature_analyst.analyze(
                project_name=session.project_name,
                job_name=session.job_name,
                trade_category=session.trade_category,
                bids_block=bids_block,
                session_id=session.id,
                project_id=session.project_id,
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="COMPARISON_FEATURE",
                message="FeatureAnalyst step failed",
                context={"session_id": session.id, "project_id": session.project_id},
                cause=exc,
            )

    @staticmethod
    def _build_columns_json(bids: list[IngestedBid]) -> str:
        """One column per bid (bid_id + vendor_name) for the CostComparator input."""
        columns = [
            {"bid_id": bid.id, "vendor_name": bid.vendor_name or bid.sender_email}
            for bid in bids
        ]
        return json.dumps(columns)

    def _assemble_table(self, cost: dict, feature: dict) -> ComparisonTable:
        """
        Map the CostComparator + FeatureAnalyst dicts into a ComparisonTable.

        WHY a dedicated helper (Rule 5): both the start flow and any future
        re-build path need the identical dict->model translation, and it is the
        one place the upstream agent JSON shapes are coupled to the persisted
        models. Every field is read defensively with `.get` and sane defaults so a
        partial or slightly-off agent payload yields a usable (if sparser) table
        rather than a crash. Any structural surprise that still raises is wrapped
        as AppError so the failure is attributable (Rules 7, 8).
        """
        try:
            cost_rows = [
                CostRow(
                    row_id=str(row.get("row_id", "")),
                    label=str(row.get("label", "")),
                    normalized_unit=str(row.get("normalized_unit", "")),
                    cells=[
                        CostCell(
                            bid_id=str(cell.get("bid_id", "")),
                            vendor_name=str(cell.get("vendor_name", "")),
                            value=self._opt_float(cell.get("value")),
                            original_text=str(cell.get("original_text", "")),
                            is_lowest=bool(cell.get("is_lowest", False)),
                            flags=self._str_list(cell.get("flags")),
                        )
                        for cell in (row.get("cells") or [])
                    ],
                )
                for row in (cost.get("cost_rows") or [])
            ]

            totals = [
                VendorTotal(
                    bid_id=str(total.get("bid_id", "")),
                    vendor_name=str(total.get("vendor_name", "")),
                    total_price=self._req_float(total.get("total_price")),
                    items_included=int(total.get("items_included", 0) or 0),
                    items_missing=int(total.get("items_missing", 0) or 0),
                    scope_caveats=self._str_list(total.get("scope_caveats")),
                )
                for total in (cost.get("totals") or [])
            ]

            analysis_raw = cost.get("analysis") or {}
            cost_analysis = CostAnalysis(
                lowest_total_bid_id=self._opt_str(analysis_raw.get("lowest_total_bid_id")),
                highest_total_bid_id=self._opt_str(
                    analysis_raw.get("highest_total_bid_id")
                ),
                spread_percentage=self._req_float(analysis_raw.get("spread_percentage")),
                significant_outliers=[
                    CostOutlier(
                        row_label=str(outlier.get("row_label", "")),
                        bid_id=str(outlier.get("bid_id", "")),
                        deviation_percentage=self._req_float(
                            outlier.get("deviation_percentage")
                        ),
                        direction=str(outlier.get("direction", "above")),
                    )
                    for outlier in (analysis_raw.get("significant_outliers") or [])
                ],
            )

            feature_rows = [
                FeatureRow(
                    row_id=str(row.get("row_id", "")),
                    category=str(row.get("category", "")),
                    label=str(row.get("label", "")),
                    importance_rank=int(row.get("importance_rank", 99) or 99),
                    cells=[
                        FeatureCell(
                            bid_id=str(cell.get("bid_id", "")),
                            vendor_name=str(cell.get("vendor_name", "")),
                            value=str(cell.get("value", "")),
                            sentiment=self._map_sentiment(cell.get("sentiment")),
                            source_quote=str(cell.get("source_quote", "")),
                        )
                        for cell in (row.get("cells") or [])
                    ],
                )
                for row in (feature.get("feature_rows") or [])
            ]

            red_flags = [
                RedFlag(
                    bid_id=str(flag.get("bid_id", "")),
                    vendor_name=str(flag.get("vendor_name", "")),
                    issue=str(flag.get("issue", "")),
                    severity=str(flag.get("severity", "low")),
                )
                for flag in (feature.get("red_flags") or [])
            ]

            return ComparisonTable(
                cost_rows=cost_rows,
                totals=totals,
                cost_analysis=cost_analysis,
                feature_rows=feature_rows,
                red_flags=red_flags,
                feature_summary=str(feature.get("summary", "")),
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="COMPARISON_ASSEMBLE",
                message="Failed to assemble comparison table from agent output",
                cause=exc,
            )

    def _track(
        self, session: ComparisonSession, started: float, agents_invoked: list[str]
    ) -> None:
        """
        Emit comparison-session telemetry on a successful build.

        messages_count is 0 at start (no chat yet) and total_tokens is 0 here —
        per-call tokens are tracked inside BaseAgent (build doc section 5), so the
        pipeline reports the orchestration-level signal (which agents ran) without
        double-counting. Telemetry never breaks the build, so a failed span is
        swallowed: the table is already durably saved.
        """
        try:
            self._telemetry.track_comparison_session(
                session_id=session.id,
                messages_count=len(session.conversation_history),
                agents_invoked=agents_invoked,
                total_tokens=0,
            )
        except Exception:
            logger.warning("Failed to emit comparison telemetry for session %s", session.id)

    async def _save(self, session: ComparisonSession, code: str) -> None:
        """Persist the session's current phase, wrapping store errors (Rule 7)."""
        try:
            await self._session_store.upsert(session)
        except Exception as exc:
            raise AppError(
                code=code,
                message="Failed to save comparison session checkpoint",
                context={"session_id": session.id, "phase": session.phase.value},
                cause=exc,
            )

    # ----------------------------- helpers ---------------------------------

    @staticmethod
    def _map_sentiment(value: object) -> Sentiment:
        """Map an agent sentiment string to the enum, defaulting to NOT_SPECIFIED."""
        try:
            return Sentiment(str(value))
        except (ValueError, TypeError):
            return Sentiment.NOT_SPECIFIED

    @staticmethod
    def _opt_float(value: object) -> float | None:
        """Coerce to float or None (for nullable cell values)."""
        if value is None:
            return None
        try:
            return float(value)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _req_float(value: object) -> float:
        """Coerce to float, defaulting to 0.0 (for required numeric fields)."""
        try:
            return float(value)  # type: ignore[arg-type]
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
        """Coerce an agent list field into a list of strings."""
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]
