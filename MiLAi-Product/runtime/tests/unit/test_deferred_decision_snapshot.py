from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from milai.application import reader_evidence_plan as snapshots
from milai.application.memory_context import MemoryContextCompiler
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.domain.reader_evidence_plan import DecisionSnapshot


def _inputs() -> dict[str, Any]:
    return {
        f"{name}_material": {"source": ["首部", "middle", "尾部"]}
        for name in (
            "source_snapshot", "query_ir", "acquisition_plan", "candidate_snapshot",
            "gate", "binding", "requirement_state", "sufficiency", "operator_result",
        )
    }


def test_deferred_snapshot_freezes_inputs_and_materializes_once_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Material(BaseModel):
        values: list[str]

    inputs = _inputs()
    model = Material(values=["original"])
    inputs["binding_material"] = model
    expected = snapshots.build_decision_snapshot(**inputs)
    original = snapshots._complete_snapshot
    calls = []

    def complete(*args: Any, **kwargs: Any) -> DecisionSnapshot:
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(snapshots, "_complete_snapshot", complete)
    deferred = snapshots.build_decision_snapshot(**inputs, defer_digests=True)
    assert isinstance(deferred, snapshots.DeferredDecisionSnapshot)
    assert deferred.lean_recall_mode == expected.lean_recall_mode
    assert deferred.evidence_set == expected.evidence_set
    assert deferred.accepted_evidence_ids == expected.accepted_evidence_ids
    assert calls == []
    model.values.append("changed")
    inputs["candidate_snapshot_material"]["source"].clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: deferred.materialize(), range(8)))
    assert len(calls) == 1
    assert all(value is results[0] for value in results)
    assert results[0].model_dump(mode="json") == expected.model_dump(mode="json")
    assert deferred.snapshot_digest == expected.snapshot_digest
    assert deferred._materials == {}
    assert DecisionSnapshot.model_validate_json(results[0].model_dump_json()) == expected
    assert snapshots.materialize_decision_snapshot(expected) is expected
    changed = snapshots.build_decision_snapshot(**inputs, defer_digests=True)
    assert changed.snapshot_digest != deferred.snapshot_digest
    assert len(calls) == 2


def test_deferred_snapshot_rejects_invalid_decision_facts_before_use() -> None:
    with pytest.raises(ValueError, match="unresolved requirements"):
        snapshots.build_decision_snapshot(
            **_inputs(), defer_digests=True, unresolved_requirement_ids=["unknown"],
        )
    with pytest.raises(ValidationError, match="lean_recall_mode"):
        snapshots.build_decision_snapshot(
            **(_inputs() | {"lean_recall_mode": "UNKNOWN"}), defer_digests=True,
        )


@pytest.mark.parametrize("pydantic_override", [False, True])
def test_custom_serializer_cannot_retain_mutable_alias_into_frozen_material(
    pydantic_override: bool,
) -> None:
    class DuckSerializer:
        def __init__(self) -> None:
            self.values = {"head": ["first"], "tail": ["last"]}

        def model_dump(self, **_: Any) -> dict[str, list[str]]:
            return self.values

    class Override(BaseModel):
        values: dict[str, list[str]]

        def model_dump(self, **_: Any) -> dict[str, Any]:
            return self.values

    source = Override(values=DuckSerializer().values) if pydantic_override else DuckSerializer()
    inputs = _inputs() | {"binding_material": source}
    expected = snapshots.build_decision_snapshot(**inputs)
    deferred = snapshots.build_decision_snapshot(**inputs, defer_digests=True)
    source.values["tail"].append("changed")
    assert deferred.snapshot_digest == expected.snapshot_digest
    assert deferred.materialize() == expected


@pytest.mark.parametrize("invalid", [b"bytes", "\ud800", {"unsupported"}])
def test_deferred_digest_errors_surface_when_full_snapshot_is_requested(invalid: Any) -> None:
    inputs = _inputs() | {"binding_material": invalid}
    with pytest.raises((TypeError, UnicodeEncodeError)) as eager:
        snapshots.build_decision_snapshot(**inputs)
    deferred = snapshots.build_decision_snapshot(**inputs, defer_digests=True)
    with pytest.raises(type(eager.value)):
        deferred.materialize()
    assert deferred._snapshot is None
    assert deferred._materials


@pytest.mark.parametrize(
    "settings", [{}, {"budget_stable_enabled": True}, {"evidence_set_selection_enabled": True}],
)
def test_context_only_materializes_when_planning_needs_full_snapshot(
    settings: dict[str, bool],
) -> None:
    compiler = MemoryContextCompiler(**settings)
    inputs = _inputs()
    eager = snapshots.build_decision_snapshot(**inputs)
    deferred = snapshots.build_decision_snapshot(**inputs, defer_digests=True)
    request = MemoryResolveRequest(query="Recall the release notes")
    outcome = {"status": "MISS", "items": [], "open_issue_ids": []}
    expected = compiler.compile(request, outcome, decision_snapshot=eager)
    result = compiler.compile(request, outcome, decision_snapshot=deferred)
    assert result == expected
    assert (deferred._snapshot is not None) == bool(settings)
    assert compiler.requires_full_decision_snapshot == bool(settings)
    planned = compiler.plan(request, outcome, decision_snapshot=deferred)
    assert isinstance(planned.decision_snapshot, DecisionSnapshot)
    assert planned.decision_snapshot == eager
