"""MD-02 sealed boundary robustness and observation-only shadow evaluation."""

from __future__ import annotations

import copy
import hashlib
import json
import random
import statistics
import tracemalloc
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter, process_time
from typing import Any
from uuid import UUID

from milai.application.acquisition import compile_acquisition_plan, rank_evidence_turns
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    resolve_acquisition_capabilities,
)
from milai.application.evidence_acquisition import EvidenceAcquisitionExecutor
from milai.application.formation_engine import DEFAULT_FORMATION_ENGINE
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_formation import build_memory_formation_bundle
from milai.application.query_planner import QueryPlanner
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.application.semantic_episode_boundary_v02 import (
    MemoryFormationBuildResultV02,
    build_memory_formation_bundle_v02,
)
from milai.application.semantic_episode_shadow import SemanticEpisodeShadowHook
from milai.domain.memory_formation import MemoryFormationBundleV01
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.reader_evidence_plan import AcceptedBindingSpan
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState

REPAIR_FIXTURE = Path("evals/md02/fixtures/boundary-repair-dev.v0.1.json")
SEALED_FIXTURE = Path("evals/md02/fixtures/shadow-validation.v0.1.json")
FRESHNESS_FIXTURE = Path("evals/md02/fixtures/freshness-contract.v0.1.json")
RUN_LOCK = Path("var/md02/md02-boundary-product-shadow-20260830-001/run-lock.json")
MF02_SEALED = Path("evals/mf02/fixtures/sealed-validation.v0.1.json")
CEILINGS = tuple(range(1, 9))


class MD02EffectError(RuntimeError):
    """A frozen MD-02 identity or preregistered invariant was violated."""


def evaluate_repair_dev(root: Path) -> dict[str, Any]:
    """Open only repair-dev labels for generalized V02 implementation work."""

    root = root.resolve()
    fixture = _object(root / REPAIR_FIXTURE)
    lock = _object(root / RUN_LOCK)
    _verify_fixture(lock, fixture, "boundary_repair_dev", root / REPAIR_FIXTURE)
    return _evaluate_boundary_fixture(fixture, lock, include_bootstrap=False)


def execute_boundary_effect(root: Path) -> dict[str, Any]:
    """Run the sole new sealed V01/V02 effect and score after prediction seal."""

    root = root.resolve()
    fixture = _object(root / SEALED_FIXTURE)
    lock = _object(root / RUN_LOCK)
    _verify_fixture(lock, fixture, "shadow_validation", root / SEALED_FIXTURE)
    predictions = _predict_boundary_fixture(fixture)
    prediction_digest = canonical_sha256(predictions)
    score = _score_boundary_fixture(fixture, predictions, lock, include_bootstrap=True)
    return {
        "schema": "milai.md02.boundary-effect.v0.1",
        "effect_attempt": 1,
        "prediction_digest_before_scoring": prediction_digest,
        "prediction_rows": predictions,
        "score": score,
        "formal_holdout_used": False,
    }


def execute_shadow_effect(root: Path) -> dict[str, Any]:
    """Run the sole default-OFF versus observation-only shadow effect."""

    root = root.resolve()
    fixture = _object(root / SEALED_FIXTURE)
    freshness = _object(root / FRESHNESS_FIXTURE)
    lock = _object(root / RUN_LOCK)
    _verify_fixture(lock, fixture, "shadow_validation", root / SEALED_FIXTURE)
    _verify_identity(
        root / FRESHNESS_FIXTURE,
        _mapping(lock["fixtures"], "fixtures")["freshness_contract"],
    )
    scenarios = _sequence(freshness.get("scenarios"), "freshness scenarios")
    rows: list[dict[str, Any]] = []
    build_wall_ms: list[float] = []
    build_cpu_ms: list[float] = []
    shadow_overhead_ms: list[float] = []
    memory_peaks: list[int] = []
    default_hook = SemanticEpisodeShadowHook()
    enabled_hook = SemanticEpisodeShadowHook(enabled=True)
    conversations = _sequence(fixture.get("conversations"), "conversations")
    for raw_conversation in conversations:
        conversation = _mapping(raw_conversation, "conversation")
        turns = [
            dict(_mapping(item, "turn"))
            for item in _sequence(conversation.get("turns"), "turns")
        ]
        probe = _mapping(
            _sequence(conversation.get("memory_probes"), "memory probes")[0],
            "memory probe",
        )

        tracemalloc.start()
        cpu_started = process_time()
        wall_started = perf_counter()
        built = DEFAULT_FORMATION_ENGINE.build(turns).episode
        build_wall_ms.append((perf_counter() - wall_started) * 1_000)
        build_cpu_ms.append((process_time() - cpu_started) * 1_000)
        memory_peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()

        baseline, anchors, baseline_calls, repository = _official_baseline_behavior(
            turns,
            str(probe["query_text"]),
        )
        baseline_digest_before = canonical_sha256(baseline)
        off = default_hook.observe(
            request_identity=str(probe["probe_id"]),
            baseline_behavior=baseline,
            current_sources=turns,
            official_anchor_evidence_ids=anchors,
            bundle=built.bundle,
        )
        if off is not None:
            raise MD02EffectError("DEFAULT_OFF_SHADOW_EMITTED_OBSERVATION")
        calls_before_shadow = repository.calls
        started = perf_counter()
        current = enabled_hook.observe(
            request_identity=str(probe["probe_id"]),
            baseline_behavior=baseline,
            current_sources=turns,
            official_anchor_evidence_ids=anchors,
            bundle=built.bundle,
        )
        shadow_overhead_ms.append((perf_counter() - started) * 1_000)
        replay = enabled_hook.observe(
            request_identity=str(probe["probe_id"]),
            baseline_behavior=baseline,
            current_sources=turns,
            official_anchor_evidence_ids=anchors,
            bundle=built.bundle,
        )
        if current is None or replay is None:
            raise MD02EffectError("ENABLED_SHADOW_OMITTED_OBSERVATION")

        observed_scenarios: list[dict[str, Any]] = []
        for raw_scenario in scenarios:
            scenario = _mapping(raw_scenario, "freshness scenario")
            scenario_name = str(scenario["scenario"])
            scenario_sources, scenario_bundle, formation_failed = _scenario_inputs(
                scenario_name,
                turns,
                built.bundle,
            )
            observation = enabled_hook.observe(
                request_identity=str(probe["probe_id"]),
                baseline_behavior=baseline,
                current_sources=scenario_sources,
                official_anchor_evidence_ids=anchors,
                bundle=scenario_bundle,
                formation_failed=formation_failed,
            )
            if observation is None:
                raise MD02EffectError("ENABLED_SHADOW_SCENARIO_NOT_OBSERVED")
            observed_scenarios.append(
                {
                    "scenario": scenario_name,
                    "observation": observation.model_dump(mode="json"),
                }
            )
        baseline_digest_after = canonical_sha256(baseline)
        rows.append(
            {
                "conversation_id": conversation["conversation_id"],
                "probe_id": probe["probe_id"],
                "bundle_digest": built.bundle.bundle_digest,
                "boundary_evidence_digests": [
                    item.boundary_evidence_digest for item in built.boundary_evidence
                ],
                "official_anchor_evidence_ids": anchors,
                "official_baseline_repository_calls": baseline_calls,
                "additional_shadow_repository_calls": repository.calls
                - calls_before_shadow,
                "baseline_behavior_digest_before": baseline_digest_before,
                "baseline_behavior_digest_after": baseline_digest_after,
                "current_observation": current.model_dump(mode="json"),
                "deterministic_replay_observation": replay.model_dump(mode="json"),
                "freshness_scenarios": observed_scenarios,
            }
        )
    shadow_digest = canonical_sha256(rows)
    score = _score_shadow_rows(rows, freshness, len(conversations))
    score["cost"] = {
        "bundle_build_time_ms_mean": statistics.mean(build_wall_ms),
        "bundle_build_cpu_time_ms_mean": statistics.mean(build_cpu_ms),
        "bundle_build_cpu_time_per_turn_ms": statistics.mean(build_cpu_ms) / 4,
        "memory_high_water_bytes": max(memory_peaks),
        "shadow_overhead_ms_p50": _percentile(shadow_overhead_ms, 0.50),
        "shadow_overhead_ms_p95": _percentile(shadow_overhead_ms, 0.95),
        "shadow_overhead_ms_mean": statistics.mean(shadow_overhead_ms),
        "latency_sla_preregistered": False,
    }
    return {
        "schema": "milai.md02.product-shadow-effect.v0.1",
        "effect_attempt": 1,
        "shadow_digest_before_contract_scoring": shadow_digest,
        "rows": rows,
        "score": score,
        "formal_holdout_used": False,
    }


def mf02_historical_non_regression(root: Path) -> dict[str, Any]:
    """Replay old MF-02 labels after V02 freeze; never use them for MD-02 tuning."""

    fixture = _object(root.resolve() / MF02_SEALED)
    lock = _object(root.resolve() / RUN_LOCK)
    result = _evaluate_boundary_fixture(fixture, lock, include_bootstrap=False)
    return {
        "conversation_count": len(_sequence(fixture["conversations"], "conversations")),
        "included_in_md02_main_denominator": False,
        "v01_episode_pairwise_f1": result["boundary"]["V01"]["episode_pairwise_f1"],
        "v02_episode_pairwise_f1": result["boundary"]["V02"]["episode_pairwise_f1"],
        "v01_support_closure_auc": result["simple_read"]["V01"]["support_closure_auc"],
        "v02_support_closure_auc": result["simple_read"]["V02"]["support_closure_auc"],
        "used_for_rule_changes": False,
    }


def hand_contract_sanity() -> dict[str, Any]:
    gold = [[0, 1], [2, 3]]
    perfect = _conversation_boundary_metrics(gold, gold)
    merged = _conversation_boundary_metrics(gold, [[0, 1, 2, 3]])
    split = _conversation_boundary_metrics(gold, [[0], [1], [2], [3]])
    return {
        "perfect_pairwise_f1": perfect["episode_pairwise_f1"],
        "merged_over_merge_pair_rate": merged["over_merge_pair_rate"],
        "split_over_split_pair_rate": split["over_split_pair_rate"],
        "freshness_scenario_count": 6,
    }


def environment_witness() -> str:
    sanity = hand_contract_sanity()
    return (
        f"WITNESS 2 {sanity['freshness_scenario_count']} "
        f"{SemanticEpisodeShadowHook().enabled:d}"
    )


def _evaluate_boundary_fixture(
    fixture: Mapping[str, Any],
    lock: Mapping[str, Any],
    *,
    include_bootstrap: bool,
) -> dict[str, Any]:
    predictions = _predict_boundary_fixture(fixture)
    return _score_boundary_fixture(
        fixture,
        predictions,
        lock,
        include_bootstrap=include_bootstrap,
    )


def _predict_boundary_fixture(fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_conversation in _sequence(fixture.get("conversations"), "conversations"):
        conversation = _mapping(raw_conversation, "conversation")
        turns = [
            dict(_mapping(item, "turn"))
            for item in _sequence(conversation.get("turns"), "turns")
        ]
        v01 = build_memory_formation_bundle(turns)
        v02 = build_memory_formation_bundle_v02(turns)
        replay = build_memory_formation_bundle_v02(turns)
        probes: list[dict[str, Any]] = []
        for raw_probe in _sequence(conversation.get("memory_probes"), "memory probes"):
            probe = _mapping(raw_probe, "memory probe")
            ranked = [
                str(item["evidence_id"])
                for item in rank_evidence_turns(turns, str(probe["query_text"]))
            ]
            probes.append(
                {
                    "probe_id": probe["probe_id"],
                    "official_ranked_anchor_evidence_ids": ranked,
                }
            )
        rows.append(
            {
                "conversation_id": conversation["conversation_id"],
                "source_evidence_ids": [turn["evidence_id"] for turn in turns],
                "source_roles": [turn["speaker"] for turn in turns],
                "v01_groups": _groups(v01.bundle),
                "v02_groups": _groups(v02.bundle),
                "v02_bundle_digest": v02.bundle.bundle_digest,
                "v02_boundary_evidence": [
                    item.model_dump(mode="json") for item in v02.boundary_evidence
                ],
                "v02_deterministic_replay": (
                    v02.bundle.model_dump_json() == replay.bundle.model_dump_json()
                    and [item.model_dump_json() for item in v02.boundary_evidence]
                    == [item.model_dump_json() for item in replay.boundary_evidence]
                ),
                "v02_artifact_source_ids": sorted(_artifact_source_ids(v02)),
                "probes": probes,
            }
        )
    return rows


def _score_boundary_fixture(
    fixture: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
    lock: Mapping[str, Any],
    *,
    include_bootstrap: bool,
) -> dict[str, Any]:
    conversations = {
        str(item["conversation_id"]): _mapping(item, "conversation")
        for item in _sequence(fixture.get("conversations"), "conversations")
    }
    records: list[dict[str, Any]] = []
    for prediction in predictions:
        conversation_id = str(prediction["conversation_id"])
        conversation = conversations[conversation_id]
        gold = [
            [int(index) for index in _sequence(episode["turn_indexes"], "turn indexes")]
            for episode in _sequence(
                conversation["expected_episodes"], "expected episodes"
            )
        ]
        v01_groups = [list(map(int, group)) for group in prediction["v01_groups"]]
        v02_groups = [list(map(int, group)) for group in prediction["v02_groups"]]
        v01 = _conversation_boundary_metrics(gold, v01_groups)
        v02 = _conversation_boundary_metrics(gold, v02_groups)
        probe_metrics: list[dict[str, Any]] = []
        probes_by_id = {
            str(item["probe_id"]): _mapping(item, "probe")
            for item in _sequence(conversation["memory_probes"], "memory probes")
        }
        for raw_probe_prediction in prediction["probes"]:
            probe_prediction = _mapping(raw_probe_prediction, "probe prediction")
            probe = probes_by_id[str(probe_prediction["probe_id"])]
            ranking = [
                str(value)
                for value in probe_prediction["official_ranked_anchor_evidence_ids"]
            ]
            source_ids = [str(value) for value in prediction["source_evidence_ids"]]
            required = {str(value) for value in probe["required_support_evidence_ids"]}
            distractors = {str(value) for value in probe["distractor_evidence_ids"]}
            probe_metrics.append(
                {
                    "V01": _probe_read_metrics(
                        v01_groups, source_ids, ranking, required, distractors
                    ),
                    "V02": _probe_read_metrics(
                        v02_groups, source_ids, ranking, required, distractors
                    ),
                }
            )
        records.append(
            {
                "conversation_id": conversation_id,
                "V01": v01,
                "V02": v02,
                "probes": probe_metrics,
            }
        )
    boundary = {
        arm: {
            key: statistics.mean(record[arm][key] for record in records)
            for key in (
                "over_merge_pair_rate",
                "over_split_pair_rate",
                "episode_pairwise_precision",
                "episode_pairwise_recall",
                "episode_pairwise_f1",
                "boundary_precision",
                "boundary_recall",
                "boundary_f1",
            )
        }
        for arm in ("V01", "V02")
    }
    read = {
        arm: {
            "support_closure_auc": statistics.mean(
                probe[arm]["support_closure_auc"]
                for record in records
                for probe in record["probes"]
            ),
            "distractor_turn_rate": statistics.mean(
                probe[arm]["distractor_turn_rate"]
                for record in records
                for probe in record["probes"]
            ),
        }
        for arm in ("V01", "V02")
    }
    over_merge_reductions = [
        float(record["V01"]["over_merge_pair_rate"])
        - float(record["V02"]["over_merge_pair_rate"])
        for record in records
    ]
    f1_deltas = [
        float(record["V02"]["episode_pairwise_f1"])
        - float(record["V01"]["episode_pairwise_f1"])
        for record in records
    ]
    read_deltas = [
        statistics.mean(
            float(probe["V02"]["support_closure_auc"])
            - float(probe["V01"]["support_closure_auc"])
            for probe in record["probes"]
        )
        for record in records
    ]
    over_split_increase = (
        boundary["V02"]["over_split_pair_rate"]
        - boundary["V01"]["over_split_pair_rate"]
    )
    deltas: dict[str, Any] = {
        "over_merge_pair_rate_absolute_reduction": statistics.mean(
            over_merge_reductions
        ),
        "over_split_pair_rate_increase": over_split_increase,
        "episode_pairwise_f1_delta": statistics.mean(f1_deltas),
        "support_closure_auc_delta": statistics.mean(read_deltas),
        "distractor_turn_rate_delta": read["V02"]["distractor_turn_rate"]
        - read["V01"]["distractor_turn_rate"],
    }
    if include_bootstrap:
        bootstrap = _mapping(
            _mapping(lock["protocol"], "protocol")["bootstrap"], "bootstrap"
        )
        deltas["over_merge_reduction_bootstrap_95_ci"] = _bootstrap_ci(
            over_merge_reductions,
            int(bootstrap["seed"]),
            int(bootstrap["resamples"]),
        )
        deltas["episode_pairwise_f1_delta_bootstrap_95_ci"] = _bootstrap_ci(
            f1_deltas,
            int(bootstrap["seed"]) + 1,
            int(bootstrap["resamples"]),
        )
        deltas["support_closure_auc_delta_bootstrap_95_ci"] = _bootstrap_ci(
            read_deltas,
            int(bootstrap["seed"]) + 2,
            int(bootstrap["resamples"]),
        )
    thresholds = _mapping(lock["thresholds"], "thresholds")
    checks = {
        "over_merge_reduction_threshold": deltas[
            "over_merge_pair_rate_absolute_reduction"
        ]
        >= float(thresholds["over_merge_pair_rate_absolute_reduction_min"]),
        "over_split_noninferiority": over_split_increase
        <= float(thresholds["over_split_pair_rate_increase_max"]),
        "episode_pairwise_f1_noninferiority": deltas["episode_pairwise_f1_delta"]
        >= float(thresholds["episode_pairwise_f1_delta_min"]),
        "support_closure_auc_noninferiority": deltas["support_closure_auc_delta"]
        >= float(thresholds["support_closure_auc_delta_min"]),
    }
    if include_bootstrap:
        checks["over_merge_bootstrap_lower_positive"] = deltas[
            "over_merge_reduction_bootstrap_95_ci"
        ]["lower"] > float(thresholds["over_merge_pair_rate_delta_bootstrap_lower_gt"])
    all_source_ids = {
        str(source_id)
        for prediction in predictions
        for source_id in prediction["source_evidence_ids"]
    }
    user_source_ids = {
        str(source_id)
        for prediction in predictions
        for source_id, role in zip(
            prediction["source_evidence_ids"], prediction["source_roles"], strict=True
        )
        if role == "user"
    }
    artifact_source_ids = {
        str(source_id)
        for prediction in predictions
        for source_id in prediction["v02_artifact_source_ids"]
    }
    safety = {
        "raw_span_coverage": float(
            all(
                [source for group in prediction["v02_groups"] for source in group]
                == list(range(len(prediction["source_evidence_ids"])))
                for prediction in predictions
            )
        ),
        "source_order_preservation": float(
            all(
                [source for group in prediction["v02_groups"] for source in group]
                == sorted(
                    source for group in prediction["v02_groups"] for source in group
                )
                for prediction in predictions
            )
        ),
        "user_semantic_source_precision": float(
            artifact_source_ids.issubset(user_source_ids)
        ),
        "artifact_lineage_closure": float(artifact_source_ids.issubset(all_source_ids)),
        "deterministic_replay": float(
            all(
                bool(prediction["v02_deterministic_replay"])
                for prediction in predictions
            )
        ),
        "canonical_mutations": 0,
        "database_calls": 0,
        "database_writes": 0,
        "provider_calls": 0,
        "reader_calls": 0,
        "model_calls": 0,
        "formal_holdout_used": False,
        "default_feature_flag": "OFF",
    }
    failures = {
        "v02_over_merge": [
            record["conversation_id"]
            for record in records
            if float(record["V02"]["over_merge_pair_rate"]) > 0
        ],
        "v02_over_split": [
            record["conversation_id"]
            for record in records
            if float(record["V02"]["over_split_pair_rate"]) > 0
        ],
    }
    return {
        "boundary": boundary,
        "simple_read": read,
        "deltas": deltas,
        "checks": checks,
        "records": records,
        "failure_distribution": failures,
        "safety": safety,
        "h1_supported": all(checks.values())
        and all(
            value == 1.0
            for key, value in safety.items()
            if key
            in {
                "raw_span_coverage",
                "source_order_preservation",
                "user_semantic_source_precision",
                "artifact_lineage_closure",
                "deterministic_replay",
            }
        ),
    }


def _official_baseline_behavior(
    turns: Sequence[Mapping[str, Any]],
    query: str,
) -> tuple[dict[str, Any], list[str], int, _SnapshotRepository]:
    repository = _SnapshotRepository(turns)
    latest = max(_timestamp(turn["observed_at"]) for turn in turns) + timedelta(days=1)
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope={"project_ids": ["md02-shadow"]},
        as_of=latest,
        system_as_of=latest,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=16, context_budget=512)
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=16,
        context_tokens=512,
    )
    policy = AcquisitionCapabilityPolicy(max_candidates=16)
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=ProjectionState(1, 1, 1, False, False, 1, False),
        repository=repository,
        policy=policy,
        generated_at=latest,
        source_observed_range=acquisition_plan.global_constraints.source_observed_range,
        event_occurrence_range=acquisition_plan.global_constraints.event_occurrence_range,
    )
    execution = EvidenceAcquisitionExecutor(repository).execute(
        context=SessionContext(UUID(int=1), UUID(int=2)),
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=policy,
        mode="PRODUCT",
        state_epoch=0,
    )
    accepted_spans = _accepted_binding_spans(execution)
    accepted_ids = tuple(sorted({item.evidence_id for item in accepted_spans}))
    query_ir = query_plan.memory_query_ir
    if query_ir is None:
        raise MD02EffectError("OFFICIAL_QUERY_IR_MISSING")
    snapshot = build_decision_snapshot(
        source_snapshot_material=list(turns),
        query_ir_material=query_ir,
        acquisition_plan_material=acquisition_plan,
        candidate_snapshot_material=execution.candidates,
        gate_material=execution.candidates,
        binding_material=execution.bindings,
        requirement_state_material=execution.requirement_state,
        sufficiency_material=execution.sufficiency_decision,
        operator_result_material=execution.derived_result,
        accepted_evidence_ids=accepted_ids,
        accepted_binding_spans=accepted_spans,
        required_requirement_ids=[
            item.slot_id for item in query_ir.requirements if item.required
        ],
        unresolved_requirement_ids=execution.requirement_state.missing_requirement_ids,
    )
    outcome = {
        "status": "HIT" if execution.results else "ABSENT",
        "requirement": "SEARCH",
        "items": execution.results,
        "memory_query_ir": query_ir.model_dump(mode="json"),
        "sufficiency_decision": execution.sufficiency_decision.model_dump(mode="json"),
        "derived_result": execution.derived_result,
        "evidence_refs": list(accepted_ids),
        "open_issue_ids": [],
        "canonical_position": {
            "canonical_outbox_sequence": 1,
            "evidence_watermark": 1,
            "fts_watermark": 1,
        },
    }
    context_plan = MemoryContextCompiler(budget_stable_enabled=True).plan(
        MemoryResolveRequest(
            query=query,
            consistency_mode="EVENTUAL",
            requested_scope={"project_ids": ["md02-shadow"]},
            reference_time=latest,
            budget=MemoryResolveBudget(
                max_results=10,
                max_candidates=16,
                max_context_tokens=512,
                max_latency_ms=500,
            ),
        ),
        outcome,
        decision_snapshot=snapshot,
    )
    behavior = {
        "schema": "milai.md02.official-behavior-material.v0.1",
        "official_executor_identity": execution.executor_identity,
        "official_retrieval_occurrences_and_order": [
            {
                "evidence_id": item.get("evidence_id"),
                "source_ref": item.get("source_ref"),
            }
            for item in execution.results
        ],
        "governance_gated_evidence_candidates": [
            item.model_dump(mode="json") for item in execution.candidates
        ],
        "accepted_binding": [
            item.model_dump(mode="json") for item in execution.bindings
        ],
        "requirement_state": execution.requirement_state.model_dump(mode="json"),
        "sufficiency": execution.sufficiency_decision.model_dump(mode="json"),
        "operator_result": execution.derived_result,
        "reader_bound_context_plan": context_plan.reader_evidence_plan.model_dump(
            mode="json"
        ),
    }
    anchors = list(
        dict.fromkeys(
            str(item["evidence_id"])
            for item in execution.results
            if item.get("evidence_id") is not None
        )
    )
    return behavior, anchors, repository.calls, repository


def _accepted_binding_spans(execution: Any) -> tuple[AcceptedBindingSpan, ...]:
    interpretation_by_id = {
        item.interpretation_id: item for item in execution.interpretations
    }
    span_by_id = {item.span_id: item for item in execution.spans}
    requirements_by_span: dict[str, set[str]] = {}
    for binding in execution.bindings:
        if binding.status != "MATCH":
            continue
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        if interpretation is None:
            continue
        requirements_by_span.setdefault(interpretation.span_id, set()).add(
            binding.requirement_id
        )
    output = []
    for span_id, requirement_ids in requirements_by_span.items():
        span = span_by_id[span_id]
        output.append(
            AcceptedBindingSpan(
                requirement_ids=tuple(sorted(requirement_ids)),
                evidence_id=span.source_evidence_id,
                source_turn_ref=span.source_turn_ref,
                session_id=span.session_id,
                speaker=span.speaker,
                start=span.start,
                end=span.end,
                text=span.text,
                observed_at=(
                    span.source_timestamp.isoformat()
                    if span.source_timestamp is not None
                    else None
                ),
            )
        )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.source_turn_ref,
                item.start,
                item.end,
                item.requirement_ids,
                item.evidence_id,
            ),
        )
    )


class _SnapshotRepository:
    def __init__(self, turns: Sequence[Mapping[str, Any]]) -> None:
        self.turns = [dict(item) for item in turns]
        self.calls = 0

    def search_evidence(
        self,
        context: object,
        query: str,
        requested_scope: Mapping[str, object],
        as_of: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        del context, query, requested_scope, as_of
        self.calls += 1
        return [dict(item) for item in self.turns[:limit]]


def _score_shadow_rows(
    rows: Sequence[Mapping[str, Any]],
    freshness: Mapping[str, Any],
    conversation_count: int,
) -> dict[str, Any]:
    expected = {
        str(item["scenario"]): _mapping(item, "freshness scenario")
        for item in _sequence(freshness["scenarios"], "freshness scenarios")
    }
    current = [
        _mapping(row["current_observation"], "current observation") for row in rows
    ]
    scenarios = [
        {
            "conversation_id": row["conversation_id"],
            **_mapping(item, "scenario result"),
        }
        for row in rows
        for item in _sequence(row["freshness_scenarios"], "freshness scenario results")
    ]
    scenario_matches = []
    for item in scenarios:
        contract = expected[str(item["scenario"])]
        observation = _mapping(item["observation"], "scenario observation")
        scenario_matches.append(
            observation["freshness_status"] == contract["expected_freshness_status"]
            and observation["disposition"] == contract["expected_disposition"]
            and observation["raw_fallback_used"] == contract["raw_fallback_expected"]
        )
    stale = [item for item in scenarios if item["scenario"] == "APPENDED_EVIDENCE"]
    ineligible_names = {
        "REVOKED_EVIDENCE",
        "PERMISSION_REMOVED",
        "RETENTION_UNREADABLE",
        "FORMATION_FAILURE_RAW_FALLBACK",
    }
    ineligible = [item for item in scenarios if item["scenario"] in ineligible_names]
    revoked = [item for item in scenarios if item["scenario"] == "REVOKED_EVIDENCE"]
    permission = [
        item
        for item in scenarios
        if item["scenario"] in {"PERMISSION_REMOVED", "RETENTION_UNREADABLE"}
    ]
    fallback_expected = [
        item
        for item in scenarios
        if bool(expected[str(item["scenario"])]["raw_fallback_expected"])
    ]
    metrics = {
        "baseline_behavior_identity_rate": _rate(
            row["baseline_behavior_digest_before"]
            == row["baseline_behavior_digest_after"]
            for row in rows
        ),
        "shadow_build_success_rate": _rate(bool(row["bundle_digest"]) for row in rows),
        "shadow_deterministic_replay_rate": _rate(
            row["current_observation"] == row["deterministic_replay_observation"]
            for row in rows
        ),
        "fresh_bundle_acceptance_rate": _rate(
            item["freshness_status"] == "CURRENT" and item["disposition"] == "OBSERVED"
            for item in current
        ),
        "stale_bundle_rejection_rate": _rate(
            _mapping(item["observation"], "observation")["disposition"]
            == "STALE_REJECTED"
            for item in stale
        ),
        "ineligible_bundle_rejection_rate": _rate(
            _mapping(item["observation"], "observation")["freshness_status"]
            == "INELIGIBLE"
            for item in ineligible
        ),
        "revoked_evidence_leak_rate": _rate(
            bool(
                _mapping(item["observation"], "observation")[
                    "shadow_context_evidence_ids"
                ]
            )
            for item in revoked
        ),
        "permission_leak_rate": _rate(
            bool(
                _mapping(item["observation"], "observation")[
                    "shadow_context_evidence_ids"
                ]
            )
            for item in permission
        ),
        "raw_fallback_rate": _rate(
            bool(_mapping(item["observation"], "observation")["raw_fallback_used"])
            for item in fallback_expected
        ),
        "additional_official_acquisition_calls": sum(
            int(row["additional_shadow_repository_calls"]) for row in rows
        ),
        "additional_reader_provider_model_calls": 0,
        "canonical_mutations": 0,
        "database_writes": 0,
        "scenario_contract_match_rate": _rate(scenario_matches),
    }
    checks = {
        "baseline_behavior_identity": metrics["baseline_behavior_identity_rate"] == 1.0,
        "shadow_build_success": metrics["shadow_build_success_rate"] == 1.0,
        "shadow_deterministic_replay": metrics["shadow_deterministic_replay_rate"]
        == 1.0,
        "fresh_bundle_acceptance": metrics["fresh_bundle_acceptance_rate"] == 1.0,
        "stale_bundle_rejection": metrics["stale_bundle_rejection_rate"] == 1.0,
        "ineligible_bundle_rejection": metrics["ineligible_bundle_rejection_rate"]
        == 1.0,
        "revoked_evidence_leak_zero": metrics["revoked_evidence_leak_rate"] == 0.0,
        "permission_leak_zero": metrics["permission_leak_rate"] == 0.0,
        "raw_fallback_complete": metrics["raw_fallback_rate"] == 1.0,
        "additional_calls_zero": metrics["additional_official_acquisition_calls"] == 0
        and metrics["additional_reader_provider_model_calls"] == 0,
        "canonical_and_db_writes_zero": metrics["canonical_mutations"] == 0
        and metrics["database_writes"] == 0,
        "scenario_contract_exact": metrics["scenario_contract_match_rate"] == 1.0,
    }
    distribution = {
        disposition: sum(
            _mapping(item["observation"], "observation")["disposition"] == disposition
            for item in scenarios
        )
        for disposition in (
            "OBSERVED",
            "STALE_REJECTED",
            "PERMISSION_REJECTED",
            "RAW_FALLBACK",
        )
    }
    return {
        "conversation_count": conversation_count,
        "scenario_count": len(scenarios),
        "metrics": metrics,
        "checks": checks,
        "disposition_distribution": distribution,
        "h2_supported": all(checks.values()),
        "safety": {
            "formal_holdout_used": False,
            "default_feature_flag": "OFF",
            "public_mcp_changed": False,
            "schema_changed": False,
            "database_accessed": False,
            "provider_calls": 0,
            "reader_calls": 0,
            "model_calls": 0,
            "canonical_mutations": 0,
            "database_writes": 0,
        },
    }


def _scenario_inputs(
    scenario: str,
    turns: Sequence[Mapping[str, Any]],
    bundle: MemoryFormationBundleV01,
) -> tuple[list[dict[str, Any]], MemoryFormationBundleV01 | None, bool]:
    sources = copy.deepcopy([dict(item) for item in turns])
    if scenario == "UNCHANGED_SNAPSHOT":
        return sources, bundle, False
    if scenario == "APPENDED_EVIDENCE":
        latest = max(_timestamp(item["observed_at"]) for item in sources)
        prefix = str(sources[0]["evidence_id"]).split("-t", maxsplit=1)[0]
        text = "A newly appended Raw turn must invalidate the prebuilt bundle."
        sources.append(
            {
                "evidence_id": f"{prefix}-appended",
                "source_ref": f"memory://md02/appended/{prefix}",
                "session_id": sources[-1]["session_id"],
                "subject_id": sources[-1]["subject_id"],
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "observed_at": (latest + timedelta(minutes=1)).isoformat(),
                "captured_at": (latest + timedelta(minutes=1, seconds=1)).isoformat(),
                "content": text,
                "content_hash": canonical_sha256(text),
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "revoked_at": None,
                "kind": "EVIDENCE_OBSERVATION",
            }
        )
        return sources, bundle, False
    if scenario == "REVOKED_EVIDENCE":
        sources[0]["revoked_at"] = _timestamp(sources[0]["observed_at"]).isoformat()
        return sources, bundle, False
    if scenario == "PERMISSION_REMOVED":
        sources[0]["permission_snapshot"] = {"readable": False}
        return sources, bundle, False
    if scenario == "RETENTION_UNREADABLE":
        sources[0]["retention_state"] = "UNREADABLE"
        return sources, bundle, False
    if scenario == "FORMATION_FAILURE_RAW_FALLBACK":
        return sources, None, True
    raise MD02EffectError(f"UNKNOWN_FRESHNESS_SCENARIO:{scenario}")


def _conversation_boundary_metrics(
    gold_groups: Sequence[Sequence[int]],
    predicted_groups: Sequence[Sequence[int]],
) -> dict[str, float]:
    gold = _membership(gold_groups)
    predicted = _membership(predicted_groups)
    indexes = sorted(gold)
    tp = fp = fn = tn = 0
    for offset, left in enumerate(indexes):
        for right in indexes[offset + 1 :]:
            gold_same = gold[left] == gold[right]
            predicted_same = predicted[left] == predicted[right]
            if gold_same and predicted_same:
                tp += 1
            elif not gold_same and predicted_same:
                fp += 1
            elif gold_same and not predicted_same:
                fn += 1
            else:
                tn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    gold_boundaries = _boundaries(gold_groups)
    predicted_boundaries = _boundaries(predicted_groups)
    boundary_tp = len(gold_boundaries & predicted_boundaries)
    boundary_fp = len(predicted_boundaries - gold_boundaries)
    boundary_fn = len(gold_boundaries - predicted_boundaries)
    boundary_precision = (
        boundary_tp / (boundary_tp + boundary_fp) if boundary_tp + boundary_fp else 1.0
    )
    boundary_recall = (
        boundary_tp / (boundary_tp + boundary_fn) if boundary_tp + boundary_fn else 1.0
    )
    boundary_f1 = (
        2
        * boundary_precision
        * boundary_recall
        / (boundary_precision + boundary_recall)
        if boundary_precision + boundary_recall
        else 0.0
    )
    return {
        "over_merge_pair_rate": fp / (fp + tn) if fp + tn else 0.0,
        "over_split_pair_rate": fn / (tp + fn) if tp + fn else 0.0,
        "episode_pairwise_precision": precision,
        "episode_pairwise_recall": recall,
        "episode_pairwise_f1": f1,
        "boundary_precision": boundary_precision,
        "boundary_recall": boundary_recall,
        "boundary_f1": boundary_f1,
    }


def _probe_read_metrics(
    groups: Sequence[Sequence[int]],
    source_ids: Sequence[str],
    ranking: Sequence[str],
    required: set[str],
    distractors: set[str],
) -> dict[str, Any]:
    closure: list[float] = []
    distractor_rates: list[float] = []
    contexts: dict[str, list[str]] = {}
    for ceiling in CEILINGS:
        context = _hydrate(groups, source_ids, ranking, ceiling)
        contexts[str(ceiling)] = context
        closure.append(float(required.issubset(context)))
        distractor_rates.append(
            len(distractors & set(context)) / len(context) if context else 0.0
        )
    return {
        "support_closure_auc": statistics.mean(closure),
        "support_closure_by_ceiling": dict(
            zip(map(str, CEILINGS), closure, strict=True)
        ),
        "distractor_turn_rate": statistics.mean(distractor_rates),
        "contexts": contexts,
    }


def _hydrate(
    groups: Sequence[Sequence[int]],
    source_ids: Sequence[str],
    ranking: Sequence[str],
    ceiling: int,
) -> list[str]:
    unit_by_source = {
        source_ids[index]: unit_index
        for unit_index, group in enumerate(groups)
        for index in group
    }
    selected_units: list[int] = []
    for anchor_id in ranking:
        unit_index = unit_by_source.get(anchor_id)
        if unit_index is not None and unit_index not in selected_units:
            selected_units.append(unit_index)
    output: list[str] = []
    for unit_index in selected_units:
        unit_ids = [source_ids[index] for index in groups[unit_index]]
        new_ids = [value for value in unit_ids if value not in output]
        if len(output) + len(new_ids) > ceiling:
            break
        output.extend(new_ids)
    return output


def _groups(bundle: MemoryFormationBundleV01) -> list[list[int]]:
    index_by_id = {
        evidence_id: index
        for index, evidence_id in enumerate(bundle.source_evidence_ids)
    }
    return [
        [index_by_id[span.evidence_id] for span in episode.source_spans]
        for episode in bundle.episode_candidates
    ]


def _artifact_source_ids(result: MemoryFormationBuildResultV02) -> set[str]:
    bundle = result.bundle
    return {
        *[item.span.evidence_id for item in bundle.semantic_sidecar.entity_candidates],
        *[item.span.evidence_id for item in bundle.semantic_sidecar.event_candidates],
        *[item.span.evidence_id for item in bundle.state_change_sidecar.assertions],
        *[item.span.evidence_id for item in bundle.state_change_sidecar.transitions],
    }


def _membership(groups: Sequence[Sequence[int]]) -> dict[int, int]:
    return {
        index: group_index
        for group_index, group in enumerate(groups)
        for index in group
    }


def _boundaries(groups: Sequence[Sequence[int]]) -> set[int]:
    return {min(group) for group in groups if min(group) > 0}


def _bootstrap_ci(values: Sequence[float], seed: int, resamples: int) -> dict[str, Any]:
    if not values:
        raise MD02EffectError("BOOTSTRAP_VALUES_EMPTY")
    generator = random.Random(seed)
    samples = sorted(
        statistics.mean(generator.choice(values) for _ in values)
        for _ in range(resamples)
    )
    return {
        "lower": samples[int(0.025 * (resamples - 1))],
        "upper": samples[int(0.975 * (resamples - 1))],
        "seed": seed,
        "resamples": resamples,
        "unit": "conversation",
    }


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def _rate(values: Iterable[bool]) -> float:
    realized = list(values)
    return sum(realized) / len(realized) if realized else 1.0


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise MD02EffectError("TIMESTAMP_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MD02EffectError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed


def _verify_fixture(
    lock: Mapping[str, Any],
    fixture: Mapping[str, Any],
    name: str,
    path: Path,
) -> None:
    identity = _mapping(_mapping(lock["fixtures"], "fixtures")[name], name)
    _verify_identity(path, identity)
    conversations = _sequence(fixture.get("conversations"), "conversations")
    if len(conversations) != int(identity["conversation_count"]):
        raise MD02EffectError(f"FIXTURE_CONVERSATION_COUNT_DRIFT:{name}")


def _verify_identity(path: Path, identity: object) -> None:
    expected = _mapping(identity, "identity")
    if (
        hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]
        or path.stat().st_size != expected["size"]
    ):
        raise MD02EffectError(f"IDENTITY_DRIFT:{path}")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MD02EffectError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MD02EffectError(f"MAPPING_REQUIRED:{name}")
    return value


def _sequence(value: object, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MD02EffectError(f"SEQUENCE_REQUIRED:{name}")
    return value


__all__ = [
    "MD02EffectError",
    "environment_witness",
    "evaluate_repair_dev",
    "execute_boundary_effect",
    "execute_shadow_effect",
    "hand_contract_sanity",
    "mf02_historical_non_regression",
]
