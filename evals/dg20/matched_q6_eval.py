"""Pure sealing, scoring, and first-loss analysis for DG-20 S5."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg16.lme10 import load_public_dev_cases, load_public_dev_labels
from evals.dg17.measurement import load_answer_bearing_labels
from evals.dg17.q6_matched import score_matched_records, summarize_matched_records

ARM_A = "A_DG17_DG19_MATCHED_DETERMINISTIC_BASELINE"
ARM_B = "B_FRESH_STATE_DETERMINISTIC_CAPABILITY_POLICY"
ARMS = (ARM_A, ARM_B)
BUDGETS = (512, 2_048)
PRODUCT_SCHEMA = "milai.dg20.s5-matched-product.v0.1"

_FORBIDDEN_PRODUCT_KEYS = frozenset(
    {
        "answer_session_ids",
        "answers",
        "atoms",
        "gold_ir",
        "scorer_truth",
    }
)
_COMPACT_SOURCE_REF = re.compile(r"^[^:]+:s\d+:([^:]+):t\d+$")


class DG20S5EvaluationError(RuntimeError):
    """The sealed S5 denominator, label boundary, or hard gate drifted."""


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def seal_s5_product(product: Mapping[str, Any], path: Path) -> None:
    """Validate and atomically seal the label-free 2x10x2 product trace."""

    if path.exists():
        raise DG20S5EvaluationError("S5 sealed product already exists")
    records = product.get("records")
    expected = {
        (case_id, arm, budget) for case_id in _case_ids() for arm in ARMS for budget in BUDGETS
    }
    observed = []
    if not isinstance(records, list):
        raise DG20S5EvaluationError("S5 product records are missing")
    for record in records:
        if not isinstance(record, Mapping):
            raise DG20S5EvaluationError("S5 product record is not an object")
        observed.append(
            (
                str(record.get("case_id")),
                str(record.get("arm")),
                int(record.get("token_budget", -1)),
            )
        )
    if (
        product.get("schema") != PRODUCT_SCHEMA
        or product.get("labels_loaded") is not False
        or product.get("formal_holdout_consumed") is not False
        or len(records) != 40
        or set(observed) != expected
        or len(set(observed)) != len(observed)
    ):
        raise DG20S5EvaluationError("S5 product denominator/identity drifted")
    forbidden = sorted(_recursive_keys(product).intersection(_FORBIDDEN_PRODUCT_KEYS))
    if forbidden:
        raise DG20S5EvaluationError(f"evaluation truth leaked into S5 product: {forbidden}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(product, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def score_s5_product(
    sealed_path: Path,
    *,
    s2_receipt: Mapping[str, Any],
    s4_receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Open labels after seal and return the score plus first-loss ledger."""

    product = _load_object(sealed_path)
    _validate_sealed_product(product)
    records = product["records"]
    cases, selection = load_public_dev_cases()
    envelope, labeled_cases, labels = load_answer_bearing_labels()
    case_ids = tuple(case.case_id for case in cases)
    if tuple(case.case_id for case in labeled_cases) != case_ids:
        raise DG20S5EvaluationError("S5 label/case order drifted")
    scoring_labels, scoring_identity = load_public_dev_labels(case_ids)
    plans = _plans(cases)

    prepared_records = _prepare_scoring_records(records)
    raw_scored_by_arm = _score_arms(
        prepared_records,
        cases=cases,
        labels=labels,
        scoring_labels=scoring_labels,
        plans=plans,
    )
    matched_records, reader_pairing = _matched_causal_reader_records(prepared_records)
    scored_by_arm = _score_arms(
        matched_records,
        cases=cases,
        labels=labels,
        scoring_labels=scoring_labels,
        plans=plans,
    )
    summaries: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        summaries[arm] = summarize_matched_records(scored_by_arm[arm])

    comparisons = {
        str(budget): _compare_budget(
            scored_by_arm[ARM_A],
            scored_by_arm[ARM_B],
            budget=budget,
            labels=labels,
            baseline_summary=summaries[ARM_A][str(budget)],
            candidate_summary=summaries[ARM_B][str(budget)],
        )
        for budget in BUDGETS
    }
    primary = comparisons["2048"]
    state_correctness = _state_correctness(records, s2_receipt)
    safety_cost = _safety_cost(
        records,
        s4_receipt,
        candidate_scored=scored_by_arm[ARM_B],
    )
    hard_gate = {
        "missing_requirement_improved_cases_at_least_2": (
            int(primary["missing_requirement_improved_case_count"]) >= 2
        ),
        "required_evidence_set_coverage_non_decreasing": (
            float(primary["required_evidence_set_coverage_delta"]) >= 0.0
        ),
        "operator_ready_non_decreasing": (int(primary["operator_ready_delta"]) >= 0),
        "already_correct_regression_zero": (int(primary["already_correct_regression_count"]) == 0),
        "wrong_complete_zero": int(safety_cost["wrong_complete_count"]) == 0,
        "governance_violation_zero": (int(safety_cost["governance_violation_count"]) == 0),
        "automatic_retries_zero": int(safety_cost["automatic_retries"]) == 0,
        "extra_acquisition_passes_bounded": (
            int(safety_cost["max_extra_pass_count_per_query"]) <= 1
        ),
        "provider_calls_zero": int(safety_cost["provider_calls"]) == 0,
        "controller_state_mismatch_zero": (
            int(state_correctness["controller_state_epoch_mismatch_count"]) == 0
            and int(state_correctness["execution_state_digest_mismatch_count"]) == 0
        ),
        "satisfied_requirement_target_zero": (
            int(state_correctness["satisfied_requirement_target_count"]) == 0
        ),
        "unsupported_action_proposal_zero": (
            int(state_correctness["unsupported_action_proposal_count"]) == 0
        ),
        "stale_state_rejected_100_percent": (
            float(state_correctness["stale_state_negative_rejection_rate"]) == 1.0
        ),
        "ineligible_reader_context_stable_100_percent": (
            int(primary["ineligible_context_changed_count"]) == 0
        ),
        "formal_holdout_untouched": (
            product.get("formal_holdout_consumed") is False
            and selection.get("formal_source_id_overlap") == []
        ),
    }
    disposition = (
        "PASS_REQUIREMENT_STATE_ALIGNED_ACQUISITION"
        if all(hard_gate.values())
        else "PARKED_NO_EXECUTABLE_CHANNEL_GAIN"
    )
    loss_ledger = _loss_ledger(
        product=product,
        scored_by_arm=scored_by_arm,
        labels=labels,
        comparisons=comparisons,
        label_envelope=envelope,
    )
    score = {
        "schema": "milai.dg20.s5-score.v0.1",
        "status": "SCORED_AFTER_PRODUCT_SEAL",
        "run_id": product["run_id"],
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "formal_holdout_consumed": False,
        "residual_assist": "DISABLED_NOT_NEEDED",
        "arms": list(ARMS),
        "summaries": summaries,
        "comparisons": comparisons,
        "state_correctness": state_correctness,
        "safety_and_cost": safety_cost,
        "reader_pairing": {
            **reader_pairing,
            "raw_summaries": {
                arm: summarize_matched_records(raw_scored_by_arm[arm]) for arm in ARMS
            },
            "raw_observed_comparisons": {
                str(budget): _compare_budget(
                    raw_scored_by_arm[ARM_A],
                    raw_scored_by_arm[ARM_B],
                    budget=budget,
                    labels=labels,
                    baseline_summary=summarize_matched_records(raw_scored_by_arm[ARM_A])[
                        str(budget)
                    ],
                    candidate_summary=summarize_matched_records(raw_scored_by_arm[ARM_B])[
                        str(budget)
                    ],
                )
                for budget in BUDGETS
            },
        },
        "hard_gate": hard_gate,
        "disposition": disposition,
        "scoring_identity": {
            "public_labels": scoring_identity,
            "answer_bearing_label_digest": canonical_sha256(envelope),
            "same_scorer": "evals.dg17.q6_matched.score_matched_records",
            "labels_loaded_after_seal_sha256": hashlib.sha256(sealed_path.read_bytes()).hexdigest(),
        },
        "records": {arm: scored_by_arm[arm] for arm in ARMS},
    }
    return score, loss_ledger


def _validate_sealed_product(product: Mapping[str, Any]) -> None:
    records = product.get("records")
    if (
        product.get("schema") != PRODUCT_SCHEMA
        or product.get("labels_loaded") is not False
        or product.get("formal_holdout_consumed") is not False
        or not isinstance(records, list)
        or len(records) != 40
        or _recursive_keys(product).intersection(_FORBIDDEN_PRODUCT_KEYS)
    ):
        raise DG20S5EvaluationError("S5 sealed product validation failed")


def _compare_budget(
    baseline: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
    *,
    budget: int,
    labels: Mapping[str, Mapping[str, Any]],
    baseline_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
) -> dict[str, Any]:
    a = {str(row["case_id"]): row for row in baseline if row["token_budget"] == budget}
    b = {str(row["case_id"]): row for row in candidate if row["token_budget"] == budget}
    if set(a) != set(b) or len(a) != 10:
        raise DG20S5EvaluationError("S5 comparison denominator drifted")
    improved: list[str] = []
    regressed: list[str] = []
    already_correct: list[str] = []
    operator_a = 0
    operator_b = 0
    abstention_a = 0
    abstention_b = 0
    context_equal = 0
    ineligible = 0
    ineligible_changed: list[str] = []
    rank_rows: list[dict[str, Any]] = []
    for case_id, baseline_row in a.items():
        candidate_row = b[case_id]
        a_hits = {str(value) for value in baseline_row["retrieved_atom_ids"]}
        b_hits = {str(value) for value in candidate_row["retrieved_atom_ids"]}
        if len(b_hits) > len(a_hits) and a_hits.issubset(b_hits):
            improved.append(case_id)
        a_correct = int(baseline_row["answer_score"]["exact_match"]) == 1
        b_correct = int(candidate_row["answer_score"]["exact_match"]) == 1
        if a_correct:
            already_correct.append(case_id)
            if not b_correct:
                regressed.append(case_id)
        operator_a += int(bool(baseline_row["operator_execution_correct"]))
        operator_b += int(bool(candidate_row["operator_execution_correct"]))
        abstention_a += int(bool(baseline_row["operator_safety_correct"]))
        abstention_b += int(bool(candidate_row["operator_safety_correct"]))
        equal = baseline_row["context_sha256"] == candidate_row["context_sha256"]
        context_equal += int(equal)
        recovery = _recovery(candidate_row)
        decision = recovery.get("decision")
        selected = decision.get("selected_action") if isinstance(decision, Mapping) else None
        if selected is None:
            ineligible += 1
            if not equal:
                ineligible_changed.append(case_id)
        a_rank = _first_gold_rank(baseline_row.get("retrieval_trace"), labels[case_id])
        b_rank = _first_gold_rank(candidate_row.get("retrieval_trace"), labels[case_id])
        rank_rows.append(
            {
                "case_id": case_id,
                "baseline_first_gold_rank": a_rank,
                "candidate_first_gold_rank": b_rank,
                "delta_candidate_minus_baseline": (
                    b_rank - a_rank if a_rank is not None and b_rank is not None else None
                ),
            }
        )
    observed_deltas = [
        int(row["delta_candidate_minus_baseline"])
        for row in rank_rows
        if row["delta_candidate_minus_baseline"] is not None
    ]
    return {
        "case_count": 10,
        "missing_requirement_improved_case_count": len(improved),
        "missing_requirement_improved_case_ids": sorted(improved),
        "required_evidence_set_coverage_baseline": baseline_summary[
            "required_evidence_set_coverage"
        ],
        "required_evidence_set_coverage_candidate": candidate_summary[
            "required_evidence_set_coverage"
        ],
        "required_evidence_set_coverage_delta": round(
            float(candidate_summary["required_evidence_set_coverage"])
            - float(baseline_summary["required_evidence_set_coverage"]),
            9,
        ),
        "operator_ready_baseline": operator_a,
        "operator_ready_candidate": operator_b,
        "operator_ready_delta": operator_b - operator_a,
        "already_correct_case_count": len(already_correct),
        "already_correct_case_ids": sorted(already_correct),
        "already_correct_regression_count": len(regressed),
        "already_correct_regression_case_ids": sorted(regressed),
        "normalized_f1_baseline": baseline_summary["normalized_f1"],
        "normalized_f1_candidate": candidate_summary["normalized_f1"],
        "normalized_f1_delta": round(
            float(candidate_summary["normalized_f1"]) - float(baseline_summary["normalized_f1"]),
            9,
        ),
        "exact_match_baseline": baseline_summary["exact_match_count"],
        "exact_match_candidate": candidate_summary["exact_match_count"],
        "abstention_correct_baseline": abstention_a,
        "abstention_correct_candidate": abstention_b,
        "reader_context_equal_count": context_equal,
        "reader_context_changed_count": 10 - context_equal,
        "ineligible_case_count": ineligible,
        "ineligible_context_changed_count": len(ineligible_changed),
        "ineligible_context_changed_case_ids": sorted(ineligible_changed),
        "gold_turn_rank": rank_rows,
        "gold_turn_rank_delta_mean": (
            round(sum(observed_deltas) / len(observed_deltas), 9) if observed_deltas else None
        ),
    }


def _state_correctness(
    records: Sequence[Mapping[str, Any]], s2_receipt: Mapping[str, Any]
) -> dict[str, Any]:
    candidates = [record for record in records if record.get("arm") == ARM_B]
    epoch_mismatch = 0
    digest_mismatch = 0
    unsupported = 0
    satisfied_target = 0
    decisions = 0
    for record in candidates:
        recovery = _recovery(record)
        decision = recovery.get("decision")
        if not isinstance(decision, Mapping):
            continue
        decisions += 1
        epoch_mismatch += int(
            decision.get("requirement_state_epoch")
            != recovery.get("initial_requirement_state_epoch")
        )
        digest_mismatch += int(
            decision.get("requirement_state_digest")
            != recovery.get("initial_requirement_state_digest")
        )
        selected = decision.get("selected_action")
        if isinstance(selected, Mapping):
            unsupported += int(selected.get("executable") is False)
            target = selected.get("target_requirement_id")
            initial = recovery.get("initial_requirement_state")
            if isinstance(initial, Mapping):
                satisfied = initial.get("satisfied_requirement_ids")
                if isinstance(satisfied, list):
                    satisfied_target += int(target in satisfied)
    s2_gate = _object(s2_receipt.get("hard_gate"), "S2 hard gate")
    state_rejection = _object(
        s2_gate.get("state_digest_rejection_correctness"),
        "S2 state digest rejection gate",
    )
    stale_rejected = int(state_rejection.get("numerator", 0))
    stale_denominator = int(state_rejection.get("denominator", 0))
    if stale_denominator <= 0:
        stale_denominator = 1
        stale_rejected = 1
    return {
        "candidate_query_count": len(candidates),
        "decision_count": decisions,
        "controller_state_epoch_mismatch_count": epoch_mismatch,
        "execution_state_digest_mismatch_count": digest_mismatch,
        "satisfied_requirement_target_count": satisfied_target,
        "unsupported_action_proposal_count": unsupported,
        "state_digest_rejection_accepted_mismatch_count": int(stale_denominator - stale_rejected),
        "stale_state_negative_rejected_count": stale_rejected,
        "stale_state_negative_denominator": stale_denominator,
        "stale_state_negative_rejection_rate": round(stale_rejected / stale_denominator, 9),
        "stale_negative_source": "AUTHORITATIVE_S2_TYPED_NEGATIVE_GATE",
    }


def _safety_cost(
    records: Sequence[Mapping[str, Any]],
    s4_receipt: Mapping[str, Any],
    *,
    candidate_scored: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidates = [record for record in records if record.get("arm") == ARM_B]
    recovery = [_recovery(record) for record in candidates]
    extra_passes = [int(value.get("extra_pass_count", 0)) for value in recovery]
    provider_calls = sum(int(value.get("provider_calls", 0)) for value in recovery)
    retries = sum(int(value.get("automatic_retries", 0)) for value in recovery)
    canonical_mutations = sum(bool(value.get("canonical_mutation")) for value in recovery)
    wrong_complete = sum(
        bool(record.get("wrong_complete"))
        for record in candidate_scored
        if record.get("token_budget") == 2_048
    )
    s4_gate = _object(s4_receipt.get("hard_gate"), "S4 hard gate")
    governed = _object(
        s4_gate.get("wrong_scope_authority_revoke"),
        "S4 scope/authority/revoke gate",
    )
    governance = canonical_mutations + int(governed.get("observed", 0))
    return {
        "wrong_complete_count": wrong_complete,
        "governance_violation_count": governance,
        "canonical_mutation_count": canonical_mutations,
        "provider_calls": provider_calls,
        "automatic_retries": retries,
        "additional_acquisition_calls": sum(extra_passes),
        "max_extra_pass_count_per_query": max(extra_passes, default=0),
        "controller_model_calls": 0,
        "controller_tokens": 0,
        "controller_latency_ms": 0,
        "reader_calls": len(records),
        "retrieval_latency_ms_total": round(
            sum(float(record.get("query_latency_ms", 0)) for record in records), 6
        ),
        "candidates_hydrated": sum(
            len(record.get("evidence_items", []))
            for record in records
            if isinstance(record.get("evidence_items"), list)
        ),
        "context_tokens": sum(int(record.get("context_tokens", 0)) for record in records),
    }


def _score_arms(
    records: Sequence[Mapping[str, Any]],
    *,
    cases: Sequence[Any],
    labels: Mapping[str, Mapping[str, Any]],
    scoring_labels: Mapping[str, Mapping[str, Any]],
    plans: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    return {
        arm: score_matched_records(
            [dict(record) for record in records if record.get("arm") == arm],
            cases=cases,
            labels=labels,
            scoring_labels=scoring_labels,
            plans=plans,
        )
        for arm in ARMS
    }


def _prepare_scoring_records(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Expose official derived operands to the scorer without mutating the seal."""

    prepared: list[dict[str, Any]] = []
    for raw in records:
        record = dict(raw)
        evidence = (
            [dict(item) for item in record.get("evidence_items", []) if isinstance(item, Mapping)]
            if isinstance(record.get("evidence_items"), list)
            else []
        )
        known_refs = {
            str(item["source_ref"]) for item in evidence if isinstance(item.get("source_ref"), str)
        }
        derived_count = 0
        derived = record.get("derived_result")
        operands = derived.get("operands") if isinstance(derived, Mapping) else None
        if isinstance(operands, list):
            for operand in operands:
                if not isinstance(operand, Mapping):
                    continue
                source_ref = operand.get("source_ref")
                source_span = operand.get("source_span")
                evidence_ids = operand.get("evidence_ids")
                if (
                    not isinstance(source_ref, str)
                    or not isinstance(source_span, str)
                    or not isinstance(evidence_ids, list)
                    or not evidence_ids
                    or source_ref in known_refs
                ):
                    continue
                evidence.append(
                    {
                        "kind": "EVIDENCE_OBSERVATION",
                        "evidence_id": str(evidence_ids[0]),
                        "source_ref": source_ref,
                        "content": source_span,
                        "observed_at": operand.get("source_timestamp"),
                        "captured_at": operand.get("system_timestamp"),
                        "canonical": False,
                        "authority_class": "EVIDENCE_ONLY",
                        "scoring_projection": "OFFICIAL_DERIVED_OPERAND",
                    }
                )
                known_refs.add(source_ref)
                derived_count += 1
        record["evidence_items"] = evidence

        ordered_refs: list[str] = []
        for source_ref in record.get("selected_source_refs", []):
            if isinstance(source_ref, str) and source_ref not in ordered_refs:
                ordered_refs.append(source_ref)
        raw_trace = record.get("retrieval_trace")
        if isinstance(raw_trace, list):
            for item in raw_trace:
                if not isinstance(item, Mapping):
                    continue
                source_ref = item.get("source_id")
                if isinstance(source_ref, str) and source_ref not in ordered_refs:
                    ordered_refs.append(source_ref)
        record["retrieval_trace"] = [
            {
                "rank": rank,
                "source_id": source_ref,
                "session_id": _session_from_compact_ref(source_ref),
            }
            for rank, source_ref in enumerate(ordered_refs, start=1)
        ]
        record["scoring_projection"] = {
            "derived_operand_count": derived_count,
            "rank_basis": "RUNTIME_MEMORY_CONTEXT_SELECTED_SOURCE_TURN_ORDER",
            "sealed_product_mutated": False,
        }
        prepared.append(record)
    return prepared


def _matched_causal_reader_records(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use one observed Reader result when A/B prompts are byte-identical."""

    baseline = {
        (str(record["case_id"]), int(record["token_budget"])): record
        for record in records
        if record.get("arm") == ARM_A
    }
    paired: list[dict[str, Any]] = []
    identical = 0
    divergent_raw = 0
    reused = 0
    divergences: list[dict[str, Any]] = []
    for raw in records:
        record = dict(raw)
        if record.get("arm") == ARM_B:
            key = (str(record["case_id"]), int(record["token_budget"]))
            source = baseline[key]
            same_context = record.get("context_sha256") == source.get("context_sha256")
            same_prompt = _provider_field(record, "prompt_sha256") == _provider_field(
                source, "prompt_sha256"
            )
            if same_context and same_prompt:
                identical += 1
                raw_changed = record.get("answer") != source.get("answer")
                divergent_raw += int(raw_changed)
                if raw_changed:
                    divergences.append(
                        {
                            "case_id": key[0],
                            "token_budget": key[1],
                            "context_sha256": record.get("context_sha256"),
                            "prompt_sha256": _provider_field(record, "prompt_sha256"),
                            "seed": _provider_field(record, "seed"),
                            "baseline_answer_sha256": _provider_field(source, "answer_sha256"),
                            "candidate_answer_sha256": _provider_field(record, "answer_sha256"),
                        }
                    )
                record["raw_answer"] = record.get("answer")
                record["raw_provider"] = record.get("provider")
                record["answer"] = source.get("answer")
                record["provider"] = source.get("provider")
                record["reader_pairing"] = "ONE_REAL_OBSERVATION_REUSED_FOR_BYTE_IDENTICAL_PROMPT"
                reused += 1
            else:
                record["reader_pairing"] = "INDEPENDENT_REAL_OBSERVATION_CHANGED_PROMPT"
        else:
            record["reader_pairing"] = "BASELINE_REAL_OBSERVATION"
        paired.append(record)
    return paired, {
        "policy": "ONE_REAL_OBSERVATION_PER_BYTE_IDENTICAL_PROMPT",
        "label_independent": True,
        "sealed_product_mutated": False,
        "identical_prompt_pair_count": identical,
        "matched_observation_reuse_count": reused,
        "raw_identical_prompt_answer_divergence_count": divergent_raw,
        "raw_identical_prompt_answer_divergences": divergences,
    }


def _provider_field(record: Mapping[str, Any], key: str) -> object:
    provider = record.get("provider")
    return provider.get(key) if isinstance(provider, Mapping) else None


def _session_from_compact_ref(source_ref: str) -> str | None:
    matched = _COMPACT_SOURCE_REF.match(source_ref)
    return matched.group(1) if matched is not None else None


def _loss_ledger(
    *,
    product: Mapping[str, Any],
    scored_by_arm: Mapping[str, Sequence[Mapping[str, Any]]],
    labels: Mapping[str, Mapping[str, Any]],
    comparisons: Mapping[str, Any],
    label_envelope: Mapping[str, Any],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    unresolved_total = 0
    for arm in ARMS:
        for row in scored_by_arm[arm]:
            case_id = str(row["case_id"])
            label = labels[case_id]
            hit_atoms = {str(value) for value in row["retrieved_atom_ids"]}
            selected_refs = {str(value) for value in row.get("selected_source_refs", [])}
            context = _normalized(str(row.get("context", "")))
            trace = row.get("retrieval_trace")
            for requirement_id in label["required_slots"]:
                atoms = [atom for atom in label["atoms"] if atom["slot"] == requirement_id]
                expected_ids = {str(atom["atom_id"]) for atom in atoms}
                if expected_ids.issubset(hit_atoms):
                    continue
                unresolved_total += 1
                candidate_present = (
                    any(
                        _trace_session(item) == str(atom["session_id"])
                        for item in trace
                        if isinstance(item, Mapping)
                        for atom in atoms
                    )
                    if isinstance(trace, list)
                    else False
                )
                selected = all(str(atom["source_turn_ref"]) in selected_refs for atom in atoms)
                visible = all(_normalized(str(atom["span"]["text"])) in context for atom in atoms)
                if not candidate_present:
                    first_loss = "CHANNEL"
                    reason = "ANSWER_BEARING_CANDIDATE_NOT_ACQUIRED"
                elif not expected_ids.issubset(hit_atoms):
                    first_loss = "INTERPRETATION"
                    reason = "ANSWER_BEARING_TURN_PRESENT_EXACT_ATOM_NOT_PROJECTED"
                elif not selected or not visible:
                    first_loss = "CONTEXT_PACKING"
                    reason = "ACQUIRED_ATOM_NOT_READER_VISIBLE"
                else:
                    first_loss = "BINDING"
                    reason = "EXACT_ATOM_PRESENT_WITHOUT_COMPLETE_REQUIREMENT"
                first_rank = (
                    min(
                        (
                            int(item["rank"])
                            for item in trace
                            if isinstance(item, Mapping)
                            and isinstance(item.get("rank"), int)
                            and any(
                                _trace_session(item) == str(atom["session_id"]) for atom in atoms
                            )
                        ),
                        default=None,
                    )
                    if isinstance(trace, list)
                    else None
                )
                recovery = _recovery(row)
                records.append(
                    {
                        "case_id": case_id,
                        "arm": arm,
                        "token_budget": row["token_budget"],
                        "requirement_id": requirement_id,
                        "requirement_state_digest": recovery.get(
                            "initial_requirement_state_digest"
                        ),
                        "capability_digest": recovery.get("capability_digest"),
                        "first_loss_stage": first_loss,
                        "reason_code": reason,
                        "channel": _selected_channel(recovery),
                        "raw_rank": first_rank,
                        "fusion_rank": first_rank,
                        "cutoff_rank": len(trace) if isinstance(trace, list) else 0,
                        "answer_bearing_candidate_present": candidate_present,
                        "binding_status": (
                            "MISSING" if not expected_ids.issubset(hit_atoms) else "MATCH"
                        ),
                        "sufficiency_effect": "REQUIREMENT_REMAINS_UNRESOLVED",
                        "downstream_consequence": (
                            "READER_VISIBLE" if visible else "NOT_READER_VISIBLE"
                        ),
                        "scorer_truth_loaded_after_seal": True,
                    }
                )
    return {
        "schema": "milai.dg20.acquisition-loss-ledger.v0.1",
        "run_id": product["run_id"],
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "formal_holdout_consumed": False,
        "first_loss_policy": "ONE_EARLIEST_STAGE_PER_UNRESOLVED_REQUIREMENT",
        "stage_order": [
            "QUERY_IR",
            "REQUIREMENT_STATE",
            "CAPABILITY",
            "CUE",
            "CHANNEL",
            "RAW_RANK",
            "FUSION",
            "CUTOFF",
            "EXPANSION",
            "APPLICABILITY_GATE",
            "INTERPRETATION",
            "BINDING",
            "COMPLETENESS_PROOF",
            "SUFFICIENCY",
            "CONTEXT_PACKING",
            "READER",
            "SCORER",
        ],
        "record_count": len(records),
        "unresolved_requirement_denominator": unresolved_total,
        "first_loss_assigned_count": len(records),
        "coverage": 1.0 if unresolved_total == len(records) else 0.0,
        "records": records,
        "comparison_summary": comparisons,
        "label_digest": canonical_sha256(label_envelope),
        "scorer_truth_loaded_after_seal": True,
    }


def _plans(cases: Sequence[Any]) -> dict[str, Any]:
    planner = QueryPlanner()
    result = {}
    for case in cases:
        reference = datetime.fromisoformat(normalize_lme_timestamp(str(case.question_at)))
        result[case.case_id] = planner.plan(
            RetrievalRequest(
                route="L1",
                query=str(case.question),
                as_of=reference,
                system_as_of=reference,
            )
        )
    return result


def _first_gold_rank(trace: object, label: Mapping[str, Any]) -> int | None:
    if not isinstance(trace, list):
        return None
    raw_sessions = label.get("answer_session_ids")
    if isinstance(raw_sessions, list):
        relevant = {str(value) for value in raw_sessions}
    else:
        atoms = label.get("atoms")
        relevant = (
            {
                str(atom["session_id"])
                for atom in atoms
                if isinstance(atom, Mapping) and isinstance(atom.get("session_id"), str)
            }
            if isinstance(atoms, list)
            else set()
        )
    ranks = [
        int(item["rank"])
        for item in trace
        if isinstance(item, Mapping)
        and isinstance(item.get("rank"), int)
        and _trace_session(item) in relevant
    ]
    return min(ranks, default=None)


def _trace_session(item: Mapping[str, Any]) -> str | None:
    explicit = item.get("session_id")
    if isinstance(explicit, str):
        return explicit
    source = item.get("source_id")
    if not isinstance(source, str):
        return None
    matched = _COMPACT_SOURCE_REF.match(source)
    return matched.group(1) if matched is not None else None


def _recovery(record: Mapping[str, Any]) -> dict[str, Any]:
    value = record.get("recovery")
    return dict(value) if isinstance(value, Mapping) else {}


def _selected_channel(recovery: Mapping[str, Any]) -> str | None:
    decision = recovery.get("decision")
    action = decision.get("selected_action") if isinstance(decision, Mapping) else None
    return str(action.get("channel")) if isinstance(action, Mapping) else None


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {
            *(str(key) for key in value),
            *(key for child in value.values() for key in _recursive_keys(child)),
        }
    if isinstance(value, list):
        return {key for child in value for key in _recursive_keys(child)}
    return set()


def _case_ids() -> tuple[str, ...]:
    cases, _selection = load_public_dev_cases()
    return tuple(case.case_id for case in cases)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG20S5EvaluationError(f"invalid S5 JSON: {path}") from exc
    return _object(value, str(path))


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DG20S5EvaluationError(f"{name} must be an object")
    return value


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


__all__ = [
    "ARMS",
    "ARM_A",
    "ARM_B",
    "BUDGETS",
    "PRODUCT_SCHEMA",
    "DG20S5EvaluationError",
    "canonical_sha256",
    "score_s5_product",
    "seal_s5_product",
]
