from __future__ import annotations

import json
from pathlib import Path

from evals.dg25.baseline_freeze import (
    CASE_ORDER,
    _review_gate,
    build_baseline_freeze,
    build_source_config_index_snapshot_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def test_dg25_s0_technical_freeze_binds_predecessors_and_denominators() -> None:
    baseline = build_baseline_freeze(ROOT)
    sealed = json.loads(
        (
            ROOT
            / "var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/"
            "baseline-freeze.json"
        ).read_text(encoding="utf-8")
    )

    assert sealed["status"] == "PENDING_INDEPENDENT_ABLATION_REVIEW_OR_OWNER_WAIVER"
    assert sealed["hard_gate"]["technical_passed"] is True
    assert baseline["status"] == "FAIL_DG25_S0_BASELINE_DENOMINATOR_REVIEW_FREEZE"
    assert baseline["hard_gate"]["checks"]["runtime_sources_match_15_of_15"] is False
    assert len(sealed["bound_artifacts"]) == 20
    assert len(sealed["runtime_source_baseline"]) == 15
    assert sealed["denominators"]["case_order"] == list(CASE_ORDER)
    assert sealed["denominators"]["evidence_group_count"] == 23
    assert sealed["denominators"]["proof_obligation_count"] == 37


def test_dg25_s0_freezes_exact_dg24_and_dg23_baselines() -> None:
    baseline = build_baseline_freeze(ROOT)
    predecessor = baseline["predecessor_baselines"]

    assert predecessor["dg24_first_loss_distribution"] == {
        "TERMINAL_SURVIVAL": 13,
        "CHANNEL_ELIGIBLE_NOT_INVOKED": 6,
        "CHANNEL_CUTOFF_DROP": 1,
        "NO_CHANNEL_RETRIEVED_GOLD": 3,
    }
    assert predecessor["dg23_mediator"]["required_evidence_coverage_reference"] == 22
    assert predecessor["dg23_mediator"]["accepted_binding_precision"] == 1
    assert predecessor["dg23_reader_reference_b_ref"]["em"] == [4, 4, 4]
    assert predecessor["dg23_reader_reference_b_ref"]["normalized_f1"] == [
        0.474263765,
        0.470909091,
        0.478605605,
    ]


def test_dg25_s0_requires_valid_independent_review_or_explicit_waiver(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "invalid-review.json"
    invalid.write_text(
        json.dumps(
            {
                "schema": "milai.dg25.ablation-independent-review.v0.1",
                "reviewer_is_independent": False,
                "disposition": "ACCEPT",
                "reviewed_blocks": ["E1", "E2"],
            }
        ),
        encoding="utf-8",
    )

    review = _review_gate(
        tmp_path,
        review_receipt=invalid,
        owner_waiver=None,
    )

    assert review["status"] == "REJECTED"
    assert review["passed"] is False


def test_dg25_s0_manifest_binds_schema_and_public_boundaries() -> None:
    manifest = build_source_config_index_snapshot_manifest(ROOT)

    assert len(manifest["runtime_sources"]) == 15
    assert manifest["boundary_tree_identities"]["architecture_v1"]["file_count"] > 0
    assert manifest["boundary_tree_identities"]["public_mcp_contracts"]["file_count"] > 0
    assert manifest["boundary_tree_identities"]["postgresql_migrations"]["file_count"] > 0
    assert manifest["candidate_default"] is False
    assert manifest["formal_holdout_consumed"] is False
