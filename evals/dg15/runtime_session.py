"""Persistent isolated Runtime/API/worker composition for DG-15 experiments."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Literal, cast

from evals.dg14.benchmark import (
    BUDGETS,
    DEFAULT_ENV_FILE,
    ROOT,
    LocalDG14RuntimeSession,
)
from evals.dg15.contracts import DG15AdapterConfig, TokenCounter
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.milai_mcp_adapter import DG15MilaiMcpAdapter


class LocalDG15RuntimeSession(LocalDG14RuntimeSession):
    """Keep one worker alive for the complete isolated development run."""

    def __init__(
        self,
        *,
        output_root: Path,
        env_file: Path = DEFAULT_ENV_FILE,
        project_root: Path = ROOT,
        mcp_concurrency: int = 4,
        projection_batch_size: int = 32,
        inherit_source_embedding_runtime: bool = False,
        barrier_timeout_ms: int = 15_000,
        data_mode: Literal["SYNTHETIC_ONLY", "DEIDENTIFIED_ALLOWED"] = (
            "DEIDENTIFIED_ALLOWED"
        ),
        memory_formation_mode: Literal["OFF", "SHADOW", "CANARY"] = "OFF",
        progressive_context_evidence: bool = False,
        budget_invariant_context: bool = False,
        retrieval_evidence_dense_enabled: bool = False,
    ) -> None:
        super().__init__(
            output_root=output_root,
            env_file=env_file,
            project_root=project_root,
            inherit_source_embedding_runtime=inherit_source_embedding_runtime,
            data_mode=data_mode,
            memory_formation_mode=memory_formation_mode,
            progressive_context_evidence=progressive_context_evidence,
            budget_invariant_context=budget_invariant_context,
            retrieval_evidence_dense_enabled=retrieval_evidence_dense_enabled,
        )
        if mcp_concurrency not in {1, 2, 4, 8}:
            raise ValueError("mcp_concurrency must be one of 1, 2, 4, or 8")
        if projection_batch_size not in {1, 16, 32, 64}:
            raise ValueError("projection_batch_size must be one of 1, 16, 32, or 64")
        if not 0 <= barrier_timeout_ms <= 120_000:
            raise ValueError("barrier_timeout_ms must be between 0 and 120000")
        self._mcp_concurrency = cast(Literal[1, 2, 4, 8], mcp_concurrency)
        self._projection_batch_size = projection_batch_size
        self._barrier_timeout_ms = barrier_timeout_ms
        self._worker_process: subprocess.Popen[bytes] | None = None
        self._worker_started_ms = 0.0
        self._mcp_transports: list[MultiplexedStdioMcpTransport] = []
        self._matched_replay_database: Any | None = None
        self._matched_replay_service: Any | None = None

    def start(self, run_id: str) -> Mapping[str, Any]:
        started = perf_counter()
        details = dict(super().start(run_id))
        if self._environment is None or self._database_urls is None:
            raise RuntimeError("Runtime environment is absent after startup")
        environment = dict(self._environment)
        environment["MILAI_WORKER_DATABASE_URL"] = self._database_urls["worker"]
        environment["MILAI_WORKER_EVENT_LIMIT"] = "10000"
        environment["MILAI_WORKER_RETRY_DELAY_SECONDS"] = "0"
        environment["MILAI_WORKER_POLL_INTERVAL_SECONDS"] = "0.01"
        environment["MILAI_WORKER_PROJECTION_BATCH_SIZE"] = str(
            self._projection_batch_size
        )
        worker_started = perf_counter()
        process = subprocess.Popen(
            [str(self.project_root / "runtime/.venv/bin/milai-worker")],
            cwd=self.project_root / "runtime",
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=self._runtime_log,
            stderr=subprocess.STDOUT,
        )
        self._worker_process = process
        self._record_ownership("WORKER_PROCESS_STARTED", worker_pid=process.pid)
        sleep(0.1)
        if process.poll() is not None:
            raise RuntimeError("persistent projection worker exited during startup")
        self._worker_started_ms = (perf_counter() - worker_started) * 1_000
        details.update(
            {
                "composition_startup_ms": round((perf_counter() - started) * 1_000, 6),
                "persistent_worker": True,
                "worker_pid": process.pid,
                "worker_startup_ms": round(self._worker_started_ms, 6),
                "worker_starts": 1,
                "projection_batch_size": self._projection_batch_size,
                "mcp_concurrency": self._mcp_concurrency,
            }
        )
        return details

    def worker_status(self) -> Mapping[str, object]:
        process = self._worker_process
        if process is None:
            return {"status": "NOT_STARTED", "worker_starts": 0}
        return {
            "status": "RUNNING" if process.poll() is None else "EXITED",
            "pid": process.pid,
            "return_code": process.poll(),
            "worker_starts": 1,
            "startup_ms": self._worker_started_ms,
        }

    def projection_metrics(self) -> Mapping[str, Any]:
        """Read current worker delivery metrics through the worker login role."""

        if (
            self._settings is None
            or self._database_urls is None
            or self._worker_process is None
        ):
            raise RuntimeError("projection metrics requested before worker startup")
        runtime_src = self.project_root / "runtime/src"
        import sys

        if str(runtime_src) not in sys.path:
            sys.path.insert(0, str(runtime_src))
        from milai.persistence import Database, SessionContext
        from milai.persistence.projection_repository import ProjectionRepository

        database = Database(
            self._settings,
            dsn=self._database_urls["worker"],
            expected_role="milai_worker",
        )
        try:
            repository = ProjectionRepository(database)
            return repository.metrics_snapshot(
                SessionContext(
                    self._settings.tenant_id,
                    self._settings.local_actor_id,
                )
            )
        finally:
            database.close()

    def adapter_config(self) -> DG15AdapterConfig:
        if self._settings is None or self._tokens is None:
            raise RuntimeError("Runtime adapter requested before session start")
        return DG15AdapterConfig(
            base_url=f"http://{self._settings.bind_host}:{self._settings.bind_port}",
            executable=self.project_root / "integrations/mcp/.venv/bin/milai-mcp",
            profile_tokens={
                "operator": self._tokens["operator"],
                "reader-detail": self._tokens["reader"],
                "reviewer": self._tokens["reviewer"],
                "submitter": self._tokens["submitter"],
            },
            tenant_id=str(self._settings.tenant_id),
            principal_id=str(self._settings.local_actor_id),
            scope={},
            max_limit=50,
            allowed_budgets=BUDGETS,
            mcp_concurrency=self._mcp_concurrency,
            barrier_timeout_ms=self._barrier_timeout_ms,
            barrier_projections=("evidence", "fts", "vector"),
            formation_mode=self._memory_formation_mode,
        )

    def adapter_for_case(self, _case: Any, token_counter: TokenCounter) -> Any:
        config = self.adapter_config()
        transport = MultiplexedStdioMcpTransport(config.dg14_config())
        self._mcp_transports.append(transport)
        return DG15MilaiMcpAdapter(
            config,
            token_counter=token_counter,
            transport=transport,
            close_transport_on_cleanup=False,
        )

    def matched_resolve(self, request: Any, request_id: str) -> Any:
        """Run the Runtime-only Q1R dual-policy view over one retrieval call."""

        if self._settings is None or self._database_urls is None:
            raise RuntimeError("matched resolve requested before session start")
        if self._matched_replay_service is None:
            from milai.api.app import _embedding_provider, _reranker_provider
            from milai.application.memory_resolve import MemoryResolveService
            from milai.application.retrieval import RetrievalService
            from milai.domain import CausalTokenCodec
            from milai.persistence import Database
            from milai.persistence.retrieval_repository import RetrievalRepository

            database = Database(
                self._settings,
                dsn=self._database_urls["api"],
                expected_role="milai_api",
            )
            retrieval = RetrievalService(
                RetrievalRepository(database),
                embedding=_embedding_provider(self._settings),
                causal_tokens=CausalTokenCodec(
                    self._settings.causal_token_secret.get_secret_value()
                ),
                mmr_enabled=self._settings.retrieval_mmr_enabled,
                mmr_lambda=self._settings.retrieval_mmr_lambda,
                reranker=_reranker_provider(self._settings),
                reranker_pool_size=self._settings.retrieval_reranker_pool_size,
                temporal_reranker_pool_size=(
                    self._settings.retrieval_temporal_reranker_pool_size
                ),
            )
            self._matched_replay_database = database
            self._matched_replay_service = MemoryResolveService(retrieval)
        from milai.persistence import SessionContext

        return self._matched_replay_service.resolve_matched_replay(
            SessionContext(
                self._settings.tenant_id,
                self._settings.local_actor_id,
            ),
            request,
            request_id,
        )

    def close(self) -> Mapping[str, Any]:
        for transport in reversed(self._mcp_transports):
            transport.close()
        self._mcp_transports = []
        matched_database = self._matched_replay_database
        self._matched_replay_database = None
        self._matched_replay_service = None
        if matched_database is not None:
            matched_database.close()
        worker = self._worker_process
        self._worker_process = None
        worker_result: dict[str, object] = {"status": "NOT_STARTED"}
        if worker is not None:
            worker.terminate()
            try:
                return_code = worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                return_code = worker.wait(timeout=5)
                worker_result = {"status": "KILLED", "return_code": return_code}
            else:
                worker_result = {"status": "STOPPED", "return_code": return_code}
        runtime_result = dict(super().close())
        runtime_result["persistent_worker"] = worker_result
        return runtime_result
