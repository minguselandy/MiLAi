"""Frozen, label-free contracts for the ML-closure LongMemEval validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, unquote

from evals.dg14.contracts import (
    DG14HistoryEvent,
    HistoryRole,
    normalize_lme_timestamp,
    sha256_json,
)
from evals.paper.datasets.longmemeval import LongMemEvalCase

ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "var/ml_closure/ml-closure-20260830-001"
CHECKPOINT_ROOT = RUN_ROOT / "checkpoints/longmemeval"
INPUT_PATH = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
DATASET_PATH = Path(
    "/cra/memory/mx_memory/benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
)
BENCHMARK_ROOT = Path("/cra/memory/mx_memory/benchmarks/LongMemEval-dg12-v3")
OFFICIAL_EVALUATOR = BENCHMARK_ROOT / "src/evaluation/evaluate_qa.py"
TOKENIZER_PATH = Path("/cra/qwen36-35B/tokenizer.json")

RUN_ID = "ml-closure-20260830-001-longmemeval"
SCHEMA_VERSION = "milai.memory-lifecycle-longmemeval.v0.1"
ARMS = ("LME-R", "LME-C")
ARM_MODES = {"LME-R": "OFF", "LME-C": "CANARY"}
CASE_COUNT = 500
RETRIEVAL_CASE_COUNT = 470
STATEFUL_SHARDS = 4
MCP_CONCURRENCY = 4
STATEFUL_CASE_TIMEOUT_SECONDS = 600
PROJECTION_BATCH_SIZE = 32
BARRIER_TIMEOUT_MS = 120_000
MAX_RESULTS = 12
MEMORY_TOKEN_BUDGET = 1_024
ANSWER_WORKERS = 8
JUDGE_WORKERS = 8
GLOBAL_WORKER_CEILING = 16
ANSWER_MAX_TOKENS = 256
JUDGE_MAX_TOKENS = 10
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_830
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_BASE_URL = "http://127.0.0.1:7860"
_SOURCE_REF = re.compile(
    r"^longmemeval://case/([^/]+)/session/(\d+)/([^/]+)/turn/(\d+)"
    r"(?:\?chunk=(\d+)(?:&|$))?"
)


class LongMemEvalClosureError(RuntimeError):
    """The frozen external validation contract was violated."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


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
        raise LongMemEvalClosureError(f"invalid JSON artifact: {path}") from exc


def case_subject(project_id: str, case_id: str) -> str:
    digest = sha256_json(
        {"case_id": case_id, "project_id": project_id, "subject": "self"}
    )
    return f"mlc-lme:{project_id}:self:{digest[:16]}"


def runtime_case_id(source_id: str) -> str:
    """Remove benchmark markers before identity crosses the MiLA boundary."""

    if not source_id:
        raise ValueError("LongMemEval source identity is empty")
    digest = hashlib.sha256(f"mlc-lme-runtime-case-v1:{source_id}".encode()).hexdigest()
    return f"case-{digest[:24]}"


def history_events(case: LongMemEvalCase) -> tuple[DG14HistoryEvent, ...]:
    """Build the exact turn-level history shape without accepting a question."""

    events: list[DG14HistoryEvent] = []
    case_id = runtime_case_id(case.source_id)
    for session_ordinal, session in enumerate(case.sessions):
        observed_at = normalize_lme_timestamp(session.observed_at)
        for turn_ordinal, turn in enumerate(session.turns):
            # Empty turns carry no retrievable Evidence. Preserve every
            # non-empty source turn exactly and retain its original ordinal.
            if not turn.content:
                continue
            events.append(
                DG14HistoryEvent(
                    case_id=case_id,
                    session_ordinal=session_ordinal,
                    original_session_id=session.session_id,
                    turn_ordinal=turn_ordinal,
                    role=cast(HistoryRole, turn.role),
                    content=turn.content,
                    observed_at=observed_at,
                )
            )
    return tuple(events)


def padded_source_ref(event: DG14HistoryEvent) -> str:
    """Keep lexical source order equal to the source conversation order."""

    return (
        f"longmemeval://case/{quote(event.case_id, safe='')}/session/"
        f"{event.session_ordinal:04d}/"
        f"{quote(event.original_session_id, safe='')}/turn/"
        f"{event.turn_ordinal:04d}?event_id={event.event_id}"
    )


def parse_source_ref(value: str) -> dict[str, object] | None:
    matched = _SOURCE_REF.match(value)
    if matched is None:
        return None
    case_id, session_ordinal, session_id, turn_ordinal, chunk_ordinal = matched.groups()
    return {
        "case_id": unquote(case_id),
        "session_ordinal": int(session_ordinal),
        "session_id": unquote(session_id),
        "turn_ordinal": int(turn_ordinal),
        "chunk_ordinal": int(chunk_ordinal or 0),
    }


def compact_source_ref(value: str) -> str:
    parsed = parse_source_ref(value)
    if parsed is None:
        return value
    return (
        f"{parsed['case_id']}:s{parsed['session_ordinal']}:"
        f"{parsed['session_id']}:t{parsed['turn_ordinal']}:c{parsed['chunk_ordinal']}"
    )


def shard_case_ids(cases: Sequence[LongMemEvalCase], shard: int) -> tuple[str, ...]:
    if not 0 <= shard < STATEFUL_SHARDS:
        raise ValueError("stateful shard is out of range")
    ordered = sorted(case.source_id for case in cases)
    return tuple(
        case_id
        for ordinal, case_id in enumerate(ordered)
        if ordinal % STATEFUL_SHARDS == shard
    )


def smoke_case_ids(cases: Sequence[LongMemEvalCase]) -> tuple[str, ...]:
    """Choose one label-free, identity-hashed case per execution shard."""

    selected: list[str] = []
    for shard in range(STATEFUL_SHARDS):
        candidates = shard_case_ids(cases, shard)
        selected.append(
            min(
                candidates,
                key=lambda case_id: hashlib.sha256(
                    f"mlc-lme-smoke-v1:{case_id}".encode()
                ).hexdigest(),
            )
        )
    return tuple(selected)


def case_seed(case_id: str, lane: str) -> int:
    """Return an arm-independent deterministic seed for a provider lane."""

    if lane not in {"answer", "judge"}:
        raise ValueError("provider lane is invalid")
    value = hashlib.sha256(
        f"{RUN_ID}:{lane}:{case_id}:{MEMORY_TOKEN_BUDGET}".encode()
    ).hexdigest()
    return int(value[:16], 16) & ((1 << 63) - 1)


def require_run_lock() -> Mapping[str, Any]:
    value = load_json(RUN_ROOT / "longmemeval-run-lock.json")
    if not isinstance(value, dict) or value.get("schema") != (
        "milai.memory-lifecycle-longmemeval-run-lock.v0.1"
    ):
        raise LongMemEvalClosureError("LongMemEval run-lock is absent or invalid")
    material = {key: item for key, item in value.items() if key != "run_lock_digest"}
    if (
        value.get("run_lock_digest")
        != hashlib.sha256(canonical_json(material)).hexdigest()
    ):
        raise LongMemEvalClosureError("LongMemEval run-lock digest drifted")
    return value


def require_terminal_records(
    records: Sequence[Mapping[str, Any]], *, expected: int, identity: str
) -> None:
    if len(records) != expected:
        raise LongMemEvalClosureError(
            f"{identity} denominator drifted: {len(records)} != {expected}"
        )
    keys = [(str(record.get("case_id")), str(record.get("arm"))) for record in records]
    if len(keys) != len(set(keys)):
        raise LongMemEvalClosureError(f"{identity} contains duplicate case/arm records")


__all__ = [
    "ANSWER_MAX_TOKENS",
    "ANSWER_WORKERS",
    "ARMS",
    "ARM_MODES",
    "BARRIER_TIMEOUT_MS",
    "BENCHMARK_ROOT",
    "BOOTSTRAP_SAMPLES",
    "BOOTSTRAP_SEED",
    "CASE_COUNT",
    "CHECKPOINT_ROOT",
    "DATASET_PATH",
    "GLOBAL_WORKER_CEILING",
    "INPUT_PATH",
    "JUDGE_MAX_TOKENS",
    "JUDGE_WORKERS",
    "MAX_RESULTS",
    "MCP_CONCURRENCY",
    "MEMORY_TOKEN_BUDGET",
    "MODEL_ID",
    "OFFICIAL_EVALUATOR",
    "PROJECTION_BATCH_SIZE",
    "RETRIEVAL_CASE_COUNT",
    "ROOT",
    "RUN_ID",
    "RUN_ROOT",
    "SCHEMA_VERSION",
    "STATEFUL_CASE_TIMEOUT_SECONDS",
    "STATEFUL_SHARDS",
    "TOKENIZER_PATH",
    "VLLM_BASE_URL",
    "LongMemEvalClosureError",
    "atomic_json",
    "canonical_json",
    "case_seed",
    "case_subject",
    "compact_source_ref",
    "history_events",
    "load_json",
    "padded_source_ref",
    "parse_source_ref",
    "require_run_lock",
    "require_terminal_records",
    "runtime_case_id",
    "sha256_file",
    "shard_case_ids",
    "smoke_case_ids",
]
