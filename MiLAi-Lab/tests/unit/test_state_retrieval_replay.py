"""Different real bindings from one recorded STATE before, without a model."""
import copy
import json
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore
from test_intent_retrieval import memory_at
from test_state_retrieval_capture import setup_capture

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.memory_control import FixedMemoryPolicy
from milai_lab.runners.state_retrieval_replay import replay_state_retrieval


def capture_known_call(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "live.sqlite")) as store:
        service, hook, _, _, _ = setup_capture(store, tmp_path)
        service.capture_tool("separate-receipt", "execution", "cancel_booking",
                             "Cancellation execution completed for booking B1.", None)
        service.capture_tool("later-receipt", "status", "lookup_booking",
                             "Cancellation status for booking B1 remains cancelled.", None)
        hook.memory.control_policy = FixedMemoryPolicy(1)
        hook.retrieve({"query": "Cancellation requires approval"})
        hook.retrieve({"query": "Cancellation approval execution booking B1"})
    calls = sorted((tmp_path / "retrieval-snapshots").iterdir(),
                   key=lambda p: read_json(p / "call.json")["captured_epoch"])
    call = calls[-1]
    row = read_json(call / "call.json")
    assert len(row["request"]["task_context"]["known_evidence_refs"]) == 1
    return call


def build(service, record):
    memory = memory_at(service, control_delivery_selection=True, control_record=record)
    memory.control_policy = FixedMemoryPolicy(1)
    return memory


def read_actions(row):
    return [a for a in row["initial_actions"] if a["kind"] == "READ"
            and not a["parameters"].get("observe_only")
            and not a["parameters"].get("expand_context")
            and not a["parameters"].get("history_directory")
            and "observed_source" not in a["parameters"]
            and "source_observation_cursor" not in a["parameters"]]


def test_two_read_bindings_share_actual_known_evidence_and_deliver_their_own_material(tmp_path):
    call = capture_known_call(tmp_path)
    candidates = [call, *sorted((call / "steps").iterdir())]
    captured = next(p for p in candidates if len(read_actions(read_json(p / "call.json"))) >= 2)
    row = read_json(captured / "call.json")
    actions = read_actions(row)[:2]
    original = {p: p.read_bytes() for p in call.rglob("*") if p.is_file()}
    packets = []
    for index, action in enumerate(actions):
        output = tmp_path / f"branch-{index}"
        result = replay_state_retrieval(captured, output, source_version="test",
            build_memory=build, intervention={"first_action": action, "continuation_steps": 0})
        assert result["frozen_request_and_allowance_equal"]
        assert result["frozen_initial_observation_and_actions_equal"]
        assert result["prefix_operations_reexecuted"] == 0
        assert result["domain_tools_executed"] == 0
        events = [json.loads(line) for line in (output / "trace.jsonl")
                  .read_text().splitlines()]
        selected = next(e for e in events if e.get("phase") == "decision_output")
        assert selected["before"] == row["initial_observation"]
        assert selected["before"]["task"]["known_evidence"]
        assert next(a for a in selected["actions"] if a["id"] == selected["selected"]) == action
        assert read_json(output / "runtime/domain.json") == read_json(
            captured / "before/domain.json")
        assert result["packet"]["evidence"]
        packets.append(result["packet"]["evidence"])
    assert packets[0] != packets[1]
    assert {p: p.read_bytes() for p in original} == original


@pytest.mark.parametrize("cut", ["initial", "post_read"])
def test_normal_continuation_restores_exact_call_or_post_read_before(tmp_path, cut):
    call = capture_known_call(tmp_path)
    captured = call if cut == "initial" else next(p for p in (call / "steps").iterdir()
        if read_json(p / "control.json")["operations"]["observed"])
    row = read_json(captured / "call.json")
    result = replay_state_retrieval(captured, tmp_path / "replayed", source_version="test",
                                    build_memory=build)
    assert result["packet"] == row["original_result"]
    assert result["frozen_initial_observation_and_actions_equal"]


def test_changed_binding_rejected_and_policy_failure_retained_without_retry(tmp_path):
    captured = capture_known_call(tmp_path)
    row = read_json(captured / "call.json")
    action = copy.deepcopy(row["initial_actions"][0])
    action["parameters"]["query"] = "not the captured binding"
    with pytest.raises(ValueError, match="not a captured complete binding"):
        replay_state_retrieval(captured, tmp_path / "changed", source_version="test",
            build_memory=build, intervention={"first_action": action, "continuation_steps": 0})
    assert read_json(tmp_path / "changed/replay.json")["status"] == "FAILED"
    assert not (tmp_path / "changed/runtime").exists()
    attempts = []

    class Fails:
        def choose(self, state, actions):
            attempts.append(state)
            raise RuntimeError("Original branch prediction failed")

    def fails(service, record):
        memory = build(service, record)
        memory.control_policy = Fails()
        return memory

    with pytest.raises(RuntimeError, match="Original branch prediction failed"):
        replay_state_retrieval(captured, tmp_path / "failed", source_version="test",
                               build_memory=fails)
    failed = read_json(tmp_path / "failed/replay.json")
    assert failed["status"] == "FAILED" and len(attempts) == 1
    assert failed["frozen_initial_observation_and_actions_equal"]
    assert "packet" not in failed and not (tmp_path / "failed/packet.json").exists()


def test_cli_uses_original_ledger_and_generation_gate_without_http(tmp_path, monkeypatch):
    import run_state_retrieval_branch as cli
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from milai_lab.harness.http_ownership import PROFILE
    from milai_lab.providers.contextual_vllm import VLLMConfig
    from milai_lab.runners.state_memory import build_retrieval
    from milai_lab.runners.state_retrieval_capture import capture_state_retrieval

    budget_path = tmp_path / "original-budget.json"
    budget = RunBudget(RunLimits(), budget_path)
    host = asdict(VLLMConfig(base_url="http://example.test/v1", model="scripted"))
    settings = {"host": host, "capacity": {}, "max_calls_per_message": 12,
        "ordinary_material_tokens": 10000, "additional_reads": 12,
        "source_top_k": 16, "semantic_top_k": 16, "memory_control": {"reads": 1},
        "budget_path": str(budget_path), "http_ownership_profile": PROFILE,
        "http_ownership_domain": {"deployment_id": "unit-test", "clients": [host]}}
    budget.record_compute("original", {"cpu_seconds": 2})
    with SqliteStore.from_conn_string(str(tmp_path / "live.sqlite")) as store:
        service, hook, domain, _, _ = setup_capture(store, tmp_path)
        hook.memory = build_retrieval(service, len, settings, "fixed_context", budget,
                                      lambda _: None)
        from milai_lab.runners.state_bench_adapter import learning_envelope

        hook.memory.return_envelope = learning_envelope
        capture_state_retrieval(hook, tmp_path, domain_snapshot=lambda: domain,
            context=lambda: {"settings": settings, "generation_calls_before": 4})
        hook.retrieve({"query": "Cancellation approval"})
    captured, = (tmp_path / "retrieval-snapshots").iterdir()
    monkeypatch.setattr(cli, "HostCapacity", lambda _: SimpleNamespace(text_tokens=len))

    def no_http(*_, **__):
        raise AssertionError("No HTTP is needed for this branch")

    monkeypatch.setattr(httpx.Client, "send", no_http)
    recipe = tmp_path / "recipe.json"
    write_json(recipe, {"policy": {"policy": "fixed_context", "reads": 1}})
    monkeypatch.setattr("sys.argv", ["branch", str(captured), str(recipe), str(tmp_path / "branch"),
        "--source-version", "test", "--compute-phase", "state-unit-branch"])
    cli.main()
    run = read_json(tmp_path / "branch/run.json")
    assert run["status"] == "COMPLETED"
    assert run["generation_calls_after"] == run["original_generation_calls"] == 4
    assert run["budget_path"] == str(budget_path)
    assert run["budget_before"]["generation_requests"] == run["budget_after"]["generation_requests"]
    ledger = read_json(budget_path)
    assert ledger["compute"]["original"]["cpu_seconds"] == 2
    assert ledger["compute"]["state-unit-branch"]["runs"] == 1
    assert not (tmp_path / "branch/budget.json").exists()
