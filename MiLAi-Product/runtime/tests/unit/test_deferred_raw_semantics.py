from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import pytest

from milai.application import deferred_raw_semantics as raw
from milai.application.decision_engine import DEFAULT_DECISION_ENGINE
from milai.application.evidence_semantics import bind_requirements, interpret_evidence_spans
from milai.application.query_planner import QueryPlanner
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import EvidenceSpan


def _inputs(text: str = "I live in Paris.") -> tuple[Any, Any, list[EvidenceSpan]]:
    reference = datetime(2026, 9, 1, tzinfo=UTC)
    request = RetrievalRequest(
        route="L1", query="Where do I live?", reference_time=reference,
        as_of=reference, system_as_of=reference,
    )
    plan = QueryPlanner().plan(request)
    span = EvidenceSpan(
        span_id="span-1", source_evidence_id="evidence-1", source_turn_ref="turn-1",
        subject_id="subject-1", session_id="session-1", turn_id="turn-1",
        identity_source="STRUCTURED_TURN_METADATA", speaker="user", start=0,
        end=len(text), text=text, source_timestamp=reference,
        provenance={"nested": {"source": "original"}},
    )
    return request, plan, [span]


@pytest.mark.parametrize("text", ["I live in Paris.", "首部\n正文\n尾部", " \t\n", "?!"])
@pytest.mark.parametrize("has_requirements", [False, True])
def test_presence_is_exact_and_full_access_preserves_all_raw_rows(
    text: str, has_requirements: bool,
) -> None:
    _, plan, spans = _inputs(text)
    requirements = plan.memory_query_ir.requirements if has_requirements else []
    expected_interpretations = interpret_evidence_spans(spans)
    expected_bindings = bind_requirements(
        requirements, expected_interpretations, spans, compatibility_profile="dg22-v0.2",
    )
    deferred = raw.DeferredRawSemantics(
        requirements, spans, compatibility_profile="dg22-v0.2",
    )
    assert bool(deferred.interpretations) == bool(expected_interpretations)
    assert bool(deferred.bindings) == bool(expected_bindings)
    assert deferred._values is None
    assert list(deferred.interpretations) == expected_interpretations
    assert list(deferred.bindings) == expected_bindings
    assert len(deferred.bindings) == len(expected_bindings)
    assert deferred.bindings[:] == expected_bindings


def test_raw_binding_presence_retains_negative_control_decision() -> None:
    request, plan, spans = _inputs()
    deferred = raw.DeferredRawSemantics(
        plan.memory_query_ir.requirements, spans, compatibility_profile="dg22-v0.2",
    )
    common = dict(
        query_ir=plan.memory_query_ir, governed_candidates=(),
        canonical_results=({"kind": "CANONICAL_CLAIM", "claim_version_id": "c-1"},),
        operator_result=None, temporal_proof=None, request=request, plan=plan,
        stage="FINAL", mode="ORDINARY_RECALL",
    )
    decision = DEFAULT_DECISION_ENGINE.decide(
        **common, spans=spans, interpretations=deferred.interpretations,
        bindings=deferred.bindings,
    )
    assert deferred._values is None
    interpretations, bindings = deferred.materialize()
    assert decision == DEFAULT_DECISION_ENGINE.decide(
        **common, spans=spans, interpretations=interpretations, bindings=bindings,
    )
    assert decision != DEFAULT_DECISION_ENGINE.decide(
        **common, spans=(), interpretations=(), bindings=(),
    )


@pytest.mark.parametrize("already_materialized", [False, True])
def test_snapshot_freezes_raw_inputs_and_materializes_once(
    monkeypatch: pytest.MonkeyPatch, already_materialized: bool,
) -> None:
    _, plan, spans = _inputs()
    deferred = raw.DeferredRawSemantics(
        plan.memory_query_ir.requirements, spans, compatibility_profile="dg22-v0.2",
    )
    original = raw.interpret_evidence_spans
    calls = []

    def interpret(*args: Any, **kwargs: Any) -> Any:
        calls.append(True)
        return original(*args, **kwargs)

    if already_materialized:
        deferred.materialize()
    inputs = {
        f"{name}_material": {"values": ["first", "last"]}
        for name in ("source_snapshot", "query_ir", "acquisition_plan", "candidate_snapshot",
                     "gate", "requirement_state", "sufficiency", "operator_result")
    }
    expected = build_decision_snapshot(**inputs, binding_material=deferred.freeze())
    monkeypatch.setattr(raw, "interpret_evidence_spans", interpret)
    snapshot = build_decision_snapshot(**inputs, binding_material=deferred, defer_digests=True)
    assert calls == []
    assert (deferred._values is not None) == already_materialized
    spans[0].provenance["nested"] = {"source": "changed"}
    spans.clear()
    plan.memory_query_ir.requirements.clear()
    inputs["gate_material"]["values"].clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: snapshot.materialize(), range(8)))
    assert all(value is values[0] for value in values)
    assert values[0].model_dump(mode="json") == expected.model_dump(mode="json")
    assert snapshot.snapshot_digest == expected.snapshot_digest
    assert len(calls) == (0 if already_materialized else 1)
