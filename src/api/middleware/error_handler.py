"""
Global exception handler — the single Rule 8 logging site for the API.

WHY this exists: the build's error philosophy is "throw up, log at top". Every
layer wraps and re-raises AppError without logging; this handler is the ONE
place that calls `logger.error()`. It flattens an AppError's cause chain into a
single structured log entry (so one failure equals exactly one log line keyed by
a unique error id) and returns only the user-safe payload — never a stack trace,
resource name, or technical detail (Rule 8).

Anything that is NOT an AppError is wrapped into one here so it gets the same
treatment: a generated error id, a single log line, and a friendly response.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)


class ErrorHandler:
    """
    Owns the FastAPI exception handlers for AppError and bare Exception.

    A class (Rule 1) rather than loose functions so the logging policy lives in
    one cohesive unit. Handlers are registered onto the app by
    `register_error_handlers`.
    """

    @staticmethod
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """
        Log the full cause chain once and return the user-safe payload.

        The log line carries the error id (so support can grep by what the user
        reports), the flattened chain (every wrap's code/message/context plus the
        terminating EXTERNAL frame), and the request method+path for locality.
        The HTTP status is 500: an AppError reaching here is an unhandled failure
        of an operation we attempted, not a client-input problem (those are
        raised as HTTPException, which FastAPI handles before this).
        """
        logger.error(
            "AppError %s on %s %s: %s",
            exc.error_id,
            request.method,
            request.url.path,
            exc.get_full_chain(),
        )
        return JSONResponse(status_code=500, content=exc.user_message)

    @staticmethod
    async def handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        """
        Wrap any non-AppError into an AppError so it logs and responds uniformly.

        A bare exception escaping to here is a bug or an un-wrapped external
        failure; wrapping it gives it an error id and the same single-log-line
        treatment, and guarantees the user still only sees a friendly message.
        """
        wrapped = AppError(
            code="UNHANDLED",
            message="An unhandled exception escaped to the top-level handler",
            context={"method": request.method, "path": request.url.path},
            cause=exc,
        )
        logger.error(
            "Unhandled %s on %s %s: %s",
            wrapped.error_id,
            request.method,
            request.url.path,
            wrapped.get_full_chain(),
        )
        return JSONResponse(status_code=500, content=wrapped.user_message)


def register_error_handlers(app: FastAPI) -> None:
    """
    Attach the AppError and catch-all Exception handlers to `app`.

    Registered in `main.py` (the composition root). The AppError handler is
    specific; the Exception handler is the safety net for anything un-wrapped.
    """
    app.add_exception_handler(AppError, ErrorHandler.handle_app_error)
    app.add_exception_handler(Exception, ErrorHandler.handle_unhandled)
