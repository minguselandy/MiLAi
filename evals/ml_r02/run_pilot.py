"""User-limited ML-R02 LongMemEval-S 8-case x 4-arm repair/resume execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from evals.dg23.reader_token_accounting import FrozenReaderTokenCounter
from evals.ml_closure.longmemeval_contexts import ContextExecutionSpec
from evals.ml_repair import mlr01_r4_contexts as legacy_contexts
from evals.ml_repair import mlr01_r4_providers as legacy_providers
from evals.ml_repair import mlr01_r4_score as legacy_score
from evals.ml_repair.mlr01_r4_contract import (
    DATASET_PATH,
    EXPECTED_DATASET_SHA256,
    EXPECTED_INPUT_SHA256,
    INPUT_PATH,
    canonical_sha256,
    load_all_cases,
    load_json,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[2]
GOAL_PATH = ROOT / "MiLAi_ML-R02_统一MemoryLifecycle架构收敛与LongMemEval验证_GOALS.md"
RUN_ID = "ml-r02-20260831-004"
REQUEST_IDENTITY_RUN_ID = "ml-r02-20260831-003"
RUN_ROOT = ROOT / "var/ml_r02" / RUN_ID
CHECKPOINT_ROOT = RUN_ROOT / "checkpoints" / "pilot-8"
CELL_ROOT = CHECKPOINT_ROOT / "cells"
CAPABILITY_PATH = CHECKPOINT_ROOT / "capability-seal.json"
ENV_SPEC_PATH = ROOT / ".aris/compute/ml-r02-8x4-local-spec.json"
ENV_LEDGER_PATH = ROOT / ".aris/compute/ml-r02-8x4-local.md"
PREDECESSOR_ROOT = ROOT / "var/ml_repair/ml-r01-20260831-001/checkpoints/r4"
PREDECESSOR_SEAL = PREDECESSOR_ROOT / "context-seal-8.json"
PREDECESSOR_CAPABILITY = PREDECESSOR_ROOT / "capability-identity-seal.json"
RESUME_RUN_ID = "ml-r02-20260831-003"
RESUME_ROOT = ROOT / "var/ml_r02" / RESUME_RUN_ID / "checkpoints" / "pilot-8"
RESUME_CAPABILITY = RESUME_ROOT / "capability-seal.json"
RESUME_CONTEXT_SEAL = RESUME_ROOT / "context-seal-8.json"
RESUME_ANSWER_SEAL = RESUME_ROOT / "answer-seal-8.json"

SCHEMA_VERSION = "milai.ml-r02.pilot-8.v1"
GOAL_SHA256 = "7b1c9bcdd6221c8fdfa52b12323f54fce93ee5ff203fe53a76b1510502aca1c3"
ARMS = ("MLR02-BM25-T", "MLR02-DENSE", "MLR02-R", "MLR02-F")
PRODUCT_ARMS = ("MLR02-R", "MLR02-F")
BASELINE_REUSE = {
    "MLR02-BM25-T": "MLR01-BM25-T",
    "MLR02-DENSE": "MLR01-DENSE",
}
RAW_ARM = "MLR02-R"
FORMED_ARM = "MLR02-F"
TARGET_COUNT = 8
MEMORY_TOKEN_BUDGET = 1_024
ANSWER_MAX_TOKENS = 500
JUDGE_MAX_TOKENS = 10
ANSWER_WORKERS = 8
JUDGE_WORKERS = 8
STATEFUL_SHARDS = 4
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_BASE_URL = "http://127.0.0.1:7860"
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_831
SCOPE_DIGEST = canonical_sha256(
    {"scope": "FIRST_8_CASES_X_4_ARMS_THEN_STOP", "formal_targets": False}
)


class MLR02PilotError(RuntimeError):
    pass


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def target_cases(_target_count: int = TARGET_COUNT):  # type: ignore[no-untyped-def]
    _partition, cases = load_all_cases()
    return tuple(cases[:TARGET_COUNT])


def target_case_ids(_target_count: int = TARGET_COUNT) -> tuple[str, ...]:
    return tuple(case.source_id for case in target_cases())


def context_path(arm: str, case_id: str) -> Path:
    if arm not in ARMS:
        raise ValueError("ML-R02 arm is invalid")
    return CELL_ROOT / "contexts" / arm / f"{case_id}.json"


def product_pair_path(case_id: str) -> Path:
    return CELL_ROOT / "product-pairs" / f"{case_id}.json"


def answer_path(arm: str, case_id: str) -> Path:
    if arm not in ARMS:
        raise ValueError("ML-R02 arm is invalid")
    return CELL_ROOT / "answers" / arm / f"{case_id}.json"


def judge_path(arm: str, case_id: str) -> Path:
    if arm not in ARMS:
        raise ValueError("ML-R02 arm is invalid")
    return CELL_ROOT / "judges" / arm / f"{case_id}.json"


def stage_seal_path(stage: str, target_count: int = TARGET_COUNT) -> Path:
    if stage not in {"context", "answer", "judge", "score"} or target_count != TARGET_COUNT:
        raise ValueError("ML-R02 pilot stage is invalid")
    return CHECKPOINT_ROOT / f"{stage}-seal-8.json"


def records_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    return canonical_sha256(
        sorted(
            (dict(record) for record in records),
            key=lambda value: (str(value.get("case_id")), str(value.get("arm"))),
        )
    )


def case_seed(case_id: str, lane: str) -> int:
    digest = hashlib.sha256(
        f"{REQUEST_IDENTITY_RUN_ID}:pilot-8:{lane}:{case_id}:{MEMORY_TOKEN_BUDGET}".encode()
    ).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def capability_seal_digest() -> str:
    value = load_json(CAPABILITY_PATH)
    if not isinstance(value, dict):
        raise MLR02PilotError("capability seal is invalid")
    claimed = value.get("seal_digest")
    observed = canonical_sha256({k: v for k, v in value.items() if k != "seal_digest"})
    code = value.get("code_sha256")
    if (
        claimed != observed
        or value.get("status") != "FROZEN"
        or value.get("goal_sha256") != GOAL_SHA256
        or not isinstance(code, dict)
        or any(
            not isinstance(path, str)
            or not isinstance(digest, str)
            or not (ROOT / path).is_file()
            or sha256_file(ROOT / path) != digest
            for path, digest in code.items()
        )
    ):
        raise MLR02PilotError("capability seal identity drifted")
    return str(claimed)


def valid_terminal(
    path: Path,
    *,
    schema_suffix: str,
    arm: str,
    case_id: str,
    seal_digest: str,
) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    value = load_json(path)
    if (
        not isinstance(value, dict)
        or value.get("schema") != f"{SCHEMA_VERSION}.{schema_suffix}-terminal"
        or value.get("arm") != arm
        or value.get("case_id") != case_id
        or value.get("capability_seal_digest") != seal_digest
        or value.get("terminal_status") not in {"SUCCEEDED", "FAILED"}
    ):
        return None
    return value


def require_stage_seal(stage: str, target_count: int = TARGET_COUNT) -> dict[str, Any]:
    value = load_json(stage_seal_path(stage, target_count))
    accepted_status = "PASS_PILOT_ONLY" if stage == "score" else "PASS"
    if (
        not isinstance(value, dict)
        or value.get("schema") != f"{SCHEMA_VERSION}.{stage}-seal"
        or value.get("target_count") != TARGET_COUNT
        or value.get("capability_seal_digest") != capability_seal_digest()
        or value.get("terminal_count") != TARGET_COUNT * len(ARMS)
        or value.get("status") != accepted_status
    ):
        raise MLR02PilotError(f"{stage} seal is absent or invalid")
    return value


def _provider_identity() -> dict[str, object]:
    request = urllib.request.Request(f"{VLLM_BASE_URL}/v1/models", method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        value = json.loads(response.read())
    models = value.get("data") if isinstance(value, dict) else None
    if (
        not isinstance(models, list)
        or len(models) != 1
        or not isinstance(models[0], dict)
        or models[0].get("id") != MODEL_ID
    ):
        raise MLR02PilotError("Qwen provider identity drifted")
    return {"base_url": VLLM_BASE_URL, "model_id": MODEL_ID, "catalog_size": 1}


def _code_identity() -> dict[str, str]:
    paths = (
        "evals/ml_r02/run_pilot.py",
        "evals/dg14/provider.py",
        "evals/dg23/reader_token_accounting.py",
        "evals/ml_repair/mlr01_r4_contexts.py",
        "evals/ml_repair/mlr01_r4_providers.py",
        "evals/ml_repair/mlr01_r4_score.py",
        "evals/ml_closure/longmemeval_contexts.py",
        "evals/dg14/benchmark.py",
        "runtime/src/milai/application/decision_engine.py",
        "runtime/src/milai/application/evidence_acquisition.py",
        "runtime/src/milai/application/formation_engine.py",
        "runtime/src/milai/application/formation_projection.py",
        "runtime/src/milai/application/memory_query.py",
        "runtime/src/milai/application/retrieval.py",
        "runtime/src/milai/application/sufficiency.py",
        "runtime/src/milai/adapters/blob_store.py",
        "runtime/src/milai/config/settings.py",
        "runtime/src/milai/domain/retrieval_audit.py",
        "runtime/src/milai/persistence/projection_repository.py",
        "runtime/src/milai/workers/main.py",
        "runtime/migrations/versions/0049_namespace_cleanup_terminal_counts.py",
    )
    return {path: sha256_file(ROOT / path) for path in paths}


def _validate_reusable_baseline_predecessor() -> dict[str, Any]:
    """Validate only the frozen baseline cells authorized for digest reuse.

    ML-R01's overall pilot seal failed on product-runtime/resource gates. Those
    failures cannot taint or be silently converted into a pass, but they also
    do not invalidate the independently terminal BM25/DENSE context cells.
    """
    capability = load_json(PREDECESSOR_CAPABILITY)
    seal = load_json(PREDECESSOR_SEAL)
    if not isinstance(capability, dict) or not isinstance(seal, dict):
        raise MLR02PilotError("ML-R01 baseline predecessor artifacts are invalid")
    source_seal_digest = capability.get("seal_digest")
    if (
        capability.get("status") != "FROZEN"
        or not isinstance(source_seal_digest, str)
        or source_seal_digest
        != canonical_sha256({k: v for k, v in capability.items() if k != "seal_digest"})
        or seal.get("target_count") != TARGET_COUNT
        or seal.get("terminal_count") != TARGET_COUNT * 4
    ):
        raise MLR02PilotError("ML-R01 baseline predecessor identity is invalid")

    old_arms = ("MLR01-BM25-T", "MLR01-DENSE", "MLR01-R", "MLR01-F")
    all_records: list[dict[str, Any]] = []
    baseline_records: list[dict[str, Any]] = []
    for case_id in target_case_ids():
        for arm in old_arms:
            path = PREDECESSOR_ROOT / "cells" / "contexts" / arm / f"{case_id}.json"
            value = load_json(path)
            if (
                not isinstance(value, dict)
                or value.get("schema") != "milai.ml-r01.r4.v1.context-terminal"
                or value.get("case_id") != case_id
                or value.get("arm") != arm
                or value.get("capability_seal_digest") != source_seal_digest
            ):
                raise MLR02PilotError(f"ML-R01 context identity is invalid: {arm}/{case_id}")
            all_records.append(value)
            if arm in BASELINE_REUSE.values():
                baseline_records.append(value)
    if seal.get("records_digest") != records_sha256(all_records):
        raise MLR02PilotError("ML-R01 context predecessor record digest drifted")
    if len(baseline_records) != TARGET_COUNT * len(BASELINE_REUSE) or any(
        row.get("terminal_status") != "SUCCEEDED"
        or row.get("canonical_authority") is not False
        or row.get("labels_opened_by_context_worker") is not False
        or row.get("answer_or_answer_session_fields_accessed") is not False
        or int(row.get("context_tokens") or 0) > MEMORY_TOKEN_BUDGET
        for row in baseline_records
    ):
        raise MLR02PilotError("ML-R01 reusable baseline cells failed their independent gates")
    return {
        "overall_context_seal_status": seal.get("status"),
        "overall_failure_preserved": seal.get("status") != "PASS",
        "reusable_cell_count": len(baseline_records),
        "reusable_arms": sorted(BASELINE_REUSE.values()),
        "all_reusable_cells_succeeded": True,
        "labels_absent": True,
        "canonical_authority_absent": True,
        "source_capability_seal_digest": source_seal_digest,
        "source_records_digest": seal["records_digest"],
    }


def _resume_context_path(arm: str, case_id: str) -> Path:
    return RESUME_ROOT / "cells" / "contexts" / arm / f"{case_id}.json"


def _resume_answer_path(arm: str, case_id: str) -> Path:
    return RESUME_ROOT / "cells" / "answers" / arm / f"{case_id}.json"


def _validate_repair_resume_source() -> dict[str, Any]:
    capability = load_json(RESUME_CAPABILITY)
    context_seal = load_json(RESUME_CONTEXT_SEAL)
    answer_seal = load_json(RESUME_ANSWER_SEAL)
    if not all(isinstance(value, dict) for value in (capability, context_seal, answer_seal)):
        raise MLR02PilotError("repair/resume source artifacts are invalid")
    source_digest = capability.get("seal_digest")
    if (
        capability.get("status") != "FROZEN"
        or capability.get("run_id") != RESUME_RUN_ID
        or not isinstance(source_digest, str)
        or source_digest
        != canonical_sha256({k: v for k, v in capability.items() if k != "seal_digest"})
        or context_seal.get("status") != "PASS"
        or context_seal.get("target_count") != TARGET_COUNT
        or context_seal.get("terminal_count") != TARGET_COUNT * len(ARMS)
        or context_seal.get("capability_seal_digest") != source_digest
        or answer_seal.get("status") != "FAIL"
        or answer_seal.get("succeeded") != 19
        or answer_seal.get("failed") != 13
        or answer_seal.get("capability_seal_digest") != source_digest
        or (RESUME_ROOT / "labels-opened.json").exists()
    ):
        raise MLR02PilotError("repair/resume source identity or stage state drifted")

    cases = {case.source_id: case for case in target_cases()}
    reader_counter = FrozenReaderTokenCounter()
    contexts: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    for case_id in target_case_ids():
        case = cases[case_id]
        for arm in ARMS:
            context_file = _resume_context_path(arm, case_id)
            context = load_json(context_file)
            if (
                not isinstance(context, dict)
                or context.get("schema") != f"{SCHEMA_VERSION}.context-terminal"
                or context.get("run_id") != RESUME_RUN_ID
                or context.get("capability_seal_digest") != source_digest
                or context.get("case_id") != case_id
                or context.get("arm") != arm
                or context.get("terminal_status") != "SUCCEEDED"
                or context.get("labels_opened_by_context_worker") is not False
                or context.get("answer_or_answer_session_fields_accessed") is not False
                or hashlib.sha256(str(context.get("context", "")).encode()).hexdigest()
                != context.get("context_sha256")
            ):
                raise MLR02PilotError(f"resume context is invalid: {case_id}/{arm}")
            sealed_tokens = context.get("context_tokens")
            if (
                not isinstance(sealed_tokens, int)
                or isinstance(sealed_tokens, bool)
                or not 0 <= sealed_tokens <= MEMORY_TOKEN_BUDGET
            ):
                raise MLR02PilotError(f"resume context budget is invalid: {case_id}/{arm}")
            reader_tokens = reader_counter.memory_tokens(
                question=case.question,
                question_as_of=case.question_at,
                memory_context=str(context["context"]),
            )
            if reader_tokens - sealed_tokens != 1:
                raise MLR02PilotError(
                    f"resume template-boundary accounting drifted: {case_id}/{arm}"
                )
            contexts.append(context)

            answer_file = _resume_answer_path(arm, case_id)
            answer = load_json(answer_file)
            if (
                not isinstance(answer, dict)
                or answer.get("schema") != f"{SCHEMA_VERSION}.answer-terminal"
                or answer.get("run_id") != RESUME_RUN_ID
                or answer.get("capability_seal_digest") != source_digest
                or answer.get("case_id") != case_id
                or answer.get("arm") != arm
                or answer.get("context_sha256") != context.get("context_sha256")
                or answer.get("seed") != case_seed(case_id, "answer")
            ):
                raise MLR02PilotError(f"resume answer is invalid: {case_id}/{arm}")
            if answer.get("terminal_status") == "SUCCEEDED":
                succeeded += 1
            elif (
                answer.get("terminal_status") == "FAILED"
                and answer.get("reader_failure_class") == "TOKEN_ACCOUNTING_MISMATCH"
                and answer.get("completion_tokens") == 0
                and isinstance(answer.get("reader_failure_metadata"), dict)
                and answer["reader_failure_metadata"].get("accounting_delta") == 1
                and answer["reader_failure_metadata"].get(
                    "send_time_truncation_attempted"
                )
                is False
            ):
                failed += 1
            else:
                raise MLR02PilotError(f"resume answer state is invalid: {case_id}/{arm}")
            answers.append(answer)
    if (
        context_seal.get("records_digest") != records_sha256(contexts)
        or answer_seal.get("records_digest") != records_sha256(answers)
        or succeeded != 19
        or failed != 13
    ):
        raise MLR02PilotError("repair/resume source record digest drifted")
    return {
        "source_run_id": RESUME_RUN_ID,
        "source_capability_seal_digest": source_digest,
        "source_context_seal_sha256": sha256_file(RESUME_CONTEXT_SEAL),
        "source_context_records_digest": context_seal["records_digest"],
        "source_answer_seal_sha256": sha256_file(RESUME_ANSWER_SEAL),
        "source_answer_records_digest": answer_seal["records_digest"],
        "context_cells_reused": len(contexts),
        "answer_success_cells_reused": succeeded,
        "answer_preflight_failures_to_resume": failed,
        "labels_opened": False,
        "template_boundary_tokens": 1,
        "retrieval_or_product_runtime_reexecution": False,
    }


def build_capability_seal() -> dict[str, Any]:
    if CAPABILITY_PATH.is_file():
        capability_seal_digest()
        return cast(dict[str, Any], load_json(CAPABILITY_PATH))
    if sha256_file(GOAL_PATH) != GOAL_SHA256:
        raise MLR02PilotError("ML-R02 goal identity drifted")
    if (
        sha256_file(INPUT_PATH) != EXPECTED_INPUT_SHA256
        or sha256_file(DATASET_PATH) != EXPECTED_DATASET_SHA256
    ):
        raise MLR02PilotError("LongMemEval input identity drifted")
    if not ENV_SPEC_PATH.is_file() or not ENV_LEDGER_PATH.is_file():
        raise MLR02PilotError("compute environment record is absent")
    predecessor = _validate_reusable_baseline_predecessor()
    resume = _validate_repair_resume_source()
    run_lock = {
        "schema": f"{SCHEMA_VERSION}.run-lock",
        "run_id": RUN_ID,
        "execution_scope": "FIRST_8_CASES_X_4_ARMS_THEN_STOP",
        "target_count": TARGET_COUNT,
        "arms": list(ARMS),
        "case_ids": list(target_case_ids()),
        "source_order_sha256": canonical_sha256(target_case_ids()),
        "input_sha256": sha256_file(INPUT_PATH),
        "dataset_sha256": sha256_file(DATASET_PATH),
        "goal_sha256": GOAL_SHA256,
        "memory_context_tokens": MEMORY_TOKEN_BUDGET,
        "formal_holdout": False,
        "formal_targets_authorized": False,
        "request_identity_run_id": REQUEST_IDENTITY_RUN_ID,
        "repair_resume_source_run_id": RESUME_RUN_ID,
    }
    run_lock["run_lock_digest"] = canonical_sha256(run_lock)
    atomic_json(RUN_ROOT / "run-lock.json", run_lock)
    material: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.capability-seal",
        "status": "FROZEN",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "goal_sha256": GOAL_SHA256,
        "run_lock_digest": run_lock["run_lock_digest"],
        "execution_scope": {
            "target": "8_CASES_X_4_ARMS",
            "stop_after_score": True,
            "targets_128_500_authorized": False,
            "formal_holdout": False,
        },
        "data": {
            "input_sha256": EXPECTED_INPUT_SHA256,
            "dataset_sha256": EXPECTED_DATASET_SHA256,
            "case_ids": list(target_case_ids()),
            "label_free_context_stage": True,
        },
        "context_budget": {
            "tokens": MEMORY_TOKEN_BUDGET,
            "limiting_capacity": "benchmark_adapter_supported_capacity",
            "same_for_all_arms": True,
        },
        "baseline_reuse": {
            "source_context_seal_sha256": sha256_file(PREDECESSOR_SEAL),
            "arms": dict(BASELINE_REUSE),
            "product_outputs_reused": False,
            "predecessor_validation": predecessor,
        },
        "repair_resume": resume,
        "provider": {
            **_provider_identity(),
            "answer_max_tokens": ANSWER_MAX_TOKENS,
            "judge_max_tokens": JUDGE_MAX_TOKENS,
            "thinking_enabled": False,
            "same_model_self_judge_bias": True,
            "request_identity_run_id": REQUEST_IDENTITY_RUN_ID,
            "sealed_context_accounting": (
                "standalone_context_tokens_plus_at_most_one_chat_template_boundary_token"
            ),
        },
        "environment": {
            "spec_sha256": sha256_file(ENV_SPEC_PATH),
            "ledger_sha256": sha256_file(ENV_LEDGER_PATH),
            "migration_head": "0049_cleanup_terminal_counts",
        },
        "code_sha256": _code_identity(),
    }
    value = {**material, "seal_digest": canonical_sha256(material)}
    atomic_json(CAPABILITY_PATH, value)
    capability_seal_digest()
    return value


def _run_lock_digest() -> str:
    value = load_json(RUN_ROOT / "run-lock.json")
    if not isinstance(value, dict) or not isinstance(value.get("run_lock_digest"), str):
        raise MLR02PilotError("run lock is absent")
    return str(value["run_lock_digest"])


def _configure_context_harness() -> ContextExecutionSpec:
    seal_digest = capability_seal_digest()
    spec = ContextExecutionSpec(
        run_id=RUN_ID,
        checkpoint_root=CHECKPOINT_ROOT,
        arms=PRODUCT_ARMS,
        arm_modes=((RAW_ARM, "OFF"), (FORMED_ARM, "CANARY")),
        run_lock_digest=_run_lock_digest(),
        stateful_shards=STATEFUL_SHARDS,
        mcp_concurrency=4,
        projection_batch_size=32,
        barrier_timeout_ms=120_000,
        max_results=12,
        memory_token_budget=MEMORY_TOKEN_BUDGET,
        max_latency_ms=2_000,
        cleanup_barrier_timeout_ms=300_000,
        shard_lifecycle_mode="SHARD_TERMINAL_CLEANUP_WITNESS",
        protocol_amendment_digest=SCOPE_DIGEST,
        progressive_context_evidence=True,
    )
    assignments: dict[str, object] = {
        "ARMS": ARMS,
        "PRODUCT_ARMS": PRODUCT_ARMS,
        "BM25_ARM": "MLR02-BM25-T",
        "DENSE_ARM": "MLR02-DENSE",
        "RAW_ARM": RAW_ARM,
        "FORMED_ARM": FORMED_ARM,
        "R4_ROOT": CHECKPOINT_ROOT,
        "RUN_ROOT": RUN_ROOT,
        "RUN_ID": RUN_ID,
        "SCHEMA_VERSION": SCHEMA_VERSION,
        "STATEFUL_SHARDS": STATEFUL_SHARDS,
        "MEMORY_TOKEN_BUDGET": MEMORY_TOKEN_BUDGET,
        "RUN_LOCK_DIGEST": _run_lock_digest(),
        "AMENDMENT_DIGEST": SCOPE_DIGEST,
        "PRODUCT_SPEC": spec,
        "CAPABILITY_SEAL_PATH": CAPABILITY_PATH,
        "capability_seal_digest": lambda: seal_digest,
        "context_path": context_path,
        "product_pair_path": product_pair_path,
        "stage_seal_path": stage_seal_path,
        "target_cases": target_cases,
        "target_case_ids": target_case_ids,
        "valid_terminal": valid_terminal,
        "records_sha256": records_sha256,
        "require_stage_seal": require_stage_seal,
        "atomic_json": atomic_json,
    }
    for name, value in assignments.items():
        setattr(legacy_contexts, name, value)
    return spec


def _reuse_baseline_contexts() -> tuple[dict[str, Any], ...]:
    seal_digest = capability_seal_digest()
    records: list[dict[str, Any]] = []
    for new_arm, old_arm in BASELINE_REUSE.items():
        for case_id in target_case_ids():
            source = PREDECESSOR_ROOT / "cells" / "contexts" / old_arm / f"{case_id}.json"
            source_value = load_json(source)
            if not isinstance(source_value, dict) or source_value.get("terminal_status") != "SUCCEEDED":
                raise MLR02PilotError(f"baseline source is invalid: {old_arm}/{case_id}")
            value = {
                **source_value,
                "schema": f"{SCHEMA_VERSION}.context-terminal",
                "run_id": RUN_ID,
                "capability_seal_digest": seal_digest,
                "arm": new_arm,
                "reused_unchanged_baseline_context": True,
                "reused_from": {
                    "run_id": "ml-r01-20260831-001",
                    "arm": old_arm,
                    "record_sha256": sha256_file(source),
                    "source_context_seal_sha256": sha256_file(PREDECESSOR_SEAL),
                },
            }
            atomic_json(context_path(new_arm, case_id), value)
            records.append(value)
    return tuple(records)


def load_context_records(_target_count: int = TARGET_COUNT) -> tuple[dict[str, Any], ...]:
    seal_digest = capability_seal_digest()
    records: list[dict[str, Any]] = []
    for case_id in target_case_ids():
        for arm in ARMS:
            value = valid_terminal(
                context_path(arm, case_id),
                schema_suffix="context",
                arm=arm,
                case_id=case_id,
                seal_digest=seal_digest,
            )
            if value is None:
                raise MLR02PilotError(f"context terminal is missing: {case_id}/{arm}")
            records.append(dict(value))
    return tuple(records)


def _reuse_repair_contexts() -> tuple[dict[str, Any], ...]:
    resume = _validate_repair_resume_source()
    seal_digest = capability_seal_digest()
    records: list[dict[str, Any]] = []
    for case_id in target_case_ids():
        for arm in ARMS:
            source = _resume_context_path(arm, case_id)
            source_value = load_json(source)
            if not isinstance(source_value, dict):
                raise MLR02PilotError(f"resume context disappeared: {case_id}/{arm}")
            value = {
                **source_value,
                "schema": f"{SCHEMA_VERSION}.context-terminal",
                "run_id": RUN_ID,
                "capability_seal_digest": seal_digest,
                "reader_accounting": {
                    "sealed_context_tokens": source_value["context_tokens"],
                    "template_boundary_tokens": resume["template_boundary_tokens"],
                    "policy": "CONTEXT_BUDGET_EXCLUDES_FIXED_CHAT_TEMPLATE_BOUNDARY",
                },
                "reused_from": {
                    "run_id": RESUME_RUN_ID,
                    "record_sha256": sha256_file(source),
                    "source_context_seal_sha256": resume[
                        "source_context_seal_sha256"
                    ],
                    "context_bytes_unchanged": True,
                    "retrieval_reexecuted": False,
                    "product_runtime_reexecuted": False,
                },
            }
            atomic_json(context_path(arm, case_id), value)
            records.append(value)
    return tuple(records)


def run_contexts() -> dict[str, Any]:
    seal_path = stage_seal_path("context")
    if seal_path.is_file():
        return require_stage_seal("context")
    started = time.perf_counter()
    source_seal = load_json(RESUME_CONTEXT_SEAL)
    if not isinstance(source_seal, dict):
        raise MLR02PilotError("resume context seal disappeared")
    resume = _validate_repair_resume_source()
    records = _reuse_repair_contexts()
    by_arm = {arm: [row for row in records if row["arm"] == arm] for arm in ARMS}
    value = {
        **source_seal,
        "schema": f"{SCHEMA_VERSION}.context-seal",
        "run_id": RUN_ID,
        "capability_seal_digest": capability_seal_digest(),
        "status": "PASS",
        "terminal_count": len(records),
        "records_digest": records_sha256(records),
        "wall_seconds": round(time.perf_counter() - started, 6),
        "arms": {
            arm: {
                "terminal_count": len(by_arm[arm]),
                "succeeded": len(by_arm[arm]),
                "failed": 0,
                "context_tokens_sum": sum(
                    int(record["context_tokens"]) for record in by_arm[arm]
                ),
            }
            for arm in ARMS
        },
        "runtime_terminals": {
            "status": "REUSED_BY_FROZEN_CONTEXT_SEAL_DIGEST",
            "source_run_id": RESUME_RUN_ID,
            "source_context_seal_sha256": resume["source_context_seal_sha256"],
            "retrieval_or_product_runtime_reexecution": False,
        },
        "repair_resume": {
            **resume,
            "context_bytes_unchanged": len(records),
            "context_cells_retried": 0,
            "standalone_context_budget": MEMORY_TOKEN_BUDGET,
            "chat_template_boundary_tokens": 1,
        },
        "answer_calls": 0,
        "judge_calls": 0,
    }
    atomic_json(seal_path, value)
    require_stage_seal("context")
    return value


def _configure_provider_harness() -> None:
    seal_digest = capability_seal_digest()
    assignments: dict[str, object] = {
        "ARMS": ARMS,
        "R4_ROOT": CHECKPOINT_ROOT,
        "RUN_ID": RUN_ID,
        "SCHEMA_VERSION": SCHEMA_VERSION,
        "MEMORY_TOKEN_BUDGET": MEMORY_TOKEN_BUDGET,
        "ANSWER_MAX_TOKENS": ANSWER_MAX_TOKENS,
        "JUDGE_MAX_TOKENS": JUDGE_MAX_TOKENS,
        "ANSWER_WORKERS": ANSWER_WORKERS,
        "JUDGE_WORKERS": JUDGE_WORKERS,
        "PROVIDER_RUN_ID": f"{REQUEST_IDENTITY_RUN_ID}-r4",
        "SEALED_CONTEXT_TOKEN_ACCOUNTING": True,
        "capability_seal_digest": lambda: seal_digest,
        "case_seed": case_seed,
        "answer_path": answer_path,
        "judge_path": judge_path,
        "stage_seal_path": stage_seal_path,
        "target_cases": target_cases,
        "valid_terminal": valid_terminal,
        "records_sha256": records_sha256,
        "require_stage_seal": require_stage_seal,
        "load_context_records": load_context_records,
        "atomic_json": atomic_json,
    }
    for name, value in assignments.items():
        setattr(legacy_providers, name, value)


def run_answers() -> dict[str, Any]:
    _configure_provider_harness()
    if stage_seal_path("answer").is_file():
        return require_stage_seal("answer")
    resume = _validate_repair_resume_source()
    seal_digest = capability_seal_digest()
    contexts = {
        (str(row["case_id"]), str(row["arm"])): row
        for row in load_context_records()
    }
    reused = 0
    for case_id in target_case_ids():
        for arm in ARMS:
            source = _resume_answer_path(arm, case_id)
            source_value = load_json(source)
            if not isinstance(source_value, dict):
                raise MLR02PilotError(f"resume answer disappeared: {case_id}/{arm}")
            if source_value.get("terminal_status") != "SUCCEEDED":
                continue
            context = contexts[(case_id, arm)]
            if source_value.get("context_sha256") != context.get("context_sha256"):
                raise MLR02PilotError(f"reused answer context drifted: {case_id}/{arm}")
            value = {
                **source_value,
                "schema": f"{SCHEMA_VERSION}.answer-terminal",
                "run_id": RUN_ID,
                "capability_seal_digest": seal_digest,
                "sealed_context_tokens": context["context_tokens"],
                "template_boundary_tokens": resume["template_boundary_tokens"],
                "reused_from": {
                    "run_id": RESUME_RUN_ID,
                    "record_sha256": sha256_file(source),
                    "source_answer_seal_sha256": resume["source_answer_seal_sha256"],
                    "provider_call_reissued": False,
                    "request_identity_preserved": True,
                },
            }
            atomic_json(answer_path(arm, case_id), value)
            reused += 1
    if reused != 19:
        raise MLR02PilotError("unexpected successful answer resume count")
    value = legacy_providers.run_answers(TARGET_COUNT)
    if value.get("status") == "PASS":
        value = {
            **value,
            "resumed_successful_provider_calls": reused,
            "new_provider_calls": TARGET_COUNT * len(ARMS) - reused,
            "repair_resume_source_answer_seal_sha256": resume[
                "source_answer_seal_sha256"
            ],
            "request_identity_run_id": REQUEST_IDENTITY_RUN_ID,
        }
        atomic_json(stage_seal_path("answer"), value)
    return value


def run_judges() -> dict[str, Any]:
    _configure_provider_harness()
    return legacy_providers.run_judges(TARGET_COUNT)


def _configure_score_harness() -> None:
    seal_digest = capability_seal_digest()
    assignments: dict[str, object] = {
        "ARMS": ARMS,
        "PRODUCT_ARMS": PRODUCT_ARMS,
        "RAW_ARM": RAW_ARM,
        "FORMED_ARM": FORMED_ARM,
        "R4_ROOT": CHECKPOINT_ROOT,
        "RUN_ID": RUN_ID,
        "SCHEMA_VERSION": SCHEMA_VERSION,
        "capability_seal_digest": lambda: seal_digest,
        "stage_seal_path": stage_seal_path,
        "target_cases": target_cases,
        "records_sha256": records_sha256,
        "require_stage_seal": require_stage_seal,
        "load_context_records": load_context_records,
        "atomic_json": atomic_json,
    }
    for name, value in assignments.items():
        setattr(legacy_score, name, value)
    # Score consumes the already sealed ML-R01 R3 strict-safety witness only.
    legacy_score.RUN_ROOT = ROOT / "var/ml_repair/ml-r01-20260831-001"
    _configure_provider_harness()
    legacy_score.load_answer_records = legacy_providers.load_answer_records
    legacy_score.load_judge_records = legacy_providers.load_judge_records


def run_score() -> dict[str, Any]:
    _configure_score_harness()
    value = legacy_score.score(TARGET_COUNT)
    if value.get("status") != "PASS_PILOT_ONLY":
        raise MLR02PilotError("8x4 score did not close as pilot-only")
    return value


def build_results() -> dict[str, Any]:
    context = require_stage_seal("context")
    answer = require_stage_seal("answer")
    judge = require_stage_seal("judge")
    score = require_stage_seal("score")
    value = {
        "schema": f"{SCHEMA_VERSION}.results",
        "run_id": RUN_ID,
        "execution_scope": "FIRST_8_CASES_X_4_ARMS_THEN_STOP",
        "status": "PASS_8X4_COMPLETE_STOPPED",
        "terminal_cells": {"context": 32, "answer": 32, "judge": 32, "score": 32},
        "stages": {
            "context": context,
            "answer": answer,
            "judge": judge,
            "score": score,
        },
        "formal_holdout_opened": False,
        "targets_128_500_started": False,
        "default_product_enablement": False,
    }
    atomic_json(RUN_ROOT / "results.json", value)
    terminal = {
        "schema": f"{SCHEMA_VERSION}.terminal",
        "run_id": RUN_ID,
        "terminal": True,
        "status": "COMPLETE_USER_LIMIT_8X4",
        "results_sha256": sha256_file(RUN_ROOT / "results.json"),
        "stopped_before_128": True,
        "stopped_before_500": True,
        "formal_holdout_opened": False,
    }
    atomic_json(RUN_ROOT / "terminal.json", terminal)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        required=True,
        choices=("seal", "contexts", "answers", "judges", "score", "pilot"),
    )
    stage = parser.parse_args().stage
    if stage == "seal":
        value = build_capability_seal()
    elif stage == "contexts":
        value = run_contexts()
    elif stage == "answers":
        value = run_answers()
    elif stage == "judges":
        value = run_judges()
    elif stage == "score":
        value = run_score()
        build_results()
    else:
        build_capability_seal()
        run_contexts()
        run_answers()
        run_judges()
        run_score()
        value = build_results()
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
