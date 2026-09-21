"""Real Runtime/PG with offline signed AS keys, never production OAuth tokens."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx2 as httpx
import pytest
from milai_client import MilaiClient, UnavailableError
from starlette.testclient import TestClient

from milai_mcp.auth_policy import PILOT_SCOPES, AdmissionPolicy, principal_for
from milai_mcp.http_transport import HttpResourceBinding
from milai_mcp.server import CodexFullRuntimeClients, build_server
from support.auth import ISSUER, RESOURCE, Fixture
from support.http import rpc
from support.postgres import (
    _ROOT,
    _RUNTIME_ROOT,
    _create_and_migrate_database,
    _drop_database,
    _free_port,
    _required_environment,
    _runtime_environment,
    _start_process,
    _wait_ready,
    _worker_environment,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("MILAI_MCP_BASELINE_E2E") != "1",
    reason="requires disposable real PostgreSQL role configuration",
)


def _worker(config_path: Path, phase: str) -> None:
    config = json.loads(config_path.read_text())
    root = config_path.parent
    fixture = Fixture(root / (phase + "-policy.json"))
    private_mode = config.get("access_mode") == "authenticated_private"
    project = "project-other" if phase == "foreign" and not private_mode else "project-one"
    fixture.doc["project_id"] = project
    fixture.doc["owners"][0]["principal_id"] = principal_for(ISSUER, "owner", project)
    fixture.doc["owners"][0]["allowed_scopes"] = sorted(PILOT_SCOPES)
    if private_mode:
        fixture.doc.update(mode="authenticated_private", owners=[])
    fixture.write()
    binding = HttpResourceBinding.create(
        issuer_url=ISSUER,
        resource_url=RESOURCE,
        scope={"project_ids": [project]},
        scopes=tuple(sorted(PILOT_SCOPES)),
    )
    transport = httpx.AsyncClient(transport=httpx.MockTransport(fixture.response))
    verifier = fixture.verifier(transport)
    verifier.scope_digest = binding.scope_digest
    verifier.policy = AdmissionPolicy(
        fixture.path,
        issuer=ISSUER,
        project_id=project,
        enabled_scopes=PILOT_SCOPES,
        trusted_owner_uid=os.getuid(),
        mode="authenticated_private" if private_mode else "explicit_owners",
    )
    clients = {
        role: MilaiClient(
            base_url=config["runtime_url"],
            token=config["tokens"][role],
            max_retries=0,
        )
        for role in ["reader", "submitter", "reviewer", "operator"]
    }
    server = build_server(
        "codex-full",
        clients["reader"],
        default_scope={"project_ids": [project]},
        http_principal_binding=binding,
        http_token_verifier=verifier,
        codex_full_clients=CodexFullRuntimeClients(**clients),
        codex_working_state_scope_refs={"TASK": "aigcit-pg-task"},
        max_retries=0,
    )
    token = fixture.token(
        sub="second-user" if private_mode and phase == "foreign" else "owner",
        scope=" ".join(sorted(PILOT_SCOPES)),
        client_id=phase,
        tenant="forged-tenant",
        project="forged-project",
        role="operator",
    )
    report: dict[str, Any] = {"pid": os.getpid(), "phase": phase}
    try:
        with TestClient(
            server.streamable_http_app(json_response=True, stateless_http=True),
            base_url=RESOURCE.removesuffix("/mcp"),
        ) as http:

            def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                response = rpc(
                    http,
                    "tools/call",
                    token=token,
                    params={
                        "name": name,
                        "arguments": arguments,
                    },
                )
                assert response.status_code == 200, response.text
                return dict(response.json()["result"])

            current = call("milai_working_state_get", {"scope": "TASK"})
            assert not current.get("isError"), current
            state = current["structuredContent"]
            if phase == "save":
                assert state["status"] == "ABSENT"
                captured = call(
                    "milai_evidence_capture",
                    {
                        "operation_id": "public-evidence",
                        "source_type": "AGENT_TURN",
                        "source_ref": "aigcit-pg/source",
                        "subject_id": "aigcit-pg-test",
                        "observed_at": datetime.now(UTC).isoformat(),
                        "content": "FIRST 完整原文 evidence-private-canary LAST",
                        "confirmation": "CAPTURE",
                    },
                )
                assert not captured.get("isError"), captured
                evidence = captured["structuredContent"]
                (root / "evidence-receipt.json").write_text(json.dumps(evidence))
                if private_mode:
                    for _ in range(50):
                        found = call("milai_memory_resolve", {"query": "evidence-private-canary"})
                        if "evidence-private-canary" in json.dumps(found):
                            break
                        time.sleep(0.1)
                    else:
                        raise AssertionError("own captured Evidence not retrievable")
                    resolved = found["structuredContent"]
                    report["own_evidence_retrieved"] = True
                    (root / "private-context.json").write_text(json.dumps(resolved))
                qualified = call(
                    "milai_working_state_update",
                    {
                        "scope": "PROJECT",
                        "operation_id": "qualified-source",
                        "expected_version": 0,
                        "payload": {"evidence_refs": [evidence["evidence_id"]]},
                    },
                )
                assert not qualified.get("isError"), qualified
                request = {
                    "scope": "TASK",
                    "operation_id": "stable-operation",
                    "expected_version": 0,
                    "payload": {"first": "完整来源", "last": "cold-process-canary"},
                }
                saved = call("milai_working_state_update", request)
                assert not saved.get("isError"), saved
                receipt = saved["structuredContent"]
                assert receipt["version"] == 1
                (root / "receipt.json").write_text(json.dumps(receipt))
                report["saved"] = receipt
                replay = call("milai_working_state_update", request)["structuredContent"]
                assert replay["replayed"] is True and replay["version"] == 1
                real_update = clients["submitter"].update_working_state
                committed: list[dict[str, Any]] = []

                def drop_response(payload: dict[str, Any], *, operation_id: str) -> dict[str, Any]:
                    committed.append(real_update(payload, operation_id=operation_id))
                    raise UnavailableError("wire-loss-canary", code="UNAVAILABLE", details={})

                unknown_request = {
                    "scope": "SESSION",
                    "operation_id": "unknown-operation",
                    "expected_version": 0,
                    "payload": {"unknown_commit": "saved-before-response-loss"},
                }
                with patch.object(clients["submitter"], "update_working_state", drop_response):
                    unknown = call("milai_working_state_update", unknown_request)
                assert unknown.get("isError") and "WORKING_STATE_OUTCOME_UNKNOWN" in json.dumps(
                    unknown
                )
                assert "wire-loss-canary" not in json.dumps(unknown)
                assert len(committed) == 1 and committed[0]["version"] == 1
                later = call(
                    "milai_working_state_update",
                    {
                        "scope": "SESSION",
                        "operation_id": "later-operation",
                        "expected_version": 1,
                        "state_id": committed[0]["state_id"],
                        "payload": {"later": "different head"},
                    },
                )
                assert later["structuredContent"]["version"] == 2
                report["unknown_after_real_commit"] = unknown
                report["unknown_attempts"] = len(committed)
            elif phase == "foreign":
                assert state["status"] == "ABSENT"
                receipt = json.loads((root / "receipt.json").read_text())
                denied_state = call(
                    "milai_working_state_update",
                    {
                        "scope": "TASK",
                        "state_id": receipt["state_id"],
                        "expected_version": 0,
                        "operation_id": "foreign-state-id",
                        "payload": {"foreign": "must-not-write"},
                    },
                )
                assert denied_state.get("isError"), denied_state
                evidence = json.loads((root / "evidence-receipt.json").read_text())
                denied_source = call(
                    "milai_working_state_update",
                    {
                        "scope": "PROJECT",
                        "operation_id": "foreign-source",
                        "expected_version": 0,
                        "payload": {"evidence_refs": [evidence["evidence_id"]]},
                    },
                )
                assert denied_source.get("isError"), denied_source
                assert "evidence-private-canary" not in json.dumps(denied_source)
                unchanged = call("milai_working_state_get", {"scope": "TASK"})["structuredContent"]
                assert unchanged["status"] == "ABSENT"
                unchanged_project = call("milai_working_state_get", {"scope": "PROJECT"})[
                    "structuredContent"
                ]
                assert unchanged_project["status"] == "ABSENT"
                report["cross_project_state_denied"] = True
                report["cross_project_evidence_reference_denied"] = True
                if private_mode:
                    lookup = call("milai_memory_resolve", {"query": "evidence-private-canary"})
                    assert "evidence-private-canary" not in json.dumps(lookup)
                    context = json.loads((root / "private-context.json").read_text())
                    assert isinstance(context.get("context_id"), str)
                    continued = call("milai_memory_resolve", {
                        "query": "evidence-private-canary",
                        "previous_context_id": context["context_id"],
                    })
                    assert continued.get("isError"), continued
                    assert "evidence-private-canary" not in json.dumps(continued)
                    report["cross_user_search_and_continuation_denied"] = True
                    own_evidence = call("milai_evidence_capture", {
                        "operation_id": "public-evidence", "source_type": "AGENT_TURN",
                        "source_ref": "aigcit-pg/source", "subject_id": "aigcit-pg-test",
                        "observed_at": datetime.now(UTC).isoformat(),
                        "content": "FIRST second-user-private-canary LAST",
                        "confirmation": "CAPTURE",
                    })["structuredContent"]
                    assert own_evidence["evidence_id"] != evidence["evidence_id"]
                    for _ in range(50):
                        own_lookup = call("milai_memory_resolve", {
                            "query": "second-user-private-canary",
                        })
                        if "second-user-private-canary" in json.dumps(own_lookup):
                            break
                        time.sleep(0.1)
                    else:
                        raise AssertionError("second user's own Evidence not retrievable")
                    own = call("milai_working_state_update", {
                        "scope": "TASK", "operation_id": "stable-operation",
                        "expected_version": 0,
                        "payload": {"first": "second-user", "last": "private"},
                    })["structuredContent"]
                    assert own["version"] == 1 and own["state_id"] != receipt["state_id"]
                    token = fixture.token(sub="owner", scope=" ".join(sorted(PILOT_SCOPES)))
                    original = call("milai_working_state_get", {"scope": "TASK"})[
                        "structuredContent"
                    ]
                    assert original["state_id"] == receipt["state_id"]
                    assert original["payload"] != own["payload"]
                    forbidden = call("milai_memory_resolve", {
                        "query": "second-user-private-canary",
                    })
                    assert "second-user-private-canary" not in json.dumps(forbidden)
                    report["two_users_same_endpoint_independent_state"] = True
                    report["two_users_same_source_and_operation_independent_evidence"] = True
            else:
                receipt = json.loads((root / "receipt.json").read_text())
                assert (
                    state["state_id"] == receipt["state_id"]
                    and state["payload"] == receipt["payload"]
                )
                report["recovered"] = state
                session_head = call("milai_working_state_get", {"scope": "SESSION"})[
                    "structuredContent"
                ]
                assert session_head["version"] == 2
                confirmed_operation = call(
                    "milai_working_state_update",
                    {
                        "scope": "SESSION",
                        "operation_id": "unknown-operation",
                        "expected_version": 0,
                        "payload": {"unknown_commit": "saved-before-response-loss"},
                    },
                )["structuredContent"]
                assert confirmed_operation["replayed"] and confirmed_operation["version"] == 1
                assert confirmed_operation["state_id"] == session_head["state_id"]
                report["unknown_operation_confirmed_by_explicit_replay"] = confirmed_operation
                report["independent_current_head"] = session_head
                # A new client and signing key must retain the operation namespace.
                replay = call(
                    "milai_working_state_update",
                    {
                        "scope": "TASK",
                        "operation_id": "stable-operation",
                        "expected_version": 0,
                        "payload": receipt["payload"],
                    },
                )["structuredContent"]
                assert replay["replayed"] is True and replay["version"] == 1

                def race(index: int) -> dict[str, Any]:
                    return call(
                        "milai_working_state_update",
                        {
                            "scope": "TASK",
                            "operation_id": f"race-{index}",
                            "expected_version": 1,
                            "state_id": receipt["state_id"],
                            "payload": {"winner": index},
                        },
                    )

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(race, [0, 1]))
                assert sum(not result.get("isError", False) for result in results) == 1, results
                head = call("milai_working_state_get", {"scope": "TASK"})["structuredContent"]
                assert head["version"] == 2
                report["cas"] = results
                if private_mode:
                    fixture.doc["disabled_subjects"] = ["owner"]
                else:
                    fixture.doc["owners"][0]["enabled"] = False
                fixture.write()
                denied = rpc(
                    http,
                    "tools/call",
                    token=token,
                    params={
                        "name": "milai_working_state_get",
                        "arguments": {"scope": "TASK"},
                    },
                )
                assert denied.status_code == 403
                report["revoked_status"] = denied.status_code
            (root / (phase + "-result.json")).write_text(json.dumps(report, ensure_ascii=False))
    finally:
        for client in clients.values():
            client.close()
        asyncio.run(transport.aclose())


@pytest.mark.parametrize("access_mode", ["explicit_owners", "authenticated_private"])
def test_aigcit_real_postgres_save_cold_resume_cas(tmp_path: Path, access_mode: str) -> None:
    owner = _required_environment("MILAI_MIGRATION_DATABASE_URL")
    database = "milai_mcpbase_" + secrets.token_hex(10)
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in [
            "legacy",
            "causal",
            "reader",
            "submitter",
            "reviewer",
            "operator",
        ]
    }
    api = None
    worker = None
    urls = None
    try:
        urls = _create_and_migrate_database(owner, database)
        port = _free_port()
        tenant_id, actor_id = secrets.token_hex(16), secrets.token_hex(16)
        environment = _runtime_environment(
            urls,
            tokens,
            tenant_id=tenant_id,
            actor_id=actor_id,
            blob_root=tmp_path / "blobs",
            port=port,
        )
        api = _start_process(
            _RUNTIME_ROOT / ".venv/bin/milai-api",
            arguments=[],
            cwd=_RUNTIME_ROOT,
            environment=environment,
        )
        _wait_ready(f"http://127.0.0.1:{port}/health/ready", api)
        if access_mode == "authenticated_private":
            worker = _start_process(
                _RUNTIME_ROOT / ".venv/bin/milai-worker", arguments=[], cwd=_RUNTIME_ROOT,
                environment=_worker_environment(
                    urls, tenant_id=tenant_id, actor_id=actor_id, blob_root=tmp_path / "blobs",
                ),
            )
        config = tmp_path / "worker-config.json"
        config.touch(mode=0o600)
        config.write_text(json.dumps({
            "runtime_url": f"http://127.0.0.1:{port}", "tokens": tokens, "access_mode": access_mode,
        }))
        for phase in ["save", "resume", "foreign"]:
            result = subprocess.run(  # noqa: S603 - exact test worker and isolated config
                [sys.executable, str(Path(__file__).resolve()), str(config), phase],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=_ROOT,
            )
            # Logs contain synthetic fixtures only; never inherit real OAuth credentials.
            (tmp_path / (phase + ".log")).write_text(result.stdout + result.stderr)
            assert result.returncode == 0, result.stderr[-4000:]
        saved = json.loads((tmp_path / "save-result.json").read_text())
        resumed = json.loads((tmp_path / "resume-result.json").read_text())
        assert saved["pid"] != resumed["pid"]
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        if api is not None:
            api.terminate()
            try:
                api.wait(timeout=15)
            except subprocess.TimeoutExpired:
                api.kill()
                api.wait(timeout=5)
        if urls is not None:
            _drop_database(owner, database)


if __name__ == "__main__":
    _worker(Path(sys.argv[1]), sys.argv[2])
