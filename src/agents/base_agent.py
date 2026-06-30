"""
BaseAgent — shared engine for all 13 agents.

This is the single class every concrete agent (QuoteValidator, UnitNormalizer,
...) inherits from. It owns four cross-cutting concerns so that no subclass ever
re-implements them (Rule 5):

  1. Prompt loading — fetch the active versioned PromptTemplate from Cosmos.
  2. Learned-rule injection — fill the {learned_rules} placeholder from the
     correction-derived rules, so the real-time learning loop works for every
     agent automatically.
  3. LLM invocation with fallback + telemetry — time the call, retry once on the
     fallback model if the primary is deprecated/at capacity, and emit a cost
     telemetry span on BOTH success and failure paths.
  4. Response parsing — delegate JSON extraction to the shared ResponseParser.

WHY fallback and telemetry live here (not in subclasses): they are policy that
must apply identically to every agent. Section 6.3 of the build doc defines the
fallback contract (retry once with modelConfig.fallbackModel on a model
deprecation/capacity error); section 5 mandates that every LLM call is
instrumented. Centralizing both guarantees no agent can forget to do either, and
keeps subclasses focused purely on building their template values and shaping
their output.
"""

import logging
import time
from collections import defaultdict

from src.agents.response_parser import ResponseParser
from src.core.errors.app_error import AppError
from src.core.interfaces.foundry_client import IFoundryClient, LlmResponse
from src.core.interfaces.prompt_store import IPromptStore
from src.core.interfaces.rule_store import IRuleStore
from src.core.interfaces.telemetry_service import ITelemetryService
from src.core.models.prompt import PromptTemplate

logger = logging.getLogger(__name__)

# Header the learned rules are listed under inside the {learned_rules} slot. The
# agent prompts reference a "LEARNED RULES" section, so the rendered block mirrors
# that wording for the model.
_LEARNED_RULES_HEADER = "LEARNED RULES:"

# Substrings that mark a model-level failure (deprecated / removed / out of
# capacity) for which retrying on the fallback model is worthwhile. Matched
# case-insensitively against the error chain text. Kept broad on purpose: the
# cost of a single extra fallback attempt is low, and a missed retry would surface
# to the user as a hard failure.
_FALLBACK_TRIGGER_TOKENS = (
    "404",
    "not found",
    "deprecat",
    "model_not_found",
    "does not exist",
    "capacity",
    "overloaded",
    "429",
    "rate limit",
    "unavailable",
    "503",
)


class _SafeFormatDict(defaultdict):
    """
    dict that returns the original "{key}" for any missing key during format.

    WHY: str.format raises KeyError on an unknown placeholder. Prompt templates
    intentionally carry placeholders an individual render may not supply (e.g.
    {learned_rules} is filled separately, and a template may evolve faster than a
    caller). Leaving unknown placeholders verbatim makes rendering total — it
    never crashes a pipeline over a missing substitution.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class BaseAgent:
    """
    Base class for every AI agent. Holds the injected collaborators every agent
    needs and exposes the protected helpers subclasses build on.

    Dependencies are injected (Rule 3); BaseAgent constructs nothing. Subclasses
    typically expose a single public method (e.g. `validate(bid)`) that builds a
    dict of template values and calls `run_agent`, then shapes the returned dict
    into a domain model. They never touch telemetry, fallback, or parsing.
    """

    def __init__(
        self,
        foundry_client: IFoundryClient,
        prompt_store: IPromptStore,
        rule_store: IRuleStore,
        telemetry: ITelemetryService,
        response_parser: ResponseParser,
    ) -> None:
        self._foundry = foundry_client
        self._prompt_store = prompt_store
        self._rule_store = rule_store
        self._telemetry = telemetry
        self._parser = response_parser

    async def _load_prompt(self, agent_name: str) -> PromptTemplate:
        """
        Fetch the active prompt version for an agent from the prompt store.

        Exactly one version per agent is active (section 6.3). A missing active
        prompt is a configuration error the seed step should have prevented, so
        it raises rather than guessing a default — running an agent with no prompt
        would produce meaningless output.
        """
        try:
            prompt = await self._prompt_store.get_active(agent_name)
        except Exception as exc:
            raise AppError(
                code="AGENT_PROMPT_LOAD",
                message="Failed to load active prompt",
                context={"agent_name": agent_name},
                cause=exc,
            )
        if prompt is None:
            raise AppError(
                code="AGENT_PROMPT_LOAD",
                message="No active prompt configured for agent",
                context={"agent_name": agent_name},
            )
        return prompt

    async def _load_rules_block(self, agent_name: str) -> str:
        """
        Build the text that fills the {learned_rules} placeholder.

        Fetches the agent's active learned rules and joins each rule's
        `as_prompt_line()` under the LEARNED RULES header. Returns "" when the
        agent has no rules so the placeholder renders to nothing rather than a
        dangling, empty header. This is the injection point of the real-time
        learning loop (Agent 10 writes the rules; every agent reads them here).
        """
        try:
            rules = await self._rule_store.list_active_for_agent(agent_name)
        except Exception as exc:
            raise AppError(
                code="AGENT_RULES_LOAD",
                message="Failed to load learned rules",
                context={"agent_name": agent_name},
                cause=exc,
            )
        if not rules:
            return ""
        lines = "\n".join(rule.as_prompt_line() for rule in rules)
        return f"{_LEARNED_RULES_HEADER}\n{lines}"

    def _render(self, template: str, values: dict) -> str:
        """
        Safely substitute {placeholders} in a template.

        Uses str.format_map with a self-healing dict (`_SafeFormatDict`) so a
        missing key leaves "{key}" untouched instead of raising KeyError. This
        keeps rendering robust as templates and callers evolve independently; a
        forgotten value degrades to a visible literal rather than a crash.
        """
        try:
            return template.format_map(_SafeFormatDict(str, values))
        except Exception as exc:
            # Reaching here means a structural problem with the template itself
            # (e.g. an unbalanced brace), not a missing key — surface it.
            raise AppError(
                code="AGENT_RENDER",
                message="Failed to render prompt template",
                context={"template_preview": template[:200]},
                cause=exc,
            )

    async def _call_llm(
        self,
        agent_name: str,
        system_prompt: str,
        user_message: str,
        *,
        bid_id: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
        max_tokens_override: int | None = None,
    ) -> dict:
        """
        Invoke the LLM with automatic fallback, telemetry, and JSON parsing.

        Flow:
          1. Load the agent's model config (model, max_tokens, temperature,
             fallback_model) from its active prompt.
          2. Call the primary model, timing wall-clock latency.
          3. On a model deprecation/capacity error, retry ONCE on the fallback
             model if one is configured (section 6.3 contract).
          4. Emit a track_llm_call span on success AND on final failure (so error
             rate and latency are captured uniformly — section 5).
          5. Parse the response JSON via the shared ResponseParser and return it.

        Final failures are wrapped as AppError "AGENT_LLM_CALL" with the
        agent_name and the model that was ultimately attempted, preserving the
        provider's typed error as the cause.
        """
        config = (await self._load_prompt(agent_name)).model_config_
        primary_model = config.model_name
        fallback_model = config.fallback_model
        max_tokens = max_tokens_override if max_tokens_override is not None else config.max_tokens

        start = time.perf_counter()
        response: LlmResponse | None = None
        used_model = primary_model
        error_code: str | None = None
        primary_error: Exception | None = None

        # --- Primary attempt -------------------------------------------------
        try:
            response = await self._foundry.get_completion(
                model=primary_model,
                system=system_prompt,
                user=user_message,
                max_tokens=max_tokens,
                temperature=config.temperature,
            )
        except Exception as exc:
            primary_error = exc

        # --- Fallback attempt (once) ----------------------------------------
        # WHY only on a model-level error: a fallback retry exists to survive a
        # deprecated/at-capacity deployment, not to mask prompt/logic bugs. A
        # non-model error is re-raised below without burning a second call.
        if (
            response is None
            and fallback_model
            and self._is_fallback_eligible(primary_error)
        ):
            used_model = fallback_model
            try:
                response = await self._foundry.get_completion(
                    model=fallback_model,
                    system=system_prompt,
                    user=user_message,
                    max_tokens=max_tokens,
                    temperature=config.temperature,
                )
            except Exception as exc:
                # Fallback also failed; the fallback error becomes the cause we
                # report, with the primary error noted in context for debugging.
                primary_error = exc

        duration_ms = (time.perf_counter() - start) * 1000.0

        # --- Failure path: emit telemetry, then raise ------------------------
        if response is None:
            error_code = (
                primary_error.code
                if isinstance(primary_error, AppError)
                else "AGENT_LLM_CALL"
            )
            self._telemetry.track_llm_call(
                agent_name=agent_name,
                model=used_model,
                tokens_in=0,
                tokens_out=0,
                duration_ms=duration_ms,
                success=False,
                bid_id=bid_id,
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                error_code=error_code,
            )
            raise AppError(
                code="AGENT_LLM_CALL",
                message="Agent LLM call failed",
                context={
                    "agent_name": agent_name,
                    "model": used_model,
                    "primary_model": primary_model,
                    "fallback_model": fallback_model,
                },
                cause=primary_error,
            )

        # --- Success path: emit telemetry, then parse ------------------------
        self._telemetry.track_llm_call(
            agent_name=agent_name,
            model=used_model,
            tokens_in=response.input_tokens,
            tokens_out=response.output_tokens,
            duration_ms=duration_ms,
            success=True,
            bid_id=bid_id,
            session_id=session_id,
            project_id=project_id,
            user_id=user_id,
            error_code=None,
        )

        # Parsing happens after telemetry so a malformed-JSON response is still
        # recorded as a (successful, billable) call — the tokens were spent.
        return self._parser.parse_json(response.text)

    @staticmethod
    def _is_fallback_eligible(error: Exception | None) -> bool:
        """
        Decide whether an error warrants a fallback-model retry.

        Matches the error's string representation (including any AppError code,
        message, and chained cause) against known model-deprecation/capacity
        markers. Broad by design: an unnecessary retry costs one call, while a
        missed retry costs the user a hard failure on a recoverable condition.
        """
        if error is None:
            return False
        haystack = str(error).lower()
        if isinstance(error, AppError):
            # Include chained context/cause so a wrapped provider 404/429 is seen.
            haystack += " " + " ".join(
                str(frame) for frame in error.get_full_chain()
            ).lower()
        return any(token in haystack for token in _FALLBACK_TRIGGER_TOKENS)

    async def run_agent(
        self,
        agent_name: str,
        template_values: dict,
        *,
        bid_id: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
        max_tokens_override: int | None = None,
    ) -> dict:
        """
        End-to-end convenience entry point that subclasses call.

        Loads the active prompt, builds the learned-rules block, renders the
        system and user templates with `template_values` plus the injected
        {learned_rules} value, then delegates to `_call_llm` (which handles
        fallback, telemetry, and parsing). Returns the parsed JSON dict for the
        subclass to map into its domain model.

        WHY a single entry point: it guarantees the learning loop ({learned_rules}
        injection) and the LLM policy (fallback + telemetry) are applied on every
        agent run with no per-agent boilerplate.
        """
        prompt = await self._load_prompt(agent_name)
        rules_block = await self._load_rules_block(agent_name)

        # The rules block fills {learned_rules}; explicit caller values win for
        # any other placeholder. A copy avoids mutating the caller's dict.
        render_values = {"learned_rules": rules_block, **template_values}

        system_prompt = self._render(prompt.system_prompt_template, render_values)
        user_message = self._render(prompt.user_message_template, render_values)

        return await self._call_llm(
            agent_name,
            system_prompt,
            user_message,
            bid_id=bid_id,
            session_id=session_id,
            project_id=project_id,
            user_id=user_id,
            max_tokens_override=max_tokens_override,
        )
