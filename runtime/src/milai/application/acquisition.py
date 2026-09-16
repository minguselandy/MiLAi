from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from milai.application.evidence_atoms import evidence_requirement_query
from milai.application.evidence_source import (
    structured_evidence_identity,
    structured_evidence_speaker,
)
from milai.application.lexical_cues import enriched_lexical_terms
from milai.application.source_time import (
    compile_event_time_point_bucket,
    compile_source_time_point_bucket,
)
from milai.domain.acquisition import (
    AcquisitionBudget,
    AcquisitionEvidenceSourcePolicy,
    AcquisitionFusion,
    AcquisitionGlobalConstraints,
    AcquisitionPlan,
    AcquisitionProbe,
    AcquisitionResidualPolicy,
    AcquisitionSemanticSubject,
    AcquisitionTemporalAxis,
    CandidateEnvelope,
)
from milai.domain.acquisition_execution_policy import SourceTimePointProfile
from milai.domain.retrieval import QueryPlan
from milai.domain.semantic_query import EvidenceRequirementV02
from milai.persistence.retrieval_repository import evidence_query_terms

_A2_FUSION_POLICY = "RRF_K60_PER_SLOT_QUOTA_THEN_GLOBAL_CAP_V1"
_A4_FUSION_POLICY = "RRF_K60_PER_SLOT_RAW_PLUS_ENRICHED_V1"
_A6_FUSION_POLICY = "RRF_K60_PER_SLOT_FTS_PLUS_EVIDENCE_DENSE_V1"
_QUANTITY_QUESTION = re.compile(r"\bhow\s+(many|much|long)\b", re.IGNORECASE)
_QUANTITY_VALUE = re.compile(
    r"(?:[$€£]\s*\d)|(?:\b\d+(?:\.\d+)?\b)|"
    r"(?:\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve)\b)|"
    r"(?:\b(?:over|under|about|nearly|almost)\s+(?:a|an|one)\s+"
    r"(?:day|week|month|year)s?\b)",
    re.IGNORECASE,
)
_DURATION_VALUE = re.compile(
    r"\b(?:over|under|about|nearly|almost)\s+(?:a|an|one)\s+"
    r"(?:day|week|month|year)s?\b|\b\d+(?:\.\d+)?\s+"
    r"(?:day|week|month|year)s?\b",
    re.IGNORECASE,
)


def compile_acquisition_plan(
    plan: QueryPlan,
    *,
    query: str,
    principal_scope: Mapping[str, object],
    authority_floor: str,
    candidate_limit: int,
    context_tokens: int,
    tenant_id: str | None = None,
    principal_id: str | None = None,
    enable_enriched: bool = False,
    enable_dense: bool = False,
    include_global_probe: bool = True,
    source_time_point_profile: SourceTimePointProfile | None = None,
) -> AcquisitionPlan:
    """Compile the deterministic query IR into A2 raw-FTS probes."""

    if candidate_limit < 1 or candidate_limit > 256:
        raise ValueError("candidate_limit must be between 1 and 256")
    query_ir = plan.memory_query_ir
    requirements = (
        [requirement for requirement in query_ir.requirements if requirement.required]
        if query_ir is not None and query_ir.mode != "AMBIGUOUS"
        else []
    )
    query_terms = evidence_query_terms(query)
    if not query_terms:
        raise ValueError("raw-FTS acquisition requires at least one safe query term")
    cue_by_slot = (
        {cue.requirement_slot: cue for cue in query_ir.lexical_cues} if query_ir is not None else {}
    )
    enriched_slots = {
        requirement.slot_id
        for requirement in requirements
        if enable_enriched
        and (cue := cue_by_slot.get(requirement.slot_id)) is not None
        and set(enriched_lexical_terms(cue)) != set(cue.surface_terms)
    }
    lexical_probe_count = (
        (1 if include_global_probe else 0) + len(requirements) + len(enriched_slots)
    )
    if lexical_probe_count == 0:
        raise ValueError("requirement-local acquisition requires a target requirement")
    # Dense retrieval is an independent full-turn channel. Enabling it must not
    # silently reduce the already-compiled lexical probe budget.
    per_probe_limit = max(1, candidate_limit // lexical_probe_count)
    probes: list[AcquisitionProbe] = []
    if include_global_probe:
        probes.append(
            AcquisitionProbe(
                probe_id="global:fts-raw",
                requirement_slot=None,
                channel="FTS_RAW",
                semantic_subject=AcquisitionSemanticSubject(),
                evidence_source_policy=AcquisitionEvidenceSourcePolicy(),
                lexical_terms=query_terms,
                phrases=[],
                predicate_family=None,
                entities=list(plan.entities),
                temporal_axis="NONE",
                candidate_limit=per_probe_limit,
                expansion_policy="NONE",
            )
        )
    if enable_dense and include_global_probe:
        probes.append(
            AcquisitionProbe(
                probe_id="global:evidence-dense",
                requirement_slot=None,
                channel="EVIDENCE_DENSE",
                dense_query_text=query,
                semantic_subject=AcquisitionSemanticSubject(),
                evidence_source_policy=AcquisitionEvidenceSourcePolicy(),
                lexical_terms=[],
                phrases=[],
                predicate_family=None,
                entities=list(plan.entities),
                temporal_axis="NONE",
                candidate_limit=min(candidate_limit, 30),
                expansion_policy="NONE",
            )
        )
    per_slot_quota: dict[str, int] = {}
    for requirement in requirements:
        query_text = evidence_requirement_query(requirement)
        if not query_text:
            # An explicit disposition remains present even when only the global
            # query can safely supply a lexical cue for this typed requirement.
            query_text = " ".join(query_terms)
        probes.append(
            AcquisitionProbe(
                probe_id=f"slot:{requirement.slot_id}:fts-raw",
                requirement_slot=requirement.slot_id,
                channel="FTS_RAW",
                semantic_subject=AcquisitionSemanticSubject.model_validate(
                    requirement.semantic_roles.model_dump(mode="json")
                ),
                evidence_source_policy=AcquisitionEvidenceSourcePolicy.model_validate(
                    requirement.evidence_source.model_dump(mode="json")
                ),
                lexical_terms=evidence_query_terms(query_text),
                phrases=[],
                predicate_family=_predicate_family(requirement),
                entities=list(requirement.entity_constraints),
                temporal_axis=_temporal_axis(requirement),
                candidate_limit=per_probe_limit,
                expansion_policy="NONE",
            )
        )
        per_slot_quota[requirement.slot_id] = per_probe_limit
        if requirement.slot_id in enriched_slots:
            cues = cue_by_slot[requirement.slot_id]
            probes.append(
                AcquisitionProbe(
                    probe_id=f"slot:{requirement.slot_id}:fts-enriched",
                    requirement_slot=requirement.slot_id,
                    channel="FTS_ENRICHED",
                    semantic_subject=AcquisitionSemanticSubject.model_validate(
                        requirement.semantic_roles.model_dump(mode="json")
                    ),
                    evidence_source_policy=AcquisitionEvidenceSourcePolicy.model_validate(
                        requirement.evidence_source.model_dump(mode="json")
                    ),
                    lexical_terms=enriched_lexical_terms(cues),
                    phrases=[],
                    predicate_family=_predicate_family(requirement),
                    entities=list(requirement.entity_constraints),
                    temporal_axis=_temporal_axis(requirement),
                    candidate_limit=per_probe_limit,
                    expansion_policy="NONE",
                )
            )
        if enable_dense:
            probes.append(
                AcquisitionProbe(
                    probe_id=f"slot:{requirement.slot_id}:evidence-dense",
                    requirement_slot=requirement.slot_id,
                    channel="EVIDENCE_DENSE",
                    dense_query_text=query_text,
                    semantic_subject=AcquisitionSemanticSubject.model_validate(
                        requirement.semantic_roles.model_dump(mode="json")
                    ),
                    evidence_source_policy=AcquisitionEvidenceSourcePolicy.model_validate(
                        requirement.evidence_source.model_dump(mode="json")
                    ),
                    lexical_terms=[],
                    phrases=[],
                    predicate_family=_predicate_family(requirement),
                    entities=list(requirement.entity_constraints),
                    temporal_axis=_temporal_axis(requirement),
                    candidate_limit=min(candidate_limit, 30),
                    expansion_policy="NONE",
                )
            )

    source_range: dict[str, object] | None = None
    event_range: dict[str, object] | None = None
    if query_ir is not None and query_ir.constraints.normalized_temporal is not None:
        normalized_temporal = query_ir.constraints.normalized_temporal
        temporal = normalized_temporal.model_dump(mode="json")
        if normalized_temporal.time_axis == "SOURCE_OBSERVED_TIME":
            if normalized_temporal.boundary == "POINT" and source_time_point_profile is not None:
                compilation = compile_source_time_point_bucket(
                    normalized_temporal,
                    source_time_point_profile,
                )
                executable = compilation.executable_range()
                if executable is not None:
                    temporal = executable
            source_range = temporal
        else:
            if normalized_temporal.boundary == "POINT" and source_time_point_profile is not None:
                compilation = compile_event_time_point_bucket(
                    normalized_temporal,
                    source_time_point_profile,
                )
                executable = compilation.executable_range()
                if executable is not None:
                    temporal = executable
            event_range = temporal
    query_ir_payload = (
        query_ir.model_dump(mode="json")
        if query_ir is not None
        else {"schema_version": "memory-query-ir-absent", "query_plan": plan.planner_version}
    )
    return AcquisitionPlan(
        query_ir_digest=_canonical_sha256(query_ir_payload),
        global_constraints=AcquisitionGlobalConstraints(
            principal_scope=cast(dict[str, Any], dict(principal_scope)),
            semantic_scope=cast(dict[str, Any], dict(plan.scope_predicate)),
            tenant_identity_digest=(
                _canonical_sha256(tenant_id) if tenant_id is not None else None
            ),
            principal_identity_digest=(
                _canonical_sha256(principal_id) if principal_id is not None else None
            ),
            authority_floor=authority_floor,
            valid_as_of=plan.time_reference,
            system_as_of=_planned_datetime(plan.time_constraint.get("system_as_of")),
            source_observed_range=cast(dict[str, Any] | None, source_range),
            event_occurrence_range=cast(dict[str, Any] | None, event_range),
        ),
        probes=probes,
        fusion=AcquisitionFusion(
            policy_identity=(
                _A6_FUSION_POLICY
                if enable_dense
                else _A4_FUSION_POLICY
                if enriched_slots
                else _A2_FUSION_POLICY
            ),
            per_slot_quota=per_slot_quota,
            global_cap=candidate_limit,
        ),
        residual_policy=AcquisitionResidualPolicy(),
        budget=AcquisitionBudget(
            latency_ms=plan.deadline_ms,
            candidate_count=candidate_limit,
            hydrate_count=candidate_limit,
            context_tokens=context_tokens,
        ),
    )


def probe_query(probe: AcquisitionProbe) -> str:
    if probe.channel == "EVIDENCE_DENSE":
        assert probe.dense_query_text is not None
        return probe.dense_query_text
    return " ".join(dict.fromkeys([*probe.phrases, *probe.lexical_terms]))


def _planned_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("acquisition plan system_as_of is missing")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("acquisition plan system_as_of must be timezone-aware")
    return parsed


def apply_probe_source_policy(
    probe: AcquisitionProbe,
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply only explicit hard source constraints to structured speaker metadata."""

    allowed = probe.evidence_source_policy.allowed_speakers
    copied = [dict(item) for item in items]
    if allowed is None:
        return copied
    allowed_lower = {speaker.casefold() for speaker in allowed}
    return [item for item in copied if structured_evidence_speaker(item)[0] in allowed_lower]


def fuse_acquisition_probe_results(
    acquisition_plan: AcquisitionPlan,
    probe_results: Sequence[tuple[AcquisitionProbe, Sequence[Mapping[str, Any]]]],
) -> list[dict[str, Any]]:
    """RRF-fuse probes while retaining every slot/probe/channel rank."""

    expected = [probe.probe_id for probe in acquisition_plan.probes]
    observed = [probe.probe_id for probe, _items in probe_results]
    if observed != expected:
        raise ValueError("probe result order/denominator drifted from AcquisitionPlan")
    aggregated: dict[str, dict[str, Any]] = {}
    for probe, items in probe_results:
        for rank, raw in enumerate(items, start=1):
            evidence_id = raw.get("evidence_id")
            source_ref = raw.get("source_ref")
            if not isinstance(evidence_id, str) or not evidence_id:
                raise ValueError("acquisition candidate lacks evidence identity")
            if not isinstance(source_ref, str) or not source_ref:
                raise ValueError("acquisition candidate lacks source-turn identity")
            score = _score(raw.get("relevance_score"))
            state = aggregated.setdefault(
                evidence_id,
                {
                    "raw": dict(raw),
                    "matched_probes": [],
                    "matched_slots": [],
                    "channel_ranks": {},
                    "channel_scores": {},
                    "probe_ranks": {},
                    "probe_scores": {},
                    "matched_fields": [],
                    "fusion_score": 0.0,
                },
            )
            state["matched_probes"].append(probe.probe_id)
            if probe.requirement_slot is not None:
                state["matched_slots"].append(probe.requirement_slot)
            channel_ranks = cast(dict[str, int], state["channel_ranks"])
            channel_scores = cast(dict[str, float], state["channel_scores"])
            channel_ranks[probe.channel] = min(channel_ranks.get(probe.channel, rank), rank)
            channel_scores[probe.channel] = max(channel_scores.get(probe.channel, score), score)
            cast(dict[str, int], state["probe_ranks"])[probe.probe_id] = rank
            cast(dict[str, float], state["probe_scores"])[probe.probe_id] = score
            state["fusion_score"] = float(state["fusion_score"]) + 1.0 / (
                acquisition_plan.fusion.rrf_k + rank
            )
            field = (
                "enriched_lexical_query"
                if probe.channel == "FTS_ENRICHED"
                else "evidence_dense_embedding"
                if probe.channel == "EVIDENCE_DENSE"
                else "lexical_text"
            )
            cast(list[str], state["matched_fields"]).append(field)
            if _preferred_source_matches(probe, raw):
                cast(list[str], state["matched_fields"]).append("speaker")

    ordered_ids = sorted(
        aggregated,
        key=lambda evidence_id: (
            -float(aggregated[evidence_id]["fusion_score"]),
            min(cast(dict[str, int], aggregated[evidence_id]["probe_ranks"]).values()),
            str(cast(dict[str, Any], aggregated[evidence_id]["raw"])["source_ref"]),
            evidence_id,
        ),
    )
    selected_ids: list[str] = []
    for slot in sorted(acquisition_plan.fusion.per_slot_quota):
        quota = acquisition_plan.fusion.per_slot_quota[slot]
        for evidence_id in ordered_ids:
            if slot not in cast(list[str], aggregated[evidence_id]["matched_slots"]):
                continue
            if evidence_id not in selected_ids:
                selected_ids.append(evidence_id)
            if (
                sum(
                    slot in cast(list[str], aggregated[selected]["matched_slots"])
                    for selected in selected_ids
                )
                >= quota
            ):
                break
            if len(selected_ids) >= acquisition_plan.fusion.global_cap:
                break
        if len(selected_ids) >= acquisition_plan.fusion.global_cap:
            break
    for evidence_id in ordered_ids:
        if len(selected_ids) >= acquisition_plan.fusion.global_cap:
            break
        if evidence_id not in selected_ids:
            selected_ids.append(evidence_id)

    fused: list[dict[str, Any]] = []
    for fusion_rank, evidence_id in enumerate(selected_ids, start=1):
        state = aggregated[evidence_id]
        raw = cast(dict[str, Any], state["raw"])
        source_ref = str(raw["source_ref"])
        content = raw.get("content")
        source_identity = structured_evidence_identity(raw, source_ref)
        if source_identity is None:
            continue
        speaker, speaker_source = structured_evidence_speaker(raw)
        envelope = CandidateEnvelope(
            candidate_id=evidence_id,
            source_evidence_id=evidence_id,
            source_turn_ref=source_ref,
            subject_id=source_identity.subject_id,
            session_id=source_identity.session_id,
            turn_id=source_identity.turn_id,
            identity_source=source_identity.identity_source,
            speaker=speaker,
            speaker_source=speaker_source,
            source_observed_at=raw.get("observed_at"),
            event_occurrence_interval=(
                dict(raw["event_occurrence_interval"])
                if isinstance(raw.get("event_occurrence_interval"), Mapping)
                else None
            ),
            matched_probes=sorted(set(cast(list[str], state["matched_probes"]))),
            matched_slots=sorted(set(cast(list[str], state["matched_slots"]))),
            channel_ranks=cast(dict[str, int], state["channel_ranks"]),
            channel_scores=cast(dict[str, float], state["channel_scores"]),
            probe_ranks=cast(dict[str, int], state["probe_ranks"]),
            probe_scores=cast(dict[str, float], state["probe_scores"]),
            fusion_rank=fusion_rank,
            fusion_score=round(float(state["fusion_score"]), 12),
            expansion_origin=None,
            matched_fields=sorted(set(cast(list[str], state["matched_fields"]))),
            body_ref=source_ref,
            body_hydrated=isinstance(content, str),
        )
        item = dict(raw)
        item["acquisition_candidate"] = envelope.model_dump(mode="json")
        item["relevance_score"] = envelope.fusion_score
        fused.append(item)
    return fused


def rank_evidence_turns(
    evidence_results: Sequence[Mapping[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Official deterministic source-turn ranking shared by product and shadow."""

    copied = [dict(item) for item in evidence_results]
    query_terms = set(evidence_query_terms(query))
    quantity_question = _QUANTITY_QUESTION.search(query)

    def score(item: dict[str, Any]) -> float:
        value = item.get("relevance_score")
        return (
            float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
        )

    def coverage(item: dict[str, Any]) -> int:
        terms = set(re.findall(r"[^\W_]+", str(item.get("content", "")).casefold(), re.UNICODE))
        return len(query_terms & terms)

    def answer_signal(item: dict[str, Any]) -> bool:
        if quantity_question is None:
            return False
        content = str(item.get("content", ""))
        if quantity_question.group(1).casefold() == "long":
            return _DURATION_VALUE.search(content) is not None
        for value in _QUANTITY_VALUE.finditer(content):
            neighborhood = content[max(0, value.start() - 72) : min(len(content), value.end() + 72)]
            terms = set(re.findall(r"[^\W_]+", neighborhood.casefold(), re.UNICODE))
            if query_terms & terms:
                return True
        return False

    return sorted(
        copied,
        key=lambda item: (
            item.get("anchor_match") is not True,
            not answer_signal(item),
            -coverage(item),
            -score(item),
            str(item.get("observed_at", "")),
            str(item.get("source_ref", "")),
        ),
    )


def _predicate_family(requirement: EvidenceRequirementV02) -> str | None:
    values = sorted(set(requirement.predicate_constraints))
    return ":".join(values) if values else None


def _temporal_axis(requirement: EvidenceRequirementV02) -> AcquisitionTemporalAxis:
    temporal = requirement.temporal_constraints
    if temporal is None:
        return "NONE"
    return (
        "SOURCE_OBSERVED_TIME"
        if temporal.time_axis == "SOURCE_OBSERVED_TIME"
        else "EVENT_OCCURRENCE_TIME"
    )


def _score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _preferred_source_matches(probe: AcquisitionProbe, item: Mapping[str, Any]) -> bool:
    preferred = {speaker.casefold() for speaker in probe.evidence_source_policy.preferred_speakers}
    if not preferred:
        return False
    speaker, source = structured_evidence_speaker(item)
    return source != "UNKNOWN" and speaker in preferred


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "apply_probe_source_policy",
    "compile_acquisition_plan",
    "fuse_acquisition_probe_results",
    "probe_query",
    "rank_evidence_turns",
]
