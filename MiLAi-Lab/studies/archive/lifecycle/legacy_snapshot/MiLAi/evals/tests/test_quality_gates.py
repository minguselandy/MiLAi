from __future__ import annotations

from evals.analysis import evaluate_quality_gates


def _metric(f1: float, em: float = 0.2) -> dict[str, float]:
    return {"normalized_f1_mean": f1, "exact_match_mean": em}


def test_quality_gates_match_preregistered_thresholds() -> None:
    current_categories = {
        "multi-session": _metric(0.2),
        "single-session-assistant": _metric(0.3),
        "knowledge-update": _metric(0.48),
    }
    dg10_categories = {
        "multi-session": _metric(0.2),
        "single-session-assistant": _metric(0.1),
        "knowledge-update": _metric(0.5),
    }
    lexical_categories = {
        "multi-session": _metric(0.1),
        "single-session-assistant": _metric(0.3),
        "knowledge-update": _metric(0.1),
    }

    gates = evaluate_quality_gates(
        current_v1=_metric(0.35, 0.2),
        legacy_v1=_metric(0.3, 0.2),
        current_categories=current_categories,
        legacy_categories=dg10_categories,
        lexical_categories=lexical_categories,
        mean_memory_tokens=320,
        safety_pass=True,
    )

    assert all(gates.values())


def test_quality_gates_reject_each_wrong_side_of_boundary() -> None:
    current_categories = {
        "multi-session": _metric(0.19),
        "single-session-assistant": _metric(0.29),
        "knowledge-update": _metric(0.479),
    }
    dg10_categories = {
        "multi-session": _metric(0.2),
        "single-session-assistant": _metric(0.1),
        "knowledge-update": _metric(0.5),
    }
    lexical_categories = {
        "multi-session": _metric(0.1),
        "single-session-assistant": _metric(0.3),
        "knowledge-update": _metric(0.1),
    }

    gates = evaluate_quality_gates(
        current_v1=_metric(0.349, 0.19),
        legacy_v1=_metric(0.3, 0.2),
        current_categories=current_categories,
        legacy_categories=dg10_categories,
        lexical_categories=lexical_categories,
        mean_memory_tokens=320.001,
        safety_pass=False,
    )

    assert not any(gates.values())
