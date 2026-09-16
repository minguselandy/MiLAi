"""Cohort-reused Memora context runner for frozen DG10/DG11 Runtime wheels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast
from uuid import uuid4

from alembic import command
from milai.adapters.agent_prefetch import prepare_compact_prefetch
from milai.config import load_settings
from milai.config.settings import prepare_runtime_directories
from milai.operations.cli import _load_environment_file
from tokenizers import Tokenizer

from evals.agent_integration import e2e
from evals.benchmark import lme_product_smoke as product
from evals.paper.contracts import (
    ContextRecord,
    read_context_archive,
    write_context_archive,
)
from evals.paper.datasets.memora import MemoraCase, MemoraCohort, load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file
from evals.paper.runners.memora import _require_inputs
from evals.paper.runners.milai_contexts import (
    EXPECTED_CANDIDATE_ID,
    EXPECTED_MCP_HOST_SHA256,
    EXPECTED_PRODUCT_ADAPTER_SHA256,
    MCP_WHEEL_SHA256,
    WHEEL_SHA256,
    _CountingEmbeddingProvider,
    _EmbeddingCallCounter,
    _mcp_origin,
    _runtime_origin,
    _trace_items,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
DEFAULT_ENV = ROOT / "runtime/.env"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
MEMORY_TOKEN_BUDGET = 512
MAX_CONTEXT_CHARS = 1_400


class MemoraMiLAiContextError(RuntimeError):
    pass


def _parse_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError as exc:
        raise MemoraMiLAiContextError("Memora date contract drifted") from exc


def _session_text(cohort: MemoraCohort, index: int) -> str:
    session = cohort.sessions[index]
    return "\n".join(f"{turn.actor}: {turn.content}" for turn in session.turns)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


class _CohortRuntime(AbstractContextManager["_CohortRuntime"]):
    """Own one isolated Runtime database for all questions in one cohort."""

    def __init__(self, *, cohort: MemoraCohort, env_file: Path) -> None:
        self.cohort = cohort
        self.env_file = env_file
        self.runtime_id = uuid4().hex
        self.database_name = f"milai_smoke_{self.runtime_id[:20]}"
        self.owner_source = ""
        self.database_urls: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.api_process: subprocess.Popen[bytes] | None = None
        self.worker_database: Any = None
        self.client: Any = None
        self.worker: Any = None
        self.settings: Any = None
        self.embedding_counter = _EmbeddingCallCounter()
        self.embedding_identity: dict[str, Any] = {}
        self.blobs: tempfile.TemporaryDirectory[str] | None = None
        self.created = False
        self.fixture_ids: list[dict[str, str]] = []
        self.projected_events = 0
        self.ingest_ms = 0.0
        self.started = time.perf_counter()

    def __enter__(self) -> Self:
        _load_environment_file(self.env_file.resolve())
        source = load_settings()
        owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
        worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
        audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
        if not owner_source or not worker_source or not audit_source:
            raise MemoraMiLAiContextError("Runtime database role URLs are absent")
        self.owner_source = owner_source
        self.database_urls = {
            "owner": product._database_url(owner_source, self.database_name),
            "api": product._database_url(source.database_dsn, self.database_name),
            "steward": product._database_url(
                source.steward_database_dsn, self.database_name
            ),
            "worker": product._database_url(worker_source, self.database_name),
            "audit": product._database_url(audit_source, self.database_name),
        }
        self.tokens = {
            name: secrets.token_urlsafe(48)
            for name in (
                "legacy",
                "causal",
                "reader",
                "submitter",
                "operator",
                "reviewer",
            )
        }
        try:
            product._create_database(owner_source, self.database_name)
            self.created = True
            with product._migration_url(self.database_urls["owner"]):
                command.upgrade(product._alembic_config(), "head")
            self.blobs = tempfile.TemporaryDirectory(prefix="milai-memora-paper-blobs-")
            embedding_updates = product._embedding_settings_updates(source)
            self.settings = product._smoke_settings(
                source,
                self.database_urls,
                Path(self.blobs.name),
                uuid4(),
                uuid4(),
                self.tokens,
                product._free_loopback_port(),
            ).model_copy(update=embedding_updates)
            if (
                self.settings.embedding_provider != "onnx_sentence_transformer"
                or self.settings.embedding_model_path is None
            ):
                raise MemoraMiLAiContextError(
                    "Memora target profile requires the frozen ONNX embedding"
                )
            prepare_runtime_directories(self.settings)
            environment = e2e._api_environment(
                self.settings, self.database_urls, self.tokens
            )
            environment.update(
                {
                    "MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED",
                    "MILAI_EMBEDDING_PROVIDER": self.settings.embedding_provider,
                    "MILAI_EMBEDDING_MODEL_PATH": str(
                        self.settings.embedding_model_path
                    ),
                    "MILAI_EMBEDDING_MODEL_ID": self.settings.embedding_model_id,
                    "MILAI_EMBEDDING_SOURCE_DIMENSIONS": str(
                        self.settings.embedding_source_dimensions
                    ),
                    "MILAI_EMBEDDING_PREWARM": (
                        "true" if self.settings.embedding_prewarm else "false"
                    ),
                    "MILAI_EMBEDDING_MAX_CONCURRENCY": str(
                        self.settings.embedding_max_concurrency
                    ),
                }
            )
            if "embedding_projection_dimensions" in type(self.settings).model_fields:
                environment["MILAI_EMBEDDING_PROJECTION_DIMENSIONS"] = str(
                    self.settings.embedding_projection_dimensions
                )
            executable = Path(sys.executable).with_name("milai-api")
            self.api_process = subprocess.Popen(
                [str(executable)],
                cwd=ROOT / "runtime",
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            base_url = f"http://{self.settings.bind_host}:{self.settings.bind_port}"
            self.client = e2e._HttpClient(base_url)
            e2e._wait_api(self.client, self.api_process)
            self.worker_database = e2e.Database(
                self.settings,
                dsn=self.database_urls["worker"],
                expected_role="milai_worker",
            )
            inner_embedding = product._embedding_provider(self.settings)
            embedding = _CountingEmbeddingProvider(
                inner_embedding, self.embedding_counter
            )
            warmup = embedding.warmup()
            if warmup.state != "READY":
                raise MemoraMiLAiContextError("frozen ONNX embedding prewarm failed")
            self.embedding_identity = {
                "model_id": embedding.identity.model_id,
                "projection_dimensions": embedding.identity.projection_dimensions,
                "provider": embedding.identity.provider,
                "source_dimensions": embedding.identity.source_dimensions,
                "warmup_duration_ms": warmup.duration_ms,
                "warmup_state": warmup.state,
            }
            self.worker = e2e.FoundationWorker(
                self.settings,
                self.worker_database,
                repository=e2e.ProjectionRepository(self.worker_database),
                blob_store=e2e.LocalContentAddressedBlobStore(
                    self.settings.blob_root,
                    kek=self.settings.blob_kek,
                    key_reference=self.settings.blob_key_reference,
                    allow_plaintext_read=True,
                ),
                embedding=embedding,
                worker_id=f"memora-paper-{self.runtime_id[:12]}",
            )
            self._ingest()
            return self
        except Exception:
            self.close()
            raise

    def _ingest(self) -> None:
        ingest_started = time.perf_counter()
        cohort_subject = hashlib.sha256(self.cohort.cohort_id.encode()).hexdigest()[:20]
        for index, session in enumerate(self.cohort.sessions):
            session_text = _session_text(self.cohort, index)
            operation = f"memora-{self.runtime_id[:8]}-{index:05d}"
            evidence = e2e._body(
                self.client.post(
                    "/v1/evidence",
                    headers=e2e._headers(self.tokens["submitter"], operation + "-e"),
                    json={
                        "source_type": "BENCHMARK_FIXTURE",
                        "source_ref": (f"dg11-memora://{cohort_subject}/{index:05d}"),
                        "subject_id": f"{cohort_subject}-{index:05d}",
                        "observed_at": _parse_date(session.observed_at).isoformat(),
                        "content": session_text,
                        "data_classification": "DEIDENTIFIED",
                        "media_type": "text/plain; charset=utf-8",
                        "permission_snapshot": {
                            "readable": True,
                            "scope": "dg11-paper-public-memora",
                        },
                        "retention_state": "READABLE",
                    },
                ),
                201,
                "memora_evidence",
            )
            evidence_id = str(evidence["evidence_id"])
            proposal = e2e._body(
                self.client.post(
                    "/v1/proposals",
                    headers=e2e._headers(self.tokens["submitter"], operation + "-p"),
                    json={
                        "operation": "CREATE",
                        "proposed_patch": {
                            "subject_id": f"{cohort_subject}-{index:05d}",
                            "predicate": "benchmark.memory.session",
                            "claim_type": "BENCHMARK_MEMORY",
                            "payload": {
                                "session_id": session.session_id,
                                "memory_text": session_text,
                            },
                            "valid_time_from": _parse_date(
                                session.observed_at
                            ).isoformat(),
                            "authority": "ACTION_SAFE",
                            "confidence": 1.0,
                        },
                        "supporting_evidence_refs": [evidence_id],
                        "scope_predicate": {"project_ids": ["milai"]},
                        "requested_authority": "ACTION_SAFE",
                        "derivation_policy_id": "dg11-memora-paper-v1",
                        "derivation_snapshot": {
                            "source_session_sha256": hashlib.sha256(
                                session_text.encode()
                            ).hexdigest(),
                            "gold_used": False,
                        },
                    },
                ),
                201,
                "memora_proposal",
            )
            reviewed = e2e._review(
                self.client,
                self.tokens["reviewer"],
                str(proposal["proposal_id"]),
                operation + "-r",
                "PUBLIC_DEIDENTIFIED_PAPER_FIXTURE",
            )
            self.fixture_ids.append(
                {
                    "claim_id": str(reviewed["claim_id"]),
                    "evidence_id": evidence_id,
                    "session_id": session.session_id,
                }
            )
        for _ in range(len(self.cohort.sessions) * 4 + 20):
            count = self.worker.run_once()
            if count <= 0:
                break
            self.projected_events += count
        self.ingest_ms = (time.perf_counter() - ingest_started) * 1000

    def query(self, case: MemoraCase, tokenizer: Tokenizer) -> ContextRecord:
        recall_started = time.perf_counter()
        recall_wire = e2e._mcp(
            "reader-lite",
            "milai_recall",
            {"query": case.question},
            base_url=f"http://{self.settings.bind_host}:{self.settings.bind_port}",
            token=self.tokens["reader"],
            scope={"project_ids": ["milai"]},
            agent_as_of=_parse_date(case.question_at),
            max_limit=3,
        )
        if recall_wire.get("is_error") is not False:
            raise MemoraMiLAiContextError(
                "Memora MCP recall failed: " + product._mcp_failure_summary(recall_wire)
            )
        recall = e2e._structured(recall_wire)
        context = prepare_compact_prefetch(
            recall, query=case.question, max_context_chars=MAX_CONTEXT_CHARS
        )
        items = recall.get("items")
        raw_items = (
            [
                {
                    "matched_by": item.get("matched_by"),
                    "relevance_score": item.get("relevance_score"),
                    "reranker": item.get("reranker"),
                    "session_id": str(item.get("payload", {}).get("session_id")),
                    "valid_time_from": item.get("valid_time_from"),
                }
                for item in items
                if isinstance(item, dict) and isinstance(item.get("payload"), dict)
            ]
            if isinstance(items, list)
            else []
        )
        trace = _trace_items({"retrieved_items": raw_items})
        declared_tokens = len(tokenizer.encode(context.rendered).ids)
        if declared_tokens > MEMORY_TOKEN_BUDGET:
            raise MemoraMiLAiContextError(
                "MiLAi Memora context exceeds the controlled memory ceiling"
            )
        reranker_calls = int(
            any(isinstance(item.get("reranker"), dict) for item in raw_items)
        )
        return ContextRecord(
            case_id=case.case_id,
            method_id="DG11-FULL",
            track="CONTROLLED",
            context=context.rendered,
            source_ids=tuple(str(item["source_id"]) for item in trace),
            trace=trace,
            declared_tokens=declared_tokens,
            latency_ms=(time.perf_counter() - recall_started) * 1000,
            usage={
                "embedding_calls_api_query": 1,
                "ingest_extraction_calls": 0,
                "memory_query_model_calls": 0,
                "memory_status": str(context.status),
                "reranker_calls": reranker_calls,
                "retriever_calls": 1,
            },
        )

    def stats(self, *, question_count: int) -> dict[str, Any]:
        storage_bytes = sum(
            len(_session_text(self.cohort, index).encode())
            for index in range(len(self.cohort.sessions))
        )
        api_warmup = int(bool(self.settings.embedding_prewarm))
        return {
            "api_query_embedding_calls": question_count,
            "api_warmup_embedding_calls": api_warmup,
            "cohort_id": self.cohort.cohort_id,
            "embedding_identity": self.embedding_identity,
            "fixture_ids_sha256": hashlib.sha256(
                _canonical(self.fixture_ids)
            ).hexdigest(),
            "governed_claim_count": len(self.fixture_ids),
            "index_time_ms": round(self.ingest_ms, 3),
            "parent_inference_embedding_calls": (
                self.embedding_counter.inference_calls
            ),
            "parent_warmup_embedding_calls": self.embedding_counter.warmup_calls,
            "projected_events": self.projected_events,
            "question_count": question_count,
            "session_count": len(self.cohort.sessions),
            "storage_bytes": storage_bytes,
            "total_embedding_calls": (
                question_count
                + api_warmup
                + self.embedding_counter.inference_calls
                + self.embedding_counter.warmup_calls
            ),
            "total_runtime_ms": round((time.perf_counter() - self.started) * 1000, 3),
        }

    def close(self) -> None:
        cleanup: dict[str, Any] = {"status": "NOT_CREATED"}
        if self.api_process is not None:
            e2e._stop_api(self.api_process)
            self.api_process = None
        if self.worker_database is not None:
            self.worker_database.close()
            self.worker_database = None
        if self.created:
            cleanup = product._drop_database(self.owner_source, self.database_name)
            self.created = False
        if self.blobs is not None:
            self.blobs.cleanup()
            self.blobs = None
        if cleanup.get("status") not in {"NOT_CREATED", "PASS"}:
            raise MemoraMiLAiContextError("Memora Runtime database cleanup failed")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()


def _verify_install(
    *, method_id: str, runtime_wheel: Path, install_manifest: Path
) -> None:
    if method_id != "DG11-FULL":
        raise MemoraMiLAiContextError("Memora paper runner accepts DG11-FULL only")
    if sha256_file(runtime_wheel) != WHEEL_SHA256[method_id]:
        raise MemoraMiLAiContextError("MiLAi Runtime wheel identity drifted")
    try:
        install = json.loads(install_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoraMiLAiContextError("MiLAi install manifest is invalid") from exc
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
        or install.get("identity") != "dg11"
        or Path(str(install.get("environment"))).resolve() != Path(sys.prefix).resolve()
        or not isinstance(installed_runtime, dict)
        or installed_runtime.get("sha256") != WHEEL_SHA256[method_id]
        or not isinstance(installed_mcp, dict)
        or installed_mcp.get("sha256") != MCP_WHEEL_SHA256[method_id]
    ):
        raise MemoraMiLAiContextError("MiLAi fresh install identity drifted")
    if (
        sha256_file(ROOT / "evals/benchmark/lme_product_smoke.py")
        != EXPECTED_PRODUCT_ADAPTER_SHA256
        or sha256_file(ROOT / "evals/agent_integration/mcp_host.py")
        != EXPECTED_MCP_HOST_SHA256
    ):
        raise MemoraMiLAiContextError("candidate-frozen adapter bytes drifted")


def _worker_identity(
    *,
    run_id: str,
    input_path: Path,
    env_file: Path,
    install_manifest: Path,
) -> dict[str, Any]:
    return {
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "env_sha256": sha256_file(env_file),
        "input_sha256": sha256_file(input_path),
        "install_manifest_sha256": sha256_file(install_manifest),
        "method_id": "DG11-FULL",
        "mcp_host_python": str(Path(sys.executable).absolute()),
        "mcp_host_source_sha256": EXPECTED_MCP_HOST_SHA256,
        "mcp_origin": _mcp_origin(),
        "mcp_wheel_sha256": MCP_WHEEL_SHA256["DG11-FULL"],
        "paper_worker_sha256": sha256_file(Path(__file__)),
        "product_adapter_sha256": EXPECTED_PRODUCT_ADAPTER_SHA256,
        "run_id": run_id,
        "runtime_origin": _runtime_origin(),
        "runtime_wheel_sha256": WHEEL_SHA256["DG11-FULL"],
    }


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    env_file: Path,
    runtime_wheel: Path,
    install_manifest: Path,
    workers: int,
    tokenizer_path: Path,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if workers != 1:
        raise MemoraMiLAiContextError(
            "MiLAi cohort Runtime requires exactly one in-process worker"
        )
    _verify_install(
        method_id="DG11-FULL",
        runtime_wheel=runtime_wheel,
        install_manifest=install_manifest,
    )
    _require_inputs(input_path, allow_unfrozen_smoke=allow_unfrozen_smoke)
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    cohorts, cases = load_inputs(input_path)
    expected_ids = {case.case_id for case in cases}
    identity = _worker_identity(
        run_id=run_id,
        input_path=input_path,
        env_file=env_file,
        install_manifest=install_manifest,
    )
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        records = read_context_archive(output)
        if (
            not isinstance(existing, dict)
            or existing.get("worker_identity") != identity
            or len(records) != len(expected_ids)
            or {record.case_id for record in records} != expected_ids
        ):
            raise MemoraMiLAiContextError("completed Memora archive drifted")
        return existing
    cases_by_cohort: dict[str, list[MemoraCase]] = {
        cohort.cohort_id: [] for cohort in cohorts
    }
    for case in cases:
        if case.cohort_id not in cases_by_cohort:
            raise MemoraMiLAiContextError("Memora case references unknown cohort")
        cases_by_cohort[case.cohort_id].append(case)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    records_by_id: dict[str, ContextRecord] = {}
    cohort_stats: list[dict[str, Any]] = []
    for cohort in cohorts:
        cohort_cases = cases_by_cohort[cohort.cohort_id]
        with _CohortRuntime(cohort=cohort, env_file=env_file) as runtime:
            for case in cohort_cases:
                records_by_id[case.case_id] = runtime.query(case, tokenizer)
            cohort_stats.append(runtime.stats(question_count=len(cohort_cases)))
    records = tuple(records_by_id[case.case_id] for case in cases)
    failures = sum(record.terminal_status != "SUCCEEDED" for record in records)
    return cast(
        dict[str, Any],
        write_context_archive(
            output,
            run_id=run_id,
            benchmark_id="MEMORA-PREREGISTERED-60",
            records=records,
            metadata={
                "cohort_stats": cohort_stats,
                "failure_count": failures,
                "labels_accessed": False,
                "paper_labels_opened": False,
                "status": "PASS" if failures == 0 else "FAIL",
                "worker_count": workers,
                "worker_identity": identity,
            },
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--runtime-wheel", type=Path, required=True)
    parser.add_argument("--install-manifest", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1,), default=1)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        env_file=args.env_file.resolve(),
        runtime_wheel=args.runtime_wheel.resolve(),
        install_manifest=args.install_manifest.resolve(),
        workers=args.workers,
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
