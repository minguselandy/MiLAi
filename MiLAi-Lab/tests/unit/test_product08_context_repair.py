from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

LAB = Path(__file__).resolve().parents[2]
TOOLS = LAB / "tools"


def _runner_module():
    path = TOOLS / "run_product08_context_repair.py"
    spec = importlib.util.spec_from_file_location("product08_context_repair", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS))
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(TOOLS))
    return module


def _valid_report() -> dict[str, Any]:
    digest = "a" * 64
    arm = {
        "snapshot_digest": digest,
        "fresh_repository_calls": 0,
        "fresh_embedding_calls": 0,
        "fresh_vector_calls": 0,
        "canonical_mutation": False,
    }
    return {
        "schema_version": "milai-context-testkit-report-v0.1",
        "snapshot": {
            "snapshot_digest": digest,
            "raw_evidence_text_emitted": False,
        },
        "invariants": {
            "snapshot_build_count": 1,
            "c_x_before_boundary_equal": True,
            "c_x_decision_snapshot_equal": True,
            "replay_external_calls": 0,
            "workspace_enabled": False,
            "context_mutation_performed": False,
            "canonical_mutation": False,
        },
        "arms": {name: dict(arm) for name in ("C", "X", "Y")},
    }


def test_product08_testkit_report_accepts_only_frozen_zero_call_replays() -> None:
    module = _runner_module()

    module._validate_testkit_report(_valid_report())

    raw_leak = _valid_report()
    raw_leak["snapshot"]["raw_evidence_text_emitted"] = True
    with pytest.raises(module.Product08ContextRepairError, match="Raw Evidence"):
        module._validate_testkit_report(raw_leak)

    fresh_call = _valid_report()
    fresh_call["arms"]["Y"]["fresh_vector_calls"] = 1
    with pytest.raises(module.Product08ContextRepairError, match="fresh replay"):
        module._validate_testkit_report(fresh_call)


def _retrieval_metrics(*, complete: bool, coverage: float) -> dict[str, Any]:
    return {
        "all_required_evidence_group_recall": complete,
        "any_gold_session_recall": True,
        "reader_visible_evidence_group_coverage": coverage,
        "reader_visible_answer_session_coverage": coverage,
    }


def _gate_rows() -> list[dict[str, Any]]:
    families = ("SET", "ASSISTANT", "TEMPORAL", "UNIT")
    rows: list[dict[str, Any]] = []
    for ordinal in range(1, 25):
        baseline_complete = ordinal <= 10
        candidate_complete = ordinal <= 14
        arms: dict[str, Any] = {}
        for arm in ("A", "C", "X", "Y"):
            is_candidate = arm == "Y"
            arms[arm] = {
                "retrieval_metrics": _retrieval_metrics(
                    complete=(candidate_complete if is_candidate else baseline_complete),
                    coverage=(0.7 if is_candidate else 0.5),
                ),
                "cross_namespace_source_count": 0,
                "trace": ({"canonical_mutation": False} if arm != "A" else {}),
            }
        rows.append(
            {
                "ordinal": ordinal,
                "case_id_sha256": f"case-{ordinal:02d}",
                "capability_family": families[(ordinal - 11) % len(families)],
                "status": "PASS",
                "arms": arms,
                "causal_invariants": {
                    "c_x_before_boundary_match": True,
                    "c_x_decision_snapshot_match": True,
                    "c_reader_visible_subset_x": True,
                    "x_nonempty_collapse": False,
                    "y_nonempty_collapse": False,
                    "dense_execution_valid": True,
                },
            }
        )
    return rows


def test_product08_gate_requires_all_causal_and_effect_gates() -> None:
    module = _runner_module()
    rows = _gate_rows()

    summary = module._gate_summary(rows)

    assert summary["p08_context_gate"] is True
    assert summary["comparisons_to_A"]["Y"]["complete_case_gain"] == 4
    assert summary["comparisons_to_A"]["Y"]["recovered_shape_count"] == 4

    rows[0]["causal_invariants"]["dense_execution_valid"] = False
    assert module._gate_summary(rows)["p08_context_gate"] is False
