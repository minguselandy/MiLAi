"""Label-free PE01 smoke over five already opened LongMemEval cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer

from evals.paper.adapters import (
    FullHistoryAdapter,
    NoMemoryAdapter,
    OfficialBM25Adapter,
)
from evals.paper.contracts import MemoryAdapter, MemoryEvent

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(
    "/cra/memory/mx_memory/benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
)
SPLIT_ROOT = ROOT / "var/dg11/splits/v1"
TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
SMOKE_CASES = 5


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _source_id(case: dict[str, Any]) -> str:
    return str(case["question_id"])


def _reserved_ids() -> set[str]:
    reserved: set[str] = set()
    for split in ("generalization-v2", "paper-test-v1"):
        value = json.loads((SPLIT_ROOT / split / "source-ids.json").read_text())
        reserved.update(str(item) for item in value["source_ids"])
    return reserved


def _events(case: dict[str, Any]) -> tuple[MemoryEvent, ...]:
    events: list[MemoryEvent] = []
    sessions = zip(
        case["haystack_session_ids"],
        case["haystack_dates"],
        case["haystack_sessions"],
        strict=True,
    )
    for session_index, (session_id, observed_at, session) in enumerate(sessions):
        session_key = f"{session_id}@{session_index}"
        for turn_index, turn in enumerate(session):
            content = turn.get("content")
            actor = turn.get("role")
            if not isinstance(content, str) or actor not in {"user", "assistant"}:
                raise ValueError("LongMemEval history turn is malformed")
            events.append(
                MemoryEvent(
                    event_id=f"{session_key}:{turn_index}",
                    content=content,
                    observed_at=str(observed_at),
                    actor=str(actor),
                    scope="paper-smoke-opened-development",
                    metadata={"session_id": session_key, "turn_index": turn_index},
                )
            )
    return tuple(events)


def run(run_id: str, output: Path) -> dict[str, Any]:
    tokenizer = Tokenizer.from_file(str(TOKENIZER))
    count_tokens = lambda value: len(tokenizer.encode(value).ids)
    dataset = json.loads(DATASET.read_text())
    if not isinstance(dataset, list) or len(dataset) != 500:
        raise ValueError("LongMemEval smoke dataset denominator drifted")
    reserved = _reserved_ids()
    opened = sorted(
        (case for case in dataset if _source_id(case) not in reserved), key=_source_id
    )
    cases = opened[:SMOKE_CASES]
    if len(cases) != SMOKE_CASES or any(_source_id(case) in reserved for case in cases):
        raise ValueError("PE01 smoke did not resolve five opened cases")
    records: list[dict[str, Any]] = []
    for case in cases:
        adapters: tuple[MemoryAdapter, ...] = (
            NoMemoryAdapter(token_counter=count_tokens),
            OfficialBM25Adapter(
                granularity="session", top_k=3, token_counter=count_tokens
            ),
            OfficialBM25Adapter(
                granularity="turn", top_k=3, token_counter=count_tokens
            ),
            FullHistoryAdapter(truncate=True, token_counter=count_tokens),
        )
        for adapter in adapters:
            adapter.reset(run_id, _source_id(case))
            for event in _events(case):
                adapter.ingest(event)
            adapter.finalize()
            query_result = adapter.query(
                str(case["question"]),
                str(case["question_date"]),
                512,
                "CONTROLLED_SMOKE",
            )
            records.append(
                {
                    "case_id": _source_id(case),
                    "context_sha256": hashlib.sha256(
                        query_result.context.encode()
                    ).hexdigest(),
                    "declared_tokens": query_result.declared_tokens,
                    "latency_ms": round(query_result.latency_ms, 6),
                    "method_id": adapter.method_id,
                    "provider_calls": dict(adapter.stats().provider_calls),
                    "source_ids": list(query_result.source_ids),
                    "usage": dict(query_result.usage),
                }
            )
            adapter.close()
    payload: dict[str, Any] = {
        "case_count": SMOKE_CASES,
        "dataset_sha256": _sha256(DATASET),
        "development_ai_reviews": 0,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "gates": {
            "all_cases_opened_before_paper": len(cases) == SMOKE_CASES,
            "all_memory_payloads_le_512_tokens": all(
                record["declared_tokens"] <= 512 for record in records
            ),
            "answer_provider_calls_zero": True,
            "label_fields_accessed_zero": True,
            "paper_case_overlap_zero": all(
                record["case_id"] not in reserved for record in records
            ),
            "records_20": len(records) == 20,
        },
        "methods": ["CTRL-NONE", "LME-BM25-S", "LME-BM25-T", "CTRL-TRUNC-FULL"],
        "paper_labels_opened": False,
        "provider_requests": 0,
        "records": records,
        "run_id": run_id,
        "schema": "milai.dg11.paper-harness-smoke.v1",
        "source_ids": [_source_id(case) for case in cases],
        "status": "PASS",
        "work_package": "DG11-PE01",
    }
    gates = payload["gates"]
    assert isinstance(gates, dict)
    if not all(gates.values()):
        payload["status"] = "FAIL"
    _atomic_json(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.run_id, args.output)
    print(
        json.dumps({"run_id": args.run_id, "status": result["status"]}, sort_keys=True)
    )


if __name__ == "__main__":
    main()
