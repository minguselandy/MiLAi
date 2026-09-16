from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from time import perf_counter
from typing import Any, Protocol

from evals.harness.contracts import ResultRecord, WorkloadHistory, WorkloadQuestion
from evals.harness.lease import EvaluationRuntimeLease


class _RecallClient(Protocol):
    def recall(self, query: str) -> dict[str, Any]: ...

    def close(self) -> None: ...


def _installed_client(socket_path):  # type: ignore[no-untyped-def]
    from milai_openworker_mcp import McpUnixClient

    return McpUnixClient(
        socket_path,
        request_timeout_seconds=30,
        max_frame_bytes=2 * 1024 * 1024,
    )


class OpenWorkerMcpMemoryMethodAdapter:
    """Dataset-neutral adapter over the installed OpenWorker profile socket."""

    method_id = "MILAI_OPENWORKER_MCP"

    def __init__(
        self,
        client_factory: Callable[[Any], _RecallClient] = _installed_client,
    ) -> None:
        self._client_factory = client_factory

    def run(
        self,
        lease: EvaluationRuntimeLease,
        history: WorkloadHistory,
        questions: Sequence[WorkloadQuestion],
    ) -> tuple[ResultRecord, ...]:
        build = lease.load_history(history)
        if build.status not in {"READY", "UNCHANGED"}:
            raise RuntimeError(f"product build is not ready: {build.status}")
        client = self._client_factory(lease.reader_socket)
        try:
            results: list[ResultRecord] = []
            for question in questions:
                if question.workload_id != history.workload_id:
                    raise ValueError("question is bound to a different workload")
                started = perf_counter()
                response = client.recall(question.query)
                elapsed_ms = round((perf_counter() - started) * 1_000, 3)
                from milai_client import prepare_compact_prefetch

                context = prepare_compact_prefetch(
                    response,
                    query=question.query,
                    max_context_chars=1_400,
                )
                results.append(
                    ResultRecord(
                        method_id=self.method_id,
                        workload_id=history.workload_id,
                        question_id=question.question_id,
                        status=str(response["status"]),
                        items=tuple(response.get("items", [])),
                        open_issue_ids=tuple(
                            str(value) for value in response.get("open_issue_ids", [])
                        ),
                        trace_id=(
                            str(response["trace_id"])
                            if response.get("trace_id") is not None
                            else None
                        ),
                        elapsed_ms=elapsed_ms,
                        product_usage={
                            "build": build.product_usage,
                            "stage_metrics": response.get("stage_metrics", {}),
                        },
                        metadata={
                            "dataset_id": history.dataset_id,
                            "product_manifest_sha256": lease.product_manifest_sha256,
                            "context": context.rendered,
                            "context_sha256": context.context_sha256,
                            "context_bytes_sha256": hashlib.sha256(
                                context.rendered.encode()
                            ).hexdigest(),
                            "context_status": context.status,
                            "context_compiler_version": context.compiler_version,
                            "context_rendered_tokens": context.rendered_tokens,
                            "session_refs": context.session_refs,
                        },
                    )
                )
            return tuple(results)
        finally:
            client.close()
