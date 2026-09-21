"""One vertical slice: signed private MCP requests -> HTTP Runtime -> PostgreSQL."""

import json
import math
import os
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from milai_client import AsyncMilaiClient, MilaiClient

from milai_mcp.auth_policy import (
    ALL_SCOPES,
    FULL_SCOPES,
    ORDINARY_CATALOG_TOOL_SCOPES,
    TOOL_SCOPE_ALTERNATIVES,
)
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


@pytest.mark.skipif(os.environ.get("MILAI_MCP_BASELINE_E2E") != "1", reason="requires owned PG")
def test_ordinary_notes_through_private_mcp_and_runtime(tmp_path: Path) -> None:
    owner = _required_environment("MILAI_MIGRATION_DATABASE_URL")
    database = "milai_mcpbase_" + secrets.token_hex(10)
    urls = None
    api = None
    clients: list[MilaiClient] = []
    stack = ExitStack()
    observations: list[dict[str, Any]] = []
    runtime_log_path = tmp_path / "runtime-timing.jsonl"
    runtime_log = stack.enter_context(runtime_log_path.open("ab"))

    def native(http: Any, token: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        completed = subprocess.run(  # noqa: S603 -- fixed local protocol client, input via stdin
            [sys.executable, str(Path(__file__).with_name("ordinary_memory_client.py"))],
            input=json.dumps({"url": str(http.base_url).rstrip("/") + "/mcp",
                              "host": http.headers["Host"], "token": token, "actions": actions}),
            text=True, capture_output=True, timeout=45,
        )
        assert completed.returncode == 0, "fresh MCP client failed: " + completed.stderr[-1500:]
        return dict(json.loads(completed.stdout))

    def migrate(target: str, *, blocked: bool = False) -> None:
        assert urls is not None
        result = subprocess.run(  # noqa: S603 -- fixed local migration on owned test database
            [str(_RUNTIME_ROOT / ".venv/bin/alembic"), "-c", "alembic.ini",
             "upgrade" if target == "head" else "downgrade", target],
            cwd=_RUNTIME_ROOT, env={
                **{k: v for k, v in os.environ.items() if not k.startswith("MILAI_")},
                "MILAI_MIGRATION_DATABASE_URL": urls["owner"],
            }, text=True, capture_output=True, timeout=30,
        )
        if blocked:
            assert result.returncode != 0
            assert "HOST_NOTES_DOWNGRADE_REQUIRES_EMPTY_STORAGE" in result.stderr
        else:
            assert result.returncode == 0, "owned-database migration failed"

    try:
        urls = _create_and_migrate_database(owner, database)
        migrate("0055_working_state_ref_capacity")
        migrate("head")
        tokens = {name: secrets.token_urlsafe(48) for name in [
            "legacy", "causal", "reader", "submitter", "reviewer", "operator",
        ]}
        port = _free_port()
        environment = _runtime_environment(
            urls, tokens, tenant_id=secrets.token_hex(16), actor_id=secrets.token_hex(16),
            blob_root=tmp_path / "blobs", port=port,
        )
        environment.update(MILAI_REQUEST_TIMING_ENABLED="true", MILAI_LOG_LEVEL="INFO")
        api = _start_process(
            _RUNTIME_ROOT / ".venv/bin/milai-api", arguments=[],
            cwd=_RUNTIME_ROOT, environment=environment,
            output_fd=runtime_log.fileno(),
        )
        base = f"http://127.0.0.1:{port}"
        _wait_ready(base + "/health/ready", api)
        proxy = stack.enter_context(FaultProxy(base))
        clients = [MilaiClient(base_url=base, token=tokens[role], max_retries=0)
                   for role in ["reader", "submitter", "reviewer", "operator"]]
        fixture = private_fixture(tmp_path / "policy.json")
        with edge(
            fixture, scopes=ALL_SCOPES, role_clients=clients, catalog="ordinary-memory-v1",
            network=True,
            working_state_client_factory=lambda: AsyncMilaiClient(
                base_url=proxy.url, token=tokens["submitter"], max_retries=2,
            ),
        ) as (http, _server, _roles):
            tokens_by_user = {user: fixture.token(sub=user, scope=" ".join(ALL_SCOPES))
                              for user in ["alice", "bob"]}

            def call(user: str, tool: str, args: dict[str, Any], denied: bool = False) -> dict:
                started = time.perf_counter()
                response = rpc(http, "tools/call", token=tokens_by_user[user],
                               params={"name": tool, "arguments": args})
                observations.append({
                    "tool": tool, "started": started, "finished": time.perf_counter(),
                    "http_status": response.status_code, "expected_error": denied,
                    "mcp_error": bool(response.json().get("result", {}).get("isError")),
                })
                assert response.status_code == 200, response.text
                result = response.json()["result"]
                assert bool(result.get("isError")) == denied, result
                return result if denied else dict(result["structuredContent"])

            old_token = fixture.token(sub="alice", scope=" ".join(FULL_SCOPES))
            legacy = rpc(http, "tools/list", token=old_token).json()["result"]["tools"]
            assert not any(tool["name"].startswith("milai_note_") for tool in legacy)
            listed = rpc(http, "tools/list", token=tokens_by_user["alice"]).json()["result"]
            listed = listed["tools"]
            assert {tool["name"] for tool in listed} == set(ORDINARY_CATALOG_TOOL_SCOPES)
            catalog_path = os.environ.get("MILAI_V07_CATALOG_PATH")
            if catalog_path:
                Path(catalog_path).write_text(json.dumps({
                    "catalog": "ordinary-memory-v1", "tools": listed,
                    "scope_mapping": ORDINARY_CATALOG_TOOL_SCOPES,
                    "scope_alternatives": {
                        name: sorted(scopes) for name, scopes in TOOL_SCOPE_ALTERNATIVES.items()
                    },
                }, ensure_ascii=False, indent=2) + "\n")
            body = " \r\nHost note 🧠 with exact content\t "
            invalid = call("alice", "milai_note_add", {
                "content": body, "operation_id": "invalid-source",
                "source_refs": [{"kind": "FILE", "locator": "private-invalid-source"}],
            }, denied=True)
            assert "private-invalid-source" not in str(invalid) and body not in str(invalid)
            assert "INVALID_ARGUMENT" in str(invalid)
            oversized = call("alice", "milai_note_add", {
                "content": "🧠" * 20_000, "operation_id": "too-many-utf8-bytes",
            }, denied=True)
            error_text = oversized["content"][0]["text"]
            field_error = json.loads(error_text.removeprefix(
                "Error executing tool milai_note_add: ",
            ))
            assert field_error["code"] == "INVALID_REQUEST"
            assert field_error["fields"][0]["path"] == "content"
            assert "65536" in field_error["fields"][0]["expected"]
            assert "🧠" not in str(field_error)
            note = call("alice", "milai_note_add", {"content": body, "operation_id": "add-one"})
            assert note["version"] == 1
            read = call("alice", "milai_note_get", {"memory_id": note["memory_id"]})
            assert read["content"] == body
            for token in [old_token, fixture.token(sub="alice", scope="milai.note.read")]:
                for tool, args in [
                    ("milai_note_add", {"content": "must not save", "operation_id": "denied-add"}),
                    ("milai_note_update", {"memory_id": note["memory_id"], "expected_version": 1,
                                          "content": "must not edit",
                                          "operation_id": "denied-edit"}),
                    ("milai_note_delete", {"memory_id": note["memory_id"], "expected_version": 1,
                                          "confirmation": "DELETE",
                                          "operation_id": "denied-delete"}),
                ]:
                    started = time.perf_counter()
                    response = rpc(http, "tools/call", token=token,
                                   params={"name": tool, "arguments": args})
                    denied = response.json()
                    observations.append({
                        "tool": tool, "started": started, "finished": time.perf_counter(),
                        "http_status": response.status_code, "expected_error": True,
                        "mcp_error": bool(denied.get("error"))
                        or bool(denied.get("result", {}).get("isError")),
                    })
                    assert "error" in denied or denied["result"].get("isError")
            assert call("alice", "milai_note_get", {"memory_id": note["memory_id"]})["version"] == 1
            call("bob", "milai_note_get", {"memory_id": note["memory_id"]}, denied=True)
            assert call("bob", "milai_note_list", {})["items"] == []
            assert call("alice", "milai_note_search", {"query": "Host note"})["items"]
            discovered = call("alice", "milai_memory_search", {"query": "Host note"})
            assert discovered["retrieval_status"] == "HIT"
            assert discovered["absence_confirmed"] is False
            assert discovered["sources"]["notes"]["result"]["items"][0]["memory_id"] == (
                note["memory_id"]
            )
            private_search = call("bob", "milai_memory_search", {"query": "Host note"})
            assert private_search["sources"]["notes"]["result"]["items"] == []
            call("alice", "milai_note_update", {
                "memory_id": note["memory_id"], "expected_version": 1,
                "content": "revised", "operation_id": "update-one",
            })
            assert call("alice", "milai_note_operation_get", {
                "operation_id": "add-one",
            })["version"] == 1
            evidence = call("alice", "milai_evidence_capture", {
                "operation_id": "source-one", "source_type": "AGENT_TURN",
                "source_ref": "synthetic://ordinary-note", "subject_id": "example",
                "observed_at": datetime.now(UTC).isoformat(), "content": body,
                "confirmation": "CAPTURE",
            })
            assert call("alice", "milai_evidence_get", {
                "evidence_id": evidence["evidence_id"],
            })["content"] == body
            assert evidence["reference"]["read_tool"] == "milai_evidence_get"
            call("bob", "milai_evidence_get", {"evidence_id": evidence["evidence_id"]}, denied=True)
            second = call("alice", "milai_evidence_capture", {
                "operation_id": "source-two", "source_type": "AGENT_TURN",
                "source_ref": "synthetic://ordinary-note-two", "subject_id": "example",
                "observed_at": datetime.now(UTC).isoformat(), "content": "independent source",
                "confirmation": "CAPTURE",
            })
            page = call("alice", "milai_evidence_list", {"limit": 1, "subject_id": "example"})
            assert page["items"][0]["evidence_id"] == evidence["evidence_id"]
            assert "content" not in page["items"][0]
            assert page["next_cursor"] is not None
            call("bob", "milai_evidence_list", {
                "limit": 1, "subject_id": "example", "cursor": page["next_cursor"],
            }, denied=True)
            assert call("bob", "milai_evidence_list", {})["items"] == []
            call("alice", "milai_evidence_list", {
                "subject_id": "changed-filter", "cursor": page["next_cursor"],
            }, denied=True)
            sources = [{"kind": "EVIDENCE", "evidence_id": evidence["evidence_id"]}] + [
                {"kind": "FILE", "locator": f"file-{i}.md",
                 "revision": "r1", "content_digest": None}
                for i in range(10)
            ]
            dependent_args = {
                "content": "linked observation", "operation_id": "add-linked",
                "source_refs": sources,
            }
            dependent = call("alice", "milai_note_add", dependent_args)
            first = call("alice", "milai_note_get", {"memory_id": dependent["memory_id"]})
            remaining = call("alice", "milai_note_get", {
                **first["read_arguments"], "source_offset": first["next_source_offset"],
            })
            assert first["source_refs"] + remaining["source_refs"] == sources
            assert remaining["next_source_offset"] is None
            assert remaining["total_source_refs"] == 11
            assert "source_refs" not in call("alice", "milai_note_search", {
                "query": "linked observation",
            })["items"][0]
            call("alice", "milai_evidence_revoke", {
                "evidence_id": evidence["evidence_id"], "operation_id": "revoke-linked-source",
                "reason_code": "USER_REQUEST", "confirmation": "REVOKE",
            })
            assert call("alice", "milai_evidence_get", {
                "evidence_id": evidence["evidence_id"],
            })["status"] == "UNREADABLE"
            later = call("alice", "milai_evidence_list", {
                "limit": 1, "subject_id": "example", "cursor": page["next_cursor"],
            })
            assert later["items"][0]["evidence_id"] == second["evidence_id"]
            assert len(call("alice", "milai_evidence_list", {})["items"]) == 1
            for version in [None, 1]:
                hidden = call("alice", "milai_note_get", {
                    "memory_id": dependent["memory_id"], "version": version,
                })
                assert hidden["content"] is None and hidden["status"] == "SOURCE_UNAVAILABLE"
            replay = call("alice", "milai_note_add", dependent_args)
            assert replay["status"] == "SOURCE_UNAVAILABLE" and "content_digest" not in replay
            assert call("alice", "milai_note_operation_get", {
                "operation_id": "add-linked",
            })["direct_read_available"] is False
            call("alice", "milai_note_add", {
                **dependent_args, "operation_id": "new-revoked-dependency",
            }, denied=True)
            assert call("alice", "milai_note_search", {
                "query": "linked observation",
            })["items"] == []
            assert len(call("alice", "milai_note_list", {})["items"]) == 1
            assert call("alice", "milai_note_get", {
                "memory_id": note["memory_id"],
            })["content"] == "revised"
            deletion = call("alice", "milai_note_delete", {
                "memory_id": note["memory_id"], "expected_version": 2,
                "operation_id": "delete-one", "confirmation": "DELETE",
            })
            deleted = call("alice", "milai_note_get", {
                "memory_id": note["memory_id"], "version": 1,
            })
            assert deleted["content"] is None
            assert deleted["deletion"] == deletion["deletion"]
            assert deleted["deletion"]["physical_deletion_supported"] is False
            operation = call("alice", "milai_note_operation_get", {"operation_id": "delete-one"})
            assert operation["deletion"] == deletion["deletion"]
            assert call("alice", "milai_working_state_get", {})["status"] == "ABSENT"

            def state_error(result: dict[str, Any]) -> dict[str, Any]:
                text = result["content"][0]["text"]
                return dict(json.loads(text[text.index("{"):]))

            for scope in ["SESSION", "TASK", "PROJECT"]:
                absent = call("alice", "milai_working_state_get", {"scope": scope})
                assert absent["mcp_usage_contract"]["resume"]["arguments"] == {"scope": scope}
                saved_args = {"operation_id": "state-create-" + scope, "expected_version": 0,
                              "scope": scope, "payload": {"text": "original"}}
                saved = call("alice", "milai_working_state_update", saved_args)
                replayed = call("alice", "milai_working_state_update", saved_args)
                assert replayed["version"] == saved["version"] == 1 and replayed["replayed"]
                assert saved["suggested_next_step"]["next_arguments"] == {"scope": scope}
                conflict = state_error(call("alice", "milai_working_state_update", {
                    **saved_args, "payload": {"text": "changed"},
                }, denied=True))
                assert conflict["code"] == "OPERATION_CONFLICT"
                for change, field in [
                    ({"expected_version": 1}, "expected_version"),
                    ({"state_id": saved["state_id"]}, "expected_version"),
                    ({"state_id": "private-invalid-state"}, "state_id"),
                    ({"payload": {"private-body": "x" * 65536}}, "payload"),
                ]:
                    invalid = state_error(call("alice", "milai_working_state_update", {
                        **saved_args, "operation_id": "invalid-state-" + scope, **change,
                    }, denied=True))
                    assert invalid["code"] == "INVALID_REQUEST"
                    assert any(item["path"] == field for item in invalid["fields"])
                    assert "private-" not in str(invalid)

                update = {"state_id": saved["state_id"], "expected_version": 1,
                          "scope": scope, "payload": {"text": "concurrent"}}

                def compete(
                    index: int, update: dict[str, Any] = update, scope: str = scope,
                ) -> dict[str, Any]:
                    response = rpc(http, "tools/call", token=tokens_by_user["alice"], params={
                        "name": "milai_working_state_update", "arguments": {
                            **update, "operation_id": f"state-race-{scope}-{index}",
                        },
                    })
                    assert response.status_code == 200
                    return dict(response.json()["result"])

                with ThreadPoolExecutor(max_workers=2) as pool:
                    raced = list(pool.map(compete, [0, 1]))
                assert sum(not result.get("isError", False) for result in raced) == 1
                stale = state_error(next(result for result in raced if result.get("isError")))
                assert stale["code"] == "STALE_WORKING_STATE"
                assert stale["scope"] == scope and stale["next_arguments"] == {"scope": scope}
                assert stale["current_version"] == 2 and stale["retryable"] is False
                assert call("alice", "milai_working_state_get", {"scope": scope})["version"] == 2
                other = call("bob", "milai_working_state_get", {"scope": scope})
                assert other["status"] == "ABSENT"
                denied = state_error(call("bob", "milai_working_state_update", {
                    **update, "operation_id": "foreign-state-" + scope,
                }, denied=True))
                assert "current_version" not in denied and "concurrent" not in str(denied)

            for boundary in ["before", "after"]:
                current = call("alice", "milai_working_state_get", {"scope": "SESSION"})
                args = {"operation_id": "state-cut-" + boundary, "scope": "SESSION",
                        "expected_version": current["version"], "state_id": current["state_id"],
                        "payload": {"text": boundary}}
                forwarded = len(proxy.forwarded)
                proxy.state_fault = boundary
                unknown = state_error(call("alice", "milai_working_state_update", args,
                                           denied=True))
                assert unknown["code"] == "WORKING_STATE_OUTCOME_UNKNOWN"
                assert "next_tool" not in unknown and unknown["retryable"] is False
                assert len(proxy.forwarded) - forwarded == (0 if boundary == "before" else 1)
                replayed = call("alice", "milai_working_state_update", args)
                assert replayed["version"] == current["version"] + 1
                assert replayed["replayed"] is (boundary == "after")

            # Actual HTTP connection loss, including an SDK configured to permit read retries.
            uncertain = {}
            for boundary in ["before", "after"]:
                operation_id = "wire-cut-" + boundary
                args = {"content": boundary + " commit boundary", "operation_id": operation_id}
                proxy.faults[operation_id] = boundary
                failure = call("alice", "milai_note_add", args, denied=True)
                assert "NOTE_OUTCOME_UNKNOWN" in str(failure)
                assert proxy.forwarded.count(operation_id) == (0 if boundary == "before" else 1)
                receipt = call("alice", "milai_note_operation_get", {
                    "operation_id": operation_id,
                }, denied=boundary == "before")
                replay = call("alice", "milai_note_add", args)
                assert replay["version"] == 1
                if boundary == "after":
                    assert replay["memory_id"] == receipt["memory_id"] and replay["replayed"]
                uncertain[operation_id] = replay["memory_id"]

            # Independent writes and mixed reads, over the real HTTP MCP listener.
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs = [pool.submit(call, user, "milai_note_add", {
                    "content": user + " independent", "operation_id": "parallel-add",
                }) for user in ["alice", "bob"]]
                jobs += [pool.submit(call, "alice", "milai_note_get", {
                    "memory_id": note["memory_id"],
                }) for _ in range(2)]
                concurrent = [job.result(timeout=15) for job in jobs]
            assert concurrent[0]["memory_id"] != concurrent[1]["memory_id"]
            assert all(item["status"] == "DELETED" for item in concurrent[2:])
            call("bob", "milai_note_get", {
                "memory_id": concurrent[0]["memory_id"],
            }, denied=True)
            cold_content = body * 500
            saved = native(http, tokens_by_user["alice"], [{
                "tool": "milai_note_add", "arguments": {
                    "content": cold_content, "operation_id": "native-cold-save",
                },
            }])
            assert not saved["results"][0]["is_error"]
            cold_note = saved["results"][0]["body"]

        # Stop the original MCP listener and Runtime, then create fresh service instances.
        original_runtime_pid = api.pid
        _stop_process(api)
        migrate("0055_working_state_ref_capacity", blocked=True)
        api = _start_process(
            _RUNTIME_ROOT / ".venv/bin/milai-api", arguments=[],
            cwd=_RUNTIME_ROOT, environment=environment,
            output_fd=runtime_log.fileno(),
        )
        _wait_ready(base + "/health/ready", api)
        assert api.pid != original_runtime_pid
        with edge(
            fixture, scopes=ALL_SCOPES, role_clients=clients, catalog="ordinary-memory-v1",
            network=True, working_state_client_factory=lambda: AsyncMilaiClient(
                base_url=base, token=tokens["submitter"], max_retries=0,
            ),
        ) as (http, _server, _roles):
            actions = [{"tool": "milai_note_get", "arguments": {
                "memory_id": cold_note["memory_id"], "version": cold_note["version"],
                "offset": offset,
            }} for offset in range(0, len(cold_content), 8192)]
            actions += [{"tool": "milai_note_operation_get", "arguments": {
                "operation_id": op,
            }} for op in uncertain]
            actions.append({"tool": "milai_evidence_get", "arguments": {
                "evidence_id": second["evidence_id"],
            }})
            resumed = native(http, fixture.token(sub="alice", scope=" ".join(ALL_SCOPES)), actions)
            assert resumed["pid"] != saved["pid"]
            assert all(not item["is_error"] for item in resumed["results"])
            pages = math.ceil(len(cold_content) / 8192)
            assert "".join(item["body"]["content"]
                           for item in resumed["results"][:pages]) == cold_content
            for op, result in zip(uncertain, resumed["results"][pages:], strict=False):
                assert result["body"]["memory_id"] == uncertain[op]
                assert result["body"]["commit_status"] == "COMMITTED"
            assert resumed["results"][-1]["body"]["content"] == "independent source"
            # A new token, native MCP process and new Runtime still discover
            # the saved note through the default entry, without a remembered ID.
            discovered = native(http, fixture.token(sub="alice", scope=" ".join(ALL_SCOPES)), [{
                "tool": "milai_memory_search", "arguments": {"query": "Host note"},
            }])
            discovery = discovered["results"][0]
            assert not discovery["is_error"], discovery
            assert discovery["body"]["retrieval_status"] == "HIT"
            assert cold_note["memory_id"] in {
                item["memory_id"]
                for item in discovery["body"]["sources"]["notes"]["result"]["items"]
            }
        durations = sorted((item["finished"] - item["started"]) * 1000 for item in observations)
        events = sorted([(item["started"], 1) for item in observations]
                        + [(item["finished"], -1) for item in observations])
        active = peak = 0
        for _, change in events:
            active += change
            peak = max(peak, active)
        pool_acquire = []
        for line in runtime_log_path.read_text().splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("event") == "runtime_request_timing":
                durations_ms = record.get("safe_metadata", {}).get("durations_ms", {})
                if "db_pool_acquire_ms" in durations_ms:
                    pool_acquire.append(durations_ms["db_pool_acquire_ms"])
        assert pool_acquire, "existing Runtime connection metrics were not captured"
        pool_acquire.sort()
        report = {
            "scope": "synthetic HTTP MCP engineering; parent RPC calls including expected errors",
            "calls": len(observations), "peak_client_concurrency": peak,
            "latency_ms": {str(p): durations[math.ceil(p / 100 * len(durations)) - 1]
                           for p in [50, 95, 99]},
            "expected_errors": sum(item["expected_error"] for item in observations),
            "mcp_errors": sum(item["mcp_error"] for item in observations),
            "http_errors": sum(item["http_status"] != 200 for item in observations),
            "timeouts": 0, "connection_wait": {
                "metric": "DB pool acquisition, including checkout and any waiting",
                "samples": len(pool_acquire), "max_ms": max(pool_acquire),
                "p95_ms": pool_acquire[math.ceil(0.95 * len(pool_acquire)) - 1],
                "http_pool_wait": "NOT_SEPARATELY_INSTRUMENTED",
            },
            "index": "DIRECT_PG_NO_ASYNC_LAG", "scale": "7 notes, 2 Evidence, 2 subjects",
            "native_client_pids": [saved["pid"], resumed["pid"]],
            "runtime_pids": [original_runtime_pid, api.pid], "requests": observations,
            "migration": "EMPTY_DOWNGRADE_UPGRADE_AND_NONEMPTY_REFUSAL_CONFIRMED",
        }
        output = Path(os.environ.get("MILAI_V07_RESULT_PATH", tmp_path / "engineering.json"))
        output.write_text(json.dumps(report, indent=2) + "\n")
    finally:
        stack.close()
        for client in clients:
            client.close()
        _stop_process(api)
        if urls is not None:
            _drop_database(owner, database)
