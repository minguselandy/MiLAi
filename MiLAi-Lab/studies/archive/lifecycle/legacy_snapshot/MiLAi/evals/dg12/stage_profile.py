"""Structured stage attribution for the DG11 reference-faithful runner.

This module deliberately wraps the frozen runner at observable process boundaries.
It does not alter the DG11 Runtime wheel, canonical behavior, or benchmark inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import statistics
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from milai.observability import OperationTimer

from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = ROOT / "runtime/.env"
DEFAULT_RUNTIME_WHEEL = (
    ROOT / "var/dg11/freeze/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl"
)
DEFAULT_INSTALL_MANIFEST = (
    ROOT / "var/dg11/paper/runs/pe04-milai-smoke-20260824-001/"
    "dg11-install-manifest.json"
)


class StageProfileError(RuntimeError):
    pass


StageRecorder = OperationTimer


def _portable_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _finite_duration(value: object, *, field: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise StageProfileError(f"{field} must be a numeric duration")
    duration = float(value)
    if duration < 0.0:
        raise StageProfileError(f"{field} must not be negative")
    return duration


def _distribution(values: list[float], *, outer_total_ms: float) -> dict[str, float]:
    if not values:
        raise StageProfileError("a deep-stage distribution must not be empty")
    total = sum(values)
    return {
        "total_ms": round(total, 3),
        "median_case_ms": round(statistics.median(values), 3),
        "minimum_case_ms": round(min(values), 3),
        "maximum_case_ms": round(max(values), 3),
        "share_of_outer": round(total / outer_total_ms, 6),
    }


def build_deep_anchor_profile(source: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce a valid EH02 terminal to payload-free deep-stage accounting."""

    if source.get("schema") != "milai.dg12.eh02-persistent-product.v1":
        raise StageProfileError("deep anchor has an unsupported schema")
    if source.get("status") != "PASS":
        raise StageProfileError("deep anchor must be a successful product run")
    records = source.get("records")
    if not isinstance(records, list) or not records:
        raise StageProfileError("deep anchor has no case records")

    case_rows: list[dict[str, Any]] = []
    stage_values: dict[str, list[float]] = {}
    query_totals: list[float] = []
    outer_totals: list[float] = []
    outer_residuals: list[float] = []
    runtime_uninstrumented: list[float] = []
    stage_counts: dict[str, int] = {}
    equivalence_passes = 0

    for record_index, raw_record in enumerate(records, start=1):
        if not isinstance(raw_record, dict):
            raise StageProfileError("deep anchor record must be an object")
        usage = raw_record.get("reuse_product_usage")
        metrics = usage.get("stage_metrics") if isinstance(usage, dict) else None
        durations = metrics.get("durations_ms") if isinstance(metrics, dict) else None
        counts = metrics.get("counts") if isinstance(metrics, dict) else None
        if not isinstance(durations, dict) or not isinstance(counts, dict):
            raise StageProfileError("deep anchor record lacks reuse stage metrics")

        outer_ms = _finite_duration(
            raw_record.get("reuse_retrieval_ms"),
            field="reuse_retrieval_ms",
        )
        query_total_ms = _finite_duration(
            durations.get("query_total_ms"), field="query_total_ms"
        )
        if query_total_ms > outer_ms + 0.001:
            raise StageProfileError("query_total_ms exceeds its outer retrieval wall")

        sibling_durations: dict[str, float] = {}
        for stage, value in durations.items():
            if stage == "query_total_ms":
                continue
            sibling_durations[str(stage)] = _finite_duration(
                value, field=f"durations_ms.{stage}"
            )
        sibling_total_ms = sum(sibling_durations.values())
        if sibling_total_ms > query_total_ms + 0.001:
            raise StageProfileError("nested Runtime stages overlap query_total_ms")

        for stage in set(stage_values) | set(sibling_durations):
            stage_values.setdefault(stage, [0.0] * (record_index - 1)).append(
                sibling_durations.get(stage, 0.0)
            )
        for stage, value in counts.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise StageProfileError(
                    f"counts.{stage} must be a non-negative integer"
                )
            stage_counts[str(stage)] = stage_counts.get(str(stage), 0) + value

        outer_residual_ms = outer_ms - query_total_ms
        runtime_uninstrumented_ms = query_total_ms - sibling_total_ms
        case_id = str(raw_record.get("case_id", record_index))
        case_rows.append(
            {
                "ordinal": int(raw_record.get("ordinal", record_index)),
                "case_id_sha256": hashlib.sha256(case_id.encode()).hexdigest(),
                "outer_retrieval_ms": round(outer_ms, 3),
                "query_total_ms": round(query_total_ms, 3),
                "recent_canonical_ms": round(
                    sibling_durations.get("recent_canonical_ms", 0.0), 3
                ),
                "fts_ms": round(sibling_durations.get("fts_ms", 0.0), 3),
                "reranker_ms": round(sibling_durations.get("reranker_ms", 0.0), 3),
                "query_embedding_ms": round(
                    sibling_durations.get("query_embedding_ms", 0.0), 3
                ),
                "vector_ms": round(sibling_durations.get("vector_ms", 0.0), 3),
                "runtime_uninstrumented_ms": round(runtime_uninstrumented_ms, 3),
                "openworker_mcp_adapter_residual_ms": round(outer_residual_ms, 3),
            }
        )
        query_totals.append(query_total_ms)
        outer_totals.append(outer_ms)
        outer_residuals.append(outer_residual_ms)
        runtime_uninstrumented.append(runtime_uninstrumented_ms)
        equivalence = raw_record.get("equivalence")
        if (
            raw_record.get("reuse_equivalent") is True
            and isinstance(equivalence, dict)
            and equivalence
            and all(value is True for value in equivalence.values())
        ):
            equivalence_passes += 1

    outer_total_ms = sum(outer_totals)
    query_total_ms = sum(query_totals)
    runtime_sibling_ms = sum(sum(values) for values in stage_values.values())
    explained_ms = (
        runtime_sibling_ms + sum(runtime_uninstrumented) + sum(outer_residuals)
    )
    named_stages = {
        stage: _distribution(
            [row.get(stage, 0.0) for row in case_rows],
            outer_total_ms=outer_total_ms,
        )
        for stage in (
            "recent_canonical_ms",
            "fts_ms",
            "reranker_ms",
            "query_embedding_ms",
            "vector_ms",
        )
    }
    named_stages["runtime_uninstrumented_ms"] = _distribution(
        runtime_uninstrumented, outer_total_ms=outer_total_ms
    )
    named_stages["openworker_mcp_adapter_residual_ms"] = _distribution(
        outer_residuals, outer_total_ms=outer_total_ms
    )

    target_ms = 31_548.0
    return {
        "anchor_kind": "HISTORICAL_SINGLE_BLOCK_NOT_A_CURRENT_REPLICATE",
        "case_count": len(case_rows),
        "equivalent_case_count": equivalence_passes,
        "outer_retrieval": _distribution(outer_totals, outer_total_ms=outer_total_ms),
        "runtime_query_total": _distribution(
            query_totals, outer_total_ms=outer_total_ms
        ),
        "named_stage_distributions": named_stages,
        "all_runtime_sibling_stage_totals_ms": {
            stage: round(sum(values), 3)
            for stage, values in sorted(stage_values.items())
        },
        "stage_call_counts": dict(sorted(stage_counts.items())),
        "non_overlapping_accounting": {
            "outer_retrieval_ms": round(outer_total_ms, 3),
            "runtime_sibling_stage_ms": round(runtime_sibling_ms, 3),
            "runtime_uninstrumented_ms": round(sum(runtime_uninstrumented), 3),
            "openworker_mcp_adapter_residual_ms": round(sum(outer_residuals), 3),
            "explained_ms": round(explained_ms, 3),
            "explained_ratio": round(explained_ms / outer_total_ms, 6),
            "runtime_nested_span_ratio": round(runtime_sibling_ms / query_total_ms, 6),
            "outer_residual_method": "outer_retrieval_ms - Runtime query_total_ms",
        },
        "target": {
            "ten_case_outer_retrieval_max_ms": target_ms,
            "anchor_observed_ms": round(outer_total_ms, 3),
            "anchor_over_target_ms": round(outer_total_ms - target_ms, 3),
            "anchor_target_met": outer_total_ms <= target_ms,
            "required_speedup_over_anchor": round(outer_total_ms / target_ms, 6),
        },
        "arithmetic_elimination_bounds_not_mechanism_evidence": {
            stage: round(outer_total_ms - distribution["total_ms"], 3)
            for stage, distribution in named_stages.items()
        },
        "case_distribution": case_rows,
        "payload_policy": {
            "raw_context_emitted": False,
            "raw_query_emitted": False,
            "source_ids_emitted": False,
            "case_identity": "SHA256_ONLY",
        },
    }


class _ProfiledEmbeddingProvider:
    def __init__(self, inner: Any, recorder: StageRecorder) -> None:
        self._inner = inner
        self._recorder = recorder
        self.dimensions = inner.dimensions
        self.identity = inner.identity

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def warmup(self, *args: Any, **kwargs: Any) -> Any:
        return self._recorder.call(
            "embedding_warm_ms", self._inner.warmup, *args, **kwargs
        )

    def embed(self, text: str) -> list[float]:
        return cast(
            list[float],
            self._recorder.call("embedding_inference_ms", self._inner.embed, text),
        )


def _rusage() -> dict[str, float]:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "cpu_user_s": own.ru_utime + children.ru_utime,
        "cpu_system_s": own.ru_stime + children.ru_stime,
        "max_rss_kib": float(max(own.ru_maxrss, children.ru_maxrss)),
    }


def _rusage_delta(
    before: Mapping[str, float], after: Mapping[str, float]
) -> dict[str, float]:
    return {
        "cpu_user_s": round(after["cpu_user_s"] - before["cpu_user_s"], 6),
        "cpu_system_s": round(after["cpu_system_s"] - before["cpu_system_s"], 6),
        # ru_maxrss is a high-water mark, so report the observed peak rather than a fake delta.
        "observed_max_rss_kib": round(after["max_rss_kib"], 3),
    }


def _reranker_duration(raw_trace: Mapping[str, Any]) -> float:
    durations: list[float] = []
    items = raw_trace.get("retrieved_items")
    if not isinstance(items, list):
        return 0.0
    for item in items:
        reranker = item.get("reranker") if isinstance(item, dict) else None
        duration = reranker.get("duration_ms") if isinstance(reranker, dict) else None
        if isinstance(duration, int | float) and not isinstance(duration, bool):
            durations.append(float(duration))
    # The Runtime repeats one execution identity on each ranked result.
    return round(max(durations, default=0.0), 3)


def _profile_summary(
    *, recorder: StageRecorder, raw_trace: Mapping[str, Any], wall_ms: float
) -> dict[str, Any]:
    runtime_ms = float(raw_trace.get("total_runtime_ms", 0.0))
    ingest_ms = float(raw_trace.get("ingest_ms", 0.0))
    retrieval_ms = float(raw_trace.get("retrieval_ms", 0.0))
    context_compile_ms = recorder.duration("context_compile_ms")
    database_ms = recorder.duration("db_create_or_clone_ms")
    migration_ms = recorder.duration("migration_ms")
    setup_ms = max(
        0.0,
        runtime_ms
        - database_ms
        - migration_ms
        - ingest_ms
        - retrieval_ms
        - context_compile_ms,
    )
    cleanup_ms = max(0.0, wall_ms - runtime_ms)
    top_level = {
        "db_create_or_clone_ms": database_ms,
        "migration_ms": migration_ms,
        "runtime_setup_ms": round(setup_ms, 3),
        "governed_ingest_and_projection_ms": round(ingest_ms, 3),
        "query_and_mcp_ms": round(retrieval_ms, 3),
        "context_compile_ms": context_compile_ms,
        "cleanup_ms": round(cleanup_ms, 3),
    }
    attributed_ms = sum(top_level.values())
    unattributed_ms = max(0.0, wall_ms - attributed_ms)
    accounting = raw_trace.get("paper_embedding_accounting")
    logical_items = (
        int(accounting.get("total_calls", 0)) if isinstance(accounting, dict) else 0
    )
    return {
        "wall_time_ms": round(wall_ms, 3),
        "attributed_ms": round(attributed_ms, 3),
        "attribution_ratio": round(attributed_ms / wall_ms, 6) if wall_ms > 0 else 0.0,
        "unattributed_ms": round(unattributed_ms, 3),
        "top_level_non_overlapping": top_level,
        "nested_stage_metrics": {
            "api_start_ms": recorder.duration("api_start_ms"),
            "worker_start_ms": recorder.duration("worker_start_ms"),
            "mcp_start_ms": None,
            "embedding_load_ms": recorder.duration("embedding_load_ms"),
            "embedding_warm_ms": recorder.duration("embedding_warm_ms"),
            "reranker_load_ms": None,
            "reranker_warm_ms": None,
            "evidence_ms": recorder.duration("evidence_ms"),
            "proposal_ms": recorder.duration("proposal_ms"),
            "review_ms": recorder.duration("review_ms"),
            "fts_projection_ms": recorder.duration("fts_projection_ms"),
            "vector_projection_ms": recorder.duration("vector_projection_ms"),
            "embedding_logical_items": logical_items,
            "embedding_inference_batches": logical_items,
            "embedding_cache_hits": 0,
            "embedding_inference_ms": recorder.duration("embedding_inference_ms"),
            "projection_write_ms": None,
            "outbox_drain_ms": recorder.duration("outbox_drain_ms"),
            "mcp_transport_ms": recorder.duration("mcp_transport_ms"),
            "query_embedding_ms": None,
            "fts_ms": None,
            "vector_ms": None,
            "fusion_ms": None,
            "canonical_gate_ms": None,
            "reranker_ms": _reranker_duration(raw_trace),
            "context_compile_ms": context_compile_ms,
            "query_total_ms": round(retrieval_ms + context_compile_ms, 3),
            "reset_ms": None,
            "cleanup_ms": round(cleanup_ms, 3),
            "answer_ms": 0.0,
            "judge_ms": 0.0,
        },
        "unavailable_nested_metrics": {
            "mcp_start_ms": "DG11 helper combines process start, initialize, tools/call, and teardown",
            "reranker_load_ms": "frozen API exposes reranker execution but not model-load timing",
            "reranker_warm_ms": "frozen API exposes no separate reranker warmup event",
            "projection_write_ms": "frozen Worker combines fragment read, inference, write, and watermark",
            "query_embedding_ms": "query embedding executes inside the frozen API subprocess",
            "fts_ms": "frozen retrieval trace records only total retrieval duration",
            "vector_ms": "frozen retrieval trace records only total retrieval duration",
            "fusion_ms": "frozen retrieval trace records only total retrieval duration",
            "canonical_gate_ms": "frozen retrieval trace records only total retrieval duration",
            "reset_ms": "reference-faithful mode drops the isolated database instead of resetting a slot",
        },
        "call_counts": {
            key: int(value) for key, value in sorted(recorder.counts.items())
        },
    }


@contextmanager
def _instrument(recorder: StageRecorder) -> Iterator[None]:
    from evals.benchmark import lme_product_smoke as product

    original_create_database = product._create_database
    original_upgrade = product.command.upgrade
    original_wait_api = product.e2e._wait_api
    original_database_init = product.e2e.Database.__init__
    original_worker_init = product.e2e.FoundationWorker.__init__
    original_worker_process = product.e2e.FoundationWorker._process
    original_worker_run_once = product.e2e.FoundationWorker.run_once
    original_embedding_factory = product._embedding_provider
    original_post = product.e2e._HttpClient.post
    original_review = product.e2e._review
    original_mcp = product.e2e._mcp
    original_compile = product.prepare_compact_prefetch
    original_stop_api = product.e2e._stop_api
    original_drop_database = product._drop_database

    def create_database(*args: Any, **kwargs: Any) -> Any:
        return recorder.call(
            "db_create_or_clone_ms", original_create_database, *args, **kwargs
        )

    def upgrade(*args: Any, **kwargs: Any) -> Any:
        return recorder.call("migration_ms", original_upgrade, *args, **kwargs)

    def wait_api(*args: Any, **kwargs: Any) -> Any:
        return recorder.call("api_start_ms", original_wait_api, *args, **kwargs)

    def database_init(instance: Any, *args: Any, **kwargs: Any) -> None:
        recorder.call(
            "worker_start_ms", original_database_init, instance, *args, **kwargs
        )

    def worker_init(instance: Any, *args: Any, **kwargs: Any) -> None:
        recorder.call(
            "worker_start_ms", original_worker_init, instance, *args, **kwargs
        )

    def worker_process(instance: Any, projection: str, event: Any) -> Any:
        stage = f"{projection}_projection_ms"
        return recorder.call(
            stage, original_worker_process, instance, projection, event
        )

    def worker_run_once(instance: Any) -> int:
        return int(recorder.call("outbox_drain_ms", original_worker_run_once, instance))

    def embedding_factory(settings: Any) -> _ProfiledEmbeddingProvider:
        inner = recorder.call("embedding_load_ms", original_embedding_factory, settings)
        return _ProfiledEmbeddingProvider(inner, recorder)

    def post(instance: Any, path: str, **kwargs: Any) -> Any:
        stage = None
        if path == "/v1/evidence":
            stage = "evidence_ms"
        elif path == "/v1/proposals":
            stage = "proposal_ms"
        elif path == "/v1/memory/query":
            stage = "query_http_ms"
        if stage is None:
            return original_post(instance, path, **kwargs)
        return recorder.call(stage, original_post, instance, path, **kwargs)

    def review(*args: Any, **kwargs: Any) -> Any:
        return recorder.call("review_ms", original_review, *args, **kwargs)

    def mcp(*args: Any, **kwargs: Any) -> Any:
        return recorder.call("mcp_transport_ms", original_mcp, *args, **kwargs)

    def compile_context(*args: Any, **kwargs: Any) -> Any:
        return recorder.call("context_compile_ms", original_compile, *args, **kwargs)

    def stop_api(*args: Any, **kwargs: Any) -> Any:
        return recorder.call("api_stop_ms", original_stop_api, *args, **kwargs)

    def drop_database(*args: Any, **kwargs: Any) -> Any:
        return recorder.call(
            "database_drop_ms", original_drop_database, *args, **kwargs
        )

    with ExitStack() as stack:
        stack.enter_context(patch.object(product, "_create_database", create_database))
        stack.enter_context(patch.object(product.command, "upgrade", upgrade))
        stack.enter_context(patch.object(product.e2e, "_wait_api", wait_api))
        stack.enter_context(
            patch.object(product.e2e.Database, "__init__", database_init)
        )
        stack.enter_context(
            patch.object(product.e2e.FoundationWorker, "__init__", worker_init)
        )
        stack.enter_context(
            patch.object(product.e2e.FoundationWorker, "_process", worker_process)
        )
        stack.enter_context(
            patch.object(product.e2e.FoundationWorker, "run_once", worker_run_once)
        )
        stack.enter_context(
            patch.object(product, "_embedding_provider", embedding_factory)
        )
        stack.enter_context(patch.object(product.e2e._HttpClient, "post", post))
        stack.enter_context(patch.object(product.e2e, "_review", review))
        stack.enter_context(patch.object(product.e2e, "_mcp", mcp))
        stack.enter_context(
            patch.object(product, "prepare_compact_prefetch", compile_context)
        )
        stack.enter_context(patch.object(product.e2e, "_stop_api", stop_api))
        stack.enter_context(patch.object(product, "_drop_database", drop_database))
        yield


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    case_index: int,
    env_file: Path,
    runtime_wheel: Path,
    install_manifest: Path,
) -> dict[str, Any]:
    from evals.benchmark import lme_product_smoke as product
    from evals.paper.runners import extended_milai_contexts as extended
    from evals.paper.runners import milai_contexts as core

    if output.exists():
        raise StageProfileError("DG12 profile output is write-once")
    if not output.parent.is_dir():
        raise StageProfileError("DG12 run directory must exist before profiling")
    extended._validate_install(runtime_wheel, install_manifest)
    partition, cases = extended.load_extended_inputs(input_path)
    if "SMOKE" not in partition:
        raise StageProfileError(
            "BHE00 is restricted to an already opened unlabeled smoke input"
        )
    if not 0 <= case_index < len(cases):
        raise StageProfileError("case_index is outside the smoke denominator")
    case = cases[case_index]
    benchmark_case = extended._product_case(case, partition)
    recorder = StageRecorder()
    resources_before = _rusage()
    started = time.perf_counter()
    with _instrument(recorder):
        context, raw_trace = core._runtime_context_with_embedding_accounting(
            case=benchmark_case, env_file=env_file
        )
    wall_ms = (time.perf_counter() - started) * 1_000
    resources_after = _rusage()
    summary = _profile_summary(recorder=recorder, raw_trace=raw_trace, wall_ms=wall_ms)
    payload = {
        "schema": "milai.dg12.stage-profile.v1",
        "run_id": run_id,
        "work_package": "DG12-BHE00",
        "mode": "REFERENCE_FAITHFUL",
        "status": "PASS" if summary["attribution_ratio"] >= 0.95 else "FAIL",
        "candidate_id": core.EXPECTED_CANDIDATE_ID,
        "candidate_modified": False,
        "benchmark_id": partition,
        "case_id": case.case_id,
        "case_index": case_index,
        "paper_labels_opened": False,
        "labels_accessed": False,
        "answer_calls": 0,
        "judge_calls": 0,
        "hidden_provider_calls": 0,
        "context_sha256": hashlib.sha256(context.rendered.encode()).hexdigest(),
        "context_chars": len(context.rendered),
        "retrieved_session_ids": list(raw_trace.get("retrieved_session_ids", [])),
        "stage_profile": summary,
        "resources": _rusage_delta(resources_before, resources_after),
        "identity": {
            "input_sha256": sha256_file(input_path),
            "env_sha256": sha256_file(env_file),
            "runtime_wheel_sha256": sha256_file(runtime_wheel),
            "install_manifest_sha256": sha256_file(install_manifest),
            "runner_sha256": sha256_file(Path(__file__)),
            "reference_adapter_sha256": sha256_file(Path(product.__file__)),
        },
        "instrumentation_changes": [
            {
                "path": "evals/dg12/stage_profile.py",
                "change_type": "created",
                "purpose": "wrap faithful runner boundaries and emit structured stage metrics",
            },
            {
                "path": "tests/test_dg12_stage_profile.py",
                "change_type": "created",
                "purpose": "validate non-overlapping attribution and missing-metric disclosure",
            },
        ],
        "raw_reference_trace": raw_trace,
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def _reference_main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-index", type=int, default=0)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--runtime-wheel", type=Path, default=DEFAULT_RUNTIME_WHEEL)
    parser.add_argument(
        "--install-manifest", type=Path, default=DEFAULT_INSTALL_MANIFEST
    )
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs,
        output=args.output,
        case_index=args.case_index,
        env_file=args.env_file,
        runtime_wheel=args.runtime_wheel,
        install_manifest=args.install_manifest,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _materialization_main() -> None:
    from evals.dg12.materialization_profile import (
        SUPPORTED_CELLS,
        run_materialization_profile,
    )

    parser = argparse.ArgumentParser(
        description="Run matched installed-product cold materialization attribution"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--python-executable", type=Path, required=True)
    parser.add_argument("--product-manifest-sha256", required=True)
    parser.add_argument("--temporary-root", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=12025)
    parser.add_argument("--cell", action="append", choices=SUPPORTED_CELLS)
    parser.add_argument("--worker-timeout-seconds", type=int, default=1800)
    args = parser.parse_args(sys.argv[2:])
    result = run_materialization_profile(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        env_file=args.env_file.resolve(),
        # Keep the venv entrypoint symlink intact; resolving it selects the base
        # interpreter and silently drops the clean installed-product environment.
        python_executable=args.python_executable.absolute(),
        product_manifest_sha256=args.product_manifest_sha256,
        temporary_root=args.temporary_root.resolve(),
        repeats=args.repeats,
        seed=args.seed,
        cells=tuple(args.cell or SUPPORTED_CELLS),
        worker_timeout_seconds=args.worker_timeout_seconds,
    )
    print(
        json.dumps(
            {
                "minimum_explained_projection_ratio": result[
                    "minimum_explained_projection_ratio"
                ],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


def run_deep_anchor_profile(
    *,
    run_id: str,
    source_path: Path,
    output: Path,
    current_product_manifest_sha256: str,
) -> dict[str, Any]:
    if output.exists():
        raise StageProfileError("DG12 deep profile output is write-once")
    if not output.parent.is_dir():
        raise StageProfileError("DG12 deep run directory must exist before profiling")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise StageProfileError("DG12 deep anchor must be a JSON object")
    profile = build_deep_anchor_profile(source)
    product = source.get("product")
    source_manifest = (
        product.get("manifest_sha256") if isinstance(product, dict) else None
    )
    payload = {
        "schema": "milai.dg12.deep-recovery-profile.v1",
        "run_id": run_id,
        "work_package": "DG12-PD02-LANE-B-DEEP",
        "mode": "READ_ONLY_POSTHOC_VALID_ANCHOR",
        "status": "TERMINAL_TARGET_MISS",
        "paper_labels_opened": False,
        "labels_accessed": False,
        "answer_calls": 0,
        "judge_calls": 0,
        "hidden_provider_calls": 0,
        "current_product": {
            "manifest_sha256": current_product_manifest_sha256,
            "matched_blocks_required": 3,
            "matched_blocks_observed": 0,
            "target_measurement": "NOT_RUN_NO_RETAINED_CANONICAL_PROJECTION_STATE",
        },
        "historical_anchor": {
            "path": _portable_path(source_path),
            "sha256": sha256_file(source_path),
            "run_id": source.get("run_id"),
            "product_manifest_sha256": source_manifest,
            "same_as_current_product": source_manifest
            == current_product_manifest_sha256,
            "profile": profile,
        },
        "gates": {
            "historical_anchor_equivalence": (
                "PASS"
                if profile["case_count"] == profile["equivalent_case_count"]
                else "FAIL"
            ),
            "historical_anchor_explained_ratio": (
                "PASS"
                if profile["non_overlapping_accounting"]["explained_ratio"] >= 0.95
                else "FAIL"
            ),
            "current_product_three_matched_blocks": "FAIL",
            "current_product_target": "NOT_MEASURED",
            "one_stage_replacement": "NOT_RUN_NO_CURRENT_RETAINED_STATE",
        },
        "terminal_reason": (
            "NO_RETAINED_HORIZON_DATABASE_OR_PROJECTION_CHECKPOINT_AND_"
            "FRESH_MATERIALIZATION_DISALLOWED_AFTER_BOUNDED_COLD_CLOSURE"
        ),
        "claim_policy": {
            "current_product_deep_speed_claim": "REMOVED_NOT_MEASURED",
            "historical_anchor_use": "BOTTLENECK_CHARACTERIZATION_ONLY",
            "arithmetic_elimination_bounds": "NOT_CAUSAL_OR_REPLACEMENT_EVIDENCE",
        },
        "identity": {
            "source_sha256": sha256_file(source_path),
            "analyzer_sha256": sha256_file(Path(__file__)),
        },
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def _deep_anchor_main() -> None:
    parser = argparse.ArgumentParser(
        description="Reduce a valid historical deep block without reading payloads"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--current-product-manifest-sha256", required=True)
    args = parser.parse_args(sys.argv[2:])
    result = run_deep_anchor_profile(
        run_id=args.run_id,
        source_path=args.source.resolve(),
        output=args.output.resolve(),
        current_product_manifest_sha256=args.current_product_manifest_sha256,
    )
    print(
        json.dumps(
            {
                "matched_blocks_observed": result["current_product"][
                    "matched_blocks_observed"
                ],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "materialization":
        _materialization_main()
    elif len(sys.argv) > 1 and sys.argv[1] == "deep-anchor":
        _deep_anchor_main()
    else:
        _reference_main()


if __name__ == "__main__":
    main()
