"""Frozen contracts shared by the ML-R01 R4 staircase.

This module is deliberately free of Runtime imports so the isolated Contriever
workers can consume the same identities without inheriting product credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from evals.paper.datasets.longmemeval import LongMemEvalCase, load_inputs

ROOT = Path(__file__).resolve().parents[2]
GOAL_PATH = (
    ROOT / "MiLAi_ML-R01_ProjectionWorker租约与Formation送达Binding闭环修复_GOALS.md"
)
RUN_ID = "ml-r01-20260831-001"
RUN_ROOT = ROOT / "var/ml_repair" / RUN_ID
R4_ROOT = RUN_ROOT / "checkpoints/r4"
CELL_ROOT = R4_ROOT / "cells"
CAPABILITY_SEAL_PATH = R4_ROOT / "capability-identity-seal.json"
INPUT_PATH = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
DATASET_PATH = Path(
    "/cra/memory/mx_memory/benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
)
BENCHMARK_ROOT = Path("/cra/memory/mx_memory/benchmarks/LongMemEval-dg12-v3")
OFFICIAL_EVALUATOR = BENCHMARK_ROOT / "src/evaluation/evaluate_qa.py"
TOKENIZER_PATH = Path("/cra/qwen36-35B/tokenizer.json")
CONTRIEVER_PYTHON = Path("/tmp/milai-dg11-contriever-20260824-001/bin/python")

SCHEMA_VERSION = "milai.ml-r01.r4.v1"
GOAL_VERSION = "0.3"
GOAL_SHA256 = "68dbfcc22524a8b8ce7b7e64fbdd3734799b32bc15eb5f253e99d48b9db3f5d4"
EXPECTED_INPUT_SHA256 = (
    "7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412"
)
EXPECTED_DATASET_SHA256 = (
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
)
EXPECTED_BENCHMARK_COMMIT = "9e0b455f4ef0e2ab8f2e582289761153549043fc"

ARMS = ("MLR01-BM25-T", "MLR01-DENSE", "MLR01-R", "MLR01-F")
BASELINE_ARMS = ("MLR01-BM25-T", "MLR01-DENSE")
PRODUCT_ARMS = ("MLR01-R", "MLR01-F")
TARGET_COUNTS = (8, 128, 500)
FORMAL_TARGET_COUNTS = (128, 500)
FULL_CASE_COUNT = 500
RETRIEVAL_CASE_COUNT = 470
MEMORY_TOKEN_BUDGET = 1_024
ANSWER_MAX_TOKENS = 500
JUDGE_MAX_TOKENS = 10
ANSWER_WORKERS = 8
JUDGE_WORKERS = 8
STATEFUL_SHARDS = 4
DENSE_SHARDS = 2
CPU_WORKERS = 8
GLOBAL_ACTIVE_CEILING = 16
CONTEXT_RESOURCE_WINDOW_SECONDS = 2 * 60 * 60
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_BASE_URL = "http://127.0.0.1:7860"
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_831
TargetCount = Literal[8, 128, 500]


class MLR01R4Error(RuntimeError):
    """The frozen R4 identity, denominator, or stage contract drifted."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode()
        )
        handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MLR01R4Error(f"invalid R4 JSON artifact: {path}") from exc


@lru_cache(maxsize=1)
def load_all_cases() -> tuple[str, tuple[LongMemEvalCase, ...]]:
    partition, cases = load_inputs(INPUT_PATH)
    if len(cases) != FULL_CASE_COUNT:
        raise MLR01R4Error("LongMemEval-S denominator drifted")
    if sum("_abs" not in case.source_id for case in cases) != RETRIEVAL_CASE_COUNT:
        raise MLR01R4Error("LongMemEval-S retrieval denominator drifted")
    return partition, cases


def target_cases(target_count: int) -> tuple[LongMemEvalCase, ...]:
    if target_count not in TARGET_COUNTS:
        raise ValueError("R4 target count must be 8, 128, or 500")
    _partition, cases = load_all_cases()
    return tuple(cases[:target_count])


def target_case_ids(target_count: int) -> tuple[str, ...]:
    return tuple(case.source_id for case in target_cases(target_count))


def source_order_sha256(target_count: int) -> str:
    return canonical_sha256(target_case_ids(target_count))


def source_snapshot_sha256(case: LongMemEvalCase) -> str:
    """Bind the label-free, ordered session/turn input seen by every arm."""

    return canonical_sha256(
        {
            "case_id": case.source_id,
            "category": case.category,
            "question": case.question,
            "question_at": case.question_at,
            "sessions": [
                {
                    "session_id": session.session_id,
                    "observed_at": session.observed_at,
                    "turns": [
                        {
                            "ordinal": ordinal,
                            "role": turn.role,
                            "content": turn.content,
                        }
                        for ordinal, turn in enumerate(session.turns)
                    ],
                }
                for session in case.sessions
            ],
        }
    )


def case_seed(case_id: str, lane: Literal["answer", "judge"]) -> int:
    if lane not in {"answer", "judge"}:
        raise ValueError("R4 provider lane is invalid")
    digest = hashlib.sha256(
        f"{RUN_ID}:r4:{lane}:{case_id}:{MEMORY_TOKEN_BUDGET}".encode()
    ).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def context_path(arm: str, case_id: str) -> Path:
    if arm not in ARMS:
        raise ValueError("R4 arm is invalid")
    return CELL_ROOT / "contexts" / arm / f"{case_id}.json"


def product_pair_path(case_id: str) -> Path:
    return CELL_ROOT / "product-pairs" / f"{case_id}.json"


def answer_path(arm: str, case_id: str) -> Path:
    if arm not in ARMS:
        raise ValueError("R4 arm is invalid")
    return CELL_ROOT / "answers" / arm / f"{case_id}.json"


def judge_path(arm: str, case_id: str) -> Path:
    if arm not in ARMS:
        raise ValueError("R4 arm is invalid")
    return CELL_ROOT / "judges" / arm / f"{case_id}.json"


def stage_seal_path(stage: str, target_count: int) -> Path:
    if stage not in {"context", "answer", "judge", "score"}:
        raise ValueError("R4 seal stage is invalid")
    if target_count not in TARGET_COUNTS:
        raise ValueError("R4 target count is invalid")
    return R4_ROOT / f"{stage}-seal-{target_count}.json"


def capability_seal_digest() -> str:
    value = load_json(CAPABILITY_SEAL_PATH)
    if not isinstance(value, dict):
        raise MLR01R4Error("R4 capability seal is not an object")
    claimed = value.get("seal_digest")
    material = {key: item for key, item in value.items() if key != "seal_digest"}
    observed = canonical_sha256(material)
    if (
        claimed != observed
        or value.get("schema") != f"{SCHEMA_VERSION}.capability-seal"
        or value.get("status") != "FROZEN"
        or value.get("goal_sha256") != GOAL_SHA256
    ):
        raise MLR01R4Error("R4 capability seal identity drifted")
    code_sha256 = value.get("code_sha256")
    if not isinstance(code_sha256, dict) or any(
        not isinstance(relative, str)
        or not isinstance(digest, str)
        or not (ROOT / relative).is_file()
        or sha256_file(ROOT / relative) != digest
        for relative, digest in code_sha256.items()
    ):
        raise MLR01R4Error("R4 capability-sealed source code drifted")
    if (
        sha256_file(GOAL_PATH) != GOAL_SHA256
        or sha256_file(INPUT_PATH) != EXPECTED_INPUT_SHA256
        or sha256_file(DATASET_PATH) != EXPECTED_DATASET_SHA256
    ):
        raise MLR01R4Error("R4 capability-sealed goal or data drifted")
    return observed


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
    try:
        value = load_json(path)
    except MLR01R4Error:
        return None
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


def records_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        (dict(record) for record in records),
        key=lambda value: (str(value.get("case_id")), str(value.get("arm"))),
    )
    return canonical_sha256(ordered)


def require_stage_seal(stage: str, target_count: int) -> dict[str, Any]:
    value = load_json(stage_seal_path(stage, target_count))
    if (
        not isinstance(value, dict)
        or value.get("schema") != f"{SCHEMA_VERSION}.{stage}-seal"
        or value.get("target_count") != target_count
        or value.get("capability_seal_digest") != capability_seal_digest()
        or value.get("terminal_count") != target_count * len(ARMS)
        or value.get("status") != "PASS"
    ):
        raise MLR01R4Error(f"R4 {stage} seal is absent or invalid")
    return value


def arm_case_keys(target_count: int) -> tuple[tuple[str, str], ...]:
    return tuple(
        (case_id, arm) for case_id in target_case_ids(target_count) for arm in ARMS
    )


__all__ = [
    "ANSWER_MAX_TOKENS",
    "ANSWER_WORKERS",
    "ARMS",
    "BASELINE_ARMS",
    "BENCHMARK_ROOT",
    "BOOTSTRAP_SAMPLES",
    "BOOTSTRAP_SEED",
    "CAPABILITY_SEAL_PATH",
    "CELL_ROOT",
    "CONTEXT_RESOURCE_WINDOW_SECONDS",
    "CONTRIEVER_PYTHON",
    "CPU_WORKERS",
    "DATASET_PATH",
    "DENSE_SHARDS",
    "EXPECTED_BENCHMARK_COMMIT",
    "EXPECTED_DATASET_SHA256",
    "EXPECTED_INPUT_SHA256",
    "FORMAL_TARGET_COUNTS",
    "FULL_CASE_COUNT",
    "GLOBAL_ACTIVE_CEILING",
    "GOAL_PATH",
    "GOAL_SHA256",
    "GOAL_VERSION",
    "INPUT_PATH",
    "JUDGE_MAX_TOKENS",
    "JUDGE_WORKERS",
    "MEMORY_TOKEN_BUDGET",
    "MODEL_ID",
    "OFFICIAL_EVALUATOR",
    "PRODUCT_ARMS",
    "R4_ROOT",
    "RETRIEVAL_CASE_COUNT",
    "ROOT",
    "RUN_ID",
    "RUN_ROOT",
    "SCHEMA_VERSION",
    "STATEFUL_SHARDS",
    "TARGET_COUNTS",
    "TOKENIZER_PATH",
    "VLLM_BASE_URL",
    "MLR01R4Error",
    "TargetCount",
    "answer_path",
    "arm_case_keys",
    "atomic_json",
    "canonical_json",
    "canonical_sha256",
    "capability_seal_digest",
    "case_seed",
    "context_path",
    "judge_path",
    "load_all_cases",
    "load_json",
    "product_pair_path",
    "records_sha256",
    "require_stage_seal",
    "sha256_file",
    "source_order_sha256",
    "source_snapshot_sha256",
    "stage_seal_path",
    "target_case_ids",
    "target_cases",
    "valid_terminal",
]
