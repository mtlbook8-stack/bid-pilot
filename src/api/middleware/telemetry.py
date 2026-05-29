"""
Per-request OpenTelemetry middleware (build doc section 5).

WHY this exists: while BaseAgent instruments every LLM call, the API also wants a
span per HTTP request so latency, status, and route can be correlated with the
downstream agent spans in Application Insights. This middleware wraps each
request in a span carrying method, path, status, and duration.

It is strictly best-effort: telemetry must NEVER break a request (the same
principle the orchestrators apply when swallowing span failures). If the tracer
is unavailable or a span operation raises, the request proceeds untouched.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

try:
    # Importing the OTel API is cheap and side-effect-free. If the package is
    # somehow absent we degrade to a no-op tracer rather than failing import.
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except Exception:  # pragma: no cover - defensive import guard
    _tracer = None
    logger.warning("OpenTelemetry API unavailable; request tracing disabled")


class TelemetryMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that opens one span per request.

    One job (Rule 2): request-level tracing. It records method/path/status/
    duration as span attributes and always returns the downstream response. Any
    failure in the telemetry path is logged and swallowed so the request is never
    affected by observability.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Time the request and annotate a span around `call_next`.

        If tracing is disabled (no tracer) we simply forward. Otherwise we open a
        span named `HTTP <METHOD>`, set the standard HTTP attributes, and record
        the status + duration once the handler returns. A span error never
        propagates: the response is the contract, telemetry is advisory.
        """
        if _tracer is None:
            return await call_next(request)

        started = time.perf_counter()
        try:
            with _tracer.start_as_current_span(
                f"HTTP {request.method}"
            ) as span:
                try:
                    span.set_attribute("http.method", request.method)
                    span.set_attribute("http.route", request.url.path)
                except Exception:
                    # Setting attributes must not block the request.
                    logger.debug("Failed to set request span attributes")

                response = await call_next(request)

                try:
                    duration_ms = (time.perf_counter() - started) * 1000.0
                    span.set_attribute("http.status_code", response.status_code)
                    span.set_attribute("http.duration_ms", duration_ms)
                except Exception:
                    logger.debug("Failed to annotate request span result")

                return response
        except Exception:
            # The span machinery itself failed (not the handler — that would have
            # propagated from call_next). Fall back to an untraced pass-through so
            # the request still completes.
            logger.warning("Request tracing failed; proceeding untraced")
            return await call_next(request)
