"""Sealed S2 scorer for deterministic capability-constrained recovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from evals.dg17.q1r_causality import canonical_sha256
from evals.dg20.official_channel_oracle import opened_dev_requirement_crosswalk

PRODUCT_SCHEMA = "milai.dg20.s2-deterministic-policy-product.v0.1"
SEALED_SCHEMA = "milai.dg20.s2-sealed-deterministic-policy.v0.1"
SCORE_SCHEMA = "milai.dg20.s2-deterministic-policy-score.v0.1"
_FORBIDDEN_KEYS = frozenset(
    {
        "answer",
        "answers",
        "answer_bearing",
        "atoms",
        "gold",
        "gold_ir",
        "join_relations",
    }
)
_STATUS_RANK = {
    "MISSING": 5,
    "UNRESOLVED": 4,
    "UNDER_COVERED": 3,
    "COMPLETENESS_PROOF_MISSING": 2,
    "CONTESTED": 1,
    "SATISFIED": 0,
}


class DG20S2EvaluationError(RuntimeError):
    """S2 phase boundary, denominator, or product trace drifted."""


def seal_s2_product(product: Mapping[str, Any], path: Path) -> dict[str, Any]:
    payload = dict(product)
    _validate_product(payload)
    if path.exists():
        raise DG20S2EvaluationError("S2 sealed product already exists")
    envelope = {
        "schema": SEALED_SCHEMA,
        "status": "SEALED_BEFORE_SCORING",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / SEALED_PRODUCT_PLANE",
        "formal_holdout_consumed": False,
        "label_fields_available": False,
        "product_sha256": canonical_sha256(payload),
        "product": payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(_canonical_bytes(envelope))
    return envelope


def score_s2_product(sealed_path: Path, *, labels_path: Path) -> dict[str, Any]:
    envelope = _load_object(sealed_path)
    product = _validated_product(envelope)
    labels_envelope = _load_object(labels_path)
    labels = {
        str(item["case_id"]): item
        for item in _mapping_list(labels_envelope.get("cases"), "labels.cases")
    }
    cases = _mapping_list(product.get("cases"), "product.cases")
    if set(labels) != {str(item.get("case_id")) for item in cases}:
        raise DG20S2EvaluationError("S2 scorer denominator drifted")
    scored = [_score_case(case, labels[str(case["case_id"])]) for case in cases]

    selected = [item for item in scored if item["selected_action"]]
    baseline_target_hits = sum(int(item["baseline_target_candidate_hits"]) for item in selected)
    final_target_hits = sum(int(item["final_target_candidate_hits"]) for item in selected)
    target_gold_count = sum(int(item["target_gold_count"]) for item in selected)
    baseline_binding_hits = sum(int(item["baseline_target_binding_hits"]) for item in selected)
    final_binding_hits = sum(int(item["final_target_binding_hits"]) for item in selected)
    total_gold = sum(int(item["required_gold_count"]) for item in scored)
    baseline_covered = sum(int(item["baseline_required_evidence_hits"]) for item in scored)
    final_covered = sum(int(item["final_required_evidence_hits"]) for item in scored)
    improved_case_ids = sorted(
        str(item["case_id"])
        for item in selected
        if int(item["target_binding_gain"]) > 0 or item["target_status_improved"] is True
    )
    proposal_count = sum(int(item["proposal_count"]) for item in scored)
    execution_count = sum(int(item["extra_pass_count"]) for item in scored)
    stale_negative_count = sum(int(item["stale_negative_count"]) for item in scored)
    stale_rejected_count = sum(int(item["stale_rejected_count"]) for item in scored)
    new_count = sum(int(item["new_candidate_count"]) for item in scored)
    useful_count = sum(int(item["useful_new_candidate_count"]) for item in scored)
    new_regions = sum(int(item["new_region_count"]) for item in scored)
    repeated_regions = sum(int(item["repeated_region_count"]) for item in scored)
    baseline_operator_ready = sum(bool(item["baseline_operator_ready"]) for item in scored)
    final_operator_ready = sum(bool(item["final_operator_ready"]) for item in scored)
    satisfied_target_total = sum(int(item["satisfied_target_count"]) for item in scored)
    unsupported_proposal_total = sum(int(item["unsupported_proposal_count"]) for item in scored)
    unsupported_execution_total = sum(int(item["unsupported_execution_count"]) for item in scored)
    wrong_complete_total = sum(int(item["wrong_complete_count"]) for item in scored)
    governance_violation_total = sum(int(item["governance_violation_count"]) for item in scored)
    regression_total = sum(int(item["already_correct_regression_count"]) for item in scored)
    full_recompute_total = sum(int(item["full_recompute_count"]) for item in scored)
    metrics = {
        "case_count": len(scored),
        "current_unresolved_case_count": sum(
            bool(item["initial_unresolved_requirement_ids"]) for item in scored
        ),
        "selected_action_case_count": len(selected),
        "missing_requirement_improved_case_ids": improved_case_ids,
        "missing_requirement_improved_case_count": len(improved_case_ids),
        "target_requirement_candidate_recall": {
            "baseline_hits": baseline_target_hits,
            "final_hits": final_target_hits,
            "denominator": target_gold_count,
            "non_decreasing": final_target_hits >= baseline_target_hits,
        },
        "target_requirement_binding": {
            "baseline_hits": baseline_binding_hits,
            "final_hits": final_binding_hits,
            "gain": final_binding_hits - baseline_binding_hits,
        },
        "required_evidence_set_coverage": {
            "baseline_hits": baseline_covered,
            "final_hits": final_covered,
            "denominator": total_gold,
            "delta": final_covered - baseline_covered,
            "non_decreasing": final_covered >= baseline_covered,
        },
        "operator_ready": {
            "baseline_cases": baseline_operator_ready,
            "final_cases": final_operator_ready,
        },
        "useful_candidate_rate": {
            "numerator": useful_count,
            "denominator": new_count,
            "value": useful_count / new_count if new_count else None,
        },
        "new_region_rate": {
            "numerator": new_regions,
            "denominator": new_regions + repeated_regions,
            "value": (
                new_regions / (new_regions + repeated_regions)
                if new_regions + repeated_regions
                else None
            ),
        },
        "repeated_region_rate": {
            "numerator": repeated_regions,
            "denominator": new_regions + repeated_regions,
            "value": (
                repeated_regions / (new_regions + repeated_regions)
                if new_regions + repeated_regions
                else None
            ),
        },
        "noise_per_useful_candidate": (
            (new_count - useful_count) / useful_count if useful_count else None
        ),
    }
    hard_gate = {
        "satisfied_requirement_target_rate": {
            "numerator": satisfied_target_total,
            "denominator": proposal_count,
        },
        "unsupported_action_proposal_rate": {
            "numerator": unsupported_proposal_total,
            "denominator": proposal_count,
        },
        "unsupported_action_execution_rate": {
            "numerator": unsupported_execution_total,
            "denominator": execution_count,
        },
        "state_digest_rejection_correctness": {
            "numerator": stale_rejected_count,
            "denominator": stale_negative_count,
        },
        "wrong_complete": wrong_complete_total,
        "governance_violation": governance_violation_total,
        "already_correct_regression": regression_total,
        "full_recompute_after_extra_pass": {
            "numerator": full_recompute_total,
            "denominator": execution_count,
        },
        "provider_calls": int(product.get("provider_calls", -1)),
        "automatic_retries": int(product.get("automatic_retries", -1)),
        "formal_holdout_consumed": product.get("formal_holdout_consumed"),
    }
    passed = (
        satisfied_target_total == 0
        and unsupported_proposal_total == 0
        and unsupported_execution_total == 0
        and stale_negative_count == proposal_count
        and stale_rejected_count == stale_negative_count
        and wrong_complete_total == 0
        and governance_violation_total == 0
        and regression_total == 0
        and full_recompute_total == execution_count
        and final_target_hits >= baseline_target_hits
        and final_binding_hits > baseline_binding_hits
        and final_covered >= baseline_covered
        and final_operator_ready >= baseline_operator_ready
        and product.get("provider_calls") == 0
        and product.get("automatic_retries") == 0
        and product.get("formal_holdout_consumed") is False
    )
    return {
        "schema": SCORE_SCHEMA,
        "status": "S2_DETERMINISTIC_POLICY_SCORED",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "run_id": product["run_id"],
        "sealed_product": _identity(sealed_path),
        "label_source": _identity(labels_path),
        "label_boundary": {
            "product_path_label_access_count": 0,
            "scorer_label_access_count": 1,
            "scoring_started_after_product_seal": True,
        },
        "metrics": metrics,
        "hard_gate": {**hard_gate, "passed": passed},
        "disposition": (
            "PASS_S2_DETERMINISTIC_CAPABILITY_POLICY"
            if passed
            else "FAILED_S2_DETERMINISTIC_CAPABILITY_POLICY"
        ),
        "enter_s4": passed,
        "residual_assist": "DISABLED_NOT_NEEDED" if passed else "NOT_EVALUATED",
        "cases": scored,
    }


def acquisition_loss_ledger(score: Mapping[str, Any]) -> dict[str, Any]:
    cases = _mapping_list(score.get("cases"), "score.cases")
    records = [
        record
        for case in cases
        for record in _mapping_list(case.get("loss_records"), "case.loss_records")
    ]
    return {
        "schema": "milai.dg20.acquisition-loss-ledger.v0.1",
        "run_id": score["run_id"],
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "scorer_truth_loaded_after_seal": True,
        "record_count": len(records),
        "all_records_have_exactly_one_first_loss": all(
            isinstance(item.get("first_loss_stage"), str) and bool(item["first_loss_stage"])
            for item in records
        ),
        "records": records,
    }


def _score_case(case: Mapping[str, Any], label: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(case["case_id"])
    runtime_order = _string_list(case.get("runtime_requirement_order"), "runtime_requirement_order")
    atom_rows = _mapping_list(label.get("atoms"), "label.atoms")
    label_order = list(dict.fromkeys(str(item["slot"]) for item in atom_rows))
    crosswalk = opened_dev_requirement_crosswalk(
        case_id=case_id,
        runtime_order=runtime_order,
        label_order=label_order,
    )
    baseline = _mapping(case, "baseline")
    final = _mapping(case, "final")
    initial_state = _mapping(case, "initial_requirement_state")
    initial_requirements = _mapping_list(initial_state.get("requirements"), "initial requirements")
    initial_status = {
        str(item["requirement_id"]): str(item["status"]) for item in initial_requirements
    }
    unresolved = sorted(key for key, value in initial_status.items() if value != "SATISFIED")
    decision = _mapping(case, "decision")
    action = decision.get("selected_action")
    selected_action = cast(Mapping[str, Any], action) if isinstance(action, Mapping) else None
    target = str(selected_action["target_requirement_id"]) if selected_action is not None else None
    baseline_refs = set(_string_list(baseline.get("candidate_refs"), "baseline refs"))
    final_refs = set(_string_list(final.get("candidate_refs"), "final refs"))
    all_gold = {str(item["source_turn_ref"]) for item in atom_rows}
    target_gold = (
        {
            str(item["source_turn_ref"])
            for item in atom_rows
            if str(item["slot"]) in crosswalk[target]
        }
        if target is not None
        else set()
    )
    baseline_target_bindings = _matched_refs(baseline, target) if target else set()
    final_target_bindings = _matched_refs(final, target) if target else set()
    final_state = _mapping(final, "requirement_state")
    final_status = {
        str(item["requirement_id"]): str(item["status"])
        for item in _mapping_list(final_state.get("requirements"), "final requirements")
    }
    target_status_improved = bool(
        target is not None
        and _STATUS_RANK[final_status[target]] < _STATUS_RANK[initial_status[target]]
    )
    new_refs = final_refs - baseline_refs
    useful_refs = {
        ref
        for requirement_id in unresolved
        for ref in _matched_refs(final, requirement_id)
        if ref in new_refs
    }
    baseline_regions = {_region(item) for item in baseline_refs}
    final_new_regions = {_region(item) for item in new_refs}
    repeated_regions = final_new_regions & baseline_regions
    novel_regions = final_new_regions - baseline_regions
    final_complete = _mapping(final, "sufficiency_decision").get("status") == "COMPLETE"
    proposal_audit = _mapping(case, "proposal_audit")
    extra_pass_count = _nonnegative_int(case.get("extra_pass_count"), "extra pass")
    full_recompute = bool(
        extra_pass_count == 1
        and selected_action is not None
        and final.get("action_digest") == selected_action.get("action_digest")
        and final_state.get("state_epoch") == 1
        and isinstance(final.get("binding_trace"), Mapping)
        and isinstance(final.get("sufficiency_decision"), Mapping)
    )
    governance = _mapping(final, "governance")
    governance_violations = sum(
        _nonnegative_int(governance.get(key), f"governance.{key}")
        for key in (
            "wrong_scope_accepted",
            "permission_unknown_accepted",
            "revoked_evidence_accepted",
            "authority_violation_accepted",
        )
    )
    already_correct = not unresolved
    already_correct_regression = int(
        already_correct
        and (
            extra_pass_count != 0
            or final_refs != baseline_refs
            or final.get("operator_ready") != baseline.get("operator_ready")
        )
    )
    loss_records = [
        _loss_record(
            case_id=case_id,
            requirement_id=requirement_id,
            case=case,
            final=final,
            target_gold={
                str(item["source_turn_ref"])
                for item in atom_rows
                if str(item["slot"]) in crosswalk[requirement_id]
            },
            selected_action=selected_action,
        )
        for requirement_id in unresolved
    ]
    return {
        "case_id": case_id,
        "initial_unresolved_requirement_ids": unresolved,
        "selected_action": selected_action,
        "target_requirement_id": target,
        "required_gold_count": len(all_gold),
        "baseline_required_evidence_hits": len(all_gold & baseline_refs),
        "final_required_evidence_hits": len(all_gold & final_refs),
        "target_gold_count": len(target_gold),
        "baseline_target_candidate_hits": len(target_gold & baseline_refs),
        "final_target_candidate_hits": len(target_gold & final_refs),
        "baseline_target_binding_hits": len(target_gold & baseline_target_bindings),
        "final_target_binding_hits": len(target_gold & final_target_bindings),
        "target_binding_gain": len(target_gold & final_target_bindings)
        - len(target_gold & baseline_target_bindings),
        "target_status_improved": target_status_improved,
        "baseline_operator_ready": baseline.get("operator_ready") is True,
        "final_operator_ready": final.get("operator_ready") is True,
        "proposal_count": _nonnegative_int(proposal_audit.get("proposal_count"), "proposal count"),
        "satisfied_target_count": _nonnegative_int(
            proposal_audit.get("satisfied_target_count"), "satisfied target count"
        ),
        "unsupported_proposal_count": _nonnegative_int(
            proposal_audit.get("unsupported_proposal_count"),
            "unsupported proposal count",
        ),
        "unsupported_execution_count": _nonnegative_int(
            proposal_audit.get("unsupported_execution_count"),
            "unsupported execution count",
        ),
        "stale_negative_count": _nonnegative_int(
            proposal_audit.get("stale_negative_count"), "stale negative count"
        ),
        "stale_rejected_count": _nonnegative_int(
            proposal_audit.get("stale_rejected_count"), "stale rejected count"
        ),
        "wrong_complete_count": int(final_complete and not all_gold.issubset(final_refs)),
        "governance_violation_count": governance_violations,
        "already_correct_regression_count": already_correct_regression,
        "full_recompute_count": int(full_recompute),
        "extra_pass_count": extra_pass_count,
        "new_candidate_count": len(new_refs),
        "useful_new_candidate_count": len(useful_refs),
        "new_region_count": len(novel_regions),
        "repeated_region_count": len(repeated_regions),
        "loss_records": loss_records,
    }


def _loss_record(
    *,
    case_id: str,
    requirement_id: str,
    case: Mapping[str, Any],
    final: Mapping[str, Any],
    target_gold: set[str],
    selected_action: Mapping[str, Any] | None,
) -> dict[str, Any]:
    selected_for_requirement = bool(
        selected_action is not None
        and selected_action.get("target_requirement_id") == requirement_id
    )
    candidate_refs = _string_list(final.get("candidate_refs"), "loss candidate refs")
    recovered = bool(set(candidate_refs) & target_gold)
    binding_statuses = sorted(
        {
            str(item["status"])
            for item in _mapping_list(
                _mapping(final, "binding_trace").get(requirement_id),
                "loss binding trace",
            )
            if item.get("source_turn_ref") in target_gold
        }
    )
    if not selected_for_requirement:
        stage, reason = "CAPABILITY", "NO_ACTION_SELECTED_FOR_REQUIREMENT"
    elif not recovered:
        stage, reason = "CHANNEL", "ANSWER_BEARING_EVIDENCE_NOT_RECOVERED"
    elif "MATCH" not in binding_statuses:
        stage, reason = "BINDING", "ANSWER_BEARING_BINDING_NOT_ACCEPTED"
    elif final.get("operator_ready") is not True:
        stage, reason = "SUFFICIENCY", "OPERATOR_NOT_READY_AFTER_ACCEPTED_BINDING"
    else:
        stage, reason = "SCORER", "NO_LOSS_OPERATOR_READY"
    initial_state = _mapping(case, "initial_requirement_state")
    return {
        "case_id": case_id,
        "requirement_id": requirement_id,
        "requirement_state_digest": initial_state["state_digest"],
        "capability_digest": initial_state["acquisition_capability_digest"],
        "first_loss_stage": stage,
        "reason_code": reason,
        "channel": (
            selected_action.get("channel")
            if selected_for_requirement and selected_action is not None
            else None
        ),
        "raw_rank": None,
        "fusion_rank": _best_rank(candidate_refs, target_gold),
        "cutoff_rank": 8,
        "answer_bearing_candidate_present": recovered,
        "binding_status": binding_statuses,
        "sufficiency_effect": final.get("operator_ready"),
        "scorer_truth_loaded_after_seal": True,
    }


def _matched_refs(execution: Mapping[str, Any], requirement_id: str) -> set[str]:
    rows = _mapping_list(_mapping(execution, "binding_trace").get(requirement_id), "binding rows")
    return {
        str(item["source_turn_ref"])
        for item in rows
        if item.get("status") == "MATCH" and isinstance(item.get("source_turn_ref"), str)
    }


def _best_rank(values: Sequence[str], targets: set[str]) -> int | None:
    ranks = [index for index, value in enumerate(values, start=1) if value in targets]
    return min(ranks) if ranks else None


def _region(source_ref: str) -> str:
    return source_ref.rsplit(":t", 1)[0]


def _validate_product(product: Mapping[str, Any]) -> None:
    if (
        product.get("schema") != PRODUCT_SCHEMA
        or product.get("status") != "PRODUCT_POLICY_COMPLETE_UNSCORED"
        or product.get("formal_holdout_consumed") is not False
        or product.get("labels_loaded") is not False
        or product.get("label_fields_available") is not False
        or product.get("provider_calls") != 0
        or product.get("automatic_retries") != 0
        or _contains_forbidden_key(product)
    ):
        raise DG20S2EvaluationError("S2 label-free product envelope is invalid")
    cases = product.get("cases")
    if not isinstance(cases, list) or len(cases) != 10:
        raise DG20S2EvaluationError("S2 product denominator must be ten cases")


def _validated_product(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    product = envelope.get("product")
    if (
        envelope.get("schema") != SEALED_SCHEMA
        or envelope.get("status") != "SEALED_BEFORE_SCORING"
        or not isinstance(product, Mapping)
        or envelope.get("product_sha256") != canonical_sha256(product)
    ):
        raise DG20S2EvaluationError("S2 sealed product identity is invalid")
    _validate_product(product)
    return product


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        if any(str(key).casefold() in _FORBIDDEN_KEYS for key in value):
            return True
        return any(_contains_forbidden_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = value.get(key)
    if not isinstance(raw, Mapping):
        raise DG20S2EvaluationError(f"{key} mapping is missing")
    return raw


def _mapping_list(value: object, path: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise DG20S2EvaluationError(f"{path} must be an object list")
    return [cast(Mapping[str, Any], item) for item in value]


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DG20S2EvaluationError(f"{path} must be a string list")
    return cast(list[str], value)


def _nonnegative_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DG20S2EvaluationError(f"{path} must be a non-negative integer")
    return value


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG20S2EvaluationError(f"JSON object required: {path}")
    return value


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


__all__ = [
    "PRODUCT_SCHEMA",
    "SCORE_SCHEMA",
    "SEALED_SCHEMA",
    "DG20S2EvaluationError",
    "acquisition_loss_ledger",
    "score_s2_product",
    "seal_s2_product",
]
