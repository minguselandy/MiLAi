"""Matched cold-materialization attribution over an installed MiLAi product."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

from evals.datasets.text import retrieval_query
from evals.harness import HistoryItem, TemporaryResourceSpec, WorkloadHistory
from evals.harness.infrastructure import seeded_counterbalanced_schedule
from evals.harness.product_runtime import (
    ProductEvaluationRuntime,
    ProductRuntimeConfig,
    grouped_history,
    read_environment,
    rewrite_database_url,
)
from evals.paper.datasets.extended import ExtendedCase, load_extended_inputs
from evals.paper.identity import sha256_file

CELL_M2 = "M2_PROJECTION_DRAIN_REAL"
CELL_M3 = "M3_PROJECTION_DRAIN_VECTOR_HIT"
SUPPORTED_CELLS = (CELL_M2, CELL_M3)


class MaterializationProfileError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WorkloadUnit:
    history: WorkloadHistory
    question_id: str
    query: str
    scope: dict[str, list[str]]


class ReplayEmbeddingProvider:
    """Evaluation-only exact-vector hit simulator for the registered M3 cell."""

    def __init__(self, identity: Any, vectors: Mapping[str, list[float]]) -> None:
        self.identity = identity
        self.dimensions = int(identity.projection_dimensions)
        self._vectors = vectors
        self.logical_hits = 0

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text], 1)[0]

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        if batch_size <= 0:
            raise ValueError("embedding batch size must be positive")
        result: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).hexdigest()
            try:
                vector = self._vectors[digest]
            except KeyError as exc:
                raise MaterializationProfileError(
                    "M3 vector cache missed a deterministic fragment"
                ) from exc
            result.append(vector)
        self.logical_hits += len(texts)
        return result


def _safe_environment(values: Mapping[str, str]) -> dict[str, str]:
    result = {
        name: value for name, value in os.environ.items() if not name.startswith("MILAI_")
    }
    result.update(values)
    return result


def _database_environment(
    source: Mapping[str, str], database_name: str, *, blob_root: Path
) -> dict[str, str]:
    result = dict(source)
    for name in (
        "MILAI_DATABASE_URL",
        "MILAI_STEWARD_DATABASE_URL",
        "MILAI_WORKER_DATABASE_URL",
        "MILAI_MIGRATION_DATABASE_URL",
        "MILAI_AUDIT_DATABASE_URL",
    ):
        result[name] = rewrite_database_url(result[name], database_name)
    result["MILAI_POSTGRES_DB"] = database_name
    result["MILAI_BLOB_ROOT"] = str(blob_root.resolve())
    result["MILAI_WORKER_EVENT_LIMIT"] = "10000"
    result["MILAI_LOG_FORMAT"] = "json"
    return result


def _admin_url(environment: Mapping[str, str]) -> str:
    return rewrite_database_url(environment["MILAI_MIGRATION_DATABASE_URL"], "postgres")


def _drop_database(admin_url: str, database_name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database_name,),
        )
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
        )


def _clone_database(admin_url: str, source: str, target: str) -> float:
    started = time.perf_counter()
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} WITH TEMPLATE {} OWNER milai_owner").format(
                sql.Identifier(target), sql.Identifier(source)
            )
        )
    return round((time.perf_counter() - started) * 1_000, 3)


def _database_snapshot(
    environment: Mapping[str, str], *, tenant_id: str
) -> dict[str, Any]:
    owner_url = environment["MILAI_MIGRATION_DATABASE_URL"]
    with psycopg.connect(owner_url) as connection:
        canonical = connection.execute(
            "SELECT COALESCE(max(outbox_sequence), 0), count(*) "
            "FROM milai.outbox_event WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        watermarks = connection.execute(
            "SELECT projection_name, last_contiguous_outbox_sequence "
            "FROM milai.index_watermark WHERE tenant_id = %s ORDER BY projection_name",
            (tenant_id,),
        ).fetchall()
        counts = connection.execute(
            "SELECT "
            "(SELECT count(*) FROM milai.claim WHERE tenant_id = %s), "
            "(SELECT count(*) FROM milai.search_document_fragment WHERE tenant_id = %s), "
            "(SELECT count(*) FROM milai.search_embedding_window_128 WHERE tenant_id = %s), "
            "(SELECT count(*) FROM milai.projection_delivery "
            " WHERE tenant_id = %s AND state = 'DEAD_LETTER'), "
            "pg_database_size(current_database())",
            (tenant_id, tenant_id, tenant_id, tenant_id),
        ).fetchone()
    assert canonical is not None and counts is not None
    return {
        "canonical_snapshot": int(canonical[0]),
        "outbox_events": int(canonical[1]),
        "claim_count": int(counts[0]),
        "fts_fragment_rows": int(counts[1]),
        "vector_fragment_rows": int(counts[2]),
        "dead_letters": int(counts[3]),
        "database_bytes": int(counts[4]),
        "watermarks": {str(name): int(value) for name, value in watermarks},
    }


def _workload_units(path: Path) -> tuple[str, tuple[WorkloadUnit, ...]]:
    partition, cases = load_extended_inputs(path)
    if partition != "HORIZON-OFFICIAL-SAMPLE-10-SMOKE" or len(cases) != 10:
        raise MaterializationProfileError(
            "materialization profile requires the frozen ten-case Horizon smoke workload"
        )
    units = tuple(_workload_unit(case, partition) for case in cases)
    if sum(len(grouped_history(unit.history)) for unit in units) != 943:
        raise MaterializationProfileError("frozen Horizon session denominator drifted")
    return partition, units


def _history_id(case: ExtendedCase) -> str:
    first = case.sessions[0].session_id
    marker = "-session-"
    if marker not in first:
        raise MaterializationProfileError("Horizon session identity drifted")
    return first.rsplit(marker, 1)[0]


def _workload_unit(case: ExtendedCase, partition: str) -> WorkloadUnit:
    history_id = _history_id(case)
    items: list[HistoryItem] = []
    for session_ordinal, session in enumerate(case.sessions):
        for turn_ordinal, turn in enumerate(session.turns):
            items.append(
                HistoryItem(
                    item_id=(
                        f"{history_id}:{session_ordinal:04d}:{turn_ordinal:04d}"
                    ),
                    session_id=session.session_id,
                    role=turn.role,  # type: ignore[arg-type]
                    content=turn.content.replace("\x00", " "),
                    occurred_at=session.observed_at,
                    metadata={"source_index": turn_ordinal},
                )
            )
    history = WorkloadHistory(
        workload_id=history_id,
        dataset_id=partition,
        items=tuple(items),
        metadata={
            "claim_subject_namespace": history_id,
            "claim_subject_index_width": 3,
            "claim_predicate": "benchmark.memory.session",
            "claim_type": "BENCHMARK_MEMORY",
        },
    )
    scope = {"project_ids": [f"eval-{history.fingerprint[:24]}"]}
    return WorkloadUnit(
        history=history,
        question_id=case.case_id,
        query=retrieval_query(case.question, partition),
        scope=scope,
    )


def _fragment_texts(units: Sequence[WorkloadUnit]) -> tuple[str, ...]:
    from milai.domain.retrieval_projection import derive_projection_fragments

    texts: list[str] = []
    for unit in units:
        for _session_id, _observed_at, content in grouped_history(unit.history):
            texts.extend(
                fragment.content_text
                for fragment in derive_projection_fragments(content)
            )
    return tuple(texts)


def _embedding_provider(environment: Mapping[str, str]) -> Any:
    from milai.adapters import (
        BoundedEmbeddingProvider,
        DeterministicHashEmbedding,
        OnnxSentenceTransformerEmbedding,
        SentenceTransformerEmbedding,
    )
    from milai.config.settings import load_settings

    settings = load_settings(environment)
    inner: Any
    if settings.embedding_provider == "onnx_sentence_transformer":
        assert settings.embedding_model_path is not None
        inner = OnnxSentenceTransformerEmbedding(
            settings.embedding_model_path,
            model_id=settings.embedding_model_id,
            source_dimensions=settings.embedding_source_dimensions,
            projection_dimensions=settings.embedding_projection_dimensions,
        )
    elif settings.embedding_provider == "sentence_transformers":
        assert settings.embedding_model_path is not None
        inner = SentenceTransformerEmbedding(
            settings.embedding_model_path,
            model_id=settings.embedding_model_id,
            source_dimensions=settings.embedding_source_dimensions,
            projection_dimensions=settings.embedding_projection_dimensions,
        )
    else:
        inner = DeterministicHashEmbedding()
    return BoundedEmbeddingProvider(
        inner, max_concurrency=settings.embedding_max_concurrency
    )


def _precompute_vectors(
    environment: Mapping[str, str], units: Sequence[WorkloadUnit]
) -> tuple[dict[str, list[float]], Any, dict[str, Any]]:
    texts = _fragment_texts(units)
    unique_texts = tuple(dict.fromkeys(texts))
    provider = _embedding_provider(environment)
    warmup = provider.warmup()
    started = time.perf_counter()
    from milai.config.settings import load_settings

    batch_size = load_settings(environment).embedding_batch_size
    vectors = provider.embed_many(list(unique_texts), batch_size)
    duration_ms = (time.perf_counter() - started) * 1_000
    cache = {
        hashlib.sha256(text.encode()).hexdigest(): vector
        for text, vector in zip(unique_texts, vectors, strict=True)
    }
    if len(cache) != len(unique_texts):
        raise MaterializationProfileError("fragment digest collision detected")
    usage = provider.usage()
    return cache, provider.identity, {
        "classification": "EVALUATION_ONLY_M3_SIMULATION_SETUP",
        "logical_fragments": len(texts),
        "unique_fragments": len(unique_texts),
        "duplicate_fragments": len(texts) - len(unique_texts),
        "duplicate_ratio": round((len(texts) - len(unique_texts)) / len(texts), 6),
        "precompute_ms": round(duration_ms, 3),
        "warmup_ms": warmup.duration_ms,
        "inference_batches": usage.inference_batches,
        "model_id": provider.identity.model_id,
        "projection_identity": provider.identity.key,
        "vectors_persisted": False,
    }


def _read_peak_rss_kib(pid: int) -> int:
    try:
        values = (Path("/proc") / str(pid) / "status").read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError:
        return 0
    for line in values:
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


def _parse_worker_metrics(output: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    cycle: dict[str, Any] | None = None
    warmup: dict[str, Any] = {}
    for raw_line in output.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if row.get("event") == "embedding_warmup":
            candidate = row.get("safe_metadata")
            if isinstance(candidate, dict):
                warmup = dict(candidate)
        if row.get("event") == "outbox_worker_cycle":
            candidate = row.get("safe_metadata")
            if isinstance(candidate, dict):
                cycle = dict(candidate)
    if cycle is None or not isinstance(cycle.get("stage_metrics"), dict):
        raise MaterializationProfileError("installed worker omitted stage metrics")
    return dict(cycle["stage_metrics"]), warmup


def _run_real_worker(
    *, python_executable: Path, environment: Mapping[str, str], timeout_seconds: int
) -> dict[str, Any]:
    executable = python_executable.with_name("milai-worker")
    started_times = os.times()
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(executable), "--once"],
        env=_safe_environment(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    peak_rss_kib = 0
    deadline = time.monotonic() + timeout_seconds
    while process.poll() is None:
        peak_rss_kib = max(peak_rss_kib, _read_peak_rss_kib(process.pid))
        if time.monotonic() >= deadline:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise MaterializationProfileError("installed worker exceeded its resource plan")
        time.sleep(0.05)
    stdout, stderr = process.communicate()
    elapsed_ms = (time.perf_counter() - started) * 1_000
    finished_times = os.times()
    if process.returncode != 0:
        failure = hashlib.sha256(stdout + b"\n" + stderr).hexdigest()
        raise MaterializationProfileError(f"installed worker failed: {failure}")
    metrics, warmup = _parse_worker_metrics(stdout + b"\n" + stderr)
    return {
        "projection_drain_total_ms": round(elapsed_ms, 3),
        "stage_metrics": metrics,
        "embedding_warmup": warmup,
        "processed": int(metrics.get("counts", {}).get("projection_complete_ms", 0)),
        "resources": {
            "cpu_user_s": round(finished_times.children_user - started_times.children_user, 6),
            "cpu_system_s": round(
                finished_times.children_system - started_times.children_system, 6
            ),
            "peak_rss_kib": peak_rss_kib,
        },
    }


def _run_replay_worker(
    *,
    environment: Mapping[str, str],
    vectors: Mapping[str, list[float]],
    identity: Any,
) -> dict[str, Any]:
    from milai.adapters import LocalContentAddressedBlobStore
    from milai.config.settings import load_settings
    from milai.persistence import Database
    from milai.persistence.projection_repository import ProjectionRepository
    from milai.workers.main import FoundationWorker

    settings = load_settings(environment)
    database = Database(
        settings,
        dsn=environment["MILAI_WORKER_DATABASE_URL"],
        expected_role="milai_worker",
    )
    replay = ReplayEmbeddingProvider(identity, vectors)
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    try:
        worker = FoundationWorker(
            settings,
            database,
            repository=ProjectionRepository(database),
            blob_store=LocalContentAddressedBlobStore(
                settings.blob_root,
                kek=settings.blob_kek,
                key_reference=settings.blob_key_reference,
                allow_plaintext_read=settings.data_mode != "LOCAL_PERSONAL_DATA",
            ),
            embedding=replay,
            worker_id="materialization-vector-hit",
        )
        processed = worker.run_once()
        metrics = worker.metrics_snapshot()
    finally:
        database.close()
    elapsed_ms = (time.perf_counter() - started) * 1_000
    after = resource.getrusage(resource.RUSAGE_SELF)
    metrics["counts"]["embedding_cache_hits"] = replay.logical_hits
    return {
        "projection_drain_total_ms": round(elapsed_ms, 3),
        "stage_metrics": metrics,
        "embedding_warmup": {"state": "PRECOMPUTED_VECTOR_HIT"},
        "processed": processed,
        "resources": {
            "cpu_user_s": round(after.ru_utime - before.ru_utime, 6),
            "cpu_system_s": round(after.ru_stime - before.ru_stime, 6),
            "peak_rss_kib": int(after.ru_maxrss),
        },
    }


def _query_units(
    *,
    config: ProductRuntimeConfig,
    environment: Mapping[str, str],
    database_name: str,
    root: Path,
    units: Sequence[WorkloadUnit],
) -> dict[str, Any]:
    from milai_client import prepare_compact_prefetch
    from milai_openworker_mcp import McpUnixClient

    spec = TemporaryResourceSpec(
        lease_id=f"query-{database_name}",
        database_name=database_name,
        blob_root=root / "blobs",
        temporary_root=root,
    )
    runtime = ProductEvaluationRuntime(config)
    api_start_ms = runtime.start_existing_database(spec, environment)
    records: list[dict[str, Any]] = []
    try:
        for unit in units:
            broker_started = time.perf_counter()
            runtime.bind_scope(unit.scope)
            broker_start_ms = (time.perf_counter() - broker_started) * 1_000
            client = McpUnixClient(
                runtime.reader_socket,
                request_timeout_seconds=30,
                max_frame_bytes=2 * 1024 * 1024,
            )
            try:
                query_started = time.perf_counter()
                response = client.recall(unit.query)
                outer_ms = (time.perf_counter() - query_started) * 1_000
            finally:
                client.close()
            compile_started = time.perf_counter()
            context = prepare_compact_prefetch(
                response, query=unit.query, max_context_chars=1_400
            )
            compile_ms = (time.perf_counter() - compile_started) * 1_000
            records.append(
                {
                    "question_id": unit.question_id,
                    "status": response["status"],
                    "source_ids": [
                        str(item.get("source_id"))
                        for item in response.get("items", [])
                        if isinstance(item, dict) and item.get("source_id") is not None
                    ],
                    "open_issue_ids": [str(value) for value in response["open_issue_ids"]],
                    "context_sha256": context.context_sha256,
                    "context_tokens": context.rendered_tokens,
                    "query_outer_ms": round(outer_ms, 3),
                    "context_compile_ms": round(compile_ms, 3),
                    "broker_start_ms": round(broker_start_ms, 3),
                    "stage_metrics": response.get("stage_metrics", {}),
                }
            )
    finally:
        runtime.destroy()
    return {
        "api_start_ms": api_start_ms,
        "query_outer_total_ms": round(
            sum(float(row["query_outer_ms"]) for row in records), 3
        ),
        "context_compile_total_ms": round(
            sum(float(row["context_compile_ms"]) for row in records), 3
        ),
        "broker_start_total_ms": round(
            sum(float(row["broker_start_ms"]) for row in records), 3
        ),
        "records": records,
    }


def _worker_attribution(worker: Mapping[str, Any]) -> dict[str, Any]:
    stages = worker["stage_metrics"]
    durations = stages.get("durations_ms", {})
    projection_total = sum(
        float(durations.get(name, 0.0))
        for name in ("purge_projection_ms", "fts_projection_ms", "vector_projection_ms")
    )
    warmup_ms = float(worker.get("embedding_warmup", {}).get("duration_ms", 0.0))
    direct = {
        "worker_ping_ms": float(durations.get("worker_ping_ms", 0.0)),
        "outbox_wait_ms": float(durations.get("projection_lease_ms", 0.0)),
        "fragment_derivation_ms": float(durations.get("fragment_derivation_ms", 0.0)),
        "embedding_ms": float(durations.get("embedding_inference_ms", 0.0)),
        "projection_write_and_index_ms": float(durations.get("projection_write_ms", 0.0)),
        "projection_complete_ms": float(durations.get("projection_complete_ms", 0.0)),
        "embedding_warm_ms": warmup_ms,
    }
    child_sum = sum(direct.values())
    drain_ms = float(worker["projection_drain_total_ms"])
    return {
        **{name: round(value, 3) for name, value in direct.items()},
        "projection_handler_total_ms": round(projection_total, 3),
        "projection_worker_unattributed_ms": round(max(0.0, drain_ms - child_sum), 3),
        "explained_projection_ms": round(min(drain_ms, child_sum), 3),
        "explained_projection_ratio": round(min(1.0, child_sum / drain_ms), 6),
        "projection_write_includes_index_maintenance": True,
    }


def _cell_signature(query: Mapping[str, Any]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            row["question_id"],
            row["status"],
            tuple(row["source_ids"]),
            tuple(row["open_issue_ids"]),
            row["context_sha256"],
        )
        for row in query["records"]
    )


def _summaries(blocks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    per_cell: dict[str, list[Mapping[str, Any]]] = {cell: [] for cell in SUPPORTED_CELLS}
    for block in blocks:
        for cell, result in block["cells"].items():
            per_cell[cell].append(result)
    cells: dict[str, Any] = {}
    for cell, values in per_cell.items():
        if not values:
            continue
        drains = [float(value["worker"]["projection_drain_total_ms"]) for value in values]
        queries = [float(value["query"]["query_outer_total_ms"]) for value in values]
        explained = [
            float(value["attribution"]["explained_projection_ratio"])
            for value in values
        ]
        cells[cell] = {
            "repetitions": len(values),
            "projection_drain_ms": {
                "median": round(median(drains), 3),
                "min": round(min(drains), 3),
                "max": round(max(drains), 3),
            },
            "query_outer_10_case_ms": {
                "median": round(median(queries), 3),
                "min": round(min(queries), 3),
                "max": round(max(queries), 3),
            },
            "explained_projection_ratio_min": round(min(explained), 6),
        }
    return {"cells": cells}


def run_materialization_profile(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    env_file: Path,
    python_executable: Path,
    product_manifest_sha256: str,
    temporary_root: Path,
    repeats: int,
    seed: int,
    cells: tuple[str, ...],
    worker_timeout_seconds: int,
) -> dict[str, Any]:
    if output.exists():
        raise MaterializationProfileError("materialization output is write-once")
    if repeats < 3:
        raise MaterializationProfileError("materialization profile requires three blocks")
    if not cells or len(set(cells)) != len(cells) or any(
        cell not in SUPPORTED_CELLS for cell in cells
    ):
        raise MaterializationProfileError("materialization cell selection drifted")
    if not python_executable.is_absolute() or not python_executable.is_file():
        raise MaterializationProfileError("installed Python identity is unavailable")
    if len(product_manifest_sha256) != 64:
        raise MaterializationProfileError("product manifest identity is invalid")
    if temporary_root.exists():
        raise MaterializationProfileError("materialization temporary root is write-once")
    temporary_root.mkdir(mode=0o700, parents=True)
    partition, units = _workload_units(input_path)
    config = ProductRuntimeConfig(
        python_executable=python_executable,
        source_env_file=env_file,
        product_manifest_sha256=product_manifest_sha256,
        startup_timeout_seconds=180,
        projection_timeout_seconds=float(worker_timeout_seconds),
    )
    source = read_environment(env_file)
    schedule = seeded_counterbalanced_schedule(
        [f"block-{index:02d}" for index in range(1, repeats + 1)], cells, seed=seed
    )
    vector_cache: dict[str, list[float]] = {}
    vector_identity: Any | None = None
    vector_setup: dict[str, Any] | None = None
    admin_url = _admin_url(source)
    run_digest = hashlib.sha256(run_id.encode()).hexdigest()[:8]
    blocks: list[dict[str, Any]] = []
    cleanup_databases: set[str] = set()
    checkpoint = output.with_suffix(output.suffix + ".partial")
    try:
        for block_index, row in enumerate(schedule, 1):
            source_name = f"milai_eval_lb_{run_digest}_b{block_index}_m1"
            cleanup_databases.add(source_name)
            block_root = temporary_root / f"block-{block_index:02d}"
            source_root = block_root / "m1"
            source_spec = TemporaryResourceSpec(
                lease_id=f"{run_id}-b{block_index}-m1",
                database_name=source_name,
                blob_root=source_root / "blobs",
                temporary_root=source_root,
            )
            runtime = ProductEvaluationRuntime(config)
            m0 = runtime.create_governance_only(source_spec)
            m1_started = time.perf_counter()
            receipts = [runtime.load_governed_history(unit.history) for unit in units]
            m1_wall_ms = (time.perf_counter() - m1_started) * 1_000
            source_environment = dict(runtime.environment)
            tenant_id = source_environment["MILAI_TENANT_ID"]
            runtime.close()
            m1_snapshot = _database_snapshot(source_environment, tenant_id=tenant_id)
            if CELL_M3 in cells and vector_setup is None:
                vector_cache, vector_identity, vector_setup = _precompute_vectors(
                    source, units
                )
            stage_values = [
                receipt.product_usage["governance_stage_ms"] for receipt in receipts
            ]
            evidence_ms = round(
                sum(float(value["evidence_ms"]) for value in stage_values), 3
            )
            proposal_ms = round(
                sum(float(value["proposal_ms"]) for value in stage_values), 3
            )
            review_ms = round(
                sum(float(value["review_ms"]) for value in stage_values), 3
            )
            m1 = {
                "governance_total_ms": round(m1_wall_ms, 3),
                "evidence_ms": evidence_ms,
                "proposal_ms": proposal_ms,
                "review_ms": review_ms,
                "history_sessions": sum(
                    int(receipt.product_usage["history_sessions"])
                    for receipt in receipts
                ),
                "snapshot": m1_snapshot,
            }
            m1["governance_orchestration_unattributed_ms"] = round(
                max(
                    0.0,
                    m1_wall_ms
                    - evidence_ms
                    - proposal_ms
                    - review_ms,
                ),
                3,
            )
            clone_receipts: dict[str, dict[str, Any]] = {}
            environments: dict[str, dict[str, str]] = {}
            for cell in cells:
                suffix = "m2" if cell == CELL_M2 else "m3"
                database_name = f"milai_eval_lb_{run_digest}_b{block_index}_{suffix}"
                cleanup_databases.add(database_name)
                clone_ms = _clone_database(admin_url, source_name, database_name)
                cell_root = block_root / suffix
                environments[cell] = _database_environment(
                    source_environment, database_name, blob_root=cell_root / "blobs"
                )
                clone_receipts[cell] = {
                    "database_name": database_name,
                    "clone_ms_excluded_from_cell": clone_ms,
                    "source_checkpoint": source_name,
                }
            cell_results: dict[str, Any] = {}
            for cell in row.method_order:
                environment = environments[cell]
                if cell == CELL_M2:
                    worker = _run_real_worker(
                        python_executable=python_executable,
                        environment=environment,
                        timeout_seconds=worker_timeout_seconds,
                    )
                else:
                    assert vector_identity is not None
                    worker = _run_replay_worker(
                        environment=environment,
                        vectors=vector_cache,
                        identity=vector_identity,
                    )
                state = _database_snapshot(environment, tenant_id=tenant_id)
                if state["dead_letters"] != 0 or any(
                    value < state["canonical_snapshot"]
                    for value in state["watermarks"].values()
                ):
                    raise MaterializationProfileError(
                        "materialization cell did not reach its canonical watermark"
                    )
                query_root = block_root / f"{cell.casefold()}-query"
                query = _query_units(
                    config=config,
                    environment=environment,
                    database_name=clone_receipts[cell]["database_name"],
                    root=query_root,
                    units=units,
                )
                cell_results[cell] = {
                    "clone": clone_receipts[cell],
                    "worker": worker,
                    "attribution": _worker_attribution(worker),
                    "state": state,
                    "query": query,
                }
                checkpoint.write_text(
                    json.dumps(
                        {
                            "schema": "milai.dg12.materialization-checkpoint.v1",
                            "run_id": run_id,
                            "completed_blocks": blocks,
                            "active_block": {
                                "block": block_index,
                                "completed_cells": list(cell_results),
                            },
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            signatures = {
                cell: _cell_signature(result["query"])
                for cell, result in cell_results.items()
            }
            reference_signature = signatures[CELL_M2]
            equivalence = {
                cell: signature == reference_signature
                for cell, signature in signatures.items()
            }
            if not all(equivalence.values()):
                raise MaterializationProfileError(
                    "materialization cell changed Top-K, context, or status"
                )
            block = {
                "block": block_index,
                "service_state": "FRESH_API_PER_QUERY_CELL_SINGLE_WARMED_WORKER_DRAIN",
                "cell_order": list(row.method_order),
                "M0_LIFECYCLE_ONLY": m0,
                "M1_GOVERNANCE_ONLY": m1,
                "cells": cell_results,
                "equivalence_to_M2": equivalence,
            }
            blocks.append(block)
            runtime.destroy()
            for cell in cells:
                _drop_database(admin_url, clone_receipts[cell]["database_name"])
                cleanup_databases.discard(clone_receipts[cell]["database_name"])
            cleanup_databases.discard(source_name)
        summary = _summaries(blocks)
        minimum_explained = min(
            float(result["attribution"]["explained_projection_ratio"])
            for block in blocks
            for result in block["cells"].values()
        )
        payload = {
            "schema": "milai.dg12.materialization-decomposition.v1",
            "run_id": run_id,
            "work_package": "DG12-PD02-LANE-B",
            "status": "PASS_ATTRIBUTION" if minimum_explained >= 0.95 else "FAIL_ATTRIBUTION",
            "candidate_modified": True,
            "paper_labels_opened": False,
            "answer_calls": 0,
            "judge_calls": 0,
            "hidden_provider_calls": 0,
            "benchmark_id": partition,
            "case_count": len(units),
            "history_sessions": sum(len(grouped_history(unit.history)) for unit in units),
            "matched_repeated_blocks": repeats,
            "counterbalance_seed": seed,
            "minimum_explained_projection_ratio": round(minimum_explained, 6),
            "M3_vector_setup": vector_setup,
            "blocks": blocks,
            "summary": summary,
            "identity": {
                "input_sha256": sha256_file(input_path),
                "env_sha256": sha256_file(env_file),
                "product_manifest_sha256": product_manifest_sha256,
                "python_executable": str(python_executable),
                "runner_sha256": sha256_file(Path(__file__)),
            },
            "boundaries": {
                "canonical_writes": "MCP_EVIDENCE_PROPOSAL_PLUS_STEWARD_REVIEW_ONLY",
                "M1_checkpoint_fanout": "SIBLING_POSTGRES_TEMPLATE_CLONES",
                "M2": "REAL_INSTALLED_WORKER_ONNX_EMBEDDING_CURRENT_SCALAR_WRITER",
                "M3": "EVALUATION_ONLY_EXACT_PRECOMPUTED_VECTOR_HIT_CURRENT_SCALAR_WRITER",
                "projection_write_ms": "INCLUDES_INDEX_MAINTENANCE",
                "M4": "NOT_RUN_UNTIL_M2_M3_ATTRIBUTION_JUSTIFIES_SET_BASED_WRITER",
            },
        }
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        checkpoint.unlink(missing_ok=True)
        return payload
    finally:
        for database_name in sorted(cleanup_databases):
            _drop_database(admin_url, database_name)
        if temporary_root.exists():
            resolved = temporary_root.resolve()
            if resolved.name and resolved != resolved.parent:
                shutil.rmtree(resolved)


def verify_environment_database(environment: Mapping[str, str], name: str) -> bool:
    """Small pure helper used by tests and preflight validation."""

    return all(
        urlsplit(environment[key]).path == f"/{name}"
        for key in (
            "MILAI_DATABASE_URL",
            "MILAI_STEWARD_DATABASE_URL",
            "MILAI_WORKER_DATABASE_URL",
            "MILAI_MIGRATION_DATABASE_URL",
            "MILAI_AUDIT_DATABASE_URL",
        )
    )
