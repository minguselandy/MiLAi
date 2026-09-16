#!/usr/bin/env python3
"""Run the lean DG-27 atomic-role repair effect once.

This successor intentionally keeps the DG-26 candidate pool fixed.  It tests
only two repaired boundaries: typed closed-set completion and atomic evidence
interpretation.  It never calls acquisition, Reader, or canonical mutation.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.adapters.grounded_interpretation_v03 import (
    DG27_V03_SYSTEM_PROMPT,
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
    _case_inputs,
    _proofs_by_case,
    _single_best,
    historical_baseline_accepted_sources,
    historical_wrong_complete_occurrences,
    score_effect,
)

RUN_ID = "dg27-v04-atomic-role-repair-20260830-001"
OUTPUT_DIR = ROOT / "var/dg27/v04" / RUN_ID
RESULTS = OUTPUT_DIR / "results.json"
RECEIPT = OUTPUT_DIR / "receipt.json"
LATEST = ROOT / "var/dg27/v04/latest.json"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
V05_RUN_ID = "dg27-v05-mf03-replay-20260830-001"
V05_OUTPUT_DIR = ROOT / "var/dg27/v05" / V05_RUN_ID


def run() -> dict[str, Any]:
    if OUTPUT_DIR.exists():
        raise RuntimeError("DG27_V04_OUTPUT_ALREADY_EXISTS")
    inputs = load_experiment_inputs(ROOT, ROOT / DG26_LOCK)
    cases = _case_inputs(inputs)
    proofs = _proofs_by_case(ROOT)
    tasks = [
        (case_id, requirement_id)
        for case_id, context in inputs.contexts.items()
        for requirement_id in context.requirement_ids
    ]
    if len(tasks) != 15:
        raise RuntimeError("DG27_V04_REQUIREMENT_DENOMINATOR_DRIFT")

    adapter = LoopbackGroundedInterpretationAdapterV03(
        model_id=MODEL_ID,
        timeout_seconds=120.0,
        max_completion_tokens=8192,
    )

    def interpret(task: tuple[str, str]) -> tuple[str, str, Any]:
        case_id, requirement_id = task
        context = inputs.contexts[case_id]
        requirement = next(
            item
            for item in context.query_ir.requirements
            if item.slot_id == requirement_id
        )
        case = cases[case_id]
        sources = [
            case["source_by_id"][candidate.candidate_id]
            for candidate in case["candidates"]
            if requirement_id in candidate.matched_slots
        ]
        execution = adapter.interpret(
            query=context.query,
            requirement=requirement,
            candidates=sources,
        )
        return case_id, requirement_id, execution

    with ThreadPoolExecutor(max_workers=4) as executor:
        executions = list(executor.map(interpret, tasks))

    model_sets: dict[str, dict[str, Any]] = {}
    model_outputs: list[dict[str, Any]] = []
    usage: list[dict[str, Any]] = []
    for case_id, requirement_id, execution in executions:
        model_sets.setdefault(case_id, {})[requirement_id] = (
            execution.interpretation_sets
        )
        model_outputs.append(
            {
                "case_id": case_id,
                "requirement_id": requirement_id,
                "interpretation_sets": [
                    item.model_dump(mode="json")
                    for item in execution.interpretation_sets
                ],
                "materializations": [
                    item.model_dump(mode="json")
                    for item in execution.materializations
                ],
            }
        )
        usage.append(
            {
                "case_id": case_id,
                "requirement_id": requirement_id,
                "response_id": execution.response_id,
                "prompt_tokens": execution.prompt_tokens,
                "completion_tokens": execution.completion_tokens,
                "latency_ms": round(execution.latency_ms, 3),
                "automatic_retries": execution.automatic_retries,
            }
        )

    arms: dict[str, list[dict[str, Any]]] = {"D1": [], "D2": [], "D3": []}
    for case_id, context in inputs.contexts.items():
        case = cases[case_id]
        common = {
            "plan": context.acquisition_plan,
            "query_ir": context.query_ir,
            "acquisition_capability_digest": case["capability_digest"],
            "candidates": case["candidates"],
            "source_records": list(case["source_by_id"].values()),
            "completion_proof": proofs[case_id],
        }
        decisions = {
            "D1": decide_deterministic_boundary(**common),
            "D2": decide_semantic_boundary(
                **common,
                interpretation_sets_by_requirement=model_sets[case_id],
            ),
            "D3": decide_semantic_boundary(
                **common,
                interpretation_sets_by_requirement={
                    requirement_id: tuple(_single_best(item) for item in values)
                    for requirement_id, values in model_sets[case_id].items()
                },
            ),
        }
        for arm_id, decision in decisions.items():
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
        "D0_replay": historical_wrong_complete_occurrences(ROOT),
        "D0_baseline_accepted_sources": historical_baseline_accepted_sources(ROOT),
        "arms": arms,
        "model_outputs": model_outputs,
        "model_usage": usage,
    }
    unscored_digest = canonical_sha256(unscored)
    gold = _read_object(ROOT / GOLD_REGISTRY)
    scores = score_effect(unscored, gold)
    result: dict[str, Any] = {
        "schema": "milai.dg27.v04.results.v0.4",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "treatment": {
            "candidate_pool": "DG26_FIXED_R0_TOP8_PER_REQUIREMENT",
            "prompt_digest": canonical_sha256(DG27_V03_SYSTEM_PROMPT),
            "completion_policy": "UNRESOLVED_CLOSED_SET_BLOCKS_COMPLETE",
            "semantic_policy": "ATOMIC_EVIDENCE_ROLE",
        },
        "label_boundary": {
            "gold_opened_after_unscored_seal": True,
            "unscored_digest": unscored_digest,
        },
        "unscored": unscored,
        "scores": scores,
        "cost": {
            "model_calls": len(usage),
            "automatic_retries": sum(item["automatic_retries"] for item in usage),
            "prompt_tokens": sum(item["prompt_tokens"] for item in usage),
            "completion_tokens": sum(item["completion_tokens"] for item in usage),
            "aggregate_latency_ms": round(
                sum(item["latency_ms"] for item in usage), 3
            ),
            "acquisition_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
        },
        "formal_holdout_used": False,
    }
    result["results_digest"] = canonical_sha256(result)

    checks = scores["checks"]
    boundary_pass = bool(
        checks["d1_wrong_complete_zero"]
        and checks["d1_correct_group_non_regression"]
    )
    semantic_pass = bool(
        checks["d2_wrong_complete_zero"]
        and checks["d2_known_false_binding_zero"]
        and checks["d2_correct_group_non_regression"]
    )
    receipt: dict[str, Any] = {
        "schema": "milai.dg27.v04.receipt.v0.4",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "results_digest": result["results_digest"],
        "boundary_status": "PASS" if boundary_pass else "FAIL",
        "semantic_status": "PASS" if semantic_pass else "NEEDS_IDENTITY_FORMATION",
        "proceed_to_mf03": boundary_pass,
        "proceed_to_dg28_lite": boundary_pass and semantic_pass,
        "wrong_complete": {
            arm: scores["arms"][arm]["wrong_complete"]
            for arm in ("D1", "D2", "D3")
        },
        "safety": {
            "automatic_retries": result["cost"]["automatic_retries"],
            "acquisition_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
            "feature_flag": "OFF",
        },
    }
    receipt["receipt_digest"] = canonical_sha256(receipt)
    OUTPUT_DIR.mkdir(parents=True)
    _write(RESULTS, result)
    _write(RECEIPT, receipt)
    _write(LATEST, receipt)
    return receipt


def replay_with_current_runtime() -> dict[str, Any]:
    """Reuse sealed V04 model outputs after Runtime/MF-03 repairs."""

    if V05_OUTPUT_DIR.exists():
        raise RuntimeError("DG27_V05_OUTPUT_ALREADY_EXISTS")
    prior = _read_object(RESULTS)
    inputs = load_experiment_inputs(ROOT, ROOT / DG26_LOCK)
    cases = _case_inputs(inputs)
    proofs = _proofs_by_case(ROOT)
    model_sets: dict[str, dict[str, tuple[SemanticInterpretationSetV02, ...]]] = {}
    for output in prior["unscored"]["model_outputs"]:
        model_sets.setdefault(output["case_id"], {})[output["requirement_id"]] = tuple(
            SemanticInterpretationSetV02.model_validate(item)
            for item in output["interpretation_sets"]
        )

    arms: dict[str, list[dict[str, Any]]] = {"D1": [], "D2": [], "D3": []}
    for case_id, context in inputs.contexts.items():
        case = cases[case_id]
        common = {
            "plan": context.acquisition_plan,
            "query_ir": context.query_ir,
            "acquisition_capability_digest": case["capability_digest"],
            "candidates": case["candidates"],
            "source_records": list(case["source_by_id"].values()),
            "completion_proof": proofs[case_id],
        }
        decisions = {
            "D1": decide_deterministic_boundary(**common),
            "D2": decide_semantic_boundary(
                **common,
                interpretation_sets_by_requirement=model_sets[case_id],
            ),
            "D3": decide_semantic_boundary(
                **common,
                interpretation_sets_by_requirement={
                    requirement_id: tuple(_single_best(item) for item in values)
                    for requirement_id, values in model_sets[case_id].items()
                },
            ),
        }
        for arm_id, decision in decisions.items():
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
    prior_unscored = prior["unscored"]
    unscored = {**prior_unscored, "arms": arms}
    scores = score_effect(unscored, _read_object(ROOT / GOLD_REGISTRY))
    result: dict[str, Any] = {
        "schema": "milai.dg27.v05.results.v0.5",
        "run_id": V05_RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "source_model_output_digest": prior["label_boundary"]["unscored_digest"],
        "source_v04_results_digest": prior["results_digest"],
        "model_calls": 0,
        "treatment": [
            "UNRESOLVED_CLOSED_SET_BLOCKS_COMPLETE",
            "MODEL_ADDITIVE_DETERMINISTIC_FALLBACK",
            "MF03_EVENT_IDENTITY_REPRESENTATIVE_SELECTION",
        ],
        "unscored": unscored,
        "scores": scores,
        "safety": {
            "automatic_retries": 0,
            "acquisition_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
            "formal_holdout_used": False,
            "feature_flag": "OFF",
        },
    }
    result["results_digest"] = canonical_sha256(result)
    checks = scores["checks"]
    passed = all(
        checks[key]
        for key in (
            "d1_wrong_complete_zero",
            "d1_correct_group_non_regression",
            "d2_wrong_complete_zero",
            "d2_known_false_binding_zero",
            "d2_correct_group_non_regression",
        )
    )
    receipt: dict[str, Any] = {
        "schema": "milai.dg27.v05.receipt.v0.5",
        "run_id": V05_RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS_DECISION_BOUNDARY_REPAIRED" if passed else "FAIL",
        "results_digest": result["results_digest"],
        "model_calls": 0,
        "wrong_complete": {
            arm: scores["arms"][arm]["wrong_complete"]
            for arm in ("D1", "D2", "D3")
        },
        "d2_accepted_binding_precision": scores["arms"]["D2"][
            "accepted_binding_precision"
        ],
        "d2_baseline_correct_groups_lost": scores["arms"]["D2"][
            "baseline_correct_groups_lost"
        ],
        "proceed_to_dg28_lite": passed,
        "safety": result["safety"],
    }
    receipt["receipt_digest"] = canonical_sha256(receipt)
    V05_OUTPUT_DIR.mkdir(parents=True)
    _write(V05_OUTPUT_DIR / "results.json", result)
    _write(V05_OUTPUT_DIR / "receipt.json", receipt)
    _write(ROOT / "var/dg27/v05/latest.json", receipt)
    return receipt


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in {"run", "replay"}:
        raise SystemExit("usage: run_dg27_v04_repair.py [run|replay]")
    output = run() if command == "run" else replay_with_current_runtime()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
