"""
model_health_check.py — weekly timer that pings every model endpoint configured
in the prompts container (build doc section 13).

WHY this trigger exists: BidPilot's agent/model assignment is data-driven — each
active prompt document names the model its agent uses (``modelConfig.modelName``),
swappable with no code change (build doc 6.3). The risk is that a provider
deprecates or capacity-limits a model and the FIRST time anyone notices is a user
hitting a failed pipeline. This weekly probe sends a single minimal completion to
each distinct configured model and emits a ``ModelHealthCheck`` telemetry event
(healthy/failed) so deprecations surface in Application Insights BEFORE users do.
On any failure it ``log.critical``s (with the exception) so an alert can fire.

THIN trigger: collect distinct models from active prompts, probe each, record the
result. Per-model failures are isolated so one dead model does not stop the rest
of the sweep from being checked.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import azure.functions as func

if TYPE_CHECKING:
    from src.composition.container import AppContainer

logger = logging.getLogger(__name__)

ContainerGetter = Callable[[], Awaitable["AppContainer"]]

# A health probe only needs to confirm the endpoint responds, so we ask for the
# smallest possible completion (build doc section 13).
_HEALTH_CHECK_MAX_TOKENS = 5
_HEALTH_CHECK_SYSTEM = "Respond with OK"
_HEALTH_CHECK_USER = "Health check"


def register(app: func.FunctionApp, get_container: ContainerGetter) -> None:
    """
    Attach the weekly model-health-check timer to ``app``.

    Schedule ``0 0 9 * * 1`` (every Monday 09:00 UTC — build doc section 13).
    Defined inside ``register`` so it closes over the injected ``get_container``
    (Rule 3) while attaching to the shared ``app``.
    """

    @app.timer_trigger(
        arg_name="timer",
        schedule="0 0 9 * * 1",
        run_on_startup=False,
    )
    async def model_health_check(timer: func.TimerRequest) -> None:
        """
        Probe every distinct model named by an active prompt.

        Collects the distinct ``modelConfig.modelName`` values across all active
        prompts, sends a minimal completion to each, and tracks a
        ``ModelHealthCheck`` event with status healthy/failed. A failed probe is
        logged ``critical`` (with the exception) so it can raise an alert, then the
        sweep continues to the next model so one dead endpoint never masks others.
        """
        container = await get_container()
        prompts = await container.prompt_store.get_all_active()

        models = sorted({p.model_config_.model_name for p in prompts})
        for model in models:
            try:
                await container.foundry.get_completion(
                    model=model,
                    system=_HEALTH_CHECK_SYSTEM,
                    user=_HEALTH_CHECK_USER,
                    max_tokens=_HEALTH_CHECK_MAX_TOKENS,
                )
                container.telemetry.track_event(
                    "ModelHealthCheck", {"model": model, "status": "healthy"}
                )
            except Exception as exc:
                # Top-level handler for this model (Rule 8): record the failure as
                # telemetry AND log.critical so an Application Insights alert can
                # fire on the deprecation/outage before users are affected.
                container.telemetry.track_event(
                    "ModelHealthCheck",
                    {"model": model, "status": "failed", "error": str(exc)},
                )
                logger.critical(
                    "Model health check FAILED: %s", model, exc_info=exc
                )
