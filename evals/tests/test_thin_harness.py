from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from evals.datasets import BEAM, CUPID, HORIZON, LONGMEMEVAL, MEMORA, map_record
from evals.harness import (
    BuildReceipt,
    EvaluationRuntimeLease,
    OpenWorkerMcpMemoryMethodAdapter,
)


class _Client:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.closed = False

    def recall(self, query: str) -> dict[str, Any]:
        return {
            "status": "OK",
            "items": [{"payload": {"query": query}}],
            "open_issue_ids": [],
            "trace_id": f"trace-{len(self.responses)}",
            "stage_metrics": {"durations_ms": {"query_total_ms": 1.0}, "counts": {}},
        }

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("mapping", [LONGMEMEVAL, MEMORA, BEAM, HORIZON, CUPID])
def test_all_dataset_mappings_use_one_workload_contract(mapping) -> None:  # type: ignore[no-untyped-def]
    record = {
        mapping.workload_id_field: "workload-1",
        mapping.question_id_field: "question-1",
        mapping.question_field: "What was remembered?",
        mapping.answer_field: "the answer",
        mapping.history_field: [
            {
                "session_id": "session-a",
                "turns": [
                    {
                        "id": "turn-1",
                        "role": "user",
                        "content": "synthetic memory",
                        "timestamp": "2026-08-24T00:00:00+00:00",
                    }
                ],
            }
        ],
    }

    mapped = map_record(record, mapping)

    assert mapped.history.dataset_id == mapping.dataset_id
    assert mapped.history.items[0].session_id == "session-a"


def test_mapping_preserves_session_timestamp_for_product_valid_time() -> None:
    mapped = map_record(
        {
            "case_id": "case-1",
            "question": "What was remembered?",
            "answer": "memory",
            "history": [
                {
                    "session_id": "session-a",
                    "observed_at": "2026-08-24T00:00:00+00:00",
                    "turns": [{"role": "user", "content": "memory"}],
                }
            ],
        },
        HORIZON,
    )

    assert mapped.history.items[0].occurred_at == "2026-08-24T00:00:00+00:00"
    assert mapped.questions[0].workload_id == mapped.history.workload_id


def test_one_openworker_mcp_adapter_accepts_every_mapped_workload() -> None:
    loaded: list[str] = []
    clients: list[_Client] = []

    def load(history):  # type: ignore[no-untyped-def]
        loaded.append(history.dataset_id)
        return BuildReceipt(history.fingerprint, "READY", 1, {"build_calls": 1})

    def client_factory(_path: Path) -> _Client:
        client = _Client([])
        clients.append(client)
        return client

    adapter = OpenWorkerMcpMemoryMethodAdapter(client_factory)
    for mapping in [LONGMEMEVAL, MEMORA, BEAM, HORIZON, CUPID]:
        record = {
            mapping.workload_id_field: f"{mapping.dataset_id}-workload",
            mapping.question_id_field: f"{mapping.dataset_id}-question",
            mapping.question_field: "What was remembered?",
            mapping.answer_field: "memory",
            mapping.history_field: [[{"role": "user", "content": "memory"}]],
        }
        mapped = map_record(record, mapping)
        lease = EvaluationRuntimeLease(
            lease_id=f"lease-{mapping.dataset_id}",
            reader_socket=Path("/tmp/reader-lite.sock"),
            product_manifest_sha256="a" * 64,
            history_loader=load,
            close_callback=lambda: None,
        )

        result = adapter.run(lease, mapped.history, mapped.questions)

        assert result[0].status == "OK"
        assert result[0].metadata["dataset_id"] == mapping.dataset_id
        assert result[0].product_usage["build"] == {"build_calls": 1}

    assert loaded == ["LONGMEMEVAL", "MEMORA", "BEAM", "HORIZON", "CUPID"]
    assert all(client.closed for client in clients)


def test_lease_binds_build_receipt_to_immutable_workload() -> None:
    mapping = LONGMEMEVAL
    record = {
        "question_id": "q-1",
        "question": "query",
        "answer": "answer",
        "haystack_sessions": [[{"role": "user", "content": "memory"}]],
    }
    history = map_record(record, mapping).history
    lease = EvaluationRuntimeLease(
        "lease",
        Path("/tmp/reader-lite.sock"),
        "a" * 64,
        lambda _history: BuildReceipt("0" * 64, "READY", 1, {}),
        lambda: None,
    )

    with pytest.raises(RuntimeError, match="immutable workload"):
        lease.load_history(history)


def test_adapter_reuses_an_unchanged_immutable_workload() -> None:
    history = map_record(
        {
            "question_id": "q-1",
            "question": "query",
            "answer": "answer",
            "haystack_sessions": [[{"role": "user", "content": "memory"}]],
        },
        LONGMEMEVAL,
    )
    client = _Client([])
    lease = EvaluationRuntimeLease(
        "lease",
        Path("/tmp/reader-lite.sock"),
        "a" * 64,
        lambda _history: BuildReceipt(
            history.history.fingerprint,
            "UNCHANGED",
            1,
            {"build_calls": 0, "immutable_workload_reused": True},
        ),
        lambda: None,
    )

    result = OpenWorkerMcpMemoryMethodAdapter(lambda _path: client).run(
        lease, history.history, history.questions
    )

    assert result[0].product_usage["build"] == {
        "build_calls": 0,
        "immutable_workload_reused": True,
    }
    assert result[0].metadata["context"].startswith("MEMORY_STATUS=AVAILABLE\n")
    assert result[0].metadata["context_status"] == "AVAILABLE"


def test_thin_harness_has_no_runtime_private_or_dataset_execution_imports() -> None:
    files = [
        *Path("evals/harness").glob("*.py"),
        Path("evals/datasets/workloads.py"),
    ]
    forbidden = ("milai.", "runtime.", "evals.dg12", "evals.paper.runners")
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "_CohortRuntime" not in source
        tree = ast.parse(source)
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        assert not any(module.startswith(forbidden) for module in imports)

    adapter_source = Path("evals/harness/openworker_mcp.py").read_text(encoding="utf-8")
    assert "from milai_openworker_mcp import McpUnixClient" in adapter_source
    assert "max_frame_bytes=2 * 1024 * 1024" in adapter_source
