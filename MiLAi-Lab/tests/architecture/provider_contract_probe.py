"""Synthetic provider contract probes; no real services or asset downloads."""

from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import tempfile
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch


def encode(value: Any) -> Any:
    def fallback(item: Any) -> Any:
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, (set, frozenset)):
            return sorted(item)
        return {"opaque_type": type(item).__name__}

    return json.loads(json.dumps(value, ensure_ascii=False, default=fallback))


def outcome(action: Any) -> dict[str, Any]:
    try:
        returned = action()
        if hasattr(returned, "generations"):
            return {
                "messages": [row.message.model_dump(mode="json") for row in returned.generations]
            }
        return {"returned": encode(returned)}
    except Exception as error:
        return {"exception": type(error).__name__, "message": str(error)}


def fixed_inputs(stack: ExitStack) -> None:
    ids = itertools.count(1)
    stack.enter_context(
        patch.object(uuid, "uuid4", lambda: uuid.UUID(f"00000000-0000-4000-8000-{next(ids):012d}"))
    )
    stack.enter_context(patch.object(time, "monotonic", lambda: 1000.0))
    stack.enter_context(patch.object(time, "perf_counter", lambda: 1000.0))
    stack.enter_context(patch.object(time, "perf_counter_ns", lambda: 1000))
    stack.enter_context(patch.object(time, "process_time_ns", lambda: 1000))


def manual_capture(model_type: Any) -> dict[str, Any]:
    import httpx
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from milai_lab.methods.freshness_projection.projection import ProjectedRequest
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

    tool = {
        "type": "function",
        "function": {
            "name": "record",
            "description": "Record a synthetic value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    }
    memory_tool = {
        "type": "function",
        "function": {
            "name": "manage_memory",
            "description": "Manage memory.",
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string"}, "content": {"type": "string"}},
            },
        },
    }
    search_tool = {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search memory.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
    }
    ordinary = [SystemMessage(content="Original system."), HumanMessage(content="Current request.")]
    continuation = [
        *ordinary,
        AIMessage(
            content="A proposal.",
            tool_calls=[
                {"name": "record", "args": {"value": "one"}, "id": "prior-1"},
                {"name": "record", "args": {"value": "two"}, "id": "prior-2"},
            ],
        ),
        ToolMessage(content="actual one", tool_call_id="prior-1", name="record"),
        ToolMessage(content="actual two", tool_call_id="prior-2", name="record"),
    ]
    events: list[Any] = []

    class Observer:
        @contextmanager
        def request_scope(self, *args: Any) -> Any:
            events.append({"stage": "scope_enter", "args": encode(args)})
            try:
                yield
            finally:
                events.append({"stage": "scope_exit"})

    class M1:
        def __init__(self, fail: bool = False) -> None:
            self.fail = fail

        def prompt_context(self, messages: Any) -> str:
            events.append({"stage": "m1_context", "messages": encode(messages)})
            return "Synthetic live M1 context."

        def request_id(self, index: int) -> str:
            return "m1:" + str(index)

        def record_error(self, *args: Any) -> None:
            events.append({"stage": "m1_error", "args": encode(args)})

        def commit(self, *args: Any) -> None:
            events.append({"stage": "m1_commit", "args": encode(args)})
            if self.fail:
                raise RuntimeError("synthetic M1 commit failure")

    class ODR:
        def __init__(self, arm: str, reject: bool = False) -> None:
            self.arm, self.rejecting = arm, reject

        def project(self, messages: Any) -> tuple[str, str]:
            events.append({"stage": "odr_project", "messages": encode(messages)})
            return (
                "Synthetic freshness." if self.arm == "freshness_only" else "",
                "Synthetic evidence e1.",
            )

        def request_id(self, index: int) -> str:
            return "odr:" + str(index)

        def reject(self, *args: Any) -> None:
            events.append({"stage": "odr_reject", "args": encode(args)})

        def accept(self, *args: Any) -> None:
            events.append({"stage": "odr_accept", "args": encode(args)})
            if self.rejecting:
                from milai_lab.methods.on_demand_reconstruction.schema import ReconstructionError

                raise ReconstructionError("SYNTHETIC_ODR_REJECT")

    class Projection:
        def __init__(self, stage: str, items: list[Any], rebases: list[Any]) -> None:
            self.stage, self.items, self.rebases = stage, items, rebases

        def project(self, messages: Any, *args: Any) -> Any:
            events.append({"stage": "projection_project", "args": encode(args)})
            return ProjectedRequest(messages, {}, self.items, [], self.rebases)

        def record_delivery(self, *args: Any) -> tuple[list[Any], int]:
            events.append({"stage": "projection_delivery", "args": encode(args)})
            return [{"snapshot": "exact delivered evidence"}], 2

        def record_output(self, *args: Any) -> None:
            events.append({"stage": "projection_output", "args": encode(args)})

    class View:
        def project(self, messages: Any, graph: Any, *args: Any) -> Any:
            events.append({"stage": "view_project", "args": encode(args)})
            return messages, graph

        def record_delivery(self, receipt: Any) -> None:
            events.append({"stage": "view_delivery", "id": receipt.get("id")})

    cases = [
        ("json_plain", {}, {"answer": "Final."}, ordinary, [tool], {}),
        ("json_empty_history", {}, {"answer": "Final."}, [], [tool], {}),
        ("json_zero_tools", {}, {"answer": "Final."}, ordinary, [], {}),
        (
            "json_multiple_calls",
            {},
            {
                "calls": [
                    {"name": "record", "arguments": {"value": "one"}},
                    {"name": "record", "arguments": {"value": "two"}},
                ]
            },
            ordinary,
            [tool],
            {},
        ),
        ("json_continuation", {}, {"answer": "Continued."}, continuation, [tool], {}),
        (
            "native_plain",
            {},
            {"role": "assistant", "content": "Native final."},
            ordinary,
            [tool],
            {},
        ),
        (
            "native_tools",
            {},
            {
                "role": "assistant",
                "content": "Proposal.",
                "tool_calls": [
                    {
                        "id": "native-1",
                        "type": "function",
                        "function": {"name": "record", "arguments": '{"value":"one"}'},
                    },
                    {
                        "id": "native-2",
                        "type": "function",
                        "function": {"name": "record", "arguments": '{"value":"two"}'},
                    },
                ],
            },
            ordinary,
            [tool],
            {},
        ),
        (
            "native_continuation",
            {},
            {"role": "assistant", "content": "Continued."},
            continuation,
            [tool],
            {"tool_choice": "auto"},
        ),
        (
            "m1_null",
            {"m1": M1()},
            {"decision_delta": None, "answer": "Null delta."},
            ordinary,
            [tool],
            {},
        ),
        ("m1_invalid_envelope", {"m1": M1()}, {"answer": "Missing delta."}, ordinary, [tool], {}),
        (
            "m1_commit_failure",
            {"m1": M1(True)},
            {"decision_delta": None, "answer": "Commit fails."},
            ordinary,
            [tool],
            {},
        ),
        (
            "odr_freshness",
            {"odr": ODR("freshness_only")},
            {"answer": "Fresh."},
            ordinary,
            [tool],
            {},
        ),
        (
            "odr_missing_envelope",
            {"odr": ODR("odr")},
            {"answer": "Missing reconstruction."},
            ordinary,
            [tool],
            {},
        ),
        (
            "odr_null",
            {"odr": ODR("odr")},
            {"reconstruction": None, "answer": "No reconstruction."},
            ordinary,
            [tool],
            {},
        ),
        (
            "odr_reject",
            {"odr": ODR("odr", True)},
            {"reconstruction": None, "answer": "Reject."},
            ordinary,
            [tool],
            {},
        ),
        (
            "m1_then_odr",
            {"m1": M1(), "odr": ODR("odr")},
            {"decision_delta": None, "reconstruction": None, "answer": "Both."},
            ordinary,
            [tool, memory_tool, search_tool],
            {},
        ),
        (
            "projection_v21_empty",
            {"projection": Projection("v21", [], [])},
            {"answer": "Empty."},
            ordinary,
            [tool],
            {},
        ),
        (
            "projection_v21_items",
            {"projection": Projection("v21", [{"status": "CURRENT"}], [])},
            {"answer": "Items."},
            ordinary,
            [tool],
            {},
        ),
        (
            "projection_v21_rebase",
            {"projection": Projection("v21", [], [{"response_id": "old"}])},
            {"answer": "Rebased."},
            ordinary,
            [tool],
            {},
        ),
        (
            "projection_v20_empty",
            {"projection": Projection("v20", [], [])},
            {"answer": "Authority."},
            ordinary,
            [tool],
            {},
        ),
        (
            "delivery_before_schema_error",
            {
                "projection": Projection("v21", [{"status": "CURRENT"}], []),
                "request_view": View(),
                "observer": Observer(),
            },
            {"invalid": True},
            ordinary,
            [tool],
            {},
        ),
    ]
    for extension in ("m1", "odr", "projection", "request_view", "C"):
        cases.append(
            (
                "native_unsupported_" + extension,
                {"memory_protocol": "C"} if extension == "C" else {extension: object()},
                {},
                ordinary,
                [tool],
                {},
            )
        )
    cases.append(
        ("native_protocol_required", {}, {}, ordinary, [tool], {"tool_choice": "required"})
    )
    result = {}
    with tempfile.TemporaryDirectory(prefix="milai-s5-manual-") as temporary:
        for name, options, action, messages, tools, kwargs in cases:
            events.clear()
            root = Path(temporary) / name
            root.mkdir()
            budget = RunBudget(RunLimits(), root / "budget.json")
            wires = []
            native = name.startswith("native")

            def respond(request: Any, wires=wires, action=action, native=native) -> Any:
                raw = request.read()
                wires.append({"raw": raw.decode(), "ordered_dict": json.loads(raw)})
                events.append({"stage": "mock_http"})
                content = action if native else {"role": "assistant", "content": json.dumps(action)}
                return httpx.Response(
                    200,
                    json={
                        "id": "synthetic-generation",
                        "model": "mock",
                        "choices": [
                            {
                                "finish_reason": "tool_calls"
                                if native and content.get("tool_calls")
                                else "stop",
                                "message": content,
                            }
                        ],
                        "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
                    },
                )

            with ExitStack() as stack:
                fixed_inputs(stack)
                client = stack.enter_context(
                    VLLMClient(
                        VLLMConfig(
                            base_url="http://mock/v1/",
                            model="mock",
                            tool_mode="native" if native else "json_action",
                        ),
                        budget=budget,
                        emit=lambda event: events.append({"stage": "emit", "event": encode(event)}),
                        transport=httpx.MockTransport(respond),
                    )
                )
                model = model_type(client=client, capacity_path=root / "capacity.json", **options)
                model.begin_public_message("synthetic:message")
                observed = outcome(
                    lambda model=model, messages=messages, tools=tools, kwargs=kwargs: (
                        model._generate(messages, tools=tools, **kwargs)
                    )
                )
                result[name] = {
                    "input_messages": [item.model_dump(mode="json") for item in messages],
                    "tools": tools,
                    "output": observed,
                    "wires": wires,
                    "ordered_events": copy.deepcopy(events),
                    "calls_in_message": model.calls_in_message,
                    "budget": budget.state,
                    "capacity_file": (root / "capacity.json").read_text()
                    if (root / "capacity.json").exists()
                    else None,
                }
        return json.loads(json.dumps(result, ensure_ascii=False).replace(temporary, "<TMP>"))


def edges_capture(model_type, source_lab):
    import httpx
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from milai_lab.methods.reasoning_bank import normalized
    from milai_lab.providers.contextual_capacity import CapacityExceeded
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

    tool = {
        "type": "function",
        "function": {
            "name": "manage_memory",
            "description": "Manage synthetic memory.",
            "parameters": {"type": "object", "properties": {"action": {"type": "string"}}},
        },
    }
    current = {
        "run_id": "run",
        "arm_id": "C",
        "user_id": "alice",
        "episode_id": "episode",
        "message_key": "thread:1",
    }
    ordinary = [SystemMessage(content="Original system."), HumanMessage(content="Current request.")]
    current_receipt = [
        *ordinary,
        AIMessage(
            content="",
            response_metadata={"memory_turn": current},
            tool_calls=[{"name": "manage_memory", "args": {"action": "create"}, "id": "memory-1"}],
        ),
        ToolMessage(
            content=json.dumps({"ok": True, "status": "created", "id": "synthetic-record"}),
            name="manage_memory",
            tool_call_id="memory-1",
        ),
    ]
    foreign = [
        *ordinary,
        AIMessage(
            content="",
            response_metadata={"memory_turn": {**current, "user_id": "bob"}},
            tool_calls=[{"name": "manage_memory", "args": {"action": "create"}, "id": "foreign-1"}],
        ),
        ToolMessage(
            content=json.dumps({"ok": True, "status": "created", "id": "foreign-record"}),
            name="manage_memory",
            tool_call_id="foreign-1",
        ),
    ]
    basic = {
        "id": "generation-edge",
        "model": "mock",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps({"answer": "Final."})},
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
    }
    result, events = {}, []

    class Observer:
        @contextmanager
        def request_scope(self, *args):
            events.append({"stage": "scope_enter", "args": encode(args)})
            try:
                yield
            finally:
                events.append({"stage": "scope_exit"})

    class RejectingCapacity:
        enable_thinking = False

        def check(self, *_args):
            raise CapacityExceeded({"synthetic": "capacity-rejected"})

    cases = []
    for arm in ("A", "B", "C"):
        for scope_name, messages, refs in (
            ("current", current_receipt, ["memory-1"]),
            ("foreign", foreign, ["foreign-1"]),
        ):
            reply = copy.deepcopy(basic)
            action = (
                {
                    "answer": "Declared.",
                    "memory_result": {"status": "committed", "receipt_refs": refs},
                }
                if arm == "C"
                else {"answer": "Declared."}
            )
            reply["choices"][0]["message"]["content"] = json.dumps(action)
            cases.append(
                (
                    arm + "_" + scope_name,
                    messages,
                    {"memory_protocol": arm, "memory_turn": current},
                    {},
                    reply,
                    {},
                )
            )
    for name, changes in (
        ("http_failure", {"status": 503}),
        ("connection_failure", {"connect_error": True}),
        ("http_non_json", {"raw_body": "{invalid"}),
        ("budget_admission", {"budget_requests": 0}),
        ("capacity_admission", {"capacity": True}),
        ("public_capacity_full", {"max_calls": 0}),
        ("public_capacity_missing_key", {"missing_key": True}),
        ("stop_rejected", {"stop": ["END"]}),
    ):
        cases.append((name, ordinary, {"observer": Observer()}, changes, basic, {}))
    for name, mutate in (
        ("missing_choices", lambda r: r.pop("choices")),
        ("truncated", lambda r: r["choices"][0].update(finish_reason="length")),
        ("invalid_role", lambda r: r["choices"][0]["message"].update(role="tool")),
        ("malformed_content", lambda r: r["choices"][0]["message"].update(content="{bad")),
        ("unknown_usage", lambda r: r.pop("usage")),
        (
            "boolean_usage",
            lambda r: r.update(
                usage={"prompt_tokens": True, "completion_tokens": False, "total_tokens": True}
            ),
        ),
        ("missing_id", lambda r: r.pop("id")),
        (
            "C_recognizable_invalid",
            lambda r: r["choices"][0]["message"].update(
                content=json.dumps({"answer": "Missing result."})
            ),
        ),
    ):
        reply = copy.deepcopy(basic)
        mutate(reply)
        options = {"observer": Observer()}
        if name.startswith("C_"):
            options.update(memory_protocol="C", memory_turn=current)
        cases.append((name, ordinary, options, {}, reply, {}))
    with tempfile.TemporaryDirectory(prefix="milai-s5-edges-") as temporary:
        for name, messages, options, controls, reply, kwargs in cases:
            events.clear()
            root = Path(temporary) / name
            root.mkdir()
            budget = RunBudget(
                RunLimits(generation_requests=controls.get("budget_requests", 160)),
                root / "budget.json",
            )
            wires = []

            def respond(request, wires=wires, controls=controls, reply=reply):
                wires.append(
                    {"raw": request.read().decode(), "ordered_dict": json.loads(request.read())}
                )
                events.append({"stage": "mock_http"})
                if controls.get("connect_error"):
                    raise httpx.ConnectError("Synthetic connection failure.", request=request)
                if controls.get("raw_body"):
                    return httpx.Response(200, content=controls["raw_body"])
                return httpx.Response(controls.get("status", 200), json=reply)

            with ExitStack() as stack:
                fixed_inputs(stack)
                client = stack.enter_context(
                    VLLMClient(
                        VLLMConfig(base_url="http://mock/v1/", model="mock"),
                        budget=budget,
                        emit=lambda event: events.append({"stage": "emit", "event": encode(event)}),
                        capacity=RejectingCapacity() if controls.get("capacity") else None,
                        transport=httpx.MockTransport(respond),
                    )
                )
                model = model_type(
                    client=client,
                    capacity_path=root / "capacity.json",
                    max_calls_per_message=controls.get("max_calls", 12),
                )
                for key, value in options.items():
                    setattr(model, key, value)
                if not controls.get("missing_key"):
                    model.begin_public_message("thread:1")
                generated = outcome(
                    lambda model=model, messages=messages, controls=controls, kwargs=kwargs: (
                        model._generate(messages, tools=[tool], stop=controls.get("stop"), **kwargs)
                    )
                )
                result[name] = {
                    "messages": [row.model_dump(mode="json") for row in messages],
                    "tools": [tool],
                    "output": generated,
                    "wires": wires,
                    "ordered_events": copy.deepcopy(events),
                    "calls_in_message": model.calls_in_message,
                    "budget": budget.state,
                    "capacity_file": (root / "capacity.json").read_text()
                    if (root / "capacity.json").exists()
                    else None,
                }
        # Mutable state is set after construction and changes between delivered requests.
        events.clear()
        root = Path(temporary) / "live_fields"
        root.mkdir()
        replies = iter(
            [
                {"answer": "A."},
                {"answer": "B."},
                {"answer": "C.", "memory_result": {"status": "no_change", "receipt_refs": []}},
            ]
        )
        wires = []

        def live_response(request):
            wires.append(
                {"raw": request.read().decode(), "ordered_dict": json.loads(request.read())}
            )
            reply = copy.deepcopy(basic)
            reply["choices"][0]["message"]["content"] = json.dumps(next(replies))
            return httpx.Response(200, json=reply)

        with ExitStack() as stack:
            fixed_inputs(stack)
            client = stack.enter_context(
                VLLMClient(
                    VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(live_response),
                )
            )
            model = model_type(client=client, capacity_path=root / "capacity.json")
            model.begin_public_message("thread:1")
            outputs = []
            for arm in ("A", "B", "C"):
                model.memory_protocol, model.memory_turn = arm, {**current, "arm_id": arm}
                model.research_profile = "live-" + arm
                model.observer = Observer()
                outputs.append(outcome(lambda: model._generate(ordinary, tools=[tool])))
            result["live_fields"] = {
                "wires": wires,
                "outputs": outputs,
                "ordered_events": copy.deepcopy(events),
                "calls_in_message": model.calls_in_message,
                "final_state": {
                    "memory_protocol": model.memory_protocol,
                    "memory_turn": model.memory_turn,
                    "research_profile": model.research_profile,
                },
            }
        serialized = json.dumps(result, ensure_ascii=False).replace(temporary, "<TMP>")
    maths = {}
    for name, vector, dimension in [
        ("unit", [3.0, 4.0], 2),
        ("negative", [-3.0, 4.0], 2),
        ("dimension", [1.0], 2),
        ("nan", [float("nan")], 1),
        ("infinity", [float("inf")], 1),
        ("zero", [0.0, 0.0], 2),
        ("overflow", [1e300], 1),
        ("underflow", [1e-300], 1),
    ]:
        maths[name] = outcome(
            lambda vector=vector, dimension=dimension: normalized(vector, dimension)
        )
    spec = importlib.util.spec_from_file_location(
        "s5_test_embeddings", source_lab / "tests/unit/test_contextual_embeddings.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    embeddings = {}
    for name, texts in [
        ("short", ["alpha beta"]),
        ("long", ["alpha beta gamma delta epsilon zeta theta"]),
        ("mixed", ["alpha beta", "alpha beta gamma delta epsilon zeta theta"]),
        ("empty", []),
    ]:
        client = helper.FakeClient()
        tokenizer = helper._tokenizer()
        output = helper.embed_texts_windowed(
            client, texts, "test-model", tokenizer=tokenizer, max_tokens=5, batch_size=2
        )
        embeddings[name] = {
            "output": output,
            "requests": client.requests,
            "truncation": tokenizer.truncation,
            "padding": tokenizer.padding,
        }
    return {
        "provider": json.loads(serialized),
        "normalized": maths,
        "windowed_embeddings": embeddings,
    }


SELECTED = {
    "test_langmem_foundation.py": [
        "test_json_action_executes_every_upstream_call_in_order",
        "test_bad_json_action_never_executes_tool",
    ],
    "test_persistent_memory.py": [
        "test_boundary_roles_reach_actual_wire_after_call_serialization_and_reset",
        "test_boundary_host_twelve_call_capacity_does_not_replay_or_add_control",
        "test_same_graph_correction_uses_visible_refs_preserves_originals_and_capacity",
        "test_existing_record_read_nochange_never_forces_create_or_reads_foreign_owner",
        "test_partial_operations_keep_real_commits_errors_and_no_semantic_certification",
        "test_nochange_contradiction_gets_only_one_entry_and_invalid_second_final_is_preserved",
        "test_semantically_wrong_nochange_is_not_auto_corrected_and_cap_is_not_extended",
        "test_business_partial_effect_is_never_replayed_by_memory_correction",
        "test_unknown_business_side_effect_propagates_without_correction_or_replay",
    ],
    "test_milai_m1_v18.py": [
        "test_real_graph_changed_recheck_and_completed_replay",
        "test_pending_protocol_or_unresolved_business_action",
    ],
    "test_milai_odr.py": [
        "test_b1_freshness_only_wire_parity_without_stale",
        "test_imported_search_result_is_unknown_without_freshness_block",
        "test_real_graph_exact_delivery_restart_and_replay",
        "test_invalid_stale_reconstruction_has_zero_business_effect",
    ],
    "test_freshness_projection.py": [
        "test_mixed_projection_actual_material_and_completed_replay",
        "test_rebase_binds_equal_text_to_response_identity_across_restart",
        "test_v21_authority_only_when_actual_memory_or_derived_risk_is_projected",
    ],
}


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 29, tzinfo=tz)


class Recorder:
    def __init__(self, model_type, source_root, temporary):
        self.model_type, self.source_root, self.temporary = model_type, source_root, temporary
        self.cases = {}
        self.current = None
        self.stack = None

    def event(self, stage, **values):
        if self.current is not None:
            self.current["events"].append(encode({"stage": stage, **values}))

    def wrap_method(self, owner, name, prefix):
        original = getattr(owner, name)

        def wrapped(instance, *args, **kwargs):
            recorded_args = args
            if name == "__call__":
                request = args[0]
                recorded_args = (
                    {
                        "tool_call": request.tool_call,
                        "state": request.state,
                        "runtime_config": {
                            "configurable": {
                                "thread_id": request.runtime.config["configurable"]["thread_id"]
                            }
                        },
                        "executor_present": callable(args[1]),
                    },
                )
            self.event(prefix + ".enter", args=recorded_args, kwargs=kwargs)
            try:
                result = original(instance, *args, **kwargs)
            except Exception as error:
                self.event(prefix + ".error", exception=type(error).__name__, message=str(error))
                raise
            self.event(prefix + ".return", returned=result)
            return result

        self.stack.enter_context(patch.object(owner, name, wrapped))

    def pytest_runtest_setup(self, item):
        import time

        import httpx
        import langgraph.store.memory as memory_store

        import milai_lab.methods.memory_boundaries as boundaries
        from milai_lab.application.journal import BusinessActionJournal
        from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
        from milai_lab.memory.revision_store import RevisionSidecar
        from milai_lab.methods.freshness_projection.controller import ProjectionController
        from milai_lab.methods.milai_m1.controller import M1Controller
        from milai_lab.methods.milai_m1.state_store import DecisionBasisStore
        from milai_lab.methods.on_demand_reconstruction.controller import ODRController
        from milai_lab.providers.contextual_vllm import VLLMClient

        node = "tests/unit/" + item.nodeid.split("/unit/")[-1]
        assert node not in self.cases
        self.current = {"events": [], "reports": [], "artifacts": {}}
        self.cases[node] = self.current
        self.stack = ExitStack()
        fixed_inputs(self.stack)
        self.stack.enter_context(
            patch.object(time, "strftime", lambda *_args: "2026-09-29T00:00:00Z")
        )
        self.stack.enter_context(patch.object(memory_store, "datetime", FixedDatetime))
        self.stack.enter_context(patch.object(boundaries, "datetime", FixedDatetime))

        original = self.model_type._generate

        def generated(model, messages, *args, **kwargs):
            self.event(
                "generate.enter",
                messages=messages,
                args=args,
                kwargs=kwargs,
                calls=model.calls_in_message,
                active_key=model.active_message_key,
            )
            try:
                result = original(model, messages, *args, **kwargs)
            except Exception as error:
                self.event(
                    "generate.error",
                    exception=type(error).__name__,
                    message=str(error),
                    calls=model.calls_in_message,
                )
                raise
            self.event(
                "generate.return",
                messages=[row.message for row in result.generations],
                calls=model.calls_in_message,
            )
            return result

        self.stack.enter_context(patch.object(self.model_type, "_generate", generated))

        original_transport = httpx.MockTransport.handle_request

        def transport(owner, request):
            self.event(
                "mock_http.request",
                url=str(request.url),
                raw=request.read().decode(),
                ordered_dict=json.loads(request.read()),
            )
            result = original_transport(owner, request)
            self.event("mock_http.response", status=result.status_code, raw=result.read().decode())
            return result

        self.stack.enter_context(patch.object(httpx.MockTransport, "handle_request", transport))

        original_client = VLLMClient.__init__

        def client(owner, *args, **kwargs):
            original_client(owner, *args, **kwargs)
            old_emit = owner.emit

            def emit(event):
                self.event("provider.emit", event=event)
                if old_emit:
                    old_emit(event)

            owner.emit = emit

        self.stack.enter_context(patch.object(VLLMClient, "__init__", client))

        original_scope = ProvenanceObserver.request_scope

        @contextmanager
        def scope(owner, *args, **kwargs):
            self.event("delivery_scope.enter", args=args, kwargs=kwargs)
            try:
                with original_scope(owner, *args, **kwargs):
                    yield
            finally:
                self.event("delivery_scope.exit")

        self.stack.enter_context(patch.object(ProvenanceObserver, "request_scope", scope))

        for owner, names in (
            (M1Controller, ("prompt_context", "record_error", "commit")),
            (ODRController, ("project", "reject", "accept")),
            (ProjectionController, ("project", "record_delivery", "record_output")),
            (boundaries.MemoryBoundaryView, ("project", "fit_final_request", "record_delivery")),
            (BusinessActionJournal, ("__call__",)),
        ):
            for name in names:
                self.wrap_method(owner, name, owner.__name__ + "." + name)

        for owner in (RevisionSidecar, DecisionBasisStore):
            original_init = owner.__init__
            original_close = owner.close

            def initialized(instance, *args, _original=original_init, **kwargs):
                _original(instance, *args, **kwargs)
                instance.conn.create_function("datetime", 1, lambda _value: "2026-09-29 00:00:00")

            def closed(instance, _original=original_close):
                tables = [
                    row[0]
                    for row in instance.conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    )
                ]
                snapshot = {
                    name: [
                        dict(row)
                        for row in instance.conn.execute(
                            'SELECT * FROM "' + name + '" ORDER BY rowid'  # noqa: S608 -- SQLite-owned table names
                        )
                    ]
                    for name in tables
                }
                self.event(type(instance).__name__ + ".close", database=snapshot)
                return _original(instance)

            self.stack.enter_context(patch.object(owner, "__init__", initialized))
            self.stack.enter_context(patch.object(owner, "close", closed))

    def pytest_runtest_logreport(self, report):
        self.current["reports"].append({"when": report.when, "outcome": report.outcome})
        if report.failed:
            self.current["reports"][-1]["failure"] = str(report.longrepr)

    def pytest_runtest_teardown(self, item):
        tmp_path = item.funcargs.get("tmp_path")
        if tmp_path:
            for path in sorted(tmp_path.rglob("*")):
                if path.is_file() and path.suffix in {".json", ".jsonl"}:
                    self.current["artifacts"][str(path.relative_to(tmp_path))] = path.read_text()
        self.stack.close()
