from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from milai_mcp.oauth_provider import OAuthStore
from milai_mcp.remote_registration import RemoteUserRegistry

_INBOUND_TOKEN = secrets.token_urlsafe(32)
_ROLE_TOKENS = {
    "reader": "reader-runtime-token-with-at-least-32-characters",
    "submitter": "submitter-runtime-token-with-at-least-32-characters",
    "reviewer": "reviewer-runtime-token-with-at-least-32-characters",
    "operator": "operator-runtime-token-with-at-least-32-characters",
}
_ROLE_CAPABILITIES = {
    "reader": ["memory:read"],
    "submitter": [
        "memory:read",
        "evidence:capture",
        "proposal:create",
        "working-state:read",
        "working-state:write",
    ],
    "reviewer": ["memory:read", "proposal:review"],
    "operator": ["memory:read", "evidence:revoke"],
}
_CODEX_FULL_OAUTH_SCOPES = " ".join(
    [
        "memory:read",
        "evidence:capture",
        "proposal:create",
        "proposal:review",
        "evidence:revoke",
        "operations:admin",
        "working-state:read",
        "working-state:write",
    ]
)


def _isolated_server_environment() -> dict[str, str]:
    """Keep ambient MiLAi service configuration out of child-process tests."""

    return {
        key: value for key, value in os.environ.items() if not key.startswith("MILAI_")
    }


EVIDENCE_ID = "00000000-0000-4000-8000-000000000001"
CLAIM_ID = "00000000-0000-4000-8000-000000000002"
VERSION_ID = "00000000-0000-4000-8000-000000000003"
FOREIGN_EVIDENCE_ID = "00000000-0000-4000-8000-000000000004"
LOCAL_EVIDENCE_ID = "00000000-0000-4000-8000-000000000005"

class _FullRuntimeHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, Any]]] = []
    mutations: ClassVar[dict[tuple[str, str], tuple[str, dict[str, Any]]]] = {}
    revoked: ClassVar[bool] = False
    working_state: ClassVar[dict[str, Any] | None] = None

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _role(self) -> str | None:
        authorization = self.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ")
        return next(
            (role for role, token in _ROLE_TOKENS.items() if token == supplied),
            None,
        )

    def _reply(self, body: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length))
        assert isinstance(value, dict)
        return value

    def _record(self, payload: dict[str, Any]) -> None:
        type(self).requests.append(
            {
                "method": self.command,
                "path": self.path,
                "role": self._role(),
                "operation_id": self.headers.get("Idempotency-Key"),
                "payload": payload,
            }
        )

    def _mutation(
        self,
        role: str,
        payload: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        if self._role() != role:
            self._reply(
                {"error": {"code": "CAPABILITY_REQUIRED", "retryable": False}},
                403,
            )
            return
        operation_id = self.headers.get("Idempotency-Key", "")
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        key = (self.path, operation_id)
        prior = type(self).mutations.get(key)
        if prior is not None:
            if prior[0] != fingerprint:
                self._reply(
                    {"error": {"code": "IDEMPOTENCY_CONFLICT", "retryable": False}},
                    409,
                )
                return
            self._reply({**prior[1], "replayed": True})
            return
        type(self).mutations[key] = (fingerprint, response)
        self._reply(response, 201 if self.path in {"/v1/evidence", "/v1/proposals"} else 200)

    def do_GET(self) -> None:
        role = self._role()
        path = urlsplit(self.path).path
        self._record({})
        if path == "/v1/capabilities" and role is not None:
            self._reply(
                {
                    "api_version": "1",
                    "contract_version": "agent.v1",
                    "runtime_version": "0.1.0",
                    "profile": role,
                    "capabilities": _ROLE_CAPABILITIES[role],
                    "routes": ["L0", "L1"],
                    "consistency_modes": ["CANONICAL_REQUIRED"],
                    "agent_profiles": list(_ROLE_TOKENS),
                    "features": {},
                    "limits": {},
                    "data_mode": "SYNTHETIC_ONLY",
                    "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
                    "implementation_status": "0.1.x CANDIDATE",
                }
            )
            return
        if path == "/v1/proposals" and role == "reviewer":
            self._reply(
                {
                    "proposals": [
                        {
                            "proposal_id": "proposal-1",
                            "status": "PENDING_REVIEW",
                            "scope_predicate": {"project_ids": ["project-one"]},
                        }
                    ]
                }
            )
            return
        if path == "/v1/proposals/proposal-1" and role == "reviewer":
            self._reply(
                {
                    "proposal_id": "proposal-1",
                    "status": "PENDING_REVIEW",
                    "scope_predicate": {"project_ids": ["project-one"]},
                }
            )
            return
        if path == f"/v1/evidence/{EVIDENCE_ID}" and role == "reader":
            self._reply(
                {
                    "evidence_id": EVIDENCE_ID,
                    "permission_snapshot": {
                        "project_ids": ["project-one"],
                        "readable": not type(self).revoked,
                    },
                    "retention_state": (
                        "REVOKED" if type(self).revoked else "READABLE"
                    ),
                }
            )
            return
        if path == f"/v1/evidence/{EVIDENCE_ID}/deletion-status" and role == "operator":
            self._reply({"evidence_id": EVIDENCE_ID, "status": "PURGE_PENDING"})
            return
        if path == "/v1/namespace-cleanups/cleanup-1" and role == "operator":
            self._reply(
                {
                    "cleanup_job_id": "cleanup-1",
                    "project_id": "project-one",
                    "status": "PENDING",
                }
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        role = self._role()
        path = urlsplit(self.path).path
        payload = self._payload()
        self._record(payload)
        if path == "/v1/memory/resolve" and role == "reader":
            evidence = [] if type(self).revoked else [
                {
                    "window_id": "window-1",
                    "session_id": "session-1",
                    "evidence_ids": [EVIDENCE_ID],
                    "source_turn_refs": ["turn-1"],
                    "text": "The governed port is 6432.",
                }
            ]
            self._reply(
                {
                    "schema_version": "access-outcome-v0.1",
                    "status": "ABSTAINED" if type(self).revoked else "PARTIAL",
                    "availability": "AVAILABLE",
                    "items": [],
                    "open_issue_ids": [],
                    "evidence_refs": [] if type(self).revoked else [EVIDENCE_ID],
                    "canonical_position": {"canonical_outbox_sequence": 9},
                    "degraded_components": [],
                    "abstention_reason": (
                        "NO_ELIGIBLE_EVIDENCE" if type(self).revoked else "SEMANTIC_NOT_ASSERTED"
                    ),
                    "memory_context": {"windows": evidence},
                    "memory_intent": "REQUIRED",
                    "requirement": "SEARCH",
                    "consistency": payload.get("consistency_mode"),
                    "access_trace": {"schema_version": "access-trace-v0.1", "spans": {}},
                    "fallback_used": False,
                    "fallback_reason": None,
                }
            )
            return
        if path == "/v1/memory/get" and role == "reader":
            self._reply(
                {
                    "schema_version": "memory-state-view-v0.1",
                    "status": "HIT",
                    "items": [{"claim_id": CLAIM_ID, "payload": {"value": 6432}}],
                    "open_issue_ids": [],
                    "evidence_refs": [EVIDENCE_ID],
                    "consistency": payload.get("consistency_mode"),
                    "canonical_position": {"canonical_outbox_sequence": 10},
                    "availability": "AVAILABLE",
                    "abstention_reason": None,
                    "resolution": {
                        "addressable": True,
                        "reachable": True,
                        "correctly_resolved": True,
                    },
                    "access_trace": {"schema_version": "access-trace-v0.1", "spans": {}},
                }
            )
            return
        if path == "/v1/working-state/get" and role == "submitter":
            if type(self).working_state is None:
                self._reply(
                    {
                        "schema_version": "host-cognitive-state-v1",
                        "status": "ABSENT",
                        "state_id": None,
                        "version": 0,
                        "authority": "HOST_WORKING",
                        "payload": {},
                        "warnings": [],
                    }
                )
            else:
                self._reply(type(self).working_state)
            return
        if path == "/v1/working-state/update":
            result = {
                "schema_version": "host-cognitive-state-v1",
                "status": "ACTIVE",
                "state_id": "working-state-1",
                "state_version_id": "working-version-1",
                "version": 1,
                "authority": "HOST_WORKING",
                "payload": payload["payload"],
                "warnings": [],
                "replayed": False,
            }
            type(self).working_state = result
            self._mutation("submitter", payload, result)
            return
        if path == "/v1/evidence":
            self._mutation(
                "submitter",
                payload,
                {
                    "evidence_id": EVIDENCE_ID,
                    "blob_id": "blob-1",
                    "outbox_id": "outbox-1",
                    "replayed": False,
                },
            )
            return
        if path == "/v1/proposals":
            self._mutation(
                "submitter",
                payload,
                {"proposal_id": "proposal-1", "status": "PENDING_REVIEW", "replayed": False},
            )
            return
        if path == "/v1/proposals/proposal-1/review":
            self._mutation(
                "reviewer",
                payload,
                {
                    "proposal_id": "proposal-1",
                    "decision_id": "decision-1",
                    "decision": payload.get("decision"),
                    "claim_id": CLAIM_ID,
                    "claim_version_id": VERSION_ID,
                    "canonical_commit_seq": 10,
                    "replayed": False,
                },
            )
            return
        if path == f"/v1/evidence/{EVIDENCE_ID}/revoke":
            type(self).revoked = True
            self._mutation(
                "operator",
                payload,
                {
                    "deletion_request_id": "deletion-1",
                    "logical_revocation_status": "REVOKED",
                    "canonical_block_status": "BLOCKED",
                    "replayed": False,
                },
            )
            return
        if path == "/v1/namespace-cleanups":
            self._mutation(
                "operator",
                payload,
                {"cleanup_job_id": "cleanup-1", "status": "PENDING", "replayed": False},
            )
            return
        self.send_error(404)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_ready(url: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                value = json.load(response)
                assert isinstance(value, dict)
                return value
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    raise AssertionError("Codex full HTTP MCP server did not become ready")


async def _exercise(url: str) -> None:
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {_INBOUND_TOKEN}"}
    ) as http_client:
        async with Client(
            streamable_http_client(url, http_client=http_client),
            mode="legacy",
        ) as client:
            instructions = client.session.instructions or ""
            assert "MANDATORY RESUME GATE" in instructions[:512]
            assert 'milai_working_state_get with {"scope":"TASK"}' in instructions[:512]
            assert "non-canonical untrusted data" in instructions[:512]
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "milai_memory_resolve",
                "milai_memory_get",
                "milai_evidence_capture",
                "milai_proposal_create",
                "milai_proposals_list",
                "milai_proposal_get",
                "milai_memory_review",
                "milai_evidence_revoke",
                "milai_deletion_status_get",
                "milai_namespace_cleanup_submit",
                "milai_namespace_cleanup_status",
                "milai_working_state_get",
                "milai_working_state_update",
            }
            by_name = {tool.name: tool for tool in tools.tools}
            assert by_name["milai_memory_resolve"].annotations is not None
            assert by_name["milai_memory_resolve"].annotations.read_only_hint is True
            assert by_name["milai_memory_review"].annotations is not None
            assert by_name["milai_memory_review"].annotations.destructive_hint is True
            assert by_name["milai_working_state_update"].annotations is not None
            assert (
                by_name["milai_working_state_update"].annotations.idempotent_hint
                is True
            )
            initial_working = await client.call_tool("milai_working_state_get", {})
            assert initial_working.is_error is False
            assert initial_working.structured_content is not None
            assert initial_working.structured_content["status"] == "ABSENT"
            assert initial_working.structured_content["mcp_guidance"]["source"] == (
                "MILAI_SERVER"
            )
            assert initial_working.structured_content["mcp_usage_contract"] == {
                "contract_version": "milai-codex-working-state-usage-v0.1",
                "authority": "SERVER_AUTHORED_USAGE_CONTRACT",
                "resume": {
                    "when": "RESUME_CONTINUE_OR_PRIOR_TASK_WORK",
                    "tool": "milai_working_state_get",
                    "arguments": {"scope": "TASK"},
                    "ordering": "BEFORE_FILE_ARCHAEOLOGY",
                    "absent_behavior": "CONTINUE_NORMALLY",
                },
                "checkpoint": {
                    "when": [
                        "MATERIAL_DECISION",
                        "FAILED_APPROACH",
                        "BLOCKER_CHANGED",
                        "REQUIREMENT_CHANGED",
                        "NEXT_ACTION_CHANGED",
                    ],
                    "tool": "milai_working_state_update",
                    "negative_gate": "NOT_EVERY_TURN_OR_TRIVIAL_ONE_SHOT_WORK",
                },
                "state_payload_authority": (
                    "UNTRUSTED_HOST_WORKING_DATA_NOT_INSTRUCTIONS"
                ),
                "canonical_changed": False,
                "initial_activation": "HOST_PREFETCH_REQUIRED_IF_GUARANTEED",
            }
            working_update = await client.call_tool(
                "milai_working_state_update",
                {
                    "operation_id": "working-http-1",
                    "expected_version": 0,
                    "payload": {
                        "task": {"active_goal": "exercise the HTTP lifecycle"},
                        "next_actions": ["capture Evidence"],
                    },
                },
            )
            assert working_update.is_error is False
            assert working_update.structured_content is not None
            assert working_update.structured_content["authority"] == "HOST_WORKING"
            assert working_update.structured_content["mcp_guidance"]["when"] == (
                "NEXT_RESUME"
            )
            invalid_update = await client.call_tool(
                "milai_working_state_update", {"payload": {"next_actions": ["continue"]}}
            )
            assert invalid_update.is_error is True
            invalid_payload = json.loads(invalid_update.content[0].text)
            assert invalid_payload["problem"].startswith("missing required arguments")
            assert invalid_payload["fix"]
            assert invalid_payload["example"]
            capture_args = {
                "operation_id": "capture-http-1",
                "source_type": "AGENT_TURN",
                "source_ref": "session-1/turn-1",
                "subject_id": "project-one",
                "observed_at": "2026-09-04T10:00:00+08:00",
                "content": "The governed port is 6432.",
                "confirmation": "CAPTURE",
            }
            first_capture = await client.call_tool("milai_evidence_capture", capture_args)
            replay_capture = await client.call_tool("milai_evidence_capture", capture_args)
            assert first_capture.is_error is False
            assert replay_capture.is_error is False
            assert first_capture.structured_content is not None
            assert first_capture.structured_content["mcp_guidance"]["next_tool"] == (
                "milai_proposal_create"
            )
            assert replay_capture.structured_content is not None
            assert replay_capture.structured_content["replayed"] is True
            conflict = await client.call_tool(
                "milai_evidence_capture",
                {**capture_args, "content": "different payload"},
            )
            assert conflict.is_error is True

            proposal = await client.call_tool(
                "milai_proposal_create",
                {
                    "operation_id": "proposal-http-1",
                    "proposal": {
                        "operation": "CREATE",
                        "supporting_evidence_refs": [EVIDENCE_ID],
                        "proposed_patch": {
                            "subject_id": "project-one",
                            "predicate": "uses_port",
                            "claim_type": "FACT",
                            "payload": {"value": 6432},
                            "confidence": 0.99,
                        },
                    },
                    "confirmation": "SUBMIT",
                },
            )
            assert proposal.is_error is False
            assert (
                await client.call_tool(
                    "milai_proposal_get", {"proposal_id": "proposal-1"}
                )
            ).is_error is False
            assert (await client.call_tool("milai_proposals_list", {})).is_error is False
            review = await client.call_tool(
                "milai_memory_review",
                {
                    "proposal_id": "proposal-1",
                    "operation_id": "review-http-1",
                    "decision": "APPROVE",
                    "policy_version": "codex-full-v1",
                    "reason_code": "HOST_REVIEW_DECISION",
                    "confirmation": "APPROVE",
                },
            )
            assert review.is_error is False
            assert (
                await client.call_tool("milai_memory_get", {"claim_id": CLAIM_ID})
            ).is_error is False
            before_revoke = await client.call_tool(
                "milai_memory_resolve", {"query": "governed port"}
            )
            assert before_revoke.structured_content is not None
            assert before_revoke.structured_content.get("retrieval_status") == "HIT", (
                before_revoke.structured_content
            )
            revoke = await client.call_tool(
                "milai_evidence_revoke",
                {
                    "evidence_id": EVIDENCE_ID,
                    "operation_id": "revoke-http-1",
                    "reason_code": "USER_REQUEST",
                    "confirmation": "REVOKE",
                },
            )
            assert revoke.is_error is False
            after_revoke = await client.call_tool(
                "milai_memory_resolve", {"query": "governed port"}
            )
            assert after_revoke.structured_content is not None
            assert after_revoke.structured_content["retrieval_status"] == "MISS"
            assert after_revoke.structured_content["evidence"] == []
            assert (
                await client.call_tool(
                    "milai_deletion_status_get", {"evidence_id": EVIDENCE_ID}
                )
            ).is_error is False
            cleanup = await client.call_tool(
                "milai_namespace_cleanup_submit",
                {
                    "operation_id": "cleanup-http-1",
                    "reason_code": "USER_REQUEST",
                    "confirmation": "CLEANUP_NAMESPACE",
                },
            )
            assert cleanup.is_error is False
            assert (
                await client.call_tool(
                    "milai_namespace_cleanup_status", {"cleanup_job_id": "cleanup-1"}
                )
            ).is_error is False


async def _exercise_registered_identity(url: str, token: str) -> None:
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}
    ) as http_client:
        async with Client(
            streamable_http_client(url, http_client=http_client),
            mode="2026-07-28",
        ) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 13
            result = await client.call_tool(
                "milai_working_state_update",
                {
                    "operation_id": "registered-working-http-1",
                    "expected_version": 0,
                    "payload": {"active_goal": "verify registered identity"},
                },
            )
            assert result.is_error is False


async def _capture_as_registered_identity(
    url: str,
    token: str,
    *,
    content: str,
) -> None:
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}
    ) as http_client:
        async with Client(
            streamable_http_client(url, http_client=http_client),
            mode="2026-07-28",
        ) as client:
            result = await client.call_tool(
                "milai_evidence_capture",
                {
                    "operation_id": "same-public-operation-id",
                    "source_type": "AGENT_TURN",
                    "source_ref": "registered/session/turn",
                    "subject_id": "project-one",
                    "observed_at": "2026-09-04T10:00:00+08:00",
                    "content": content,
                    "confirmation": "CAPTURE",
                },
            )
            assert result.is_error is False


def _oauth_access_token(base_url: str, enrollment_code: str) -> str:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    redirect_uri = "http://127.0.0.1:34567/callback"
    with httpx2.Client(follow_redirects=False, timeout=10) as client:
        registration = client.post(
            base_url + "/register",
            json={
                "client_name": "Codex full OAuth smoke",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": _CODEX_FULL_OAUTH_SCOPES,
            },
        )
        assert registration.status_code == 201, registration.text
        client_id = registration.json()["client_id"]
        authorization = client.get(
            base_url + "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": _CODEX_FULL_OAUTH_SCOPES,
                "state": "codex-full-state",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": base_url + "/mcp",
            },
        )
        assert authorization.status_code == 302, authorization.text
        consent_location = authorization.headers["location"]
        request_id = parse_qs(urlsplit(consent_location).query)["request_id"][0]
        consent = client.post(
            base_url + "/oauth/consent",
            data={
                "request_id": request_id,
                "enrollment_code": enrollment_code,
                "decision": "APPROVE",
            },
        )
        assert consent.status_code == 302, consent.text
        callback = parse_qs(urlsplit(consent.headers["location"]).query)
        assert callback["state"] == ["codex-full-state"]
        exchange = client.post(
            base_url + "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": callback["code"][0],
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "resource": base_url + "/mcp",
            },
        )
        assert exchange.status_code == 200, exchange.text
        return str(exchange.json()["access_token"])


def test_codex_full_real_http_lifecycle_and_role_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FullRuntimeHandler.requests = []
    _FullRuntimeHandler.mutations = {}
    _FullRuntimeHandler.revoked = False
    _FullRuntimeHandler.working_state = None
    runtime = ThreadingHTTPServer(("127.0.0.1", 0), _FullRuntimeHandler)
    runtime_thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    runtime_thread.start()
    port = _free_port()
    executable = Path(sys.executable).with_name("milai-codex-full-mcp")
    # This setting would make the nominally static test start the OAuth provider
    # and touch an external edge database if it leaked into the child process.
    monkeypatch.setenv("MILAI_OAUTH_DB", "/")
    environment = _isolated_server_environment()
    environment.update(
        {
            "MILAI_BASE_URL": f"http://127.0.0.1:{runtime.server_port}",
            "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["project-one"]}',
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_CODEX_TOKEN": _INBOUND_TOKEN,
            "MILAI_CODEX_PRINCIPAL_ID": "codex-project-one",
            "MILAI_CODEX_TASK_REF": "task-http-one",
            "MILAI_AGENT_READER_TOKEN": _ROLE_TOKENS["reader"],
            "MILAI_AGENT_SUBMITTER_TOKEN": _ROLE_TOKENS["submitter"],
            "MILAI_AGENT_REVIEWER_TOKEN": _ROLE_TOKENS["reviewer"],
            "MILAI_AGENT_OPERATOR_TOKEN": _ROLE_TOKENS["operator"],
        }
    )
    process = subprocess.Popen(  # noqa: S603 - exact installed test executable
        [str(executable), "--host", "127.0.0.1", "--port", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    process_stderr = ""
    try:
        assert _wait_ready(f"http://127.0.0.1:{port}/readyz") == {
            "status": "ready",
            "service": "milai-mcp",
        }
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/mcp", timeout=2)
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("unauthenticated full-control MCP request was accepted")
        asyncio.run(_exercise(f"http://127.0.0.1:{port}/mcp"))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stderr is not None:
            process_stderr = process.stderr.read()
        runtime.shutdown()
        runtime.server_close()
        runtime_thread.join(timeout=5)

    mutations = [item for item in _FullRuntimeHandler.requests if item["operation_id"]]
    assert {item["role"] for item in mutations} == {"submitter", "reviewer", "operator"}
    capture_requests = [item for item in mutations if item["path"] == "/v1/evidence"]
    assert len(capture_requests) == 3
    assert all(
        item["payload"]["permission_snapshot"]
        == {"project_ids": ["project-one"], "readable": True}
        for item in capture_requests
    )
    cleanup_request = next(
        item for item in mutations if item["path"] == "/v1/namespace-cleanups"
    )
    assert cleanup_request["payload"]["project_id"] == "project-one"
    working_request = next(
        item for item in mutations if item["path"] == "/v1/working-state/update"
    )
    assert working_request["role"] == "submitter"
    assert working_request["payload"]["project_id"] == "project-one"
    assert working_request["payload"]["scope_type"] == "TASK"
    assert working_request["payload"]["scope_ref"] == "task-http-one"
    assert len(working_request["payload"]["principal_binding_digest"]) == 64
    assert "MILAI_CODEX_FULL_AUDIT" in process_stderr
    assert '"governance_mode": "SINGLE_HOST_FULL_CONTROL"' in process_stderr
    assert '"independent_host_review": false' in process_stderr
    assert "The governed port is 6432." not in process_stderr


def test_codex_full_json_only_user_auto_registers_on_first_http_session(
    tmp_path: Path,
) -> None:
    _FullRuntimeHandler.requests = []
    _FullRuntimeHandler.mutations = {}
    _FullRuntimeHandler.revoked = False
    _FullRuntimeHandler.working_state = None
    runtime = ThreadingHTTPServer(("127.0.0.1", 0), _FullRuntimeHandler)
    runtime_thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    runtime_thread.start()
    registry = RemoteUserRegistry(tmp_path / "codex-users.json")
    user_token = registry.issue("user-a")
    second_user_token = registry.issue("user-b")
    principal_id = registry.list_users()[0]["principal_id"]
    port = _free_port()
    executable = Path(sys.executable).with_name("milai-codex-full-mcp")
    environment = _isolated_server_environment()
    environment.update(
        {
            "MILAI_BASE_URL": f"http://127.0.0.1:{runtime.server_port}",
            "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["project-one"]}',
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_CODEX_TOKEN": _INBOUND_TOKEN,
            "MILAI_CODEX_PRINCIPAL_ID": "codex-project-one",
            "MILAI_CODEX_TASK_REF": "task-http-one",
            "MILAI_CODEX_USER_REGISTRY": str(registry.path),
            "MILAI_AGENT_READER_TOKEN": _ROLE_TOKENS["reader"],
            "MILAI_AGENT_SUBMITTER_TOKEN": _ROLE_TOKENS["submitter"],
            "MILAI_AGENT_REVIEWER_TOKEN": _ROLE_TOKENS["reviewer"],
            "MILAI_AGENT_OPERATOR_TOKEN": _ROLE_TOKENS["operator"],
        }
    )
    process = subprocess.Popen(  # noqa: S603 - exact installed test executable
        [str(executable), "--host", "127.0.0.1", "--port", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    process_stderr = ""
    try:
        assert _wait_ready(f"http://127.0.0.1:{port}/readyz")["status"] == "ready"
        asyncio.run(
            _exercise_registered_identity(
                f"http://127.0.0.1:{port}/mcp",
                user_token,
            )
        )
        asyncio.run(
            _capture_as_registered_identity(
                f"http://127.0.0.1:{port}/mcp",
                user_token,
                content="user-a observation",
            )
        )
        asyncio.run(
            _capture_as_registered_identity(
                f"http://127.0.0.1:{port}/mcp",
                second_user_token,
                content="user-b independent observation",
            )
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stderr is not None:
            process_stderr = process.stderr.read()
        runtime.shutdown()
        runtime.server_close()
        runtime_thread.join(timeout=5)

    working_request = next(
        item
        for item in _FullRuntimeHandler.requests
        if item["path"] == "/v1/working-state/update"
    )
    expected_binding_digest = hashlib.sha256(
        json.dumps(
            {
                "governance_mode": "SINGLE_HOST_FULL_CONTROL",
                "host_principal_id": principal_id,
                "scope_sha256": hashlib.sha256(
                    b'{"project_ids":["project-one"]}'
                ).hexdigest(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert working_request["payload"]["principal_binding_digest"] == (
        expected_binding_digest
    )
    assert registry.list_users()[0]["status"] == "ACTIVE"
    registered_capture_requests = [
        item
        for item in _FullRuntimeHandler.requests
        if item["path"] == "/v1/evidence"
    ]
    assert len(registered_capture_requests) == 2
    assert len(
        {item["operation_id"] for item in registered_capture_requests}
    ) == 2
    assert all(
        len(str(item["operation_id"])) == 64
        for item in registered_capture_requests
    )
    assert "USER_REGISTERED" in registry.audit_path.read_text(encoding="utf-8")
    assert principal_id in process_stderr


def test_codex_full_oauth_dcr_login_exposes_full_catalog(tmp_path: Path) -> None:
    _FullRuntimeHandler.requests = []
    _FullRuntimeHandler.mutations = {}
    _FullRuntimeHandler.revoked = False
    _FullRuntimeHandler.working_state = None
    runtime = ThreadingHTTPServer(("127.0.0.1", 0), _FullRuntimeHandler)
    runtime_thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    runtime_thread.start()
    oauth_store = OAuthStore(tmp_path / "oauth.sqlite3")
    enrollment_code = oauth_store.issue_enrollment("oauth-user-a")
    principal_id = oauth_store.list_users()[0]["principal_id"]
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    executable = Path(sys.executable).with_name("milai-codex-full-mcp")
    environment = _isolated_server_environment()
    environment.update(
        {
            "MILAI_BASE_URL": f"http://127.0.0.1:{runtime.server_port}",
            "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["project-one"]}',
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_CODEX_TOKEN": _INBOUND_TOKEN,
            "MILAI_CODEX_PRINCIPAL_ID": "codex-project-one",
            "MILAI_CODEX_TASK_REF": "task-http-one",
            "MILAI_MCP_HTTP_PUBLIC_BASE_URL": base_url,
            "MILAI_OAUTH_DB": str(oauth_store.path),
            "MILAI_AGENT_READER_TOKEN": _ROLE_TOKENS["reader"],
            "MILAI_AGENT_SUBMITTER_TOKEN": _ROLE_TOKENS["submitter"],
            "MILAI_AGENT_REVIEWER_TOKEN": _ROLE_TOKENS["reviewer"],
            "MILAI_AGENT_OPERATOR_TOKEN": _ROLE_TOKENS["operator"],
        }
    )
    process = subprocess.Popen(  # noqa: S603 - exact installed test executable
        [str(executable), "--host", "127.0.0.1", "--port", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    process_stderr = ""
    try:
        assert _wait_ready(base_url + "/readyz")["status"] == "ready"
        access_token = _oauth_access_token(base_url, enrollment_code)
        asyncio.run(_exercise_registered_identity(base_url + "/mcp", access_token))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stderr is not None:
            process_stderr = process.stderr.read()
        runtime.shutdown()
        runtime.server_close()
        runtime_thread.join(timeout=5)

    assert oauth_store.list_users()[0]["status"] == "ACTIVE"
    working_request = next(
        item
        for item in _FullRuntimeHandler.requests
        if item["path"] == "/v1/working-state/update"
    )
    expected_binding_digest = hashlib.sha256(
        json.dumps(
            {
                "governance_mode": "SINGLE_HOST_FULL_CONTROL",
                "host_principal_id": principal_id,
                "scope_sha256": hashlib.sha256(
                    b'{"project_ids":["project-one"]}'
                ).hexdigest(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert working_request["payload"]["principal_binding_digest"] == (
        expected_binding_digest
    )
    assert "OAUTH_USER_REGISTERED" in process_stderr
    assert principal_id in process_stderr
