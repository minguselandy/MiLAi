from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.mf01.labels import ALL_OBLIGATION_KINDS, FormationLabelSeal, build_label_seal
from scripts.freeze_mf01_s0_s1 import stage_availability_map

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def label_seal() -> FormationLabelSeal:
    return build_label_seal(ROOT)


def test_s1_seal_is_source_exact_and_adequate(label_seal: FormationLabelSeal) -> None:
    assert label_seal.case_count == 14
    assert label_seal.label_count == 125
    assert label_seal.counts_by_origin == {
        "DG17_OPENED_DEVELOPMENT": 90,
        "MF01_SYNTHETIC_LOCAL": 35,
    }
    assert all(label_seal.counts_by_kind[kind] >= 2 for kind in ALL_OBLIGATION_KINDS)
    assert label_seal.scope_coverage == 1.0
    assert label_seal.determinability == 1.0
    assert label_seal.adequate_for_s2_entry_review is True
    assert label_seal.formal_holdout_used is False


def test_synthetic_supplement_covers_missing_lifecycle_types(
    label_seal: FormationLabelSeal,
) -> None:
    synthetic_kinds = {
        label.obligation_kind
        for label in label_seal.labels
        if label.origin == "MF01_SYNTHETIC_LOCAL"
    }

    assert synthetic_kinds == set(ALL_OBLIGATION_KINDS)
    assert all(label.speaker == "user" for label in label_seal.labels)


def test_s0_map_does_not_misname_adjacent_runtime_capabilities() -> None:
    stage_map = {item["stage"]: item for item in stage_availability_map()}

    for stage in (
        "F10_EPISODE_FORMED",
        "F20_MENTION_FORMED",
        "F30_IDENTITY_RESOLVED",
        "F40_EVENT_TIME_GROUNDED",
        "F50_STATE_OR_CHANGE_FORMED",
    ):
        assert stage_map[stage]["availability"] == "NOT_IMPLEMENTED"
        assert stage_map[stage]["owner"] is None
        assert "adjacent_non_equivalent_capability" in stage_map[stage]
    assert stage_map["F00_RAW_EVIDENCE_CAPTURED"]["availability"] == "IMPLEMENTED"
    assert (
        stage_map["F60_PROPOSAL_EMITTED"]["availability"]
        == "IMPLEMENTED_EXPLICIT_CALLER_ONLY"
    )
    assert (
        stage_map["F70_CANONICAL_DISPOSITION"]["availability"]
        == "IMPLEMENTED_GOVERNED"
    )
    assert stage_map["F80_RETRIEVAL_PROJECTION_BUILT"]["availability"] == (
        "IMPLEMENTED_RAW_AND_CANONICAL_READ_PATHS"
    )


def test_historical_s0_s1_lock_did_not_claim_an_effect() -> None:
    lock = json.loads((ROOT / "var/mf01/run-lock.json").read_text(encoding="utf-8"))

    assert lock["scope"]["effect_run"] is False
    assert lock["S2_entry_gates"]["effect_authorized"] is False
    assert lock["safety"]["trace_artifact_written"] is False
    assert lock["safety"]["results_artifact_written"] is False
    assert lock["safety"]["terminal_artifact_written"] is False
