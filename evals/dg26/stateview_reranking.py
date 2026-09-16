"""Frozen DG-26 fixed-pool StateView reranking experiment.

All model-visible material is built from label-free inputs.  Scorer registries
are opened only after every arm has produced an immutable selection output.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote

from milai.adapters import (
    FrozenOnnxCrossEncoderReranker,
    StateAwareCrossEncoderReranker,
    fixed_candidate_pool_digest,
)
from milai.application.acquisition import compile_acquisition_plan
from milai.application.evidence_semantics import (
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_state import resolve_requirement_state
from milai.domain.acquisition import AcquisitionPlan, CandidateEnvelope
from milai.domain.ranking_state_view import (
    RankingStateViewV01,
    build_ranking_state_view,
)
from milai.domain.requirement_state import RequirementState, canonical_sha256
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.domain.semantic_query import MemoryQueryIRV02
from milai.domain.sufficiency import SufficiencyDecision

from evals.dg14.contracts import normalize_lme_timestamp

ARM_ORDER = ("R0", "R1", "R2", "R3")
MODEL_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
GOLD_SHA256 = "c13789936296695027191f3c625c99e49e5725db189fd53791d207879226493a"
PROOF_SHA256 = "a2e40b175c33ebc453253e1596f680285c33e13e6b8141cd6a0d5be6158ba26a"
_LONGMEM_SOURCE_REF = re.compile(
    r"^longmemeval://case/([^/]+)/session/(\d+)/([^/]+)/turn/(\d+)(?:\?|$)"
)


class DG26ExperimentError(RuntimeError):
    """The frozen experiment contract or one source identity drifted."""


@dataclass(frozen=True, slots=True)
class QueryContext:
    case_id: str
    query: str
    plan: QueryPlan
    query_ir: MemoryQueryIRV02
    acquisition_plan: AcquisitionPlan
    requirement_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequirementPool:
    case_id: str
    requirement_id: str
    query: str
    anchors: tuple[str, ...]
    candidates: tuple[dict[str, Any], ...]
    pool_digest: str


@dataclass(frozen=True, slots=True)
class ExperimentInputs:
    lock: dict[str, Any]
    order: tuple[tuple[str, str], ...]
    contexts: dict[str, QueryContext]
    pools: dict[tuple[str, str], RequirementPool]


@dataclass(frozen=True, slots=True)
class ArmEvaluation:
    records: dict[tuple[str, str], list[dict[str, Any]]]
    states: dict[str, RequirementState]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_run_lock(root: Path, path: Path) -> dict[str, Any]:
    root = root.resolve()
    lock = _object(path)
    if lock.get("schema") != "milai.dg26.run-lock.v0.1":
        raise DG26ExperimentError("DG26_RUN_LOCK_SCHEMA_DRIFT")
    material = dict(lock)
    observed_lock_digest = material.pop("lock_digest", None)
    if observed_lock_digest != canonical_sha256(material):
        raise DG26ExperimentError("DG26_RUN_LOCK_DIGEST_MISMATCH")
    if lock.get("config_digest") != canonical_sha256(lock.get("config")):
        raise DG26ExperimentError("DG26_CONFIG_DIGEST_MISMATCH")
    serialization = _mapping(_mapping(lock["config"], "config")["serialization"], "serialization")
    if lock.get("chat_template_digest") != canonical_sha256(serialization):
        raise DG26ExperimentError("DG26_SERIALIZATION_DIGEST_MISMATCH")
    if (
        lock.get("formal_holdout_used") is not False
        or _mapping(lock.get("safety"), "safety").get("candidate_feature_flag") != "OFF"
        or _mapping(lock.get("budget"), "budget").get("automatic_retries") != 0
    ):
        raise DG26ExperimentError("DG26_FROZEN_SAFETY_BOUNDARY_DRIFT")
    identities = [
        _mapping(lock["predecessor_terminal"], "predecessor terminal"),
        *[_mapping(item, "entry evidence") for item in _sequence(lock["entry"]["evidence"], "entry evidence")],
        _mapping(lock["dataset_snapshot"], "dataset snapshot"),
        *[
            _mapping(value, f"memory snapshot {key}")
            for key, value in _mapping(lock["memory_snapshot"], "memory snapshot").items()
        ],
        _mapping(lock["model_identity"], "model identity"),
        _mapping(lock["tokenizer_identity"], "tokenizer identity"),
    ]
    for identity in identities:
        _verify_identity(root, identity)
    tokenizer = _mapping(lock["tokenizer_identity"], "tokenizer identity")
    _verify_named_identity(
        root,
        str(tokenizer["config_path"]),
        str(tokenizer["config_sha256"]),
        int(tokenizer["config_size"]),
    )
    return lock


def load_experiment_inputs(root: Path, run_lock_path: Path) -> ExperimentInputs:
    root = root.resolve()
    lock = load_run_lock(root, run_lock_path)
    dataset = _object(root / str(lock["dataset_snapshot"]["path"]))
    if (
        dataset.get("schema") != "milai.dg11.paper-longmemeval-inputs.v1"
        or dataset.get("forbidden_label_fields_present") is not False
        or dataset.get("label_fields_accessed") is not False
        or dataset.get("paper_labels_opened") is not False
    ):
        raise DG26ExperimentError("DG26_LABEL_FREE_DATASET_CONTRACT_DRIFT")
    cases = {
        str(item["source_id"]): _mapping(item, "label-free case")
        for item in _sequence(dataset.get("cases"), "label-free cases")
    }
    memory = _mapping(lock["memory_snapshot"], "memory snapshot")
    manifest = _object(root / str(memory["input_manifest"]["path"]))
    action_manifest = _object(root / str(memory["e1_action_manifest"]["path"]))
    probes = _object(root / str(memory["official_probe_collection"]["path"]))
    baseline_bundle = _object(root / str(memory["e1_label_free_baseline"]["path"]))
    case_order = tuple(str(value) for value in _sequence(manifest["case_order"], "case order"))
    requests = {
        str(item["case_id"]): _mapping(item, "input request")
        for item in _sequence(manifest["requests"], "input requests")
    }
    raw_order = _sequence(action_manifest["query_requirement_order"], "requirement order")
    order = tuple(
        (str(item["case_id"]), str(item["requirement_id"])) for item in raw_order
    )
    if len(case_order) != 10 or len(order) != 15 or set(case_order) != set(requests):
        raise DG26ExperimentError("DG26_FROZEN_DENOMINATOR_DRIFT")

    requirements_by_case: dict[str, list[str]] = {case_id: [] for case_id in case_order}
    for case_id, requirement_id in order:
        requirements_by_case[case_id].append(requirement_id)
    contexts: dict[str, QueryContext] = {}
    for case_id in case_order:
        case = cases.get(case_id)
        request = requests[case_id]
        if case is None or case.get("question") != request.get("query_text"):
            raise DG26ExperimentError("DG26_LABEL_FREE_QUERY_IDENTITY_DRIFT")
        reference_time = datetime.fromisoformat(
            normalize_lme_timestamp(str(case["question_date"])).replace("Z", "+00:00")
        )
        query = str(case["question"])
        retrieval_request = RetrievalRequest(
            route="L1",
            consistency="CANONICAL_REQUIRED",
            query=query,
            as_of=reference_time,
            reference_time=reference_time,
            system_as_of=reference_time,
            limit=8,
        )
        plan = QueryPlanner().plan(
            retrieval_request,
            candidate_cap=8,
            reranker_candidate_cap=0,
        )
        query_ir = plan.memory_query_ir
        if query_ir is None:
            raise DG26ExperimentError("DG26_QUERY_IR_MISSING")
        required = tuple(item.slot_id for item in query_ir.requirements if item.required)
        expected = tuple(requirements_by_case[case_id])
        if set(required) != set(expected):
            raise DG26ExperimentError("DG26_QUERY_REQUIREMENT_SET_DRIFT")
        acquisition_plan = compile_acquisition_plan(
            plan,
            query=query,
            principal_scope={},
            authority_floor="INFORMATIONAL",
            candidate_limit=8,
            context_tokens=8_000,
            include_global_probe=False,
        )
        contexts[case_id] = QueryContext(
            case_id=case_id,
            query=query,
            plan=plan,
            query_ir=query_ir,
            acquisition_plan=acquisition_plan,
            requirement_ids=expected,
        )

    probe_index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in _sequence(probes.get("records"), "official probe records"):
        record = _mapping(item, "official probe record")
        trace = _mapping(record.get("trace"), "official probe trace")
        if trace.get("channel") != "FTS_RAW":
            continue
        key = (str(record["case_id"]), str(trace["requirement_id"]))
        if key in probe_index:
            raise DG26ExperimentError("DG26_DUPLICATE_FTS_RAW_POOL")
        probe_index[key] = trace
    baseline_index = _baseline_selected_index(baseline_bundle)
    pools: dict[tuple[str, str], RequirementPool] = {}
    for key in order:
        case_id, requirement_id = key
        pool_trace = probe_index.get(key)
        if pool_trace is None or pool_trace.get("disposition") != "EXECUTED":
            raise DG26ExperimentError("DG26_FTS_RAW_POOL_UNAVAILABLE")
        raw_occurrences = _sequence(
            pool_trace.get("returned_occurrences"), "pool occurrences"
        )
        candidates = [
            _hydrate_candidate(cases[case_id], case_id, requirement_id, raw)
            for raw in raw_occurrences
        ]
        ranks = [int(item["raw_rank"]) for item in candidates]
        identities = [str(item["evidence_id"]) for item in candidates]
        if ranks != list(range(1, len(candidates) + 1)) or len(set(identities)) != len(identities):
            raise DG26ExperimentError("DG26_POOL_ORDER_OR_IDENTITY_DRIFT")
        expected_baseline = baseline_index[key]
        observed_baseline = identities[: min(8, len(identities))]
        if observed_baseline != expected_baseline:
            raise DG26ExperimentError("DG26_R0_SELECTION_DRIFT_FROM_DG25")
        anchors = tuple(sorted({str(value) for value in candidates[0]["normalized_terms"]}))
        pool_digest = fixed_candidate_pool_digest(candidates)
        pools[key] = RequirementPool(
            case_id=case_id,
            requirement_id=requirement_id,
            query=contexts[case_id].query,
            anchors=anchors,
            candidates=tuple(candidates),
            pool_digest=pool_digest,
        )
    if len(pools) != 15 or sum(len(item.candidates) for item in pools.values()) != 327:
        raise DG26ExperimentError("DG26_FIXED_POOL_DENOMINATOR_DRIFT")
    return ExperimentInputs(lock=lock, order=order, contexts=contexts, pools=pools)


def execute_once(
    root: Path,
    run_lock_path: Path,
    gold_registry_path: Path,
    proof_registry_path: Path,
    attribution_path: Path,
) -> dict[str, Any]:
    """Execute all label-free arms, then open scorer-only registries once."""

    root = root.resolve()
    inputs = load_experiment_inputs(root, run_lock_path)
    baseline_selections = {
        key: [dict(item) for item in pool.candidates[: min(8, len(pool.candidates))]]
        for key, pool in inputs.pools.items()
    }
    baseline = _evaluate_selections(inputs, baseline_selections, build_states=True)
    views = _build_views(inputs, baseline.states)
    selections: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {
        "R0": baseline_selections
    }
    batch_summaries: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARM_ORDER}
    reranker = _reranker(inputs, root)
    for arm, state_mode in (("R1", "NONE"), ("R2", "CORRECT"), ("R3", "SHUFFLED")):
        arm_selections: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for key in inputs.order:
            pool = inputs.pools[key]
            view = views[key] if state_mode != "NONE" else None
            execution = reranker.rerank(
                pool.query,
                [dict(item) for item in pool.candidates],
                limit=min(8, len(pool.candidates)),
                pool_size=len(pool.candidates),
                state_view=view,
                state_mode=cast(Any, state_mode),
            )
            arm_selections[key] = execution.results
            batch_summaries[arm].append(
                {
                    "query_id": key[0],
                    "requirement_id": key[1],
                    "pairs": int(execution.metadata.get("pairs", 0)),
                    "duration_ms": float(execution.metadata.get("duration_ms", 0.0)),
                    "fallback_used": execution.metadata.get("fallback_used") is True,
                    "fallback_reason": execution.metadata.get("fallback_reason"),
                    "model_invocations": int(execution.metadata.get("model_invocations", 0)),
                    "automatic_retries": int(execution.metadata.get("automatic_retries", 0)),
                }
            )
        selections[arm] = arm_selections

    evaluations = {
        "R0": baseline,
        **{
            arm: _evaluate_selections(inputs, selections[arm], build_states=False)
            for arm in ARM_ORDER[1:]
        },
    }
    # Scorer labels are opened only after every arm and Runtime Binding pass exists.
    scorer = _load_scorer(
        root,
        gold_registry_path,
        proof_registry_path,
        attribution_path,
    )
    scores, residual_groups = _score_all(inputs, evaluations, scorer)
    fallback_count = sum(
        int(item["fallback_used"])
        for arm in ARM_ORDER[1:]
        for item in batch_summaries[arm]
    )
    model_batches = sum(
        int(item["model_invocations"])
        for arm in ARM_ORDER[1:]
        for item in batch_summaries[arm]
    )
    model_pairs = sum(
        int(item["pairs"])
        for arm in ARM_ORDER[1:]
        for item in batch_summaries[arm]
    )
    automatic_retries = sum(
        int(item["automatic_retries"])
        for arm in ARM_ORDER[1:]
        for item in batch_summaries[arm]
    )
    output: dict[str, Any] = {
        "schema": "milai.dg26.single-run-result.v0.1",
        "run_lock_digest": inputs.lock["lock_digest"],
        "arm_order": list(ARM_ORDER),
        "label_boundary": {
            "model_input_source": str(inputs.lock["dataset_snapshot"]["path"]),
            "answer_bearing_treatment_inputs": 0,
            "registry_open_phase": "POST_ALL_ARM_EXECUTION_AND_RUNTIME_BINDING",
            "registry_open_count": 2,
        },
        "views": [
            {
                "query_id": key[0],
                "requirement_id": key[1],
                "view_digest": views[key].view_digest,
                "requirement_state_digest": views[key].requirement_state_digest,
                "candidate_pool_digest": views[key].candidate_pool_digest,
                "semantic_material": views[key].semantic_material(),
            }
            for key in inputs.order
        ],
        "arms": {
            arm: {
                "records": _safe_records(inputs, evaluations[arm].records),
                "metrics": scores[arm],
            }
            for arm in ARM_ORDER
        },
        "residual_groups": residual_groups,
        "error_analysis": _error_analysis(scores),
        "safety": {
            "adapter_fallback_count": fallback_count,
            "wrong_complete": int(scores["R2"]["wrong_complete"]),
            "baseline_correct_groups_lost": int(scores["R2"]["baseline_correct_groups_lost"]),
            "acquisition_call_delta": 0,
            "reader_calls": 0,
            "canonical_mutation": 0,
            "automatic_retries": automatic_retries,
            "authority_violations": 0,
            "formal_holdout_used": False,
            "candidate_feature_flag": "OFF",
        },
        "cost": {
            "model_batches": model_batches,
            "model_pairs": model_pairs,
            "model_duration_ms": round(
                sum(
                    float(item["duration_ms"])
                    for arm in ARM_ORDER[1:]
                    for item in batch_summaries[arm]
                ),
                3,
            ),
            "batch_summaries": batch_summaries,
            "acquisition_calls": 0,
            "automatic_retries": automatic_retries,
        },
    }
    projection = deterministic_projection(output)
    output["semantic_digest"] = canonical_sha256(projection)
    return output


def deterministic_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    """Drop latency-only observations from fresh-process equality."""

    return {
        key: item
        for key, item in value.items()
        if key not in {"cost", "semantic_digest"}
    }


def derive_decision(
    single_run: Mapping[str, Any],
    *,
    fresh_process_exact_match: bool,
) -> dict[str, Any]:
    arms = _mapping(single_run["arms"], "arms")
    r0 = _mapping(_mapping(arms["R0"], "R0")["metrics"], "R0 metrics")
    r1 = _mapping(_mapping(arms["R1"], "R1")["metrics"], "R1 metrics")
    r2 = _mapping(_mapping(arms["R2"], "R2")["metrics"], "R2 metrics")
    r3 = _mapping(_mapping(arms["R3"], "R3")["metrics"], "R3 metrics")
    safety = _mapping(single_run["safety"], "safety")
    checks = {
        "r2_recovers_residual_group": int(r2["residual_groups_recovered"]) >= 1,
        "r2_loses_no_r0_group": int(r2["baseline_correct_groups_lost"]) == 0,
        "r2_beats_query_only": int(r2["covered_groups"]) > int(r1["covered_groups"]),
        "r2_beats_shuffled_state": int(r2["covered_groups"]) > int(r3["covered_groups"]),
        "accepted_binding_precision_non_regression": float(r2["accepted_binding_precision"])
        >= float(r0["accepted_binding_precision"]),
        "wrong_complete_zero": int(r2["wrong_complete"]) == 0,
        "acquisition_call_delta_zero": int(safety["acquisition_call_delta"]) == 0,
        "adapter_fallback_zero": int(safety["adapter_fallback_count"]) == 0,
        "automatic_retry_zero": int(safety["automatic_retries"]) == 0,
        "fresh_process_exact_match": fresh_process_exact_match,
    }
    if not (
        checks["adapter_fallback_zero"]
        and checks["automatic_retry_zero"]
        and checks["fresh_process_exact_match"]
        and checks["wrong_complete_zero"]
        and checks["acquisition_call_delta_zero"]
    ):
        status, reason = "FAIL", "SAFETY_OR_PROTOCOL"
    elif not checks["r2_loses_no_r0_group"]:
        status, reason = "FAIL", "CORRECT_CASE_REGRESSION"
    elif not checks["accepted_binding_precision_non_regression"]:
        status, reason = "FAIL", "SAFETY_OR_PROTOCOL"
    elif not checks["r2_recovers_residual_group"]:
        status, reason = "PARKED", "NO_STATEVIEW_GAIN"
    elif not (checks["r2_beats_query_only"] and checks["r2_beats_shuffled_state"]):
        status, reason = "PARKED", "GAIN_NOT_STATE_CONDITIONED"
    else:
        status, reason = "PASS", "STATEVIEW_RERANKING_GAIN"
    return {"status": status, "reason_code": reason, "checks": checks}


def _reranker(inputs: ExperimentInputs, root: Path) -> StateAwareCrossEncoderReranker:
    model = _mapping(inputs.lock["model_identity"], "model identity")
    tokenizer = _mapping(inputs.lock["tokenizer_identity"], "tokenizer identity")
    model_path = root / str(model["path"])
    backend = FrozenOnnxCrossEncoderReranker(
        model_path.parents[1],
        model_id=str(model["model_id"]),
        revision=str(model["revision"]),
        expected_model_sha256=str(model["sha256"]),
    )
    return StateAwareCrossEncoderReranker(
        backend,
        expected_identity={
            "provider": "onnx_cross_encoder",
            "model_id": str(model["model_id"]),
            "revision": MODEL_REVISION,
            "model_sha256": str(model["sha256"]),
            "tokenizer_sha256": str(tokenizer["sha256"]),
            "runtime": "onnxruntime/CPUExecutionProvider",
            "max_length": 512,
        },
    )


def _build_views(
    inputs: ExperimentInputs,
    states: Mapping[str, RequirementState],
) -> dict[tuple[str, str], RankingStateViewV01]:
    result: dict[tuple[str, str], RankingStateViewV01] = {}
    for key in inputs.order:
        pool = inputs.pools[key]
        context = inputs.contexts[key[0]]
        result[key] = build_ranking_state_view(
            requirement_state=states[key[0]],
            requirement_id=key[1],
            query_operator=infer_operator_family(context.query_ir),
            permission_trimmed_anchors=list(pool.anchors),
            candidate_pool_digest=pool.pool_digest,
            selection_cutoff_k=8,
        )
    return result


def _evaluate_selections(
    inputs: ExperimentInputs,
    selections: Mapping[tuple[str, str], list[dict[str, Any]]],
    *,
    build_states: bool,
) -> ArmEvaluation:
    records: dict[tuple[str, str], list[dict[str, Any]]] = {}
    states: dict[str, RequirementState] = {}
    for case_id, context in inputs.contexts.items():
        selected_by_requirement = {
            requirement_id: selections[(case_id, requirement_id)]
            for requirement_id in context.requirement_ids
        }
        union: dict[str, dict[str, Any]] = {}
        matched_slots: dict[str, set[str]] = {}
        min_rank: dict[str, int] = {}
        for requirement_id in context.requirement_ids:
            for rank, candidate in enumerate(selected_by_requirement[requirement_id], start=1):
                evidence_id = str(candidate["evidence_id"])
                union.setdefault(evidence_id, dict(candidate))
                matched_slots.setdefault(evidence_id, set()).add(requirement_id)
                min_rank[evidence_id] = min(min_rank.get(evidence_id, rank), rank)
        evidence = list(union.values())
        spans = project_evidence_spans(evidence)
        interpretations, bindings, _audit = run_type_directed_semantics(
            context.query_ir.requirements,
            spans,
            compatibility_profile="dg22-v0.2",
        )
        span_by_id = {item.span_id: item for item in spans}
        interpretation_by_id = {item.interpretation_id: item for item in interpretations}
        binding_status: dict[tuple[str, str], str] = {}
        priority = {"REJECTED": 1, "POSSIBLE": 2, "MATCH": 3}
        for binding in bindings:
            interpretation = interpretation_by_id[binding.interpretation_id]
            span = span_by_id[interpretation.span_id]
            key = (binding.requirement_id, span.source_evidence_id)
            previous = binding_status.get(key, "NOT_EVALUATED")
            if priority.get(binding.status, 0) > priority.get(previous, 0):
                binding_status[key] = binding.status
        for requirement_id, values in selected_by_requirement.items():
            records[(case_id, requirement_id)] = [
                {
                    **dict(item),
                    "binding_status": binding_status.get(
                        (requirement_id, str(item["evidence_id"])),
                        "NOT_EVALUATED",
                    ),
                }
                for item in values
            ]
        if build_states:
            covered = sorted(
                {
                    requirement_id
                    for (requirement_id, _evidence_id), status in binding_status.items()
                    if status == "MATCH"
                }
            )
            required = sorted(context.requirement_ids)
            decision = SufficiencyDecision(
                status="PARTIAL" if covered else "UNSATISFIED",
                covered_slots=covered,
                missing_slots=[item for item in required if item not in covered],
                stop_reason="SEARCH_SPACE_EXHAUSTED",
            )
            candidates = [
                _candidate_envelope(
                    candidate,
                    matched_slots=sorted(matched_slots[str(candidate["evidence_id"])]),
                    fusion_rank=index,
                    source_rank=min_rank[str(candidate["evidence_id"])],
                )
                for index, candidate in enumerate(evidence, start=1)
            ]
            states[case_id] = resolve_requirement_state(
                plan=context.acquisition_plan,
                requirements=context.query_ir.requirements,
                acquisition_capability_digest=canonical_sha256(
                    {
                        "capability": "DG26_FIXED_FTS_RAW_POOL",
                        "pool_digests": [
                            inputs.pools[(case_id, requirement_id)].pool_digest
                            for requirement_id in context.requirement_ids
                        ],
                    }
                ),
                candidates=candidates,
                spans=spans,
                interpretations=interpretations,
                bindings=bindings,
                sufficiency_decision=decision,
                state_epoch=0,
                memory_query_ir=context.query_ir,
            )
    return ArmEvaluation(records=records, states=states)


def _candidate_envelope(
    candidate: Mapping[str, Any],
    *,
    matched_slots: list[str],
    fusion_rank: int,
    source_rank: int,
) -> CandidateEnvelope:
    evidence_id = str(candidate["evidence_id"])
    return CandidateEnvelope(
        candidate_id=evidence_id,
        source_evidence_id=evidence_id,
        source_turn_ref=str(candidate["source_ref"]),
        subject_id=str(candidate.get("subject_id") or candidate["session_id"]),
        session_id=str(candidate["session_id"]),
        turn_id=str(candidate.get("turn_id") or candidate["source_ref"]),
        identity_source="STRUCTURED_TURN_METADATA",
        speaker=cast(Any, candidate["speaker"]),
        speaker_source="STRUCTURED_TURN_METADATA",
        source_observed_at=datetime.fromisoformat(str(candidate["observed_at"])),
        matched_probes=[f"dg26:{slot}:FTS_RAW" for slot in matched_slots],
        matched_slots=matched_slots,
        channel_ranks={"FTS_RAW": source_rank},
        channel_scores={"FTS_RAW": float(candidate["raw_score"])},
        probe_ranks={f"dg26:{slot}:FTS_RAW": source_rank for slot in matched_slots},
        probe_scores={
            f"dg26:{slot}:FTS_RAW": float(candidate["raw_score"])
            for slot in matched_slots
        },
        fusion_rank=fusion_rank,
        fusion_score=1.0 / (60 + source_rank),
        matched_fields=["lexical_text"],
        body_ref=str(candidate["source_ref"]),
        body_hydrated=True,
    )


def _hydrate_candidate(
    case: Mapping[str, Any],
    case_id: str,
    requirement_id: str,
    raw: object,
) -> dict[str, Any]:
    occurrence = _mapping(raw, "pool occurrence")
    evidence = _mapping(occurrence.get("evidence_record_identity"), "evidence identity")
    source_ref = str(evidence["source_ref"])
    matched = _LONGMEM_SOURCE_REF.match(source_ref)
    if matched is None:
        raise DG26ExperimentError("DG26_SOURCE_REF_INVALID")
    source_case, session_ordinal, session_id, turn_ordinal = matched.groups()
    if unquote(source_case) != case_id:
        raise DG26ExperimentError("DG26_SOURCE_CASE_SCOPE_MISMATCH")
    sessions = _sequence(case.get("sessions"), "case sessions")
    session = _mapping(sessions[int(session_ordinal)], "source session")
    if str(session["session_id"]) != unquote(session_id):
        raise DG26ExperimentError("DG26_SOURCE_SESSION_IDENTITY_MISMATCH")
    turns = _sequence(session.get("turns"), "source turns")
    turn = _mapping(turns[int(turn_ordinal)], "source turn")
    speaker = str(turn["role"])
    content = str(turn["content"])
    captured_body = f"{speaker}: {content}"
    if hashlib.sha256(captured_body.encode()).hexdigest() != evidence.get("content_hash"):
        raise DG26ExperimentError("DG26_CAPTURED_BODY_HASH_MISMATCH")
    observed_at = datetime.fromisoformat(
        normalize_lme_timestamp(str(session["observed_at"])).replace("Z", "+00:00")
    ).isoformat()
    if observed_at != evidence.get("observed_at"):
        raise DG26ExperimentError("DG26_SOURCE_OBSERVED_AT_MISMATCH")
    for field in ("permission_snapshot_digest", "retention_snapshot_digest"):
        value = evidence.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise DG26ExperimentError("DG26_GOVERNANCE_SNAPSHOT_IDENTITY_MISSING")
    normalized_terms = [
        str(value) for value in _sequence(occurrence.get("normalized_terms"), "normalized terms")
    ]
    score = occurrence.get("raw_score")
    return {
        "evidence_id": str(evidence["evidence_id"]),
        "source_ref": source_ref,
        "content_hash": str(evidence["content_hash"]),
        "observed_at": observed_at,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "session_id": unquote(session_id),
        "content": captured_body,
        "memory_text": f"observed_at={observed_at}\nspeaker={speaker}\ncontent={content}",
        "payload": {
            "memory_text": f"observed_at={observed_at}\nspeaker={speaker}\ncontent={content}"
        },
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "access_decision": "ALLOWED",
        "raw_rank": int(occurrence["raw_rank"]),
        "raw_score": (
            float(score)
            if isinstance(score, (int, float)) and not isinstance(score, bool)
            else 0.0
        ),
        "occurrence_id": str(occurrence["occurrence_id"]),
        "requirement_id": requirement_id,
        "normalized_terms": normalized_terms,
        "permission_snapshot_digest": str(evidence["permission_snapshot_digest"]),
        "retention_snapshot_digest": str(evidence["retention_snapshot_digest"]),
    }


def _baseline_selected_index(bundle: Mapping[str, Any]) -> dict[tuple[str, str], list[str]]:
    arm_outputs = _mapping(bundle.get("arm_outputs"), "arm outputs")
    r0 = _mapping(arm_outputs.get("R0"), "R0 output")
    result: dict[tuple[str, str], list[str]] = {}
    for record in _sequence(r0.get("records"), "R0 records"):
        row = _mapping(record, "R0 record")
        case_id = str(row["query_id"])
        for requirement in _sequence(row.get("requirements"), "R0 requirements"):
            item = _mapping(requirement, "R0 requirement")
            result[(case_id, str(item["requirement_id"]))] = [
                str(_mapping(value, "R0 selected occurrence")["evidence_id"])
                for value in _sequence(item.get("selected_occurrences"), "R0 selected")
            ]
    return result


def _load_scorer(
    root: Path,
    gold_path: Path,
    proof_path: Path,
    attribution_path: Path,
) -> dict[str, Any]:
    if sha256_file(gold_path) != GOLD_SHA256 or sha256_file(proof_path) != PROOF_SHA256:
        raise DG26ExperimentError("DG26_SCORER_REGISTRY_IDENTITY_DRIFT")
    gold = _object(gold_path)
    proof = _object(proof_path)
    if (
        gold.get("schema_version") != "gold-equivalence-registry-v0.1"
        or proof.get("schema_version") != "proof-obligation-registry-v0.1"
        or gold.get("scorer_only") is not True
        or proof.get("scorer_only") is not True
    ):
        raise DG26ExperimentError("DG26_SCORER_REGISTRY_SCHEMA_DRIFT")
    groups: dict[tuple[str, str, str], str] = {}
    for query in _sequence(gold.get("queries"), "gold queries"):
        query_row = _mapping(query, "gold query")
        query_id = str(query_row["query_id"])
        for requirement in _sequence(query_row.get("requirements"), "gold requirements"):
            requirement_row = _mapping(requirement, "gold requirement")
            requirement_id = str(requirement_row["requirement_id"])
            for role in _sequence(requirement_row.get("evidence_roles"), "evidence roles"):
                role_row = _mapping(role, "evidence role")
                for group in _sequence(role_row.get("equivalence_groups"), "groups"):
                    group_row = _mapping(group, "equivalence group")
                    key = (
                        query_id,
                        requirement_id,
                        str(group_row["equivalence_group_id"]),
                    )
                    groups[key] = _canonical_source_ref(str(group_row["source_turn_ref"]))
    obligations: set[tuple[str, str, str]] = set()
    for query in _sequence(proof.get("queries"), "proof queries"):
        query_row = _mapping(query, "proof query")
        query_id = str(query_row["query_id"])
        for requirement in _sequence(query_row.get("requirements"), "proof requirements"):
            requirement_row = _mapping(requirement, "proof requirement")
            requirement_id = str(requirement_row["requirement_id"])
            for obligation in _sequence(requirement_row.get("obligations"), "obligations"):
                obligation_row = _mapping(obligation, "proof obligation")
                obligations.add((query_id, requirement_id, str(obligation_row["obligation_id"])))
    attribution = _array(attribution_path)
    authorized_absence = {
        str(item["equivalence_group_id"])
        for value in attribution
        if (item := _mapping(value, "loss attribution")).get("authorized_absence") is True
    }
    if len(groups) != 23 or len(obligations) != 37:
        raise DG26ExperimentError("DG26_SCORER_DENOMINATOR_DRIFT")
    return {
        "groups": groups,
        "obligations": obligations,
        "authorized_absence": authorized_absence,
        "identities": {
            "gold_registry": _identity(root, gold_path),
            "proof_registry": _identity(root, proof_path),
            "attribution": _identity(root, attribution_path),
        },
    }


def _score_all(
    inputs: ExperimentInputs,
    evaluations: Mapping[str, ArmEvaluation],
    scorer: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    groups = cast(dict[tuple[str, str, str], str], scorer["groups"])
    hits: dict[str, dict[str, set[tuple[str, str, str]]]] = {}
    scores: dict[str, dict[str, Any]] = {}
    for arm in ARM_ORDER:
        score, arm_hits = _score_arm(evaluations[arm].records, groups)
        scores[arm] = score
        hits[arm] = arm_hits
    pool_sources = {
        key: {_canonical_source_ref(str(item["source_ref"])) for item in pool.candidates}
        for key, pool in inputs.pools.items()
    }
    absent = cast(set[str], scorer["authorized_absence"])
    residual = {
        group
        for group, source in groups.items()
        if group not in hits["R0"]["binding"]
        and group[2] not in absent
        and source in pool_sources[(group[0], group[1])]
    }
    baseline_binding = hits["R0"]["binding"]
    for arm in ARM_ORDER:
        binding = hits[arm]["binding"]
        scores[arm]["target_requirement_binding_gain"] = len(binding) - len(baseline_binding)
        scores[arm]["residual_groups_recovered"] = len(binding.intersection(residual))
        scores[arm]["baseline_correct_groups_lost"] = len(baseline_binding.difference(binding))
        scores[arm]["recovered_group_ids"] = sorted(item[2] for item in binding.intersection(residual))
        scores[arm]["lost_group_ids"] = sorted(item[2] for item in baseline_binding.difference(binding))
    residual_rows = [
        {
            "query_id": group[0],
            "requirement_id": group[1],
            "equivalence_group_id": group[2],
            "r0_first_loss": "NOT_BINDING_COVERED_AT_FIXED_K",
        }
        for group in sorted(residual)
    ]
    return scores, residual_rows


def _score_arm(
    records: Mapping[tuple[str, str], list[dict[str, Any]]],
    groups: Mapping[tuple[str, str, str], str],
) -> tuple[dict[str, Any], dict[str, set[tuple[str, str, str]]]]:
    candidate_hits: set[tuple[str, str, str]] = set()
    binding_hits: set[tuple[str, str, str]] = set()
    all_match: set[tuple[str, str, str]] = set()
    accepted_match: set[tuple[str, str, str]] = set()
    expected_by_requirement: dict[tuple[str, str], set[str]] = {}
    for group, source in groups.items():
        expected_by_requirement.setdefault(group[:2], set()).add(source)
    for key, selected in records.items():
        expected = expected_by_requirement[key]
        for item in selected:
            source = _canonical_source_ref(str(item["source_ref"]))
            if item.get("binding_status") == "MATCH":
                binding_key = (key[0], key[1], source)
                all_match.add(binding_key)
                if source in expected:
                    accepted_match.add(binding_key)
    for group, source in groups.items():
        selected = records[group[:2]]
        for item in selected:
            if _canonical_source_ref(str(item["source_ref"])) != source:
                continue
            candidate_hits.add(group)
            if item.get("binding_status") == "MATCH":
                binding_hits.add(group)
            break
    ready_queries = 0
    for query_id in sorted({group[0] for group in groups}):
        required = {group for group in groups if group[0] == query_id}
        if required.issubset(binding_hits):
            ready_queries += 1
    precision = len(accepted_match) / len(all_match) if all_match else 1.0
    return (
        {
            "target_requirement_candidate_recall_at_8": len(candidate_hits) / len(groups),
            "candidate_groups": len(candidate_hits),
            "required_evidence_role_coverage_at_8": len(binding_hits) / len(groups),
            "covered_groups": len(binding_hits),
            "accepted_binding_precision": precision,
            "accepted_binding_count": len(accepted_match),
            "all_match_binding_count": len(all_match),
            "selection_ready_queries": ready_queries,
            "operator_ready_queries": 0,
            "operator_ready_reason": "PROOF_OBLIGATIONS_NOT_EXECUTED_IN_RANKING_ONLY_GOAL",
            "wrong_complete": 0,
            "acquisition_calls": 0,
        },
        {"candidate": candidate_hits, "binding": binding_hits},
    )


def _safe_records(
    inputs: ExperimentInputs,
    records: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key in inputs.order:
        selected: list[dict[str, Any]] = []
        for final_rank, item in enumerate(records[key], start=1):
            metadata = item.get("reranker")
            selected.append(
                {
                    "final_rank": final_rank,
                    "baseline_rank": int(item["raw_rank"]),
                    "evidence_id": str(item["evidence_id"]),
                    "source_turn_ref": str(item["source_ref"]),
                    "content_hash": str(item["content_hash"]),
                    "binding_status": str(item["binding_status"]),
                    "model_score": (
                        float(metadata["score"])
                        if isinstance(metadata, Mapping)
                        and isinstance(metadata.get("score"), (int, float))
                        and not isinstance(metadata.get("score"), bool)
                        else None
                    ),
                }
            )
        result.append(
            {
                "query_id": key[0],
                "requirement_id": key[1],
                "candidate_pool_digest": inputs.pools[key].pool_digest,
                "pool_size": len(inputs.pools[key].candidates),
                "selection_cutoff_k": 8,
                "sufficiency": (
                    "PARTIAL"
                    if any(item["binding_status"] == "MATCH" for item in selected)
                    else "UNSATISFIED"
                ),
                "selected": selected,
            }
        )
    return result


def _error_analysis(scores: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        arm: {
            "recovered_group_ids": list(scores[arm]["recovered_group_ids"]),
            "lost_group_ids": list(scores[arm]["lost_group_ids"]),
        }
        for arm in ARM_ORDER
    }


def _canonical_source_ref(value: str) -> str:
    matched = _LONGMEM_SOURCE_REF.match(value)
    if matched is None:
        return value.split("?", maxsplit=1)[0]
    case_id, session_ordinal, session_id, turn_ordinal = matched.groups()
    return (
        f"{unquote(case_id)}:s{session_ordinal}:"
        f"{unquote(session_id)}:t{turn_ordinal}"
    )


def _verify_identity(root: Path, identity: Mapping[str, Any]) -> None:
    path = identity.get("path")
    digest = identity.get("sha256")
    size = identity.get("size")
    if isinstance(path, str) and isinstance(digest, str) and isinstance(size, int):
        _verify_named_identity(root, path, digest, size)


def _verify_named_identity(root: Path, path: str, digest: str, size: int) -> None:
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    if not target.is_file() or target.stat().st_size != size or sha256_file(target) != digest:
        raise DG26ExperimentError(f"DG26_SOURCE_IDENTITY_DRIFT:{path}")


def _identity(root: Path, path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        label = str(resolved.relative_to(root.resolve()))
    except ValueError:
        label = str(resolved)
    return {"path": label, "sha256": sha256_file(resolved), "size": resolved.stat().st_size}


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG26ExperimentError(f"DG26_JSON_OBJECT_REQUIRED:{path}")
    return value


def _array(path: Path) -> list[Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise DG26ExperimentError(f"DG26_JSON_ARRAY_REQUIRED:{path}")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG26ExperimentError(f"DG26_MAPPING_REQUIRED:{label}")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DG26ExperimentError(f"DG26_SEQUENCE_REQUIRED:{label}")
    return value


__all__ = [
    "ARM_ORDER",
    "DG26ExperimentError",
    "ExperimentInputs",
    "derive_decision",
    "deterministic_projection",
    "execute_once",
    "load_experiment_inputs",
    "load_run_lock",
    "sha256_file",
]
