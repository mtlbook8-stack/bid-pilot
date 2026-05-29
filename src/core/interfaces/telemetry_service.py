"""ITelemetryService — contract for OpenTelemetry + cost tracking."""

from typing import Protocol


class ITelemetryService(Protocol):
    """
    Instruments every LLM call, pipeline run, and session. BaseAgent calls
    `track_llm_call` automatically so no agent subclass thinks about telemetry
    (build doc section 5).
    """

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
    ) -> None: ...

    def track_pipeline_run(
        self,
        bid_id: str,
        status: str,
        duration_ms: float,
        agents_called: list[str],
        total_tokens: int,
    ) -> None: ...

    def track_comparison_session(
        self,
        session_id: str,
        messages_count: int,
        agents_invoked: list[str],
        total_tokens: int,
    ) -> None: ...

    def track_event(self, name: str, properties: dict) -> None: ...
