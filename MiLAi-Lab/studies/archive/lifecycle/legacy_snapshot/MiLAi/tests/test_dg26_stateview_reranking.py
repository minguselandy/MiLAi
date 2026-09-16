from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from milai.adapters import (
    RerankerExecution,
    StateAwareCrossEncoderReranker,
    fixed_candidate_pool_digest,
)
from milai.domain.ranking_state_view import (
    RankingStateViewV01,
    build_ranking_state_view,
)
from milai.domain.requirement_state import (
    RequirementCardinalityState,
    RequirementDisposition,
    RequirementState,
    canonical_sha256,
)

from evals.dg26.stateview_reranking import (
    _build_views,
    _evaluate_selections,
    _reranker,
    derive_decision,
    load_experiment_inputs,
    load_run_lock,
)
from scripts.run_dg26 import build_terminal

ROOT = Path(__file__).resolve().parents[1]
RUN_LOCK = ROOT / "var/dg26/run-lock.json"
EXPECTED_IDENTITY = {
    "provider": "fake",
    "model_id": "fake-model",
    "revision": "frozen",
    "model_sha256": "a" * 64,
    "tokenizer_sha256": "b" * 64,
    "runtime": "fake/CPU",
    "max_length": 512,
}


class _Backend:
    def __init__(self, fault: str | None = None) -> None:
        self.fault = fault
        self.calls = 0

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        limit: int,
        pool_size: int,
    ) -> RerankerExecution:
        self.calls += 1
        assert query
        assert limit == pool_size == len(candidates)
        if self.fault == "timeout":
            raise TimeoutError("injected")
        results = []
        for index, candidate in enumerate(candidates):
            value = dict(candidate)
            value["reranker"] = {
                "score": math.nan if self.fault == "nonfinite" and index == 0 else float(index),
                "source_rank": index + 1,
            }
            results.append(value)
        if self.fault == "partial":
            results = results[:-1]
        metadata = {**EXPECTED_IDENTITY, "pairs": len(candidates), "duration_ms": 1.0}
        if self.fault == "identity":
            metadata["model_id"] = "drifted"
        return RerankerExecution(results, metadata)


def _candidates() -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": value,
            "source_ref": f"fixture://{value}",
            "content_hash": value * 64,
            "memory_text": f"memory {value}",
        }
        for value in ("a", "b", "c")
    ]


def _state() -> RequirementState:
    disposition = RequirementDisposition(
        requirement_id="TARGET",
        kind="EVENT_SLOT",
        status="MISSING",
        required_cardinality=RequirementCardinalityState(
            minimum=1,
            maximum=1,
            distinct=False,
        ),
        observed_cardinality=0,
        proof_status="NOT_REQUIRED",
    )
    material: dict[str, Any] = {
        "schema_version": "requirement-state-v0.1",
        "query_ir_digest": "1" * 64,
        "acquisition_plan_digest": "2" * 64,
        "acquisition_capability_digest": "3" * 64,
        "candidate_snapshot_digest": "4" * 64,
        "binding_digest": "5" * 64,
        "sufficiency_decision_digest": "6" * 64,
        "sufficiency_policy_version": "test",
        "state_epoch": 0,
        "requirements": [disposition.model_dump(mode="json")],
        "lifetime": "MEMORY_RESOLVE",
        "canonical": False,
        "canonical_mutation": False,
    }
    return RequirementState.model_validate(
        {**material, "state_digest": canonical_sha256(material)}
    )


def _view(candidates: list[dict[str, Any]]) -> RankingStateViewV01:
    return build_ranking_state_view(
        requirement_state=_state(),
        requirement_id="TARGET",
        query_operator="LOOKUP",
        permission_trimmed_anchors=["alpha", "beta"],
        candidate_pool_digest=fixed_candidate_pool_digest(candidates),
        selection_cutoff_k=2,
    )


def test_view_serialization_excludes_runtime_identity_and_shuffles_within_view() -> None:
    candidates = _candidates()
    view = _view(candidates)

    correct = view.render("Which memory applies?")
    shuffled = view.render("Which memory applies?", shuffled=True)

    assert correct != shuffled
    assert "operator=LOOKUP" in correct
    assert "operator=EVENT_SLOT" in shuffled
    assert "missing_evidence_roles=TARGET" in correct
    assert "missing_evidence_roles=alpha,beta" in shuffled
    assert view.requirement_state_digest not in correct
    assert view.candidate_pool_digest not in correct
    assert view.view_digest not in correct
    assert set(view.semantic_material()).isdisjoint(
        {"state_epoch", "requirement_state_digest", "candidate_pool_digest", "view_digest"}
    )


def test_adapter_scores_complete_pool_and_uses_baseline_tie_breaker() -> None:
    candidates = _candidates()
    backend = _Backend()
    adapter = StateAwareCrossEncoderReranker(backend, expected_identity=EXPECTED_IDENTITY)

    execution = adapter.rerank(
        "Which memory applies?",
        candidates,
        limit=2,
        pool_size=3,
        state_view=_view(candidates),
        state_mode="CORRECT",
    )

    assert [item["evidence_id"] for item in execution.results] == ["c", "b"]
    assert execution.metadata["fallback_used"] is False
    assert execution.metadata["automatic_retries"] == 0
    assert backend.calls == 1


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("timeout", "TIMEOUT"),
        ("partial", "PARTIAL_OR_FOREIGN_BATCH"),
        ("identity", "IDENTITY_MISMATCH"),
        ("nonfinite", "NON_FINITE_SCORE"),
    ],
)
def test_adapter_faults_fail_closed_without_retry(fault: str, reason: str) -> None:
    candidates = _candidates()
    backend = _Backend(fault)
    adapter = StateAwareCrossEncoderReranker(backend, expected_identity=EXPECTED_IDENTITY)

    execution = adapter.rerank(
        "Which memory applies?",
        candidates,
        limit=2,
        pool_size=3,
        state_view=_view(candidates),
        state_mode="CORRECT",
    )

    assert [item["evidence_id"] for item in execution.results] == ["a", "b"]
    assert execution.metadata["fallback_used"] is True
    assert execution.metadata["fallback_reason"] == reason
    assert execution.metadata["automatic_retries"] == 0
    assert backend.calls == 1


def test_stale_view_fails_closed_before_model_invocation() -> None:
    candidates = _candidates()
    stale = _view(candidates[:-1])
    backend = _Backend()
    adapter = StateAwareCrossEncoderReranker(backend, expected_identity=EXPECTED_IDENTITY)

    execution = adapter.rerank(
        "Which memory applies?",
        candidates,
        limit=2,
        pool_size=3,
        state_view=stale,
        state_mode="CORRECT",
    )

    assert [item["evidence_id"] for item in execution.results] == ["a", "b"]
    assert execution.metadata["fallback_reason"] == "PRECALL_PROTOCOL_FAILURE"
    assert execution.metadata["model_invocations"] == 0
    assert backend.calls == 0


def test_run_lock_and_label_free_fixed_pool_recompute() -> None:
    lock = load_run_lock(ROOT, RUN_LOCK)
    inputs = load_experiment_inputs(ROOT, RUN_LOCK)

    assert lock["formal_holdout_used"] is False
    assert lock["dataset_snapshot"]["forbidden_label_fields_present"] is False
    assert len(inputs.contexts) == 10
    assert len(inputs.pools) == 15
    assert sum(len(pool.candidates) for pool in inputs.pools.values()) == 327
    assert len(inputs.pools[("a82c026e", "LOOKUP_ANSWER")].candidates) == 32


def test_frozen_onnx_one_fixed_pool_smoke() -> None:
    inputs = load_experiment_inputs(ROOT, RUN_LOCK)
    baseline = {
        key: [dict(item) for item in pool.candidates[: min(8, len(pool.candidates))]]
        for key, pool in inputs.pools.items()
    }
    evaluation = _evaluate_selections(inputs, baseline, build_states=True)
    views = _build_views(inputs, evaluation.states)
    key = ("a82c026e", "LOOKUP_ANSWER")
    pool = inputs.pools[key]

    execution = _reranker(inputs, ROOT).rerank(
        pool.query,
        [dict(item) for item in pool.candidates],
        limit=8,
        pool_size=len(pool.candidates),
        state_view=views[key],
        state_mode="CORRECT",
    )

    assert len(execution.results) == 8
    assert execution.metadata["pairs"] == 32
    assert execution.metadata["fallback_used"] is False
    assert "longmemeval://" not in views[key].render(pool.query)


def _single_run(
    *,
    r0: int = 10,
    r1: int = 10,
    r2: int = 11,
    r3: int = 10,
    recovered: int = 1,
    lost: int = 0,
) -> dict[str, Any]:
    def metrics(covered: int) -> dict[str, Any]:
        return {
            "covered_groups": covered,
            "accepted_binding_precision": 1.0,
            "wrong_complete": 0,
            "residual_groups_recovered": 0,
            "baseline_correct_groups_lost": 0,
        }

    arms = {
        "R0": {"metrics": metrics(r0)},
        "R1": {"metrics": metrics(r1)},
        "R2": {"metrics": metrics(r2)},
        "R3": {"metrics": metrics(r3)},
    }
    arms["R2"]["metrics"]["residual_groups_recovered"] = recovered
    arms["R2"]["metrics"]["baseline_correct_groups_lost"] = lost
    return {
        "arms": arms,
        "safety": {
            "acquisition_call_delta": 0,
            "adapter_fallback_count": 0,
            "automatic_retries": 0,
        },
    }


def test_terminal_decision_rules_are_exact() -> None:
    assert derive_decision(_single_run(), fresh_process_exact_match=True)["status"] == "PASS"
    no_gain = derive_decision(
        _single_run(r2=10, recovered=0), fresh_process_exact_match=True
    )
    copied = derive_decision(
        _single_run(r1=11, r2=11), fresh_process_exact_match=True
    )
    regression = derive_decision(
        _single_run(r2=11, lost=1), fresh_process_exact_match=True
    )

    assert no_gain["reason_code"] == "NO_STATEVIEW_GAIN"
    assert copied["reason_code"] == "GAIN_NOT_STATE_CONDITIONED"
    assert regression["reason_code"] == "CORRECT_CASE_REGRESSION"


def test_failed_terminal_keeps_independently_supported_safety_claim(tmp_path: Path) -> None:
    terminal = build_terminal(
        run_lock=RUN_LOCK,
        results_path=ROOT / "var/dg26/results.json",
        terminal_path=tmp_path / "terminal.json",
        targeted_tests="PASS: fixture",
        typecheck="PASS: fixture",
        lint="PASS: fixture",
    )

    claims = {item["claim_id"]: item["status"] for item in terminal["claims"]}
    assert terminal["status"] == "FAIL"
    assert claims["C1_STATEVIEW_INDEPENDENT_RANKING_GAIN"] == "NOT_SUPPORTED"
    assert claims["C2_NO_ACQUISITION_OR_SAFETY_RELAXATION"] == "SUPPORTED"
