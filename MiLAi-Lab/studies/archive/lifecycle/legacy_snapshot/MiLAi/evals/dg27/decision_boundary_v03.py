"""DG-27 V03 matched effect using quote-grounded local materialization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from milai.adapters.grounded_interpretation_v03 import (
    GroundedInterpretationExecutionV03,
    LoopbackGroundedInterpretationAdapterV03,
)
from milai.application.decision_boundary import (
    decide_deterministic_boundary,
    decide_semantic_boundary,
)
from milai.domain.decision_boundary import SemanticInterpretationSetV02
from milai.domain.requirement_state import canonical_sha256

from evals.dg26.stateview_reranking import load_experiment_inputs
from evals.dg27.decision_boundary import (
    DG26_LOCK,
    GOLD_REGISTRY,
    _candidate_manifest,
    _case_inputs,
    _proofs_by_case,
    _single_best,
    historical_baseline_accepted_sources,
    historical_wrong_complete_occurrences,
    score_effect,
)


class DG27V03EffectError(RuntimeError):
    """The V03 freeze or matched-effect identity is invalid."""


def load_v03_run_lock(root: Path, path: Path) -> dict[str, Any]:
    """Validate the superseding V03 lock and every bound file identity."""

    root = root.resolve()
    lock = _object(path)
    if lock.get("schema") != "milai.dg27.v03.run-lock.v0.3":
        raise DG27V03EffectError("DG27_V03_RUN_LOCK_SCHEMA_DRIFT")
    material = dict(lock)
    observed = material.pop("lock_digest", None)
    if observed != canonical_sha256(material):
        raise DG27V03EffectError("DG27_V03_RUN_LOCK_DIGEST_MISMATCH")
    if lock.get("config_digest") != canonical_sha256(lock.get("config")):
        raise DG27V03EffectError("DG27_V03_CONFIG_DIGEST_MISMATCH")
    for identity in _sequence(lock.get("bound_identities"), "bound identities"):
        _verify_identity(root, _mapping(identity, "bound identity"))
    budget = _mapping(lock.get("budget"), "budget")
    safety = _mapping(lock.get("safety"), "safety")
    canary = _mapping(lock.get("canary"), "canary")
    if (
        canary.get("status") != "PASS"
        or safety.get("candidate_feature_flag") != "OFF"
        or safety.get("canonical_mutations") != 0
        or lock.get("formal_holdout_used") is not False
        or budget.get("automatic_retries") != 0
        or budget.get("effect_model_calls") != 15
        or budget.get("initial_concurrency") != 4
    ):
        raise DG27V03EffectError("DG27_V03_SAFETY_BOUNDARY_DRIFT")
    return lock


def execute_v03_effect(
    root: Path,
    run_lock_path: Path,
    *,
    adapter: LoopbackGroundedInterpretationAdapterV03,
) -> dict[str, Any]:
    """Execute the frozen 15 calls once, seal outputs, and then score."""

    root = root.resolve()
    lock = load_v03_run_lock(root, run_lock_path)
    inputs = load_experiment_inputs(root, root / DG26_LOCK)
    cases = _case_inputs(inputs)
    manifest = _candidate_manifest(cases)
    snapshot = _mapping(lock.get("candidate_snapshot"), "candidate snapshot")
    if canonical_sha256(manifest) != snapshot.get("manifest_digest"):
        raise DG27V03EffectError("DG27_V03_CANDIDATE_SNAPSHOT_DRIFT")

    tasks: list[tuple[str, str]] = []
    for case_id, context in inputs.contexts.items():
        tasks.extend((case_id, requirement_id) for requirement_id in context.requirement_ids)
    if len(tasks) != 15:
        raise DG27V03EffectError("DG27_V03_REQUIREMENT_DENOMINATOR_DRIFT")

    def interpret(task: tuple[str, str]) -> tuple[str, str, GroundedInterpretationExecutionV03]:
        case_id, requirement_id = task
        context = inputs.contexts[case_id]
        requirement_by_id = {
            item.slot_id: item for item in context.query_ir.requirements
        }
        source_records = [
            cases[case_id]["source_by_id"][item.candidate_id]
            for item in cases[case_id]["candidates"]
            if requirement_id in item.matched_slots
        ]
        execution = adapter.interpret(
            query=context.query,
            requirement=requirement_by_id[requirement_id],
            candidates=source_records,
        )
        return case_id, requirement_id, execution

    concurrency = int(_mapping(lock.get("budget"), "budget")["initial_concurrency"])
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        executions = list(executor.map(interpret, tasks))

    model_sets: dict[str, dict[str, tuple[SemanticInterpretationSetV02, ...]]] = {}
    model_usage: list[dict[str, Any]] = []
    local_materializations: list[dict[str, Any]] = []
    for case_id, requirement_id, execution in executions:
        model_sets.setdefault(case_id, {})[requirement_id] = execution.interpretation_sets
        model_usage.append(_usage(case_id, requirement_id, execution))
        local_materializations.extend(
            {
                "case_id": case_id,
                **item.model_dump(mode="json"),
            }
            for item in execution.materializations
        )

    proof_by_case = _proofs_by_case(root)
    arms: dict[str, list[dict[str, Any]]] = {"D1": [], "D2": [], "D3": []}
    for case_id, context in inputs.contexts.items():
        case = cases[case_id]
        common = {
            "plan": context.acquisition_plan,
            "query_ir": context.query_ir,
            "acquisition_capability_digest": case["capability_digest"],
            "candidates": case["candidates"],
            "source_records": list(case["source_by_id"].values()),
            "completion_proof": proof_by_case[case_id],
        }
        d1 = decide_deterministic_boundary(**common)
        d2 = decide_semantic_boundary(
            **common,
            interpretation_sets_by_requirement=model_sets[case_id],
        )
        d3 = decide_semantic_boundary(
            **common,
            interpretation_sets_by_requirement={
                requirement_id: tuple(_single_best(item) for item in values)
                for requirement_id, values in model_sets[case_id].items()
            },
        )
        for arm_id, decision in (("D1", d1), ("D2", d2), ("D3", d3)):
            arms[arm_id].append(
                {
                    "case_id": case_id,
                    "decision": decision.model_dump(mode="json"),
                    "accepted_sources": [
                        {
                            "requirement_id": item.requirement_id,
                            "evidence_id": item.evidence_id,
                            "source_ref": str(
                                case["source_by_id"][item.evidence_id]["source_ref"]
                            ),
                        }
                        for item in decision.accepted_bindings
                    ],
                }
            )

    unscored = {
        "arm_order": ["D0", "D1", "D2", "D3"],
        "D0_replay": historical_wrong_complete_occurrences(root),
        "D0_baseline_accepted_sources": historical_baseline_accepted_sources(root),
        "arms": arms,
        "model_usage": model_usage,
        "local_materializations": local_materializations,
    }
    unscored_seal_digest = canonical_sha256(unscored)
    scores = score_effect(unscored, _object(root / GOLD_REGISTRY))
    dispositions = {
        name: sum(item["disposition"] == name for item in local_materializations)
        for name in ("VALID", "REJECTED_PROTOCOL", "DOWNGRADED_UNRESOLVED")
    }
    output: dict[str, Any] = {
        "schema": "milai.dg27.v03.results.v0.3",
        "goal_id": "DG-27",
        "run_id": lock["run_id"],
        "run_lock_digest": lock["lock_digest"],
        "arm_order": ["D0", "D1", "D2", "D3"],
        "label_boundary": {
            "model_visible_gold_labels": 0,
            "gold_registry_open_phase": "POST_D0_D3_OUTPUT_SEAL",
            "unscored_output_seal_digest": unscored_seal_digest,
            "registry_open_count": 1,
        },
        "unscored": unscored,
        "scores": scores,
        "materialization_summary": dispositions,
        "cost": {
            "current_canary_model_calls": 1,
            "prior_canary_model_calls": 2,
            "prior_invalid_effect_requests_submitted": 30,
            "effect_model_calls": len(model_usage),
            "cumulative_model_requests": len(model_usage) + 33,
            "interpreted_candidate_occurrences": sum(
                len(row["candidates"]) for row in manifest
            ),
            "final_validation_calls": 30,
            "prompt_tokens": sum(int(item["prompt_tokens"]) for item in model_usage),
            "completion_tokens": sum(
                int(item["completion_tokens"]) for item in model_usage
            ),
            "latency_ms": round(
                sum(float(item["latency_ms"]) for item in model_usage), 3
            ),
            "automatic_retries": sum(
                int(item["automatic_retries"]) for item in model_usage
            ),
            "acquisition_calls": 0,
            "reader_calls": 0,
            "concurrency": concurrency,
        },
        "safety": {
            "canonical_mutations": 0,
            "authority_violations": 0,
            "candidate_feature_flag": "OFF",
            "formal_holdout_used": False,
        },
    }
    output["results_digest"] = canonical_sha256(output)
    return output


def _usage(
    case_id: str,
    requirement_id: str,
    execution: GroundedInterpretationExecutionV03,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "requirement_id": requirement_id,
        "model_id": execution.model_id,
        "response_id": execution.response_id,
        "prompt_tokens": execution.prompt_tokens,
        "completion_tokens": execution.completion_tokens,
        "latency_ms": round(execution.latency_ms, 3),
        "automatic_retries": execution.automatic_retries,
    }


def _verify_identity(root: Path, identity: Mapping[str, Any]) -> None:
    path = root / str(identity["path"])
    if (
        not path.is_file()
        or path.stat().st_size != int(identity["size"])
        or _sha256_file(path) != identity["sha256"]
    ):
        raise DG27V03EffectError(f"DG27_V03_BOUND_IDENTITY_DRIFT:{identity['path']}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG27V03EffectError(f"DG27_V03_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG27V03EffectError(f"DG27_V03_MAPPING_REQUIRED:{source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DG27V03EffectError(f"DG27_V03_SEQUENCE_REQUIRED:{source}")
    return value


__all__ = ["DG27V03EffectError", "execute_v03_effect", "load_v03_run_lock"]
