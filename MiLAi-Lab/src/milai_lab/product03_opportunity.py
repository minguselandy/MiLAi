from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OpportunityCase:
    case_id: str
    family: str
    query_type: str
    answer_turn_refs: tuple[str, ...]
    required_role_groups: tuple[tuple[str, ...], ...]
    candidate_refs: Mapping[str, tuple[str, ...]]
    candidate_count: int
    duplicate_occurrence_count: int


def channel_candidate_refs(
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[str, ...]]:
    """Project one official acquired trace into channel-owned source identities."""

    refs: dict[str, set[str]] = {"ALL": set()}
    for candidate in candidates:
        source_ref = candidate.get("source_turn_ref")
        channel_ranks = candidate.get("channel_ranks")
        if not isinstance(source_ref, str) or not isinstance(channel_ranks, Mapping):
            continue
        refs["ALL"].add(source_ref)
        for channel in channel_ranks:
            if isinstance(channel, str):
                refs.setdefault(channel, set()).add(source_ref)
        expansion = candidate.get("expansion_origin")
        if isinstance(expansion, str):
            refs.setdefault(expansion, set()).add(source_ref)
    return {key: tuple(sorted(values)) for key, values in sorted(refs.items())}


def coverage(
    source_refs: Sequence[str],
    *,
    answer_turn_refs: Sequence[str],
    required_role_groups: Sequence[Sequence[str]],
) -> tuple[float | None, float | None, tuple[int, ...]]:
    visible = set(source_refs)
    answer_turns = set(answer_turn_refs)
    turn_recall = (
        len(answer_turns.intersection(visible)) / len(answer_turns)
        if answer_turns
        else None
    )
    covered_groups = tuple(
        index
        for index, group in enumerate(required_role_groups)
        if visible.intersection(group)
    )
    role_coverage = (
        len(covered_groups) / len(required_role_groups)
        if required_role_groups
        else None
    )
    return turn_recall, role_coverage, covered_groups


def compare_mechanisms(
    baseline: Sequence[OpportunityCase],
    diagnostic: Sequence[OpportunityCase],
) -> dict[str, object]:
    """Compare four read-only official-channel projections on matched opened cases."""

    baseline_by_id = {case.case_id: case for case in baseline}
    diagnostic_by_id = {case.case_id: case for case in diagnostic}
    if (
        len(baseline_by_id) != len(baseline)
        or len(diagnostic_by_id) != len(diagnostic)
        or set(baseline_by_id) != set(diagnostic_by_id)
        or not baseline_by_id
    ):
        raise ValueError("opportunity comparison requires unique matched cases")

    mechanisms: dict[
        str, Callable[[OpportunityCase, OpportunityCase], set[str]]
    ] = {
        "A0_CURRENT_RAW_FTS": lambda base, _diag: set(
            base.candidate_refs.get("ALL", ())
        ),
        "A1_EVIDENCE_DENSE": lambda _base, diag: set(
            diag.candidate_refs.get("EVIDENCE_DENSE", ())
        ),
        "A2_FTS_DENSE_UNION": lambda _base, diag: set(
            diag.candidate_refs.get("FTS_RAW", ())
        ).union(diag.candidate_refs.get("EVIDENCE_DENSE", ())),
        "A3_SAME_SESSION_EXPANSION": lambda base, diag: set(
            base.candidate_refs.get("ALL", ())
        ).union(diag.candidate_refs.get("ADJACENT_TURNS", ())),
    }
    baseline_groups: dict[str, set[int]] = {}
    baseline_missing_group_count = 0
    for case_id, case in baseline_by_id.items():
        baseline_groups[case_id] = set(
            coverage(
                case.candidate_refs.get("ALL", ()),
                answer_turn_refs=case.answer_turn_refs,
                required_role_groups=case.required_role_groups,
            )[2]
        )
        baseline_missing_group_count += len(case.required_role_groups) - len(
            baseline_groups[case_id]
        )

    summaries: dict[str, object] = {}
    for name, candidate_set in mechanisms.items():
        case_rows: list[dict[str, object]] = []
        recovered_groups = 0
        lost_groups = 0
        recovered_types: set[str] = set()
        total_candidates = 0
        baseline_turn_values: list[float] = []
        candidate_turn_values: list[float] = []
        baseline_role_values: list[float] = []
        candidate_role_values: list[float] = []
        for case_id in sorted(baseline_by_id):
            base = baseline_by_id[case_id]
            diag = diagnostic_by_id[case_id]
            refs = candidate_set(base, diag)
            turn_recall, role_coverage, covered = coverage(
                sorted(refs),
                answer_turn_refs=base.answer_turn_refs,
                required_role_groups=base.required_role_groups,
            )
            new_groups = set(covered).difference(baseline_groups[case_id])
            lost_case_groups = baseline_groups[case_id].difference(covered)
            recovered_groups += len(new_groups)
            lost_groups += len(lost_case_groups)
            if new_groups:
                recovered_types.add(base.query_type)
            baseline_turn_recall, baseline_role_coverage, _ = coverage(
                base.candidate_refs.get("ALL", ()),
                answer_turn_refs=base.answer_turn_refs,
                required_role_groups=base.required_role_groups,
            )
            if baseline_turn_recall is not None and turn_recall is not None:
                baseline_turn_values.append(baseline_turn_recall)
                candidate_turn_values.append(turn_recall)
            if baseline_role_coverage is not None and role_coverage is not None:
                baseline_role_values.append(baseline_role_coverage)
                candidate_role_values.append(role_coverage)
            total_candidates += len(refs)
            case_rows.append(
                {
                    "case_id": case_id,
                    "family": base.family,
                    "query_type": base.query_type,
                    "candidate_count": len(refs),
                    "acquired_exact_turn_recall": turn_recall,
                    "acquired_role_coverage": role_coverage,
                    "new_required_role_group_count": len(new_groups),
                    "lost_required_role_group_count": len(lost_case_groups),
                }
            )
        baseline_turn_mean = (
            sum(baseline_turn_values) / len(baseline_turn_values)
            if baseline_turn_values
            else None
        )
        candidate_turn_mean = (
            sum(candidate_turn_values) / len(candidate_turn_values)
            if candidate_turn_values
            else None
        )
        baseline_role_mean = (
            sum(baseline_role_values) / len(baseline_role_values)
            if baseline_role_values
            else None
        )
        candidate_role_mean = (
            sum(candidate_role_values) / len(candidate_role_values)
            if candidate_role_values
            else None
        )
        gate = recovered_groups >= 3 and len(recovered_types) >= 2
        summaries[name] = {
            "case_count": len(case_rows),
            "new_required_role_group_count": recovered_groups,
            "lost_required_role_group_count": lost_groups,
            "baseline_missing_required_role_group_count": baseline_missing_group_count,
            "selected_family_role_recovery": (
                recovered_groups / baseline_missing_group_count
                if baseline_missing_group_count
                else 0.0
            ),
            "new_required_role_query_types": sorted(recovered_types),
            "total_candidate_count": total_candidates,
            "baseline_acquired_exact_turn_recall_mean": baseline_turn_mean,
            "candidate_acquired_exact_turn_recall_mean": candidate_turn_mean,
            "acquired_exact_turn_recall_delta": (
                candidate_turn_mean - baseline_turn_mean
                if baseline_turn_mean is not None and candidate_turn_mean is not None
                else None
            ),
            "baseline_acquired_role_coverage_mean": baseline_role_mean,
            "candidate_acquired_role_coverage_mean": candidate_role_mean,
            "acquired_role_coverage_delta": (
                candidate_role_mean - baseline_role_mean
                if baseline_role_mean is not None and candidate_role_mean is not None
                else None
            ),
            "selection_gate_pass": gate,
            "cases": case_rows,
        }
    return summaries


def select_allowed_treatment(comparison: Mapping[str, object]) -> str | None:
    """Select only a Goal-authorized additive Product treatment.

    A1 is a channel oracle: Dense-only may prove opportunity, but replacing the
    selected Raw FTS baseline is not an allowed Product treatment. F1 channel
    opportunity therefore maps to the additive A2 union.
    """

    allowed = ("A2_FTS_DENSE_UNION", "A3_SAME_SESSION_EXPANSION")
    passing: list[tuple[str, Mapping[str, object]]] = []
    for name in allowed:
        value = comparison.get(name)
        if isinstance(value, Mapping) and value.get("selection_gate_pass") is True:
            passing.append((name, value))
    if not passing:
        return None
    return min(
        passing,
        key=lambda item: (
            -int(str(item[1]["new_required_role_group_count"])),
            int(str(item[1]["total_candidate_count"])),
            item[0],
        ),
    )[0]


__all__ = [
    "OpportunityCase",
    "channel_candidate_refs",
    "compare_mechanisms",
    "coverage",
    "select_allowed_treatment",
]
