"""Opt-in real MCP/HTTP/PG continuity diagnosis with fresh Host processes.

Requires an already migrated isolated database and installed local MCP/broker CLIs.
No inference service is contacted. Run artifacts remain in pytest's external base temp.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import subprocess
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from milai_openworker_mcp.trace_testkit import (
    NativeTaskMetadata,
    ObservedOpenWorkerProviderAdapter,
    OpenAIChatRequest,
)
from test_host_adapter import FIXTURE, _provider_manifest, _test_tokenizer_json
from test_trace_testkit import _Transport

PRODUCT = Path(__file__).resolve().parents[3]
QUERY = "Recall synthetic ceramic cups purchase marker"
CONTENT = "Synthetic ceramic cups purchase marker: ready for pickup."
SCOPE = {"project_ids": ["orchid-release"]}


def _post(base: str, token: str, path: str, body: object) -> dict[str, Any]:
    request = Request(  # noqa: S310 -- owned loopback endpoint
        base + path,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid4()),
        },
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310
        return json.load(response)  # type: ignore[no-any-return]


def _host_process(connection: Any, root: Path, policy_path: Path) -> None:
    """Fresh interpreter owns all native graph, Context locator and Provider state."""
    root.mkdir()
    policy = json.loads(policy_path.read_text())
    adapter = ObservedOpenWorkerProviderAdapter(
        _provider_manifest(root / "manifest.json", run_id=root.name),
        root / "ledger.jsonl",
        root / "trace.jsonl",
        memory_mode="query-first",
        prefetch_socket=Path(policy["socket_path"]),
        tokenizer_json=_test_tokenizer_json(root),
        broker_policy=policy_path,
        task_fixture=FIXTURE,
    )
    transport = _Transport()
    adapter.transport = transport
    host_instance = str(uuid4())
    try:
        connection.send({"pid": os.getpid(), "host_instance": host_instance})
        for _ in range(4):
            operation = connection.recv()
            if operation is None:
                break
            _, route = adapter.complete(
                OpenAIChatRequest.parse(
                    {
                        "model": "Qwen3.6-35B-A3B-FP8",
                        "stream": False,
                        "max_tokens": 64,
                        "messages": [{"role": "user", "content": QUERY}],
                    }
                ),
                NativeTaskMetadata(host_instance, "continuity-session", operation),
            )
            connection.send(
                {
                    "route": route,
                    "fixture_calls": len(transport.requests),
                    "trace": adapter.owner_traces()[-1],
                }
            )
    finally:
        adapter.close()
        connection.close()


@contextmanager
def _host(root: Path, policy: Path):  # type: ignore[no-untyped-def]
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_host_process, args=(child, root, policy))
    process.start()
    child.close()

    def receive() -> Any:
        assert parent.poll(15), "Host child exceeded bounded response time"
        return parent.recv()

    try:
        identity = receive()

        def call(operation: str) -> Any:
            parent.send(operation)
            return receive()

        yield identity, call
    finally:
        if process.is_alive():
            parent.send(None)
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent.close()
        assert process.exitcode == 0


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_fresh_host_reacquires_persisted_memory_and_offline_locator_fails_closed(
    tmp_path: Path,
) -> None:
    required = [
        "MILAI_TEST_API_DATABASE_URL",
        "MILAI_TEST_STEWARD_DATABASE_URL",
        "MILAI_TEST_WORKER_DATABASE_URL",
    ]
    if any(not os.environ.get(name) for name in required):
        pytest.skip("isolated role-separated PostgreSQL URLs not configured")
    runtime_module = pytest.importorskip("milai.testkit.observed_runtime")
    mcp_cli = PRODUCT / "integrations/mcp/.venv/bin/milai-mcp"
    broker_cli = PRODUCT / "integrations/openworker-mcp/.venv/bin/milai-mcp-broker"
    assert mcp_cli.is_file() and broker_cli.is_file()
    admin, reader, reviewer = ("synthetic-" + uuid4().hex for _ in range(3))
    socket_root = Path(tempfile.mkdtemp(prefix="milai-cont-", dir="/dev/shm"))
    token_file = socket_root / "reader.token"
    token_file.write_text(reader)
    token_file.chmod(0o600)
    config = {
        "environment": "test",
        "data_mode": "SYNTHETIC_ONLY",
        "database_url": os.environ[required[0]],
        "steward_database_url": os.environ[required[1]],
        "tenant_id": str(uuid4()),
        "local_actor_id": str(uuid4()),
        "blob_root": str(tmp_path / "blobs"),
        "api_token": admin,
        "agent_reader_token": reader,
        "agent_reviewer_token": reviewer,
        "causal_token_secret": "synthetic-" + uuid4().hex,
        "embedding_provider": "deterministic_hash",
        "embedding_prewarm": False,
    }
    observations: dict[str, Any] = {"model_requests": 0}
    runtime = runtime_module.ObservedRuntime(config)
    try:
        with ExitStack() as resources:
            with runtime:
                evidence = _post(
                    runtime.base_url,
                    admin,
                    "/v1/evidence",
                    {
                        "source_type": "RUNTIME_OBSERVATION",
                        "source_ref": "synthetic://continuity",
                        "subject_id": "orchid-release",
                        "observed_at": "2026-01-01T10:00:00Z",
                        "content": "Independent synthetic verification.",
                        "media_type": "text/plain",
                        "retention_state": "READABLE",
                        "permission_snapshot": {"readable": True, **SCOPE},
                    },
                )
                proposal = _post(
                    runtime.base_url,
                    admin,
                    "/v1/proposals",
                    {
                        "operation": "CREATE",
                        "proposed_patch": {
                            "subject_id": "synthetic-continuity",
                            "predicate": "synthetic.purchase",
                            "claim_type": "FACT",
                            "payload": {"memory_text": CONTENT},
                            "authority": "ACTION_SAFE",
                            "confidence": 0.99,
                        },
                        "supporting_evidence_refs": [evidence["evidence_id"]],
                        "scope_predicate": SCOPE,
                        "requested_authority": "ACTION_SAFE",
                        "derivation_policy_id": "synthetic-continuity",
                        "derivation_snapshot": {"fixture": "continuity"},
                    },
                )
                _post(
                    runtime.base_url,
                    reviewer,
                    f"/v1/proposals/{proposal['proposal_id']}/review",
                    {
                        "decision": "APPROVE",
                        "policy_version": "synthetic-continuity",
                        "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
                    },
                )
                subprocess.run(  # noqa: S603 -- Product CLI; isolated role/environment
                    [str(PRODUCT / "runtime/.venv/bin/milai-worker"), "--once"],
                    check=True,
                    capture_output=True,
                    timeout=20,
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "MILAI_ENVIRONMENT": "test",
                        "MILAI_WORKER_DATABASE_URL": os.environ[required[2]],
                        "MILAI_BLOB_ROOT": config["blob_root"],
                        "MILAI_TENANT_ID": config["tenant_id"],
                        "MILAI_LOCAL_ACTOR_ID": config["local_actor_id"],
                        "MILAI_EMBEDDING_PROVIDER": "deterministic_hash",
                        "MILAI_EMBEDDING_PREWARM": "false",
                        "MILAI_WORKER_EVENT_LIMIT": "3",
                    },
                )
                policy_path = tmp_path / "broker-policy.json"
                policy_path.write_text(
                    json.dumps(
                        {
                            "schema": "milai.openworker.mcp-broker-policy.v1",
                            "profile": "reader-lite",
                            "socket_path": str(socket_root / "reader.sock"),
                            "socket_mode": "0600",
                            "allowed_peer_uids": [os.geteuid()],
                            "mcp_executable": str(mcp_cli),
                            "mcp_executable_sha256": hashlib.sha256(
                                mcp_cli.read_bytes()
                            ).hexdigest(),
                            "base_url": runtime.base_url,
                            "scope": SCOPE,
                            "required_authority": "INFORMATIONAL",
                            "consistency_floor": "CANONICAL_REQUIRED",
                            "max_limit": 3,
                            "max_connections": 2,
                            "child_shutdown_seconds": 2,
                            "mcp_max_retries": 0,
                        }
                    )
                )
                log = resources.enter_context((tmp_path / "broker.log").open("wb"))
                broker = subprocess.Popen(  # noqa: S603 -- fixed local Product CLI
                    [
                        str(broker_cli),
                        "--policy",
                        str(policy_path),
                        "--token-file",
                        str(token_file),
                    ],
                    env={"PATH": os.environ.get("PATH", "")},
                    stdout=log,
                    stderr=log,
                )
                resources.callback(_stop, broker)
                for _ in range(100):
                    if (socket_root / "reader.sock").exists():
                        break
                    assert broker.poll() is None
                    time.sleep(0.05)
                else:
                    pytest.fail("broker startup timeout")
                with _host(tmp_path / "host-before", policy_path) as (identity, call):
                    observations["before_identity"] = identity
                    observations["first"] = call("op-1")
                    observations["continue"] = call("op-2")
                identity, call = resources.enter_context(
                    _host(tmp_path / "host-after", policy_path)
                )
                observations["after_identity"] = identity
                observations["restart"] = call("op-1")
                observations["restart_continue"] = call("op-2")
                observations["runtime"] = runtime.owner_traces()
            # Keep the actual Host process, MCP child and locator alive while Runtime stops.
            observations["runtime_unavailable"] = call("op-3")
    finally:
        token_file.unlink(missing_ok=True)
        (tmp_path / "diagnostic.json").write_text(json.dumps(observations, indent=2))
    assert observations["before_identity"]["pid"] != observations["after_identity"]["pid"]
    assert (
        observations["before_identity"]["host_instance"]
        != observations["after_identity"]["host_instance"]
    )
    names = ["first", "continue", "restart", "restart_continue"]
    for name in names:
        assert observations[name]["route"] == "PROVIDER_AVAILABLE"
    hosts = [observations[name]["trace"] for name in names]
    invocations = [row["mcp_invocations"][0] for row in hosts]
    assert [row["receipt_reused"] for row in invocations] == [False, True, False, True]
    assert [row["previous_context_ref"] is None for row in invocations] == [
        True,
        False,
        True,
        False,
    ]
    bound = [
        next(e for e in row["host_events"] if e["event"] == "HOST_NATIVE_TASK_BOUND")
        for row in hosts
    ]
    assert [row["task_relation"] for row in bound] == [
        "TASK_START",
        "CONTINUE",
        "TASK_START",
        "CONTINUE",
    ]
    traces = observations["runtime"]
    assert len(traces) == 4
    assert len({row["request_ref"] for row in traces}) == 4
    assert traces[0]["selected_claim_version_refs"] == traces[2]["selected_claim_version_refs"]
    assert len(traces[2]["selected_claim_version_refs"]) == 1
    assert traces[0]["retrieval_trace_ref"] != traces[2]["retrieval_trace_ref"]
    offline = observations["runtime_unavailable"]
    assert offline["route"] == "HOST_MEMORY_REQUIRED_BUT_UNAVAILABLE"
    assert offline["fixture_calls"] == 2
    assert offline["trace"]["provider_requests"] == []
