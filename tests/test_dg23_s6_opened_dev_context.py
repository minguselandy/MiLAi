from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from evals.dg23.opened_dev_context import (
    DG23OpenedDevContextError,
    _case_usage,
    _cleanup_deferred_adapters,
    _first_loss,
    _plan_source_refs,
    _score_mode_record,
    build_opened_dev_context_product,
    seal_opened_dev_context_product,
    structural_gate,
)
from milai.application import evidence_acquisition
from milai.application.evidence_acquisition import (
    _run_product_type_directed_semantics,
)
from milai.config.settings import RuntimeSettings
from scripts.run_dg23_s6_opened_dev_context import (
    _score_sealed_product,
)
from scripts.run_dg23_s6_opened_dev_context import (
    main as s6_main,
)


class _CleanupAdapter:
    def __init__(self, events: list[str], case_id: str) -> None:
        self.events = events
        self.case_id = case_id

    def cleanup(self) -> dict[str, object]:
        self.events.append(self.case_id)
        return {"status": "ACCEPTED", "cleanup_accepted": True}


class _Unit:
    def __init__(self, *source_turn_refs: str) -> None:
        self.source_turn_refs = source_turn_refs


class _ReaderPlan:
    protected_units = (_Unit("case:s1:t0", "case:s1:t1"),)
    conditional_units = (_Unit("case:s1:t1", "case:s2:t0"),)


class _Planned:
    reader_evidence_plan = _ReaderPlan()


def test_dg23_s6_candidate_feature_default_is_false() -> None:
    field = RuntimeSettings.model_fields["budget_invariant_context_v0_1"]

    assert field.default is False


def test_dg23_s6_label_free_seal_rejects_answer_material(tmp_path: Path) -> None:
    product = {
        "schema": "milai.dg23.s6-opened-dev-context-product.v0.1",
        "labels_loaded": False,
        "formal_holdout_consumed": False,
        "structural_gate": {"passed": True},
        "answers": ["forbidden"],
    }

    with pytest.raises(DG23OpenedDevContextError):
        seal_opened_dev_context_product(product, tmp_path / "product.json")


def test_dg23_s6_structural_gate_has_no_label_dependency() -> None:
    source = inspect.getsource(structural_gate)

    assert "load_answer_bearing_labels" not in source
    assert "score" not in source.casefold()


def test_dg23_s6_uses_frozen_dg22_acquisition_capabilities() -> None:
    source = inspect.getsource(build_opened_dev_context_product)

    assert "lexical_enrichment_enabled=True" in source
    assert "evidence_dense_enabled=True" in source


def test_dg23_s6_namespace_cleanup_is_deferred_and_exactly_once() -> None:
    events: list[str] = []
    lifecycle = [{"case_id": case_id, "cleanup_status": "DEFERRED"} for case_id in ("a", "b", "c")]
    deferred = [(case_id, _CleanupAdapter(events, case_id)) for case_id in ("a", "b", "c")]

    failure = _cleanup_deferred_adapters(deferred, lifecycle)

    assert failure is None
    assert events == ["c", "b", "a"]
    assert all(row["cleanup_status"] == "ACCEPTED" for row in lifecycle)


def test_dg23_s6_quarantine_is_persisted_before_authoritative_seal() -> None:
    source = inspect.getsource(s6_main)

    assert source.index("unsealed-context-product-quarantine.json") < source.index(
        "seal_opened_dev_context_product"
    )
    assert "--score-only-product" in source
    assert "reacquisition_executions" in inspect.getsource(_score_sealed_product)


def test_dg23_s6_scored_view_retains_first_loss_provenance() -> None:
    scored = _score_mode_record(
        {
            "case_id": "case-a",
            "mode": "REFERENCE_B_REF",
            "budget": 8000,
            "readiness": "READY",
            "selected_source_refs": ["source-a"],
            "all_candidate_source_refs": ["source-a", "source-b"],
            "accepted_binding_source_refs": ["source-a"],
            "sufficiency_status": "COMPLETE",
            "found_requirement_ids": ["requirement-a"],
            "usage": {},
        },
        ["source-a", "source-b", "source-c"],
    )

    assert scored["all_candidate_source_refs"] == ["source-a", "source-b"]
    assert scored["accepted_binding_source_refs"] == ["source-a"]
    assert _first_loss([scored], {"case-a": ["source-a", "source-b", "source-c"]}) == [
        {"case_id": "case-a", "source_turn_ref": "source-a", "first_loss": "NONE"},
        {
            "case_id": "case-a",
            "source_turn_ref": "source-b",
            "first_loss": "BINDING",
        },
        {
            "case_id": "case-a",
            "source_turn_ref": "source-c",
            "first_loss": "ACQUISITION",
        },
    ]


def test_dg23_s6_plan_source_projection_is_ordered_and_deduplicated() -> None:
    assert _plan_source_refs(_Planned()) == [
        "case:s1:t0",
        "case:s1:t1",
        "case:s2:t0",
    ]


def test_dg23_s6_usage_prefers_actual_accuracy_hydration_counters() -> None:
    body = {
        "search_trace": {
            "candidate_counts": {"evidence_slot_union": 8},
            "deterministic_recovery": {
                "extra_pass_count": 1,
                "provider_calls": 0,
                "automatic_retries": 0,
                "accuracy_acquisition": {
                    "candidates_hydrated": 3,
                    "useful_candidate_count": 2,
                },
            },
        }
    }

    assert _case_usage(body, ["accepted-a"]) == {
        "additional_acquisition_calls": 1,
        "candidates_hydrated": 3,
        "useful_candidate_count": 2,
        "provider_controller_calls": 0,
        "automatic_retries": 0,
        "hidden_model_calls": 0,
    }


def test_dg23_s6_first_loss_prefers_observed_context_over_internal_stage_labels() -> None:
    scored = _score_mode_record(
        {
            "case_id": "case-a",
            "mode": "REFERENCE_B_REF",
            "budget": 8000,
            "readiness": "READY",
            "selected_source_refs": ["source-a"],
            "all_candidate_source_refs": [],
            "accepted_binding_source_refs": [],
            "sufficiency_status": "PARTIAL",
            "found_requirement_ids": [],
            "usage": {},
        },
        ["source-a"],
    )

    assert _first_loss([scored], {"case-a": ["source-a"]}) == [
        {"case_id": "case-a", "source_turn_ref": "source-a", "first_loss": "NONE"}
    ]


def test_dg23_s6_product_type_directed_flag_uses_frozen_dg22_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_semantics(
        requirements: object,
        spans: object,
        *,
        compatibility_profile: str,
    ) -> tuple[list[object], list[object], object]:
        observed["requirements"] = requirements
        observed["spans"] = spans
        observed["profile"] = compatibility_profile
        return [], [], object()

    monkeypatch.setattr(
        evidence_acquisition,
        "run_type_directed_semantics",
        fake_semantics,
    )

    result = _run_product_type_directed_semantics([], [])

    assert result[:2] == ([], [])
    assert observed == {
        "requirements": [],
        "spans": [],
        "profile": "dg22-v0.2",
    }
