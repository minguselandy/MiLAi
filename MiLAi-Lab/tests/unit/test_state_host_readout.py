"""Real STATE sandbox and captured HTTP wires; scripted transport is not model evidence."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore
from test_intent_retrieval import memory_at

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, Trace
from milai_lab.memory.functional_state import canonical
from milai_lab.memory.service import MemoryService
from milai_lab.methods.memory_control import FixedMemoryPolicy
from milai_lab.providers.chat_bridge import IncompleteChatResponse, VLLMChatModel
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.state_bench_adapter import StateMemoryHook, make_state_agent
from milai_lab.runners.state_host_readout import (
    prepare_state_readout,
    run_state_readout,
    state_readout_request,
)
from milai_lab.runners.state_retrieval_capture import capture_state_retrieval
from milai_lab.runners.state_retrieval_replay import replay_state_retrieval


def collect(tmp_path, native=False, fail_post=False):
    sdk = pytest.importorskip("state_bench.agents.base")
    from state_bench.domain import get_domain_config
    from state_bench.domains.travel.schemas import EnvironmentData, HotelInventoryItem, User
    from state_bench.orchestrator import _run_harness_executed_agent_turn

    original = tmp_path / "original"
    original.mkdir()
    now = "2026-06-15T10:00:00"
    domain = get_domain_config("travel")
    data = EnvironmentData(flights=[], bookings=[], users=[User("u1", "Alice", "a@example.test")],
        hotel_inventory=[HotelInventoryItem("H1", "Hotel", "DEN", "2026-07-01",
                                           "2026-07-02", "standard", 100, 100)])
    environment = domain.environment_class(data, now)
    requests = []
    calls = [{"name": "book_hotel", "arguments": {"user_id": "u1", "hotel_id": "H1"}},
             {"name": "retrieve_learnings", "arguments": {"query": "Cancellation"}},
             {"name": "retrieve_learnings", "arguments": {"query": "Cancellation"}}]
    fail_readout = []

    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert "HIDDEN_EVALUATOR" not in json.dumps(payload)
        if len(requests) == 1:
            message = ({"role": "assistant", "content": "", "tool_calls": [
                {"id": f"original-{i}", "type": "function", "function": {
                    "name": call["name"], "arguments": json.dumps(call["arguments"])}}
                for i, call in enumerate(calls)]} if native else
                {"role": "assistant", "content": json.dumps({"calls": calls})})
            finish = "tool_calls" if native else "stop"
        else:
            answer = "ORIGINAL_FINAL_ANSWER" if len(requests) == 2 else "BRANCH_FINAL_ANSWER"
            message = {"role": "assistant", "content": answer if native else
                       json.dumps({"answer": answer})}
            finish = "length" if fail_readout or (fail_post and len(requests) == 2) else "stop"
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    trace = Trace(original / "trace.jsonl", "state-unit-readout")
    budget = RunBudget(RunLimits(), original / "budget.json")
    client = VLLMClient(VLLMConfig(base_url="http://example.test/v1", model="scripted",
        tool_mode="native" if native else "json_action"), budget=budget, emit=trace,
        transport=httpx.MockTransport(transport))
    model = VLLMChatModel(client=client, max_calls_per_message=12)
    public = {}
    with SqliteStore.from_conn_string(str(original / "memory.sqlite")) as store:
        service = MemoryService(store, ("state-readout", "alice"), "alice", original / "lock",
                                functional_contract="functional_v1")
        service.capture_user("history", "report", "Cancellation requires approval.")
        memory = memory_at(service, control_delivery_selection=True, control_record=trace)
        hook = StateMemoryHook(memory, session="task", now=now, domain="travel", user_id="u1",
                               config_version="test", record=trace)
        capture_state_retrieval(hook, original, domain_snapshot=environment.get_full_snapshot,
            context=lambda: {"host_frame": public, "trace_path": str(trace.path),
                "settings": {"host": {"tool_mode": client.config.tool_mode}},
                "generation_calls_before": model.calls_in_message})

        def observed(frame):
            public.clear()
            public.update(frame, memory_calls_before=hook.calls)

        runtime = sdk.AgentRuntimeContext(task_id="HIDDEN_EVALUATOR", user_id="u1", domain="travel",
            now=now, task_summary="HIDDEN_EVALUATOR",
            state_requirements=[{"HIDDEN_EVALUATOR": True}])
        agent = make_state_agent(model, hook, runtime, observe_host=observed)
        def operation():
            return _run_harness_executed_agent_turn(agent=agent,
                system_prompt="Public business policy",
                conversation_full=[{"role": "user", "content": "Book H1 and recall cancellation."}],
                domain_tools=domain.tool_schemas, domain_tool_handlers=environment.tool_handlers)
        if fail_post:
            with pytest.raises(IncompleteChatResponse):
                operation()
        else:
            operation()
    write_json(original / "run.json", {
        "status": "FAILED" if fail_post else "COMPLETED_RESEARCH_TRAJECTORY"})
    captures = sorted((original / "retrieval-snapshots").iterdir(),
                      key=lambda p: read_json(p / "call.json")["retrieval_ordinal"])
    assert len(environment.hotels) == 1 and len(captures) == 2
    return captures, client, model, budget, requests, fail_readout, environment


def branch(captured, output):
    def build(service, record):
        memory = memory_at(service, control_delivery_selection=True, control_record=record)
        memory.control_policy = FixedMemoryPolicy(0)
        return memory

    return replay_state_retrieval(captured, output, source_version="test", build_memory=build)


@pytest.mark.parametrize("native", [False, True])
def test_actual_sdk_batch_disambiguates_identical_queries_and_substitutes_only_one_receipt(
    tmp_path, native,
):
    captures, client, model, budget, requests, _, environment = collect(tmp_path, native)
    try:
        frames = [prepare_state_readout(p) for p in captures]
        assert [f["call_id"] for f in frames] == ["state-1-1", "state-1-2"]
        assert all(f["status"] == "READY" and f["request"] == requests[1] for f in frames)
        assert all(f["batch_call_ids"] == ["state-1-0", "state-1-1", "state-1-2"] for f in frames)
        assert "ORIGINAL_FINAL_ANSWER" not in canonical(frames)
        step = next((captures[0] / "steps").iterdir())
        assert prepare_state_readout(step)["request"] == frames[0]["request"]
        originals = {p: p.read_bytes() for p in captures[0].rglob("*") if p.is_file()}
        result = branch(captures[0], tmp_path / "branch")
        assert result["packet"]["evidence"] == []
        frame_before = copy.deepcopy(frames[0])
        wire = state_readout_request(frames[0], result)
        position = frames[0]["target_message_index"]
        assert wire["messages"][:position] == requests[1]["messages"][:position]
        assert wire["messages"][position + 1:] == requests[1]["messages"][position + 1:]
        assert json.loads(wire["messages"][position]["content"]) == result["envelope"]
        assert frames[0] == frame_before
        domain_before = environment.get_full_snapshot()
        before = copy.deepcopy(budget.state)
        model.begin_public_message("turn-1", checkpoint_calls=1)
        report = run_state_readout(frames[0], result, tmp_path / "readout", host=model,
                                   source_version="test")
        assert report["status"] == "COMPLETED" and report["answer"] == "BRANCH_FINAL_ANSWER"
        assert report["actual_http_attempts"] == 1 and len(requests) == 3
        assert report["generation_calls_before"] == 1 and report["generation_calls_after"] == 2
        assert budget.state["generation_requests"] == before["generation_requests"] + 1
        assert budget.state["generation"]["known_tokens"] == (
            before["generation"]["known_tokens"] + 15)
        assert environment.get_full_snapshot() == domain_before
        assert {p: p.read_bytes() for p in originals} == originals
    finally:
        client.close()


def test_original_length_failure_retains_input_and_new_failure_is_not_retried(tmp_path):
    captures, client, model, budget, requests, fail_readout, _ = collect(tmp_path, fail_post=True)
    try:
        frame = prepare_state_readout(captures[0])
        assert frame["status"] == "READY" and frame["original_task_status"] == "FAILED"
        result = branch(captures[0], tmp_path / "branch")
        fail_readout.append(True)
        with pytest.raises(IncompleteChatResponse):
            run_state_readout(frame, result, tmp_path / "readout", host=model,
                              source_version="test")
        report = read_json(tmp_path / "readout/readout.json")
        assert report["status"] == "FAILED" and report["actual_http_attempts"] == 1
        assert len(requests) == 3 and "answer" not in report
        assert budget.state["generation"]["unknown_usage"] == 0
    finally:
        client.close()


def test_missing_frame_or_prefix_stays_unavailable_and_changed_prefix_rejects(tmp_path):
    captures, client, model, _, requests, _, _ = collect(tmp_path)
    try:
        captured = captures[0]
        row = read_json(captured / "call.json")
        frame = prepare_state_readout(captured)
        changed = copy.deepcopy(row)
        changed["host_frame"]["host_request_generated"] = False
        write_json(captured / "call.json", changed)
        no_origin = prepare_state_readout(captured)
        assert no_origin["status"] == "NO_HOST_REQUEST_ORIGIN"
        skipped = run_state_readout(no_origin, {}, tmp_path / "no-readout", host=model,
                                    source_version="test")
        assert skipped["status"] == "NOT_EXECUTED" and len(requests) == 2
        write_json(captured / "call.json", row)
        prefix_path = captured / "before/provider-trace-prefix.jsonl"
        prefix = prefix_path.read_bytes()
        prefix_path.unlink()
        assert prepare_state_readout(captured)["status"] == "NO_CAPTURED_TRACE_PREFIX"
        prefix_path.write_bytes(prefix)
        trace = Path(row["trace_path"])
        full = trace.read_bytes()
        trace.write_bytes(prefix)
        assert prepare_state_readout(captured)["status"] == "NO_POST_TOOL_HOST_INPUT"
        trace.write_bytes(b"X" + full[1:])
        with pytest.raises(ValueError, match="trace prefix changed"):
            prepare_state_readout(captured)
        trace.write_bytes(full)
        result = branch(captured, tmp_path / "branch")
        result["captured_call"] = str(captures[1])
        with pytest.raises(ValueError, match="exact capture"):
            state_readout_request(frame, result)
    finally:
        client.close()


def test_same_frame_budget_and_capacity_rejections_never_dispatch_or_retry(tmp_path):
    captures, client, model, budget, requests, _, _ = collect(tmp_path)
    try:
        frame = prepare_state_readout(captures[0])
        result = branch(captures[0], tmp_path / "branch")
        model.max_calls_per_message = model.calls_in_message
        with pytest.raises(ValueError, match="PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"):
            run_state_readout(frame, result, tmp_path / "budget-rejected", host=model,
                              source_version="test")
        assert len(requests) == 2
        assert read_json(tmp_path / "budget-rejected/readout.json")["actual_http_attempts"] == 0
        model.max_calls_per_message = 12

        class Full:
            def check(self, *args, **kwargs):
                raise CapacityExceeded({"context_tokens": 1, "total_reserved_tokens": 2})

        client.capacity = Full()
        before = budget.state["generation_requests"]
        with pytest.raises(CapacityExceeded):
            run_state_readout(frame, result, tmp_path / "capacity-rejected", host=model,
                              source_version="test")
        rejected = read_json(tmp_path / "capacity-rejected/readout.json")
        assert rejected["actual_http_attempts"] == 0 and "answer" not in rejected
        assert rejected["capacity_rejection"]["context_tokens"] == 1
        assert len(requests) == 2 and budget.state["generation_requests"] == before
    finally:
        client.close()


@pytest.mark.parametrize("change", ["sibling_receipt", "binding"])
def test_changed_post_tool_batch_is_rejected_before_readout(tmp_path, change):
    captures, client, _, _, requests, _, _ = collect(tmp_path)
    try:
        captured = captures[0]
        call = read_json(captured / "call.json")
        trace = Path(call["trace_path"])
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        event = next(e for e in events if e.get("event") == "vllm_response"
                     and any(m["role"] == "tool" for m in e["request"]["messages"]))
        messages = event["request"]["messages"]
        if change == "sibling_receipt":
            messages.remove(next(m for m in messages if m.get("tool_call_id") == "state-1-0"))
        else:
            assistant = next(m for m in reversed(messages) if m["role"] == "assistant")
            response = json.loads(assistant["content"])
            response["calls"][0]["arguments"]["hotel_id"] = "different-object"
            assistant["content"] = json.dumps(response)
        # Keep the literal captured prefix; change only the later actual-wire event.
        prefix = (captured / "before/provider-trace-prefix.jsonl").read_bytes()
        original = trace.read_bytes()
        suffix = [json.loads(line) for line in original[len(prefix):].splitlines()]
        for index, row in enumerate(suffix):
            if row.get("event") == "vllm_response" and any(
                    m["role"] == "tool" for m in row["request"]["messages"]):
                suffix[index] = event
                break
        trace.write_bytes(prefix + b"".join((json.dumps(row) + "\n").encode() for row in suffix))
        with pytest.raises(ValueError, match=r"batch|BATCH|bindings"):
            prepare_state_readout(captured)
        assert len(requests) == 2
    finally:
        client.close()
