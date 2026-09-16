from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import httpx
import pytest
from milai_client import AsyncMilaiClient, HttpxAsyncTransport

from milai_mcp.auth_policy import (
    PILOT_SCOPES,
    AuthDependencyUnavailable,
    private_project_for,
)
from test_aigcit_auth import ISSUER, Fixture
from test_aigcit_http import edge, rpc
from test_working_state_async import CAPABILITIES, TOKEN


@pytest.mark.parametrize("hot_status", [200, 503])
def test_authenticated_private_async_state_peer_completes_while_hot_user_waits(
    tmp_path: Path, hot_status: int,
) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    fixture.doc.update(mode="authenticated_private", owners=[])
    fixture.write()
    projects = {subject: private_project_for(ISSUER, subject, "project-one")
                for subject in ("hot-user", "ordinary-user")}
    entered, release = Event(), Event()
    requests = []

    def factory() -> AsyncMilaiClient:
        async def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/capabilities":
                return httpx.Response(200, json=CAPABILITIES)
            body = json.loads(request.content)
            requests.append(body)
            if body["project_id"] == projects["hot-user"]:
                entered.set()
                assert await asyncio.to_thread(release.wait, 5)
                if hot_status == 503:
                    return httpx.Response(503, json={"error": {
                        "code": "DATABASE_CAPACITY_EXCEEDED", "message": "synthetic-capacity",
                        "retryable": True}})
            return httpx.Response(200, json={
                "status": "ACTIVE", "version": 1,
                "payload": {"first": body["project_id"], "last": body["project_id"]}})

        return AsyncMilaiClient(token=TOKEN, max_retries=0, transport=HttpxAsyncTransport(
            "http://127.0.0.1", 5, transport=httpx.MockTransport(handle)))

    with edge(
        fixture, scopes=PILOT_SCOPES, working_state_client_factory=factory,
    ) as (http, _, roles):
        tokens = {subject: fixture.token(sub=subject, scope=" ".join(PILOT_SCOPES),
                                        tenant="forged-tenant", project=projects["hot-user"])
                  for subject in projects}

        def read(subject):
            response = rpc(http, "tools/call", token=tokens[subject], params={
                "name": "milai_working_state_get", "arguments": {"scope": "TASK"}})
            assert response.status_code == 200
            return response.json()["result"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            hot = pool.submit(read, "hot-user")
            try:
                assert entered.wait(3)
                ordinary = pool.submit(read, "ordinary-user").result(timeout=3)
                assert not hot.done()
                assert not ordinary.get("isError")
                assert ordinary["structuredContent"]["payload"] == {
                    "first": projects["ordinary-user"], "last": projects["ordinary-user"]}
            finally:
                release.set()
            result = hot.result(timeout=3)
        assert bool(result.get("isError")) is (hot_status == 503)
        if hot_status == 200:
            assert result["structuredContent"]["payload"]["first"] == projects["hot-user"]
        else:
            assert "synthetic-capacity" in json.dumps(result)
            assert all(project not in json.dumps(result) for project in projects.values())
        # A failed other-user operation cannot change this request's trusted namespace.
        assert read("ordinary-user")["structuredContent"]["payload"]["last"] == (
            projects["ordinary-user"])
        assert len(requests) == 3  # No hidden retry of the hot request.
        assert len({body["principal_binding_digest"] for body in requests}) == 2
        assert sum(body["project_id"] == projects["ordinary-user"] for body in requests) == 2
        assert not any(call[0] == "working_state_get" for role in roles for call in role.calls)


def test_private_users_bind_every_ordinary_path_and_concurrent_state(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    fixture.doc.update(mode="authenticated_private", owners=[])
    fixture.write()
    with edge(fixture, scopes=PILOT_SCOPES) as (http, _server, roles):
        projects = {}
        operations = {}
        for subject in ["alice", "bob"]:
            project = private_project_for(ISSUER, subject, "project-one")
            projects[subject] = project
            token = fixture.token(sub=subject, scope=" ".join(PILOT_SCOPES),
                                  project="project-one", tenant="forged", role="operator")

            def call(name: str, arguments: dict, token: str = token) -> None:
                result = rpc(http, "tools/call", token=token,
                             params={"name": name, "arguments": arguments})
                assert result.status_code == 200 and not result.json()["result"].get("isError")

            call("milai_memory_resolve", {"query": subject})
            assert roles[0].calls[-1][1][1]["requested_scope"] == {"project_ids": [project]}
            call("milai_memory_get", {"claim_id": "claim-1"})
            assert roles[0].calls[-1][1]["requested_scope"] == {"project_ids": [project]}
            call("milai_evidence_capture", {
                "operation_id": "same-op", "source_type": "AGENT_TURN", "source_ref": "same-source",
                "subject_id": "same-claimed-subject", "observed_at": "2026-09-07T00:00:00Z",
                "content": subject, "confirmation": "CAPTURE",
            })
            payload, operation = roles[1].calls[-1][1]
            assert payload["permission_snapshot"] == {"project_ids": [project], "readable": True}
            operations[subject] = operation
            for scope in ["SESSION", "TASK", "PROJECT"]:
                call("milai_working_state_get", {"scope": scope})
                assert roles[1].calls[-1][1]["project_id"] == project
                call("milai_working_state_update", {"scope": scope, "expected_version": 0,
                     "operation_id": "same-state", "payload": {"value": subject}})
                assert roles[1].calls[-1][1][0]["project_id"] == project
        assert projects["alice"] != projects["bob"] != "project-one"
        assert operations["alice"] != operations["bob"]

        original_get = roles[1].get_working_state

        def echo_binding(binding: dict) -> dict:
            result = original_get(binding)
            result["payload"] = {"project": binding["project_id"]}
            return result

        roles[1].get_working_state = echo_binding

        def read(index: int) -> int:
            subject = "alice" if index % 2 else "bob"
            response = rpc(http, "tools/call", token=fixture.token(sub=subject),
                       params={"name": "milai_working_state_get", "arguments": {"scope": "TASK"}}
                       )
            assert response.json()["result"]["structuredContent"]["payload"] == {
                "project": projects[subject],
            }
            return response.status_code

        start = len(roles[1].calls)
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(read, range(24))) == [200] * 24
        bindings = [call[1] for call in roles[1].calls[start:]]
        assert sum(b["project_id"] == projects["alice"] for b in bindings) == 12
        assert sum(b["project_id"] == projects["bob"] for b in bindings) == 12
        fixture.doc["disabled_subjects"] = ["alice"]
        fixture.write()
        assert rpc(http, "tools/list", token=fixture.token(sub="alice")).status_code == 403
        assert rpc(http, "tools/list", token=fixture.token(sub="bob")).status_code == 200


def test_private_identity_stable_across_clients_and_scope_changes(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    fixture.doc.update(mode="authenticated_private", owners=[])
    fixture.write()
    policy = fixture.policy()
    alice = policy.admit("alice", frozenset({"milai.state.read"}))
    again = policy.admit("alice", PILOT_SCOPES)
    bob = policy.admit("bob", PILOT_SCOPES)
    assert alice.principal_id == again.principal_id != bob.principal_id
    assert alice.project_id == again.project_id != bob.project_id


@pytest.mark.parametrize("change", [
    {"mode": "explicit_owners"}, {"disabled_subjects": [""]},
    {"disabled_subjects": ["alice", "alice"]},
])
def test_private_policy_changes_fail_closed(tmp_path: Path, change: dict) -> None:
    fixture = Fixture(tmp_path / "bindings.json")
    fixture.doc.update(mode="authenticated_private", owners=[])
    fixture.write()
    policy = fixture.policy()
    fixture.doc.update(change)
    fixture.write()
    with pytest.raises(AuthDependencyUnavailable):
        policy.admit("alice", PILOT_SCOPES)
