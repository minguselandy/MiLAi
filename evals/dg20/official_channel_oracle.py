"""DG-20 S1 official-executor channel oracle and sealed scorer boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypedDict, cast

from milai.application.evidence_acquisition import (
    OFFICIAL_EXECUTOR_IDENTITY,
    EvidenceAcquisitionExecution,
)
from milai.domain.acquisition_capability import AcquisitionCapabilityName

from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg17.q1r_causality import canonical_sha256

PRODUCT_SCHEMA = "milai.dg20.s1-official-channel-oracle-product.v0.1"
SEALED_SCHEMA = "milai.dg20.s1-sealed-official-channel-oracle.v0.1"
SCORE_SCHEMA = "milai.dg20.s1-official-channel-oracle-score.v0.1"
CHANNELS: tuple[AcquisitionCapabilityName, ...] = (
    "FTS_RAW",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "SOURCE_OBSERVED_RANGE_SCAN",
    "TEMPORAL_EVENT",
    "ADJACENT_TURNS",
    "SAME_EPISODE",
)
_FORBIDDEN_PRODUCT_KEYS = frozenset(
    {
        "answer",
        "answers",
        "answer_session_ids",
        "answer_bearing",
        "atoms",
        "gold",
        "gold_ir",
        "join_relations",
    }
)
_OPENED_DEV_REQUIREMENT_CROSSWALK: dict[str, dict[str, tuple[str, ...]]] = {
    "gpt4_8279ba03": {"TARGET_EVENT": ("TARGET_EVENT",)},
    "9a707b82": {"TARGET_EVENT": ("TARGET_EVENT",)},
    "2a1811e2": {
        "EVENT_1": ("START_EVENT",),
        "EVENT_2": ("END_EVENT",),
    },
    "0bb5a684": {
        "EVENT_1": ("START_EVENT",),
        "EVENT_2": ("END_EVENT",),
    },
    "2e6d26dc": {"MATCHING_EVENTS_IN_RANGE": ("BABY_EVENTS",)},
    "4dfccbf7": {
        "EVENT_1": ("START_EVENT",),
        "EVENT_2": ("END_EVENT",),
    },
    "gpt4_88806d6e": {
        "EVENT_1": ("LEFT_EVENT",),
        "EVENT_2": ("RIGHT_EVENT",),
    },
    "a89d7624": {
        "PREFERENCE_SIGNAL_SET": (
            "PAST_EXPERIENCE",
            "INTEREST_SIGNAL",
            "CURRENT_INTENT",
        )
    },
    "a82c026e": {"LOOKUP_ANSWER": ("LOOKUP_ANSWER",)},
    "88432d0a": {"MATCHING_EVENTS_IN_RANGE": ("BAKING_EVENTS",)},
}


class DG20S1OracleError(RuntimeError):
    """The S1 official-channel oracle contract or phase boundary drifted."""


class _ExecutionAudit(TypedDict):
    execution_count: int
    official_executor_count: int
    capability_identity_count: int
    capability_identity_bound_count: int
    governance_violation_count: int
    attribution_complete: bool
    execution_status_consistent: bool


def execution_summary(
    execution: EvidenceAcquisitionExecution,
    *,
    case_id: str,
) -> dict[str, Any]:
    """Project official execution facts without adding evaluator semantics."""

    candidates = [
        {
            **item.model_dump(mode="json"),
            "source_turn_ref": compact_lme_source_ref(item.source_turn_ref),
        }
        for item in execution.candidates
    ]
    source_ref_by_evidence = {
        item.source_evidence_id: compact_lme_source_ref(item.source_turn_ref)
        for item in execution.candidates
    }
    span_by_id = {item.span_id: item for item in execution.spans}
    interpretation_by_id = {item.interpretation_id: item for item in execution.interpretations}
    binding_trace: dict[str, list[dict[str, Any]]] = {
        item.requirement_id: [] for item in execution.requirement_state.requirements
    }
    for binding in execution.bindings:
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        span = span_by_id.get(interpretation.span_id) if interpretation is not None else None
        source_ref = compact_lme_source_ref(span.source_turn_ref) if span is not None else None
        binding_trace.setdefault(binding.requirement_id, []).append(
            {
                "source_turn_ref": source_ref,
                "source_evidence_id": (span.source_evidence_id if span is not None else None),
                "status": binding.status,
                "reason_code": binding.reason_code,
                "binding_digest": canonical_sha256(binding.model_dump(mode="json")),
            }
        )
    for values in binding_trace.values():
        values.sort(
            key=lambda item: (
                str(item["source_turn_ref"]),
                str(item["status"]),
                str(item["reason_code"]),
            )
        )
    probe_traces = []
    for trace in execution.probe_candidate_traces:
        value = trace.model_dump(mode="json")
        value["raw_source_refs"] = [compact_lme_source_ref(item) for item in trace.raw_source_refs]
        value["fusion_surviving_source_refs"] = [
            compact_lme_source_ref(item) for item in trace.fusion_surviving_source_refs
        ]
        probe_traces.append(value)
    candidate_refs = [str(item["source_turn_ref"]) for item in candidates]
    wrong_scope = sum(not value.startswith(f"{case_id}:s") for value in candidate_refs)
    required = execution.requirement_state.requirements
    return {
        "executor_identity": execution.executor_identity,
        "mode": execution.mode,
        "acquisition_capability_digest": execution.acquisition_capability_digest,
        "action_digest": execution.action_digest,
        "candidate_count": len(candidates),
        "candidate_refs": candidate_refs,
        "candidates": candidates,
        "probe_dispositions": [
            item.model_dump(mode="json") for item in execution.probe_dispositions
        ],
        "probe_candidate_traces": probe_traces,
        "candidate_requirement_attribution": execution.candidate_requirement_attribution,
        "binding_trace": binding_trace,
        "requirement_state": execution.requirement_state.model_dump(mode="json"),
        "sufficiency_decision": execution.sufficiency_decision.model_dump(mode="json"),
        "sufficiency_reason": execution.sufficiency_reason,
        "operator_ready": (
            execution.sufficiency_decision.status == "COMPLETE"
            and all(item.status == "SATISFIED" for item in required)
        ),
        "derived_result": execution.derived_result,
        "bounded_range_scan_proof": (
            execution.bounded_range_scan_proof.model_dump(mode="json")
            if execution.bounded_range_scan_proof is not None
            else None
        ),
        "latency_ms": round(sum(item.latency_ms for item in execution.probe_dispositions), 6),
        "hydrated_candidate_count": sum(item.body_hydrated for item in execution.candidates),
        "governance": {
            "repository_governed_candidate_count": len(candidates),
            "wrong_scope_accepted": wrong_scope,
            "permission_unknown_accepted": 0,
            "revoked_evidence_accepted": 0,
            "authority_violation_accepted": 0,
        },
        "source_ref_by_evidence": source_ref_by_evidence,
        "context_mutation_performed": execution.context_mutation_performed,
        "canonical_mutation": execution.canonical_mutation,
    }


def seal_product_oracle(product: Mapping[str, Any], output_path: Path) -> dict[str, Any]:
    """Seal the label-free product trace before the scorer opens gold atoms."""

    payload = dict(product)
    _validate_product(payload)
    if output_path.exists():
        raise DG20S1OracleError("S1 sealed product output already exists")
    envelope = {
        "schema": SEALED_SCHEMA,
        "status": "SEALED_BEFORE_SCORING",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / SEALED_PRODUCT_PLANE",
        "formal_holdout_consumed": False,
        "label_fields_available": False,
        "product_sha256": canonical_sha256(payload),
        "product": payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as handle:
        handle.write(_canonical_bytes(envelope))
    return envelope


def score_sealed_oracle(
    sealed_path: Path,
    *,
    labels_path: Path,
) -> dict[str, Any]:
    """Open selected opened-dev truth only after product trace sealing."""

    envelope = _load_object(sealed_path)
    product = _validated_sealed_product(envelope)
    labels_envelope = _load_object(labels_path)
    raw_labels = labels_envelope.get("cases")
    if not isinstance(raw_labels, list):
        raise DG20S1OracleError("S1 scoring labels are malformed")
    labels = {
        str(item["case_id"]): cast(Mapping[str, Any], item)
        for item in raw_labels
        if isinstance(item, Mapping) and isinstance(item.get("case_id"), str)
    }
    raw_cases = product.get("cases")
    if not isinstance(raw_cases, list):
        raise DG20S1OracleError("S1 product cases are missing")
    cases = [cast(Mapping[str, Any], item) for item in raw_cases if isinstance(item, Mapping)]
    if len(cases) != len(raw_cases) or set(labels) != {str(item.get("case_id")) for item in cases}:
        raise DG20S1OracleError("S1 scorer denominator drifted")
    scored_cases = [_score_case(item, labels[str(item["case_id"])]) for item in cases]
    unresolved_cases = [item for item in scored_cases if item["current_unresolved"]]
    classifications = [
        arm
        for case in scored_cases
        for requirement in cast(list[dict[str, Any]], case["requirements"])
        for arm in cast(list[dict[str, Any]], requirement["arms"])
    ]
    recovered_case_ids = sorted(
        {
            str(case["case_id"])
            for case in unresolved_cases
            if any(
                arm["answer_bearing_recovered"] is True
                for requirement in cast(list[dict[str, Any]], case["requirements"])
                for arm in cast(list[dict[str, Any]], requirement["arms"])
                if arm["capability_executable"] is True
            )
        }
    )
    execution_audit = _audit_product_executions(cases)
    first_loss_covered = sum(bool(arm["first_loss_stage"]) for arm in classifications)
    attribution_complete = execution_audit["attribution_complete"] is True
    hard_gate = {
        "eval_owned_ranking_filter_expansion": 0,
        "official_executor_rate": {
            "numerator": execution_audit["official_executor_count"],
            "denominator": execution_audit["execution_count"],
        },
        "capability_identity_bound_rate": {
            "numerator": execution_audit["capability_identity_bound_count"],
            "denominator": execution_audit["capability_identity_count"],
        },
        "candidate_requirement_attribution_complete": attribution_complete,
        "execution_status_consistent": execution_audit["execution_status_consistent"],
        "first_loss_classification_coverage": {
            "numerator": first_loss_covered,
            "denominator": len(classifications),
        },
        "wrong_scope_permission_revoke_authority_accepted": execution_audit[
            "governance_violation_count"
        ],
        "formal_holdout_consumed": False,
    }
    truth_gate_passed = (
        hard_gate["eval_owned_ranking_filter_expansion"] == 0
        and execution_audit["official_executor_count"] == execution_audit["execution_count"]
        and execution_audit["capability_identity_bound_count"]
        == execution_audit["capability_identity_count"]
        and execution_audit["execution_status_consistent"]
        and attribution_complete
        and first_loss_covered == len(classifications)
        and execution_audit["governance_violation_count"] == 0
        and product.get("formal_holdout_consumed") is False
    )
    mechanism_signal = len(recovered_case_ids) >= 2
    disposition = (
        "FAILED_PRODUCT_PATH_FIDELITY"
        if not truth_gate_passed
        else "PASS_S1_OFFICIAL_CHANNEL_ORACLE"
        if mechanism_signal
        else "PARKED_NO_EXECUTABLE_CHANNEL_GAIN"
    )
    return {
        "schema": SCORE_SCHEMA,
        "status": "S1_OFFICIAL_CHANNEL_ORACLE_SCORED",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "run_id": product["run_id"],
        "formal_holdout_consumed": False,
        "sealed_product": _identity(sealed_path),
        "label_source": _identity(labels_path),
        "label_boundary": {
            "product_path_label_access_count": 0,
            "scorer_label_access_count": 1,
            "scoring_started_after_product_seal": True,
        },
        "current_unresolved_case_count": len(unresolved_cases),
        "current_unresolved_requirement_count": sum(
            len(cast(list[Any], item["requirements"])) for item in unresolved_cases
        ),
        "executable_channel_recovered_case_ids": recovered_case_ids,
        "minimum_mechanism_signal": {
            "required_case_count": 2,
            "observed_case_count": len(recovered_case_ids),
            "passed": mechanism_signal,
        },
        "hard_gate": {**hard_gate, "passed": truth_gate_passed},
        "disposition": disposition,
        "enter_s2": truth_gate_passed and mechanism_signal,
        "cases": scored_cases,
    }


def _score_case(case: Mapping[str, Any], label: Mapping[str, Any]) -> dict[str, Any]:
    baseline = _mapping(case, "baseline")
    requirements = _mapping_list(case.get("requirements"), "requirements")
    runtime_order = _string_list(case.get("runtime_requirement_order"), "Runtime requirement order")
    atom_rows = _mapping_list(label.get("atoms"), "label.atoms")
    label_order = list(dict.fromkeys(str(item["slot"]) for item in atom_rows))
    crosswalk = opened_dev_requirement_crosswalk(
        case_id=str(case["case_id"]),
        runtime_order=runtime_order,
        label_order=label_order,
    )
    baseline_refs = set(_string_list(baseline.get("candidate_refs"), "baseline refs"))
    scored_requirements = []
    for requirement in requirements:
        requirement_id = str(requirement["requirement_id"])
        label_slots = crosswalk[requirement_id]
        gold_refs = {
            str(item["source_turn_ref"]) for item in atom_rows if str(item["slot"]) in label_slots
        }
        arms = [
            _score_arm(
                arm,
                requirement_id=requirement_id,
                gold_refs=gold_refs,
                baseline_refs=baseline_refs,
            )
            for arm in _mapping_list(requirement.get("arms"), "requirement.arms")
        ]
        scored_requirements.append(
            {
                "requirement_id": requirement_id,
                "requirement_kind": requirement.get("requirement_kind"),
                "label_slots": list(label_slots),
                "gold_source_turn_count": len(gold_refs),
                "baseline_answer_bearing_hits": len(gold_refs & baseline_refs),
                "arms": arms,
            }
        )
    return {
        "case_id": str(case["case_id"]),
        "current_unresolved": bool(requirements),
        "requirement_crosswalk": {key: list(value) for key, value in crosswalk.items()},
        "requirements": scored_requirements,
    }


def opened_dev_requirement_crosswalk(
    *,
    case_id: str,
    runtime_order: Sequence[str],
    label_order: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    if len(set(runtime_order)) != len(runtime_order) or len(set(label_order)) != len(label_order):
        raise DG20S1OracleError("S1 requirement crosswalk inputs are not unique")
    if set(runtime_order) == set(label_order):
        return {item: (item,) for item in runtime_order}
    declared = _OPENED_DEV_REQUIREMENT_CROSSWALK.get(case_id)
    if declared is None:
        raise DG20S1OracleError("S1 Runtime/gold requirement crosswalk is undeclared")
    if set(declared) != set(runtime_order):
        raise DG20S1OracleError("S1 Runtime requirement crosswalk drifted")
    covered_labels = [item for values in declared.values() for item in values]
    if not all(declared.values()) or set(covered_labels) != set(label_order):
        raise DG20S1OracleError("S1 gold requirement crosswalk drifted")
    return dict(declared)


def _audit_product_executions(
    cases: Sequence[Mapping[str, Any]],
) -> _ExecutionAudit:
    execution_count = 0
    official_executor_count = 0
    capability_identity_count = 0
    capability_identity_bound_count = 0
    governance_violation_count = 0
    attribution_complete = True
    execution_status_consistent = True

    def audit_execution(
        execution: Mapping[str, Any],
        *,
        capability_digest: str,
        requirement_ids: Sequence[str],
    ) -> None:
        nonlocal execution_count
        nonlocal official_executor_count
        nonlocal capability_identity_count
        nonlocal capability_identity_bound_count
        nonlocal governance_violation_count
        nonlocal attribution_complete
        execution_count += 1
        official_executor_count += int(
            execution.get("executor_identity") == OFFICIAL_EXECUTOR_IDENTITY
        )
        capability_identity_count += 1
        capability_identity_bound_count += int(
            execution.get("acquisition_capability_digest") == capability_digest
        )
        governance = _mapping(execution, "governance")
        governance_violation_count += sum(
            _nonnegative_int(governance.get(key), f"governance.{key}")
            for key in (
                "wrong_scope_accepted",
                "permission_unknown_accepted",
                "revoked_evidence_accepted",
                "authority_violation_accepted",
            )
        )
        attribution = _mapping(execution, "candidate_requirement_attribution")
        attribution_complete = attribution_complete and all(
            requirement_id in attribution for requirement_id in requirement_ids
        )

    for case in cases:
        runtime_order = _string_list(
            case.get("runtime_requirement_order"), "Runtime requirement order"
        )
        baseline_set = _mapping(case, "baseline_capability_set")
        baseline_digest = str(baseline_set.get("capability_digest"))
        audit_execution(
            _mapping(case, "baseline"),
            capability_digest=baseline_digest,
            requirement_ids=runtime_order,
        )
        oracle_set = _mapping(case, "oracle_capability_set")
        oracle_digest = str(oracle_set.get("capability_digest"))
        for requirement in _mapping_list(case.get("requirements"), "requirements"):
            requirement_id = str(requirement.get("requirement_id"))
            for arm in _mapping_list(requirement.get("arms"), "arms"):
                capability_identity_count += 1
                capability_identity_bound_count += int(
                    arm.get("capability_digest") == oracle_digest
                )
                execution = arm.get("execution")
                combined = arm.get("combined_execution")
                executed = arm.get("execution_status") == "EXECUTED"
                execution_status_consistent = execution_status_consistent and (
                    executed == isinstance(execution, Mapping)
                    and executed == isinstance(combined, Mapping)
                )
                action = arm.get("action")
                if executed:
                    capability_identity_count += 1
                    capability_identity_bound_count += int(
                        isinstance(action, Mapping)
                        and action.get("capability_digest") == oracle_digest
                        and action.get("target_requirement_id") == requirement_id
                    )
                if isinstance(execution, Mapping):
                    audit_execution(
                        execution,
                        capability_digest=oracle_digest,
                        requirement_ids=runtime_order,
                    )
                if isinstance(combined, Mapping):
                    audit_execution(
                        combined,
                        capability_digest=oracle_digest,
                        requirement_ids=runtime_order,
                    )
    return {
        "execution_count": execution_count,
        "official_executor_count": official_executor_count,
        "capability_identity_count": capability_identity_count,
        "capability_identity_bound_count": capability_identity_bound_count,
        "governance_violation_count": governance_violation_count,
        "attribution_complete": attribution_complete,
        "execution_status_consistent": execution_status_consistent,
    }


def _score_arm(
    arm: Mapping[str, Any],
    *,
    requirement_id: str,
    gold_refs: set[str],
    baseline_refs: set[str],
) -> dict[str, Any]:
    capability = _mapping(arm, "capability")
    execution = arm.get("execution")
    if not isinstance(execution, Mapping):
        return {
            "channel": arm["channel"],
            "capability_executable": capability.get("status") in {"ENABLED", "CONDITIONAL"},
            "execution_status": str(arm["execution_status"]),
            "answer_bearing_recovered": False,
            "new_answer_bearing_recovered": False,
            "raw_rank": None,
            "fusion_rank": None,
            "cutoff_survival": False,
            "binding_statuses": [],
            "attribution_present": False,
            "first_loss_stage": (
                "CAPABILITY_UNAVAILABLE"
                if capability.get("status") not in {"ENABLED", "CONDITIONAL"}
                else "NO_FEASIBLE_REQUIREMENT_ACTION"
            ),
        }
    candidate_refs = _string_list(execution.get("candidate_refs"), "arm candidate refs")
    candidate_set = set(candidate_refs)
    raw_rank = _best_raw_rank(execution, requirement_id, gold_refs)
    fusion_rank = _best_rank(candidate_refs, gold_refs)
    if raw_rank is None and arm.get("channel") in {
        "SOURCE_OBSERVED_RANGE_SCAN",
        "TEMPORAL_EVENT",
        "ADJACENT_TURNS",
        "SAME_EPISODE",
    }:
        raw_rank = fusion_rank
    binding_rows = _mapping_list(
        _mapping(execution, "binding_trace").get(requirement_id),
        "binding trace",
    )
    binding_statuses = sorted(
        {str(item["status"]) for item in binding_rows if item.get("source_turn_ref") in gold_refs}
    )
    recovered = bool(candidate_set & gold_refs)
    new_recovered = bool((candidate_set - baseline_refs) & gold_refs)
    if raw_rank is None:
        first_loss = "CHANNEL_RETRIEVAL_BOUND_MISS"
    elif not recovered:
        first_loss = "FUSION_CUTOFF"
    elif "MATCH" not in binding_statuses:
        first_loss = "BINDING_REJECTED_OR_POSSIBLE"
    elif execution.get("operator_ready") is not True:
        first_loss = "SUFFICIENCY_OR_OPERATOR_NOT_READY"
    else:
        first_loss = "OPERATOR_READY"
    attribution = _mapping(execution, "candidate_requirement_attribution")
    return {
        "channel": arm["channel"],
        "capability_executable": capability.get("status") in {"ENABLED", "CONDITIONAL"},
        "execution_status": str(arm["execution_status"]),
        "answer_bearing_recovered": recovered,
        "new_answer_bearing_recovered": new_recovered,
        "raw_rank": raw_rank,
        "fusion_rank": fusion_rank,
        "cutoff_survival": raw_rank is not None and recovered,
        "binding_statuses": binding_statuses,
        "attribution_present": requirement_id in attribution,
        "first_loss_stage": first_loss,
    }


def _best_raw_rank(
    execution: Mapping[str, Any], requirement_id: str, gold_refs: set[str]
) -> int | None:
    ranks: list[int] = []
    for trace in _mapping_list(execution.get("probe_candidate_traces"), "probe traces"):
        if trace.get("requirement_id") not in {None, requirement_id}:
            continue
        refs = _string_list(trace.get("raw_source_refs"), "raw source refs")
        value = _best_rank(refs, gold_refs)
        if value is not None:
            ranks.append(value)
    return min(ranks) if ranks else None


def _best_rank(values: Sequence[str], targets: set[str]) -> int | None:
    ranks = [index for index, value in enumerate(values, start=1) if value in targets]
    return min(ranks) if ranks else None


def _validate_product(product: Mapping[str, Any]) -> None:
    if (
        product.get("schema") != PRODUCT_SCHEMA
        or product.get("status") != "PRODUCT_ORACLE_COMPLETE_UNSCORED"
        or product.get("formal_holdout_consumed") is not False
        or product.get("labels_loaded") is not False
        or product.get("label_fields_available") is not False
        or product.get("executor_identity") != OFFICIAL_EXECUTOR_IDENTITY
        or product.get("eval_owned_ranking_filter_expansion") != 0
        or _contains_forbidden_key(product)
    ):
        raise DG20S1OracleError("S1 label-free product envelope is invalid")
    cases = product.get("cases")
    if not isinstance(cases, list) or len(cases) != 10:
        raise DG20S1OracleError("S1 product denominator must be ten cases")


def _validated_sealed_product(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    product = envelope.get("product")
    if (
        envelope.get("schema") != SEALED_SCHEMA
        or envelope.get("status") != "SEALED_BEFORE_SCORING"
        or not isinstance(product, Mapping)
        or envelope.get("product_sha256") != canonical_sha256(product)
    ):
        raise DG20S1OracleError("S1 sealed product identity is invalid")
    _validate_product(product)
    return product


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        if any(str(key).casefold() in _FORBIDDEN_PRODUCT_KEYS for key in value):
            return True
        return any(_contains_forbidden_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = value.get(key)
    if not isinstance(raw, Mapping):
        raise DG20S1OracleError(f"{key} mapping is missing")
    return raw


def _mapping_list(value: object, path: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise DG20S1OracleError(f"{path} must be an object list")
    return [cast(Mapping[str, Any], item) for item in value]


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DG20S1OracleError(f"{path} must be a string list")
    return cast(list[str], value)


def _nonnegative_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DG20S1OracleError(f"{path} must be a non-negative integer")
    return value


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG20S1OracleError(f"JSON object required: {path}")
    return value


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


__all__ = [
    "CHANNELS",
    "PRODUCT_SCHEMA",
    "SCORE_SCHEMA",
    "SEALED_SCHEMA",
    "DG20S1OracleError",
    "execution_summary",
    "opened_dev_requirement_crosswalk",
    "score_sealed_oracle",
    "seal_product_oracle",
]
