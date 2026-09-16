"""Bounded observation, one-call shadow controller, and policy validation for DG-18."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import ValidationError

from milai.application.evidence_source import structured_evidence_speaker
from milai.application.semantic_hint import (
    SemanticHintCompletion,
    StructuredSemanticProvider,
)
from milai.domain.acquisition import (
    AcquisitionGlobalConstraints,
    AcquisitionPlan,
    AcquisitionState,
)
from milai.domain.residual_refinding import (
    AcquisitionObservation,
    ResidualCandidateEligibilityReceipt,
    ResidualCandidateSummary,
    ResidualControllerReceipt,
    ResidualControllerTiming,
    ResidualCueProposal,
    ResidualHintValidation,
    ResidualLexicalCues,
    ResidualMissingRequirement,
    ResidualSearchAction,
    ResidualSearchHint,
    ResidualTemporalCue,
)
from milai.domain.semantic_query import EvidenceRequirementV02

MAX_RESIDUAL_COMPLETION_TOKENS = 192
MAX_QUESTION_EXCERPT_CHARS = 600
MAX_OBSERVATION_CANDIDATES = 12
MAX_OBSERVATION_SNIPPET_CHARS = 600
_TERM = re.compile(r"[^\W_]+", re.UNICODE)
_ALLOWED_ACTIONS: frozenset[ResidualSearchAction] = frozenset(
    {
        "SEARCH_LEXICAL",
        "SEARCH_TEMPORAL",
        "EXPAND_NEIGHBORS",
        "EXPAND_EPISODE",
        "NO_ACTION",
    }
)


class ResidualRefindingError(RuntimeError):
    """Typed failure; shadow callers must preserve deterministic-only output."""

    def __init__(
        self,
        code: str,
        *,
        validation_field_path: str | None = None,
        validation_error_type: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.validation_field_path = validation_field_path
        self.validation_error_type = validation_error_type


def build_acquisition_observation(
    *,
    query: str,
    requirements: Sequence[EvidenceRequirementV02],
    candidates: Sequence[Mapping[str, Any]],
    state: AcquisitionState,
    plan: AcquisitionPlan,
) -> AcquisitionObservation:
    """Build the minimal controller view from already-gated Raw Evidence candidates."""

    normalized_query = unicodedata.normalize("NFKC", query).strip()
    if not normalized_query:
        raise ValueError("residual observation query is empty")
    if (
        state.query_ir_digest != plan.query_ir_digest
        or state.acquisition_plan_digest != _digest(plan.model_dump(mode="json"))
    ):
        raise ValueError("residual observation AcquisitionPlan identity mismatch")
    requirement_by_id = {item.slot_id: item for item in requirements if item.required}
    if not set(state.missing_requirement_ids).issubset(requirement_by_id):
        raise ValueError("AcquisitionState missing requirement is absent from QueryIR")
    missing = [
        _requirement_observation(requirement_by_id[requirement_id])
        for requirement_id in state.missing_requirement_ids
    ]
    if not missing:
        raise ValueError("residual observation requires a real missing requirement")
    query_terms = frozenset(_TERM.findall(normalized_query.casefold()))
    summaries: list[ResidualCandidateSummary] = []
    seen_candidates: set[str] = set()
    for raw in candidates:
        eligibility = evaluate_residual_candidate_eligibility(raw=raw, plan=plan)
        if not eligibility.eligible:
            continue
        summary = _candidate_summary(
            raw,
            query_terms=query_terms,
            missing_requirement_ids=frozenset(state.missing_requirement_ids),
        )
        if summary is None or summary.ephemeral_candidate_ref in seen_candidates:
            continue
        summaries.append(summary)
        seen_candidates.add(summary.ephemeral_candidate_ref)
        if len(summaries) >= MAX_OBSERVATION_CANDIDATES:
            break
    return AcquisitionObservation(
        query_ir_digest=state.query_ir_digest,
        acquisition_plan_digest=state.acquisition_plan_digest,
        question_excerpt=_bounded_excerpt(
            normalized_query, frozenset(), MAX_QUESTION_EXCERPT_CHARS
        ),
        missing_requirements=missing,
        candidate_summaries=summaries,
        prior_action_digests=[item.action_digest for item in state.prior_actions],
        exhausted_region_digests=[item.region_digest for item in state.exhausted_regions],
        remaining_budget=state.remaining_budget,
    )


def evaluate_residual_candidate_eligibility(
    *, raw: Mapping[str, Any], plan: AcquisitionPlan
) -> ResidualCandidateEligibilityReceipt:
    """Reapply hard identity, scope, time, permission and authority filters pre-model."""

    plan_digest = _digest(plan.model_dump(mode="json"))
    candidate_digest = _digest(
        {
            "evidence_id": raw.get("evidence_id"),
            "source_ref": raw.get("source_ref"),
            "content_hash": raw.get("content_hash"),
        }
    )
    reason = "ELIGIBLE"
    constraints = plan.global_constraints
    if raw.get("kind") != "EVIDENCE_OBSERVATION":
        reason = "NON_EVIDENCE_CANDIDATE"
    elif raw.get("canonical") is not False or raw.get("canonical_mutation") is not False:
        reason = "CANONICAL_CANDIDATE"
    elif (
        constraints.tenant_identity_digest is None
        or constraints.principal_identity_digest is None
    ):
        reason = "PLAN_IDENTITY_UNBOUND"
    elif _digest(raw.get("tenant_id")) != constraints.tenant_identity_digest:
        reason = "TENANT_MISMATCH"
    elif _digest(raw.get("principal_id")) != constraints.principal_identity_digest:
        reason = "PRINCIPAL_MISMATCH"
    elif not _candidate_scope_contains(raw.get("scope_predicate"), constraints):
        reason = "SCOPE_MISMATCH"
    else:
        permission = raw.get("permission_snapshot")
        if not isinstance(permission, Mapping) or not isinstance(
            permission.get("readable"), bool
        ):
            reason = "PERMISSION_UNKNOWN"
        elif permission.get("readable") is not True:
            reason = "PERMISSION_DENIED"
        elif not _permission_projects_cover_scope(permission, constraints.principal_scope):
            reason = "SCOPE_MISMATCH"
        elif raw.get("retention_state") != "READABLE":
            reason = "RETENTION_BLOCKED"
        elif raw.get("revoked_at") is not None:
            reason = "REVOKED_EVIDENCE"
        elif raw.get("authority_class") != "EVIDENCE_ONLY":
            reason = "AUTHORITY_MISMATCH"
        elif raw.get("fallback_used") is not False:
            reason = "HIDDEN_FALLBACK"
        elif not _timestamp_at_or_before(raw.get("observed_at"), constraints.valid_as_of):
            reason = "SOURCE_TIME_OUT_OF_SCOPE"
        elif not _timestamp_at_or_before(
            raw.get("captured_at") or raw.get("system_time"),
            constraints.system_as_of,
        ):
            reason = "SYSTEM_TIME_OUT_OF_SCOPE"
        elif not _source_time_in_range(
            raw.get("observed_at"), constraints.source_observed_range
        ):
            reason = "SOURCE_TIME_OUT_OF_SCOPE"
        elif not _event_time_in_range(
            raw.get("event_occurrence_interval"),
            constraints.event_occurrence_range,
        ):
            reason = "EVENT_TIME_OUT_OF_SCOPE"
        elif not all(
            isinstance(raw.get(key), str) and bool(raw.get(key))
            for key in ("evidence_id", "source_ref", "content", "content_hash")
        ):
            reason = "MALFORMED_CANDIDATE"
    return ResidualCandidateEligibilityReceipt(
        eligible=reason == "ELIGIBLE",
        reason_code=cast(Any, reason),
        candidate_digest=candidate_digest,
        acquisition_plan_digest=plan_digest,
    )


def validate_residual_search_hint(
    *,
    hint: ResidualSearchHint,
    state: AcquisitionState,
    plan: AcquisitionPlan,
    allowed_actions: frozenset[ResidualSearchAction] = _ALLOWED_ACTIONS,
) -> ResidualHintValidation:
    """Apply immutable Runtime policy without interpreting model rationale as truth."""

    status: Literal["ACCEPTED", "REJECTED", "NO_ACTION"] = "ACCEPTED"
    reason = "HINT_POLICY_ACCEPTED"
    if (
        state.query_ir_digest != plan.query_ir_digest
        or state.acquisition_plan_digest
        != _digest(plan.model_dump(mode="json"))
    ):
        status = "REJECTED"
        reason = "ACQUISITION_PLAN_IDENTITY_MISMATCH"
    elif hint.requirement_id not in state.missing_requirement_ids:
        status = "REJECTED"
        reason = "REQUIREMENT_NOT_MISSING"
    elif hint.action not in allowed_actions:
        status = "REJECTED"
        reason = "ACTION_NOT_ALLOWED"
    elif (
        state.residual_model_call_count != 1
        or state.remaining_budget.model_calls != 0
    ):
        status = "REJECTED"
        reason = "MODEL_CALL_NOT_RESERVED"
    elif hint.action != "NO_ACTION" and state.remaining_budget.acquisition_passes < 1:
        status = "REJECTED"
        reason = "ACQUISITION_PASS_BUDGET_EXHAUSTED"
    elif hint.action == "SEARCH_LEXICAL" and not any(
        probe.channel in {"FTS_RAW", "FTS_ENRICHED"} for probe in plan.probes
    ):
        status = "REJECTED"
        reason = "LEXICAL_CAPABILITY_UNAVAILABLE"
    elif hint.action == "SEARCH_TEMPORAL":
        temporal_constraint = (
            plan.global_constraints.event_occurrence_range
            if hint.temporal_cue.axis == "EVENT_OCCURRENCE_TIME"
            else plan.global_constraints.source_observed_range
        )
        if hint.temporal_cue.axis == "EVENT_OCCURRENCE_TIME" and not any(
            probe.channel == "TEMPORAL_EVENT" for probe in plan.probes
        ):
            status = "REJECTED"
            reason = "EVENT_TIME_CAPABILITY_UNAVAILABLE"
        elif temporal_constraint is None:
            status = "REJECTED"
            reason = "TEMPORAL_SCOPE_NOT_INHERITED"
        elif not _temporal_cue_is_subset(hint, temporal_constraint):
            status = "REJECTED"
            reason = "TEMPORAL_SCOPE_EXPANSION_REJECTED"
    elif hint.action == "EXPAND_NEIGHBORS" and not any(
        probe.expansion_policy == "ADJACENT_TURNS" for probe in plan.probes
    ):
        status = "REJECTED"
        reason = "NEIGHBOR_EXPANSION_NOT_PLANNED"
    elif hint.action == "EXPAND_EPISODE" and not any(
        probe.expansion_policy in {"SAME_EPISODE", "SAME_SESSION"} for probe in plan.probes
    ):
        status = "REJECTED"
        reason = "EPISODE_EXPANSION_NOT_PLANNED"
    elif hint.action == "NO_ACTION":
        status = "NO_ACTION"
        reason = "CONTROLLER_NO_SAFE_ACTION"
    return ResidualHintValidation(
        status=status,
        reason_code=reason,
        requirement_id=hint.requirement_id,
        action=hint.action,
        inherited_scope_digest=_digest(
            {
                "principal_scope": plan.global_constraints.principal_scope,
                "semantic_scope": plan.global_constraints.semantic_scope,
                "source_observed_range": plan.global_constraints.source_observed_range,
                "event_occurrence_range": plan.global_constraints.event_occurrence_range,
            }
        ),
        inherited_authority_floor=plan.global_constraints.authority_floor,
    )


def _temporal_cue_is_subset(
    hint: ResidualSearchHint,
    inherited: Mapping[str, object],
) -> bool:
    """Reject a model-proposed interval unless it narrows an inherited hard bound."""

    inherited_start = _aware_datetime(inherited.get("start"))
    inherited_end = _aware_datetime(inherited.get("end"))
    hint_start = hint.temporal_cue.start
    hint_end = hint.temporal_cue.end
    if inherited_start is not None and hint_start is None:
        return False
    if inherited_end is not None and hint_end is None:
        return False
    if inherited_start is not None and hint_start is not None and hint_start < inherited_start:
        return False
    if inherited_end is not None and hint_end is not None and hint_end > inherited_end:
        return False
    return inherited_start is not None or inherited_end is not None


def _aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


class ResidualHintShadowService:
    """Generate one untrusted search hint without changing the product result."""

    def __init__(self, provider: StructuredSemanticProvider) -> None:
        self._provider = provider
        self._used = False

    def generate(
        self,
        *,
        run_id: str,
        case_id: str,
        observation: AcquisitionObservation,
        state: AcquisitionState,
        plan: AcquisitionPlan,
    ) -> ResidualControllerReceipt:
        if not run_id or not case_id:
            raise ValueError("residual controller run/case identity is required")
        if self._used:
            raise ResidualRefindingError("RESIDUAL_CONTROLLER_ALREADY_USED")
        if (
            observation.query_ir_digest != state.query_ir_digest
            or observation.acquisition_plan_digest != state.acquisition_plan_digest
            or state.acquisition_plan_digest != _digest(plan.model_dump(mode="json"))
        ):
            raise ResidualRefindingError("RESIDUAL_CONTROLLER_STATE_IDENTITY_MISMATCH")
        if (
            state.residual_model_call_count != 1
            or state.remaining_budget.model_calls != 0
            or state.remaining_budget.acquisition_passes < 1
            or state.remaining_budget.candidate_count < 1
            or state.remaining_budget.context_tokens < 1
            or state.remaining_budget.latency_ms <= 0
        ):
            raise ResidualRefindingError("RESIDUAL_MODEL_CALL_BUDGET_BLOCKED")
        self._used = True
        messages = _controller_messages(observation)
        schema = residual_cue_proposal_output_schema()
        completion = self._provider.complete_structured(
            messages=messages,
            schema_name="residual_cue_proposal_v01",
            schema=schema,
            max_completion_tokens=MAX_RESIDUAL_COMPLETION_TOKENS,
            seed=_seed(run_id, case_id),
        )
        _validate_completion(completion)
        try:
            proposal = ResidualCueProposal.model_validate_json(completion.content)
        except ValidationError as exc:
            diagnostic = exc.errors(include_url=False, include_context=False)[0]
            field_path = ".".join(str(value) for value in diagnostic.get("loc", ()))
            raise ResidualRefindingError(
                "RESIDUAL_CUE_PROPOSAL_SCHEMA_INVALID",
                validation_field_path=field_path or "$",
                validation_error_type=str(diagnostic.get("type", "unknown")),
            ) from exc
        hint = normalize_residual_cue_proposal(
            proposal=proposal,
            observation=observation,
            plan=plan,
        )
        return ResidualControllerReceipt(
            hint=hint,
            provider=completion.provider,
            model=completion.model,
            prompt_digest=_digest(messages),
            schema_digest=_digest(schema),
            observation_digest=_digest(observation.model_dump(mode="json")),
            seed=_seed(run_id, case_id),
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            tokenizer_latency_ms=completion.tokenizer_latency_ms,
            timing=ResidualControllerTiming(
                queue_ms=completion.queue_ms,
                ttft_ms=completion.ttft_ms,
                decode_ms=completion.decode_ms,
                total_ms=completion.total_ms,
            ),
        )


def normalize_residual_cue_proposal(
    *,
    proposal: ResidualCueProposal,
    observation: AcquisitionObservation,
    plan: AcquisitionPlan,
) -> ResidualSearchHint:
    """Derive the historical domain hint without trusting provider control fields."""

    requirement = next(
        (
            item
            for item in observation.missing_requirements
            if item.requirement_id == proposal.requirement_id
        ),
        None,
    )
    if requirement is None:
        raise ResidualRefindingError("RESIDUAL_HINT_REQUIREMENT_NOT_MISSING")
    source_preference = _runtime_source_preference(proposal.requirement_id, plan)
    provenance = _runtime_cue_provenance(proposal.cues, observation)
    if proposal.action == "SEARCH_LEXICAL":
        return ResidualSearchHint(
            requirement_id=proposal.requirement_id,
            action=proposal.action,
            lexical_cues=ResidualLexicalCues(terms=proposal.cues),
            source_preference=source_preference,
            cue_provenance=provenance,
            rationale_code=(
                "ENTITY_BRIDGE" if provenance == "OBSERVATION" else "LEXICAL_MISMATCH"
            ),
        )
    if proposal.action == "SEARCH_TEMPORAL":
        temporal = _inherited_temporal_cue(
            requirement=requirement,
            plan=plan,
            expression=proposal.cues[0] if proposal.cues else None,
        )
        return ResidualSearchHint(
            requirement_id=proposal.requirement_id,
            action=proposal.action,
            temporal_cue=temporal,
            source_preference=source_preference,
            cue_provenance=provenance,
            rationale_code="TEMPORAL_NARROWING",
        )
    if proposal.action == "EXPAND_NEIGHBORS":
        return ResidualSearchHint(
            requirement_id=proposal.requirement_id,
            action=proposal.action,
            source_preference=source_preference,
            cue_provenance="OBSERVATION",
            rationale_code="LOCAL_CONTEXT_REQUIRED",
        )
    return ResidualSearchHint(
        requirement_id=proposal.requirement_id,
        action="NO_ACTION",
        source_preference="NO_CHANGE",
        cue_provenance="OBSERVATION",
        rationale_code="NO_SAFE_ACTION",
    )


def _runtime_source_preference(
    requirement_id: str, plan: AcquisitionPlan
) -> Literal["USER", "ASSISTANT", "BOTH", "NO_CHANGE"]:
    speakers = {
        speaker
        for probe in plan.probes
        if probe.requirement_slot == requirement_id
        for speaker in probe.evidence_source_policy.preferred_speakers
        if speaker in {"USER", "ASSISTANT"}
    }
    if speakers == {"USER"}:
        return "USER"
    if speakers == {"ASSISTANT"}:
        return "ASSISTANT"
    if speakers == {"USER", "ASSISTANT"}:
        return "BOTH"
    return "NO_CHANGE"


def _runtime_cue_provenance(
    cues: Sequence[str], observation: AcquisitionObservation
) -> Literal["QUERY", "OBSERVATION", "PARAPHRASE"]:
    cue_terms = {
        term
        for cue in cues
        for term in _TERM.findall(unicodedata.normalize("NFKC", cue).casefold())
    }
    if not cue_terms:
        return "OBSERVATION"
    query_terms = set(_TERM.findall(observation.question_excerpt.casefold()))
    if cue_terms.issubset(query_terms):
        return "QUERY"
    observed_terms = {
        term
        for candidate in observation.candidate_summaries
        for value in (candidate.bounded_snippet, *candidate.matched_terms)
        for term in _TERM.findall(value.casefold())
    }
    if cue_terms.intersection(observed_terms):
        return "OBSERVATION"
    return "PARAPHRASE"


def _inherited_temporal_cue(
    *,
    requirement: ResidualMissingRequirement,
    plan: AcquisitionPlan,
    expression: str | None,
) -> ResidualTemporalCue:
    constraint = requirement.temporal_constraint
    axis: Literal["SOURCE_OBSERVED_TIME", "EVENT_OCCURRENCE_TIME"]
    inherited: Mapping[str, object] | None = None
    if isinstance(constraint, Mapping):
        inherited = constraint
        axis = (
            "SOURCE_OBSERVED_TIME"
            if constraint.get("time_axis") == "SOURCE_OBSERVED_TIME"
            else "EVENT_OCCURRENCE_TIME"
        )
    elif plan.global_constraints.event_occurrence_range is not None:
        inherited = plan.global_constraints.event_occurrence_range
        axis = "EVENT_OCCURRENCE_TIME"
    elif plan.global_constraints.source_observed_range is not None:
        inherited = plan.global_constraints.source_observed_range
        axis = "SOURCE_OBSERVED_TIME"
    else:
        raise ResidualRefindingError("RESIDUAL_PROPOSAL_TEMPORAL_BOUND_UNAVAILABLE")
    start = _aware_datetime(inherited.get("start"))
    end = _aware_datetime(inherited.get("end"))
    if start is None and end is None:
        raise ResidualRefindingError("RESIDUAL_PROPOSAL_TEMPORAL_BOUND_UNAVAILABLE")
    return ResidualTemporalCue(
        axis=axis,
        expression=expression,
        start=start,
        end=end,
    )


def _requirement_observation(
    requirement: EvidenceRequirementV02,
) -> ResidualMissingRequirement:
    roles = requirement.semantic_roles.model_dump(mode="json", exclude_none=True)
    description = json.dumps(
        {
            "interpretation_kind": requirement.interpretation_kind,
            "value_type": requirement.value_type,
            "cardinality": requirement.cardinality.model_dump(mode="json"),
            "semantic_roles": roles,
            "join_key": requirement.join_key,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ResidualMissingRequirement(
        requirement_id=requirement.slot_id,
        semantic_description=description,
        known_entities=list(requirement.entity_constraints),
        known_predicates=list(requirement.predicate_constraints),
        temporal_constraint=(
            requirement.temporal_constraints.model_dump(mode="json")
            if requirement.temporal_constraints is not None
            else None
        ),
    )


def _candidate_summary(
    raw: Mapping[str, Any],
    *,
    query_terms: frozenset[str],
    missing_requirement_ids: frozenset[str],
) -> ResidualCandidateSummary | None:
    if raw.get("kind") != "EVIDENCE_OBSERVATION" or raw.get("canonical") is not False:
        return None
    permission = raw.get("permission_snapshot")
    if not isinstance(permission, Mapping) or permission.get("readable") is not True:
        return None
    if raw.get("retention_state") != "READABLE" or raw.get("revoked_at") is not None:
        return None
    evidence_id = raw.get("evidence_id")
    source_ref = raw.get("source_ref")
    content = raw.get("content")
    session_id = raw.get("subject_id")
    if not all(isinstance(value, str) and value for value in (evidence_id, source_ref, content)):
        return None
    if not isinstance(session_id, str) or not session_id:
        session_id = str(source_ref)
    assert isinstance(evidence_id, str)
    assert isinstance(source_ref, str)
    assert isinstance(content, str)
    speaker, _speaker_source = structured_evidence_speaker(raw)
    content_terms = frozenset(_TERM.findall(content.casefold()))
    acquisition = raw.get("acquisition_candidate")
    matched_slots: list[str] = []
    channels: list[str] = []
    if isinstance(acquisition, Mapping):
        raw_slots = acquisition.get("matched_slots")
        if isinstance(raw_slots, list):
            matched_slots = [
                value
                for value in raw_slots
                if isinstance(value, str) and value in missing_requirement_ids
            ]
        raw_channels = acquisition.get("channel_ranks")
        if isinstance(raw_channels, Mapping):
            channels = sorted(str(value) for value in raw_channels)
    if not channels and isinstance(raw.get("acquisition_channel"), str):
        channels = [str(raw["acquisition_channel"])]
    identity = _digest(
        {
            "evidence_id": evidence_id,
            "source_ref": source_ref,
            "content_hash": raw.get("content_hash"),
        }
    )
    return ResidualCandidateSummary(
        ephemeral_candidate_ref=f"candidate-{identity[:16]}",
        session_ref=f"session-{_digest(session_id)[:16]}",
        speaker=cast(
            Literal["USER", "ASSISTANT", "SYSTEM", "TOOL", "UNKNOWN"],
            speaker.upper(),
        ),
        source_observed_time=raw.get("observed_at"),
        event_time=(
            dict(raw["event_occurrence_interval"])
            if isinstance(raw.get("event_occurrence_interval"), Mapping)
            else None
        ),
        bounded_snippet=_bounded_excerpt(
            content, query_terms, MAX_OBSERVATION_SNIPPET_CHARS
        ),
        matched_terms=sorted(query_terms.intersection(content_terms))[:32],
        matched_channels=channels[:8],
        possible_requirement_ids=sorted(set(matched_slots)),
    )


def _candidate_scope_contains(
    raw_scope: object, constraints: AcquisitionGlobalConstraints
) -> bool:
    if not isinstance(raw_scope, Mapping):
        return False
    return _json_contains(raw_scope, constraints.principal_scope) and _json_contains(
        raw_scope, constraints.semantic_scope
    )


def _json_contains(container: object, required: object) -> bool:
    if isinstance(required, Mapping):
        return isinstance(container, Mapping) and all(
            key in container and _json_contains(container[key], value)
            for key, value in required.items()
        )
    if isinstance(required, list):
        return isinstance(container, list) and all(value in container for value in required)
    return container == required


def _permission_projects_cover_scope(
    permission: Mapping[str, Any], scope: Mapping[str, Any]
) -> bool:
    required = scope.get("project_ids")
    if required is None:
        return True
    offered = permission.get("project_ids")
    return (
        isinstance(required, list)
        and bool(required)
        and all(isinstance(value, str) and value for value in required)
        and isinstance(offered, list)
        and set(required).issubset(
            {value for value in offered if isinstance(value, str) and value}
        )
    )


def _timestamp_at_or_before(value: object, upper: datetime) -> bool:
    parsed = _aware_datetime(value)
    return parsed is not None and parsed <= upper


def _source_time_in_range(
    value: object, inherited: Mapping[str, object] | None
) -> bool:
    if inherited is None:
        return True
    parsed = _aware_datetime(value)
    return parsed is not None and _timestamp_in_bounds(parsed, inherited)


def _event_time_in_range(
    value: object, inherited: Mapping[str, object] | None
) -> bool:
    if inherited is None:
        return True
    if not isinstance(value, Mapping):
        return False
    start = _aware_datetime(value.get("start"))
    end = _aware_datetime(value.get("end"))
    if start is None and end is None:
        return False
    return all(
        timestamp is None or _timestamp_in_bounds(timestamp, inherited)
        for timestamp in (start, end)
    )


def _timestamp_in_bounds(value: datetime, inherited: Mapping[str, object]) -> bool:
    start = _aware_datetime(inherited.get("start"))
    end = _aware_datetime(inherited.get("end"))
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return start is not None or end is not None


def _bounded_excerpt(text: str, terms: frozenset[str], limit: int) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip()
    if len(normalized) <= limit:
        return normalized
    folded = normalized.casefold()
    positions = [folded.find(term) for term in sorted(terms) if term in folded]
    focus = min((value for value in positions if value >= 0), default=0)
    provisional_start = max(0, min(len(normalized) - limit, focus - limit // 3))
    marker_budget = int(provisional_start > 0) + 1
    body_limit = limit - marker_budget
    start = max(0, min(len(normalized) - body_limit, focus - body_limit // 3))
    marker_budget = int(start > 0) + 1
    body_limit = limit - marker_budget
    end = start + body_limit
    return ("\u2026" if start else "") + normalized[start:end] + (
        "\u2026" if end < len(normalized) else ""
    )


def _controller_messages(observation: AcquisitionObservation) -> list[dict[str, str]]:
    system = (
        "Propose one weak residual acquisition cue using the supplied flat JSON schema. "
        "Return exactly requirement_id, action, and cues. Target one listed missing "
        "requirement. SEARCH_LEXICAL needs one or more short vocabulary cues. "
        "SEARCH_TEMPORAL may provide at most one expression cue; Runtime inherits all "
        "normalized time bounds. EXPAND_NEIGHBORS and NO_ACTION require an empty cues "
        "array. Never answer the question, name an Evidence or Claim ID, declare "
        "completeness, choose source roles, state provenance or rationale, change the "
        "operator, scope, principal, permission, authority, or propose a canonical mutation."
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                observation.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    ]


def residual_cue_proposal_output_schema() -> dict[str, Any]:
    """Return only the provider-conformed flat JSON Schema subset."""

    return {
        "type": "object",
        "properties": {
            "requirement_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
            },
            "action": {
                "type": "string",
                "enum": [
                    "SEARCH_LEXICAL",
                    "SEARCH_TEMPORAL",
                    "EXPAND_NEIGHBORS",
                    "NO_ACTION",
                ],
            },
            "cues": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 128},
                "maxItems": 8,
            },
        },
        "required": ["requirement_id", "action", "cues"],
        "additionalProperties": False,
    }


def _validate_completion(completion: SemanticHintCompletion) -> None:
    if completion.provider_calls != 1 or completion.automatic_retry_count != 0:
        raise ResidualRefindingError("RESIDUAL_CONTROLLER_CALL_CEILING_VIOLATED")
    if not 0 <= completion.completion_tokens <= MAX_RESIDUAL_COMPLETION_TOKENS:
        raise ResidualRefindingError("RESIDUAL_CONTROLLER_COMPLETION_BUDGET_VIOLATED")
    if completion.finish_reason == "length":
        raise ResidualRefindingError("RESIDUAL_CONTROLLER_OUTPUT_TRUNCATED")
    if not completion.content.strip():
        raise ResidualRefindingError("RESIDUAL_CONTROLLER_EMPTY_OUTPUT")


def _seed(run_id: str, case_id: str) -> int:
    return int(
        hashlib.sha256(f"milai-dg18-residual-v01\0{run_id}\0{case_id}".encode()).hexdigest()[
            :16
        ],
        16,
    ) & ((1 << 63) - 1)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


__all__ = [
    "MAX_OBSERVATION_CANDIDATES",
    "MAX_OBSERVATION_SNIPPET_CHARS",
    "MAX_RESIDUAL_COMPLETION_TOKENS",
    "ResidualHintShadowService",
    "ResidualRefindingError",
    "build_acquisition_observation",
    "normalize_residual_cue_proposal",
    "residual_cue_proposal_output_schema",
    "validate_residual_search_hint",
]
