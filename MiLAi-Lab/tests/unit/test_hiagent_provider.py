"""Real accounting/client code with MockTransport; no network or containers."""

import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest

from milai_lab.methods.adaptive_memory import ADAPTIVE_OUTPUT_SCHEMA, PROFILES
from milai_lab.methods.hiagent import HiAgentError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v02_local_provider import read_events
from v0213_provider import MODEL
from workspace_task_provider import Provider

TOOLS = Path(__file__).resolve().parents[2] / "tools"


class Context:
    n_input_tokens = 0
    n_output_tokens = 0
    metadata = None

    def model_dump(self):
        return vars(self)


def load_adapter(monkeypatch):
    # Harbor is an optional external dependency; replace only its inherited shell
    # boundary. _solve, the lifecycle and the entire HTTP accounting code are real.
    base = ModuleType("workspace_harbor_agent")
    class StubBase:
        def __init__(self, *, max_calls=64):
            self.max_calls = max_calls

    base.WorkspaceAgent = StubBase
    monkeypatch.setitem(sys.modules, "workspace_harbor_agent", base)
    spec = importlib.util.spec_from_file_location(
        "hiagent_adapter_test", TOOLS / "hiagent_harbor_agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_mock(
    tmp_path, monkeypatch, failure=None, max_calls=64, method="HIAGENT", handoff=None, batch_size=1,
):
    module = load_adapter(monkeypatch)
    sent, effects = [], []

    def actor(subgoal=None, action="exec", **arguments):
        return json.dumps({"subgoal": subgoal, "action": action, "arguments": arguments})

    values = [
        actor("Inspect", command="FIRST_EVIDENCE"),
        actor("Change", command="SECOND_EVIDENCE"),
        "The first command produced an observation.",
        actor(action="retrieve", segments=[1]),
        actor(action="final", text="Submitted for native verification"),
    ]
    if method in {"EVIDENCE_0", "EVIDENCE_1", "INCREMENTAL"}:
        values = [values[0], "First observed result.", values[1], "Updated evidence scope.",
                  values[3], values[4]]
    if method == "CONTROL_0":
        record = json.dumps({"record": "Observed", "question": "Next?", "intent": "Check",
                             "focus_segments": [], "focus_refs": [], "branches": []})
        values = [record, values[0], record, values[1], record, values[3], values[4],
                  record, values[4]]
    if method in {"WORKSPACE_SIMPLE", "MILAI_RWC"}:
        def control(kind="ACT", refs=()):
            return json.dumps({"workspace_update": None,
                "frame": {"question": "Next", "intent": "Inspect", "selected_refs": []},
                "dispatch": {"kind": kind, "refs": list(refs), "delivery": None}})
        values = [control(), values[0], control(), values[1], values[2],
                  control("RECALL", ["H001"]), control(), values[4], control("DELIVER")]
        if batch_size > 1:
            values = [control(), actor("Inspect", command="first"), actor(command="second"),
                      actor(action="final", text="Current result"), control("DELIVER")]
    if method in PROFILES:
        values = [actor("Inspect", command="first"),
                  actor(action="maintain", reason="Revise after feedback", refs=["H001"]),
                  json.dumps({"workspace_update": {"working_note": "Retained current evidence"}}),
                  actor(action="final", text="Current result"),
                  json.dumps({"dispatch": {"kind": "DELIVER"}})]
    outputs = iter(values)

    def transport(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        sent.append(body)
        summary = "response_format" not in body
        if failure == "unknown" and summary:
            return httpx.Response(500, json={"error": "usage unknown"})
        if failure == "budget":
            output = actor("Only" if len(sent) == 1 else None, command="continue")
        else:
            output = next(outputs)
        if failure == "missing_visible" and summary:
            output = None
        return httpx.Response(200, json={
            "choices": [{"message": {"content": output}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}})

    monkeypatch.setattr(module, "Provider", lambda root, **kwargs: Provider(
        root, transport=httpx.MockTransport(transport), **kwargs))
    instance = module.HiAgentAgent(
        hiagent_max_calls=max_calls, control_handoff_after=handoff,
        control_feedback_batch_size=batch_size,
    )
    instance.run_root = tmp_path
    instance.logs_dir = tmp_path / "trials/demo/agent"
    instance.stop_requested = threading.Event()
    instance.task_timeout, instance.wave_cap, instance.arm = 900, 64, method
    instance.counts = SimpleNamespace(wire=lambda _: 100, text=lambda _: 100)
    context = Context()
    error = None
    try:
        instance._solve("Task with constraints", lambda *a: effects.append(a) or {
            "stdout": a[0], "return_code": 0}, context)
    except (httpx.HTTPStatusError, ValueError, HiAgentError) as exc:
        error = exc
    result = json.loads((tmp_path / "host/demo/terminal.json").read_text())
    return result, sent, effects, error


def test_actor_and_maintenance_use_real_shared_ledger_and_restore_details(tmp_path, monkeypatch):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch)
    assert error is None
    assert len(sent) == 5 and len(effects) == 2
    assert result["call_attempts"] == {"actor": 4, "summary": 1}
    assert result["n_input_tokens"] == 500 and result["n_output_tokens"] == 50
    assert result["metadata"]["wave_accounting"]["raw_tokens"] == 550
    assert result["metadata"]["wave_accounting"]["pending"] == []
    assert "response_format" not in sent[2]
    assert sent[3]["response_format"] == {"type": "json_object"}
    assert "FIRST_EVIDENCE" not in json.dumps(sent[3]["messages"])
    assert "FIRST_EVIDENCE" in json.dumps(sent[4]["messages"])
    rows = read_events(tmp_path / "host/demo/method-events.jsonl")
    classified = [r for r in rows if r["event"] == "PROVIDER_ATTEMPT_END"]
    assert [r["kind"] for r in classified] == ["actor", "actor", "summary", "actor", "actor"]
    assert all(len(r["request_ids"]) == 1 for r in classified)


@pytest.mark.parametrize("method,counts,total", [
    ("H_ONCE", {"actor": 4, "summary": 1}, 5),
    ("EVIDENCE_0", {"actor": 4, "summary": 0, "maintenance": 2}, 6),
    ("EVIDENCE_1", {"actor": 4, "summary": 0, "maintenance": 2}, 6),
    ("INCREMENTAL", {"actor": 4, "summary": 0, "maintenance": 2}, 6),
])
def test_new_methods_share_provider_and_account_auxiliary_http(
    tmp_path, monkeypatch, method, counts, total,
):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch, method=method)
    assert error is None and len(effects) == 2
    assert len(sent) == total and result["call_attempts"] == counts
    assert result["metadata"]["wave_accounting"]["raw_tokens"] == total * 110
    http = read_events(tmp_path / "provider/http-events.jsonl")
    starts = [r for r in http if r["event"] == "HTTP_STARTED"]
    returns = [r for r in http if r["event"] == "HTTP_RETURNED"]
    assert len(starts) == len(returns) == 1 + 2 * total
    assert sum(r["path"] == "/tokenize" for r in starts) == total
    assert sum(r["path"] == "/v1/chat/completions" for r in starts) == total
    assert {r["http_id"] for r in starts} == {r["http_id"] for r in returns}
    config = json.loads((tmp_path / "host/demo/configuration.json").read_text())
    assert config["arm"] == method and config["max_total_model_calls"] == 64
    if method != "H_ONCE":
        assert config["summary_policy"] == (
            TOOLS.parent / f"configs/policies/evidence/{method.lower()}.txt").read_text()
        assert "maintenance" in config["call_budget_includes"]


def test_unknown_summary_request_stops_with_reservation_and_no_retry(tmp_path, monkeypatch):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch, "unknown")
    assert isinstance(error, httpx.HTTPStatusError)
    assert len(sent) == 3 and len(effects) == 2
    state = result["metadata"]["wave_accounting"]
    assert state["requests"] == 3 and state["raw_tokens"] == 220
    assert len(state["pending"]) == 1
    assert result["n_input_tokens"] == 200 and result["n_output_tokens"] == 20


def test_settled_usage_remains_counted_if_visible_summary_missing(tmp_path, monkeypatch):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch, "missing_visible")
    assert str(error) == "MISSING_VISIBLE_OUTPUT"
    assert len(sent) == 3 and len(effects) == 2
    assert result["metadata"]["wave_accounting"]["raw_tokens"] == 330
    assert result["metadata"]["wave_accounting"]["pending"] == []
    assert result["n_input_tokens"] == 300 and result["n_output_tokens"] == 30


def test_known_budget_exhaustion_returns_for_native_verification(tmp_path, monkeypatch):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch, "budget")
    assert error is None  # Not an agent exception that suppresses native verification.
    assert len(sent) == len(effects) == 64
    assert result["metadata"]["stop_reason"] == "TOTAL_MODEL_CALL_LIMIT"
    assert result["metadata"]["wave_accounting"]["raw_tokens"] == 64 * 110


def test_repair_allocation_can_reduce_actor_and_summary_shared_budget(tmp_path, monkeypatch):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch, max_calls=3)
    assert error is None
    assert len(sent) == 3 and len(effects) == 2
    assert result["call_attempts"] == {"actor": 2, "summary": 1}
    assert result["metadata"]["stop_reason"] == "TOTAL_MODEL_CALL_LIMIT"
    assert result["metadata"]["wave_accounting"]["raw_tokens"] == 330
    config = json.loads((tmp_path / "host/demo/configuration.json").read_text())
    assert config["max_total_model_calls"] == 3


def test_control_json_maintenance_and_fresh_host_share_one_provider_budget(tmp_path, monkeypatch):
    result, sent, effects, error = run_mock(
        tmp_path, monkeypatch, method="CONTROL_0", handoff=2)
    assert error is None and len(sent) == 9 and len(effects) == 2
    assert all(body["response_format"] == {"type": "json_object"} for body in sent)
    assert result["call_attempts"] == {"actor": 5, "summary": 0, "maintenance": 4}
    assert result["metadata"]["control_handoff_completed"]
    assert result["metadata"]["wave_accounting"]["raw_tokens"] == 990
    assert result["n_input_tokens"] == 900 and result["n_output_tokens"] == 90
    assert (tmp_path / "host/demo/handoff.json").is_file()
    rows = read_events(tmp_path / "host/demo/method-events.jsonl")
    assert sum(row["event"] == "HOST_RESTORED" for row in rows) == 1


@pytest.mark.parametrize("method", ["WORKSPACE_SIMPLE", "MILAI_RWC"])
def test_reversible_loop_uses_real_provider_caps_recall_and_handoff(tmp_path, monkeypatch, method):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch, method=method, handoff=2)
    assert error is None and len(effects) == 2
    assert len(sent) == 9
    assert result["call_attempts"] == {"actor": 3, "summary": 1, "maintenance": 5}
    assert [body["max_tokens"] for body in sent] == [
        2048, 4096, 2048, 4096, 1024, 2048, 2048, 4096, 2048]
    accounting = result["metadata"]["wave_accounting"]
    assert accounting["raw_tokens"] == 990 and not accounting["pending"]
    assert result["metadata"]["control_handoff_completed"]
    rows = read_events(tmp_path / "host/demo/method-events.jsonl")
    assert sum(row["event"] == "HOST_RESTORED" for row in rows) == 1
    assert sum(row["event"] == "SOURCE_RECALLED" for row in rows) == 1
    assert sum(row["event"] == "PUBLIC_CHECKPOINT_SAVED" for row in rows) == 0


@pytest.mark.parametrize("method", ["WORKSPACE_SIMPLE", "MILAI_RWC"])
def test_batched_adapter_records_configuration_and_delivery_status(tmp_path, monkeypatch, method):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch, method=method, batch_size=3)
    assert error is None and len(sent) == 5 and len(effects) == 2
    assert result["call_attempts"] == {"actor": 3, "summary": 0, "maintenance": 2}
    assert result["metadata"]["delivery_status"] == "REVIEWED"
    config = json.loads((tmp_path / "host/demo/configuration.json").read_text())
    assert config["control_feedback_batch_size"] == 3
    assert result["metadata"]["wave_accounting"]["raw_tokens"] == 550


@pytest.mark.parametrize("cap", [0, 65, True, 3.5])
def test_adapter_rejects_invalid_call_budget_before_provider(monkeypatch, cap):
    module = load_adapter(monkeypatch)
    with pytest.raises(ValueError, match="INVALID_HIAGENT_CALL_BUDGET"):
        module.HiAgentAgent(hiagent_max_calls=cap)


@pytest.mark.parametrize("failure", ["unknown", "missing_visible"])
def test_failed_summary_never_publishes_a_completed_segment(tmp_path, monkeypatch, failure):
    run_mock(tmp_path, monkeypatch, failure)
    memory = json.loads((tmp_path / "host/demo/memory.json").read_text())
    assert memory["halted"] and memory["segments"][0]["summary"] is None
    assert memory["segments"][0]["pairs"] and memory["segments"][1]["pairs"]


@pytest.mark.parametrize("method", sorted(PROFILES))
def test_adaptive_provider_schema_modes_caps_usage_and_handoff(tmp_path, monkeypatch, method):
    result, sent, effects, error = run_mock(tmp_path, monkeypatch, method=method, handoff=1)
    assert error is None and len(effects) == 1 and len(sent) == 5
    assert result["call_attempts"] == {"actor": 3, "maintenance": 2}
    assert result["metadata"]["control_handoff_completed"]
    assert result["metadata"]["delivery_status"] == "REVIEWED"
    maintenance = [b for b in sent if b["response_format"]["type"] == "json_schema"]
    assert len(maintenance) == 2
    assert all(b["response_format"]["json_schema"]["schema"] == ADAPTIVE_OUTPUT_SCHEMA
               and b["max_tokens"] == 2048 for b in maintenance)
    assert [json.loads(b["messages"][-1]["content"])["mode"] for b in maintenance] == [
        "REVISE", "REVIEW",
    ]
    memory = json.loads((tmp_path / "host/demo/memory.json").read_text())
    assert memory["usage"]["input_tokens"] == result["n_input_tokens"] == 500
    assert memory["usage"]["output_tokens"] == result["n_output_tokens"] == 50
    assert not result["metadata"]["wave_accounting"]["pending"]
