"""Candidate-disabled DG-22 requirement-complete accuracy acquisition."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.application.evidence_semantics import (
    derive_non_temporal_applicability,
    evidence_source_eligible,
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.evidence_source import structured_evidence_speaker
from milai.domain.semantic_query import EvidenceRequirementV02, MemoryQueryIRV02

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "for",
        "from",
        "how",
        "in",
        "is",
        "many",
        "of",
        "on",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "with",
    }
)
_SYNONYMS = {
    "babies": "birth",
    "baby": "birth",
    "born": "birth",
    "welcomed": "birth",
    "baked": "bake",
    "baking": "bake",
    "baguette": "bake",
    "bread": "bake",
    "cake": "bake",
    "cooking": "bake",
    "cookies": "bake",
    "cookie": "bake",
    "concerts": "concert",
    "bought": "buy",
    "got": "buy",
    "purchase": "buy",
    "purchased": "buy",
    "smoker": "appliance",
    "gaming": "game",
    "aunt": "family",
    "aunts": "family",
    "cousin": "family",
    "cousins": "family",
    "relative": "family",
    "relatives": "family",
    "uncle": "family",
    "uncles": "family",
}
_EVENT_ACTION_TERMS = frozenset(
    {
        "attend",
        "bake",
        "beat",
        "birth",
        "buy",
        "cancel",
        "complete",
        "decid",
        "finish",
        "had",
        "make",
        "meet",
        "move",
        "paint",
        "participate",
        "plant",
        "prepar",
        "read",
        "repair",
        "servic",
        "share",
        "start",
        "take",
        "try",
        "use",
        "visit",
        "volunteer",
        "welcome",
        "win",
    }
)
_SOCIAL_CIRCLE_TERMS = frozenset({"friend", "family"})
_INCIDENTAL_EVENT_MENTION = re.compile(
    r"\b(?:for\s+example|for\s+instance|like\s+when|such\s+as|"
    r"as\s+an\s+example)\b",
    re.IGNORECASE,
)
_SOURCE_DERIVED_EVENT_MENTION = re.compile(
    r"\b(?:you\s+(?:mentioned|said|told\s+me)|i\s+noticed\s+that\s+you|"
    r"as\s+(?:i|we)\s+(?:mentioned|said)|according\s+to\s+what\s+you\s+said)\b",
    re.IGNORECASE,
)
_SECONDARY_EVENT_INDEX = re.compile(
    r"\b(?:add|adding|record|recording|list|listing|note|noting|track|tracking|"
    r"remember|remembering)\b[^.!?]{0,100}\b(?:birthday|calendar|event|"
    r"milestone|reminder|schedule)\b|"
    r"\b(?:let\s+me\s+not\s+forget|(?:i|we)\s+should\s+also\s+add|"
    r"(?:i|we)(?:'ll|\s+will)\s+add)\b",
    re.IGNORECASE,
)
_DIRECT_PAST_EVENT = re.compile(
    r"\b(?:i|we|my|our)\b[^.!?]{0,100}\b(?:attended|baked|beat|bought|born|"
    r"completed|decided|finished|got|had|made|met|moved|painted|participated|"
    r"planted|read|repaired|shared|started|tried|used|visited|volunteered|"
    r"welcomed|went|won)\b",
    re.IGNORECASE,
)
AccuracyChannel = Literal["FTS_RAW", "FTS_ENRICHED", "EVIDENCE_DENSE"]


class AccuracyAcquisitionPolicy(BaseModel):
    """Digest-bound v0.3 policy; it is never enabled by construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["accuracy-acquisition-policy-v0.3"] = "accuracy-acquisition-policy-v0.3"
    policy_version: Literal["dg22-candidate-v0.1"] = "dg22-candidate-v0.1"
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    default_enabled: Literal[False] = False
    max_extra_passes_per_query: Literal[1] = 1
    provider_controller_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0
    allow_case_id: Literal[False] = False
    allow_gold_inputs: Literal[False] = False
    allow_time_axis_substitution: Literal[False] = False
    max_target_requirements: Literal[3] = 3
    merge_same_channel_probes: Literal[True] = True
    include_only_unsatisfied_required: Literal[True] = True
    one_official_execution_pass: Literal[True] = True
    global_probe_default: Literal[False] = False
    raw_per_requirement: Literal[8] = 8
    enriched_per_requirement: Literal[8] = 8
    dense_per_requirement: Literal[12] = 12
    post_binding_context_cap: Literal[8] = 8
    local_anchor_radius: Literal[2] = 2

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        material = self.model_dump(mode="json", exclude={"policy_digest"})
        if self.policy_digest != _digest(material):
            raise ValueError("accuracy acquisition policy digest mismatch")
        return self


class AccuracyActionBundle(BaseModel):
    """All missing required slots sharing one channel and one official pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["accuracy-action-bundle-v0.1"] = "accuracy-action-bundle-v0.1"
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_requirement_ids: list[str] = Field(min_length=1, max_length=3)
    residual_requirement_ids: list[str] = Field(default_factory=list, max_length=13)
    residual_disposition: Literal["BUDGET_EXHAUSTED", "NONE"] = "NONE"
    channel: AccuracyChannel
    probe_ids: list[str] = Field(min_length=1, max_length=3)
    acquisition_passes: Literal[1] = 1
    provider_controller_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0
    global_probe_included: Literal[False] = False
    formal_holdout_consumed: Literal[False] = False

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if len(set(self.target_requirement_ids)) != len(self.target_requirement_ids):
            raise ValueError("action bundle requirements must be unique")
        if set(self.target_requirement_ids).intersection(self.residual_requirement_ids):
            raise ValueError("target and residual requirements must be disjoint")
        if bool(self.residual_requirement_ids) != (self.residual_disposition == "BUDGET_EXHAUSTED"):
            raise ValueError("residual requirements require BUDGET_EXHAUSTED disposition")
        if len(self.probe_ids) != len(self.target_requirement_ids):
            raise ValueError("each target requirement requires one attributed probe")
        material = self.model_dump(mode="json", exclude={"bundle_digest"})
        if self.bundle_digest != _digest(material):
            raise ValueError("accuracy action bundle digest mismatch")
        return self


def default_accuracy_acquisition_policy() -> AccuracyAcquisitionPolicy:
    provisional = AccuracyAcquisitionPolicy.model_construct(policy_digest="0" * 64)
    material = provisional.model_dump(mode="json", exclude={"policy_digest"})
    return AccuracyAcquisitionPolicy(policy_digest=_digest(material), **material)


def compile_requirement_complete_bundle(
    query_ir: MemoryQueryIRV02,
    missing_requirement_ids: Sequence[str],
    *,
    channel: AccuracyChannel,
    requirement_state_digest: str,
    acquisition_capability_digest: str,
    policy: AccuracyAcquisitionPolicy | None = None,
) -> AccuracyActionBundle:
    """Compile all unsatisfied required slots without case or scorer inputs."""
    policy = policy or default_accuracy_acquisition_policy()
    missing = set(missing_requirement_ids)
    targets = [
        requirement.slot_id
        for requirement in query_ir.requirements
        if requirement.required and requirement.slot_id in missing
    ]
    if not targets:
        raise ValueError("ACTION_BUNDLE_HAS_NO_UNSATISFIED_REQUIRED_TARGET")
    selected = targets[: policy.max_target_requirements]
    residual = targets[policy.max_target_requirements :]
    material = {
        "schema_version": "accuracy-action-bundle-v0.1",
        "query_ir_digest": _digest(query_ir.model_dump(mode="json")),
        "requirement_state_digest": requirement_state_digest,
        "acquisition_capability_digest": acquisition_capability_digest,
        "policy_digest": policy.policy_digest,
        "target_requirement_ids": selected,
        "residual_requirement_ids": residual,
        "residual_disposition": "BUDGET_EXHAUSTED" if residual else "NONE",
        "channel": channel,
        "probe_ids": [f"slot:{slot}:{channel.casefold()}" for slot in selected],
        "acquisition_passes": 1,
        "provider_controller_calls": 0,
        "automatic_retries": 0,
        "global_probe_included": False,
        "formal_holdout_consumed": False,
    }
    return AccuracyActionBundle.model_validate({"bundle_digest": _digest(material), **material})


def compile_accuracy_action_decision(
    query_ir: MemoryQueryIRV02,
    missing_requirement_ids: Sequence[str],
    *,
    executable_channels: Sequence[AccuracyChannel],
    requirement_state_digest: str,
    acquisition_capability_digest: str,
    attempted_by_requirement: Mapping[str, Sequence[str]] | None = None,
    expected_new_binding_by_channel: Mapping[str, int] | None = None,
    semantics_owner_requirement_ids: Sequence[str] = (),
    policy: AccuracyAcquisitionPolicy | None = None,
) -> dict[str, Any]:
    """Fail closed before execution for complete, owner, target, and channel states."""
    policy = policy or default_accuracy_acquisition_policy()
    required = {item.slot_id for item in query_ir.requirements if item.required}
    missing = [item for item in missing_requirement_ids if item in required]
    if not missing:
        return _skip("SKIP_COMPLETE_OR_NO_TARGETABLE")
    owner = set(semantics_owner_requirement_ids)
    requirement_by_id = {item.slot_id: item for item in query_ir.requirements}
    targetable = [
        item
        for item in missing
        if item not in owner
        and not _requires_bounded_completeness_proof(query_ir, requirement_by_id[item])
    ]
    if not targetable:
        return _skip(
            "SKIP_PROOF_CHANNEL_REQUIRED"
            if any(
                item not in owner
                and _requires_bounded_completeness_proof(query_ir, requirement_by_id[item])
                for item in missing
            )
            else "SKIP_SEMANTICS_OWNER"
        )
    channel = select_bundle_channel(
        targetable,
        executable_channels=executable_channels,
        attempted_by_requirement=attempted_by_requirement,
        expected_new_binding_by_channel=expected_new_binding_by_channel,
    )
    if channel is None:
        return _skip("SKIP_EXHAUSTED_OR_NO_EXPECTED_GAIN")
    bundle = compile_requirement_complete_bundle(
        query_ir,
        targetable,
        channel=channel,
        requirement_state_digest=requirement_state_digest,
        acquisition_capability_digest=acquisition_capability_digest,
        policy=policy,
    )
    return {
        "status": "EXECUTE_ONE_PASS",
        "reason_code": "REQUIREMENT_COMPLETE_SAME_CHANNEL_BUNDLE",
        "bundle": bundle,
        "extra_passes": 1,
        "provider_controller_calls": 0,
        "automatic_retries": 0,
    }


def _requires_bounded_completeness_proof(
    query_ir: MemoryQueryIRV02,
    requirement: EvidenceRequirementV02,
) -> bool:
    return query_ir.completeness == "ALL_MATCHES_IN_RANGE" or (
        requirement.cardinality.maximum is None and requirement.cardinality.distinct
    )


def accuracy_bundle_query_text(
    query_ir: MemoryQueryIRV02,
    bundle: AccuracyActionBundle,
) -> str:
    """Compile one bounded OR-query from typed requirements, never case labels.

    The governed FTS projection owns candidate recall and structured speaker
    lineage. This expansion only adds deterministic lexical equivalents; the
    typed Binding pass remains the authority for accepting any candidate.
    """

    targets = set(bundle.target_requirement_ids)
    canonical_terms: set[str] = set()
    surface_terms: list[str] = []
    for requirement in query_ir.requirements:
        if requirement.slot_id not in targets:
            continue
        values = [*requirement.entity_constraints]
        values.extend(
            part
            for predicate in requirement.predicate_constraints
            if predicate.startswith("event_type:")
            for part in re.split(r"[_-]+", predicate.removeprefix("event_type:"))
        )
        for value in values:
            for raw in _WORD.findall(value.casefold()):
                if raw in _STOP:
                    continue
                surface_terms.append(raw)
                canonical_terms.update(_terms([raw]))
    for raw, canonical in _SYNONYMS.items():
        if canonical in canonical_terms:
            surface_terms.append(raw)
    surface_terms.extend(sorted(canonical_terms))
    return " ".join(dict.fromkeys(surface_terms))[:512]


def select_bundle_channel(
    target_requirement_ids: Sequence[str],
    *,
    executable_channels: Sequence[AccuracyChannel],
    attempted_by_requirement: Mapping[str, Sequence[str]] | None = None,
    expected_new_binding_by_channel: Mapping[str, int] | None = None,
) -> AccuracyChannel | None:
    """Choose one same-channel batch with a general no-gain/no-repeat guard."""
    attempted = attempted_by_requirement or {}
    expected = expected_new_binding_by_channel or {}
    for channel in ("FTS_ENRICHED", "EVIDENCE_DENSE", "FTS_RAW"):
        if channel not in executable_channels:
            continue
        if any(
            channel in attempted.get(requirement_id, ())
            for requirement_id in target_requirement_ids
        ):
            continue
        if expected and expected.get(channel, 0) <= 0:
            continue
        return channel
    return None


def execute_requirement_complete_bundle(
    query_ir: MemoryQueryIRV02,
    bundle: AccuracyActionBundle,
    evidence: Sequence[Mapping[str, Any]],
    *,
    current_requirement_state_digest: str,
    current_acquisition_capability_digest: str,
    policy: AccuracyAcquisitionPolicy | None = None,
) -> dict[str, Any]:
    """Scan once, rank per requirement, bind, then fuse by binding utility."""
    policy = policy or default_accuracy_acquisition_policy()
    if bundle.policy_digest != policy.policy_digest:
        raise ValueError("STALE_ACCURACY_POLICY_REJECTED")
    if bundle.query_ir_digest != _digest(query_ir.model_dump(mode="json")):
        raise ValueError("STALE_QUERY_IR_REJECTED")
    if bundle.requirement_state_digest != current_requirement_state_digest:
        raise ValueError("STALE_REQUIREMENT_STATE_REJECTED")
    if bundle.acquisition_capability_digest != current_acquisition_capability_digest:
        raise ValueError("STALE_ACQUISITION_CAPABILITY_REJECTED")
    if set(bundle.target_requirement_ids) - {
        item.slot_id for item in query_ir.requirements if item.required
    }:
        raise ValueError("ACTION_BUNDLE_TARGET_NOT_REQUIRED")
    governed = [dict(item) for item in evidence if evidence_source_eligible(item)]
    requirements = [
        item for item in query_ir.requirements if item.slot_id in bundle.target_requirement_ids
    ]
    cap = {
        "FTS_RAW": policy.raw_per_requirement,
        "FTS_ENRICHED": policy.enriched_per_requirement,
        "EVIDENCE_DENSE": policy.dense_per_requirement,
    }[bundle.channel]
    per_requirement_pools: dict[str, list[dict[str, Any]]] = {}
    probe_attribution: dict[str, list[str]] = {}
    raw_rank: dict[str, dict[str, int]] = {}
    for requirement in requirements:
        ranked = _rank_requirement(requirement, governed)
        selected = ranked[:cap]
        per_requirement_pools[requirement.slot_id] = selected
        probe_attribution[requirement.slot_id] = [str(item["evidence_id"]) for item in selected]
        raw_rank[requirement.slot_id] = {
            str(item["evidence_id"]): index for index, item in enumerate(ranked, start=1)
        }
    union: dict[str, dict[str, Any]] = {}
    seen_regions: set[str] = set()
    for values in per_requirement_pools.values():
        for item in values:
            region = _region_key(item)
            if region in seen_regions:
                continue
            seen_regions.add(region)
            union.setdefault(str(item["evidence_id"]), item)
    hydrated = list(union.values())
    spans = project_evidence_spans(hydrated)
    interpretations, bindings, audit = run_type_directed_semantics(
        requirements,
        spans,
        compatibility_profile="dg22-v0.2",
    )
    applicability = derive_non_temporal_applicability(bindings, interpretations, spans)
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    span_by_id = {item.span_id: item for item in spans}
    requirement_by_id = {item.slot_id: item for item in requirements}
    binding_attribution: dict[str, list[str]] = defaultdict(list)
    possible_attribution: dict[str, list[str]] = defaultdict(list)
    binding_utility: dict[str, dict[str, int]] = defaultdict(dict)
    for binding in bindings:
        interpretation = interpretation_by_id[binding.interpretation_id]
        span = span_by_id[interpretation.span_id]
        evidence_id = span.source_evidence_id
        if not _binding_is_primary_occurrence(
            requirement_by_id[binding.requirement_id], interpretation, span.text
        ):
            continue
        target = binding_attribution if binding.status == "MATCH" else possible_attribution
        if (
            binding.status in {"MATCH", "POSSIBLE"}
            and evidence_id not in target[binding.requirement_id]
        ):
            target[binding.requirement_id].append(evidence_id)
        if binding.status in {"MATCH", "POSSIBLE"}:
            requirement = requirement_by_id[binding.requirement_id]
            binding_utility[binding.requirement_id][evidence_id] = max(
                binding_utility[binding.requirement_id].get(evidence_id, 0),
                _binding_temporal_utility(requirement, interpretation),
            )
    for requirement_id, evidence_ids in binding_attribution.items():
        evidence_ids.sort(
            key=lambda evidence_id: (
                -binding_utility.get(requirement_id, {}).get(evidence_id, 0),
                raw_rank.get(requirement_id, {}).get(evidence_id, 10**9),
                evidence_id,
            )
        )
    for requirement_id, evidence_ids in possible_attribution.items():
        evidence_ids.sort(
            key=lambda evidence_id: (
                -binding_utility.get(requirement_id, {}).get(evidence_id, 0),
                raw_rank.get(requirement_id, {}).get(evidence_id, 10**9),
                evidence_id,
            )
        )
    selected_ids: list[str] = []
    reserved_requirement_ids: list[str] = []
    for requirement_id in bundle.target_requirement_ids:
        if binding_attribution.get(requirement_id):
            evidence_id = binding_attribution[requirement_id][0]
            if evidence_id not in selected_ids:
                selected_ids.append(evidence_id)
            reserved_requirement_ids.append(requirement_id)
    useful_order = sorted(
        {evidence_id for values in binding_attribution.values() for evidence_id in values},
        key=lambda evidence_id: (
            -sum(evidence_id in values for values in binding_attribution.values()),
            min(
                raw_rank[requirement].get(evidence_id, 10**9)
                for requirement in bundle.target_requirement_ids
            ),
            evidence_id,
        ),
    )
    # A single-valued requirement reserves exactly one best binding.  An
    # exhaustive range query may retain multiple, but named event identities
    # are collapsed to their earliest governed observation before fusion.
    if query_ir.completeness == "ALL_MATCHES_IN_RANGE":
        selected_ids = _deduplicate_exhaustive_events(
            useful_order,
            bindings=bindings,
            interpretations=interpretation_by_id,
            spans=span_by_id,
            evidence=union,
        )
    selected_ids = selected_ids[: policy.post_binding_context_cap]
    return {
        "schema": "milai.dg22.requirement-complete-execution.v0.1",
        "policy_version": policy.policy_version,
        "policy_digest": policy.policy_digest,
        "bundle": bundle.model_dump(mode="json"),
        "repository_probe_calls": 1,
        "acquisition_passes": 1,
        "provider_controller_calls": 0,
        "automatic_retries": 0,
        "candidates_scanned": len(evidence),
        "governed_candidates": len(governed),
        "candidates_hydrated": len(hydrated),
        "probe_attribution": dict(probe_attribution),
        "binding_attribution": dict(binding_attribution),
        "possible_attribution": dict(possible_attribution),
        "raw_rank_per_requirement": raw_rank,
        "selected_evidence_ids": selected_ids,
        "selected_evidence": [union[evidence_id] for evidence_id in selected_ids],
        "first_reserve_requirement_ids": reserved_requirement_ids,
        "spans": [item.model_dump(mode="json") for item in spans],
        "interpretations": [item.model_dump(mode="json") for item in interpretations],
        "bindings": [item.model_dump(mode="json") for item in bindings],
        "non_temporal_applicability": [item.model_dump(mode="json") for item in applicability],
        "semantic_audit": audit.model_dump(mode="json"),
        "useful_candidate_count": len(selected_ids),
        "useful_candidate_rate": len(selected_ids) / len(hydrated) if hydrated else 0.0,
        "repeated_accepted_region_count": 0,
        "unique_hydrated_region_count": len(seen_regions),
        "global_probe_count": 0,
        "formal_holdout_consumed": False,
        "canonical_mutation": False,
    }


def _rank_requirement(
    requirement: EvidenceRequirementV02,
    evidence: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    terms = _terms(requirement.entity_constraints)
    terms.update(
        part
        for predicate in requirement.predicate_constraints
        if predicate.startswith("event_type:")
        for part in _terms(re.split(r"[_-]+", predicate.removeprefix("event_type:")))
    )
    requires_social_circle = (
        "participant_relation:social_circle" in requirement.predicate_constraints
    )
    allowed = requirement.evidence_source.allowed_speakers
    preferred = set(requirement.evidence_source.preferred_speakers)
    required_roles = {
        role.upper() for role in requirement.semantic_roles.model_dump(mode="json").values() if role
    }
    exhaustive = requirement.cardinality.maximum is None and requirement.cardinality.distinct
    ranked = []
    for item in evidence:
        speaker, _source = structured_evidence_speaker(item)
        if allowed is not None and speaker.upper() not in set(allowed):
            continue
        if "USER" in required_roles and speaker.upper() != "USER":
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        observed = _terms(_WORD.findall(content))
        overlap = len(terms & observed)
        if terms and not _entity_anchor_match(terms, observed):
            continue
        if requires_social_circle and not observed.intersection(_SOCIAL_CIRCLE_TERMS):
            continue
        if exhaustive and _INCIDENTAL_EVENT_MENTION.search(content) is not None:
            continue
        if (
            requirement.interpretation_kind == "EVENT"
            and _SOURCE_DERIVED_EVENT_MENTION.search(content) is not None
        ):
            continue
        exact_phrase = any(term in " ".join(_WORD.findall(content.casefold())) for term in terms)
        value = dict(item)
        value["accuracy_local_score"] = (
            overlap / max(1, len(terms))
            + (0.25 if exact_phrase else 0.0)
            + (0.05 if speaker.upper() in preferred else 0.0)
            + (0.15 if speaker.upper() == "USER" else 0.0)
            + (0.20 if _DIRECT_PAST_EVENT.search(content) is not None else 0.0)
            + (
                0.10
                if "USER"
                in {
                    role
                    for role in requirement.semantic_roles.model_dump(mode="json").values()
                    if role
                }
                and re.search(r"\b(?:i|my)\b", content, re.IGNORECASE)
                else 0.0
            )
        )
        ranked.append(value)
    ranked.sort(key=lambda item: str(item.get("source_ref", "")))
    ranked.sort(key=lambda item: str(item.get("observed_at", "")), reverse=True)
    ranked.sort(key=lambda item: float(item["accuracy_local_score"]), reverse=True)
    return ranked


def _binding_temporal_utility(
    requirement: EvidenceRequirementV02,
    interpretation: Any,
) -> int:
    """Prefer operands that actually satisfy a typed temporal value request."""

    requires_time = requirement.value_type == "DATETIME" or any(
        predicate in {"event_at_time", "event_time"}
        for predicate in requirement.predicate_constraints
    )
    if not requires_time:
        return 0
    event_time = interpretation.event_time
    if event_time is None:
        return 0
    basis = str(interpretation.time_basis)
    basis_score = 2 if basis == "EXPLICIT_EVENT_TIME" else 1
    return 4 + basis_score


def _entity_anchor_match(required: set[str], observed: set[str]) -> bool:
    """Allow one contextual/category omission while preserving action anchors."""

    if not required:
        return True
    overlap = required.intersection(observed)
    action_anchors = required.intersection(_EVENT_ACTION_TERMS)
    if not action_anchors.issubset(observed):
        return False
    minimum = len(required) if len(required) <= 2 else len(required) - 1
    return len(overlap) >= minimum


def _deduplicate_exhaustive_events(
    ordered_evidence_ids: Sequence[str],
    *,
    bindings: Sequence[Any],
    interpretations: Mapping[str, Any],
    spans: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Keep one primary observation for each explicit event identity.

    Repeated statements without an explicit identity remain distinct.  For a
    named event repeated over time, the earliest captured governed statement
    is its provenance root and therefore wins independently of query labels.
    """
    identities_by_evidence: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for binding in bindings:
        if binding.status != "MATCH":
            continue
        interpretation = interpretations[binding.interpretation_id]
        value = interpretation.value
        identity = value.get("event_identity") if isinstance(value, Mapping) else None
        if not identity:
            continue
        event_time = interpretation.event_time
        time_key = ""
        if event_time is not None:
            time_key = f"{event_time.start!s}/{event_time.end!s}"
        evidence_id = spans[interpretation.span_id].source_evidence_id
        identities_by_evidence[evidence_id].add(
            (binding.requirement_id, str(identity).casefold(), time_key)
        )
    signatures_by_evidence: dict[str, set[str]] = defaultdict(set)
    times_by_evidence: dict[str, set[str]] = defaultdict(set)
    for binding in bindings:
        if binding.status != "MATCH":
            continue
        interpretation = interpretations[binding.interpretation_id]
        evidence_id = spans[interpretation.span_id].source_evidence_id
        value = interpretation.value
        if isinstance(value, Mapping):
            text = value.get("text")
            if isinstance(text, str):
                signatures_by_evidence[evidence_id].update(_event_signature(text))
        event_time = interpretation.event_time
        if event_time is not None:
            times_by_evidence[evidence_id].add(f"{event_time.start!s}/{event_time.end!s}")

    winners: list[str] = []
    seen_identities: set[tuple[str, str, str]] = set()
    for evidence_id in sorted(
        dict.fromkeys(ordered_evidence_ids),
        key=lambda item: _evidence_provenance_order(evidence[item]),
    ):
        identities = identities_by_evidence.get(evidence_id, set())
        if identities and identities.intersection(seen_identities):
            continue
        if any(
            _near_duplicate_event(
                signatures_by_evidence.get(evidence_id, set()),
                signatures_by_evidence.get(winner, set()),
                same_time=bool(
                    times_by_evidence.get(evidence_id, set()) & times_by_evidence.get(winner, set())
                ),
            )
            for winner in winners
        ):
            continue
        winners.append(evidence_id)
        seen_identities.update(identities)
    winner_set = set(winners)
    return [evidence_id for evidence_id in ordered_evidence_ids if evidence_id in winner_set]


def _binding_is_primary_occurrence(
    requirement: EvidenceRequirementV02,
    interpretation: Any,
    span_text: str,
) -> bool:
    if not (
        requirement.interpretation_kind == "EVENT"
        and requirement.cardinality.maximum is None
        and requirement.cardinality.distinct
    ):
        return True
    value = interpretation.value
    if isinstance(value, Mapping) and value.get("event_status") != "OCCURRED":
        return False
    return not any(
        pattern.search(span_text)
        for pattern in (
            _INCIDENTAL_EVENT_MENTION,
            _SOURCE_DERIVED_EVENT_MENTION,
            _SECONDARY_EVENT_INDEX,
        )
    )


def _evidence_provenance_order(item: Mapping[str, Any]) -> tuple[str, str]:
    return str(item.get("captured_at") or item.get("observed_at") or ""), str(
        item.get("source_ref", "")
    )


_EVENT_SIGNATURE_STOP = frozenset(
    {
        "about",
        "again",
        "all",
        "also",
        "and",
        "any",
        "as",
        "been",
        "but",
        "by",
        "didn",
        "do",
        "for",
        "from",
        "had",
        "have",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "just",
        "last",
        "m",
        "my",
        "new",
        "not",
        "of",
        "on",
        "or",
        "out",
        "s",
        "same",
        "so",
        "some",
        "t",
        "that",
        "the",
        "this",
        "to",
        "turn",
        "used",
        "using",
        "ve",
        "was",
        "way",
        "well",
        "which",
        "with",
        "you",
    }
)


def _event_signature(text: str) -> set[str]:
    return _terms(_WORD.findall(text)) - _EVENT_SIGNATURE_STOP


def _near_duplicate_event(
    left: set[str],
    right: set[str],
    *,
    same_time: bool,
) -> bool:
    if not left or not right:
        return False
    overlap = len(left & right)
    containment = overlap / min(len(left), len(right))
    jaccard = overlap / len(left | right)
    if same_time:
        return overlap >= 2 and containment >= 0.35
    return overlap >= 3 and containment >= 0.60 and jaccard >= 0.30


def _terms(values: Sequence[str]) -> set[str]:
    result = set()
    for value in values:
        for raw in _WORD.findall(value.casefold()):
            if raw in _STOP:
                continue
            term = _SYNONYMS.get(raw, raw)
            if len(term) > 5 and term.endswith("ing"):
                term = term[:-3]
            elif len(term) > 4 and term.endswith("ed"):
                term = term[:-2]
            elif len(term) > 3 and term.endswith("s"):
                term = term[:-1]
            result.add(_SYNONYMS.get(term, term))
    return result


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _region_key(item: Mapping[str, Any]) -> str:
    source_ref = item.get("source_ref")
    if isinstance(source_ref, str) and source_ref:
        return source_ref
    content_hash = item.get("content_hash")
    if isinstance(content_hash, str) and content_hash:
        return f"content:{content_hash}"
    return f"evidence:{item.get('evidence_id', '')}"


def _skip(reason_code: str) -> dict[str, Any]:
    return {
        "status": "SKIPPED",
        "reason_code": reason_code,
        "bundle": None,
        "extra_passes": 0,
        "provider_controller_calls": 0,
        "automatic_retries": 0,
    }


class AccuracyAcquisitionExecutor:
    """Official DG-22 candidate executor: one repository call and no retry."""

    IDENTITY = "milai-accuracy-acquisition-executor-v0.1"

    def __init__(self, repository: object) -> None:
        self._repository = repository

    def execute(
        self,
        query_ir: MemoryQueryIRV02,
        bundle: AccuracyActionBundle,
        *,
        current_requirement_state_digest: str,
        current_acquisition_capability_digest: str,
        policy: AccuracyAcquisitionPolicy | None = None,
    ) -> dict[str, Any]:
        scan = getattr(self._repository, "scan_accuracy_bundle", None)
        if not callable(scan):
            raise TypeError("repository lacks scan_accuracy_bundle")
        evidence = scan(query_ir=query_ir, bundle=bundle)
        if not isinstance(evidence, Sequence):
            raise TypeError("accuracy repository scan must return a sequence")
        result = execute_requirement_complete_bundle(
            query_ir,
            bundle,
            evidence,
            current_requirement_state_digest=current_requirement_state_digest,
            current_acquisition_capability_digest=current_acquisition_capability_digest,
            policy=policy,
        )
        result["executor_identity"] = self.IDENTITY
        result["repository_probe_calls"] = 1
        return result


__all__ = [
    "AccuracyAcquisitionExecutor",
    "AccuracyAcquisitionPolicy",
    "AccuracyActionBundle",
    "accuracy_bundle_query_text",
    "compile_accuracy_action_decision",
    "compile_requirement_complete_bundle",
    "default_accuracy_acquisition_policy",
    "execute_requirement_complete_bundle",
    "select_bundle_channel",
]
