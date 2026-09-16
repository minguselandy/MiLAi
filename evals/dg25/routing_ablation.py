"""Pure, label-free DG-25 E1 replay primitives and arm configuration contracts.

The functions in this module never call a repository.  They operate only on
already-sealed official occurrences and compare ranks within a channel.  Raw
scores from different channels are deliberately absent from the API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Self

from milai.domain.requirement_state import canonical_sha256
from pydantic import BaseModel, ConfigDict, Field, model_validator

E1LexicalMode = Literal["LEGACY_HARD_FILTER", "SOFT_RANK_FEATURE"]
PlanContract = Literal["LEGACY_ACCURACY_ACTION_BUNDLE_V01", "REQUIREMENT_PLAN_V01"]
BindingStatus = Literal["MATCH", "POSSIBLE", "NO_MATCH", "NOT_EVALUATED"]
ReplayActionRole = Literal["EVIDENCE_DISCOVERY", "PROOF_CLOSURE"]
ReplayActionKind = Literal[
    "BASELINE_DISCOVERY",
    "REQUIRED_PROOF_CLOSURE",
    "OPTIONAL_DISCOVERY",
]
OptionalActionDisposition = Literal[
    "SELECTED",
    "OPTIONAL_CHANNEL_UNION_DISABLED",
    "NO_EXECUTABLE_OPTIONAL_CHANNEL",
    "BUDGET_NOT_AUTHORIZED",
]


class E1ArmConfigV01(BaseModel):
    """Exact executable component vector for one preregistered E1 arm."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["dg25-e1-arm-config-v0.1"] = "dg25-e1-arm-config-v0.1"
    config_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    arm_id: str = Field(min_length=1, max_length=96)
    ordered_predecessor: str | None
    matched_full_policy_control: str | None
    removed_component: str | None
    plan_contract: PlanContract
    unified_proof_first: bool
    optional_channel_union: bool
    optional_channel_priority: list[str]
    proof_channel_priority: list[str]
    role_reservation: bool
    lexical_mode: E1LexicalMode
    synonym_normalization: bool
    final_k: Literal[8] = 8
    max_actions_per_plan: Literal[2] = 2
    cross_channel_fusion: Literal["RANK_BASED_ONLY"] = "RANK_BASED_ONLY"
    compare_raw_scores_across_channels: Literal[False] = False
    pool_binding_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_source_identities: dict[str, dict[str, Any]]

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        for values in (self.optional_channel_priority, self.proof_channel_priority):
            if len(values) != len(set(values)):
                raise ValueError("channel priorities must be unique")
        if self.removed_component is None and self.matched_full_policy_control is not None:
            raise ValueError("a matched full-policy control requires a removed component")
        if self.removed_component is not None and self.matched_full_policy_control is None:
            raise ValueError("a removed component requires a matched full-policy control")
        material = self.model_dump(mode="json", exclude={"config_digest"})
        if self.config_digest != canonical_sha256(material):
            raise ValueError("E1 arm config digest mismatch")
        return self


class E2ArmConfigV01(BaseModel):
    """Exact cumulative temporal component vector for one E2 arm."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["dg25-e2-arm-config-v0.1"] = "dg25-e2-arm-config-v0.1"
    config_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    arm_id: str = Field(min_length=1, max_length=32)
    ordered_predecessor: str | None
    interval_normalization_version: str | None
    unique_anchor_resolution_version: str | None
    event_identity_dedup_version: str | None
    proof_writer_version: Literal[
        "bounded-range-scan-proof-v0.1",
        "bounded-range-scan-proof-v0.2",
    ]
    proof_validator_version: Literal[
        "dg24-proof-disposition-v0.1",
        "bounded-range-scan-proof-validator-v0.2",
    ]
    t2_applicability_source: Literal["PRELABEL_COMMON_INPUT"] = "PRELABEL_COMMON_INPUT"
    common_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_source_identities: dict[str, dict[str, Any]]

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        material = self.model_dump(mode="json", exclude={"config_digest"})
        if self.config_digest != canonical_sha256(material):
            raise ValueError("E2 arm config digest mismatch")
        return self


class ReplayOccurrenceV01(BaseModel):
    """Label-free occurrence projection consumed by the matched replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    occurrence_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    channel_rank: int = Field(ge=1)
    legal: bool
    direct_lexical_match: bool
    synonym_lexical_match: bool
    matched_roles: list[str] = Field(default_factory=list)
    binding_status: BindingStatus = "NOT_EVALUATED"

    @model_validator(mode="after")
    def validate_roles(self) -> Self:
        if self.matched_roles != sorted(set(self.matched_roles)):
            raise ValueError("matched roles must be sorted and unique")
        return self


class ReplayActionV01(BaseModel):
    """One digest-bound official action whose role is derived from its slot.

    ``action_kind`` is not a caller-supplied role label.  The only proof slot
    is ``REQUIRED_PROOF_CLOSURE`` and its channel is constrained here and by
    the arm-specific plan validator below.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["dg25-replay-action-v0.2"] = "dg25-replay-action-v0.2"
    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    action_kind: ReplayActionKind
    channel_query_identity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    returned_occurrence_count: int = Field(ge=1)

    @property
    def action_role(self) -> ReplayActionRole:
        if self.action_kind == "REQUIRED_PROOF_CLOSURE":
            return "PROOF_CLOSURE"
        return "EVIDENCE_DISCOVERY"

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.action_kind == "BASELINE_DISCOVERY" and self.channel != "FTS_RAW":
            raise ValueError("DG25_BASELINE_ACTION_MUST_USE_FTS_RAW")
        if self.action_kind == "REQUIRED_PROOF_CLOSURE" and self.channel not in {
            "TEMPORAL_EVENT",
            "SOURCE_OBSERVED_RANGE_SCAN",
        }:
            raise ValueError("DG25_PROOF_ACTION_CHANNEL_INVALID")
        if self.action_kind == "OPTIONAL_DISCOVERY" and self.channel == "FTS_RAW":
            raise ValueError("DG25_OPTIONAL_ACTION_CANNOT_REPLACE_BASELINE")
        material = self.model_dump(mode="json", exclude={"action_digest"})
        if self.action_digest != canonical_sha256(material):
            raise ValueError("DG25_REPLAY_ACTION_DIGEST_MISMATCH")
        return self


class E1RequirementActionPlanV01(BaseModel):
    """Exact arm/query/requirement action vector frozen before labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["dg25-e1-requirement-action-plan-v0.1"] = (
        "dg25-e1-requirement-action-plan-v0.1"
    )
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    arm_id: str = Field(min_length=1)
    arm_config_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str = Field(min_length=1)
    query_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_id: str = Field(min_length=1)
    required_roles: list[str]
    proof_required: bool
    available_proof_channels: list[str]
    available_optional_channels: list[str]
    baseline_action: ReplayActionV01
    proof_action: ReplayActionV01 | None
    optional_action: ReplayActionV01 | None
    optional_action_disposition: OptionalActionDisposition
    active_action_digests: list[str] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_plan_identity(self) -> Self:
        if self.required_roles != sorted(set(self.required_roles)):
            raise ValueError("DG25_REQUIRED_ROLES_NOT_CANONICAL")
        for channels in (self.available_proof_channels, self.available_optional_channels):
            if len(channels) != len(set(channels)):
                raise ValueError("DG25_AVAILABLE_ACTION_CHANNELS_DUPLICATE")
        actions = self.active_actions
        if [item.action_digest for item in actions] != self.active_action_digests:
            raise ValueError("DG25_ACTIVE_ACTION_VECTOR_DIGEST_MISMATCH")
        if len({item.channel for item in actions}) != len(actions):
            raise ValueError("DG25_ACTIVE_ACTION_CHANNEL_DUPLICATE")
        if any(
            item.case_id != self.case_id or item.requirement_id != self.requirement_id
            for item in actions
        ):
            raise ValueError("DG25_ACTION_TARGET_IDENTITY_MISMATCH")
        material = self.model_dump(mode="json", exclude={"plan_digest"})
        if self.plan_digest != canonical_sha256(material):
            raise ValueError("DG25_E1_ACTION_PLAN_DIGEST_MISMATCH")
        return self

    @property
    def active_actions(self) -> list[ReplayActionV01]:
        return [
            self.baseline_action,
            *([self.proof_action] if self.proof_action is not None else []),
            *([self.optional_action] if self.optional_action is not None else []),
        ]


class SelectedOccurrenceV01(BaseModel):
    """One deduplicated final-K item with all discovery lineage retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    occurrence_id: str
    evidence_id: str
    source_turn_ref: str
    requirement_id: str
    binding_status: BindingStatus
    matched_roles: list[str]
    discovery_lineage: list[dict[str, Any]]
    selected_by_reservation: bool
    final_rank: int = Field(ge=1, le=8)


def build_e1_arm_config(**values: Any) -> E1ArmConfigV01:
    """Build a digest-bound arm config from an explicit component vector."""

    provisional = E1ArmConfigV01.model_construct(config_digest="0" * 64, **values)
    material = provisional.model_dump(mode="json", exclude={"config_digest"})
    return E1ArmConfigV01(config_digest=canonical_sha256(material), **material)


def build_e2_arm_config(**values: Any) -> E2ArmConfigV01:
    """Build a digest-bound temporal arm config."""

    provisional = E2ArmConfigV01.model_construct(config_digest="0" * 64, **values)
    material = provisional.model_dump(mode="json", exclude={"config_digest"})
    return E2ArmConfigV01(config_digest=canonical_sha256(material), **material)


def build_replay_action(**values: Any) -> ReplayActionV01:
    """Build one immutable action identity without accepting an action role."""

    provisional = ReplayActionV01.model_construct(action_digest="0" * 64, **values)
    material = provisional.model_dump(mode="json", exclude={"action_digest"})
    return ReplayActionV01(action_digest=canonical_sha256(material), **material)


def build_e1_requirement_action_plan(**values: Any) -> E1RequirementActionPlanV01:
    """Build one digest-bound arm/query/requirement action vector."""

    provisional = E1RequirementActionPlanV01.model_construct(
        plan_digest="0" * 64,
        **values,
    )
    material = provisional.model_dump(mode="json", exclude={"plan_digest"})
    return E1RequirementActionPlanV01(
        plan_digest=canonical_sha256(material),
        **material,
    )


def validate_e1_requirement_action_plan(
    *,
    plan: E1RequirementActionPlanV01,
    config: E1ArmConfigV01,
    expected_plan_digest: str,
) -> list[ReplayActionV01]:
    """Validate the exact vector and derive roles from frozen action kinds.

    The expected digest comes from the pre-label all-query action manifest.
    A caller therefore cannot omit proof, relabel discovery as proof, swap a
    channel, or introduce an optional action merely by recomputing a local
    model digest.
    """

    if plan.plan_digest != expected_plan_digest:
        raise ValueError("DG25_E1_ACTION_PLAN_NOT_FROZEN_MANIFEST_MEMBER")
    if plan.arm_id != config.arm_id or plan.arm_config_digest != config.config_digest:
        raise ValueError("DG25_E1_ACTION_PLAN_ARM_BINDING_MISMATCH")
    if plan.available_proof_channels != [
        channel
        for channel in config.proof_channel_priority
        if channel in plan.available_proof_channels
    ]:
        raise ValueError("DG25_PROOF_CHANNEL_PRIORITY_DRIFT")
    if plan.available_optional_channels != [
        channel
        for channel in config.optional_channel_priority
        if channel in plan.available_optional_channels
    ]:
        raise ValueError("DG25_OPTIONAL_CHANNEL_PRIORITY_DRIFT")

    expected_proof_channel = (
        plan.available_proof_channels[0]
        if plan.proof_required and config.unified_proof_first
        else None
    )
    if expected_proof_channel is None:
        if plan.proof_action is not None:
            raise ValueError("DG25_UNAUTHORIZED_PROOF_ACTION")
    else:
        if plan.proof_action is None:
            raise ValueError("DG25_REQUIRED_PROOF_ACTION_OMITTED")
        if (
            plan.proof_action.action_kind != "REQUIRED_PROOF_CLOSURE"
            or plan.proof_action.channel != expected_proof_channel
        ):
            raise ValueError("DG25_REQUIRED_PROOF_ACTION_MISLABELED_OR_WRONG_CHANNEL")

    occupied = {plan.baseline_action.channel}
    if plan.proof_action is not None:
        occupied.add(plan.proof_action.channel)
    eligible_optional = [
        channel for channel in plan.available_optional_channels if channel not in occupied
    ]
    remaining_budget = config.max_actions_per_plan - (
        1 + (plan.proof_action is not None)
    )
    if not config.optional_channel_union:
        expected_optional_channel = None
        expected_disposition = "OPTIONAL_CHANNEL_UNION_DISABLED"
    elif remaining_budget == 0 and eligible_optional:
        expected_optional_channel = None
        expected_disposition = "BUDGET_NOT_AUTHORIZED"
    elif eligible_optional:
        expected_optional_channel = eligible_optional[0]
        expected_disposition = "SELECTED"
    else:
        expected_optional_channel = None
        expected_disposition = "NO_EXECUTABLE_OPTIONAL_CHANNEL"
    if plan.optional_action_disposition != expected_disposition:
        raise ValueError("DG25_OPTIONAL_ACTION_DISPOSITION_MISMATCH")
    if expected_optional_channel is None:
        if plan.optional_action is not None:
            raise ValueError("DG25_UNAUTHORIZED_OPTIONAL_ACTION")
    else:
        if plan.optional_action is None:
            raise ValueError("DG25_FROZEN_OPTIONAL_ACTION_OMITTED")
        if (
            plan.optional_action.action_kind != "OPTIONAL_DISCOVERY"
            or plan.optional_action.channel != expected_optional_channel
        ):
            raise ValueError("DG25_OPTIONAL_ACTION_MISLABELED_OR_WRONG_CHANNEL")
    actions = plan.active_actions
    if len(actions) > config.max_actions_per_plan:
        raise ValueError("DG25_REPLAY_ACTION_BUDGET_EXCEEDED")
    if actions[0].action_kind != "BASELINE_DISCOVERY":
        raise ValueError("DG25_FROZEN_BASELINE_ACTION_MISSING")
    return actions


def select_label_free_occurrences(
    *,
    per_channel: Mapping[str, Sequence[ReplayOccurrenceV01]],
    action_plan: E1RequirementActionPlanV01,
    expected_action_plan_digest: str,
    config: E1ArmConfigV01,
) -> list[SelectedOccurrenceV01]:
    """Fuse an already-sealed pool and apply legal, lexical, and role controls.

    Channel-local rank is the only ranking signal crossing this boundary.
    Repeated evidence is hydrated once conceptually while all channel lineage
    remains attached to the selected item.
    """

    active_actions = validate_e1_requirement_action_plan(
        plan=action_plan,
        config=config,
        expected_plan_digest=expected_action_plan_digest,
    )
    action_ids = [item.action_digest for item in active_actions]
    active_channels = [item.channel for item in active_actions]
    if len(action_ids) != len(set(action_ids)):
        raise ValueError("DUPLICATE_REPLAY_ACTION")
    if len(active_channels) != len(set(active_channels)):
        raise ValueError("DUPLICATE_REPLAY_CHANNEL")
    if set(active_channels) != set(per_channel):
        raise ValueError("DG25_REPLAY_CHANNEL_SET_NOT_EXACT_ACTION_VECTOR")

    channel_order = {channel: index for index, channel in enumerate(active_channels)}
    eligible: list[ReplayOccurrenceV01] = []
    for channel in active_channels:
        previous_rank = 0
        for item in per_channel[channel]:
            if item.channel != channel:
                raise ValueError("REPLAY_CHANNEL_LINEAGE_MISMATCH")
            if item.requirement_id != action_plan.requirement_id:
                raise ValueError("REPLAY_REQUIREMENT_LINEAGE_MISMATCH")
            if item.channel_rank <= previous_rank:
                raise ValueError("CHANNEL_LOCAL_RANK_NOT_STRICTLY_INCREASING")
            previous_rank = item.channel_rank
            if not item.legal:
                continue
            lexical_match = item.direct_lexical_match or (
                config.synonym_normalization and item.synonym_lexical_match
            )
            if config.lexical_mode == "LEGACY_HARD_FILTER" and not lexical_match:
                continue
            eligible.append(item)

    # Rank-based round robin: compare rank positions, never incomparable raw scores.
    eligible.sort(
        key=lambda item: (
            item.channel_rank,
            0
            if config.lexical_mode == "LEGACY_HARD_FILTER"
            or item.direct_lexical_match
            or (config.synonym_normalization and item.synonym_lexical_match)
            else 1,
            channel_order[item.channel],
            item.evidence_id,
            item.occurrence_id,
        )
    )
    by_evidence: dict[str, dict[str, Any]] = {}
    ordered_evidence: list[str] = []
    for item in eligible:
        state = by_evidence.get(item.evidence_id)
        lineage = {
            "channel": item.channel,
            "channel_rank": item.channel_rank,
            "occurrence_id": item.occurrence_id,
        }
        if state is None:
            state = {"item": item, "lineage": [lineage]}
            by_evidence[item.evidence_id] = state
            ordered_evidence.append(item.evidence_id)
        else:
            existing = state["lineage"]
            if not isinstance(existing, list):
                raise TypeError("internal lineage list required")
            existing.append(lineage)

    selected_ids: list[str] = []
    reserved: set[str] = set()
    if config.role_reservation:
        for role in action_plan.required_roles:
            match = next(
                (
                    evidence_id
                    for evidence_id in ordered_evidence
                    if role in _state_item(by_evidence[evidence_id]).matched_roles
                    and evidence_id not in selected_ids
                ),
                None,
            )
            if match is not None:
                selected_ids.append(match)
                reserved.add(match)
            if len(selected_ids) == config.final_k:
                break
    for evidence_id in ordered_evidence:
        if len(selected_ids) == config.final_k:
            break
        if evidence_id not in selected_ids:
            selected_ids.append(evidence_id)

    result: list[SelectedOccurrenceV01] = []
    for final_rank, evidence_id in enumerate(selected_ids, start=1):
        state = by_evidence[evidence_id]
        item = _state_item(state)
        raw_lineage = state["lineage"]
        if not isinstance(raw_lineage, list):
            raise TypeError("internal lineage list required")
        selected_lineage: list[dict[str, Any]] = sorted(
            [dict(value) for value in raw_lineage if isinstance(value, Mapping)],
            key=lambda value: (
                channel_order[str(value["channel"])],
                int(value["channel_rank"]),
                str(value["occurrence_id"]),
            ),
        )
        result.append(
            SelectedOccurrenceV01(
                occurrence_id=item.occurrence_id,
                evidence_id=item.evidence_id,
                source_turn_ref=item.source_turn_ref,
                requirement_id=item.requirement_id,
                binding_status=item.binding_status,
                matched_roles=item.matched_roles,
                discovery_lineage=selected_lineage,
                selected_by_reservation=evidence_id in reserved,
                final_rank=final_rank,
            )
        )
    return result


def component_difference(
    left: E1ArmConfigV01,
    right: E1ArmConfigV01,
) -> list[str]:
    """Return treatment fields that differ, excluding identity/lineage metadata."""

    excluded = {
        "schema_version",
        "config_digest",
        "arm_id",
        "ordered_predecessor",
        "matched_full_policy_control",
        "removed_component",
    }
    left_values = left.model_dump(mode="json")
    right_values = right.model_dump(mode="json")
    return sorted(
        key
        for key in left_values
        if key not in excluded and left_values[key] != right_values[key]
    )


def temporal_component_difference(
    left: E2ArmConfigV01,
    right: E2ArmConfigV01,
) -> list[str]:
    excluded = {
        "schema_version",
        "config_digest",
        "arm_id",
        "ordered_predecessor",
    }
    left_values = left.model_dump(mode="json")
    right_values = right.model_dump(mode="json")
    return sorted(
        key
        for key in left_values
        if key not in excluded and left_values[key] != right_values[key]
    )


def _state_item(state: Mapping[str, Any]) -> ReplayOccurrenceV01:
    value = state.get("item")
    if not isinstance(value, ReplayOccurrenceV01):
        raise TypeError("internal replay occurrence required")
    return value


__all__ = [
    "E1ArmConfigV01",
    "E1RequirementActionPlanV01",
    "E2ArmConfigV01",
    "ReplayActionV01",
    "ReplayOccurrenceV01",
    "SelectedOccurrenceV01",
    "build_e1_arm_config",
    "build_e1_requirement_action_plan",
    "build_e2_arm_config",
    "build_replay_action",
    "component_difference",
    "select_label_free_occurrences",
    "temporal_component_difference",
    "validate_e1_requirement_action_plan",
]
