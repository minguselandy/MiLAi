"""Memora native-context runner for a frozen Hindsight OSS server."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from hindsight_client import Hindsight  # type: ignore[import-not-found]
from tokenizers import Tokenizer  # type: ignore[import-not-found]

from evals.paper.contracts import ContextRecord, write_context_archive
from evals.paper.datasets.memora import MemoraCase, MemoraCohort, load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
DEFAULT_BASE_URL = "http://127.0.0.1:28888"
MEMORY_TOKEN_BUDGET = 512


class MemoraHindsightError(RuntimeError):
    pass


def _require_inputs(path: Path, *, allow_unfrozen_smoke: bool) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MemoraHindsightError("Memora input artifact is invalid")
    if allow_unfrozen_smoke:
        if value.get("test_data_only") is not True or not 1 <= value.get(
            "case_count", 0
        ) <= 10:
            raise MemoraHindsightError(
                "unfrozen Memora smoke requires synthetic inputs"
            )
    elif value.get("test_data_only") is True:
        raise MemoraHindsightError("formal Memora run cannot use synthetic inputs")


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _session_text(cohort: MemoraCohort, index: int) -> str:
    return "\n".join(
        f"{turn.actor}: {turn.content}" for turn in cohort.sessions[index].turns
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _source_ids(
    item: dict[str, Any],
    *,
    document_to_session: dict[str, str],
    session_texts: dict[str, str],
    source_facts: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    document_id = item.get("document_id")
    if isinstance(document_id, str) and document_id in document_to_session:
        return (document_to_session[document_id],)
    source_fact_ids = item.get("source_fact_ids")
    if isinstance(source_fact_ids, list):
        resolved = []
        for fact_id in source_fact_ids:
            fact = source_facts.get(str(fact_id), {})
            fact_document_id = fact.get("document_id")
            if (
                isinstance(fact_document_id, str)
                and fact_document_id in document_to_session
            ):
                resolved.append(document_to_session[fact_document_id])
        if resolved:
            return tuple(dict.fromkeys(resolved))
    text = str(item.get("text", "")).strip().casefold()
    if text:
        matches = [
            session_id
            for session_id, content in session_texts.items()
            if text in content.casefold()
        ]
        if len(matches) == 1:
            return (matches[0],)
    return ("hindsight-derived",)


def _fit_results(
    results: list[dict[str, Any]],
    *,
    tokenizer: Tokenizer,
    document_to_session: dict[str, str],
    session_texts: dict[str, str],
    source_facts: dict[str, dict[str, Any]],
) -> tuple[str, tuple[str, ...], tuple[dict[str, Any], ...], int]:
    blocks: list[str] = []
    sources: list[str] = []
    trace: list[dict[str, Any]] = []
    declared_tokens = 0
    for rank, item in enumerate(results, start=1):
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        source_session_ids = _source_ids(
            item,
            document_to_session=document_to_session,
            session_texts=session_texts,
            source_facts=source_facts,
        )
        source_id = source_session_ids[0]
        observed_at = str(item.get("mentioned_at") or "UNKNOWN")
        block = f"Session Date: {observed_at}\nSession Content:\n{text.strip()}"
        candidate = "\n\n".join([*blocks, block])
        candidate_tokens = len(tokenizer.encode(candidate).ids)
        if candidate_tokens > MEMORY_TOKEN_BUDGET:
            continue
        scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        final_score = scores.get("final") if isinstance(scores, dict) else None
        blocks.append(block)
        sources.extend(source_session_ids)
        trace.append(
            {
                "rank": rank,
                "score": float(final_score)
                if isinstance(final_score, int | float)
                else 0.0,
                "session_id": source_id,
                "source_id": source_id,
                "source_session_ids": list(source_session_ids),
                "result_type": str(item.get("type", "unknown")),
            }
        )
        declared_tokens = candidate_tokens
    return (
        "\n\n".join(blocks),
        tuple(dict.fromkeys(sources)),
        tuple(trace),
        declared_tokens,
    )


async def _run_cohort(
    *,
    client: Hindsight,
    run_id: str,
    cohort: MemoraCohort,
    cases: list[MemoraCase],
    tokenizer: Tokenizer,
) -> tuple[list[ContextRecord], dict[str, Any]]:
    bank_id = "pe05-" + hashlib.sha256(
        f"{run_id}\0{cohort.cohort_id}".encode()
    ).hexdigest()[:24]
    usage_rows: list[dict[str, Any]] = []
    document_to_session: dict[str, str] = {}
    session_texts: dict[str, str] = {}
    records: list[ContextRecord] = []
    ingest_started = time.perf_counter()
    cleanup_confirmed = False
    try:
        for index, session in enumerate(cohort.sessions):
            document_id = f"session-{index:06d}"
            content = _session_text(cohort, index)
            document_to_session[document_id] = session.session_id
            session_texts[session.session_id] = content
            response = await client.aretain(
                bank_id=bank_id,
                content=content,
                timestamp=_timestamp(session.observed_at),
                context=f"Memora session {session.session_id}",
                document_id=document_id,
                metadata={
                    "sequence": str(index),
                    "session_id": session.session_id,
                },
                retain_async=False,
            )
            value = _jsonable(response)
            if not isinstance(value, dict) or value.get("success") is not True:
                raise MemoraHindsightError("Hindsight retain response drifted")
            usage = value.get("usage")
            usage_rows.append(usage if isinstance(usage, dict) else {})
        ingest_ms = (time.perf_counter() - ingest_started) * 1000
        for case in cases:
            started = time.perf_counter()
            response = await client.arecall(
                bank_id=bank_id,
                query=case.question,
                max_tokens=MEMORY_TOKEN_BUDGET,
                budget="low",
                query_timestamp=case.question_at,
                include_chunks=True,
                include_source_facts=True,
            )
            value = _jsonable(response)
            raw_results = value.get("results") if isinstance(value, dict) else None
            if not isinstance(raw_results, list) or not all(
                isinstance(item, dict) for item in raw_results
            ):
                raise MemoraHindsightError("Hindsight recall response drifted")
            raw_source_facts = value.get("source_facts")
            source_facts = (
                {
                    str(key): item
                    for key, item in raw_source_facts.items()
                    if isinstance(item, dict)
                }
                if isinstance(raw_source_facts, dict)
                else {}
            )
            context, sources, trace, tokens = _fit_results(
                raw_results,
                tokenizer=tokenizer,
                document_to_session=document_to_session,
                session_texts=session_texts,
                source_facts=source_facts,
            )
            records.append(
                ContextRecord(
                    case_id=case.case_id,
                    method_id="HINDSIGHT-OSS",
                    track="NATIVE",
                    context=context,
                    source_ids=sources,
                    trace=trace,
                    declared_tokens=tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    usage={
                        "memory_query_api_calls": 1,
                        "memory_query_model_calls": "NOT_EXPOSED_BY_API",
                        "results_returned": len(raw_results),
                    },
                )
            )
        usage_totals = {
            key: sum(int(row.get(key, 0) or 0) for row in usage_rows)
            for key in (
                "cached_tokens",
                "input_tokens",
                "output_tokens",
                "thoughts_tokens",
                "total_tokens",
            )
        }
        return records, {
            "bank_id_sha256": hashlib.sha256(bank_id.encode()).hexdigest(),
            "cohort_id": cohort.cohort_id,
            "index_time_ms": round(ingest_ms, 3),
            "provider_call_count_observability": "AGGREGATE_USAGE_PER_RETAIN_ONLY",
            "question_count": len(cases),
            "recall_api_calls": len(cases),
            "retain_api_calls": len(cohort.sessions),
            "session_count": len(cohort.sessions),
            "usage": usage_totals,
        }
    finally:
        try:
            deleted = await client.adelete_bank(bank_id)
            cleanup_confirmed = bool(_jsonable(deleted))
        finally:
            if not cleanup_confirmed:
                raise MemoraHindsightError("Hindsight bank cleanup failed")


async def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    tokenizer_path: Path,
    workers: int,
    base_url: str,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if workers != 1:
        raise MemoraHindsightError("Hindsight runner requires one in-process worker")
    _require_inputs(input_path, allow_unfrozen_smoke=allow_unfrozen_smoke)
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    cohorts, cases = load_inputs(input_path)
    cases_by_cohort: dict[str, list[MemoraCase]] = {
        cohort.cohort_id: [] for cohort in cohorts
    }
    for case in cases:
        cases_by_cohort[case.cohort_id].append(case)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    client = Hindsight(base_url=base_url, timeout=300)
    records: list[ContextRecord] = []
    cohort_stats: list[dict[str, Any]] = []
    try:
        for cohort in cohorts:
            cohort_records, stats = await _run_cohort(
                client=client,
                run_id=run_id,
                cohort=cohort,
                cases=cases_by_cohort[cohort.cohort_id],
                tokenizer=tokenizer,
            )
            records.extend(cohort_records)
            cohort_stats.append(stats)
    finally:
        await client.aclose()
    by_key = {(record.case_id, record.method_id): record for record in records}
    ordered = [by_key[(case.case_id, "HINDSIGHT-OSS")] for case in cases]
    if len(ordered) != len(cases):
        raise MemoraHindsightError("Hindsight context denominator drifted")
    return cast(
        dict[str, Any],
        write_context_archive(
            output,
            run_id=run_id,
            benchmark_id="MEMORA-PREREGISTERED-60",
            records=ordered,
            metadata={
                "adapter_identity": {
                    "base_url": base_url,
                    "config_sha256": hashlib.sha256(
                        json.dumps(
                            {
                                "budget": "low",
                                "include_chunks": True,
                                "include_source_facts": True,
                                "memory_token_budget": MEMORY_TOKEN_BUDGET,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                    "runner_sha256": sha256_file(Path(__file__)),
                },
                "cohort_stats": cohort_stats,
                "failure_count": 0,
                "labels_accessed": False,
                "paper_labels_opened": False,
                "status": "PASS",
                "worker_count": workers,
            },
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--workers", type=int, choices=(1,), default=1)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        run(
            run_id=args.run_id,
            input_path=args.inputs.resolve(),
            output=args.output.resolve(),
            tokenizer_path=args.tokenizer.resolve(),
            workers=args.workers,
            base_url=args.base_url,
            freeze_manifest=args.freeze_manifest.resolve(),
            allow_unfrozen_smoke=args.allow_unfrozen_smoke,
        )
    )
    print(json.dumps({"record_count": result["record_count"], "status": result["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
