"""
CostComparator — Agent 6 of the comparison subsystem.

WHY this agent exists: once UnitNormalizer has reconciled every line item to
common units, the cost comparison itself (lowest-per-row, totals, spread, scope
caveats, outliers) is deterministic arithmetic over that JSON. Rather than ask
the model to do the math in its head — where it can silently misadd — Agent 6
asks the model to OUTPUT PYTHON CODE that reads the normalized data from stdin
and writes the comparison-table JSON to stdout (section 7, Agent 6). The code
then runs in an `IPythonSandbox`, so the numbers are computed by a real
interpreter and the model's role is reduced to writing the transformation.

CONSEQUENCE FOR THIS CLASS: the model's response is Python SOURCE, not the final
JSON. BaseAgent's `run_agent`/`_call_llm` both force JSON parsing on the
response, which would reject raw code. So this agent cannot use that path for the
code-generation step. Instead it composes BaseAgent's lower-level seams
(`_load_prompt`, `_load_rules_block`, `_render`, the injected `self._foundry` and
`self._telemetry`) in a small protected `_generate_code` helper that returns the
RAW completion text. The raw text is de-fenced, executed in the sandbox, and the
sandbox's stdout is parsed as JSON via the shared ResponseParser (Rule 5). This
keeps prompt loading, rule injection, rendering, and telemetry centralized while
adding only the one thing BaseAgent does not offer: a non-JSON completion.
"""

import json
import time

from src.agents.base_agent import BaseAgent
from src.agents.response_parser import ResponseParser
from src.core.enums import AgentName
from src.core.errors.app_error import AppError
from src.core.interfaces.foundry_client import IFoundryClient
from src.core.interfaces.prompt_store import IPromptStore
from src.core.interfaces.python_sandbox import IPythonSandbox, SandboxResult
from src.core.interfaces.rule_store import IRuleStore
from src.core.interfaces.telemetry_service import ITelemetryService

# Sandbox wall-clock budget for the generated cost code. The build doc fixes the
# sandbox at a 30s ceiling; cost math over a single job's line items is trivial,
# so the default is plenty while still bounding a runaway model-written loop.
_SANDBOX_TIMEOUT_SECONDS = 30

# Injected at the end of every code-generation system prompt to ensure the model
# uses the correct stdin keys. The payload sent to the sandbox is always the
# wrapped form {"columns": [...], "normalized": {...}} built by
# _build_stdin_payload — not the raw normalizer JSON. This note overrides any
# ambiguity in the Cosmos-stored template.
_STDIN_FORMAT_NOTE = (
    "\n\nCRITICAL — STDIN FORMAT: The JSON object on stdin has exactly two top-level keys:\n"
    '  data = json.load(sys.stdin)\n'
    '  columns = data["columns"]              # list of {"bid_id": str, "vendor_name": str}\n'
    '  groups  = data["normalized"]["groups"] # list of normalized line-item groups\n'
    "Never use data['groups'] or any other top-level key — only data['columns'] and data['normalized']."
)


class CostComparator(BaseAgent):
    """
    Generates and runs Python that builds the cost comparison table (Agent 6).

    Unlike the other comparison agents this one has TWO collaborators beyond
    BaseAgent's injected set: it additionally receives an `IPythonSandbox` (Rule
    3) to execute the model-written code. Its single job (Rule 2) is: turn
    normalized bid data into the cost-table dict — by asking the model for code,
    running that code, and parsing the result. It owns one public method,
    `compare`.
    """

    def __init__(
        self,
        foundry_client: IFoundryClient,
        prompt_store: IPromptStore,
        rule_store: IRuleStore,
        telemetry: ITelemetryService,
        response_parser: ResponseParser,
        sandbox: IPythonSandbox,
    ) -> None:
        # Forward BaseAgent's shared collaborators; store the sandbox locally as
        # the one dependency unique to a code-generating agent.
        super().__init__(
            foundry_client,
            prompt_store,
            rule_store,
            telemetry,
            response_parser,
        )
        self._sandbox = sandbox

    async def compare(
        self,
        *,
        columns_json: str,
        normalizer_output_json: str,
        session_id: str,
        project_id: str,
    ) -> dict:
        """
        Build the cost comparison table from normalized bid data.

        Flow:
          1. Ask the model for Python code via `_generate_code` (RAW text, not
             JSON — Agent 6 emits source, not the answer).
          2. Strip any Markdown code fences from the source.
          3. Feed the normalized data to the code on stdin and run it in the
             sandbox.
          4. Parse the sandbox's stdout as the cost-table JSON.

        Returns the parsed dict with keys: cost_rows, totals, analysis.

        The stdin payload is built via _build_stdin_payload: both COLUMNS and
        NORMALIZED DATA are wrapped in {"columns": [...], "normalized": {...}}
        so the generated code reads data["columns"] and data["normalized"]["groups"]
        without ambiguity. Sandbox failures
        (non-success or timeout) are wrapped as AppError "AGENT_COST_SANDBOX" with
        stderr captured for the single top-level log entry (Rules 7, 8).
        """
        template_values = {
            "columns_json": columns_json,
            "normalizer_output_json": normalizer_output_json,
        }

        # Step 1+2: obtain the model-written code as raw text and de-fence it.
        raw_code = await self._generate_code(
            template_values,
            session_id=session_id,
            project_id=project_id,
        )
        code = self._strip_code_fences(raw_code)

        # Step 3: assemble stdin. The system prompt tells the model that stdin
        # contains {"columns": [...], "normalized": {...}} — both inputs in one
        # JSON object. The generated code reads data["columns"] for vendor
        # identifiers and data["normalized"]["groups"] for the line items.
        stdin_data = self._build_stdin_payload(columns_json, normalizer_output_json)

        try:
            result: SandboxResult = await self._sandbox.run(
                code,
                stdin_data,
                _SANDBOX_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise AppError(
                code="AGENT_COST_SANDBOX",
                message="CostComparator sandbox execution raised",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        # A non-success or timed-out run means the generated code crashed or hung.
        # Surface stderr so the top-level handler can show why (Rule 7).
        if not result.success or result.timed_out:
            raise AppError(
                code="AGENT_COST_SANDBOX",
                message="CostComparator generated code failed in sandbox",
                context={
                    "session_id": session_id,
                    "project_id": project_id,
                    "timed_out": result.timed_out,
                    "stderr": result.stderr,
                },
            )

        # Step 4: the table JSON the code emitted lives on stdout — parse it with
        # the same forgiving parser used for direct LLM JSON (Rule 5).
        return self._parser.parse_json(result.stdout)

    async def _generate_code(
        self,
        template_values: dict,
        *,
        session_id: str | None,
        project_id: str | None,
    ) -> str:
        """
        Run Agent 6's prompt and return the RAW completion text (the Python code).

        This is the one seam BaseAgent does not provide: `run_agent`/`_call_llm`
        always JSON-parse the response, but Agent 6 emits source code, so parsing
        would reject it. It therefore reuses BaseAgent's prompt loading, learned-
        rule injection, and rendering (Rule 5), then calls the injected
        `self._foundry` directly to capture text — mirroring `_call_llm`'s model-
        config resolution and success/failure telemetry so this code path is still
        instrumented like every other LLM call (section 5). Fallback is
        intentionally NOT replicated here: a deprecation/capacity retry is a
        BaseAgent policy concern, and a code-gen call that fails surfaces as a
        single wrapped AppError the caller can act on.
        """
        agent_name = AgentName.COST_COMPARATOR.value

        prompt = await self._load_prompt(agent_name)
        rules_block = await self._load_rules_block(agent_name)
        render_values = {"learned_rules": rules_block, **template_values}
        system_prompt = self._render(prompt.system_prompt_template, render_values)
        user_message = self._render(prompt.user_message_template, render_values)

        # Append an unambiguous stdin format note so the generated code always
        # uses the correct keys regardless of what the Cosmos prompt says.
        # stdin is {"columns": [...], "normalized": {...}} — never the raw
        # normalizer JSON at the top level, never a different nesting.
        system_prompt = system_prompt + _STDIN_FORMAT_NOTE

        config = prompt.model_config_
        start = time.perf_counter()
        try:
            response = await self._foundry.get_completion(
                model=config.model_name,
                system=system_prompt,
                user=user_message,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
            )
        except Exception as exc:
            # Emit a failure span so code-gen errors are visible in the same
            # telemetry stream as parsed-JSON calls, then wrap (Rules 7, 8).
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._telemetry.track_llm_call(
                agent_name=agent_name,
                model=config.model_name,
                tokens_in=0,
                tokens_out=0,
                duration_ms=duration_ms,
                success=False,
                bid_id=None,
                session_id=session_id,
                project_id=project_id,
                user_id=None,
                error_code="AGENT_COST_CODEGEN",
            )
            raise AppError(
                code="AGENT_COST_CODEGEN",
                message="CostComparator code-generation LLM call failed",
                context={
                    "session_id": session_id,
                    "project_id": project_id,
                    "model": config.model_name,
                },
                cause=exc,
            )

        duration_ms = (time.perf_counter() - start) * 1000.0
        self._telemetry.track_llm_call(
            agent_name=agent_name,
            model=response.model,
            tokens_in=response.input_tokens,
            tokens_out=response.output_tokens,
            duration_ms=duration_ms,
            success=True,
            bid_id=None,
            session_id=session_id,
            project_id=project_id,
            user_id=None,
            error_code=None,
        )
        return response.text

    @staticmethod
    def _build_stdin_payload(columns_json: str, normalizer_output_json: str) -> str:
        """
        Combine the two prompt inputs into the single stdin JSON the code reads.

        Both arguments arrive as JSON STRINGS (that is what the user template
        interpolates). Re-parsing them before nesting keeps the stdin value a real
        JSON object/array under each key rather than an escaped string, so the
        generated `json.load(sys.stdin)` sees structured data. If either string is
        not valid JSON it is passed through verbatim under its key — the generated
        code, not this assembler, owns interpreting malformed upstream data.
        """
        payload = {
            "columns": CostComparator._loads_or_raw(columns_json),
            "normalized": CostComparator._loads_or_raw(normalizer_output_json),
        }
        return json.dumps(payload)

    @staticmethod
    def _loads_or_raw(value: str) -> object:
        """Parse JSON text, falling back to the raw string if it is not JSON."""
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """
        Remove ```python / ``` fences a model commonly wraps code in.

        Reuses ResponseParser's fence-stripping (Rule 5): the logic for dropping
        an opening fence line and the trailing fence is identical whether the
        fenced body is JSON or Python, so there is no second implementation.
        """
        return ResponseParser._strip_code_fences(text)
