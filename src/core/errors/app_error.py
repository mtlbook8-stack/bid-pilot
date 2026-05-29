"""
Custom error class implementing the Rule 8 error-chain architecture.

Every error in the system is an AppError or is wrapped by one. Each wrap adds a
unique code plus structured context, building a cause chain that the global
exception handler (the ONLY place that logs) can flatten into a single log
entry. The user only ever sees a friendly message plus a short error id they
can report.
"""

from uuid import uuid4


class AppError(Exception):
    """
    Application error with chaining, context, and user-safe messaging.

    Why it exists: the build's error philosophy is "throw up, log at top". A
    low-level call wraps the original exception with a descriptive code and the
    relevant identifiers (bid id, model, etc.); higher layers may wrap again.
    Nothing logs along the way. The middleware walks `get_full_chain()` once and
    emits exactly one log line, then returns `user_message` to the caller.
    """

    def __init__(
        self,
        code: str,
        message: str,
        context: dict | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.context = context or {}
        self.cause = cause
        # Short, human-quotable id. The same id appears in the log entry and in
        # the user-facing payload, so support can grep logs by what the user reports.
        self.error_id = self._generate_error_id()
        super().__init__(message)

    @staticmethod
    def _generate_error_id() -> str:
        """Short unique id the user can report and the dev can search logs for."""
        return f"ERR-{uuid4().hex[:8].upper()}"

    def get_full_chain(self) -> list[dict]:
        """
        Walk the cause chain and collect all context for the log entry.

        AppError causes contribute their code/message/context; the first
        non-AppError cause is recorded as an EXTERNAL frame (its repr + type)
        and terminates the walk, since we cannot introspect arbitrary
        third-party exceptions further.
        """
        chain: list[dict] = [
            {"code": self.code, "message": self.message, "context": self.context}
        ]
        current = self.cause
        while current is not None:
            if isinstance(current, AppError):
                chain.append(
                    {
                        "code": current.code,
                        "message": current.message,
                        "context": current.context,
                    }
                )
                current = current.cause
            else:
                chain.append(
                    {
                        "code": "EXTERNAL",
                        "message": str(current),
                        "type": type(current).__name__,
                    }
                )
                break
        return chain

    @property
    def user_message(self) -> dict:
        """What the user sees — friendly message plus an error id to report."""
        return {"message": "Something went wrong", "error_id": self.error_id}

    def __str__(self) -> str:
        return f"[{self.code}] {self.message} ({self.error_id})"
