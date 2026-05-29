"""
OpenTelemetryService — cost-aware instrumentation for every LLM call.

Implements ITelemetryService (build doc section 5). Each LLM invocation, pipeline
run, and comparison session is emitted as an OpenTelemetry span carrying the
structured attributes from the section 5.2 table — most importantly the estimated
USD cost, computed from token counts and a pricing table so the user can see what
they are spending.

This service degrades gracefully: if no tracer is available it becomes a safe
no-op rather than crashing the request path. Telemetry is observability, not
business logic, so a telemetry failure must never break a bid or a chat.
"""

import json
import logging
from pathlib import Path

from opentelemetry import trace
from opentelemetry.trace import Tracer

from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)


class OpenTelemetryService:
    """
    ITelemetryService backed by OpenTelemetry spans.

    Why cost lives here: BaseAgent reports raw token counts after each call and
    this service turns them into dollars using the injected pricing table. That
    keeps pricing in one place (Rule 5) and lets the agents stay model-agnostic.

    The pricing table and tracer are injected (Rule 3). If a model is absent from
    the table we treat its cost as 0.0 and attach a `cost_estimated=False` flag
    rather than raising — a missing price must not break instrumentation, and the
    flag makes the gap visible in the telemetry backend.
    """

    def __init__(
        self,
        pricing: dict[str, dict[str, float]],
        tracer: Tracer | None = None,
    ) -> None:
        self._pricing = pricing
        # Fall back to the global tracer if none is injected; if even that is the
        # default no-op tracer, every emit becomes harmless.
        self._tracer = tracer or trace.get_tracer(__name__)

    @staticmethod
    def load_pricing(path: str) -> dict[str, dict[str, float]]:
        """
        Read the model pricing table from a JSON file (build doc section 5.3).

        Kept static and side-effect-free so it can run at composition time (in
        main.py) and be unit-tested directly. Wrapped so a missing/malformed
        file surfaces as a typed AppError instead of a bare IOError (Rule 7).
        """
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise AppError(
                code="TELEMETRY_PRICING_LOAD",
                message="Failed to load model pricing table",
                context={"path": path},
                cause=exc,
            )

    def compute_cost(
        self, model: str, tokens_in: int, tokens_out: int
    ) -> tuple[float, bool]:
        """
        Estimate USD cost for a call from token counts and the pricing table.

        Formula (section 5.3):
            (tokens_in / 1000 * input_rate) + (tokens_out / 1000 * output_rate)

        Returns (cost, priced) where `priced` is False when the model is missing
        from the table (cost defaults to 0.0). A real, pure method so it is
        unit-testable in isolation and reused by track_llm_call.
        """
        rates = self._pricing.get(model)
        if rates is None:
            # Unknown model: do not guess, do not crash. Cost 0.0 + a flag so the
            # gap is visible without polluting logs.
            return 0.0, False
        cost = (
            tokens_in / 1000 * rates["input_per_1k"]
            + tokens_out / 1000 * rates["output_per_1k"]
        )
        return round(cost, 6), True

    def _emit(self, name: str, attributes: dict) -> None:
        """
        Emit a single short-lived span carrying the given attributes.

        Why span-per-event: these are point-in-time metrics (a finished LLM call,
        a closed session) rather than nested operations, so a self-contained span
        with attributes is the simplest faithful representation.

        Telemetry must never break the caller, so any tracer/exporter failure is
        swallowed here (the one deliberate exception to Rule 7): an observability
        outage cannot be allowed to fail a user request. None-valued attributes
        are dropped because the OpenTelemetry attribute API rejects None.
        """
        try:
            clean = {k: v for k, v in attributes.items() if v is not None}
            with self._tracer.start_as_current_span(name) as span:
                span.set_attributes(clean)
        except Exception:
            # Intentionally non-fatal: a telemetry backend problem must not
            # surface to the user or abort the operation being measured.
            return

    def track_llm_call(
        self,
        agent_name: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        duration_ms: float,
        success: bool,
        bid_id: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """
        Record one LLM invocation with cost estimation (section 5.2 fields).

        Called automatically by BaseAgent after every Foundry call, on both the
        success and failure paths, so error rate and cost are tracked uniformly.
        """
        cost, priced = self.compute_cost(model, tokens_in, tokens_out)
        self._emit(
            "llm_call",
            {
                "agent_name": agent_name,
                "model_used": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "duration_ms": duration_ms,
                "cost_estimate_usd": cost,
                "cost_estimated": priced,
                "success": success,
                "error_code": error_code,
                "bid_id": bid_id,
                "session_id": session_id,
                "project_id": project_id,
                "user_id": user_id,
            },
        )

    def track_pipeline_run(
        self,
        bid_id: str,
        status: str,
        duration_ms: float,
        agents_called: list[str],
        total_tokens: int,
    ) -> None:
        """Record a complete 3-agent bid-processing pipeline run."""
        self._emit(
            "pipeline_run",
            {
                "bid_id": bid_id,
                "status": status,
                "duration_ms": duration_ms,
                # Span attributes must be primitives/sequences of primitives;
                # join the agent list into a stable comma-separated string.
                "agents_called": ",".join(agents_called),
                "total_tokens": total_tokens,
            },
        )

    def track_comparison_session(
        self,
        session_id: str,
        messages_count: int,
        agents_invoked: list[str],
        total_tokens: int,
    ) -> None:
        """Record comparison-session telemetry on close/compact."""
        self._emit(
            "comparison_session",
            {
                "session_id": session_id,
                "messages_count": messages_count,
                "agents_invoked": ",".join(agents_invoked),
                "total_tokens": total_tokens,
            },
        )

    def track_event(self, name: str, properties: dict) -> None:
        """Record an arbitrary named event with free-form properties."""
        self._emit(name, properties)
