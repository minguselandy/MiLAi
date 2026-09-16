from __future__ import annotations

import pytest
from scripts.build_dg24_s8_terminal import (
    DELIVERABLE_NAMES,
    DG24S8Error,
    derive_terminal_disposition,
)


def _passing_signals() -> dict[str, bool]:
    return {
        "safety_integrity": True,
        "label_product_boundary": True,
        "behavior_neutrality": True,
        "candidate_lineage": True,
        "gold_proof_mapping": True,
        "official_probe_fidelity": True,
        "attribution_completeness": True,
        "quality": True,
    }


def test_terminal_pass_requires_all_independent_lanes() -> None:
    assert (
        derive_terminal_disposition(_passing_signals())
        == "PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED"
    )
    assert len(DELIVERABLE_NAMES) == 33
    assert len(set(DELIVERABLE_NAMES)) == 33


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        ("safety_integrity", "FAIL_SAFETY_OR_INTEGRITY"),
        ("label_product_boundary", "PARKED_LABEL_PRODUCT_BOUNDARY_VIOLATION"),
        ("behavior_neutrality", "PARKED_BEHAVIOR_CHANGED"),
        ("candidate_lineage", "PARKED_UNRESOLVED_CANDIDATE_LINEAGE"),
        ("gold_proof_mapping", "PARKED_GOLD_MAPPING_INCOMPLETE"),
        ("official_probe_fidelity", "PARKED_EVAL_PRODUCT_PATH_DIVERGENCE"),
    ],
)
def test_terminal_preserves_predeclared_failure_lanes(
    signal: str, expected: str
) -> None:
    signals = _passing_signals()
    signals[signal] = False

    assert derive_terminal_disposition(signals) == expected


def test_terminal_rejects_an_incomplete_signal_denominator() -> None:
    signals = _passing_signals()
    signals.pop("quality")

    with pytest.raises(DG24S8Error, match="denominator"):
        derive_terminal_disposition(signals)
