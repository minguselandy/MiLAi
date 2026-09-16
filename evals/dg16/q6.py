"""Pure scoring and release gates for the DG-16 product-path evaluation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from evals.paper.scorers.longmemeval import score_answer


class DG16Q6Error(RuntimeError):
    """A Q6 denominator, label boundary, or baseline comparison drifted."""


def _baseline_index(
    baseline_records: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, int], Mapping[str, Any]]:
    selected = {
        (str(record["case_id"]), int(record["token_budget"])): record
        for record in baseline_records
        if record.get("method_id") == "DG14-MILAI-MCP"
    }
    if len(selected) != 10:
        raise DG16Q6Error("frozen DG14 product baseline must contain exactly 10 cells")
    return selected


def score_product_records(
    product_records: Sequence[Mapping[str, Any]],
    fixture: Mapping[str, Any],
    baseline_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Join labels only after product execution and score the sealed 10 cells."""

    raw_cases = fixture.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 5:
        raise DG16Q6Error("opened-development scoring fixture must contain five cases")
    labels: dict[str, Mapping[str, Any]] = {}
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping) or not isinstance(
            raw_case.get("case_id"), str
        ):
            raise DG16Q6Error("scoring fixture case is malformed")
        labels[str(raw_case["case_id"])] = raw_case
    expected = {(case_id, budget) for case_id in labels for budget in (512, 2048)}
    observed = [
        (str(record.get("case_id")), int(record.get("token_budget", -1)))
        for record in product_records
    ]
    if len(observed) != 10 or set(observed) != expected or len(set(observed)) != 10:
        raise DG16Q6Error("product result denominator or cell identity drifted")

    baseline = _baseline_index(baseline_records)
    scored: list[dict[str, Any]] = []
    for record in product_records:
        case_id = str(record["case_id"])
        budget = int(record["token_budget"])
        label = labels[case_id]
        answers = label.get("answers")
        atoms = label.get("required_atoms")
        if not isinstance(answers, list) or not answers or not isinstance(atoms, list):
            raise DG16Q6Error("scoring fixture lacks answers or evidence atoms")
        available_refs = {
            str(value) for value in record.get("selected_source_refs", [])
        } | {str(value) for value in record.get("derived_source_turn_refs", [])}
        required_refs = {
            str(atom["source_turn_ref"])
            for atom in atoms
            if isinstance(atom, Mapping) and isinstance(atom.get("source_turn_ref"), str)
        }
        if len(required_refs) != len(atoms):
            raise DG16Q6Error("scoring fixture evidence atom is malformed")
        atom_hits = sorted(required_refs & available_refs)
        answer_score = score_answer(
            str(record["answer"]), [str(answer) for answer in answers]
        )
        baseline_score = baseline[(case_id, budget)].get("answer_score")
        if not isinstance(baseline_score, Mapping):
            raise DG16Q6Error("frozen DG14 baseline score is malformed")
        scored.append(
            {
                **dict(record),
                "answer_score": answer_score,
                "required_atom_count": len(required_refs),
                "retrieved_atom_count": len(atom_hits),
                "retrieved_atom_refs": atom_hits,
                "evidence_atom_recall": round(
                    len(atom_hits) / len(required_refs), 9
                ),
                "dg14_baseline_exact_match": int(
                    baseline_score.get("exact_match", 0)
                ),
            }
        )
    scored.sort(key=lambda item: (int(item["token_budget"]), str(item["case_id"])))

    grouped: defaultdict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for record in scored:
        grouped[int(record["token_budget"])].append(record)
    summaries: dict[str, Any] = {}
    for budget in (512, 2048):
        records = grouped[budget]
        exact = sum(int(record["answer_score"]["exact_match"]) for record in records)
        baseline_exact = sum(
            int(record["dg14_baseline_exact_match"]) for record in records
        )
        regressions = [
            str(record["case_id"])
            for record in records
            if record["dg14_baseline_exact_match"] == 1
            and record["answer_score"]["exact_match"] == 0
        ]
        summaries[str(budget)] = {
            "case_count": len(records),
            "exact_match_count": exact,
            "exact_match": round(exact / len(records), 9),
            "normalized_f1": round(
                sum(float(record["answer_score"]["normalized_f1"]) for record in records)
                / len(records),
                9,
            ),
            "evidence_atom_recall": round(
                sum(int(record["retrieved_atom_count"]) for record in records)
                / sum(int(record["required_atom_count"]) for record in records),
                9,
            ),
            "dg14_baseline_exact_match_count": baseline_exact,
            "exact_match_delta_count": exact - baseline_exact,
            "baseline_regression_case_ids": regressions,
        }
    return {"records": scored, "summaries": summaries}


def evaluate_release_gate(
    summaries: Mapping[str, Mapping[str, Any]],
    safety: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    """Evaluate the predeclared five-case quality and nonzero safety gates."""

    required_safety = {
        "canonical_promotion",
        "cross_case_contamination",
        "label_leakage",
        "permission_denied_bypass",
        "silent_fallback",
        "stale_revoked_evidence_acceptance",
        "wrong_scope_acceptance",
    }
    if set(safety) != required_safety:
        raise DG16Q6Error("Q6 safety gate field set drifted")
    safety_pass = True
    for trial in safety.values():
        accepted = trial.get("accepted")
        denominator = trial.get("denominator")
        if (
            not isinstance(accepted, int)
            or isinstance(accepted, bool)
            or not isinstance(denominator, int)
            or isinstance(denominator, bool)
            or accepted != 0
            or denominator <= 0
        ):
            safety_pass = False
    summary_2048 = summaries.get("2048", {})
    checks = {
        "five_of_five_exact_match_at_2048": summary_2048.get("exact_match_count") == 5,
        "no_dg14_correct_case_regression_at_2048": summary_2048.get(
            "baseline_regression_case_ids"
        )
        == [],
        "all_safety_denominators_nonzero_and_zero_acceptance": safety_pass,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
    }


__all__ = ["DG16Q6Error", "evaluate_release_gate", "score_product_records"]
