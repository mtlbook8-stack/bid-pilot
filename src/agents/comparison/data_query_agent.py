"""
DataQueryAgent — Agent 9 of the comparison subsystem.

WHY this agent exists: a comparison session is scoped to one job's bids, but
users ask questions that reach OUTSIDE it — "how does this HVAC price compare to
what we've paid on other projects?", "which vendor bids most often?". Answering
those needs data the session doesn't hold, and arithmetic over that data. So
Agent 9 runs in TWO phases (section 7, Agent 9):

  PHASE 1 (plan)  — given the question + a schema, the model returns a QUERY PLAN
                    (collections, filters, aggregation). This is JSON the model
                    answers directly, so BaseAgent's `run_agent` (which parses
                    JSON) handles it as-is.
  PHASE 2 (code)  — the orchestrator runs the plan against Cosmos and hands the
                    retrieved rows back; the model then returns
                    {"phase":"code","python_code":"..."} — still JSON. This agent
                    extracts `python_code`, runs it in an `IPythonSandbox` with the
                    retrieved data on stdin, and parses the sandbox's stdout.

WHY Phase 2 does NOT use `run_agent`: the prompt document stores a single
`userMessageTemplate`, which holds the Phase-1 ("PHASE: plan") template. Phase 2
needs a DIFFERENT user message ("PHASE: code", carrying the query plan + the
retrieved data). Rather than add a second prompt document, the Phase-2 user
template lives here as a class constant and is rendered against the SAME seeded
system prompt (which already describes both phases), then sent through
`_call_llm` — which still parses the returned JSON envelope correctly. Phase 1
keeps using `run_agent` unchanged.
"""

from src.agents.base_agent import BaseAgent
from src.agents.response_parser import ResponseParser
from src.core.enums import AgentName
from src.core.errors.app_error import AppError
from src.core.interfaces.foundry_client import IFoundryClient
from src.core.interfaces.prompt_store import IPromptStore
from src.core.interfaces.python_sandbox import IPythonSandbox, SandboxResult
from src.core.interfaces.rule_store import IRuleStore
from src.core.interfaces.telemetry_service import ITelemetryService

# Sandbox wall-clock budget for the generated query code. Matches the build doc's
# 30s sandbox ceiling; aggregating a portfolio's worth of bids is light work, but
# the bound still protects against a runaway model-written computation.
_SANDBOX_TIMEOUT_SECONDS = 30


class DataQueryAgent(BaseAgent):
    """
    Plans and runs cross-project data queries in two phases (Agent 9).

    Like CostComparator, this agent adds an injected `IPythonSandbox` (Rule 3) on
    top of BaseAgent's shared collaborators, because Phase 2 executes model-written
    code. Its job (Rule 2) splits across two public methods that mirror the two
    prompt phases: `plan` (returns the query plan) and `generate_and_run` (runs
    the generated code and returns the answer). The orchestrator queries Cosmos
    between the two calls; this class never touches storage itself.
    """

    # Phase-2 user message (build doc section 7, Agent 9 "User Message Template
    # (Phase 2)"). Held here because the prompt document only stores the Phase-1
    # template; the {placeholders} map to the generate_and_run arguments.
    _PHASE2_USER_TEMPLATE = (
        "PHASE: code\n"
        "\n"
        "ORIGINAL QUESTION: {extracted_query}\n"
        "QUERY PLAN: {phase1_output}\n"
        "\n"
        "RETRIEVED DATA:\n"
        "{query_results_json}"
    )

    def __init__(
        self,
        foundry_client: IFoundryClient,
        prompt_store: IPromptStore,
        rule_store: IRuleStore,
        telemetry: ITelemetryService,
        response_parser: ResponseParser,
        sandbox: IPythonSandbox,
    ) -> None:
        # Forward BaseAgent's shared collaborators; keep the sandbox locally as
        # the one dependency unique to this code-running agent.
        super().__init__(
            foundry_client,
            prompt_store,
            rule_store,
            telemetry,
            response_parser,
        )
        self._sandbox = sandbox

    async def plan(
        self,
        *,
        extracted_query: str,
        project_name: str,
        job_name: str,
        trade_category: str,
        vendor_list: str,
        session_id: str,
        project_id: str,
    ) -> dict:
        """
        Phase 1 — produce the query plan for a cross-project question.

        Builds the Phase-1 user template values (keys mirror the template tokens
        exactly; the template's leading "PHASE: plan" line is fixed text in the
        prompt, not a value). The plan is plain JSON the model answers directly,
        so `run_agent` (with its built-in JSON parsing) is the right path. Returns
        the parsed dict with keys: phase, collections_needed, filters,
        description, needs_aggregation, aggregation_type.

        Any unexpected error while assembling the template values is wrapped as an
        AppError with a unique code (Rules 7, 8).
        """
        try:
            template_values = {
                "extracted_query": extracted_query,
                "project_name": project_name,
                "job_name": job_name,
                "trade_category": trade_category,
                "vendor_list": vendor_list,
            }
        except Exception as exc:
            raise AppError(
                code="AGENT_DATAQUERY_PLAN_TEMPLATE",
                message="Failed to build DataQueryAgent plan template values",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        return await self.run_agent(
            AgentName.DATA_QUERY_AGENT.value,
            template_values,
            session_id=session_id,
            project_id=project_id,
        )

    async def generate_and_run(
        self,
        *,
        extracted_query: str,
        phase1_output: str,
        query_results_json: str,
        session_id: str,
        project_id: str,
    ) -> dict:
        """
        Phase 2 — generate query code, run it on the retrieved data, return answer.

        Flow:
          1. Render the Phase-2 user message (class constant) against the seeded
             system prompt, and call `_call_llm`. The model responds with the JSON
             envelope {"phase":"code","python_code":"..."}, which `_call_llm`
             parses for us (and which carries fallback + telemetry like any call).
          2. Pull `python_code` out of the envelope and de-fence it.
          3. Run it in the sandbox with the retrieved data (`query_results_json`)
             on stdin.
          4. Parse the sandbox's stdout as the answer JSON.

        Returns the parsed dict with keys: answer, data, confidence.

        The Phase-2 template's leading "PHASE: code" line is fixed prompt text;
        ORIGINAL QUESTION / QUERY PLAN / RETRIEVED DATA map to extracted_query /
        phase1_output / query_results_json. Sandbox failures are wrapped as
        AppError "AGENT_DATAQUERY_SANDBOX" with stderr captured (Rules 7, 8).
        """
        agent_name = AgentName.DATA_QUERY_AGENT.value

        # Step 1: render the seeded SYSTEM prompt (with learned rules) but our own
        # PHASE-2 USER template, then call _call_llm directly. run_agent is not
        # used here because it would render the seeded Phase-1 user template.
        try:
            prompt = await self._load_prompt(agent_name)
            rules_block = await self._load_rules_block(agent_name)
            system_prompt = self._render(
                prompt.system_prompt_template, {"learned_rules": rules_block}
            )
            user_message = self._render(
                self._PHASE2_USER_TEMPLATE,
                {
                    "extracted_query": extracted_query,
                    "phase1_output": phase1_output,
                    "query_results_json": query_results_json,
                },
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                code="AGENT_DATAQUERY_CODE_TEMPLATE",
                message="Failed to build DataQueryAgent Phase-2 prompt",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        # The code-envelope IS JSON, so _call_llm parses it correctly.
        envelope = await self._call_llm(
            agent_name,
            system_prompt,
            user_message,
            session_id=session_id,
            project_id=project_id,
        )

        # Step 2: extract the source. A missing python_code means the model
        # ignored the Phase-2 contract — fail loudly rather than run "" (Rule 7).
        python_code = envelope.get("python_code")
        if not isinstance(python_code, str) or not python_code.strip():
            raise AppError(
                code="AGENT_DATAQUERY_NO_CODE",
                message="DataQueryAgent Phase 2 returned no python_code",
                context={
                    "session_id": session_id,
                    "project_id": project_id,
                    "envelope_keys": list(envelope.keys()),
                },
            )
        code = ResponseParser._strip_code_fences(python_code)

        # Step 3: the retrieved data is the code's stdin exactly as the prompt
        # framed it ("contains the retrieved data"), passed through unchanged.
        try:
            result: SandboxResult = await self._sandbox.run(
                code,
                query_results_json,
                _SANDBOX_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise AppError(
                code="AGENT_DATAQUERY_SANDBOX",
                message="DataQueryAgent sandbox execution raised",
                context={"session_id": session_id, "project_id": project_id},
                cause=exc,
            )

        if not result.success or result.timed_out:
            raise AppError(
                code="AGENT_DATAQUERY_SANDBOX",
                message="DataQueryAgent generated code failed in sandbox",
                context={
                    "session_id": session_id,
                    "project_id": project_id,
                    "timed_out": result.timed_out,
                    "stderr": result.stderr,
                },
            )

        # Step 4: the answer JSON the code emitted is on stdout — parse it with
        # the same shared parser used for direct LLM JSON (Rule 5).
        return self._parser.parse_json(result.stdout)
