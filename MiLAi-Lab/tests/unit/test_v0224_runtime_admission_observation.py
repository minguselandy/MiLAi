"""Synthetic whole-runtime spans and original business delegation; no Session run."""

import ast
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0222_presentation_references as original
import v0224_runtime_admission_observation as observer


@pytest.fixture
def synthetic(monkeypatch, tmp_path):
    state = {"clock": 0, "calls": 0, "host_checks": 0}
    resolved = {"stage": "P4", "scope": "scope", "initial_state_sha256": "initial", "actions": [{}]}
    provider = SimpleNamespace(rows=[{}, {}, {}])
    world = SimpleNamespace(snapshot=lambda: {}, ledger=lambda: [])

    class Host:
        def __init__(self):
            self.rows = []

        def validate_runtime(self):
            self.callback()
            state["clock"] += 2_000_000_000
            state["host_checks"] += 1

        def run(self, provider, *, deadline):
            assert deadline == 160.0
            for _ in range(7):
                self.validate_runtime()
            return {"status": "SESSION_FINISHED_NOT_TASK_VERDICT"}

    host = Host()

    def create(world, directory, spec, callback):
        host.callback = callback
        callback()
        return host

    def clock():
        state["calls"] += 1
        state["clock"] += 1
        return state["clock"]

    for module in (observer, original):
        monkeypatch.setattr(module, "resolve_p4_spec", lambda *args: (resolved, {}))
        monkeypatch.setattr(module, "World", SimpleNamespace(create=lambda *args: world))
        monkeypatch.setattr(module, "digest", lambda value: "initial")
        monkeypatch.setattr(module, "session", create)
        monkeypatch.setattr(module, "ReferenceProvider", lambda *args: provider)
        monkeypatch.setattr(module, "effects", lambda *args: {"status": "PASS"})
        monkeypatch.setattr(module, "save", lambda *args: None)
    monkeypatch.setattr(observer.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(observer.time, "monotonic_ns", clock)
    return tmp_path, resolved, state, host


def test_S_contains_host_checks_not_just_callback_and_restores_instance(synthetic):
    path, spec, state, host = synthetic
    report = {}
    rows, _ = observer.prepare_p4_observed(
        path, spec, {}, lambda: None, mode="S", observation=report
    )
    assert len(rows) == 3 and report["callback_counts"] == {"attempted": 9, "returned": 9}
    assert report["setup_callbacks"] == {"attempted": 2, "returned": 2}
    assert len(report["runtime_intervals"]) == 7 and state["host_checks"] == 7
    assert report["runtime_union_ns"] > 14_000_000_000
    assert state["calls"] == 16  # 14 fullruntime endpoints plus2completeSession endpoints
    assert "validate_runtime" not in vars(host)


def test_U_calls_original_presentation_prepare_and_has_zero_observation_clocks(synthetic):
    path, spec, state, _host = synthetic
    assert observer.original_prepare_p4 is original.prepare_p4
    report = {}
    observer.prepare_p4_observed(path, spec, {}, lambda: None, mode="U", observation=report)
    assert state["calls"] == 0 and report["runtime_intervals"] == []
    assert report["session_interval"] is None and report["runtime_union_ns"] is None
    assert report["status"] == "STRICT_U_UNTIMED"
    assert report["callback_counts"] == {"attempted": 9, "returned": 9}


def test_no_strong18_wall_refusal(synthetic):
    path, spec, state, host = synthetic
    original_method = host.validate_runtime

    def slower():
        original_method()
        state["clock"] += 1_000_000_000

    host.validate_runtime = slower
    report = {}
    observer.prepare_p4_observed(path, spec, {}, lambda: None, mode="S", observation=report)
    assert report["runtime_union_ns"] > 18_000_000_000
    assert report["status"] == "COMPLETE_RUNTIME_INTERVALS"
    assert host.validate_runtime is slower


def test_original_run_exception_and_clock_failure_preserve_primary(synthetic, monkeypatch):
    path, spec, _state, host = synthetic
    primary = RuntimeError("original-run")

    def fail(*args, **kwargs):
        raise primary

    host.run = fail
    ticks = iter([1])
    monkeypatch.setattr(observer.time, "monotonic_ns", lambda: next(ticks))
    report = {}
    with pytest.raises(RuntimeError) as caught:
        observer.prepare_p4_observed(path, spec, {}, lambda: None, mode="S", observation=report)
    assert caught.value is primary
    assert report["status"] == "FAILED_NOT_MEASUREMENT_QUALIFIED"
    assert "validate_runtime" not in vars(host)
    assert any("SECONDARY_SESSION_OBSERVATION" in note for note in primary.__notes__)


def test_clock_failure_never_replaces_completed_business_with_qualified_timing(
    synthetic, monkeypatch
):
    path, spec, state, _host = synthetic

    def fail():
        raise RuntimeError("clock")

    monkeypatch.setattr(observer.time, "monotonic_ns", fail)
    report = {}
    with pytest.raises(ValueError, match="INVALID_RUNTIME_OBSERVATION"):
        observer.prepare_p4_observed(path, spec, {}, lambda: None, mode="S", observation=report)
    assert state["host_checks"] == 7 and report["errors"]
    assert report["runtime_union_ns"] is None


def test_callback_failure_U_has_counts_but_no_clock(synthetic):
    path, spec, state, _host = synthetic
    primary = RuntimeError("callback")

    def fail():
        raise primary

    report = {}
    with pytest.raises(RuntimeError) as caught:
        observer.prepare_p4_observed(path, spec, {}, fail, mode="U", observation=report)
    assert caught.value is primary and state["calls"] == 0
    assert report["callback_counts"] == {"attempted": 1, "returned": 0}


@pytest.mark.parametrize("change", ["overlap", "missing", "callback", "outside"])
def test_invalid_span_coverage_refuses(synthetic, change):
    path, spec, _state, _host = synthetic
    report = {}
    observer.prepare_p4_observed(path, spec, {}, lambda: None, mode="S", observation=report)
    if change == "overlap":
        report["runtime_intervals"][1]["start_ns"] = report["runtime_intervals"][0]["start_ns"]
    elif change == "missing":
        report["runtime_intervals"].pop()
    elif change == "callback":
        report["runtime_intervals"][0]["callback_returned_delta"] = 0
    else:
        report["runtime_intervals"][-1]["end_ns"] = report["session_interval"]["end_ns"] + 1
    with pytest.raises(ValueError):
        observer._validate_observation(report, 3)


def test_original_business_statements_preserved():
    old = ast.parse(inspect.getsource(original.prepare_p4)).body[0]
    new = ast.parse(inspect.getsource(observer._prepare_s)).body[0]
    old_nodes = [ast.dump(node) for node in old.body[1:]]
    candidates = [ast.dump(node) for node in new.body]
    run_call = next(
        node
        for node in old.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "result" for target in node.targets)
    )
    assert ast.dump(run_call) in [ast.dump(node) for node in ast.walk(new)]
    remaining = [node for node in old_nodes if node != ast.dump(run_call)]
    positions = [candidates.index(node) for node in remaining]
    assert positions == sorted(positions)


def test_runtime_primary_survives_collector_failure_and_instance_restore(synthetic):
    path, spec, _state, host = synthetic
    primary = RuntimeError("runtime-primary")
    report = {}

    class BrokenCollector(list):
        def append(self, value):
            raise RuntimeError("collector-failure")

    original_run = host.run

    def run(*args, **kwargs):
        report["runtime_intervals"] = BrokenCollector()
        return original_run(*args, **kwargs)

    host.run = run
    count = [0]

    def callback():
        count[0] += 1
        if count[0] == 3:
            raise primary

    with pytest.raises(RuntimeError) as raised:
        observer.prepare_p4_observed(path, spec, {}, callback, mode="S", observation=report)
    assert raised.value is primary
    assert "validate_runtime" not in vars(host)
    assert any("SECONDARY_RUNTIME_OBSERVATION" in note for note in primary.__notes__)
    assert report["status"] == "FAILED_NOT_MEASUREMENT_QUALIFIED"
