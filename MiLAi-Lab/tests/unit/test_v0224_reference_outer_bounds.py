"""Deterministic synthetic clocks only; no reference fixture or timing run."""

import ast
import inspect
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import v0222_presentation_references as original
import v0224_reference_outer_bounds as bounded


@pytest.fixture
def synthetic(monkeypatch, tmp_path):
    events = []
    resolved = {"scope": "synthetic", "initial_state_sha256": "initial", "actions": [{}]}
    provider = SimpleNamespace(rows=[{}, {}, {}])

    def run(provider, *, deadline):
        events.append(("run", deadline))
        return {"status": "SESSION_FINISHED_NOT_TASK_VERDICT"}

    host = SimpleNamespace(run=run, rows=[])
    world = SimpleNamespace(snapshot=lambda: {}, ledger=lambda: [])
    monkeypatch.setattr(bounded, "resolve_p4_spec", lambda *args: (resolved, {}))
    monkeypatch.setattr(bounded, "World", SimpleNamespace(create=lambda *args: world))
    monkeypatch.setattr(bounded, "digest", lambda value: "initial")
    monkeypatch.setattr(bounded, "session", lambda *args: host)
    monkeypatch.setattr(bounded, "ReferenceProvider", lambda *args: provider)
    monkeypatch.setattr(bounded, "effects", lambda *args: {"status": "PASS"})
    monkeypatch.setattr(bounded, "save", lambda path, value: events.append(("save", path.name)))
    monkeypatch.setattr(bounded.time, "monotonic", lambda: 123.0)
    return tmp_path, host, provider, events


def clocks(monkeypatch, elapsed):
    sequence = iter([1, 100, 100 + elapsed, 200 + elapsed])
    monkeypatch.setattr(bounded.time, "monotonic_ns", lambda: next(sequence))


@pytest.mark.parametrize("elapsed", [17_000_000_000, 18_000_000_000])
def test_17_and_exact_18_qualified_and_original_deadline_unchanged(monkeypatch, synthetic, elapsed):
    path, _host, provider, events = synthetic
    clocks(monkeypatch, elapsed)
    collector = []
    result = bounded.prepare_p4_bounded(
        path, {"stage": "P4"}, {}, lambda: events.append("guard"), bounds_collector=collector
    )
    assert result[0] is provider.rows
    assert events[0] == "guard" and events[1] == ("run", 183.0)
    assert len([event for event in events if isinstance(event, tuple) and event[0] == "save"]) == 4
    assert collector[0]["status"] == "QUALIFIED_OUTER_UPPER_BOUND"
    assert collector[0]["admission_union_upper_bound_ns"] == elapsed
    assert collector[0]["prepare_wall_ns"] > elapsed


def test_over_18_is_stronger_wall_failure_after_original_raw_saves(monkeypatch, synthetic):
    path, _host, _provider, events = synthetic
    clocks(monkeypatch, 18_000_000_001)
    collector = []
    with pytest.raises(bounded.ProviderStop, match="NOT_UNION_FAILURE"):
        bounded.prepare_p4_bounded(
            path, {"stage": "P4"}, {}, lambda: None, bounds_collector=collector
        )
    row = collector[0]
    assert row["prepare_completed"] and row["session_completed"]
    assert row["admission_union_upper_bound_ns"] is None
    assert row["session_wall_at_most_18"] is False
    assert len(events) == 5


def test_original_effect_failure_is_primary_even_if_wall_exceeded(monkeypatch, synthetic):
    path, _host, _provider, _events = synthetic
    clocks(monkeypatch, 19_000_000_000)
    monkeypatch.setattr(bounded, "effects", lambda *args: {"status": "FAIL"})
    collector = []
    with pytest.raises(bounded.ProviderStop, match="INDEPENDENT_EFFECT_NOT_MET"):
        bounded.prepare_p4_bounded(
            path, {"stage": "P4"}, {}, lambda: None, bounds_collector=collector
        )
    assert collector[0]["status"] == "NOT_QUALIFIED"
    assert collector[0]["prepare_completed"] is False


def test_run_failure_and_observation_failure_keep_original_object(monkeypatch, synthetic):
    path, host, _provider, _events = synthetic
    primary = RuntimeError("original")

    def run(*args, **kwargs):
        raise primary

    host.run = run
    values = iter([1, 2])
    monkeypatch.setattr(bounded.time, "monotonic_ns", lambda: next(values))
    collector = []
    with pytest.raises(RuntimeError) as raised:
        bounded.prepare_p4_bounded(
            path, {"stage": "P4"}, {}, lambda: None, bounds_collector=collector
        )
    assert raised.value is primary
    assert "SECONDARY_OUTER_BOUND_OBSERVATION_FAILURE" in primary.__notes__[0]
    assert collector == []


def test_fail_closed_session_is_not_qualified(monkeypatch, synthetic):
    path, host, _provider, _events = synthetic
    clocks(monkeypatch, 17_000_000_000)
    host.run = lambda *args, **kwargs: {"status": "EPISODE_DEADLINE"}
    collector = []
    with pytest.raises(bounded.ProviderStop, match="INDEPENDENT_EFFECT_NOT_MET"):
        bounded.prepare_p4_bounded(
            path, {"stage": "P4"}, {}, lambda: None, bounds_collector=collector
        )
    assert collector[0]["admission_union_upper_bound_ns"] is None


def test_original_prepare_statements_preserved_in_order():
    old = ast.parse(textwrap.dedent(inspect.getsource(original.prepare_p4))).body[0]
    new = ast.parse(textwrap.dedent(inspect.getsource(bounded.prepare_p4_bounded))).body[0]
    body = next(node for node in new.body if isinstance(node, ast.Try)).body
    old_statements = [ast.dump(node, include_attributes=False) for node in old.body[1:]]
    new_statements = [ast.dump(node, include_attributes=False) for node in body]
    # New outer clock/flags/gate statements may surround original statements, but
    # every original business statement including deadline+60 and return is exact.
    positions = [new_statements.index(statement) for statement in old_statements]
    assert positions == sorted(positions)
