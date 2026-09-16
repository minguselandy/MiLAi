"""Bounded EH04 Horizon reconfirmation over the clean-installed product.

The runner performs one governed cold pass and three deterministic retained-state
deep blocks. Persisted artifacts contain hashes and stage/resource measurements,
not queries, contexts, or source identifiers.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import random
import statistics
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
from tokenizers import Tokenizer

from evals.datasets.text import retrieval_query, runtime_safe_text
from evals.harness import (
    HistoryItem,
    OpenWorkerMcpMemoryMethodAdapter,
    ProductEvaluationRuntime,
    ProductRuntimeConfig,
    TemporaryResourceSpec,
    WorkloadHistory,
    WorkloadQuestion,
)
from evals.harness.product_runtime import read_environment, rewrite_database_url
from evals.paper.datasets.extended import load_extended_inputs

RUN_ID = "dg12-eh04-reconfirmation-20260825-001"
ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "var/dg11/paper/freeze/horizon-smoke-inputs.json"
REFERENCE = (
    ROOT / "var/dg12/runs/dg12-eh02-pd01-horizon-persistent-20260824-024/terminal.json"
)
OUTPUT = ROOT / "var/dg12/runs" / RUN_ID / "horizon-reconfirmation.json"
SOURCE_ENV = ROOT / "runtime/.env"
PYTHON = Path("/cra/memory/mx_memory/.milai-dg12-eh04-venv-20260825-002/bin/python")
TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
TEMPORARY_ROOT = Path("/tmp/milai-eh04-001")
DATABASE_NAME = "milai_eval_eh04_001"
PRODUCT_MANIFEST = "cdf3d942aadeaa8e57743bf2691758303852c5f5047244a0acfe638f811bd16a"
RUNTIME_WHEEL_SHA256 = (
    "bb79f03de0f51833b592234addd002defced202d74df33e8c8c8851ee57271db"
)
SCHEDULE_SEED = 20_260_825
SCHEDULE_OFFSETS = (0, 3, 7)
COLD_TARGET_SECONDS = 268.900
DEEP_TARGET_MILLISECONDS = 31_548.0
REUSE_CEILING_SECONDS = 80.0
REFERENCE_COLD_SECONDS = 918.847
REFERENCE_DEEP_MILLISECONDS = 63_096.588
HARD_PROCESS_TREE_RSS_BYTES = 1_610_612_736
HARD_TEMPORARY_STORAGE_BYTES = 2_147_483_648


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _workload(case: Any) -> tuple[WorkloadHistory, tuple[WorkloadQuestion, ...]]:
    history_id = case.sessions[0].session_id.rsplit("-session-", 1)[0]
    history = WorkloadHistory(
        workload_id=history_id,
        dataset_id="HORIZON-OFFICIAL-SAMPLE-10-SMOKE",
        items=tuple(
            HistoryItem(
                item_id=f"{session.session_id}:{turn_index:05d}",
                session_id=session.session_id,
                role=turn.role,
                content=runtime_safe_text(turn.content),
                occurred_at=session.observed_at,
                metadata={"turn_index": turn_index},
            )
            for session in case.sessions
            for turn_index, turn in enumerate(session.turns)
        ),
        metadata={
            "case_id": case.case_id,
            "claim_subject_namespace": case.case_id,
            "claim_subject_index_width": 3,
            "claim_predicate": "benchmark.memory.session",
            "claim_type": "BENCHMARK_MEMORY",
            "gold_used": False,
        },
    )
    question = WorkloadQuestion(
        question_id=case.case_id,
        workload_id=history_id,
        query=retrieval_query(case.question, history.dataset_id),
    )
    return history, (question,)


def _source_ids(record: Any) -> list[str]:
    return [
        str(item.get("payload", {}).get("session_id"))
        for item in record.items
        if isinstance(item.get("payload"), dict)
    ]


def _stage_metrics(product_usage: Mapping[str, Any]) -> dict[str, Any]:
    value = product_usage.get("stage_metrics")
    if not isinstance(value, Mapping):
        return {"counts": {}, "durations_ms": {}}
    counts = value.get("counts")
    durations = value.get("durations_ms")
    return {
        "counts": dict(counts) if isinstance(counts, Mapping) else {},
        "durations_ms": dict(durations) if isinstance(durations, Mapping) else {},
    }


def _build_summary(product_usage: Mapping[str, Any]) -> dict[str, Any]:
    build = product_usage.get("build")
    if not isinstance(build, Mapping):
        return {}
    allowed = (
        "build_calls",
        "immutable_workload_reused",
        "history_items",
        "history_sessions",
        "evidence_captures",
        "proposal_creates",
        "steward_reviews",
        "governance_stage_ms",
        "elapsed_ms",
    )
    return {key: build[key] for key in allowed if key in build}


def _directory_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _process_rss_bytes(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def _marked_process_ids(marker: bytes) -> set[int]:
    result = {os.getpid()}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if marker in command:
            result.add(int(entry.name))
    return result


class _ResourceSampler:
    def __init__(self, marker: Path) -> None:
        self._marker = str(marker).encode()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.samples = 0
        self.peak_rss_bytes = 0
        self.peak_process_count = 0
        self.peak_temporary_bytes = 0

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            pids = _marked_process_ids(self._marker)
            rss = sum(_process_rss_bytes(pid) for pid in pids)
            self.samples += 1
            self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
            self.peak_process_count = max(self.peak_process_count, len(pids))
            self.peak_temporary_bytes = max(
                self.peak_temporary_bytes, _directory_bytes(TEMPORARY_ROOT)
            )
            self._stop.wait(0.5)


def _database_admin_url() -> str:
    source = read_environment(SOURCE_ENV)
    return rewrite_database_url(source["MILAI_MIGRATION_DATABASE_URL"], "postgres")


def _database_count() -> int:
    with psycopg.connect(_database_admin_url(), autocommit=True) as connection:
        row = connection.execute(
            "SELECT count(*) FROM pg_database WHERE datname = %s",
            (DATABASE_NAME,),
        ).fetchone()
    return int(row[0]) if row is not None else -1


def _database_size() -> int:
    with psycopg.connect(_database_admin_url(), autocommit=True) as connection:
        row = connection.execute(
            "SELECT pg_database_size(%s)", (DATABASE_NAME,)
        ).fetchone()
    return int(row[0]) if row is not None else 0


def _remaining_marked_processes() -> int:
    return len(_marked_process_ids(str(TEMPORARY_ROOT).encode()) - {os.getpid()})


def _schedule(case_count: int) -> tuple[tuple[int, ...], ...]:
    base = list(range(case_count))
    random.Random(SCHEDULE_SEED).shuffle(base)
    return tuple(tuple(base[offset:] + base[:offset]) for offset in SCHEDULE_OFFSETS)


def _equivalence(
    record: Any,
    *,
    reference: Mapping[str, Any],
    tokenizer: Tokenizer,
) -> tuple[dict[str, bool], list[str], str, int]:
    context = str(record.metadata["context"])
    context_sha256 = str(record.metadata["context_sha256"])
    source_ids = _source_ids(record)
    declared_tokens = len(tokenizer.encode(context).ids)
    checks = {
        "context_sha256": context_sha256 == reference["context_sha256"],
        "declared_tokens": declared_tokens == reference["declared_tokens"],
        "open_issues": list(record.open_issue_ids) == [],
        "source_ids": source_ids == reference["source_ids"],
        "status": record.status == reference["status"],
        "top_k": len(source_ids) == len(reference["source_ids"]),
    }
    return checks, source_ids, context_sha256, declared_tokens


def _distribution(values: Sequence[float]) -> dict[str, float]:
    return {
        "minimum": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "maximum": round(max(values), 3),
    }


def main() -> int:
    overall_started = time.perf_counter()
    tokenizer = Tokenizer.from_file(str(TOKENIZER))
    benchmark_id, cases = load_extended_inputs(INPUT)
    work = [(case, *_workload(case)) for case in cases]
    frozen_terminal = json.loads(REFERENCE.read_text(encoding="utf-8"))
    frozen = {record["case_id"]: record for record in frozen_terminal["records"]}
    schedule = _schedule(len(work))

    from milai_openworker_mcp.host_adapter import OpenWorkerProviderAdapter

    product_origin = Path(inspect.getfile(OpenWorkerProviderAdapter)).resolve()
    if not product_origin.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("OpenWorker product bytes are not clean-installed")

    runtime = ProductEvaluationRuntime(
        ProductRuntimeConfig(
            python_executable=PYTHON,
            source_env_file=SOURCE_ENV,
            product_manifest_sha256=PRODUCT_MANIFEST,
            startup_timeout_seconds=180,
            projection_timeout_seconds=300,
        )
    )
    spec = TemporaryResourceSpec(
        lease_id=RUN_ID,
        database_name=DATABASE_NAME,
        blob_root=TEMPORARY_ROOT / "blobs",
        temporary_root=TEMPORARY_ROOT,
    )
    adapter = OpenWorkerMcpMemoryMethodAdapter()
    sampler = _ResourceSampler(TEMPORARY_ROOT)
    sampler.start()
    cold_records: list[dict[str, Any]] = []
    deep_blocks: list[dict[str, Any]] = []
    failure: dict[str, str] | None = None
    status = "BLOCKED"
    startup_seconds = 0.0
    cold_phase_seconds = 0.0
    cleanup_seconds = 0.0
    database_peak_bytes = 0
    lease = None
    try:
        startup_started = time.perf_counter()
        lease = runtime.create(spec)
        startup_seconds = time.perf_counter() - startup_started

        cold_started = time.perf_counter()
        for ordinal, (case, history, questions) in enumerate(work, start=1):
            case_started = time.perf_counter()
            record = adapter.run(lease, history, questions)[0]
            checks, source_ids, context_sha256, declared_tokens = _equivalence(
                record, reference=frozen[case.case_id], tokenizer=tokenizer
            )
            cold_records.append(
                {
                    "case_id_sha256": _identity_sha256(case.case_id),
                    "ordinal": ordinal,
                    "outer_wall_ms": round(
                        (time.perf_counter() - case_started) * 1_000, 3
                    ),
                    "retrieval_ms": record.elapsed_ms,
                    "status": record.status,
                    "context_sha256": context_sha256,
                    "declared_tokens": declared_tokens,
                    "source_id_sha256": [
                        _identity_sha256(value) for value in source_ids
                    ],
                    "equivalence": checks,
                    "build": _build_summary(record.product_usage),
                    "stage_metrics": _stage_metrics(record.product_usage),
                }
            )
            print(json.dumps({"case": ordinal, "phase": "cold"}), flush=True)
        cold_phase_seconds = time.perf_counter() - cold_started
        database_peak_bytes = max(database_peak_bytes, _database_size())

        for block_index, order in enumerate(schedule, start=1):
            block_started = time.perf_counter()
            block_records: list[dict[str, Any]] = []
            for position, case_index in enumerate(order, start=1):
                case, history, questions = work[case_index]
                record = adapter.run(lease, history, questions)[0]
                checks, source_ids, context_sha256, declared_tokens = _equivalence(
                    record, reference=frozen[case.case_id], tokenizer=tokenizer
                )
                build = _build_summary(record.product_usage)
                block_records.append(
                    {
                        "case_id_sha256": _identity_sha256(case.case_id),
                        "position": position,
                        "outer_retrieval_ms": record.elapsed_ms,
                        "status": record.status,
                        "context_sha256": context_sha256,
                        "declared_tokens": declared_tokens,
                        "source_id_sha256": [
                            _identity_sha256(value) for value in source_ids
                        ],
                        "equivalence": checks,
                        "build_calls": build.get("build_calls"),
                        "immutable_workload_reused": build.get(
                            "immutable_workload_reused"
                        ),
                        "stage_metrics": _stage_metrics(record.product_usage),
                    }
                )
            block_wall_seconds = time.perf_counter() - block_started
            outer_total_ms = sum(
                float(record["outer_retrieval_ms"]) for record in block_records
            )
            deep_blocks.append(
                {
                    "block": block_index,
                    "case_order_sha256": [
                        record["case_id_sha256"] for record in block_records
                    ],
                    "records": block_records,
                    "wall_seconds": round(block_wall_seconds, 3),
                    "outer_retrieval_total_ms": round(outer_total_ms, 3),
                    "equivalent_cases": sum(
                        all(record["equivalence"].values()) for record in block_records
                    ),
                    "build_calls": sum(
                        int(record["build_calls"] or 0) for record in block_records
                    ),
                }
            )
            print(
                json.dumps(
                    {
                        "block": block_index,
                        "outer_retrieval_total_ms": round(outer_total_ms, 3),
                        "phase": "deep",
                    }
                ),
                flush=True,
            )
        database_peak_bytes = max(database_peak_bytes, _database_size())
    except Exception as exc:  # noqa: BLE001 - terminal runner must persist failures
        failure = {"class": type(exc).__name__, "message": str(exc)}
    finally:
        cleanup_started = time.perf_counter()
        try:
            if lease is not None:
                lease.close()
            runtime.destroy()
        except Exception as exc:  # noqa: BLE001 - cleanup failures are terminal evidence
            failure = {"class": "CLEANUP_EXCEPTION", "message": type(exc).__name__}
        cleanup_seconds = time.perf_counter() - cleanup_started
        sampler.close()

    cleanup = {
        "database_remaining": _database_count(),
        "temporary_root_absent": not TEMPORARY_ROOT.exists(),
        "marked_processes_remaining": _remaining_marked_processes(),
    }
    cold_build_calls = sum(
        int(record["build"].get("build_calls", 0)) for record in cold_records
    )
    cold_equivalent = sum(
        all(record["equivalence"].values()) for record in cold_records
    )
    deep_values = [float(block["outer_retrieval_total_ms"]) for block in deep_blocks]
    deep_walls = [float(block["wall_seconds"]) for block in deep_blocks]
    deep_equivalent = sum(int(block["equivalent_cases"]) for block in deep_blocks)
    deep_build_calls = sum(int(block["build_calls"]) for block in deep_blocks)
    cold_product_seconds = startup_seconds + cold_phase_seconds + cleanup_seconds
    temporary_peak_bytes = sampler.peak_temporary_bytes + database_peak_bytes
    resource_pass = (
        sampler.peak_rss_bytes <= HARD_PROCESS_TREE_RSS_BYTES
        and temporary_peak_bytes <= HARD_TEMPORARY_STORAGE_BYTES
    )
    functional_pass = (
        failure is None
        and len(cold_records) == 10
        and cold_equivalent == 10
        and cold_build_calls == 10
        and len(deep_blocks) == 3
        and deep_equivalent == 30
        and deep_build_calls == 0
        and max(deep_walls, default=float("inf")) <= REUSE_CEILING_SECONDS
        and cleanup
        == {
            "database_remaining": 0,
            "temporary_root_absent": True,
            "marked_processes_remaining": 0,
        }
        and resource_pass
    )
    status = "PASS" if functional_pass else "BLOCKED"
    case_distributions = []
    if len(deep_blocks) == 3:
        by_case: dict[str, list[float]] = {}
        for block in deep_blocks:
            for record in block["records"]:
                by_case.setdefault(record["case_id_sha256"], []).append(
                    float(record["outer_retrieval_ms"])
                )
        case_distributions = [
            {"case_id_sha256": key, **_distribution(values)}
            for key, values in sorted(by_case.items())
        ]

    terminal = {
        "schema": "milai.dg12.eh04-horizon-reconfirmation.v1",
        "run_id": RUN_ID,
        "status": status,
        "failure": failure,
        "benchmark_id": benchmark_id,
        "data_boundary": "DEIDENTIFIED_INPUT_PAYLOAD_FREE_OUTPUT",
        "paper_labels_opened": False,
        "answer_calls": 0,
        "judge_calls": 0,
        "hidden_provider_calls": 0,
        "maximum_concurrent_product_requests": 1,
        "input": {"path": str(INPUT.relative_to(ROOT)), "sha256": _sha256(INPUT)},
        "reference": {
            "path": str(REFERENCE.relative_to(ROOT)),
            "sha256": _sha256(REFERENCE),
            "product_manifest_sha256": frozen_terminal["product"]["manifest_sha256"],
        },
        "product": {
            "manifest_sha256": PRODUCT_MANIFEST,
            "runtime_wheel_sha256": RUNTIME_WHEEL_SHA256,
            "openworker_origin": str(product_origin),
        },
        "schedule": {
            "seed": SCHEDULE_SEED,
            "cyclic_offsets": list(SCHEDULE_OFFSETS),
            "blocks": 3,
        },
        "cold": {
            "records": cold_records,
            "equivalent_cases": cold_equivalent,
            "build_calls": cold_build_calls,
            "product_wall_seconds": round(cold_product_seconds, 3),
            "target_seconds": COLD_TARGET_SECONDS,
            "reference_seconds": REFERENCE_COLD_SECONDS,
            "target_status": (
                "PASS_TARGET_MET"
                if cold_product_seconds <= COLD_TARGET_SECONDS
                else "TERMINAL_TARGET_MISS"
            ),
        },
        "deep": {
            "blocks": deep_blocks,
            "block_outer_retrieval_ms": (
                _distribution(deep_values) if deep_values else None
            ),
            "block_wall_seconds": _distribution(deep_walls) if deep_walls else None,
            "case_distribution_ms": case_distributions,
            "equivalent_cases": deep_equivalent,
            "build_calls": deep_build_calls,
            "reference_anchor_ms": REFERENCE_DEEP_MILLISECONDS,
            "target_ms": DEEP_TARGET_MILLISECONDS,
            "target_status": (
                "PASS_TARGET_MET"
                if deep_values
                and statistics.median(deep_values) <= DEEP_TARGET_MILLISECONDS
                else "TERMINAL_TARGET_MISS"
            ),
            "reuse_regression_ceiling_seconds": REUSE_CEILING_SECONDS,
            "reuse_regression_status": (
                "PASS"
                if deep_walls
                and max(deep_walls) <= REUSE_CEILING_SECONDS
                and deep_build_calls == 0
                else "FAIL"
            ),
        },
        "resource": {
            "process_tree_sampling": {
                "method": "RUNNER_PLUS_TEMPORARY_ROOT_MARKED_PROCESSES",
                "samples": sampler.samples,
                "peak_process_count": sampler.peak_process_count,
                "peak_rss_bytes": sampler.peak_rss_bytes,
            },
            "storage": {
                "peak_non_database_temporary_bytes": sampler.peak_temporary_bytes,
                "peak_database_bytes": database_peak_bytes,
                "combined_peak_upper_bound_bytes": temporary_peak_bytes,
            },
            "hard_process_tree_rss_bytes": HARD_PROCESS_TREE_RSS_BYTES,
            "hard_temporary_storage_bytes": HARD_TEMPORARY_STORAGE_BYTES,
            "status": "PASS" if resource_pass else "FAIL",
            "onnx_threads": {
                "embedding": "ONNXRUNTIME_DEFAULT_NOT_EXPLICIT",
                "reranker_intra_op": 1,
                "reranker_inter_op": 1,
            },
        },
        "timing": {
            "startup_seconds": round(startup_seconds, 3),
            "cold_phase_seconds": round(cold_phase_seconds, 3),
            "cleanup_seconds": round(cleanup_seconds, 3),
            "overall_seconds": round(time.perf_counter() - overall_started, 3),
        },
        "cleanup": cleanup,
        "payload_policy": {
            "raw_context_emitted": False,
            "raw_query_emitted": False,
            "source_ids_emitted": False,
            "case_identity": "SHA256_ONLY",
        },
    }
    OUTPUT.write_text(
        json.dumps(terminal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_id": RUN_ID, "status": status}, sort_keys=True))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
