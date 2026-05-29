"""Tests for ResponseParser — the single JSON-extraction reuse point (Rule 5)."""

import pytest

from src.agents.response_parser import ResponseParser
from src.core.errors.app_error import AppError


@pytest.fixture
def parser() -> ResponseParser:
    return ResponseParser()


def test_parses_bare_json(parser: ResponseParser) -> None:
    assert parser.parse_json('{"a": 1, "b": true}') == {"a": 1, "b": True}


def test_strips_code_fences(parser: ResponseParser) -> None:
    text = 'Sure:\n```json\n{"is_bid": true, "confidence": 0.9}\n```\nthanks'
    assert parser.parse_json(text) == {"is_bid": True, "confidence": 0.9}


def test_extracts_object_amid_prose(parser: ResponseParser) -> None:
    text = 'The answer is {"x": [1, 2, 3]} as shown.'
    assert parser.parse_json(text) == {"x": [1, 2, 3]}


def test_raises_appdomain_on_garbage(parser: ResponseParser) -> None:
    with pytest.raises(AppError) as exc:
        parser.parse_json("no json here")
    assert exc.value.code == "RESPONSE_PARSE"
