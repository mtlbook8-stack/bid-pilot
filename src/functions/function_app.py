"""
function_app.py — the Azure Functions v2 host entry point for BidPilot's
background workers (build doc Phase 8, section 3).

WHY this file exists: the v2 Python programming model attaches every trigger to
a single module-level ``func.FunctionApp`` via decorators. BidPilot's triggers
are deliberately THIN (build doc 8.1/8.2): each one parses its trigger input,
resolves the already-wired ``AppContainer``, calls an orchestrator, and lets
errors propagate to the Functions runtime. All real logic lives in the
orchestrators and the composition container, which this host reuses (Rule 5: the
wiring is defined once in ``src/composition/container.py``).

REGISTRATION CHOICE (documented per task):
The idiomatic v2 pattern decorates functions directly on a shared ``app``. To
keep one cohesive unit per file (Rule 4) while still using that pattern, each
trigger module exposes a single ``register(app, container_getter)`` function that
attaches its trigger(s) to the shared ``app`` via decorators. This file owns the
``app`` instance and the lazily-started container accessor, then calls each
module's ``register`` once at import time. The Functions runtime imports this
module, which materialises every binding before the worker starts serving.

CONTAINER LIFECYCLE: the ``AppContainer`` opens network resources (Cosmos client,
HTTP client, Azure credential) in ``await startup()``. A worker process serves
many invocations, so the container is built ONCE per process and shared across
invocations. ``get_container()`` constructs-and-starts it on first use behind an
``asyncio.Lock`` so concurrent cold-start invocations cannot race into two
parallel startups. There is no per-invocation teardown — the resources live for
the lifetime of the worker, which is the correct scope for pooled clients.
"""

import asyncio
import logging
import os
import sys

# Ensure the directory containing this file (the deployment package root in
# Azure Functions) is on sys.path so `from src.* import ...` resolves whether
# the worker is started from this directory or elsewhere. Required on Flex
# Consumption where the Python indexer otherwise reports
# ModuleNotFoundError: No module named 'src'.
_PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
# Flex Consumption: the Python worker is launched from the runtime's
# "standby" mount (e.g. /tmp/functions/standby/wwwroot) but ``__file__`` may
# still report /home/site/wwwroot. Probe every plausible root for the actual
# ``src`` package and prepend the first match (and the standby root) to
# sys.path so ``from src.* import ...`` resolves during indexing.
_CANDIDATE_ROOTS = [
    _PKG_ROOT,
    os.getcwd(),
    "/home/site/wwwroot",
    "/tmp/functions/standby/wwwroot",
]
for _candidate in _CANDIDATE_ROOTS:
    if _candidate and _candidate not in sys.path:
        sys.path.insert(0, _candidate)
# Pick the first candidate that actually contains src/__init__.py and make
# sure it's at the very front of sys.path.
for _candidate in _CANDIDATE_ROOTS:
    if _candidate and os.path.isfile(os.path.join(_candidate, "src", "__init__.py")):
        try:
            sys.path.remove(_candidate)
        except ValueError:
            pass
        sys.path.insert(0, _candidate)
        break
def _safe_listdir(p):
    try:
        return sorted(os.listdir(p))[:60]
    except Exception as _e:
        return f"err:{_e!r}"

sys.stderr.write(
    f"[bidpilot_function_app] __file__={__file__!r} _PKG_ROOT={_PKG_ROOT!r} "
    f"cwd={os.getcwd()!r} "
    f"candidate_src_found="
    f"{[c for c in _CANDIDATE_ROOTS if c and os.path.isfile(os.path.join(c, 'src', '__init__.py'))]!r}\n"
)
sys.stderr.flush()

import azure.functions as func

from src.composition.container import AppContainer
from src.functions import (
    bid_processing_trigger,
    bid_retry_trigger,
    connectivity_check,
    email_polling_trigger,
    manual_poll_trigger,
    model_health_check,
    webhook_notification,
    webhook_renewal_trigger,
)

logger = logging.getLogger(__name__)

# The single FunctionApp every trigger attaches to (v2 programming model).
app = func.FunctionApp()


class _ContainerProvider:
    """
    Process-wide lazy accessor for the shared, started ``AppContainer``.

    A Functions worker handles many invocations, so the container (and its pooled
    Cosmos/HTTP/credential resources) must be built once and reused — building it
    per invocation would leak connections and pay cold-start cost every time. The
    first caller constructs and ``await startup()``s the container; an
    ``asyncio.Lock`` serialises that so two concurrent cold invocations cannot
    each start their own container (Rule 9: no race-condition shortcuts).
    """

    def __init__(self) -> None:
        # Cheap construction only — no event loop or network touched at import.
        self._container: AppContainer | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> AppContainer:
        """
        Return the shared started container, building it on first use.

        Double-checked under the lock: the fast path returns the already-started
        container without acquiring the lock, while the slow path holds the lock
        and re-checks so only the first concurrent caller pays for startup.
        """
        if self._container is not None:
            return self._container
        async with self._lock:
            # Re-check inside the lock: another coroutine may have started it
            # while we awaited the lock.
            if self._container is None:
                container = AppContainer()
                await container.startup()
                self._container = container
            return self._container


# Module-level provider shared by every trigger via the injected getter.
_provider = _ContainerProvider()


async def get_container() -> AppContainer:
    """
    Resolve the shared, lazily-started ``AppContainer`` for the current worker.

    Passed to each trigger module's ``register`` as the ``container_getter`` so
    triggers depend on this callable rather than on how the container is built
    (Rule 3). Awaiting it the first time performs startup; later awaits are O(1).
    """
    return await _provider.get()


# Attach every trigger to the shared app. Each module owns its own binding shape
# and cohesive logic (Rule 4); this host only composes them.
bid_processing_trigger.register(app, get_container)
bid_retry_trigger.register(app, get_container)
email_polling_trigger.register(app, get_container)
webhook_notification.register(app, get_container)
webhook_renewal_trigger.register(app, get_container)
manual_poll_trigger.register(app, get_container)
model_health_check.register(app, get_container)
connectivity_check.register(app, get_container)
