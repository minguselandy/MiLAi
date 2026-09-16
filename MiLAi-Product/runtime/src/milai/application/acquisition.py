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
    AcquisitionExpansionPolicy,
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
QUERY_PRESERVING_UNION_POLICY = "QUERY_PRESERVING_FTS_DENSE_SESSION_RRF_V1"
ADDITIVE_UNION_V2_POLICY = "QUERY_PRESERVING_ADDITIVE_FTS_DENSE_RRF_V2"
QUERY_PRESERVING_UNION_CANDIDATE_CAP = 240
QUERY_PRESERVING_UNION_DIRECT_CAP = 40
QUERY_PRESERVING_UNION_HYDRATE_CAP = 160
QUERY_PRESERVING_UNION_CHANNEL_QUOTA = 20
QUERY_PRESERVING_UNION_SESSION_QUOTA = 20
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
    enable_same_session_expansion: bool = False,
    include_global_probe: bool = True,
    source_time_point_profile: SourceTimePointProfile | None = None,
    query_preserving_union: bool = False,
    additive_union_v0_2: bool = False,
) -> AcquisitionPlan:
    """Compile direct-turn probes and an optional bounded locality treatment."""

    if candidate_limit < 1 or candidate_limit > 256:
        raise ValueError("candidate_limit must be between 1 and 256")
    query_ir = plan.memory_query_ir
    requirements = (
        [requirement for requirement in query_ir.requirements if requirement.required]
        if query_ir is not None and query_ir.mode != "AMBIGUOUS"
        else []
    )
    if query_preserving_union and additive_union_v0_2:
        raise ValueError("query-preserving union policies are mutually exclusive")
    probe_requirements = (
        requirements
        if additive_union_v0_2
        else []
        if query_preserving_union
        else requirements
    )
    query_terms = evidence_query_terms(query)
    if not query_terms:
        raise ValueError("raw-FTS acquisition requires at least one safe query term")
    cue_by_slot = (
        {cue.requirement_slot: cue for cue in query_ir.lexical_cues} if query_ir is not None else {}
    )
    enriched_slots = {
        requirement.slot_id
        for requirement in probe_requirements
        if enable_enriched
        and (cue := cue_by_slot.get(requirement.slot_id)) is not None
        and set(enriched_lexical_terms(cue)) != set(cue.surface_terms)
    }
    lexical_probe_count = (
        (1 if include_global_probe else 0) + len(probe_requirements) + len(enriched_slots)
    )
    if lexical_probe_count == 0:
        raise ValueError("requirement-local acquisition requires a target requirement")
    # Dense retrieval is an independent full-turn channel. Enabling it must not
    # silently reduce the already-compiled lexical probe budget.
    per_probe_limit = (
        QUERY_PRESERVING_UNION_DIRECT_CAP
        if query_preserving_union or additive_union_v0_2
        else max(1, candidate_limit // lexical_probe_count)
    )
    expansion_policy: AcquisitionExpansionPolicy = (
        "SAME_SESSION" if enable_same_session_expansion else "NONE"
    )
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
                expansion_policy=expansion_policy,
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
                candidate_limit=(
                    min(30, QUERY_PRESERVING_UNION_DIRECT_CAP)
                    if query_preserving_union or additive_union_v0_2
                    else min(candidate_limit, 30)
                ),
                expansion_policy=expansion_policy,
            )
        )
    per_slot_quota: dict[str, int] = {}
    for requirement in probe_requirements:
        cue = cue_by_slot.get(requirement.slot_id)
        # Retrieval surfaces are planner-owned hints.  Semantic subject/entity
        # constraints remain Binding inputs and must not be overloaded as an
        # FTS query bag.  Legacy plans have equivalent cue/entity terms, so
        # this is behavior-preserving for their compatibility projection.
        query_text = (
            " ".join(cue.surface_terms)
            if cue is not None and cue.surface_terms
            else evidence_requirement_query(requirement)
        )
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
                expansion_policy=expansion_policy,
            )
        )
        # V2 treats compiler output as a soft acquisition hint.  A possibly
        # imperfect QueryIR slot gets one reserved opportunity, never a large
        # quota that can displace the preserved full-query backbone.
        per_slot_quota[requirement.slot_id] = (
            1 if additive_union_v0_2 else per_probe_limit
        )
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
                    expansion_policy=expansion_policy,
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
                    expansion_policy=expansion_policy,
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
                ADDITIVE_UNION_V2_POLICY
                if additive_union_v0_2
                else QUERY_PRESERVING_UNION_POLICY
                if query_preserving_union
                else _A6_FUSION_POLICY
                if enable_dense
                else _A4_FUSION_POLICY
                if enriched_slots
                else _A2_FUSION_POLICY
            ),
            per_slot_quota=per_slot_quota,
            global_cap=(
                QUERY_PRESERVING_UNION_CANDIDATE_CAP
                if query_preserving_union or additive_union_v0_2
                else candidate_limit
            ),
        ),
        residual_policy=AcquisitionResidualPolicy(),
        budget=AcquisitionBudget(
            latency_ms=plan.deadline_ms,
            candidate_count=(
                QUERY_PRESERVING_UNION_CANDIDATE_CAP
                if query_preserving_union or additive_union_v0_2
                else candidate_limit
            ),
            hydrate_count=(
                QUERY_PRESERVING_UNION_HYDRATE_CAP
                if query_preserving_union or additive_union_v0_2
                else candidate_limit
            ),
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
    direct_cap = _direct_fusion_cap(acquisition_plan)
    slot_quotas = acquisition_plan.fusion.per_slot_quota

    if additive_union_v0_2_enabled(acquisition_plan):
        selected_ids.extend(
            _additive_union_v0_2_ids(
                aggregated,
                ordered_ids,
                slot_quotas=slot_quotas,
                direct_cap=direct_cap,
            )
        )
    elif query_preserving_union_enabled(acquisition_plan):
        # Give every governed real session one representative before spending
        # depth on a session already present. Identity comes only from captured
        # structured source metadata; benchmark labels and QueryIR slots never
        # participate in this ordering.
        seen_sessions: set[str] = set()
        for evidence_id in ordered_ids:
            source_identity = structured_evidence_identity(
                cast(dict[str, Any], aggregated[evidence_id]["raw"]),
                str(cast(dict[str, Any], aggregated[evidence_id]["raw"])["source_ref"]),
            )
            if source_identity is None or source_identity.session_id in seen_sessions:
                continue
            selected_ids.append(evidence_id)
            seen_sessions.add(source_identity.session_id)
            if len(selected_ids) >= min(
                direct_cap,
                QUERY_PRESERVING_UNION_SESSION_QUOTA,
            ):
                break

        # Raw FTS and configured Dense have independent opportunities. Their
        # scores are never compared directly; only per-channel rank membership
        # is used to fill each bounded quota.
        channel_order = ("FTS_RAW", "EVIDENCE_DENSE")
        for channel in channel_order:
            while len(selected_ids) < direct_cap:
                covered = sum(
                    channel in cast(dict[str, int], aggregated[item]["channel_ranks"])
                    for item in selected_ids
                )
                if covered >= QUERY_PRESERVING_UNION_CHANNEL_QUOTA:
                    break
                candidate = next(
                    (
                        evidence_id
                        for evidence_id in ordered_ids
                        if evidence_id not in selected_ids
                        and channel
                        in cast(dict[str, int], aggregated[evidence_id]["channel_ranks"])
                    ),
                    None,
                )
                if candidate is None:
                    break
                selected_ids.append(candidate)

    # Give every required role one candidate opportunity before spending the
    # remainder of the direct-turn budget. A single Evidence may legitimately
    # cover more than one role, but one high-quota role cannot starve another.
    for slot in (() if query_preserving_union_enabled(acquisition_plan) else sorted(slot_quotas)):
        if any(slot in cast(list[str], aggregated[item]["matched_slots"]) for item in selected_ids):
            continue
        candidate = next(
            (
                evidence_id
                for evidence_id in ordered_ids
                if evidence_id not in selected_ids
                and slot in cast(list[str], aggregated[evidence_id]["matched_slots"])
            ),
            None,
        )
        if candidate is not None:
            selected_ids.append(candidate)
        if len(selected_ids) >= direct_cap:
            break

    # Preserve a small independent opportunity for every healthy direct lane.
    # This is an identity union, so one Evidence found by several channels may
    # satisfy several lane floors without consuming duplicate capacity.
    channel_priority = {
        "FTS_RAW": 0,
        "EVIDENCE_DENSE": 1,
        "FTS_ENRICHED": 2,
    }
    available_channels = sorted(
        {
            channel
            for value in aggregated.values()
            for channel in cast(dict[str, int], value["channel_ranks"])
        },
        key=lambda channel: (channel_priority.get(channel, 99), channel),
    )
    for channel in available_channels:
        if any(
            channel in cast(dict[str, int], aggregated[item]["channel_ranks"])
            for item in selected_ids
        ):
            continue
        candidate = next(
            (
                evidence_id
                for evidence_id in ordered_ids
                if evidence_id not in selected_ids
                and channel
                in cast(dict[str, int], aggregated[evidence_id]["channel_ranks"])
            ),
            None,
        )
        if candidate is not None:
            selected_ids.append(candidate)
        if len(selected_ids) >= direct_cap:
            break

    # Allocate any remaining per-role quota round-robin, then let global RRF
    # ranking consume unreserved capacity.
    made_progress = True
    while len(selected_ids) < direct_cap and made_progress:
        made_progress = False
        for slot in sorted(slot_quotas):
            covered = sum(
                slot in cast(list[str], aggregated[item]["matched_slots"]) for item in selected_ids
            )
            if covered >= slot_quotas[slot]:
                continue
            candidate = next(
                (
                    evidence_id
                    for evidence_id in ordered_ids
                    if evidence_id not in selected_ids
                    and slot in cast(list[str], aggregated[evidence_id]["matched_slots"])
                ),
                None,
            )
            if candidate is not None:
                selected_ids.append(candidate)
                made_progress = True
            if len(selected_ids) >= direct_cap:
                break
    for evidence_id in ordered_ids:
        if len(selected_ids) >= direct_cap:
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


def _direct_fusion_cap(acquisition_plan: AcquisitionPlan) -> int:
    """Reserve part of the fixed candidate budget for local atomic expansion."""

    if query_preserving_union_enabled(acquisition_plan):
        return QUERY_PRESERVING_UNION_DIRECT_CAP
    global_cap = acquisition_plan.fusion.global_cap
    if not any(
        probe.expansion_policy in {"ADJACENT_TURNS", "SAME_SESSION"}
        for probe in acquisition_plan.probes
    ):
        return global_cap
    role_floor = max(1, len(acquisition_plan.fusion.per_slot_quota))
    expansion_reserve = min(4, max(0, global_cap - role_floor))
    return global_cap - expansion_reserve


def query_preserving_union_enabled(acquisition_plan: AcquisitionPlan) -> bool:
    return acquisition_plan.fusion.policy_identity in {
        QUERY_PRESERVING_UNION_POLICY,
        ADDITIVE_UNION_V2_POLICY,
    }


def additive_union_v0_2_enabled(acquisition_plan: AcquisitionPlan) -> bool:
    return acquisition_plan.fusion.policy_identity == ADDITIVE_UNION_V2_POLICY


def _additive_union_v0_2_ids(
    aggregated: dict[str, dict[str, Any]],
    ordered_ids: Sequence[str],
    *,
    slot_quotas: Mapping[str, int],
    direct_cap: int,
) -> list[str]:
    """Preserve global FTS, then admit bounded additive retrieval lanes.

    The first half of the existing 40-candidate direct budget belongs to the
    original full-query FTS probe.  Requirement-local lexical and Dense probes
    share the remaining half.  Empty partitions may backfill one another, but
    an inferred requirement receives only one reserved opportunity.
    """

    selected: list[str] = []
    selected_set: set[str] = set()
    seen_sessions: set[str] = set()

    def append(candidate_id: str) -> bool:
        if candidate_id in selected_set or len(selected) >= direct_cap:
            return False
        selected.append(candidate_id)
        selected_set.add(candidate_id)
        session_id = _aggregated_session_id(aggregated[candidate_id])
        if session_id is not None:
            seen_sessions.add(session_id)
        return True

    def next_candidate(candidate_ids: Sequence[str]) -> str | None:
        for candidate_id in candidate_ids:
            if candidate_id in selected_set:
                continue
            session_id = _aggregated_session_id(aggregated[candidate_id])
            if session_id is not None and session_id not in seen_sessions:
                return candidate_id
        return next(
            (candidate_id for candidate_id in candidate_ids if candidate_id not in selected_set),
            None,
        )

    global_fts = [
        candidate_id
        for candidate_id in ordered_ids
        if "global:fts-raw"
        in cast(dict[str, int], aggregated[candidate_id]["probe_ranks"])
    ]
    backbone_cap = min(direct_cap, QUERY_PRESERVING_UNION_CHANNEL_QUOTA)
    while len(selected) < backbone_cap:
        candidate = next_candidate(global_fts)
        if candidate is None:
            break
        append(candidate)

    def is_slot_lexical(candidate_id: str) -> bool:
        probe_ids = cast(dict[str, int], aggregated[candidate_id]["probe_ranks"])
        return any(
            probe_id.startswith("slot:")
            and (probe_id.endswith(":fts-raw") or probe_id.endswith(":fts-enriched"))
            for probe_id in probe_ids
        )

    slot_lexical = [candidate_id for candidate_id in ordered_ids if is_slot_lexical(candidate_id)]
    dense = [
        candidate_id
        for candidate_id in ordered_ids
        if "EVIDENCE_DENSE"
        in cast(dict[str, int], aggregated[candidate_id]["channel_ranks"])
    ]
    additive = list(dict.fromkeys([*slot_lexical, *dense]))

    # One opportunity per inferred slot.  A candidate already selected by the
    # global query satisfies the opportunity without spending extra capacity.
    for slot in sorted(slot_quotas):
        if any(
            slot in cast(list[str], aggregated[item]["matched_slots"])
            for item in selected
        ):
            continue
        candidate = next_candidate(
            [
                candidate_id
                for candidate_id in additive
                if slot in cast(list[str], aggregated[candidate_id]["matched_slots"])
            ]
        )
        if candidate is not None:
            append(candidate)
        if len(selected) >= direct_cap:
            return selected

    # Scores from lexical and vector indexes are not compared directly.  Each
    # available lane advances one identity at a time, with unseen sessions
    # preferred inside the lane.
    lanes = (slot_lexical, dense)
    made_progress = True
    while len(selected) < direct_cap and made_progress:
        made_progress = False
        for lane in lanes:
            candidate = next_candidate(lane)
            if candidate is not None:
                made_progress = append(candidate) or made_progress
            if len(selected) >= direct_cap:
                return selected

    # Backfill unused additive capacity from the preserved full-query ranking,
    # then from the complete RRF identity union.
    for pool in (global_fts, list(ordered_ids)):
        while len(selected) < direct_cap:
            candidate = next_candidate(pool)
            if candidate is None:
                break
            append(candidate)
    return selected


def _aggregated_session_id(value: Mapping[str, Any]) -> str | None:
    raw = value.get("raw")
    if not isinstance(raw, Mapping):
        return None
    source_ref = raw.get("source_ref")
    if not isinstance(source_ref, str):
        return None
    identity = structured_evidence_identity(dict(raw), source_ref)
    return identity.session_id if identity is not None else None


def rank_evidence_turns(
    evidence_results: Sequence[Mapping[str, Any]],
    query: str,
    *,
    preferred_speakers: Sequence[str] = (),
    feature_cache: dict[tuple[str, str], tuple[int, bool]] | None = None,
) -> list[dict[str, Any]]:
    """Official deterministic source-turn ranking shared by product and shadow."""

    copied = [dict(item) for item in evidence_results]
    query_terms = set(evidence_query_terms(query))
    quantity_question = _QUANTITY_QUESTION.search(query)
    preferred = {speaker.casefold() for speaker in preferred_speakers}

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

    def preferred_source(item: dict[str, Any]) -> bool:
        speaker, source = structured_evidence_speaker(item)
        return source != "UNKNOWN" and speaker in preferred

    def ranking_key(item: dict[str, Any]) -> tuple[Any, ...]:
        # Only query/text-derived features are reusable. Eligibility, source
        # preferences, scores and the returned rows belong to this probe.
        cache_key = (query, str(item.get("content", "")))
        features = feature_cache.get(cache_key) if feature_cache is not None else None
        if features is None:
            answer = answer_signal(item)
            features = coverage(item), answer
            if feature_cache is not None:
                feature_cache[cache_key] = features
        return (
            item.get("anchor_match") is not True,
            not features[1],
            -features[0],
            not preferred_source(item) if preferred else False,
            -score(item),
            str(item.get("observed_at", "")),
            str(item.get("source_ref", "")),
        )

    return sorted(copied, key=ranking_key)


def _probe_ranking_speakers(probe: AcquisitionProbe) -> tuple[str, ...]:
    """Return a soft source prior without inventing an access constraint."""

    return tuple(probe.evidence_source_policy.preferred_speakers)


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
    "ADDITIVE_UNION_V2_POLICY",
    "QUERY_PRESERVING_UNION_CANDIDATE_CAP",
    "QUERY_PRESERVING_UNION_DIRECT_CAP",
    "QUERY_PRESERVING_UNION_HYDRATE_CAP",
    "QUERY_PRESERVING_UNION_POLICY",
    "additive_union_v0_2_enabled",
    "apply_probe_source_policy",
    "compile_acquisition_plan",
    "fuse_acquisition_probe_results",
    "probe_query",
    "query_preserving_union_enabled",
    "rank_evidence_turns",
]
