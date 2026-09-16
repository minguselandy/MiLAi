"""Freeze identities and execution policy for the one LongMemEval full run."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.dg14.provider import full_provider_contract_sha256
from evals.paper.datasets.longmemeval import load_inputs
from evals.paper.scorers.longmemeval import SCORER_ID

from .longmemeval_contract import (
    ANSWER_MAX_TOKENS,
    ANSWER_WORKERS,
    ARM_MODES,
    ARMS,
    BARRIER_TIMEOUT_MS,
    BENCHMARK_ROOT,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CASE_COUNT,
    DATASET_PATH,
    GLOBAL_WORKER_CEILING,
    INPUT_PATH,
    JUDGE_MAX_TOKENS,
    JUDGE_WORKERS,
    MAX_RESULTS,
    MCP_CONCURRENCY,
    MEMORY_TOKEN_BUDGET,
    MODEL_ID,
    OFFICIAL_EVALUATOR,
    PROJECTION_BATCH_SIZE,
    RETRIEVAL_CASE_COUNT,
    ROOT,
    RUN_ID,
    RUN_ROOT,
    STATEFUL_CASE_TIMEOUT_SECONDS,
    STATEFUL_SHARDS,
    TOKENIZER_PATH,
    VLLM_BASE_URL,
    LongMemEvalClosureError,
    atomic_json,
    canonical_json,
    history_events,
    load_json,
    sha256_file,
    smoke_case_ids,
)

EXPECTED_DATASET_SHA256 = (
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
)
EXPECTED_INPUT_SHA256 = (
    "7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412"
)
EXPECTED_BENCHMARK_COMMIT = "9e0b455f4ef0e2ab8f2e582289761153549043fc"

_IDENTITY_PATHS = (
    "evals/ml_closure/longmemeval_contract.py",
    "evals/ml_closure/longmemeval_contexts.py",
    "evals/ml_closure/longmemeval_providers.py",
    "evals/ml_closure/longmemeval_score.py",
    "evals/ml_closure/longmemeval_freeze.py",
    "evals/ml_closure/run_longmemeval.py",
    "evals/dg15/contracts.py",
    "evals/dg15/mcp_stdio.py",
    "evals/dg15/milai_mcp_adapter.py",
    "evals/dg15/runtime_session.py",
    "evals/dg14/provider.py",
    "evals/paper/datasets/longmemeval.py",
    "evals/paper/scorers/longmemeval.py",
    "integrations/mcp/src/milai_mcp/server.py",
    "runtime/src/milai/application/formation_projection.py",
    "runtime/src/milai/application/formation_generalization.py",
    "runtime/src/milai/application/formation_recollection.py",
    "runtime/src/milai/application/formation_semantic_replay.py",
    "runtime/src/milai/application/memory_context.py",
    "runtime/src/milai/application/memory_formation.py",
    "runtime/src/milai/application/memory_resolve.py",
    "runtime/src/milai/application/retrieval.py",
)


def _command(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _provider_identity() -> dict[str, Any]:
    request = urllib.request.Request(f"{VLLM_BASE_URL}/v1/models", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.loads(response.read())
    except (OSError, json.JSONDecodeError) as exc:
        raise LongMemEvalClosureError(
            "frozen loopback provider is unavailable"
        ) from exc
    raw_models = value.get("data") if isinstance(value, dict) else None
    if not isinstance(raw_models, list) or len(raw_models) != 1:
        raise LongMemEvalClosureError("loopback provider model catalog drifted")
    model = raw_models[0]
    if not isinstance(model, dict) or model.get("id") != MODEL_ID:
        raise LongMemEvalClosureError("loopback provider model identity drifted")
    return {
        "base_url": VLLM_BASE_URL,
        "loopback_only": True,
        "model_id": MODEL_ID,
        "served_model": model,
        "models_response_sha256": hashlib.sha256(canonical_json(value)).hexdigest(),
    }


def _hardware() -> dict[str, Any]:
    physical_pairs: set[tuple[str, str]] = set()
    physical_id = ""
    core_id = ""
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("physical id"):
            physical_id = line.split(":", 1)[1].strip()
        elif line.startswith("core id"):
            core_id = line.split(":", 1)[1].strip()
            physical_pairs.add((physical_id, core_id))
    meminfo = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith(("MemTotal:", "MemAvailable:")):
            key, value, _unit = line.split()
            meminfo[key.rstrip(":")] = int(value)
    gpu_query = _command(
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    )
    return {
        "logical_cpus": os.cpu_count(),
        "physical_cores": len(physical_pairs),
        "memory_kib": meminfo,
        "gpus": [line.strip() for line in gpu_query.splitlines() if line.strip()],
    }


def _migration_head() -> str:
    runtime_src = ROOT / "runtime/src"
    if str(runtime_src) not in sys.path:
        sys.path.insert(0, str(runtime_src))
    from alembic.script import ScriptDirectory
    from milai.operations.smoke import _alembic_config

    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if not isinstance(head, str):
        raise LongMemEvalClosureError("Runtime migration head is ambiguous")
    return head


def build_run_lock() -> dict[str, Any]:
    dataset_sha = sha256_file(DATASET_PATH)
    input_sha = sha256_file(INPUT_PATH)
    if dataset_sha != EXPECTED_DATASET_SHA256 or input_sha != EXPECTED_INPUT_SHA256:
        raise LongMemEvalClosureError("LongMemEval data identity drifted")
    benchmark_commit = _command("git", "rev-parse", "HEAD", cwd=BENCHMARK_ROOT)
    benchmark_dirty = _command("git", "status", "--porcelain", cwd=BENCHMARK_ROOT)
    if benchmark_commit != EXPECTED_BENCHMARK_COMMIT or benchmark_dirty:
        raise LongMemEvalClosureError("LongMemEval source repository identity drifted")
    partition, cases = load_inputs(INPUT_PATH)
    if len(cases) != CASE_COUNT:
        raise LongMemEvalClosureError("LongMemEval QA denominator drifted")
    abstention_count = sum("_abs" in case.source_id for case in cases)
    if CASE_COUNT - abstention_count != RETRIEVAL_CASE_COUNT:
        raise LongMemEvalClosureError("LongMemEval retrieval denominator drifted")
    selected = load_json(RUN_ROOT / "selected-method.json")
    c3 = load_json(RUN_ROOT / "block-c3-terminal.json")
    c4 = load_json(RUN_ROOT / "checkpoints/c4-lifecycle-validation.json")
    program = load_json(RUN_ROOT / "program-run-lock.json")
    if (
        not isinstance(selected, dict)
        or selected.get("selected_arm") != "F"
        or selected.get("representation") != "FORMED_PLUS_RAW_CANONICAL"
        or selected.get("recollection") != "SIMPLE"
        or not isinstance(c3, dict)
        or c3.get("status") != "PASS_C3_PRODUCT_INTEGRATION"
        or not isinstance(c4, dict)
        or c4.get("status") != "PASS_C4_NON_HOLDOUT_LIFECYCLE"
    ):
        raise LongMemEvalClosureError("LongMemEval entry gates are not complete")
    code_hashes = {}
    for relative in _IDENTITY_PATHS:
        path = ROOT / relative
        if not path.is_file():
            raise LongMemEvalClosureError(
                f"run-lock identity file is absent: {relative}"
            )
        code_hashes[relative] = sha256_file(path)
    source_order = [case.source_id for case in cases]
    counts = Counter(case.category for case in cases)
    source_turn_count = sum(
        len(session.turns) for case in cases for session in case.sessions
    )
    empty_source_turn_count = sum(
        not turn.content
        for case in cases
        for session in case.sessions
        for turn in session.turns
    )
    session_count = sum(len(case.sessions) for case in cases)
    encoded_events = {case.source_id: history_events(case) for case in cases}
    ingest_event_count = sum(len(events) for events in encoded_events.values())
    user_event_max = max(
        sum(event.role == "user" for event in events)
        for events in encoded_events.values()
    )
    provider = _provider_identity()
    material: dict[str, Any] = {
        "schema": "milai.memory-lifecycle-longmemeval-run-lock.v0.1",
        "status": "FROZEN_BEFORE_OFFICIAL_SMOKE_AND_FULL_EXECUTION",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "goal_identity": "MILA-ML-CLOSURE@0.2",
        "entry_gates": {
            "c0_c3_complete": True,
            "c3_terminal_digest": c3.get("terminal_digest"),
            "c4_1_non_holdout_lifecycle": "PASS",
            "c4_1_result_digest": c4.get("result_digest"),
            "selected_method_digest": selected.get("selected_method_digest"),
            "flag_off_identity": "PASS",
            "implementation_rollback": "PASS",
            "open_authority_scope_revocation_failure": False,
        },
        "source": {
            "benchmark_root": str(BENCHMARK_ROOT),
            "benchmark_commit": benchmark_commit,
            "benchmark_git_clean": True,
            "official_evaluator": str(OFFICIAL_EVALUATOR),
            "official_evaluator_sha256": sha256_file(OFFICIAL_EVALUATOR),
        },
        "data": {
            "classification": "EXTERNAL_PUBLIC_BENCHMARK",
            "partition": partition,
            "input_path": str(INPUT_PATH),
            "input_sha256": input_sha,
            "dataset_path": str(DATASET_PATH),
            "dataset_sha256": dataset_sha,
            "qa_denominator": CASE_COUNT,
            "retrieval_denominator": RETRIEVAL_CASE_COUNT,
            "abstention_count": abstention_count,
            "session_count": session_count,
            "source_turn_count": source_turn_count,
            "empty_source_turn_count": empty_source_turn_count,
            "ingested_evidence_count": ingest_event_count,
            "max_user_events_per_case": user_event_max,
            "source_order_sha256": hashlib.sha256(
                canonical_json(source_order)
            ).hexdigest(),
            "category_counts": dict(sorted(counts.items())),
            "label_free_input_contract": True,
            "source_case_ids_pseudonymized_before_ingest": True,
        },
        "matched_systems": {
            "arms": list(ARMS),
            "LME-R": "C0_FROZEN_RAW_PLUS_CANONICAL_SIMPLE",
            "LME-C": "C2_FORMED_PLUS_RAW_CANONICAL_SIMPLE",
            "formation_modes": ARM_MODES,
            "candidate_selected_before_external_results": True,
            "representation": "EXACT_NONEMPTY_SOURCE_TURN_EVIDENCE_V1",
            "empty_source_turn_policy": "OMIT_ZERO_INFORMATION_PRESERVE_ORDINALS",
            "turn_session_provenance_preserved": True,
            "formation_subject": "ONE_CASE_LEVEL_SELF_SUBJECT",
            "source_ref_order": "ZERO_PADDED_SESSION_AND_TURN_ORDINAL",
            "same_question_order": True,
            "same_reader": True,
            "same_candidate_token_action_ceilings": True,
        },
        "product_path": {
            "context_execution": "MILAI_MCP_STDIO_TO_RUNTIME",
            "ingest_tool": "milai_evidence_capture",
            "query_tool": "milai_memory_resolve",
            "readiness_tool": "milai_projection_readiness_wait",
            "cleanup_tool": "milai_namespace_cleanup_submit",
            "real_openworker_transport_witness": "C3_SEPARATE_REAL_TRANSPORT_PASS",
            "eval_owned_memory_behavior": False,
        },
        "configuration": {
            "max_results": MAX_RESULTS,
            "memory_token_budget": MEMORY_TOKEN_BUDGET,
            "answer_max_tokens": ANSWER_MAX_TOKENS,
            "judge_max_tokens": JUDGE_MAX_TOKENS,
            "stateful_case_timeout_seconds": STATEFUL_CASE_TIMEOUT_SECONDS,
            "barrier_timeout_ms": BARRIER_TIMEOUT_MS,
            "projection_batch_size": PROJECTION_BATCH_SIZE,
            "mcp_call_retries": 0,
            "case_arm_logical_attempts": 1,
            "identical_transport_retry_ceiling": 1,
            "retry_condition": "NO_RESPONSE_AND_NO_EXTERNAL_SIDE_EFFECT_ONLY",
            "post_result_retuning": False,
            "post_result_rerun": False,
        },
        "concurrency": {
            "stateful": {"processes": STATEFUL_SHARDS, "workers_per_process": 1},
            "mcp_within_case": MCP_CONCURRENCY,
            "cpu_stateless": 8,
            "dense_retrieval": "NOT_RUN_SELECTED_METHOD_HAS_NO_DENSE",
            "answer": ANSWER_WORKERS,
            "judge": JUDGE_WORKERS,
            "global_ceiling": GLOBAL_WORKER_CEILING,
            "answer_and_judge_windows_overlap": False,
            "arms_use_same_schedule": True,
        },
        "provider": {
            **provider,
            "tokenizer_path": str(TOKENIZER_PATH),
            "tokenizer_sha256": sha256_file(TOKENIZER_PATH),
            "answer_prompt_contract_sha256": full_provider_contract_sha256(
                max_output_tokens=ANSWER_MAX_TOKENS
            ),
            "judge_prompt": "UPSTREAM_GET_ANSCHECK_PROMPT_AST_EXACT_BODY",
            "judge_temperature": 0,
            "judge_self_model_bias_disclosed": True,
        },
        "scoring": {
            "deterministic_scorer": SCORER_ID,
            "scorer_sha256": code_hashes["evals/paper/scorers/longmemeval.py"],
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_unit": "question_id",
            "f1_noninferiority_margin": -0.02,
            "ability_accuracy_noninferiority_margin": -0.05,
        },
        "label_boundary": {
            "question_enters_milai_only_at_query": True,
            "answer_fields_enter_ingest_formation_retrieval_context": False,
            "labels_open_after_all_answers_sealed": True,
            "minimum_fields_opened": ["answer", "answer_session_ids"],
            "formal_holdout": "NOT_RUN_NOT_AUTHORIZED",
        },
        "smoke_case_ids": list(smoke_case_ids(cases)),
        "runtime": {
            "main_repo_git_head": _command("git", "rev-parse", "HEAD"),
            "program_run_lock_git_head": program.get("repository_commit_at_activation")
            if isinstance(program, dict)
            else None,
            "migration_head_actual": _migration_head(),
            "program_run_lock_migration_head": program.get("database_identity", {}).get(
                "migration_code_head"
            )
            if isinstance(program, dict)
            and isinstance(program.get("database_identity"), dict)
            else None,
            "program_run_lock_digest": program.get("lock_digest")
            if isinstance(program, dict)
            else None,
            "program_lock_drift_documented_not_mutated": True,
            "database_policy": "FRESH_EPHEMERAL_DATABASE_PER_STATEFUL_LANE",
            "product_database_mutation": False,
            "formation_projection": "PROCESS_LOCAL_NON_DURABLE_DEFAULT_OFF",
            "adr_028": "PROPOSED_NOT_APPROVED",
        },
        "hardware": _hardware(),
        "code_sha256": code_hashes,
        "artifact_policy": {
            "final": [
                "longmemeval-run-lock.json",
                "longmemeval-results.jsonl",
                "longmemeval-summary.json",
                "longmemeval-terminal.json",
            ],
            "case_checkpoints_removed_after_verified_merge": True,
        },
    }
    return {
        **material,
        "run_lock_digest": hashlib.sha256(canonical_json(material)).hexdigest(),
    }


def freeze_run_lock() -> dict[str, Any]:
    path = RUN_ROOT / "longmemeval-run-lock.json"
    if path.exists():
        raise LongMemEvalClosureError("LongMemEval run-lock already exists")
    value = build_run_lock()
    atomic_json(path, value)
    return value


__all__ = ["build_run_lock", "freeze_run_lock"]
