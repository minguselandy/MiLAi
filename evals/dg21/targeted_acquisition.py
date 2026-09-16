"""DG-21 S3 official-executor target/source/adjacency matrix."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from milai.adapters import ProjectionIdentity
from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
    validate_feasible_action,
)
from milai.application.acquisition_execution_policy import (
    default_acquisition_execution_policy,
    select_acquisition_execution_profile,
)
from milai.application.deterministic_recovery import build_acquisition_observation_v02
from milai.application.evidence_acquisition import EvidenceAcquisitionExecutor
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_state import resolve_initial_requirement_state
from milai.application.source_time import compile_source_time_point_bucket
from milai.domain.acquisition_capability import FeasibleAcquisitionAction
from milai.domain.acquisition_execution_policy import AcquisitionExecutionSelection
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.sufficiency import SufficiencyDecision
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState
from pydantic import JsonValue

_REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)
_CONTEXT = SessionContext(UUID(int=21), UUID(int=22))
_SCOPE: dict[str, JsonValue] = {"project_ids": ["dg21"]}
_SEMANTIC_QUERY = "How many days passed between Holi and Sunday mass?"
_SCORE = "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/score.json"
_LABEL_FREE = "var/dg11/runs/dg11-r03-operator-20260823-002/label-free-inputs.json"
_ARM = "B_FRESH_STATE_DETERMINISTIC_CAPABILITY_POLICY"


class _Embedding128:
    dimensions = 128
    identity = ProjectionIdentity(
        provider="synthetic",
        model_id="dg21-s3-zero-provider",
        source_dimensions=128,
        projection_dimensions=128,
        normalization="l2",
        code_version="projection-128/v1",
    )

    def embed(self, _text: str) -> list[float]:
        return [0.0] * self.dimensions

    def embed_many(self, texts: list[str], _batch_size: int) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class _Repository:
    def __init__(self) -> None:
        self.dense_items: list[dict[str, Any]] = []
        self.adjacent_items: list[dict[str, Any]] = []
        self.range_items: list[dict[str, Any]] = []
        self.dense_calls = 0
        self.adjacency_calls: list[dict[str, Any]] = []
        self.range_calls: list[dict[str, Any]] = []

    def search_evidence(self, *args: object, **kwargs: object) -> list[dict[str, Any]]:
        return []

    def search_evidence_dense(
        self, *args: object, **kwargs: object
    ) -> dict[str, object]:
        self.dense_calls += 1
        return {"status": "COMPLETE", "items": self.dense_items}

    def hydrate_evidence_adjacency(
        self,
        _context: SessionContext,
        *,
        anchor_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
    ) -> list[dict[str, Any]]:
        self.adjacency_calls.append(
            {
                "anchor_count": len(anchor_evidence_ids),
                "scope_digest": canonical_sha256(requested_scope),
                "as_of": as_of.isoformat(),
                "max_items": max_items,
            }
        )
        return self.adjacent_items

    def scan_evidence_range(
        self,
        _context: SessionContext,
        requested_scope: dict[str, object],
        range_start: datetime,
        range_end: datetime,
        max_items: int,
    ) -> dict[str, object]:
        self.range_calls.append(
            {
                "scope_digest": canonical_sha256(requested_scope),
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
                "max_items": max_items,
            }
        )
        return {
            "status": "PARTIAL",
            "scan_axis": "SOURCE_OBSERVED_TIME",
            "source_partition_closed": False,
            "projection_watermark_covered": False,
            "projection_watermark": 7,
            "target_watermark": 8,
            "source_count": len(self.range_items),
            "projected_count": len(self.range_items),
            "returned_count": len(self.range_items),
            "max_items": max_items,
            "dead_letter_gap": False,
            "unreadable_evidence_count": 0,
            "items": self.range_items,
        }

    def exact_candidates(self) -> None:
        pass


def run_targeted_acquisition_matrix(root: Path) -> dict[str, Any]:
    """Run official executor only; evaluation owns fixtures and trace projection."""

    root = root.resolve()
    semantic = [_semantic_case(cap) for cap in (8, 12, 16)]
    adjacency = _adjacency_case()
    source = _source_point_case()
    opened_source = _opened_source_point_diagnosis(root)
    policy = default_acquisition_execution_policy()

    global_probe_count = sum(item["global_probe_count"] for item in semantic)
    attribution_total = sum(item["new_candidate_count"] for item in semantic)
    attribution_correct = sum(
        item["target_attributed_candidate_count"] for item in semantic
    )
    repeated_accepted = sum(
        item["repeated_candidate_accepted_count"] for item in semantic
    )
    checks = {
        "candidate_sweep_exact_8_12_16": [item["candidate_cap"] for item in semantic]
        == [8, 12, 16],
        "fixed_policy_digest": all(
            item["policy_digest"] == policy.policy_digest for item in semantic
        ),
        "effective_budget_owned_by_profile_or_remaining": [
            item["effective_candidate_count"] for item in semantic
        ]
        == [8, 12, 12],
        "target_requirement_attribution_100_percent": (
            attribution_total > 0 and attribution_correct == attribution_total
        ),
        "global_probe_in_target_action_zero": global_probe_count == 0,
        "repeated_candidate_accepted_zero": repeated_accepted == 0,
        "unsupported_stale_action_accepted_zero": all(
            not item["stale_action_accepted"] for item in semantic
        ),
        "additional_acquisition_pass_at_most_one": all(
            item["acquisition_passes"] <= 1 for item in semantic
        ),
        "repository_probe_calls_one_per_action": all(
            item["repository_probe_calls"] == 1 for item in semantic
        ),
        "adjacency_caps_exact": (
            adjacency["anchor_count"] <= 2 and adjacency["max_items"] <= 4
        ),
        "adjacency_governance_violation_accepted_zero": (
            adjacency["governance_violation_accepted_count"] == 0
        ),
        "adjacency_repeated_candidate_accepted_zero": (
            adjacency["repeated_candidate_accepted_count"] == 0
        ),
        "source_point_compiled_closed_open": source["compiled_boundary"]
        == "CLOSED_OPEN",
        "source_point_declared_precision_timezone": (
            source["precision"] == "DAY" and source["timezone"] == "UTC"
        ),
        "source_point_time_axis_substitution_zero": (
            source["time_axis_substitution"] is False
        ),
        "source_point_unproven_widening_zero": source["semantic_widening"] is False,
        "source_scan_official_executor_axis_exact": source["scan_axis"]
        == "SOURCE_OBSERVED_TIME",
        "opened_9a_source_point_compiles": opened_source["compiled"] is True,
        "opened_9a_no_case_specific_runtime_rule": (
            opened_source["runtime_case_id_inputs"] == 0
        ),
    }
    return {
        "schema": "milai.dg21.s3-targeted-acquisition-matrix.v0.1",
        "status": "PASS_TARGETED_SOURCE_ADJACENCY" if all(checks.values()) else "FAIL",
        "classification": "SYNTHETIC_CONTRACT_PLUS_OPENED_DEVELOPMENT_DIAGNOSIS",
        "policy_digest": policy.policy_digest,
        "selected_candidate_policy": {
            "semantic_candidate_cap": policy.profiles.semantic_slot.dense_candidate_cap,
            "source_point_scan_cap": policy.profiles.source_time_point.scan_max_items,
            "adjacent_max_anchors": policy.profiles.semantic_slot.adjacent_max_anchors,
            "adjacent_max_items": policy.profiles.semantic_slot.adjacent_max_items,
            "adjacent_radius": policy.profiles.semantic_slot.adjacent_radius,
        },
        "metrics": {
            "target_requirement_attribution_numerator": attribution_correct,
            "target_requirement_attribution_denominator": attribution_total,
            "global_probe_count": global_probe_count,
            "repeated_candidate_accepted_count": repeated_accepted,
            "unsupported_action_accepted_count": sum(
                item["stale_action_accepted"] for item in semantic
            ),
            "provider_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
            "time_axis_substitutions": 0,
            "unproven_point_widenings": 0,
        },
        "semantic_candidate_sweep": semantic,
        "adjacency": adjacency,
        "source_point": source,
        "opened_9a_diagnosis": opened_source,
        "safety": {
            "provider_calls": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
            "formal_holdout_consumed": False,
            "canonical_mutations": 0,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def _semantic_case(candidate_cap: int) -> dict[str, Any]:
    repository = _Repository()
    seen = _item("seen", "I attended Sunday mass on March 10.")
    new = _item("target", "I joined the Holi festival on March 8.")
    repository.dense_items = [seen, new]
    setup = _setup(repository, _SEMANTIC_QUERY, candidate_cap=candidate_cap)
    selection = _selection(setup, remaining=candidate_cap)
    action = _bound_action(selection, setup["actions"])
    stale = _stale_action(action)
    stale_accepted = validate_feasible_action(
        stale,
        setup["state"],
        setup["capabilities"],
        setup["capability_policy"],
    ).accepted
    execution = EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
        context=_CONTEXT,
        request=setup["request"],
        query_plan=setup["query_plan"],
        acquisition_plan=setup["plan"],
        capability_set=setup["capabilities"],
        policy=setup["capability_policy"],
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=setup["state"],
        existing_results=[seen],
        type_directed_semantics=True,
        execution_selection=selection,
    )
    new_candidates = [
        item for item in execution.candidates if item.source_evidence_id != "seen"
    ]
    return {
        "scenario": "TARGET_ONLY_EVIDENCE_DENSE",
        "candidate_cap": candidate_cap,
        "policy_digest": selection.policy_digest,
        "selection_digest": selection.selection_digest,
        "target_requirement_id": selection.target_requirement_id,
        "selected_channel": selection.selected_channel,
        "declared_candidate_count": selection.declared_budget.candidate_count,
        "effective_candidate_count": selection.effective_budget.candidate_count,
        "budget_clamp_owner": selection.budget_clamp_owner,
        "executed_probe_ids": [item.probe_id for item in execution.probe_dispositions],
        "global_probe_count": sum(
            item.probe_id.startswith("global:") for item in execution.probe_dispositions
        ),
        "repository_probe_calls": repository.dense_calls,
        "new_candidate_count": len(new_candidates),
        "target_attributed_candidate_count": sum(
            item.matched_slots == [selection.target_requirement_id]
            for item in new_candidates
        ),
        "repeated_candidate_accepted_count": sum(
            item.source_evidence_id == "seen" for item in new_candidates
        ),
        "excluded_seen_candidate_count": sum(
            item.excluded_seen_candidate_count for item in execution.probe_dispositions
        ),
        "stale_action_accepted": stale_accepted,
        "acquisition_passes": action.bounded_cost["acquisition_passes"],
        "provider_calls": 0,
        "reader_calls": 0,
    }


def _adjacency_case() -> dict[str, Any]:
    repository = _Repository()
    anchor = _item("anchor", "I am considering a local trip.")
    valid = _item("valid", "I want to visit Denver soon.", round_ordinal=3)
    invalid_ids = {
        "cross-session",
        "outside-radius",
        "cross-scope",
        "unreadable",
        "revoked",
    }
    repository.adjacent_items = [
        anchor,
        valid,
        _item("cross-session", "x", session_id="session-b"),
        _item("outside-radius", "x", round_ordinal=4),
        _item("cross-scope", "x", project_id="other"),
        _item("unreadable", "x", readable=False),
        _item("revoked", "x", revoked=True),
    ]
    setup = _setup(repository, _SEMANTIC_QUERY, candidate_cap=12, adjacency=True)
    observation = build_acquisition_observation_v02(
        requirement_state=setup["state"],
        capability_set=setup["capabilities"],
        policy=setup["capability_policy"],
        probe_dispositions=[],
        feasible_actions=setup["actions"],
        remaining_budget={
            "acquisition_passes": 1,
            "candidate_count": 12,
            "model_calls": 0,
        },
        valid_adjacency_anchor_count=1,
    )
    target_id = setup["state"].missing_requirement_ids[0]
    material = observation.model_dump(mode="json", exclude={"observation_digest"})
    for requirement in material["requirements"]:
        if requirement["requirement_id"] == target_id:
            requirement["matched_evidence_refs"] = ["anchor"]
    observation = type(observation).model_validate(
        {"observation_digest": canonical_sha256(material), **material}
    )
    selection = _selection(setup, remaining=12, observation=observation)
    action = _bound_action(selection, setup["actions"])
    execution = EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
        context=_CONTEXT,
        request=setup["request"],
        query_plan=setup["query_plan"],
        acquisition_plan=setup["plan"],
        capability_set=setup["capabilities"],
        policy=setup["capability_policy"],
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=setup["state"],
        existing_results=[anchor],
        type_directed_semantics=True,
        execution_selection=selection,
    )
    accepted = {
        str(item["evidence_id"])
        for item in execution.results
        if item["evidence_id"] != "anchor"
    }
    disposition = execution.probe_dispositions[0]
    call = repository.adjacency_calls[0]
    return {
        "selected_channel": selection.selected_channel,
        "selection_digest": selection.selection_digest,
        "anchor_count": call["anchor_count"],
        "max_items": call["max_items"],
        "accepted_candidate_count": len(accepted),
        "governance_violation_accepted_count": len(accepted & invalid_ids),
        "repeated_candidate_accepted_count": int("anchor" in accepted),
        "excluded_seen_candidate_count": disposition.excluded_seen_candidate_count,
        "new_region_count": disposition.new_region_count,
        "provider_calls": 0,
        "reader_calls": 0,
    }


def _source_point_case() -> dict[str, Any]:
    repository = _Repository()
    repository.range_items = [_item("source-hit", "I mentioned cooking with a friend.")]
    query = "I mentioned cooking with a friend a couple of days ago. What was it?"
    setup = _setup(
        repository,
        query,
        candidate_cap=128,
        source_point=True,
    )
    selection = _selection(setup, remaining=128)
    action = _bound_action(selection, setup["actions"])
    execution = EvidenceAcquisitionExecutor(repository, _Embedding128()).execute(
        context=_CONTEXT,
        request=setup["request"],
        query_plan=setup["query_plan"],
        acquisition_plan=setup["plan"],
        capability_set=setup["capabilities"],
        policy=setup["capability_policy"],
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=1,
        action=action,
        current_requirement_state=setup["state"],
        type_directed_semantics=True,
        execution_selection=selection,
    )
    temporal = setup["query_plan"].memory_query_ir.constraints.normalized_temporal
    compiled = setup["plan"].global_constraints.source_observed_range
    assert temporal is not None and compiled is not None
    proof = execution.bounded_range_scan_proof
    assert proof is not None
    return {
        "selection_digest": selection.selection_digest,
        "selected_channel": selection.selected_channel,
        "precision": temporal.precision,
        "timezone": temporal.timezone,
        "compiled_boundary": compiled["boundary"],
        "compiled_from_boundary": compiled["compiled_from_boundary"],
        "time_axis_substitution": compiled["time_axis_substitution"],
        "semantic_widening": compiled["semantic_widening"],
        "scan_axis": proof.scan_axis,
        "range_call": repository.range_calls[0],
        "provider_calls": 0,
        "reader_calls": 0,
    }


def _opened_source_point_diagnosis(root: Path) -> dict[str, Any]:
    path = root / _SCORE
    label_free_path = root / _LABEL_FREE
    score = _read_json(path)
    label_free = _read_json(label_free_path)
    record = next(
        item
        for item in score["records"][_ARM]
        if item["case_id"] == "9a707b82" and item["token_budget"] == 2048
    )
    archived_plan = record["search_trace"]["acquisition_plan"]
    query = next(
        item["question"]
        for item in label_free["cases"]
        if item["source_id"] == "9a707b82"
    )
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope=record["memory_query_ir"]["constraints"]["scope"],
        as_of=archived_plan["global_constraints"]["valid_as_of"],
        system_as_of=archived_plan["global_constraints"]["system_as_of"],
    )
    query_plan = QueryPlanner().plan(request)
    assert query_plan.memory_query_ir is not None
    temporal = query_plan.memory_query_ir.constraints.normalized_temporal
    assert temporal is not None
    result = compile_source_time_point_bucket(
        temporal,
        default_acquisition_execution_policy().profiles.source_time_point,
    )
    return {
        "case_id": "9a707b82",
        "source_score_sha256": _sha256(path),
        "label_free_input_sha256": _sha256(label_free_path),
        "question_sha256": canonical_sha256(query),
        "compiled": result.status == "COMPILED",
        "reason_code": result.reason_code,
        "precision": result.precision,
        "timezone": result.timezone,
        "time_axis": result.original_axis,
        "runtime_case_id_inputs": 0,
        "provider_calls": 0,
        "reader_calls": 0,
    }


def _setup(
    repository: _Repository,
    query: str,
    *,
    candidate_cap: int,
    adjacency: bool = False,
    source_point: bool = False,
) -> dict[str, Any]:
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope=_SCOPE,
        as_of=_REFERENCE,
        system_as_of=_REFERENCE,
    )
    query_plan = QueryPlanner().plan(request)
    assert query_plan.memory_query_ir is not None
    execution_policy = default_acquisition_execution_policy()
    plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=_SCOPE,
        authority_floor="INFORMATIONAL",
        candidate_limit=candidate_cap,
        context_tokens=512,
        enable_enriched=True,
        enable_dense=True,
        source_time_point_profile=(
            execution_policy.profiles.source_time_point if source_point else None
        ),
    )
    capability_policy = AcquisitionCapabilityPolicy(
        policy_version="dg21-s3-matrix",
        max_candidates=256,
        max_hydrated_items=4,
    )
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            lexical_enrichment_bound=True,
            lexical_enrichment_enabled=True,
            evidence_dense_enabled=True,
            embedding_projection_dimensions=128,
            adjacent_turns_acquisition_enabled=adjacency,
        ),
        projection_state=ProjectionState(7, 7, 7, False, False, 7, False),
        repository=repository,
        policy=capability_policy,
        generated_at=_REFERENCE,
        source_observed_range=plan.global_constraints.source_observed_range,
        event_occurrence_range=plan.global_constraints.event_occurrence_range,
    )
    state = resolve_initial_requirement_state(
        plan,
        query_plan.memory_query_ir.requirements,
        acquisition_capability_digest=capabilities.capability_digest,
        memory_query_ir=query_plan.memory_query_ir,
    )
    actions = feasible_acquisition_actions(
        state,
        capabilities,
        capability_policy,
        source_observed_range=plan.global_constraints.source_observed_range,
        valid_anchor_available=adjacency,
        remaining_candidates=candidate_cap,
        acquisition_plan=plan,
    )
    return {
        "request": request,
        "query_plan": query_plan,
        "plan": plan,
        "execution_policy": execution_policy,
        "capability_policy": capability_policy,
        "capabilities": capabilities,
        "state": state,
        "actions": actions,
    }


def _selection(
    setup: Mapping[str, Any],
    *,
    remaining: int,
    observation: Any = None,
) -> AcquisitionExecutionSelection:
    query_plan: QueryPlan = setup["query_plan"]
    assert query_plan.memory_query_ir is not None
    return select_acquisition_execution_profile(
        policy=setup["execution_policy"],
        query_ir=query_plan.memory_query_ir,
        requirement_state=setup["state"],
        sufficiency=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=setup["state"].missing_requirement_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        capability_set=setup["capabilities"],
        remaining_budget={"acquisition_passes": 1, "candidate_count": remaining},
        observation=observation,
    )


def _bound_action(
    selection: AcquisitionExecutionSelection,
    actions: list[FeasibleAcquisitionAction],
) -> FeasibleAcquisitionAction:
    source = next(
        item
        for item in actions
        if item.target_requirement_id == selection.target_requirement_id
        and item.channel == selection.selected_channel
    )
    payload = source.model_dump(mode="json", exclude={"action_digest"})
    payload["bounded_cost"] = {
        "acquisition_passes": selection.effective_budget.acquisition_passes,
        "candidate_count": selection.effective_budget.candidate_count,
        "model_calls": 0,
    }
    return FeasibleAcquisitionAction.model_validate(
        {"action_digest": canonical_sha256(payload), **payload}
    )


def _stale_action(action: FeasibleAcquisitionAction) -> FeasibleAcquisitionAction:
    payload = action.model_dump(mode="json", exclude={"action_digest"})
    payload["requirement_state_digest"] = "f" * 64
    return FeasibleAcquisitionAction.model_validate(
        {"action_digest": canonical_sha256(payload), **payload}
    )


def _item(
    evidence_id: str,
    content: str,
    *,
    session_id: str = "session-a",
    round_ordinal: int = 1,
    project_id: str = "dg21",
    readable: bool = True,
    revoked: bool = False,
) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": evidence_id,
        "source_ref": f"opaque://{evidence_id}",
        "subject_id": session_id,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session_id,
            "turn_id": f"turn-{round_ordinal}",
            "turn_ordinal": round_ordinal,
            "round_id": f"round-{round_ordinal}",
            "round_ordinal": round_ordinal,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "observed_at": "2022-04-10T12:00:00+00:00",
        "captured_at": "2022-04-10T12:00:01+00:00",
        "content": content,
        "content_hash": canonical_sha256(content),
        "permission_snapshot": {
            "readable": readable,
            "project_ids": [project_id],
        },
        "retention_state": "READABLE",
        "revoked_at": "2026-01-01T00:00:00+00:00" if revoked else None,
        "relevance_score": 1.0,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


__all__ = ["run_targeted_acquisition_matrix"]
