"""
SubprocessPythonSandbox — IPythonSandbox via an isolated child interpreter.

Agents 6 (CostComparator) and 9 (DataQueryAgent) emit Python source that BidPilot
must execute to build comparison tables and answer cross-project questions. That
code is LLM-generated and therefore untrusted: it must run with a hard timeout
and a stripped environment so a runaway or malicious snippet cannot hang the
worker or read host secrets out of environment variables (build doc C5).

Hardening summary (each step commented inline below):
- `sys.executable -I -c <code>` runs the SAME interpreter in *isolated* mode, so
  the snippet cannot import from the current working directory, honor PYTHON*
  env vars, or pick up user site-packages.
- `env={}` strips ALL inherited environment, so credentials and connection
  strings present in the worker's environment are invisible to the snippet.
- `asyncio.wait_for(...)` enforces the wall-clock timeout; on expiry the child is
  killed so it cannot keep consuming CPU after we stop waiting.
- input arrives only via stdin (piped), output only via captured stdout/stderr —
  the snippet has no other channel by contract.
"""

import asyncio
import logging
import os
import sys

from src.core.errors.app_error import AppError
from src.core.interfaces.python_sandbox import SandboxResult

logger = logging.getLogger(__name__)

# Minimal env for the child. We pass ONLY PATH so the interpreter can still find
# the system shared libraries it needs to start; everything else (secrets,
# connection strings, PYTHON* overrides) is deliberately withheld. An empty
# string default keeps the key present-but-harmless if PATH is somehow unset.
_PATH_ENV_KEY = "PATH"


class SubprocessPythonSandbox:
    """
    IPythonSandbox implementation that runs code in a short-lived child process.

    Why a subprocess rather than `exec()` in-process: `exec` shares the worker's
    memory, threads, and imported modules, so a bad snippet could corrupt state
    or read live objects holding secrets. A separate process with a stripped
    environment and a kill-on-timeout contract gives a clean isolation boundary
    we can actually enforce.

    This class has no injected dependencies because its only collaborators are
    the OS process API and the current interpreter path (`sys.executable`), both
    of which are process-global facts rather than swappable services. Unexpected
    orchestration failures (spawn errors, kill errors) are wrapped as AppError
    "SANDBOX_RUN" (Rules 7/8); a non-zero exit or a timeout from the *snippet*
    itself is a normal result, not an error, and is returned as such.
    """

    async def run(
        self, code: str, stdin_data: str, timeout_seconds: int = 30
    ) -> SandboxResult:
        """
        Execute `code` in an isolated child interpreter, feeding `stdin_data` to
        its stdin and capturing stdout/stderr.

        Result mapping:
        - timeout      → SandboxResult(success=False, timed_out=True) after the
                         child is killed and reaped.
        - non-zero RC  → SandboxResult(success=False, stderr=...) so the caller
                         can show the agent's traceback for debugging.
        - zero RC      → SandboxResult(success=True, stdout=...) — stdout carries
                         the JSON the agent is contracted to emit.

        Only failures of the sandbox *machinery* (failing to spawn or kill the
        process) raise; failures of the executed code are data in the result.
        """
        try:
            return await self._run_guarded(code, stdin_data, timeout_seconds)
        except AppError:
            # Already a typed, contextualized error from the inner helper — let it
            # propagate unchanged so we do not double-wrap the same failure.
            raise
        except Exception as exc:
            raise AppError(
                code="SANDBOX_RUN",
                message="Unexpected failure orchestrating the sandbox subprocess",
                context={"timeout_seconds": timeout_seconds},
                cause=exc,
            )

    async def _run_guarded(
        self, code: str, stdin_data: str, timeout_seconds: int
    ) -> SandboxResult:
        """
        Spawn, communicate-with-timeout, and map the outcome.

        Split out from `run` so the broad except in `run` only ever sees genuine
        orchestration faults, while this method keeps the spawn/communicate/kill
        sequence readable.
        """
        # `-I` = isolated mode: ignore PYTHON* env vars, the user site directory,
        # and the script directory on sys.path. `-c code` runs the source string.
        # We reuse `sys.executable` so the child is the exact interpreter the
        # worker is running, guaranteeing version/stdlib parity.
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-c",
                code,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Strip the environment: pass only PATH so the snippet cannot read
                # secrets/connection strings inherited from the worker process.
                env={_PATH_ENV_KEY: os.environ.get(_PATH_ENV_KEY, "")},
            )
        except Exception as exc:
            raise AppError(
                code="SANDBOX_RUN",
                message="Failed to spawn the sandbox subprocess",
                context={"timeout_seconds": timeout_seconds},
                cause=exc,
            )

        # Encode stdin once; the program reads it as bytes via its own stdin.
        stdin_bytes = (stdin_data or "").encode("utf-8")

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=stdin_bytes),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            # The snippet exceeded its wall-clock budget. Kill and reap it so it
            # cannot keep burning CPU after we have given up waiting; a leaked
            # child would otherwise outlive the request.
            await self._terminate(process)
            return SandboxResult(
                success=False,
                stdout="",
                stderr="",
                timed_out=True,
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return_code = process.returncode

        if return_code != 0:
            # A non-zero exit means the agent's code raised. This is expected
            # often enough (bad generated code) that it is a normal result, not an
            # AppError — the caller may retry the agent or surface the stderr.
            return SandboxResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
            )

        return SandboxResult(
            success=True,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
        )

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        """
        Force-kill a running child and wait for it to fully exit.

        Uses `kill()` (SIGKILL) rather than `terminate()` because the snippet is
        untrusted and may ignore catchable signals; SIGKILL cannot be trapped.
        The follow-up `wait()` reaps the process so it does not linger as a
        zombie. Wrapped because a failure to kill leaves a runaway process and is
        a genuine machinery fault the caller must learn about.
        """
        try:
            if process.returncode is None:
                process.kill()
            await process.wait()
        except ProcessLookupError:
            # The child already exited between our check and the kill — nothing
            # left to clean up, so this race is benign.
            return
        except Exception as exc:
            raise AppError(
                code="SANDBOX_RUN",
                message="Failed to kill a timed-out sandbox subprocess",
                context={},
                cause=exc,
            )
