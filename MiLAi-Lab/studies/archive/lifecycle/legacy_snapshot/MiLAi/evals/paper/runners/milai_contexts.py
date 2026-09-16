"""Paper-plane context worker for frozen DG10 and DG11 Runtime wheels."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import milai
from milai.config import load_settings
from tokenizers import Tokenizer

from evals.paper.contracts import (
    ContextRecord,
    read_context_archive,
    write_context_archive,
)
from evals.paper.datasets.longmemeval import LongMemEvalCase, load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.runners.longmemeval import require_unfrozen_smoke_inputs

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
DEFAULT_ENV = ROOT / "runtime/.env"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
EXPECTED_PRODUCT_ADAPTER_SHA256 = (
    "b69a65280cdeeb6c9ece91cf96c759632961b4e1506755e818090da2d8c04fa9"
)
EXPECTED_CANDIDATE_ID = (
    "712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51"
)
WHEEL_SHA256 = {
    "DG10-FROZEN": "2a22e5d1dadc7dc8716a017845be9adc059962eb6ea653a766db048d8c499f8e",
    "DG11-FULL": "7fc0b1ab3babed5d99daca1ef92a7160ba0de729a34ccc1b1a10c5c82641e25a",
}
MCP_WHEEL_SHA256 = {
    "DG10-FROZEN": "08a08d13be792fc34cd9eb2e1b99b8b9f0a7ed00c5b5c51c30c4b85d0494ee66",
    "DG11-FULL": "7ef5b1038f38a47fdffa4c9f73e39072a0525174b7220022dbf1ae6ebfc089a2",
}
EXPECTED_MCP_HOST_SHA256 = (
    "eca20a37abdea47b9205be8a40dd365cfe1bb97b630536d2ca09c23cac588588"
)


class MiLAiContextError(RuntimeError):
    pass


@dataclass(slots=True)
class _EmbeddingCallCounter:
    warmup_calls: int = 0
    inference_calls: int = 0


class _CountingEmbeddingProvider:
    """Transparent paper-plane counter around the frozen in-process provider."""

    def __init__(self, inner: Any, counter: _EmbeddingCallCounter) -> None:
        self._inner = inner
        self._counter = counter
        self.dimensions = inner.dimensions
        self.identity = inner.identity

    def warmup(self, *args: Any, **kwargs: Any) -> Any:
        self._counter.warmup_calls += 1
        return self._inner.warmup(*args, **kwargs)

    def embed(self, text: str) -> list[float]:
        self._counter.inference_calls += 1
        return cast(list[float], self._inner.embed(text))


def _legacy_product_module() -> Any:
    return importlib.import_module("evals.benchmark.lme_product_smoke")


def _runtime_context_with_embedding_accounting(
    *, case: Any, env_file: Path, product_module: Any | None = None
) -> tuple[Any, dict[str, Any]]:
    """Count parent-process calls and derive the isolated API's fixed call path."""

    counter = _EmbeddingCallCounter()
    backend = product_module or _legacy_product_module()
    original_factory = backend._embedding_provider

    def counted_factory(settings: Any) -> _CountingEmbeddingProvider:
        return _CountingEmbeddingProvider(original_factory(settings), counter)

    mcp_host_python = str(Path(sys.executable).absolute())
    previous_mcp_host_python = os.environ.get("DG10_MCP_HOST_PYTHON")
    os.environ["DG10_MCP_HOST_PYTHON"] = mcp_host_python
    backend._embedding_provider = counted_factory
    try:
        context, raw_trace = backend._runtime_context(
            case=case,
            env_file=env_file,
            recall_limit=3,
        )
    finally:
        backend._embedding_provider = original_factory
        if previous_mcp_host_python is None:
            os.environ.pop("DG10_MCP_HOST_PYTHON", None)
        else:
            os.environ["DG10_MCP_HOST_PYTHON"] = previous_mcp_host_python
    api_warmup_calls = int(load_settings().embedding_prewarm)
    api_query_calls = 1
    accounting = {
        "api_query_calls": api_query_calls,
        "api_warmup_calls": api_warmup_calls,
        "direct_parent_inference_calls": counter.inference_calls,
        "direct_parent_warmup_calls": counter.warmup_calls,
    }
    accounting["total_calls"] = sum(accounting.values())
    enriched_trace = dict(raw_trace)
    enriched_trace["paper_embedding_accounting"] = accounting
    return context, enriched_trace


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise MiLAiContextError("LongMemEval timestamp contract drifted") from exc


def _product_case(case: LongMemEvalCase) -> Any:
    return _legacy_product_module().ProductSmokeCase(
        case_id=f"longmemeval:{case.source_id}",
        source_case_id=case.source_id,
        dataset="LONGMEMEVAL_CLEANED_500",
        category=case.category,
        question=case.question,
        answers=(),
        sessions=tuple(
            (
                session.session_id,
                "\n".join(f"{turn.role}: {turn.content}" for turn in session.turns),
            )
            for session in case.sessions
        ),
        question_at=_parse_datetime(case.question_at),
        session_observed_at=tuple(
            _parse_datetime(session.observed_at) for session in case.sessions
        ),
    )


def _trace_items(value: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_items = value.get("retrieved_items")
    if not isinstance(raw_items, list):
        raise MiLAiContextError("MiLAi retrieval trace is missing ranked items")
    records: list[dict[str, Any]] = []
    for rank, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("session_id"), str):
            raise MiLAiContextError("MiLAi ranked item contract drifted")
        reranker = item.get("reranker")
        score = (
            reranker.get("score")
            if isinstance(reranker, dict)
            and isinstance(reranker.get("score"), int | float)
            else item.get("relevance_score")
        )
        records.append(
            {
                "matched_by": item.get("matched_by"),
                "rank": rank,
                "score": float(score) if isinstance(score, int | float) else 0.0,
                "session_id": item["session_id"],
                "source_id": item["session_id"],
                "valid_time_from": item.get("valid_time_from"),
            }
        )
    return tuple(records)


def _runtime_origin() -> str:
    origin = Path(str(milai.__file__)).resolve()
    if not origin.is_relative_to(Path(sys.prefix).resolve()):
        raise MiLAiContextError("paper worker did not import the isolated frozen wheel")
    return str(origin)


def _mcp_origin() -> str:
    module = importlib.import_module("milai_mcp")
    origin = Path(str(module.__file__)).resolve()
    if not origin.is_relative_to(Path(sys.prefix).resolve()):
        raise MiLAiContextError("paper worker did not import the isolated MCP wheel")
    return str(origin)


def _checkpoint_identity(
    *,
    run_id: str,
    input_path: Path,
    method_id: str,
    env_file: Path,
    install_manifest: Path,
) -> dict[str, Any]:
    return {
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "env_sha256": sha256_file(env_file),
        "input_sha256": sha256_file(input_path),
        "install_manifest_sha256": sha256_file(install_manifest),
        "method_id": method_id,
        "mcp_host_python": str(Path(sys.executable).absolute()),
        "mcp_host_source_sha256": EXPECTED_MCP_HOST_SHA256,
        "mcp_origin": _mcp_origin(),
        "mcp_wheel_sha256": MCP_WHEEL_SHA256[method_id],
        "paper_worker_sha256": sha256_file(Path(__file__)),
        "product_adapter_sha256": EXPECTED_PRODUCT_ADAPTER_SHA256,
        "run_id": run_id,
        "runtime_origin": _runtime_origin(),
        "runtime_wheel_sha256": WHEEL_SHA256[method_id],
    }


def _resume_records(
    *,
    path: Path,
    identity: dict[str, Any],
    expected_ids: set[str],
) -> dict[str, ContextRecord]:
    if not path.exists():
        return {}
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MiLAiContextError("MiLAi context checkpoint is invalid") from exc
    if not isinstance(envelope, dict) or envelope.get("worker_identity") != identity:
        raise MiLAiContextError("MiLAi context checkpoint identity drifted")
    records = read_context_archive(path)
    by_id = {record.case_id: record for record in records}
    if len(by_id) != len(records) or not set(by_id).issubset(expected_ids):
        raise MiLAiContextError("MiLAi context checkpoint denominator drifted")
    return by_id


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    env_file: Path,
    method_id: str,
    runtime_wheel: Path,
    install_manifest: Path,
    workers: int,
    max_case_attempts: int,
    tokenizer_path: Path,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if method_id not in WHEEL_SHA256:
        raise MiLAiContextError("unknown frozen MiLAi paper method")
    if workers != 1:
        raise MiLAiContextError(
            "MiLAi requires exactly one worker per process because the frozen "
            "Runtime migration target is process-global; use at most two "
            "independent method processes for paper concurrency"
        )
    if not 1 <= max_case_attempts <= 3:
        raise MiLAiContextError("MiLAi attempt bound is invalid")
    if sha256_file(runtime_wheel) != WHEEL_SHA256[method_id]:
        raise MiLAiContextError("MiLAi Runtime wheel identity drifted")
    try:
        install = json.loads(install_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MiLAiContextError("MiLAi install manifest is invalid") from exc
    expected_install_identity = "dg10" if method_id == "DG10-FROZEN" else "dg11"
    installed_runtime = (
        install.get("wheels", {}).get("runtime")
        if isinstance(install, dict) and isinstance(install.get("wheels"), dict)
        else None
    )
    installed_mcp = (
        install.get("wheels", {}).get("mcp")
        if isinstance(install, dict) and isinstance(install.get("wheels"), dict)
        else None
    )
    if (
        not isinstance(install, dict)
        or install.get("schema") != "milai.dg11.paper-milai-install.v1"
        or install.get("status") != "PASS"
        or install.get("identity") != expected_install_identity
        or Path(str(install.get("environment"))).resolve() != Path(sys.prefix).resolve()
        or not isinstance(installed_runtime, dict)
        or installed_runtime.get("sha256") != WHEEL_SHA256[method_id]
        or not isinstance(installed_mcp, dict)
        or installed_mcp.get("sha256") != MCP_WHEEL_SHA256[method_id]
    ):
        raise MiLAiContextError("MiLAi fresh install identity drifted")
    if (
        sha256_file(ROOT / "evals/benchmark/lme_product_smoke.py")
        != EXPECTED_PRODUCT_ADAPTER_SHA256
    ):
        raise MiLAiContextError("candidate-frozen product adapter drifted")
    if (
        sha256_file(ROOT / "evals/agent_integration/mcp_host.py")
        != EXPECTED_MCP_HOST_SHA256
    ):
        raise MiLAiContextError("candidate-frozen MCP host drifted")
    if allow_unfrozen_smoke:
        require_unfrozen_smoke_inputs(input_path)
    else:
        require_paper_evaluation_ready(freeze_manifest)
    partition, cases = load_inputs(input_path)
    expected_ids = {case.source_id for case in cases}
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    identity = _checkpoint_identity(
        run_id=run_id,
        input_path=input_path,
        method_id=method_id,
        env_file=env_file,
        install_manifest=install_manifest,
    )
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MiLAiContextError(
                "completed MiLAi context archive is invalid"
            ) from exc
        records = read_context_archive(output)
        if (
            not isinstance(existing, dict)
            or existing.get("worker_identity") != identity
            or {record.case_id for record in records} != expected_ids
            or len(records) != len(expected_ids)
        ):
            raise MiLAiContextError("completed MiLAi context archive drifted")
        return existing
    checkpoint = output.with_suffix(output.suffix + ".partial")
    resumed = _resume_records(
        path=checkpoint, identity=identity, expected_ids=expected_ids
    )
    results: list[ContextRecord | None] = [
        resumed.get(case.source_id) for case in cases
    ]

    def prepare(index: int, case: LongMemEvalCase) -> tuple[int, ContextRecord]:
        benchmark_case = _product_case(case)
        last_failure: Exception | None = None
        attempts_used = 0
        for attempt in range(1, max_case_attempts + 1):
            attempts_used = attempt
            try:
                context, raw_trace = _runtime_context_with_embedding_accounting(
                    case=benchmark_case, env_file=env_file
                )
                trace = _trace_items(raw_trace)
                context_tokens = len(tokenizer.encode(context.rendered).ids)
                embedding_accounting = raw_trace.get("paper_embedding_accounting")
                if not isinstance(embedding_accounting, dict) or any(
                    not isinstance(embedding_accounting.get(key), int)
                    for key in (
                        "api_query_calls",
                        "api_warmup_calls",
                        "direct_parent_inference_calls",
                        "direct_parent_warmup_calls",
                        "total_calls",
                    )
                ):
                    raise MiLAiContextError("MiLAi embedding accounting is absent")
                reranker_calls = int(
                    any(
                        isinstance(item, dict)
                        and isinstance(item.get("reranker"), dict)
                        for item in raw_trace.get("retrieved_items", [])
                    )
                )
                return index, ContextRecord(
                    case_id=case.source_id,
                    method_id=method_id,
                    track="CONTROLLED",
                    context=context.rendered,
                    source_ids=tuple(str(item["source_id"]) for item in trace),
                    trace=trace,
                    declared_tokens=context_tokens,
                    latency_ms=float(raw_trace.get("retrieval_ms", 0.0)),
                    usage={
                        "adapter_storage_bytes": sum(
                            len(turn.content.encode())
                            for session in case.sessions
                            for turn in session.turns
                        ),
                        "embedding_provider": str(
                            (raw_trace.get("embedding") or {}).get(
                                "provider", "UNKNOWN"
                            )
                        ),
                        "embedding_call_accounting": (
                            "DIRECT_PARENT_COUNTER_PLUS_FROZEN_API_PATH_V1"
                        ),
                        "embedding_calls": int(embedding_accounting["total_calls"]),
                        "embedding_calls_api_query": int(
                            embedding_accounting["api_query_calls"]
                        ),
                        "embedding_calls_api_warmup": int(
                            embedding_accounting["api_warmup_calls"]
                        ),
                        "embedding_calls_parent_inference": int(
                            embedding_accounting["direct_parent_inference_calls"]
                        ),
                        "embedding_calls_parent_warmup": int(
                            embedding_accounting["direct_parent_warmup_calls"]
                        ),
                        "compiler_version": str(
                            getattr(context, "compiler_version", "DG10_LEGACY")
                        ),
                        "context_chars": len(context.rendered),
                        "governed_claim_count": int(
                            raw_trace.get("governed_claim_count", 0)
                        ),
                        "index_time_ms": float(raw_trace.get("ingest_ms", 0.0)),
                        "ingest_extraction_calls": 0,
                        "memory_query_model_calls": 0,
                        "memory_status": str(context.status),
                        "projected_events": int(raw_trace.get("projected_events", 0)),
                        "reranker_calls": reranker_calls,
                        "retriever_calls": 1,
                        "total_runtime_ms": float(
                            raw_trace.get("total_runtime_ms", 0.0)
                        ),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - bounded retry keeps denominator
                last_failure = exc
                retryable = any(
                    marker in str(exc)
                    for marker in (
                        "endpoint is unavailable",
                        "database cleanup failed",
                    )
                )
                if not retryable or attempt == max_case_attempts:
                    break
        assert last_failure is not None
        return index, ContextRecord(
            case_id=case.source_id,
            method_id=method_id,
            track="CONTROLLED",
            context="",
            source_ids=(),
            trace=(),
            declared_tokens=0,
            latency_ms=0.0,
            usage={
                "attempts": attempts_used,
                "failure_class": type(last_failure).__name__,
            },
            terminal_status="INFRASTRUCTURE_FAILURE",
        )

    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix=f"paper-{method_id.casefold()}"
    ) as pool:
        futures = {
            pool.submit(prepare, index, case): index
            for index, case in enumerate(cases)
            if results[index] is None
        }
        for future in as_completed(futures):
            index, record = future.result()
            results[index] = record
            completed = [item for item in results if item is not None]
            write_context_archive(
                checkpoint,
                run_id=run_id,
                benchmark_id=partition,
                records=completed,
                metadata={
                    "paper_labels_opened": False,
                    "worker_identity": identity,
                },
            )
    if any(record is None for record in results):
        raise MiLAiContextError("MiLAi context worker lost a case terminal")
    finalized = tuple(record for record in results if record is not None)
    failures = sum(record.terminal_status != "SUCCEEDED" for record in finalized)
    payload = write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=finalized,
        metadata={
            "failure_count": failures,
            "labels_accessed": False,
            "paper_labels_opened": False,
            "status": "PASS" if failures == 0 else "FAIL",
            "worker_count": workers,
            "worker_identity": identity,
        },
    )
    checkpoint.unlink(missing_ok=True)
    return cast(dict[str, Any], payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--method-id", choices=tuple(WHEEL_SHA256), required=True)
    parser.add_argument("--runtime-wheel", type=Path, required=True)
    parser.add_argument("--install-manifest", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1,), default=1)
    parser.add_argument("--max-case-attempts", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        env_file=args.env_file.resolve(),
        method_id=args.method_id,
        runtime_wheel=args.runtime_wheel.resolve(),
        install_manifest=args.install_manifest.resolve(),
        workers=args.workers,
        max_case_attempts=args.max_case_attempts,
        tokenizer_path=args.tokenizer.resolve(),
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
    )
    print(
        json.dumps(
            {
                "failure_count": result["failure_count"],
                "record_count": result["record_count"],
                "run_id": result["run_id"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
