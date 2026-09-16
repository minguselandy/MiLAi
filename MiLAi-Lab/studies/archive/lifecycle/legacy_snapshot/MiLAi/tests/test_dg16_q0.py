from __future__ import annotations

from evals.dg14.benchmark import OPENED_DEV_INPUT_PATH, load_opened_dev
from evals.dg16.q0 import (
    DEFAULT_FIXTURE_PATH,
    build_oracle_contexts,
    build_q0_receipt,
    load_evaluation_fixture,
)


def test_q0_fixture_spans_replay_against_frozen_opened_dev_input() -> None:
    fixture = load_evaluation_fixture(DEFAULT_FIXTURE_PATH)

    assert fixture["input_sha256"] == (
        "dd1c6fb5c137b16780965b5637562cdfdc8e69ef8d1f1e02e94ce92c754b5a5b"
    )
    assert sum(len(case["required_atoms"]) for case in fixture["cases"]) == 9
    assert fixture["classification"].endswith("EVALUATION_PLANE")


def test_q0_metrics_expose_coffee_boundary_loss_and_doctor_range_miss() -> None:
    receipt = build_q0_receipt()
    metrics = {item["case_id"]: item for item in receipt["metrics"]}

    coffee = metrics["0100672e"]
    assert coffee["session_recall"] == 1.0
    assert coffee["required_evidence_set_coverage"] == 0.5
    assert coffee["filled_slots"] == ["ITEM_COUNT"]
    assert coffee["primary_failure"] == "EVIDENCE_BOUNDARY_LOSS"
    assert coffee["secondary_diagnostics"] == ["REQUIRED_SLOT_MISSING"]

    doctor = metrics["00ca467f"]
    assert doctor["session_recall"] == 0.0
    assert doctor["required_evidence_set_coverage"] == 0.0
    assert doctor["primary_failure"] == "CANDIDATE_RECALL_MISS"
    assert doctor["secondary_diagnostics"] == ["TEMPORAL_RANGE_INCOMPLETE"]
    assert doctor["temporal_range_resolved"] is False
    assert doctor["bounded_scan_completed"] is False


def test_q0_replays_all_atoms_for_three_currently_correct_cases() -> None:
    receipt = build_q0_receipt()
    metrics = {item["case_id"]: item for item in receipt["metrics"]}

    assert receipt["correct_case_atom_replay"] == {
        "case_ids": ["001be529", "01493427", "031748ae"],
        "count": 3,
        "status": "PASS",
    }
    for case_id in receipt["correct_case_atom_replay"]["case_ids"]:
        assert metrics[case_id]["required_evidence_set_coverage"] == 1.0
        assert metrics[case_id]["primary_failure"] == "NONE"


def test_q0_binds_observed_retrieval_calls_without_inventing_model_identity() -> None:
    receipt = build_q0_receipt()
    config = receipt["retrieval_configuration"]

    assert config["embedding"]["calls"] == 5
    assert config["embedding"]["model_id"] == "UNKNOWN_NOT_BOUND_BY_DG14_MANIFEST"
    assert config["vector_search_calls"] == 5
    assert config["reranker"]["calls"] == 0
    assert config["reranker"]["observed_execution"] == "NOT_EXECUTED"
    assert receipt["label_boundary"]["product_path_label_access_count"] == 0
    assert receipt["label_boundary"]["case_count"] == 5


def test_q0_oracle_contexts_keep_gold_material_in_evaluation_module() -> None:
    _partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
    fixture = load_evaluation_fixture(DEFAULT_FIXTURE_PATH, cases=cases)
    labels = {item["case_id"]: item for item in fixture["cases"]}
    coffee = next(case for case in cases if case.case_id == "0100672e")

    contexts = build_oracle_contexts(coffee, labels[coffee.case_id], "actual")

    assert set(contexts) == {
        "A_FULL_HISTORY",
        "B_GOLD_EVIDENCE_SET",
        "C_GOLD_QUERYSPEC_ACTUAL_RETRIEVAL",
        "D_ACTUAL_QUERYSPEC_ACTUAL_RETRIEVAL",
    }
    assert "spent $60" in contexts["B_GOLD_EVIDENCE_SET"]
    assert "purchased 5 coffee mugs" in contexts["B_GOLD_EVIDENCE_SET"]
    assert "DIVIDE_EVIDENCE_VALUES" in contexts[
        "C_GOLD_QUERYSPEC_ACTUAL_RETRIEVAL"
    ]
    assert "UNTYPED_NEED_REQUIRES_FULL_PIPELINE" in contexts[
        "D_ACTUAL_QUERYSPEC_ACTUAL_RETRIEVAL"
    ]
