"""Small synchronous OpenAI-compatible vLLM transport and tool-loop host."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import uuid4

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]

from milai_lab.methods.contextual_memory.decision_basis import (
    STATE_DELTA_SCHEMA,
    WORK_NOTE_SCHEMA,
    bind_delta,
)
from milai_lab.methods.contextual_memory.decision_basis import (
    projected as projected_decision,
)
from milai_lab.methods.contextual_memory.models import Observation, receipt_outcome
from milai_lab.methods.contextual_memory.operations import TaskEnvelope, new_save_operation_id
from milai_lab.methods.contextual_memory.write_contract import apply_content_patch
from milai_lab.methods.contextual_user_memory import TOOLS as MEMORY_TOOLS
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import Emit, VLLMClient
from milai_lab.runners.contextual_agent_tasks import (
    BusinessTool,
    BusinessToolResult,
    Retention,
    accept_observation,
    dispatch_action,
)
from milai_lab.runners.contextual_maintenance import (
    FINAL_SCHEMA,
    FINISH_TOOL,
    MAINTENANCE_PROTOCOL,
    SEMANTIC_FINAL_SCHEMA,
    SEMANTIC_FINISH_TOOL,
    SEMANTIC_MAINTENANCE_PROTOCOL,
    committed,
    finish_tool,
    pending_materials,
    semantic_finish,
    semantic_finish_tool,
    semantic_frontier,
)
from milai_lab.runners.contextual_maintenance import (
    finish as finish_maintenance,
)
from milai_lab.runners.contextual_session import HostSession

if TYPE_CHECKING:
    from milai_lab.runners.contextual_runtime_store import RuntimeStore

Dispatch = Callable[[str, dict[str, Any]], dict[str, Any]]
READ_ONLY_TOOLS = frozenset({"memory_search", "memory_read"})
NO_PROGRESS_LIMIT = 3
ACTION_PROTOCOL = "contextual-json-action-v2"
FINAL_ANSWER_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "final_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    },
}


def _action_response_format(
    tools: Sequence[dict[str, Any]], *, maintenance: bool = False,
    decision_policy: str = "off",
) -> dict[str, Any]:
    branches: list[dict[str, Any]] = (
        [] if maintenance else [FINAL_ANSWER_RESPONSE_FORMAT["json_schema"]["schema"]]
    )
    for tool in tools:
        function = tool.get("function", tool)
        branches.append(
            {
                "type": "object",
                "properties": {
                    "tool": {"const": function["name"]},
                    "arguments": function["parameters"],
                },
                "required": ["tool", "arguments"],
                "additionalProperties": False,
            }
        )
    if decision_policy != "off":
        key = "state_delta" if decision_policy == "basis" else "work_note"
        sidecar = STATE_DELTA_SCHEMA if decision_policy == "basis" else WORK_NOTE_SCHEMA
        branches = [
            {**branch, "properties": {key: sidecar, **branch["properties"]},
             "required": [key, *branch["required"]]}
            for branch in branches
        ]
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "host_action",
            "strict": True,
            "schema": {"oneOf": branches},
        },
    }


def _subject_tools(
    tools: Sequence[dict[str, Any]], subjects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Offer only subject handles already delivered in this Host conversation."""
    choices = [item["ref"] for item in subjects]
    selected = []
    for tool in tools:
        function = tool.get("function", tool)
        if function["name"] == "memory_save":
            tool = copy.deepcopy(tool)
            parameters = tool.get("function", tool)["parameters"]
            for branch in parameters.get("oneOf", [parameters]):
                properties = branch.get("properties", {})
                if "about_ref" in properties:
                    properties["about_ref"] = {"type": "string", "enum": choices}
        selected.append(tool)
    return selected


def _focus_tools(tools: Sequence[dict[str, Any]], *, allow_gap: bool) -> list[dict[str, Any]]:
    if allow_gap:
        return list(tools)
    selected = []
    for tool in tools:
        function = tool.get("function", tool)
        if function["name"] == "memory_search":
            tool = copy.deepcopy(tool)
            tool.get("function", tool)["parameters"]["properties"]["focus"] = {
                "const": "default",
            }
        selected.append(tool)
    return selected


def _required_tool_response_format(tool: dict[str, Any], *,
                                   decision_policy: str = "off") -> dict[str, Any]:
    function = tool.get("function", tool)
    properties = {
        "tool": {"const": function["name"]},
        "arguments": function["parameters"],
    }
    required = ["tool", "arguments"]
    if decision_policy != "off":
        key = "state_delta" if decision_policy == "basis" else "work_note"
        properties = {key: (STATE_DELTA_SCHEMA if decision_policy == "basis"
                            else WORK_NOTE_SCHEMA), **properties}
        required.insert(0, key)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "required_memory_action",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _final_response_format(decision_policy: str) -> dict[str, Any]:
    if decision_policy == "off":
        return FINAL_ANSWER_RESPONSE_FORMAT
    branch = _action_response_format([], decision_policy=decision_policy)[
        "json_schema"]["schema"]["oneOf"][0]
    return {"type": "json_schema", "json_schema": {
        "name": "final_answer", "strict": True, "schema": branch,
    }}


def _initial_state_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Before material delivery, the model can describe the task but cannot cite refs."""
    function = tool.get("function", tool)
    fields = ("context", "subject", "uncertainty")
    properties = function["parameters"]["properties"]
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    field: {**properties[field], "minLength": 1} for field in fields
                },
                "required": [required],
                "additionalProperties": False,
            }
            for required in fields
        ],
    }
    initial_function = {
        **function,
        "description": (
            "Initial current-task understanding before any memory material is delivered. "
            "Use only context, subject, or uncertainty; do not invent references."
        ),
        "parameters": schema,
    }
    return (
        {**tool, "function": initial_function}
        if "function" in tool else initial_function
    )


@dataclass
class HostResult:
    answer: str
    status: str
    calls: list[dict[str, Any]]
    usage: dict[str, int | str | None]
    elapsed_seconds: float
    transcript: list[dict[str, Any]]
    maintenance: dict[str, Any] = field(default_factory=dict)


class InvalidToolCall(ValueError):
    """A malformed or schema-invalid model tool request that can be corrected."""


@dataclass
class ContextualHost:
    """Run a vLLM Host tool loop against the caller's actual Lab dispatch."""

    client: VLLMClient
    dispatch: Dispatch
    tools: Sequence[dict[str, Any]]
    prompt: str
    emit: Emit | None = None
    delivery_mode: Literal["full", "delta"] = "full"
    envelope: TaskEnvelope | None = None
    memory: ContextualMemory | None = field(kw_only=True)
    business_tools: Mapping[str, BusinessTool] = field(default_factory=dict, kw_only=True)
    observation_retention: Retention = field(default="session", kw_only=True)
    observation_bytes: int = field(default=16000, kw_only=True)
    initial_context_bytes: int = field(default=0, kw_only=True)
    initial_context_limit: int = field(default=4, kw_only=True)
    maintenance_policy: Literal["off", "required"] = field(default="off", kw_only=True)
    maintenance_protocol: str = field(default=MAINTENANCE_PROTOCOL, kw_only=True)
    decision_policy: Literal["off", "notes", "basis"] = field(default="off", kw_only=True)
    runtime_store: RuntimeStore | None = field(default=None, kw_only=True)
    last_session: HostSession | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.decision_policy not in {"off", "notes", "basis"}:
            raise ValueError("UNKNOWN_DECISION_POLICY")
        if self.decision_policy != "off" and (
            self.memory is None or self.memory.decision_policy != self.decision_policy
            or self.client.config.tool_mode != "json_action"
            or self.maintenance_protocol != SEMANTIC_MAINTENANCE_PROTOCOL
        ):
            raise ValueError("INCOMPATIBLE_DECISION_HOST_CONFIGURATION")
        if self.maintenance_policy not in {"off", "required"}:
            raise ValueError("UNKNOWN_MAINTENANCE_POLICY")
        if self.maintenance_protocol not in {MAINTENANCE_PROTOCOL,
                                             SEMANTIC_MAINTENANCE_PROTOCOL}:
            raise ValueError("UNKNOWN_MAINTENANCE_PROTOCOL")
        if self.maintenance_policy == "required" and self.memory is None:
            raise ValueError("MAINTENANCE_REQUIRES_MEMORY")
        if (type(self.initial_context_bytes) is not int
                or not 0 <= self.initial_context_bytes <= 65536
                or type(self.initial_context_limit) is not int
                or not 1 <= self.initial_context_limit <= 32):
            raise ValueError("INVALID_INITIAL_MEMORY_CONTEXT_BUDGET")
        names = {tool.get("function", tool)["name"] for tool in self.tools}
        memory_names = {tool["function"]["name"] for tool in MEMORY_TOOLS} | {"finish_turn"}
        if (names | memory_names) & self.business_tools.keys():
            raise ValueError("BUSINESS_MEMORY_TOOL_NAME_CONFLICT")
        if len(names) != len(self.tools):
            raise ValueError("DUPLICATE_TOOL_NAME")
        for name, tool in self.business_tools.items():
            if tool.schema.get("function", tool.schema)["name"] != name:
                raise ValueError("BUSINESS_TOOL_NAME_MISMATCH")
        self.tools = [*self.tools, *(tool.schema for tool in self.business_tools.values())]
        if self.maintenance_policy == "required":
            terminal = (SEMANTIC_FINISH_TOOL if self.maintenance_protocol ==
                        SEMANTIC_MAINTENANCE_PROTOCOL else FINISH_TOOL)
            self.tools = [*self.tools, terminal]

    def run(
        self, messages: Sequence[Mapping[str, Any]], max_calls: int | None = None,
        *, envelope: TaskEnvelope | None = None, session: HostSession | None = None,
        turn_id: str = "", resume: bool = False,
    ) -> HostResult:
        """Run at most max_calls model requests, including the final answer request."""
        if envelope is None:
            envelope = self.envelope
        if envelope is not None and envelope.purpose in {"delete_only", "delete_then_answer"}:
            if envelope.phase != "lifecycle" or "delete" not in envelope.allowed_operations:
                raise ValueError("DELETE_NOT_AUTHORIZED_FOR_TASK")
            memory = self.memory
            ledger = getattr(memory, "deletion_ledger", None)
            operation = (
                ledger.read().operations.get(envelope.operation_id)
                if ledger is not None else None
            )
            if (
                ledger is None or ledger.user_id != envelope.user_id
                or operation is None or not operation.committed
                or operation.pending_effects or operation.task_id != envelope.task_id
                or operation.scope_id != envelope.scope_id
                or operation.purpose != envelope.purpose
                or operation.retained_input_sha256 != hashlib.sha256(
                    envelope.retained_input.encode()
                ).hexdigest()
            ):
                return HostResult("", "cleanup_pending", [], _empty_usage(), 0.0, [])
            if envelope.purpose == "delete_only":
                return HostResult("", "deletion_complete", [], _empty_usage(), 0.0, [])
            if not envelope.retained_input:
                return HostResult("", "input_insufficient", [], _empty_usage(), 0.0, [])
            messages = [{"role": "user", "content": envelope.retained_input}]
        budget = self.client.config.max_calls if max_calls is None else max_calls
        if type(budget) is not int or budget < 0:
            raise ValueError("max_calls must be non-negative")
        protocol_prompt = self.prompt + (
            f"\nThis run allows at most {budget} model responses, including the final answer. "
            "Use compact useful memory operations; reserve one response to finish. "
            "Search results already include material content; answer directly when that is enough. "
            "Repeating the same read-only action without a state change will not "
            "return its content again."
        )
        if self.memory is not None:
            protocol_prompt += (
                "\nNew observations are retained "
                + ("only for this session; a new session cannot retrieve unsaved observations. "
                   if self.observation_retention == "session" else "as durable raw sources. ")
                + "CURRENT describes a version, not persistence. A successful business action "
                "or confirmation does not save memory. Preserve supported information needed "
                "for later work, such as commitments, decisions, requirements or reusable "
                "outcomes, with memory_save. Look for the existing person and matter before "
                "choosing CREATE or REVISE. Routine outputs, temporary instructions and "
                "unchanged understanding need no write."
            )
        if self.decision_policy == "basis":
            protocol_prompt += (
                "\nIn the same JSON action, include state_delta: null to keep the one current "
                "decision, {op:'set', decision, scope:{subject_ref,item,context}, "
                "adopted_evidence, critical_gap, status} to replace it, or {op:'clear'} "
                "to clear it. Choose adopted_evidence from delivered body refs or cN "
                "continued exact versions; a link alone is not read evidence. A decision "
                "is a working judgment, not proof or a business receipt. A changed adopted "
                "version needs review; a new observation may matter even with no old link. "
                "Use memory_search focus=critical_gap only for a concrete information need, "
                "with empty query. No extra State call is needed."
            )
        elif self.decision_policy == "notes":
            protocol_prompt += (
                "\nIn the same JSON action, include work_note: null to keep your current "
                "work note or a short replacement string. It can record a judgment, "
                "references, uncertainty, and what to query next; you may revise it each "
                "step. Use the same memory and business tools. This note is task-local."
            )
        maintenance_required = self.maintenance_policy == "required"
        semantic_maintenance = (maintenance_required and self.maintenance_protocol ==
                                SEMANTIC_MAINTENANCE_PROTOCOL)
        if semantic_maintenance:
            protocol_prompt += (
                "\nBefore finishing, use finish_turn with maintenance.decision and remaining. "
                "processed means the new material and actual business outcomes have been "
                "handled; not_selected means no durable change was chosen; pending names "
                "unfinished matters by delivered ref and reason. The program checks actual "
                "writes, source body coverage, unresolved operations and business results. "
                "Only explicit application requirements appear in the frontier; their absence "
                "does not mean a supported matter needs no durable memory. Session source "
                "retention does not bar a durable interpretation. Save the first supported "
                "commitment or decision needed later, without waiting for repetition. After a "
                "real business result, update the same matter's status when it changes; an "
                "earlier pending plan does not record execution. Zero-write processed is for "
                "routine or unchanged meaning, or when a current durable record already "
                "expresses it. A tool result or CURRENT version alone is not a durable save. "
                "Do not claim required review or saving without the delivered body and actual "
                "current durable record. Once evidence suffices, issue the next operation "
                "directly instead of repeatedly restating the decision or planned call. "
                "Finish using finish_turn as the sole tool call in its response."
            )
        elif maintenance_required:
            protocol_prompt += (
                "\nBefore finishing, review every new observation listed in the maintenance "
                "frontier. Preserve the first supported commitment/requirement for later work; "
                "do not wait for it to be repeated. After a real business result, revise the "
                "same matter's status (success, failure, or uncertainty) using that result as "
                "evidence. Previously saving a pending plan does not record its execution. "
                "Use saved only for actual current durable record commits with these sources; "
                "no_change with a brief reason for routine/already represented observations; "
                "pending if useful maintenance is still unfinished. Group sources with the same "
                "decision. Review is a receipt, not a memory write. Never claim saved without "
                "memory_save. Keep scope and concrete entities clear. Execution limits apply "
                "to the requested business action; stated corrections to existing matters and "
                "future requirements retain their own scope and must update the old understanding. "
                "Respect explicit instructions not to retain information or to limit it to this "
                "session. "
                "Use no_change only after considering all facts in a source, including updates "
                "stated alongside an instruction. "
                "Finish using finish_turn as the sole tool call in its response. "
                "Its record_refs are mN handles returned by a successful memory_save, "
                "never proposed text. Include each frontier source once."
            )
        if self.client.config.tool_mode == "json_action":
            sidecar_example = (
                '"state_delta":null,' if self.decision_policy == "basis" else
                '"work_note":null,' if self.decision_policy == "notes" else ""
            )
            protocol_prompt += (
                "\n\nJSON-action protocol: respond with exactly one JSON object: "
                + '{' + sidecar_example
                + '"tool":"TOOL_NAME","arguments":{...}} to call a tool, or '
                + ('{' + sidecar_example + '"tool":"finish_turn","arguments":{...}}'
                   if maintenance_required else
                   '{' + sidecar_example + '"answer":"final answer"}')
                + ' to finish. Tool results will be returned '
                "as a user message. This is the configured json_action mode. "
                "Available tools (names, descriptions, and JSON Schema parameters):\n"
                + _json(self.tools)
            )
        session = session or HostSession(uuid4().hex, self.memory)
        if session.memory is not self.memory:
            raise ValueError("HOST_SESSION_MEMORY_MISMATCH")
        if maintenance_required:
            active = session.maintenance.setdefault("protocol", self.maintenance_protocol)
            if active != self.maintenance_protocol:
                raise ValueError("MAINTENANCE_PROTOCOL_MISMATCH")
        self.last_session = session
        if resume:
            if session.closed or session.turn_id != turn_id:
                raise ValueError("HOST_RESUME_TURN_MISMATCH")
            session.read_cache.clear()
        else:
            session.begin_turn(turn_id)
        if resume:
            self._recover_business_results(session)
        recovered_settled_actions = (
            [item for item in self.runtime_store.actions_for_turn(
                session.session_id, session.turn_id)
             if (item.get("reconciliation") or {}).get("result", item.get("result") or {}).get(
                 "status") in {"succeeded", "failed"}]
            if resume and self.runtime_store is not None else []
        )
        transcript = session.transcript
        transcript[0] = {"role": "system", "content": protocol_prompt}
        if not resume:
            question = next((str(item["content"]) for item in reversed(messages)
                             if item.get("role") == "user" and
                             isinstance(item.get("content"), str)),
                            self.memory.workspace.frame.question if self.memory else "")
            self.prime_session(session, question)
        for index, message in enumerate(messages):
            if maintenance_required and (
                message.get("role") == "user" and isinstance(message.get("content"), str)
            ):
                assert self.memory is not None
                accept_observation(self.memory, session, Observation(
                    f"{session.turn_id}:input:{index}", str(message["content"]), "user",
                    "host-request", session_id=session.session_id,
                ), retention=self.observation_retention, max_bytes=self.observation_bytes,
                   emit=self.emit, label="Current user request",
                   required_review_ranges=((0, len(str(message["content"]))),)
                   if message["content"] else ())
            else:
                transcript.append(dict(message))
        delivery = session.delivery
        bound_memory = self.memory
        material_view = session.material_view
        if material_view is not None:
            transcript[0]["content"] += (
                "\nSubject handles (identity, not topic): "
                + _json(material_view.subject_catalogue())
                + ". Source materials may provide additional speaker_ref handles. "
                "Choose the described person; that person may differ from the source speaker."
            )
        staged_tools = {
            name: next(
                (tool for tool in self.tools
                 if tool.get("function", tool).get("name") == name),
                None,
            )
            for name in ("memory_state", "memory_search")
        }
        if staged_tools["memory_state"] is not None:
            staged_tools["memory_state"] = _initial_state_tool(
                staged_tools["memory_state"]
            )
        active_stage = (
            "state" if isinstance(bound_memory, ContextualMemory)
            and bound_memory.state_policy == "forced_legacy" and all(staged_tools.values())
            and bound_memory.execution_context.phase == "answer"
            else "free"
        )
        if active_stage != "free":
            if budget < 3:
                return HostResult("", "state_budget_insufficient", [], _empty_usage(), 0.0, [])
            transcript[0]["content"] += (
                "\nFor this state-enabled task, first call memory_state using only "
                "context, subject, or uncertainty. These describe your current task "
                "understanding; do not provide refs, coverage, conditions, or dates "
                "before seeing material. Then call "
                "memory_search so the updated State affects retrieval. Treat the "
                "question as a task, not as evidence of a durable user fact."
            )
        calls: list[dict[str, Any]] = []
        usage = _empty_usage()
        if resume:
            calls = copy.deepcopy(session.maintenance.get("turn_calls", []))
            usage = copy.deepcopy(session.maintenance.get("turn_usage", usage))
        started = time.monotonic()
        model_calls = 0
        read_cache = session.read_cache
        last_condition_evidence: str | None = None
        no_progress = 0

        def business_outcomes() -> list[dict[str, Any]]:
            if self.runtime_store is not None:
                return [{"call_id": item["call_id"], "name": item["name"],
                         "status": (item.get("reconciliation") or {}).get(
                             "result", item.get("result") or {}).get("status", "unknown")}
                        for item in self.runtime_store.actions_for_turn(
                            session.session_id, session.turn_id)]
            return [{"call_id": call.get("tool_call_id"), "name": call["name"],
                     "status": call["execution_status"]}
                    for call in calls if call.get("name") in self.business_tools
                    and "execution_status" in call]

        def persist() -> None:
            if self.runtime_store is not None:
                assert self.memory is not None
                session.maintenance["turn_calls"] = calls
                session.maintenance["turn_usage"] = usage
                self.runtime_store.persist(self.memory, session)

        def make_result(answer: str, status: str) -> HostResult:
            persist()
            result = self._result(answer, status, calls, usage, started, transcript)
            if maintenance_required:
                if semantic_maintenance:
                    reviewed = session.maintenance.get("last_review")
                    if status == "complete" and reviewed and reviewed["status"] == "complete":
                        result.maintenance = copy.deepcopy(reviewed)
                    else:
                        result.maintenance = {
                            **semantic_frontier(session,
                                                business_outcomes=business_outcomes()),
                            "status": "pending", "last_review": reviewed,
                        }
                else:
                    result.maintenance = {
                        "protocol": MAINTENANCE_PROTOCOL,
                        "status": "pending" if pending_materials(session) or
                        session.maintenance.get("unsettled_operations") else "complete",
                        "pending": pending_materials(session),
                        "last_review": session.maintenance.get("last_review"),
                    }
                if status == "complete" and result.maintenance["status"] != "complete":
                    result.status = "maintenance_pending"
            return result

        def finish_answer(action: dict[str, Any]) -> HostResult | None:
            nonlocal no_progress
            if not maintenance_required:
                return make_result(action["answer"], "complete")
            try:
                validate(action, SEMANTIC_FINAL_SCHEMA if semantic_maintenance else FINAL_SCHEMA)
                reviewed = (semantic_finish(
                    session, action["maintenance"], business_outcomes=business_outcomes(),
                ) if semantic_maintenance else
                    finish_maintenance(session, action["memory_review"]))
            except (ValueError, TypeError, ValidationError) as error:
                no_progress += 1
                error_text = error.message if isinstance(error, ValidationError) else str(error)
                if self.emit:
                    self.emit({"event": "maintenance_rejected", "error": error_text,
                               "session_id": session.session_id, "turn_id": session.turn_id})
                if model_calls == budget or no_progress >= NO_PROGRESS_LIMIT:
                    return make_result(action.get("answer", ""), "maintenance_pending")
                transcript.append({"role": "user", "content":
                                   "Maintenance receipt rejected: " + error_text})
                return None
            if self.emit:
                self.emit({"event": "maintenance_review", "session_id": session.session_id,
                           "turn_id": session.turn_id, **reviewed})
            return make_result(action["answer"], "complete" if reviewed["status"] == "complete"
                               else "maintenance_pending")

        def resolved_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if material_view is None:
                return arguments

            def resolve_ref(value: str, *, body: bool = False,
                            kind: str | None = None, field: str = "ref") -> str:
                if value != "unknown" and value not in session.visible_bindings:
                    raise InvalidToolCall("MATERIAL_REF_NOT_DELIVERED")
                binding = material_view.binding(value)
                if kind is not None and binding.kind != kind:
                    raise InvalidToolCall("reference has the wrong material kind")
                if body and not binding.spans:
                    raise InvalidToolCall(
                        f"{field}={value}: read the referenced body before using it to write"
                    )
                return binding.exact_ref

            resolved = dict(arguments)
            if name == "memory_read":
                resolved["ref"] = resolve_ref(arguments["ref"])
            elif name == "memory_save":
                if arguments.get("basis_mode") == "delta":
                    target_alias = arguments["target_ref"]
                    target_exact = resolve_ref(target_alias, body=True,
                                               kind="interpretation", field="target_ref")
                    target_row: dict[str, Any] | None = None

                    def find_target(value: Any) -> None:
                        nonlocal target_row
                        if isinstance(value, dict):
                            if (value.get("kind") == "interpretation"
                                    and value.get("ref") == target_alias):
                                if (target_row is None or value.get("body_delivery") == "full"):
                                    target_row = value
                            for part in value.values():
                                if isinstance(part, (dict, list)):
                                    find_target(part)
                        elif isinstance(value, list):
                            for part in value:
                                find_target(part)

                    for message, content, bindings in reversed(session.deliveries):
                        if target_alias not in bindings or message.get("content") != content:
                            continue
                        from milai_lab.runners.contextual_runtime_store import _payload

                        projected = _payload(message)
                        if projected is not None:
                            find_target(projected)
                        if target_row is not None:
                            break
                    if (target_row is None or target_row.get("status") != "CURRENT"
                            or target_row.get("body_delivery") != "full"):
                        raise InvalidToolCall(
                            "DELTA_TARGET_REQUIRES_DELIVERED_CURRENT_FULL_BODY"
                        )
                    assert bound_memory is not None
                    old_target = bound_memory.read(target_exact, include_sources=False,
                                                   _visible=False)
                    if old_target.get("current_ref") != target_exact:
                        raise InvalidToolCall("DELTA_TARGET_VERSION_CHANGED")
                    for field, kind, relation in (
                        ("source_delta", "source", "source_refs"),
                        ("dependency_delta", "interpretation", "dependency_refs"),
                    ):
                        if field not in arguments:
                            continue
                        delta = arguments[field]
                        for alias in delta["remove"]:
                            if alias not in target_row.get(relation, []):
                                raise InvalidToolCall(
                                    f"{field}.remove={alias}: not in delivered target {relation}"
                                )
                        resolved[field] = {
                            "add": [resolve_ref(alias, body=True, kind=kind,
                                                field=f"{field}.add")
                                    for alias in delta["add"]],
                            "remove": [resolve_ref(alias, kind=kind,
                                                   field=f"{field}.remove")
                                       for alias in delta["remove"]],
                        }
                if "content_patch" in resolved:
                    assert bound_memory is not None and material_view is not None
                    target = resolve_ref(arguments["target_ref"], body=True,
                                         kind="interpretation", field="target_ref")
                    old = bound_memory.read(target, include_sources=False, _visible=False)
                    apply_content_patch(
                        old["text"], arguments["content_patch"],
                        visible_spans=material_view.binding(arguments["target_ref"]).spans,
                    )
                if "about_ref" in resolved:
                    resolved["about_ref"] = resolve_ref(resolved["about_ref"], kind="subject")
                for key, kind in (("source_ref", "source"),
                                  ("target_ref", "interpretation")):
                    if key in resolved:
                        resolved[key] = resolve_ref(resolved[key], body=True,
                                                    kind=kind, field=key)
                for key, kind in (("source_refs", "source"),
                                  ("dependencies", "interpretation")):
                    if key in resolved:
                        resolved[key] = [resolve_ref(ref, body=True, kind=kind,
                                                     field=f"{key}[{index}]")
                                         for index, ref in enumerate(resolved[key])]
            elif name == "memory_state":
                for key in ("intentions", "conflicts"):
                    if key in resolved:
                        resolved[key] = [resolve_ref(ref, body=True,
                                                     kind="interpretation")
                                         for ref in resolved[key]]
            if name in READ_ONLY_TOOLS and "condition_evidence" in resolved:
                evidence = []
                for item in resolved["condition_evidence"]:
                    item = dict(item)
                    if item.get("basis_ref"):
                        item["basis_ref"] = resolve_ref(
                            item["basis_ref"], body=True, kind="source",
                        )
                    evidence.append(item)
                resolved["condition_evidence"] = evidence
            return resolved

        def preflight_sidecar(action: dict[str, Any], schema: dict[str, Any]) -> Any:
            """Check both halves before either state or external action has an effect."""
            session.refresh_visibility()
            validate(action, schema)
            assert bound_memory is not None and material_view is not None
            name = action.get("tool")
            if name is not None:
                arguments = action["arguments"]
                if name == "finish_turn":
                    validate(arguments, SEMANTIC_FINAL_SCHEMA)
                    semantic_finish(session, arguments["maintenance"],
                                    business_outcomes=business_outcomes(), commit=False)
                else:
                    required = {"state": "memory_state", "search": "memory_search"}.get(
                        active_stage
                    )
                    if required is not None and name != required:
                        raise InvalidToolCall(f"{required} must complete before other actions")
                    self._validate_tool(name, arguments)
                    dispatched = resolved_arguments(name, arguments)
                    if name in self.business_tools and any(
                        prior["name"] == name and prior["arguments"] == dispatched
                        for prior in recovered_settled_actions
                    ):
                        raise InvalidToolCall("RECOVERED_ACTION_ALREADY_SETTLED")
            if self.decision_policy == "notes":
                return action["work_note"]
            current = bound_memory.state.active_decision
            subjects = {"unknown": "unresolved"}
            if any(item["ref"] == "u0" for item in material_view.subject_catalogue()):
                subjects["u0"] = "current_user"
            subjects.update({
                item["ref"]: material_view.binding(item["ref"]).exact_ref
                for item in material_view.subject_catalogue()
                if item["ref"] not in {"u0", "unknown"}
                and item["ref"] in session.visible_bindings
            })

            def current_ref(ref: str) -> str:
                if ref in bound_memory.forgotten:
                    raise ValueError("DECISION_EVIDENCE_UNAVAILABLE")
                try:
                    return bound_memory.resolve(ref)
                except (KeyError, ValueError) as exc:
                    raise ValueError("DECISION_EVIDENCE_UNAVAILABLE") from exc

            candidate = bind_delta(
                action["state_delta"], current=current,
                task_id=bound_memory.state.task_id,
                visible=session.visible_bindings,
                valid_subjects=subjects, unavailable=bound_memory.forgotten,
                current_ref=current_ref,
                delivered_source_sequence=max((
                    bound_memory.source_sequence.get(binding.exact_ref, 0)
                    for binding in session.visible_bindings.values()
                    if binding.kind == "source" and binding.spans
                ), default=0),
            )
            if name == "memory_search" and action["arguments"].get("focus") == "critical_gap":
                if not bound_memory.decision_gap_focus:
                    raise InvalidToolCall("CRITICAL_GAP_FOCUS_DISABLED")
                if (candidate is None or not candidate.critical_gap.strip()
                        or action["arguments"].get("query", "")):
                    raise InvalidToolCall("CRITICAL_GAP_REQUIRES_EMPTY_QUERY_AND_ACTIVE_GAP")
            return candidate

        def apply_sidecar(action: dict[str, Any], candidate: Any) -> None:
            assert bound_memory is not None
            if self.decision_policy == "notes":
                if candidate is not None:
                    bound_memory.state.work_note = candidate
                    persist()
                    if self.emit:
                        self.emit({"event": "work_note_saved", "task_id":
                                   bound_memory.state.task_id, "characters": len(candidate)})
                return
            if action["state_delta"] is not None:
                old_focus = (
                    bound_memory.state.active_decision.critical_gap,
                    bound_memory.state.active_decision.scope.get("item", ""),
                ) if bound_memory.state.active_decision else ("", "")
                bound_memory.apply_decision(candidate)
                new_focus = (candidate.critical_gap, candidate.scope.get("item", "")) if (
                    candidate is not None
                ) else ("", "")
                if old_focus != new_focus:
                    read_cache.clear()
                persist()
                if self.emit:
                    self.emit({
                        "event": "decision_delta_accepted",
                        "task_id": bound_memory.state.task_id,
                        "decision_id": candidate.decision_id if candidate else None,
                        "revision": candidate.revision if candidate else None,
                        "adopted": [
                            {"exact_ref": row.exact_ref, "spans": row.spans}
                            for row in candidate.adopted
                        ] if candidate else [],
                        "focus_changed": old_focus != new_focus,
                    })

        def record_tool_message(outcome: dict[str, Any]) -> None:
            if isinstance(outcome.get("result"), dict):
                session.record_delivery(transcript[-1], outcome["result"])
                if self.emit and material_view is not None:
                    self.emit({
                        "event": "material_visible", "session_id": session.session_id,
                        "turn_id": session.turn_id, "tool_call_id": outcome.get("tool_call_id"),
                        "bindings": {alias: asdict(binding) for alias, binding in
                                     material_view.visible_bindings(outcome["result"]).items()},
                    })

        def rejected_tool_call(name: str, error: str) -> dict[str, Any]:
            outcome: dict[str, Any] = {"ok": False, "error": error}
            if name == "memory_save":
                result = {
                    "status": "ERROR", "decision": "REJECTED",
                    "operation_id": new_save_operation_id(),
                }
                outcome["result"] = result
                outcome["operation_receipt"] = asdict(receipt_outcome(name, result))
            return outcome

        def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            nonlocal no_progress, last_condition_evidence, active_stage
            session.refresh_visibility()
            if name not in READ_ONLY_TOOLS:
                read_cache.clear()
            try:
                required = {"state": "memory_state", "search": "memory_search"}.get(
                    active_stage
                )
                if required is not None and name != required:
                    raise InvalidToolCall(f"{required} must complete before other actions")
                if active_stage == "state":
                    initial = cast(dict[str, Any], staged_tools["memory_state"])
                    validate(
                        instance=arguments,
                        schema=initial.get("function", initial)["parameters"],
                    )
                else:
                    self._validate_tool(name, arguments)
                dispatched_arguments = resolved_arguments(name, arguments)
                if active_stage == "state" and not any(
                    isinstance(arguments.get(field), str) and arguments[field].strip()
                    for field in ("context", "subject", "uncertainty")
                ):
                    raise InvalidToolCall("memory_state needs nonempty task understanding")
            except (ValueError, TypeError, ValidationError) as exc:
                no_progress += 1
                return rejected_tool_call(name, f"Invalid tool call: {exc}")
            if name in self.business_tools:
                for prior in recovered_settled_actions:
                    prior_result = (prior.get("reconciliation") or {}).get(
                        "result", prior.get("result") or {})
                    if (prior["name"] == name and prior["arguments"] == dispatched_arguments
                            and prior_result.get("status") in {"succeeded", "failed"}):
                        no_progress += 1
                        return {
                            "ok": False, "error": "RECOVERED_ACTION_ALREADY_SETTLED",
                            "prior_call_id": prior["call_id"],
                            "prior_status": prior_result["status"],
                            "notice": "This recovered turn already has a settled result for "
                                      "the same action. Use that result; no action was run.",
                        }
            if name in READ_ONLY_TOOLS and arguments.get("condition_evidence"):
                evidence = _json(arguments["condition_evidence"], canonical=True)
                if evidence != last_condition_evidence:
                    # QueryContext is task-local state changed by this read-only call.
                    read_cache.clear()
                    last_condition_evidence = evidence
            key = _json([name, arguments], canonical=True) if name in READ_ONLY_TOOLS else None
            if key is not None and key in read_cache:
                previous = read_cache[key]
                no_progress += 1
                return {
                    "ok": calls[previous]["ok"],
                    "operation_receipt": calls[previous]["operation_receipt"],
                    "reused": True,
                    "reused_from_call": previous,
                    "notice": "Identical read-only result is already in the earlier tool receipt. "
                    "Use it, choose a different action, or answer.",
                }
            dispatch_started = time.monotonic()
            try:
                call_id = f"{session.session_id}:{session.turn_index}:{len(calls)}"
                if self.runtime_store is not None:
                    call_id = self.runtime_store.call_id(
                        session.session_id, session.turn_id,
                        session.maintenance.get("call_ordinal", 0),
                    )
                    session.maintenance["call_ordinal"] = (
                        session.maintenance.get("call_ordinal", 0) + 1
                    )
                if name in self.business_tools:
                    result: dict[str, Any] | BusinessToolResult = self._business_action(
                        name, dispatched_arguments, call_id, session,
                    )
                else:
                    result = dispatch_action(
                        name, dispatched_arguments, memory_dispatch=self.dispatch,
                        business_tools=self.business_tools, call_id=call_id,
                    )
            finally:
                if self.emit:
                    self.emit({
                        "event": "host_dispatch", "tool": name,
                        "session_id": session.session_id, "turn_id": session.turn_id,
                        "tool_call_id": call_id,
                        "elapsed_seconds": time.monotonic() - dispatch_started,
                    })
            if isinstance(result, BusinessToolResult):
                no_progress = 0
                acquired: dict[str, Any] = {}
                if bound_memory is None:
                    projected_business: dict[str, Any] = {"output": result.output}
                else:
                    observation = self._business_observation(
                        name, dispatched_arguments, result, session.session_id,
                    )
                    acquired = accept_observation(
                        bound_memory, session, observation,
                        retention=self.observation_retention, max_bytes=self.observation_bytes,
                        emit=self.emit, deliver=False,
                    )
                    projected_business = acquired.get("material", acquired)
                    if "source_ref" in acquired:
                        session.observations[acquired["source_ref"]] = projected_business
                    session.maintenance.setdefault("delivered_actions", []).append(call_id)
                if self.emit:
                    self.emit({
                        "event": "business_result", "session_id": session.session_id,
                        "turn_id": session.turn_id, "tool_call_id": call_id, "tool": name,
                        "arguments": dispatched_arguments, "execution_status": result.status,
                        "output": result.output, "source_ref": acquired.get("source_ref"),
                    })
                return {"ok": result.status == "succeeded", "execution_status": result.status,
                        "tool_call_id": call_id, "session_id": session.session_id,
                        "turn_id": session.turn_id, "result": projected_business}
            if not isinstance(result, dict):
                raise TypeError("memory dispatch must return a dict")
            receipt = receipt_outcome(name, result)
            internal_result = result
            if name == "memory_save":
                committed(session, receipt, internal_result)
                persist()
            if active_stage == "state" and name == "memory_state" and receipt.ok:
                active_stage = "search"
            if name in READ_ONLY_TOOLS:
                original_bytes = len(_json(result).encode())
                capacity = getattr(self.client, "capacity", None)
                original_tokens = (
                    capacity.text_tokens(_json(result)) if capacity is not None else None
                )
                omitted = 0
                if material_view is not None:
                    result = material_view.project(
                        internal_result, max_bytes=arguments.get("max_bytes", 16000),
                        linked=(isinstance(bound_memory, ContextualMemory)
                                and bound_memory.material_mode == "linked"),
                        include_sources=(name == "memory_read"
                                         and arguments.get("include_sources", True)),
                    )
                elif self.delivery_mode == "delta":
                    candidate, omitted = delivery.deliver(result, transcript)
                    if len(_json(candidate).encode()) < original_bytes:
                        result = candidate
                    else:
                        omitted = 0
                if active_stage == "search" and name == "memory_search" and receipt.ok:
                    attention = internal_result.get("attention")
                    if (isinstance(attention, dict) and attention.get("state_sha256")
                            and isinstance(internal_result.get("query"), str)
                            and result.get("status") != "INSUFFICIENT_MATERIAL_BUDGET"):
                        active_stage = "free"
                delivered_bytes = len(_json(result).encode())
                if self.emit:
                    breakdown = _material_token_breakdown(result, capacity)
                    self.emit({
                        "event": "material_delivery",
                        "tool": name,
                        "delivery_mode": self.delivery_mode,
                        "context_generation": delivery.generation,
                        "omitted_body_bytes": omitted,
                        "original_bytes": original_bytes,
                        "delivered_bytes": delivered_bytes,
                        "original_total_tokens": original_tokens,
                        "internal_material_bytes": original_bytes,
                        "projected_material_bytes": delivered_bytes,
                        "internal_material_tokens": original_tokens,
                        "projected_material_tokens": breakdown["delivered_total_tokens"],
                        "material_view_protocol": result.get("view"),
                        "tokenizer_identity": getattr(capacity, "identity", None),
                        **breakdown,
                    })
                    if (name == "memory_search" and isinstance(bound_memory, ContextualMemory)
                            and bound_memory.contextual):
                        attention = internal_result.get("attention", {})
                        delivered_bindings = (
                            material_view.visible_bindings(result)
                            if material_view is not None else {}
                        )
                        self.emit({
                            "event": "state_attention_search",
                            "effective_query": internal_result.get("query"),
                            "state_sha256": attention.get("state_sha256"),
                            "attention_action": attention.get("action"),
                            "attention_reason": attention.get("reason"),
                            "selected_refs": [
                                item.get("source_id")
                                for item in attention.get("selected_sources", [])
                            ],
                            "delivered_materials": [
                                {
                                    **{key: item[key]
                                       for key in ("ref", "kind", "status", "range")
                                       if key in item},
                                    "exact_ref": delivered_bindings[item["ref"]].exact_ref,
                                    "spans": [list(span)
                                              for span in delivered_bindings[item["ref"]].spans],
                                }
                                for item in (result.get("materials", [])
                                             + result.get("expanded_materials", []))
                                if item.get("ref") in delivered_bindings
                            ],
                        })
            elif name == "memory_save" and material_view is not None:
                result = material_view.project_write(internal_result)
            operation_receipt = (
                {
                    "completion": receipt.completion,
                    "decision": receipt.decision,
                    "operation_id": receipt.operation_id,
                    "succeeded": receipt.succeeded,
                    "failed": receipt.failed,
                    "cleanup_pending": bool(receipt.pending or receipt.cleanup_effects),
                }
                if material_view is not None and name in READ_ONLY_TOOLS | {"memory_save"}
                else asdict(receipt)
            )
            outcome = {"ok": receipt.ok, "result": result,
                       "operation_receipt": operation_receipt,
                       "session_id": session.session_id, "turn_id": session.turn_id,
                       "tool_call_id": call_id}
            if key is not None:
                read_cache[key] = len(calls)
            # A dispatched write may have changed state even if its result is partial failure.
            no_progress = (
                no_progress + 1 if (name not in READ_ONLY_TOOLS
                                    and receipt.decision == "NO_CHANGE")
                or (name in READ_ONLY_TOOLS and not outcome["ok"])
                else 0
            )
            return outcome

        def stalled() -> HostResult | None:
            if no_progress < NO_PROGRESS_LIMIT:
                return None
            if self.emit:
                self.emit(
                    {
                        "event": "host_no_progress",
                        "consecutive_calls": no_progress,
                        "model_calls": model_calls,
                    }
                )
            return make_result("", "no_progress")

        while model_calls < budget:
            persist()
            final_request = model_calls + 1 == budget
            if final_request and active_stage != "free":
                return make_result("", "state_unconsumed")
            request_transcript = list(transcript)
            if self.decision_policy == "basis" and bound_memory is not None:
                current_decision = bound_memory.state.active_decision
                subject_alias = "unknown"
                if current_decision is not None and material_view is not None:
                    subject_alias = next((
                        item["ref"] for item in material_view.subject_catalogue()
                        if (item["ref"] in {"u0", "unknown"} and
                            {"u0": "current_user", "unknown": "unresolved"}[
                                item["ref"]] == current_decision.scope["subject_ref"])
                        or (item["ref"] not in {"u0", "unknown"}
                            and material_view.binding(item["ref"]).exact_ref ==
                            current_decision.scope["subject_ref"])
                    ), "unknown")
                request_transcript.append({
                    "role": "user", "content": "Current task decision (cN keeps an already "
                    "adopted exact version, not a new read): " +
                    _json(projected_decision(current_decision,
                                             subject_alias=subject_alias,
                                             new_observations=tuple(
                        alias for alias, binding in session.visible_bindings.items()
                        if current_decision is not None and binding.kind == "source"
                        and binding.spans and bound_memory.source_sequence.get(
                            binding.exact_ref, 0
                        ) > current_decision.last_delivered_source_sequence
                    ))),
                })
            elif self.decision_policy == "notes" and bound_memory is not None:
                request_transcript.append({
                    "role": "user", "content": "Current task work note: " +
                    bound_memory.state.work_note,
                })
            if maintenance_required:
                request_transcript.append({"role": "user", "content":
                    ("Maintenance frontier (program evidence for this turn): "
                     + _json(semantic_frontier(
                         session, business_outcomes=business_outcomes()))
                     if semantic_maintenance else
                     "Maintenance frontier (new observations to review before finishing): "
                     + _json(pending_materials(session)))})
            if final_request:
                final_format = (
                    ('Call finish_turn with maintenance and answer.' if semantic_maintenance
                     else 'Call finish_turn with memory_review and answer.')
                    if maintenance_required and self.client.config.tool_mode == "json_action"
                    else "Use finish_turn only."
                    if maintenance_required else
                    'Return only a JSON object of the form {"answer":"brief final answer"}.'
                    if self.client.config.tool_mode == "json_action"
                    else "Return a brief final answer."
                )
                request_transcript.append(
                    {
                        "role": "user",
                        "content": "This is the last permitted model response. "
                        "No tool calls can be executed after this response. "
                        + final_format
                        + " Preserve the task's requested answer format inside the answer text.",
                    }
                )
            native = self.client.config.tool_mode == "native"
            required_name = {"state": "memory_state", "search": "memory_search"}.get(
                active_stage
            )
            required_tool = (
                cast(dict[str, Any], staged_tools[required_name])
                if required_name is not None else None
            )
            request_tools = (
                [SEMANTIC_FINISH_TOOL if semantic_maintenance else FINISH_TOOL]
                if native and final_request and maintenance_required else
                [required_tool] if required_tool is not None
                else _subject_tools(self.tools, material_view.subject_catalogue())
                if material_view is not None else list(self.tools)
            )
            terminal_tool = (semantic_finish_tool(session) if semantic_maintenance else
                             finish_tool(session)) if maintenance_required else FINISH_TOOL
            if maintenance_required:
                request_tools = [terminal_tool if tool.get("function", tool)["name"] ==
                                 "finish_turn" else tool for tool in request_tools]
            if self.decision_policy != "off":
                request_tools = _focus_tools(
                    request_tools,
                    allow_gap=(self.decision_policy == "basis" and bound_memory is not None
                               and bound_memory.decision_gap_focus),
                )
            response_format = (
                (_required_tool_response_format(
                    terminal_tool, decision_policy=self.decision_policy)
                 if final_request and maintenance_required else
                 _final_response_format(self.decision_policy) if final_request else
                 _required_tool_response_format(
                     required_tool, decision_policy=self.decision_policy)
                 if required_tool is not None else _action_response_format(
                     request_tools, maintenance=maintenance_required,
                     decision_policy=self.decision_policy))
                if self.client.config.tool_mode == "json_action" else None
            )
            receipt = self.client.chat(
                request_transcript,
                request_tools if native else None,
                tool_choice="required" if native and final_request and maintenance_required else
                ("none" if final_request else "required")
                if native and required_name is not None else
                "none" if native and final_request else None,
                response_format=response_format,
            )
            model_calls += 1
            _add_usage(usage, receipt.get("usage"),
                       first_receipt=model_calls == 1 and not resume)
            choice = receipt["choices"][0]
            message = dict(choice["message"])
            transcript.append(message)
            if choice.get("finish_reason") == "length":
                outcome: dict[str, Any] = {
                    "ok": False,
                    "error": "The previous response was truncated and no tool was executed. "
                    "Reply with one short operation or a brief final answer.",
                    "remaining_model_calls": budget - model_calls,
                }
                tool_calls = (
                    message.get("tool_calls") or []
                    if self.client.config.tool_mode == "native"
                    else []
                )
                if tool_calls:
                    for tool_call in tool_calls:
                        calls.append(
                            {
                                "name": tool_call.get("function", {}).get("name", ""),
                                "arguments": tool_call.get("function", {}).get("arguments"),
                                **outcome,
                            }
                        )
                        transcript.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": _json(outcome),
                            }
                        )
                        self._emit_call(calls[-1])
                else:
                    calls.append({"name": "", "arguments": {}, **outcome})
                    transcript.append(
                        {
                            "role": "user",
                            "content": f"json_action tool result: {_json(outcome)}"
                            if not native
                            else f"tool result: {_json(outcome)}",
                        }
                    )
                    self._emit_call(calls[-1])
                if final_request:
                    return make_result("", "incomplete")
                continue

            if self.client.config.tool_mode == "native":
                tool_calls = message.get("tool_calls") or []
                finish_calls = [call for call in tool_calls
                                if call.get("function", {}).get("name") == "finish_turn"]
                if maintenance_required and finish_calls:
                    if len(tool_calls) != 1:
                        # No sibling action executes: the finish arguments predate its result.
                        for call in tool_calls:
                            transcript.append({"role": "tool", "tool_call_id": call["id"],
                                               "content": "finish_turn must be the only call; "
                                                          "no tool in this response executed."})
                        if final_request:
                            return make_result("", "maintenance_pending")
                        continue
                    call = finish_calls[0]
                    try:
                        finish_action = _parse_arguments(call["function"].get("arguments", "{}"))
                    except (ValueError, TypeError):
                        finish_action = {}
                    transcript.append({"role": "tool", "tool_call_id": call["id"],
                                       "content": "Maintenance receipt received."})
                    if finished := finish_answer(finish_action):
                        return finished
                    continue
                if not tool_calls:
                    if active_stage != "free":
                        no_progress += 1
                        outcome = {
                            "ok": False,
                            "error": (
                                "Complete memory_state and then memory_search "
                                "before answering."
                            ),
                            "remaining_model_calls": budget - model_calls,
                        }
                        calls.append({"name": "", "arguments": {}, **outcome})
                        transcript.append({
                            "role": "user", "content": f"tool result: {_json(outcome)}",
                        })
                        self._emit_call(calls[-1])
                        if (stopped := stalled()):
                            return stopped
                        continue
                    answer = message.get("content")
                    if isinstance(answer, str):
                        if finished := finish_answer({"answer": answer}):
                            return finished
                        continue
                    raise ValueError(
                        "native assistant response has neither tool_calls nor string content"
                    )
                if final_request:
                    for tool_call in tool_calls:
                        rejected_name = tool_call.get("function", {}).get("name", "")
                        outcome = rejected_tool_call(
                            rejected_name, "Tool call rejected on the final model response.",
                        )
                        outcome["remaining_model_calls"] = 0
                        calls.append(
                            {
                                "name": tool_call.get("function", {}).get("name", ""),
                                "arguments": tool_call.get("function", {}).get("arguments"),
                                **outcome,
                            }
                        )
                        transcript.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": _json(outcome),
                            }
                        )
                        self._emit_call(calls[-1])
                    return make_result("", "incomplete")
                for tool_call in tool_calls:
                    function = tool_call.get("function", {})
                    name = function.get("name", "")
                    try:
                        arguments = _parse_arguments(function.get("arguments", "{}"))
                    except (ValueError, TypeError, ValidationError) as exc:
                        if name not in READ_ONLY_TOOLS:
                            read_cache.clear()
                        no_progress += 1
                        outcome = rejected_tool_call(name, f"Invalid tool call: {exc}")
                    else:
                        outcome = execute_tool(name, arguments)
                    outcome["remaining_model_calls"] = budget - model_calls
                    calls.append({"name": name, "arguments": function.get("arguments"), **outcome})
                    transcript.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": _json(outcome),
                        }
                    )
                    record_tool_message(outcome)
                    self._emit_call(calls[-1])
                if not final_request and (stopped := stalled()):
                    return stopped
                continue

            content = message.get("content")
            if not isinstance(content, str):
                raise ValueError("json_action assistant response must contain string content")
            invalid = "Expected {'tool': name, 'arguments': object} or {'answer': string}."
            try:
                action = json.loads(content)
            except json.JSONDecodeError as exc:
                action = None
                invalid = f"Invalid JSON-action response: {exc.msg}"
            if self.decision_policy != "off" and isinstance(action, dict):
                try:
                    assert response_format is not None
                    candidate = preflight_sidecar(
                        action, response_format["json_schema"]["schema"],
                    )
                except (ValueError, TypeError, ValidationError) as exc:
                    no_progress += 1
                    error_text = exc.message if isinstance(exc, ValidationError) else str(exc)
                    outcome = rejected_tool_call(
                        str(action.get("tool", "")),
                        "Invalid action and state proposal: " + error_text,
                    )
                    outcome["remaining_model_calls"] = budget - model_calls
                    calls.append({"name": action.get("tool", ""),
                                  "arguments": action.get("arguments"), **outcome})
                    transcript.append({"role": "user", "content":
                                       f"json_action tool result: {_json(outcome)}"})
                    self._emit_call(calls[-1])
                    if final_request:
                        return make_result("", "maintenance_pending" if maintenance_required
                                           else "incomplete")
                    if stopped := stalled():
                        return stopped
                    continue
                apply_sidecar(action, candidate)
            if (active_stage == "free" and isinstance(action, dict)
                    and isinstance(action.get("answer"), str)):
                if finished := finish_answer(action):
                    return finished
                continue
            if (maintenance_required and active_stage == "free" and isinstance(action, dict)
                    and action.get("tool") == "finish_turn"):
                finish_arguments = action.get("arguments", {})
                if not isinstance(finish_arguments, dict):
                    finish_arguments = {}
                if finished := finish_answer(finish_arguments):
                    return finished
                continue
            if final_request and isinstance(action, dict) and isinstance(action.get("tool"), str):
                outcome = rejected_tool_call(
                    action["tool"], "Tool call rejected on the final model response.",
                )
                outcome["remaining_model_calls"] = 0
                calls.append(
                    {"name": action["tool"], "arguments": action.get("arguments"), **outcome}
                )
                transcript.append(
                    {"role": "user", "content": f"json_action tool result: {_json(outcome)}"}
                )
                self._emit_call(calls[-1])
                return make_result("", "incomplete")
            if not isinstance(action, dict) or not isinstance(action.get("tool"), str):
                no_progress += 1
                outcome = {
                    "ok": False,
                    "error": invalid,
                    "remaining_model_calls": budget - model_calls,
                }
                calls.append({"name": "", "arguments": {}, **outcome})
                transcript.append(
                    {"role": "user", "content": f"json_action tool result: {_json(outcome)}"}
                )
                self._emit_call(calls[-1])
                if not final_request and (stopped := stalled()):
                    return stopped
                continue
            try:
                arguments = action.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be a JSON object")
            except (ValueError, TypeError, ValidationError) as exc:
                if action["tool"] not in READ_ONLY_TOOLS:
                    read_cache.clear()
                no_progress += 1
                outcome = rejected_tool_call(action["tool"], f"Invalid tool call: {exc}")
                arguments = cast(dict[str, Any], action.get("arguments"))
            else:
                outcome = execute_tool(action["tool"], arguments)
            outcome["remaining_model_calls"] = budget - model_calls
            calls.append({"name": action["tool"], "arguments": arguments, **outcome})
            transcript.append(
                {"role": "user", "content": f"json_action tool result: {_json(outcome)}"}
            )
            record_tool_message(outcome)
            self._emit_call(calls[-1])
            if not final_request and (stopped := stalled()):
                return stopped
        return make_result("", "budget_exhausted")

    def prime_session(self, session: HostSession, question: str) -> None:
        """Deliver compact existing memory before new input can compete in the index."""
        memory, view = self.memory, session.material_view
        if (not self.initial_context_bytes or memory is None or view is None
                or session.maintenance.get("initial_context_turn") == session.turn_id):
            return
        if session.memory is not memory:
            raise ValueError("HOST_SESSION_MEMORY_MISMATCH")
        session.refresh_visibility()
        try:
            if memory.workspace.cards or memory.retained:
                current = memory.search(query=question, limit=self.initial_context_limit,
                                        max_bytes=self.initial_context_bytes)
                signature = hashlib.sha256(_json(current).encode()).hexdigest()
                cache = session.maintenance.get("initial_context_cache", {})
                resident = next((message for message, content, _ in session.deliveries
                                 if cache.get("input_sha256") == signature
                                 and hashlib.sha256(content.encode()).hexdigest()
                                 == cache.get("message_sha256")), None)
                if resident is not None:
                    projected = json.loads(
                        resident["content"].removeprefix("Relevant current memory: ")
                    )
                else:
                    projected = view.project(current, max_bytes=self.initial_context_bytes)
                    session.append_material(projected, label="Relevant current memory")
                    session.maintenance["initial_context_cache"] = {
                        "input_sha256": signature,
                        "message_sha256": hashlib.sha256(
                            session.transcript[-1]["content"].encode()
                        ).hexdigest(),
                    }
                if self.emit:
                    self.emit({"event": "initial_memory_context", "session_id": session.session_id,
                               "turn_id": session.turn_id, "query": current.get("query"),
                               "reused_resident_message": resident is not None,
                               "max_bytes": self.initial_context_bytes, "materials": projected,
                               "bindings": {alias: asdict(binding) for alias, binding in
                                            view.visible_bindings(projected).items()}})
        finally:
            # Search updates internal seen/ranges before the Host projection exists.
            # A cache hit publishes no new receipt, so restore actual visibility too.
            session.refresh_visibility()
        session.maintenance["initial_context_turn"] = session.turn_id

    def _business_action(
        self, name: str, arguments: dict[str, Any], call_id: str, session: HostSession,
    ) -> BusinessToolResult:
        store = self.runtime_store
        if store is not None:
            assert self.memory is not None
            unresolved = [item for item in store.pending_actions()
                          if item["name"] == name and item["arguments"] == arguments]
            if unresolved:
                return BusinessToolResult(call_id, "unknown", {
                    "error": "PRIOR_EXECUTION_UNRESOLVED",
                    "prior_call_id": unresolved[0]["call_id"],
                    "notice": "The action may already have executed. Query the business state "
                              "and reconcile that call; it was not repeated.",
                })
            reservation = store.begin_action(call_id, name, arguments,
                                             memory=self.memory, session=session)
            if not reservation["may_execute"]:
                raise ValueError("BUSINESS_ACTION_ALREADY_REGISTERED")
        try:
            raw = dispatch_action(name, arguments, memory_dispatch=self.dispatch,
                                  business_tools=self.business_tools, call_id=call_id)
            assert isinstance(raw, BusinessToolResult)
            if raw.status not in {"succeeded", "failed", "unknown"}:
                raise ValueError("BUSINESS_RESULT_STATUS_INVALID")
            result = raw
        except Exception as error:
            # Once entered, an executor may have changed the world before raising.
            # A query/reconciliation is needed; never assume that retry is safe.
            result = BusinessToolResult(call_id, "unknown", {
                "error": type(error).__name__, "detail": str(error),
                "notice": "Execution outcome is unknown. Inspect the business state before "
                          "another attempt.",
            })
        if store is not None:
            assert self.memory is not None
            # Persist the raw result before source intake/projection can fail.
            store.finish_action(call_id, result, memory=self.memory, session=session)
        return result

    def _business_observation(
        self, name: str, arguments: dict[str, Any], result: BusinessToolResult, session_id: str,
    ) -> Observation:
        observation = result.observation or Observation(
            event_id=result.call_id, content=_json(result.output), role="tool",
            artifact=name, session_id=session_id, actor_ref=f"tool:{name}",
        )
        if self.maintenance_policy == "required":
            observation = replace(observation, content=_json({
                "tool": name, "call_id": result.call_id, "arguments": arguments,
                "execution_status": result.status, "output": result.output,
            }), role="tool")
        return observation

    def _recover_business_results(self, session: HostSession) -> None:
        store, memory = self.runtime_store, self.memory
        if store is None or memory is None:
            return
        delivered = session.maintenance.setdefault("delivered_actions", [])
        recovered: dict[str, dict[str, Any]] = {}
        for entry in store.actions_for_turn(session.session_id, session.turn_id):
            call_id = entry["call_id"]
            reconciliation = entry.get("reconciliation")
            delivery_id = call_id + ":reconciled" if reconciliation else call_id
            if delivery_id in delivered:
                continue
            raw = reconciliation["result"] if reconciliation else entry.get("result")
            if raw is None:
                result = BusinessToolResult(call_id, "unknown", {
                    "notice": "Interrupted after recording intent. Execution may have happened. "
                              "Do not replay; query the real business state.",
                })
            else:
                result = BusinessToolResult(
                    raw.get("call_id", call_id), raw["status"], raw["output"],
                    Observation(**raw["observation"]) if raw.get("observation") else None,
                )
            observation = self._business_observation(
                entry["name"], entry["arguments"], result, session.session_id,
            )
            if raw is None:
                observation = replace(observation, event_id=call_id + ":interrupted")
            elif reconciliation:
                observation = replace(observation, event_id=delivery_id, content=_json({
                    "tool": entry["name"], "call_id": call_id, "execution_status": result.status,
                    "output": result.output, "verification": reconciliation["evidence"],
                    "previous_outcome": "unknown",
                }))
            acquired = accept_observation(
                memory, session, observation, retention=self.observation_retention,
                max_bytes=self.observation_bytes, emit=self.emit, deliver=False,
            )
            recovered[call_id] = {"ok": result.status == "succeeded",
                                  "execution_status": result.status,
                                  "tool_call_id": call_id, "result": acquired["material"]}
            session.observations[acquired["source_ref"]] = acquired["material"]
            if raw is not None:
                delivered.append(delivery_id)
        # Resolve native assistant/tool adjacency without inventing results for
        # memory operations or actions that had no journal intent.
        answered = {message.get("tool_call_id") for message in session.transcript
                    if message.get("role") == "tool"}
        for message in list(session.transcript):
            for tool_call in message.get("tool_calls", []):
                if tool_call["id"] not in answered:
                    session.transcript.append({"role": "tool", "tool_call_id": tool_call["id"],
                        "content": "Interrupted before result delivery. The recovery observations "
                                   "below contain journaled outcomes. Inspect existing memory "
                                   "before repeating a memory write; never replay unknown actions.",
                    })
        for outcome in recovered.values():
            message = {"role": "user", "content": "Recovered business result: " + _json(outcome)}
            session.transcript.append(message)
            session.record_delivery(message, outcome["result"])
        if self.emit:
            self.emit({"event": "session_recovered", "session_id": session.session_id,
                       "turn_id": session.turn_id, "business_calls": list(recovered)})
        store.persist(memory, session)

    def _validate_tool(self, name: str, arguments: dict[str, Any]) -> None:
        if name == "memory_save" and "forget_refs" in arguments:
            raise InvalidToolCall("delete requires the trusted lifecycle executor")
        schema = _tool_schema(self.tools, name)
        if schema is None:
            raise InvalidToolCall(f"unknown tool {name!r}")
        validate(instance=arguments, schema=schema)

    def _emit_call(self, call: dict[str, Any]) -> None:
        if self.emit:
            self.emit({"event": "host_tool_call", "call": call})

    def _result(
        self,
        answer: str,
        status: str,
        calls: list[dict[str, Any]],
        usage: dict[str, int | str | None],
        started: float,
        transcript: list[dict[str, Any]],
    ) -> HostResult:
        return HostResult(
            answer=answer,
            status=status,
            calls=calls,
            usage=usage,
            elapsed_seconds=time.monotonic() - started,
            transcript=copy.deepcopy(transcript),
        )


def _tool_schema(tools: Sequence[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for tool in tools:
        function = tool.get("function", tool)
        if function.get("name") == name:
            return cast(dict[str, Any], function.get("parameters", {"type": "object"}))
    return None


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        arguments = raw
    elif isinstance(raw, str):
        arguments = json.loads(raw)
    else:
        raise ValueError("tool arguments must be a JSON object")
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must decode to a JSON object")
    return arguments


def _json(value: Any, *, canonical: bool = False) -> str:
    """Preserve model-facing schema/material order; canonicalize only internal keys."""
    return json.dumps(value, ensure_ascii=False, sort_keys=canonical)


def _material_token_breakdown(
    result: dict[str, Any], capacity: HostCapacity | None,
) -> dict[str, int | bool | None]:
    """Diagnostic counts of the delivered JSON; tokenizer boundaries prevent additivity."""
    if capacity is None:
        return {
            "delivered_total_tokens": None,
            "body_tokens": None,
            "reference_status_tokens": None,
            "associated_material_tokens": None,
            "token_sections_additive": False,
        }

    bodies: list[str] = []
    associated: list[Any] = []

    def collect(value: Any, *, excerpt: bool = False) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item, excerpt=excerpt)
        elif isinstance(value, dict):
            if excerpt or value.get("kind") in {"source", "interpretation"}:
                bodies.extend(
                    value[key] for key in ("content", "text")
                    if isinstance(value.get(key), str)
                )
            for key, item in value.items():
                if key == "associated_materials":
                    if isinstance(item, list):
                        associated.extend(item)
                    else:
                        associated.append(item)
                elif key in {"excerpts", "delivered_spans"}:
                    collect(item, excerpt=True)
                elif key not in {"content", "text"}:
                    collect(item)

    def metadata(value: Any) -> Any:
        if isinstance(value, list):
            return [metadata(item) for item in value]
        if isinstance(value, dict):
            return {
                key: metadata(item) for key, item in value.items()
                if key not in {"content", "text", "associated_materials"}
            }
        return value

    collect(result)
    return {
        "delivered_total_tokens": capacity.text_tokens(_json(result)),
        "body_tokens": sum(capacity.text_tokens(body) for body in bodies),
        "reference_status_tokens": capacity.text_tokens(_json(metadata(result))),
        "associated_material_tokens": (
            capacity.text_tokens(_json(associated)) if associated else 0
        ),
        "token_sections_additive": False,
    }


def _empty_usage() -> dict[str, int | str | None]:
    return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}


def _add_usage(target: dict[str, int | str | None], usage: Any, *, first_receipt: bool) -> None:
    for key in target:
        value = usage.get(key) if isinstance(usage, Mapping) else None
        if type(value) is not int or (not first_receipt and target[key] is None):
            target[key] = None
        else:
            current = target[key]
            target[key] = value + (current if isinstance(current, int) else 0)
