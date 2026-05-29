"""Tests for the subprocess Python sandbox (security-critical, Rule C5)."""

import pytest

from src.infrastructure.sandbox.python_sandbox import SubprocessPythonSandbox


@pytest.fixture
def sandbox() -> SubprocessPythonSandbox:
    return SubprocessPythonSandbox()


async def test_runs_code_and_pipes_stdin(sandbox: SubprocessPythonSandbox) -> None:
    code = "import sys, json; d=json.load(sys.stdin); print(json.dumps({'sum': d['a']+d['b']}))"
    result = await sandbox.run(code, '{"a": 2, "b": 40}', 10)
    assert result.success is True
    assert result.timed_out is False
    assert '"sum": 42' in result.stdout


async def test_nonzero_exit_is_failure(sandbox: SubprocessPythonSandbox) -> None:
    result = await sandbox.run("raise ValueError('nope')", "", 10)
    assert result.success is False
    assert "ValueError" in result.stderr


async def test_timeout_is_killed(sandbox: SubprocessPythonSandbox) -> None:
    result = await sandbox.run("import time; time.sleep(5)", "", 1)
    assert result.success is False
    assert result.timed_out is True
