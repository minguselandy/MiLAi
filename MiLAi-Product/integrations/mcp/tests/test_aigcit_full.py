from __future__ import annotations

import base64
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from milai_client import MilaiClient

from milai_mcp.auth_policy import FULL_SCOPES, TOOL_SCOPES, AdmissionPolicy
from test_aigcit_auth import ISSUER, Fixture
from test_aigcit_http import edge, rpc
from test_codex_full_postgres_e2e import (
    _RUNTIME_ROOT,
    _create_and_migrate_database,
    _drop_database,
    _free_port,
    _required_environment,
    _runtime_environment,
    _start_process,
    _stop_process,
    _wait_ready,
)


def private_fixture(path: Path) -> Fixture:
    fixture = Fixture(path)
    fixture.doc.update(mode="authenticated_private", owners=[])
    fixture.write()
    return fixture


def test_full_private_catalog_and_every_scope_dispatch_boundary(tmp_path: Path) -> None:
    fixture = private_fixture(tmp_path / "policy.json")
    AdmissionPolicy(
        fixture.path, issuer=ISSUER, project_id="project-one", enabled_scopes=FULL_SCOPES,
        trusted_owner_uid=os.getuid(), mode="authenticated_private",
    ).load()
    with edge(fixture, scopes=FULL_SCOPES) as (http, _server, roles):
        for scopes in [FULL_SCOPES, *[frozenset({s}) for s in sorted(FULL_SCOPES)]]:
            token = fixture.token(sub="ordinary-user", scope=" ".join(scopes))
            listed = rpc(http, "tools/list", token=token).json()["result"]["tools"]
            expected = {name for name, scope in TOOL_SCOPES.items() if scope in scopes}
            assert {tool["name"] for tool in listed} == expected
            before = [len(role.calls) for role in roles]
            for name in set(TOOL_SCOPES) - expected:
                denied = rpc(http, "tools/call", token=token,
                             params={"name": name, "arguments": {}}).json()
                assert "error" in denied or denied["result"].get("isError")
            assert [len(role.calls) for role in roles] == before
        assert not AdmissionPolicy.allows_tool("unmapped_admin", set(FULL_SCOPES))
        # A previously granted token cannot bypass local account disabling.
        fixture.doc["disabled_subjects"] = ["ordinary-user"]
        fixture.write()
        assert rpc(http, "tools/list", token=token).status_code == 403


@pytest.mark.skipif(
    os.environ.get("MILAI_MCP_BASELINE_E2E") != "1",
    reason="requires disposable real PostgreSQL roles",
)
def test_full_private_lifecycle_and_cross_user_denial_real_postgres(tmp_path: Path) -> None:
    owner = _required_environment("MILAI_MIGRATION_DATABASE_URL")
    database = "milai_mcpbase_" + secrets.token_hex(10)
    urls = None
    api = None
    clients: list[MilaiClient] = []
    try:
        urls = _create_and_migrate_database(owner, database)
        tokens = {name: secrets.token_urlsafe(48) for name in [
            "legacy", "causal", "reader", "submitter", "reviewer", "operator",
        ]}
        port = _free_port()
        environment = _runtime_environment(
            urls, tokens, tenant_id=secrets.token_hex(16), actor_id=secrets.token_hex(16),
            blob_root=tmp_path / "blobs", port=port,
        )
        environment.update(
            MILAI_DATA_MODE="LOCAL_PERSONAL_DATA", MILAI_BLOB_ENCRYPTION="AES_256_GCM",
            MILAI_BLOB_KEK_B64=base64.b64encode(secrets.token_bytes(32)).decode(),
            MILAI_BACKUP_KEY_RECOVERY_CONFIRMED="true",
        )
        api = _start_process(
            _RUNTIME_ROOT / ".venv/bin/milai-api", arguments=[], cwd=_RUNTIME_ROOT,
            environment=environment,
        )
        _wait_ready(f"http://127.0.0.1:{port}/health/ready", api)
        clients = [MilaiClient(base_url=f"http://127.0.0.1:{port}", token=tokens[role],
                              max_retries=0)
                   for role in ["reader", "submitter", "reviewer", "operator"]]
        fixture = private_fixture(tmp_path / "policy.json")
        with edge(fixture, scopes=FULL_SCOPES, role_clients=clients,
                  data_classification="PERSONAL") as (http, _server, _roles):
            auth = {user: fixture.token(sub=user, scope=" ".join(FULL_SCOPES))
                    for user in ["alice", "bob"]}
            used: set[str] = set()

            def call(user: str, name: str, args: dict[str, Any], *, denied: bool = False) -> dict:
                response = rpc(http, "tools/call", token=auth[user],
                               params={"name": name, "arguments": args})
                assert response.status_code == 200, response.text
                result = response.json()["result"]
                if denied:
                    assert result.get("isError"), result
                    return result
                assert not result.get("isError"), result
                used.add(name)
                return dict(result["structuredContent"])

            def capture(user: str) -> str:
                return str(call(user, "milai_evidence_capture", {
                    "operation_id": "same-capture", "source_type": "AGENT_TURN",
                    "source_ref": "full-private/source", "subject_id": user,
                    "observed_at": datetime.now(UTC).isoformat(), "content": f"{user} port 6432",
                    "confirmation": "CAPTURE",
                })["evidence_id"])

            def proposal(user: str, evidence: str, op: str) -> dict:
                return {
                    "operation_id": op, "confirmation": "SUBMIT",
                    "proposal": {"operation": "CREATE", "supporting_evidence_refs": [evidence],
                                 "proposed_patch": {"subject_id": user, "predicate": "runtime.port",
                                                    "claim_type": "FACT", "payload": {"port": 6432},
                                                    "confidence": 0.99}},
                }

            evidence = {user: capture(user) for user in auth}
            assert evidence["alice"] != evidence["bob"]
            for user in auth:
                assert call(user, "milai_working_state_get", {})["status"] == "ABSENT"
                call(user, "milai_working_state_update", {
                    "operation_id": "same-state", "expected_version": 0, "payload": {"user": user},
                })
            created = call("alice", "milai_proposal_create",
                           proposal("alice", evidence["alice"], "alice-proposal"))
            pid = created["proposal_id"]
            # More foreign records than the old global fetch limit must not hide Alice's item.
            for index in range(101):
                call("bob", "milai_proposal_create",
                     proposal("bob", evidence["bob"], f"bob-proposal-{index}"))
            listed = call("alice", "milai_proposals_list", {"limit": 1})["proposals"]
            assert [p["proposal_id"] for p in listed] == [pid]
            assert call("alice", "milai_proposal_get", {"proposal_id": pid})["proposal_id"] == pid
            call("bob", "milai_proposal_get", {"proposal_id": pid}, denied=True)
            review = {"proposal_id": pid, "operation_id": "same-review", "decision": "APPROVE",
                      "confirmation": "APPROVE", "policy_version": "full-private-v1",
                      "reason_code": "SYNTHETIC_VERIFIED"}
            call("bob", "milai_memory_review", review, denied=True)
            call("alice", "milai_memory_review", {**review, "confirmation": "REJECT"}, denied=True)
            approved = call("alice", "milai_memory_review", review)
            replay = call("alice", "milai_memory_review", review)
            assert replay["claim_version_id"] == approved["claim_version_id"]
            claim = call("alice", "milai_memory_get", {"claim_id": approved["claim_id"]})
            assert claim["items"][0]["payload"]["port"] == 6432
            foreign = call("bob", "milai_memory_get", {"claim_id": approved["claim_id"]})
            assert not foreign.get("items")
            call("alice", "milai_memory_resolve", {"query": "runtime.port"})
            call("bob", "milai_proposal_create",
                 proposal("bob", evidence["alice"], "foreign-support"), denied=True)
            revoke = {"evidence_id": evidence["alice"], "operation_id": "same-revoke",
                      "reason_code": "USER_REQUEST", "confirmation": "REVOKE"}
            call("bob", "milai_evidence_revoke", revoke, denied=True)
            call("bob", "milai_deletion_status_get",
                 {"evidence_id": evidence["alice"]}, denied=True)
            call("alice", "milai_evidence_revoke", revoke)
            call("alice", "milai_deletion_status_get", {"evidence_id": evidence["alice"]})
            cleanup = {"operation_id": "same-cleanup", "reason_code": "USER_REQUEST",
                       "confirmation": "CLEANUP_NAMESPACE"}
            call("alice", "milai_namespace_cleanup_submit",
                 {**cleanup, "project_id": "forged-peer"}, denied=True)
            job = call("alice", "milai_namespace_cleanup_submit", cleanup)
            call("bob", "milai_namespace_cleanup_status",
                 {"cleanup_job_id": job["cleanup_job_id"]}, denied=True)
            call("alice", "milai_namespace_cleanup_status",
                 {"cleanup_job_id": job["cleanup_job_id"]})
            assert call("bob", "milai_working_state_get", {})["payload"] == {"user": "bob"}
            bob_proposals = call("bob", "milai_proposals_list", {"limit": 1})["proposals"]
            assert len(bob_proposals) == 1
            bob_review = call("bob", "milai_memory_review", {
                **review, "proposal_id": bob_proposals[0]["proposal_id"],
            })
            bob_claim = call("bob", "milai_memory_get", {"claim_id": bob_review["claim_id"]})
            assert bob_claim["items"][0]["payload"]["port"] == 6432
            assert used == set(TOOL_SCOPES)
    finally:
        for client in clients:
            client.close()
        _stop_process(api)
        if urls is not None:
            _drop_database(owner, database)
