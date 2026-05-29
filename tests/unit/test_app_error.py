"""Tests for the AppError chain architecture (Rule 8)."""

from src.core.errors.app_error import AppError


def test_error_id_format() -> None:
    err = AppError(code="X", message="boom")
    assert err.error_id.startswith("ERR-")
    assert len(err.error_id) == 12  # "ERR-" + 8 hex chars


def test_user_message_hides_internals() -> None:
    err = AppError(code="SECRET_CODE", message="db password was wrong",
                   context={"password": "hunter2"})
    payload = err.user_message
    assert payload["message"] == "Something went wrong"
    assert payload["error_id"] == err.error_id
    # The user payload must not leak the code, message, or context.
    assert "SECRET_CODE" not in str(payload)
    assert "hunter2" not in str(payload)


def test_chain_walks_appdomain_then_external() -> None:
    root = ValueError("network down")
    mid = AppError(code="STORE", message="store failed", context={"id": "1"}, cause=root)
    top = AppError(code="SERVICE", message="service failed", cause=mid)

    chain = top.get_full_chain()
    assert [c["code"] for c in chain] == ["SERVICE", "STORE", "EXTERNAL"]
    assert chain[1]["context"] == {"id": "1"}
    assert chain[2]["type"] == "ValueError"
    assert "network down" in chain[2]["message"]
