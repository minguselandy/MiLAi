"""Two-shard frozen flat-Contriever producer for ML-R01 R4."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from typing import Any

from tokenizers import Tokenizer

from evals.ml_repair.mlr01_r4_contract import (
    MEMORY_TOKEN_BUDGET,
    MODEL_ID,
    R4_ROOT,
    RUN_ID,
    SCHEMA_VERSION,
    TOKENIZER_PATH,
    atomic_json,
    capability_seal_digest,
    context_path,
    source_snapshot_sha256,
    target_cases,
    valid_terminal,
)
from evals.paper.adapters import DenseAdapter
from evals.paper.runners.contriever_contexts import (
    MODEL_ID as CONTRIEVER_MODEL_ID,
)
from evals.paper.runners.contriever_contexts import FrozenContrieverEmbedder
from evals.paper.runners.longmemeval import memory_events

ARM = "MLR01-DENSE"


def _success_record(
    *,
    case: Any,
    result: Any,
    embedder: FrozenContrieverEmbedder,
    seal_digest: str,
    shard: int,
) -> dict[str, Any]:
    context = str(result.context)
    return {
        "schema": f"{SCHEMA_VERSION}.context-terminal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "case_id": case.source_id,
        "category": case.category,
        "arm": ARM,
        "track": "EVALUATION_BASELINE_NO_CANONICAL_AUTHORITY",
        "terminal_status": "SUCCEEDED",
        "context": context,
        "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
        "context_tokens": int(result.declared_tokens),
        "retrieval_trace": [dict(value) for value in result.trace],
        "selected_session_ids": list(
            dict.fromkeys(str(value["session_id"]) for value in result.trace)
        ),
        "source_input_snapshot_digest": source_snapshot_sha256(case),
        "history_session_count": len(case.sessions),
        "history_turn_count": sum(len(session.turns) for session in case.sessions),
        "labels_opened_by_context_worker": False,
        "answer_or_answer_session_fields_accessed": False,
        "canonical_authority": False,
        "canonical_mutation": False,
        "provider_calls": {"answer": 0, "judge": 0},
        "shard": shard,
        "usage": {
            **dict(result.usage),
            "context_truncated": result.usage.get("context_truncated") is True,
            "embedder_identity": embedder.identity(),
        },
        "latency_ms": round(float(result.latency_ms), 6),
        "reader_model_id": MODEL_ID,
    }


def _failure_record(
    *, case: Any, error: Exception, seal_digest: str, shard: int
) -> dict[str, Any]:
    return {
        "schema": f"{SCHEMA_VERSION}.context-terminal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "case_id": case.source_id,
        "category": case.category,
        "arm": ARM,
        "track": "EVALUATION_BASELINE_NO_CANONICAL_AUTHORITY",
        "terminal_status": "FAILED",
        "context": "",
        "context_sha256": hashlib.sha256(b"").hexdigest(),
        "context_tokens": 0,
        "retrieval_trace": [],
        "selected_session_ids": [],
        "source_input_snapshot_digest": source_snapshot_sha256(case),
        "labels_opened_by_context_worker": False,
        "answer_or_answer_session_fields_accessed": False,
        "canonical_authority": False,
        "canonical_mutation": False,
        "provider_calls": {"answer": 0, "judge": 0},
        "shard": shard,
        "failure_class": type(error).__name__,
        "failure_message_sha256": hashlib.sha256(str(error).encode()).hexdigest(),
    }


def run_dense_shard(*, target_count: int, shard: int) -> dict[str, Any]:
    if shard not in {0, 1}:
        raise ValueError("dense shard must be 0 or 1")
    seal_digest = capability_seal_digest()
    cases = tuple(
        case
        for ordinal, case in enumerate(target_cases(target_count))
        if ordinal % 2 == shard
    )
    existing = {
        case.source_id: valid_terminal(
            context_path(ARM, case.source_id),
            schema_suffix="context",
            arm=ARM,
            case_id=case.source_id,
            seal_digest=seal_digest,
        )
        for case in cases
    }
    pending = []
    for case in cases:
        record = existing[case.source_id]
        if record is None or record.get("terminal_status") != "SUCCEEDED":
            pending.append(case)
    started = time.perf_counter()
    succeeded = sum(
        record is not None and record.get("terminal_status") == "SUCCEEDED"
        for record in existing.values()
    )
    failed = 0
    embedder: FrozenContrieverEmbedder | None = None
    if pending:
        tokenizer = Tokenizer.from_file(str(TOKENIZER_PATH))
        token_counter = lambda text: len(tokenizer.encode(text).ids)
        embedder = FrozenContrieverEmbedder(device=f"cuda:{2 + shard}")
        for case in pending:
            try:
                adapter = DenseAdapter(
                    embedder,
                    granularity="session",
                    top_k=3,
                    token_counter=token_counter,
                    model_id=CONTRIEVER_MODEL_ID,
                )
                adapter.reset(RUN_ID, case.source_id)
                for event in memory_events(case):
                    adapter.ingest(event)
                adapter.finalize()
                result = adapter.query(
                    case.question,
                    case.question_at,
                    MEMORY_TOKEN_BUDGET,
                    "CONTROLLED",
                )
                record = _success_record(
                    case=case,
                    result=result,
                    embedder=embedder,
                    seal_digest=seal_digest,
                    shard=shard,
                )
                succeeded += 1
            except Exception as exc:  # noqa: BLE001 - one cell becomes terminal
                record = _failure_record(
                    case=case, error=exc, seal_digest=seal_digest, shard=shard
                )
                failed += 1
            atomic_json(context_path(ARM, case.source_id), record)
    terminal = {
        "schema": f"{SCHEMA_VERSION}.dense-shard-terminal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "arm": ARM,
        "shard": shard,
        "device": f"cuda:{2 + shard}",
        "case_count": len(cases),
        "resumed": len(cases) - len(pending),
        "succeeded": succeeded,
        "failed": failed,
        "model_id": CONTRIEVER_MODEL_ID,
        "embedder_identity": embedder.identity() if embedder is not None else None,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    atomic_json(
        R4_ROOT / "runtime" / f"dense-{target_count}-shard-{shard}.json",
        terminal,
    )
    return terminal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, choices=(8, 128, 500), required=True)
    parser.add_argument("--shard", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    value = run_dense_shard(target_count=args.target, shard=args.shard)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return int(value["failed"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
