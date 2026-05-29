"""IPythonSandbox — contract for executing agent-generated Python safely."""

from typing import Protocol

from pydantic import BaseModel


class SandboxResult(BaseModel):
    """Outcome of a sandboxed run. `stdout` carries the JSON the agent emits."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class IPythonSandbox(Protocol):
    """
    Runs untrusted, LLM-generated code in a subprocess with a hard timeout and a
    stripped environment (build doc C5). `stdin_data` is piped to the program.
    """

    async def run(self, code: str, stdin_data: str, timeout_seconds: int = 30) -> SandboxResult: ...
