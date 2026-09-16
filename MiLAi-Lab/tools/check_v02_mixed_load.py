"""Public SDK import plus fixed-arrival MCP reads; no Product private imports or SQL."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

from check_v02_service_concurrency import clock_identity, digest, request_fingerprint, write
from v02_client_gc import observe
from v02_fixed_arrivals import arrivals, summarize


async def run(root: Path) -> dict:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from milai_client import AsyncMilaiClient, HttpxAsyncTransport

    config = json.loads((root / "config.json").read_text())
    assert not config["model_transport_enabled"] and config["max_retries"] == 0
    phase = "prepare"
    physical, events, scopes, sources = [], [], ("TASK", "SESSION", "PROJECT"), []
    report = {
        "status": "RUNNING",
        "arm": config["mixed_load_arm"],
        "phases": [],
        "model_calls": 0,
        "gateway_slo": "NOT_MEASURED",
    }
    sdk_log = (root / "sdk-physical.jsonl").open("w")
    if config.get("require_shared_monotonic_clock", False):
        report["clock_identity"] = clock_identity()

    class Observed(HttpxAsyncTransport):
        async def send(self, method, path, data, headers):
            assert len(physical) < config["maximum_sdk_physical_calls"]
            event = {
                "phase": phase,
                "method": method,
                "path": path,
                "start_s": time.monotonic(),
                "request_body_sha256": hashlib.sha256(data or b"").hexdigest(),
            }
            physical.append(event)
            try:
                response = await super().send(method, path, data, headers)
                event["status"] = response.status
                return response
            except BaseException as exc:
                event["error_type"] = type(exc).__name__
                raise
            finally:
                event["end_s"] = time.monotonic()
                sdk_log.write(json.dumps(event) + "\n")
                sdk_log.flush()

    sdk = AsyncMilaiClient(
        token=os.environ["MILAI_AGENT_SUBMITTER_TOKEN"],
        max_retries=0,
        base_url=os.environ["MILAI_BASE_URL"],
        transport=Observed(os.environ["MILAI_BASE_URL"], 10),
    )
    captures = []

    def source_payload(index, *, seed=False):
        size = config["payload_text_bytes"][index % 3]
        marker = ("seedsource" if seed else "importsource") + str(index)
        content = marker + "\nfirst\n" + "x" * (size - len(marker) - 13) + "\nlast\n"
        return {
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": "mixed://" + marker,
            "subject_id": "mixed-source",
            "observed_at": "2026-09-06T10:00:00+08:00",
            "content": content,
            "data_classification": "SYNTHETIC",
            "speaker": "user",
            "source_context": {
                "session_id": "mixed-session",
                "turn_id": marker,
                "turn_ordinal": index,
                "round_id": marker,
                "round_ordinal": index,
            },
            "permission_snapshot": {"readable": True, "project_ids": ["mixed-project"]},
        }

    async def ready(refs):
        value = await sdk.wait_for_projection_readiness(
            target_outbox_ids=refs,
            required_projections=["evidence"],
            expected_versions={"evidence": "evidence-search-v1"},
            timeout_ms=config["drain_timeout_ms"],
        )
        assert value["status"] == "READY" and not value["projection_work_started"]
        return value

    try:
        await sdk.capabilities()
        for i in range(3):
            sources.append(
                await sdk.capture_evidence(source_payload(i, seed=True), operation_id=f"source-{i}")
            )
        write(root / "source-receipts.json", [s.raw for s in sources])
        await ready([s.outbox_id for s in sources])
        indices = iter(range(config["state_count"]))

        async def seed_states():
            for i in indices:
                value = await sdk.update_working_state(
                    {
                        "principal_binding_digest": digest("seed-host-" + str(i % 2)),
                        "project_id": "mixed-project",
                        "scope_type": "TASK",
                        "scope_ref": f"seed-{i}",
                        "expected_version": 0,
                        "payload": {
                            "first": f"state-{i}",
                            "text": "x" * config["payload_text_bytes"][i % 3],
                            "last": "preserved",
                            "evidence_refs": [sources[i % 3].evidence_id],
                        },
                    },
                    operation_id=f"seed-state-{i}",
                )
                assert value["version"] == 1

        async with asyncio.TaskGroup() as group:
            for _ in range(config["seed_concurrency"]):
                group.create_task(seed_states())

        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + os.environ["MILAI_CODEX_TOKEN"]}
        ) as http:
            async with Client(
                streamable_http_client(os.environ["MILAI_MIXED_MCP_URL"], http_client=http),
                mode=config["mcp_protocol_mode"],
            ) as mcp:
                catalog = await mcp.list_tools()
                write(root / "mcp-catalog.json", catalog.model_dump(mode="json"))
                receipts, tool_calls = {}, []

                async def call(tool, args):
                    assert len(tool_calls) < config["maximum_mcp_tool_calls"]
                    event = {
                        "phase": phase,
                        "tool": tool,
                        "args": args,
                        "start_s": time.monotonic(),
                    }
                    tool_calls.append(event)
                    try:
                        result = await mcp.call_tool(tool, args)
                        assert not result.is_error and isinstance(result.structured_content, dict)
                        value = result.structured_content
                        event.update(
                            status="COMPLETED",
                            response_sha256=digest(value),
                            runtime_request_id_fingerprint=request_fingerprint(value),
                        )
                        return value
                    finally:
                        event["end_s"] = time.monotonic()

                for i, scope in enumerate(scopes):
                    receipts[scope] = await call(
                        "milai_working_state_update",
                        {
                            "scope": scope,
                            "operation_id": "active-" + scope,
                            "expected_version": 0,
                            "payload": {
                                "first": scope,
                                "text": "x" * config["payload_text_bytes"][i],
                                "last": "preserved",
                                "evidence_refs": [sources[i].evidence_id],
                            },
                        },
                    )
                write(root / "mcp-state-receipts.json", receipts)

                async def read(i):
                    scope = scopes[i % 3]
                    value = await call("milai_working_state_get", {"scope": scope})
                    assert value["payload"] == receipts[scope]["payload"]
                    assert value["state_version_id"] == receipts[scope]["state_version_id"]
                    assert not value.get("payload_withheld")
                    return {
                        "scope": scope,
                        "runtime_request_id_fingerprint": request_fingerprint(value),
                    }

                for i in range(config["warmup_reads"]):
                    await read(i)
                for repeat in range(config["rounds"]):
                    phase = f"round-{repeat}"
                    start, abort = time.monotonic() + 0.1, asyncio.Event()

                    async def capture(i, repeat=repeat):
                        index = repeat * config["imports_per_round"] + i
                        payload = source_payload(index)
                        begin = time.monotonic()
                        value = await sdk.capture_evidence(payload, operation_id=f"import-{index}")
                        item = {
                            "index": index,
                            "receipt": value.raw,
                            "committed_response_s": time.monotonic(),
                            "save_ms": 1000 * (time.monotonic() - begin),
                            "content_hash": hashlib.sha256(payload["content"].encode()).hexdigest(),
                        }
                        captures.append(item)
                        assert value.evidence_id and value.outbox_id and not value.replayed
                        return {"evidence_id": value.evidence_id, "save_ms": item["save_ms"]}

                    async with asyncio.TaskGroup() as group:
                        group.create_task(
                            arrivals(
                                count=config["reads_per_round"],
                                rate=config["read_rate"],
                                capacity=config["read_capacity"],
                                timeout=config["request_timeout_seconds"],
                                operation=read,
                                label=phase + "-read",
                                events=events,
                                start=start,
                                abort=abort,
                            )
                        )
                        if config["mixed_load_arm"] == "mixed":
                            group.create_task(
                                arrivals(
                                    count=config["imports_per_round"],
                                    rate=config["import_rate"],
                                    capacity=config["import_capacity"],
                                    queue_capacity=config.get("import_queue_capacity", 0),
                                    queue_timeout=config.get("import_queue_timeout_seconds", 0),
                                    timeout=config["request_timeout_seconds"],
                                    operation=capture,
                                    label=phase + "-import",
                                    events=events,
                                    start=start,
                                    abort=abort,
                                )
                            )
                    end = time.monotonic()
                    reads = summarize(
                        [e for e in events if e["label"] == phase + "-read"],
                        duration=config["round_seconds"],
                        target_ms=config["read_p95_stop_ms"],
                    )
                    read_sent = [
                        e for e in events if e["label"] == phase + "-read" and "dispatch_s" in e
                    ]
                    imports = [e for e in events if e["label"] == phase + "-import"]
                    overlap = sum(
                        any(
                            r["dispatch_s"] < e["observed_end_s"]
                            and e["dispatch_s"] < r["observed_end_s"]
                            for r in read_sent
                        )
                        for e in imports
                        if "dispatch_s" in e
                    )
                    report["phases"].append(
                        {
                            "round": repeat,
                            "read": reads,
                            "actual_round_seconds": end - start,
                            "imports_overlapping_read_calls": overlap,
                            "import": summarize(
                                imports, duration=config["round_seconds"], target_ms=150
                            )
                            if imports
                            else None,
                        }
                    )
                    write(root / "arrival-events.json", events)
                    write(root / "capture-receipts.json", captures)
                    phase = f"drain-{repeat}"
                    current = [
                        c for c in captures if c["index"] // config["imports_per_round"] == repeat
                    ]
                    if current:
                        readiness = await ready([c["receipt"]["outbox_id"] for c in current])
                        write(root / f"readiness-{repeat}.json", readiness)
                        for item in current:
                            found = await sdk.get_evidence_metadata(item["receipt"]["evidence_id"])
                            assert found["content_hash"] == item["content_hash"]
                    if (
                        abort.is_set()
                        or not reads["candidate_target_met"]
                        or any(e["status"] != "COMPLETED" for e in imports)
                    ):
                        report["status"] = "STOPPED_AT_CANDIDATE_TARGET_OR_ERROR"
                        break
                else:
                    report["status"] = "FIXED_ARRIVAL_CHECK_COMPLETED_NOT_GATEWAY_SLO"
                report["mcp_tool_calls"] = len(tool_calls)
                write(root / "mcp-events.json", tool_calls)
        report["sdk_physical_calls"] = len(physical)
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        await sdk.close()
        sdk_log.close()
        write(root / "arrival-events.json", events)
        write(root / "capture-receipts.json", captures)
        if config.get("require_shared_monotonic_clock", False):
            report["clock_identity_end"] = clock_identity()
        write(root / "mixed-result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((args.root / "config.json").read_text())
    with observe(args.root, enabled=config.get("observe_client_gc", False)):
        result = asyncio.run(run(args.root))
    print(json.dumps(result))
