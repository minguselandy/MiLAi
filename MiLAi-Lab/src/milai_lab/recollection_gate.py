from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from milai_lab.context_preflight import source_session_instance_keys

_TARGET_REF = re.compile(
    r"^(?P<case>[^:]+):s(?P<session_index>\d+):"
    r"(?P<source_session>[^:]+):t(?P<turn_ordinal>\d+)$"
)


@dataclass(frozen=True, slots=True)
class RecollectionResultMetrics:
    accepted_count: int
    true_accepted_count: int
    false_accepted_count: int
    forbidden_candidate_count: int
    forbidden_accepted_count: int
    reference_integrity: float
    evidence_set_binding_exactness: float
    strict_wrong_complete_count: int
    canonical_mutation_count: int
    model_provider_policy_call_count: int
    acquisition_phase_count: int
    executed_dense_probe_count: int
    exact_source_span_failure_count: int

    @property
    def binding_precision(self) -> float:
        if self.accepted_count == 0:
            return 0.0
        return self.true_accepted_count / self.accepted_count

    def to_dict(self) -> dict[str, float | int]:
        return {
            "accepted_count": self.accepted_count,
            "true_accepted_count": self.true_accepted_count,
            "false_accepted_count": self.false_accepted_count,
            "forbidden_candidate_count": self.forbidden_candidate_count,
            "forbidden_accepted_count": self.forbidden_accepted_count,
            "reference_integrity": self.reference_integrity,
            "evidence_set_binding_exactness": self.evidence_set_binding_exactness,
            "strict_wrong_complete_count": self.strict_wrong_complete_count,
            "canonical_mutation_count": self.canonical_mutation_count,
            "model_provider_policy_call_count": self.model_provider_policy_call_count,
            "acquisition_phase_count": self.acquisition_phase_count,
            "executed_dense_probe_count": self.executed_dense_probe_count,
            "exact_source_span_failure_count": self.exact_source_span_failure_count,
            "binding_precision": self.binding_precision,
        }


def evaluate_recollection_result(
    result: Mapping[str, Any],
    *,
    identities: Mapping[str, Mapping[str, str]],
    true_evidence_ids: Sequence[str],
    false_evidence_ids: Sequence[str],
    forbidden_evidence_ids: Sequence[str] = (),
) -> RecollectionResultMetrics:
    """Score only public Product fields against preregistered synthetic labels."""

    true_ids = set(true_evidence_ids)
    false_ids = set(false_evidence_ids)
    forbidden_ids = set(forbidden_evidence_ids)
    if true_ids & false_ids or (true_ids | false_ids) & forbidden_ids:
        raise ValueError("recollection labels must be disjoint")

    accepted = set(_string_sequence(result.get("accepted_binding_evidence_refs")))
    compile_trace = _mapping(_mapping(result.get("memory_context"), "memory_context").get(
        "compile_trace"
    ), "compile_trace")
    candidates = _public_candidates(result, compile_trace)
    candidate_by_id = {
        str(item["evidence_id"]): item
        for item in candidates
        if isinstance(item.get("evidence_id"), str)
    }
    if len(candidate_by_id) != len(candidates):
        raise ValueError("raw candidate identities are missing or duplicated")

    reference_exact = accepted_binding_reference_integrity(result, identities) == 1.0

    raw_admitted = compile_trace.get("admitted_evidence_trace")
    if isinstance(raw_admitted, Mapping):
        units = _mapping_sequence(raw_admitted.get("units"), "admitted units")
        binding_unit_ids = {
            evidence_id
            for unit in units
            if unit.get("kind") == "REQUIRED_BINDING"
            for evidence_id in _string_sequence(unit.get("evidence_ids"))
        }
        evidence_set_exact = (
            binding_unit_ids == accepted
            and set(
                _string_sequence(raw_admitted.get("selected_evidence_ids"))
            ).issuperset(accepted)
            and raw_admitted.get("whole_unit_admission") is True
        )
    else:
        evidence_set_exact = False

    sufficiency = _mapping(result.get("sufficiency_decision"), "sufficiency_decision")
    wrong_complete = int(sufficiency.get("status") == "COMPLETE" and not (accepted & true_ids))
    search_trace = _mapping(result.get("search_trace"), "search_trace")
    acquisition_state = _mapping(search_trace.get("acquisition_state"), "acquisition_state")
    dispositions = _mapping_sequence(
        search_trace.get("acquisition_probe_dispositions"), "probe dispositions"
    )
    raw_semantic_audit = search_trace.get("semantic_audit")
    semantic_audit = raw_semantic_audit if isinstance(raw_semantic_audit, Mapping) else {}
    model_calls = _int_value(acquisition_state.get("residual_model_call_count"))
    hidden_model_calls = compile_trace.get("hidden_model_calls")
    if isinstance(hidden_model_calls, int) and not isinstance(hidden_model_calls, bool):
        model_calls += hidden_model_calls

    return RecollectionResultMetrics(
        accepted_count=len(accepted),
        true_accepted_count=len(accepted & true_ids),
        false_accepted_count=len(accepted & false_ids),
        forbidden_candidate_count=len(set(candidate_by_id) & forbidden_ids),
        forbidden_accepted_count=len(accepted & forbidden_ids),
        reference_integrity=float(reference_exact),
        evidence_set_binding_exactness=float(evidence_set_exact),
        strict_wrong_complete_count=wrong_complete,
        canonical_mutation_count=int(
            compile_trace.get("canonical_mutation") is not False
            or acquisition_state.get("canonical_mutation") is not False
        ),
        model_provider_policy_call_count=model_calls,
        acquisition_phase_count=len(
            _string_sequence(acquisition_state.get("prior_action_digests"))
        ),
        executed_dense_probe_count=sum(
            item.get("channel") == "EVIDENCE_DENSE" and item.get("status") == "EXECUTED"
            for item in dispositions
        ),
        exact_source_span_failure_count=(
            _int_value(semantic_audit.get("exact_source_span_failure_count"))
            if semantic_audit
            else 0
        ),
    )


def accepted_binding_reference_integrity(
    result: Mapping[str, Any],
    identities: Mapping[str, Mapping[str, str]],
) -> float:
    """Verify every asserted binding against the public raw identity trace."""

    accepted = set(_string_sequence(result.get("accepted_binding_evidence_refs")))
    compile_trace = _mapping(_mapping(result.get("memory_context"), "memory_context").get(
        "compile_trace"
    ), "compile_trace")
    candidates = _public_candidates(result, compile_trace)
    candidate_by_id = {
        str(item["evidence_id"]): item
        for item in candidates
        if isinstance(item.get("evidence_id"), str)
    }
    if len(candidate_by_id) != len(candidates):
        return 0.0
    for evidence_id in accepted:
        expected = identities.get(evidence_id)
        candidate = candidate_by_id.get(evidence_id)
        if expected is None or candidate is None:
            return 0.0
        if any(
            candidate.get(name) != expected[name]
            for name in ("subject_id", "session_id", "turn_id")
        ):
            return 0.0
        if (
            candidate.get("source_turn_ref") != expected["source_ref"]
            or candidate.get("identity_source") != "STRUCTURED_TURN_METADATA"
        ):
            return 0.0
    return 1.0


def dg28_target_source_refs(
    records: Mapping[str, Mapping[str, Any]],
    target_groups: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Resolve frozen DG28 source identities into current black-box capture refs."""

    resolved: dict[str, str] = {}
    for target in target_groups:
        group_id = target.get("equivalence_group_id")
        raw_ref = target.get("acceptable_source_turn_ref")
        if not isinstance(group_id, str) or not isinstance(raw_ref, str):
            raise ValueError("DG28 target identity is invalid")
        match = _TARGET_REF.fullmatch(raw_ref)
        if match is None:
            raise ValueError("DG28 target source ref is invalid")
        case_id = match.group("case")
        record = records.get(case_id)
        if record is None:
            raise ValueError(f"DG28 case {case_id} is absent")
        session_ids = record.get("haystack_session_ids")
        if not isinstance(session_ids, list):
            raise ValueError("DG28 case session identities are invalid")
        session_index = int(match.group("session_index"))
        if session_index >= len(session_ids):
            raise ValueError("DG28 session index is out of range")
        if not isinstance(session_ids[session_index], str) or not session_ids[session_index]:
            raise ValueError("DG28 source session identity is invalid")
        instance_keys = source_session_instance_keys(session_ids)
        resolved[group_id] = (
            f"lme://{_stable_component(case_id, length=12)}/"
            f"{_stable_component(instance_keys[session_index], length=20)}/"
            f"turn/{int(match.group('turn_ordinal'))}"
        )
    if len(resolved) != len(target_groups):
        raise ValueError("DG28 target group identities must be unique")
    return resolved


def admitted_dg28_groups(
    result: Mapping[str, Any],
    target_refs: Mapping[str, str],
) -> tuple[str, ...]:
    compile_trace = _mapping(_mapping(result.get("memory_context"), "memory_context").get(
        "compile_trace"
    ), "compile_trace")
    candidate_refs = {
        str(item["source_turn_ref"])
        for item in _public_candidates(result, compile_trace)
        if isinstance(item.get("source_turn_ref"), str)
    }
    return tuple(
        sorted(
            group_id
            for group_id, source_ref in target_refs.items()
            if source_ref in candidate_refs
        )
    )


def _stable_component(value: str, *, length: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _public_candidates(
    result: Mapping[str, Any], compile_trace: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    raw = compile_trace.get("raw_retrieval_trace")
    if isinstance(raw, Mapping):
        return _mapping_sequence(raw.get("candidates"), "raw candidates")
    items = _mapping_sequence(result.get("items"), "legacy result items")
    candidates: list[Mapping[str, Any]] = []
    for item in items:
        candidate = item.get("acquisition_candidate")
        if not isinstance(candidate, Mapping):
            continue
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str):
            continue
        candidates.append(
            {
                "evidence_id": evidence_id,
                "source_turn_ref": candidate.get("source_turn_ref"),
                "subject_id": candidate.get("subject_id"),
                "session_id": candidate.get("session_id"),
                "turn_id": candidate.get("turn_id"),
                "identity_source": candidate.get("identity_source"),
            }
        )
    return candidates


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} is missing or invalid")
    return value


def _mapping_sequence(value: object, name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} is missing or invalid")
    return list(value)


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("expected a string sequence")
    return tuple(value)


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer trace value")
    return value


__all__ = [
    "RecollectionResultMetrics",
    "accepted_binding_reference_integrity",
    "admitted_dg28_groups",
    "dg28_target_source_refs",
    "evaluate_recollection_result",
]
