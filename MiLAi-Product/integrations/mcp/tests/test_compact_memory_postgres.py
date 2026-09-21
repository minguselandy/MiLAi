"""Compact U05-U12 over owned PG, real Runtime and signed local HTTP; zero models."""

import json
import os
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import pytest
from milai_client import AsyncMilaiClient, MilaiClient

from milai_mcp.auth_policy import ALL_SCOPES
from ordinary_memory_fault_proxy import FaultProxy
from support.http import edge, rpc
from support.postgres import (
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
from support.private_catalog import private_fixture


@pytest.mark.skipif(os.environ.get("MILAI_MCP_COMPACT_E2E") != "1", reason="requires owned PG")
def test_compact_persistence_cold_discovery_isolation_and_recovery(tmp_path):
    owner = _required_environment("MILAI_MIGRATION_DATABASE_URL")
    database = "milai_mcpbase_" + secrets.token_hex(10)
    urls, api = None, None
    clients = []
    stack = ExitStack()
    observations = []
    log_path = tmp_path / "runtime.jsonl"
    log = stack.enter_context(log_path.open("ab"))

    def native(http, token, payload):
        result = subprocess.run(  # noqa: S603 -- fixed test-only protocol client
            [sys.executable, str(Path(__file__).with_name("compact_memory_client.py"))],
            input=json.dumps({"url": str(http.base_url).rstrip("/") + "/mcp",
                              "host": http.headers["Host"], "token": token, **payload}),
            text=True, capture_output=True, timeout=45,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout)

    try:
        urls = _create_and_migrate_database(owner, database)
        tokens = {role: secrets.token_urlsafe(48) for role in (
            "legacy", "causal", "reader", "submitter", "reviewer", "operator",
        )}
        port = _free_port()
        environment = _runtime_environment(
            urls, tokens, tenant_id=secrets.token_hex(16), actor_id=secrets.token_hex(16),
            blob_root=tmp_path / "blobs", port=port,
        )
        environment.update(MILAI_REQUEST_TIMING_ENABLED="true", MILAI_LOG_LEVEL="INFO")

        def start():
            process = _start_process(
                _RUNTIME_ROOT / ".venv/bin/milai-api", arguments=[], cwd=_RUNTIME_ROOT,
                environment=environment, output_fd=log.fileno(),
            )
            _wait_ready(f"http://127.0.0.1:{port}/health/ready", process)
            return process

        api = start()
        base = f"http://127.0.0.1:{port}"
        proxy = stack.enter_context(FaultProxy(base))
        clients = [MilaiClient(base_url=base, token=tokens[role], max_retries=0)
                   for role in ("reader", "submitter", "reviewer", "operator")]
        fixture = private_fixture(tmp_path / "binding.json")
        users = {user: fixture.token(sub=user, scope=" ".join(ALL_SCOPES))
                 for user in ("alice", "bob")}

        def listener(catalog):
            return edge(
                fixture, scopes=ALL_SCOPES, role_clients=clients, catalog=catalog, network=True,
                working_state_client_factory=lambda: AsyncMilaiClient(
                    base_url=proxy.url, token=tokens["submitter"], max_retries=2,
                ),
            )

        def call(http, tool, args, *, user="alice", error=False):
            started = time.perf_counter()
            response = rpc(http, "tools/call", token=users[user],
                           params={"name": tool, "arguments": args})
            body = response.json()["result"]
            observations.append({"tool": tool, "elapsed_ms": (time.perf_counter()-started)*1000,
                                 "expected_error": error, "error": bool(body.get("isError")),
                                 "response_utf8_bytes": len(response.content)})
            assert response.status_code == 200 and bool(body.get("isError")) == error, body
            if error:
                text = body["content"][0]["text"]
                return json.loads(text[text.index("{"):])
            return body["structuredContent"]

        def read(http, kind, identifier, **kwargs):
            return call(http, "milai_memory_read", {"target": {
                "kind": kind, "id": identifier, **kwargs,
            }})

        def status(http, operation):
            return call(http, "milai_memory_status", {
                "target": {"kind": "NOTE_WRITE", "operation_id": operation},
            })

        with listener("compact-memory-v1") as (http, _, _roles), \
                listener("ordinary-memory-v1") as (advanced, _, _):
            save = {"content": " \r\nSynthetic compact record 🧠\t ",
                    "operation_id": "compact-default"}
            note = call(http, "milai_memory_save", save)
            assert note["version"] == 1 and note["durable"]
            immediate = call(http, note["read_tool"], note["read_arguments"])
            assert immediate["content"] == save["content"]
            replay = call(advanced, "milai_note_add", save)
            assert replay["memory_id"] == note["memory_id"] and replay["replayed"]
            conflict = call(http, "milai_memory_save", {**save, "content": "different"}, error=True)
            assert conflict["code"] == "OPERATION_CONFLICT" and not conflict["retryable"]
            call(http, "milai_memory_read", note["read_arguments"], user="bob", error=True)
            assert call(http, "milai_memory_search", {"query": "Synthetic compact"},
                        user="bob")["sources"]["notes"]["result"]["items"] == []

            def update(index):
                return rpc(http, "tools/call", token=users["alice"], params={
                    "name": "milai_memory_save", "arguments": {
                        "content": f"winner {index}", "operation_id": f"cas-{index}",
                        "options": {"action": "UPDATE_NOTE", "memory_id": note["memory_id"],
                                    "expected_version": 1},
                    },
                }).json()["result"]

            with ThreadPoolExecutor(max_workers=2) as pool:
                race = list(pool.map(update, [0, 1]))
            assert sum(not r.get("isError") for r in race) == 1
            failed = next(r for r in race if r.get("isError"))["content"][0]["text"]
            failure = json.loads(failed[failed.index("{"):])
            assert not failure["retryable"] and failure["next_tool"] == "milai_memory_read"
            assert read(http, "NOTE", note["memory_id"])["version"] == 2
            assert status(http, save["operation_id"])["version"] == 1

            # Unknown HTTP outcome: no adapter/SDK write retry; exact cross-catalog replay.
            uncertain = {}
            for boundary in ("before", "after"):
                op = "compact-cut-" + boundary
                args = {"content": "wire cut " + boundary, "operation_id": op}
                proxy.faults[op] = boundary
                failure = call(http, "milai_memory_save", args, error=True)
                assert failure["code"] == "NOTE_OUTCOME_UNKNOWN" and not failure["retryable"]
                assert failure["next_tool"] == "milai_memory_status"
                assert proxy.forwarded.count(op) == (boundary == "after")
                if boundary == "before":
                    call(http, "milai_memory_status", failure["next_arguments"], error=True)
                else:
                    receipt = call(http, "milai_memory_status", failure["next_arguments"])
                    assert receipt["commit_status"] == "COMMITTED"
                replay = call(advanced, "milai_note_add", args)
                assert replay["version"] == 1 and replay["replayed"] == (boundary == "after")
                uncertain[op] = replay["memory_id"]

            # Filter/identity-bound cursors for both inventories.
            page = call(http, "milai_memory_list", {"limit": 1})
            assert page["next_cursor"]
            call(http, "milai_memory_list", {"limit": 1, "cursor": page["next_cursor"]},
                 user="bob", error=True)
            call(http, "milai_memory_list", {"cursor": page["next_cursor"],
                 "selection": {"kind": "NOTE", "query": "different"}}, error=True)
            assert call(http, "milai_memory_list", {
                "limit": 1, "cursor": page["next_cursor"],
            })["items"][0]["memory_id"] != page["items"][0]["memory_id"]
            capture = {"content": "Synthetic source observation", "operation_id": "capture",
                       "options": {"action": "CAPTURE_EVIDENCE", "source_type": "AGENT_TURN",
                                   "source_ref": "synthetic://compact/one", "subject_id": "topic",
                                   "observed_at": datetime.now(UTC).isoformat(),
                                   "confirmation": "CAPTURE"}}
            evidence = call(http, "milai_memory_save", capture)
            evidence_ref = evidence["reference"]
            assert call(http, evidence_ref["read_tool"], evidence_ref["read_arguments"])[
                "content"] == capture["content"]
            replay = call(advanced, "milai_evidence_capture", {
                "content": capture["content"], "operation_id": capture["operation_id"],
                **{k: v for k, v in capture["options"].items() if k != "action"},
            })
            assert replay["evidence_id"] == evidence["evidence_id"]
            call(http, "milai_memory_save", {
                **capture, "operation_id": "capture-two", "options": {
                    **capture["options"], "source_ref": "synthetic://compact/two",
                },
            })
            selection = {"kind": "EVIDENCE", "subject_id": "topic"}
            ep = call(http, "milai_memory_list", {"selection": selection, "limit": 1})
            assert ep["next_cursor"]
            for user, filters in [("bob", selection), ("alice", {**selection, "subject_id": "x"})]:
                call(http, "milai_memory_list", {"selection": filters, "cursor": ep["next_cursor"]},
                     user=user, error=True)
            sources = [{"kind": "EVIDENCE", "evidence_id": evidence["evidence_id"]}] + [
                {"kind": "FILE", "locator": f"synthetic-{i}", "revision": "r1",
                 "content_digest": None} for i in range(10)
            ]
            linked_args = {"content": "dependent body", "operation_id": "linked", "options": {
                "action": "ADD_NOTE", "source_refs": sources,
            }}
            linked = call(http, "milai_memory_save", linked_args)
            first = read(http, "NOTE", linked["memory_id"])
            tail = read(http, "NOTE", linked["memory_id"], version=first["version"],
                        source_offset=first["next_source_offset"])
            assert first["source_refs"] + tail["source_refs"] == sources
            revoked = call(http, "milai_memory_delete", {"operation_id": "revoke", "target": {
                "kind": "EVIDENCE", "id": evidence["evidence_id"],
                "reason_code": "USER_REQUEST", "confirmation": "REVOKE",
            }})
            assert read(http, "EVIDENCE", evidence["evidence_id"])["status"] == "UNREADABLE"
            deletion_status = call(http, "milai_memory_status", {
                "target": {"kind": "EVIDENCE_DELETION", "id": evidence["evidence_id"]},
            })
            assert deletion_status["evidence_id"] == evidence["evidence_id"]
            assert deletion_status["deletion_request_id"] == revoked["deletion_request_id"]
            assert deletion_status["logical_revocation_status"] == "APPLIED"
            assert deletion_status["canonical_block_status"] == "APPLIED"
            assert deletion_status["derived_purge_status"] == "PENDING"
            assert deletion_status["primary_bytes_status"] == revoked["primary_bytes_status"]
            assert deletion_status["backup_expiry_status"] == revoked["backup_expiry_status"]
            assert deletion_status["primary_bytes_erased_at"] is None
            assert deletion_status["backup_expiry_completed_at"] is None
            assert "asynchronous" in revoked["suggested_next_step"]["message"]
            for version in (None, 1):
                hidden = read(http, "NOTE", linked["memory_id"], version=version)
                assert hidden["status"] == "SOURCE_UNAVAILABLE" and hidden["content"] is None
            assert not status(http, "linked")["direct_read_available"]
            assert call(http, "milai_memory_save", linked_args)["status"] == "SOURCE_UNAVAILABLE"
            assert call(http, "milai_memory_search", {"query": "dependent body"})[
                "sources"]["notes"]["result"]["items"] == []
            deleted = call(http, "milai_memory_delete", {"operation_id": "delete", "target": {
                "kind": "NOTE", "id": note["memory_id"], "expected_version": 2,
                "confirmation": "DELETE",
            }})
            assert not deleted["deletion"]["physical_deletion_supported"]
            assert read(http, "NOTE", note["memory_id"], version=1)["content"] is None
            assert not status(http, save["operation_id"])["direct_read_available"]

            # Concurrent identities and independent objects share a listener, not a binding.
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs = [pool.submit(call, http, "milai_memory_save", {
                    "content": user + " parallel object", "operation_id": "parallel",
                }, user=user) for user in ("alice", "bob")]
                jobs += [pool.submit(read, http, "NOTE", note["memory_id"]) for _ in range(2)]
                concurrent = [j.result(timeout=15) for j in jobs]
            assert concurrent[0]["memory_id"] != concurrent[1]["memory_id"]
            assert all(r["status"] == "DELETED" for r in concurrent[2:])
            for scope in ("SESSION", "TASK", "PROJECT"):
                call(http, "milai_working_state_update", {"scope": scope,
                     "operation_id": "checkpoint-" + scope, "expected_version": 0,
                     "payload": {"text": "resume only after verifying " + scope}})
                assert call(http, "milai_working_state_get", {"scope": scope},
                            user="bob")["status"] == "ABSENT"
            body = "Observatory continuation: use the red filter; do not enable tracking.\n" * 160
            saved = native(http, users["alice"], {"save": {
                "content": body, "operation_id": "cold-native",
            }})
            assert saved["saved"]["durable"]

        old_pid = api.pid
        _stop_process(api)
        api = start()
        assert api.pid != old_pid
        with listener("compact-memory-v1") as (http, _, _):
            # No old ID, cursor, answer or history enters the fresh B process.
            recovered = native(http, fixture.token(sub="alice", scope=" ".join(ALL_SCOPES)), {
                "query": "What constraints apply when continuing the Observatory task?",
                "note_query": "Observatory",
            })
            assert recovered["pid"] != saved["pid"]
            assert len(recovered["reads"]) == 1 and recovered["reads"][0]["content"] == body
            assert len(recovered["reads"][0]["pages"]) > 1
            assert recovered["reads"][0]["pages"][0]["memory_id"] == saved["saved"]["memory_id"]
            foreign = native(http, fixture.token(sub="bob", scope=" ".join(ALL_SCOPES)), {
                "query": "Observatory",
            })
            assert foreign["reads"] == [] and not foreign["discovery"]["absence_confirmed"]
            for op, identifier in {**uncertain, "cold-native": saved["saved"]["memory_id"]}.items():
                receipt = status(http, op)
                assert receipt["memory_id"] == identifier
                assert receipt["commit_status"] == "COMMITTED"
            for scope in ("SESSION", "TASK", "PROJECT"):
                checkpoint = call(http, "milai_working_state_get", {"scope": scope})
                assert checkpoint["payload"]["text"] == "resume only after verifying " + scope
                assert checkpoint["mcp_usage_contract"]["resume"]["arguments"] == {"scope": scope}
            # Restart never resurrects logically deleted or source-revoked historical bodies.
            assert read(http, "NOTE", note["memory_id"], version=1)["content"] is None
            assert read(http, "NOTE", linked["memory_id"], version=1)["content"] is None
            assert read(http, "EVIDENCE", evidence["evidence_id"])["status"] == "UNREADABLE"
        timings = [json.loads(line) for line in log_path.read_text().splitlines()
                   if line.startswith("{")]
        timing_events = [t for t in timings if t.get("event") == "runtime_request_timing"]
        assert timing_events
        report = {"scope": "synthetic compact protocol engineering; no model or public writes",
                  "database": database, "runtime_pids": [old_pid, api.pid],
                  "client_pids": [saved["pid"], recovered["pid"], foreign["pid"]],
                  "minimal_save_required_parameters": 2, "minimal_save_product_calls": 1,
                  "verification_reads_are_not_product_cost": True,
                  "model_requests": 0, "requests": observations,
                  "runtime_request_timings": timing_events,
                  "checkpoint_scope_binding": "same trusted binding; not all-session history"}
        output = Path(os.environ.get("MILAI_COMPACT_RESULT_PATH", tmp_path / "compact-report.json"))
        output.write_text(json.dumps(report, indent=2) + "\n")
    finally:
        stack.close()
        for client in clients:
            client.close()
        _stop_process(api)
        if urls is not None:
            _drop_database(owner, database)
