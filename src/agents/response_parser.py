"""
ResponseParser — the single JSON-extraction point for all LLM responses.

Every agent prompt ends with "Respond with ONLY valid JSON", but models in
practice sometimes wrap their answer in ```json fences or add a sentence of
prose before/after the object. This class centralizes the cleanup + parse so the
recovery logic lives in exactly one place (Rule 5) instead of being copy-pasted
into all 13 agents. A parse failure raises a typed AppError (Rules 7, 8) that
carries the offending text (truncated) so the single top-level log entry can
explain why an otherwise-successful call could not be decoded.
"""

import json
import logging

from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)

# How much of a bad response to keep in the error context. Enough to diagnose
# the malformation, capped so a multi-thousand-token answer cannot bloat logs.
_MAX_CONTEXT_CHARS = 500


class ResponseParser:
    """
    Extracts a JSON object from free-form LLM text.

    The strategy is deliberately forgiving: strip Markdown code fences, then take
    the substring from the first '{' to the matching last '}', then json.loads.
    This recovers the common "prose + JSON" and "fenced JSON" shapes without
    needing the model to be perfectly obedient.

    Stateless and dependency-free, so it is trivially injectable (Rule 3) and
    unit-testable. Methods are instance methods so BaseAgent holds one injected
    parser, but they keep no state between calls.
    """

    def parse_json(self, text: str) -> dict:
        """
        Parse the JSON object embedded in an LLM text response.

        Steps:
          1. Strip surrounding whitespace and any ```json / ``` code fences.
          2. Slice from the first '{' to the last '}' (inclusive) so leading or
             trailing prose is discarded.
          3. json.loads the slice.

        Raises AppError "RESPONSE_PARSE" with the offending text truncated to
        500 chars on any failure (no JSON object present, or invalid JSON). The
        original exception is chained as the cause so the top-level handler can
        show the underlying decode error.
        """
        candidate = self._strip_code_fences(text)

        # WHY first-'{'-to-last-'}': models occasionally emit a short sentence
        # ("Here is the result:") before the object, or a trailing note after it.
        # Bounding to the outermost braces tolerates both without a brittle regex.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise AppError(
                code="RESPONSE_PARSE",
                message="No JSON object found in LLM response",
                context={"text": self._truncate(text)},
            )

        json_slice = candidate[start : end + 1]
        try:
            parsed = json.loads(json_slice)
        except Exception as exc:
            raise AppError(
                code="RESPONSE_PARSE",
                message="LLM response was not valid JSON",
                context={"text": self._truncate(text)},
                cause=exc,
            )

        # The contract is a JSON object; a bare array/number/string indicates the
        # model ignored the schema, which downstream code cannot consume.
        if not isinstance(parsed, dict):
            raise AppError(
                code="RESPONSE_PARSE",
                message="LLM response JSON was not an object",
                context={"text": self._truncate(text)},
            )

        return parsed

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """
        Remove Markdown code fences that wrap a fenced JSON block.

        Handles ```json ... ``` and plain ``` ... ``` by dropping the opening
        fence line and the trailing fence. Leaves unfenced text untouched so the
        brace-slicing in parse_json still applies.
        """
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped

        # Drop the opening fence line (which may be ``` or ```json or ```JSON).
        newline = stripped.find("\n")
        if newline == -1:
            # A single-line fence with no body — nothing useful to extract.
            return stripped
        without_open = stripped[newline + 1 :]

        # Drop the trailing closing fence if present.
        close = without_open.rfind("```")
        if close != -1:
            without_open = without_open[:close]
        return without_open.strip()

    @staticmethod
    def _truncate(text: str) -> str:
        """Cap response text for error context so logs stay bounded."""
        if len(text) <= _MAX_CONTEXT_CHARS:
            return text
        return text[:_MAX_CONTEXT_CHARS] + "...[truncated]"
