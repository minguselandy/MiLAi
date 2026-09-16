"""Finite scope-bound lexical recall via public SDK seeds and the published MCP tool."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path

from check_v02_service_concurrency import digest, distribution, write


def source(index: int, sizes: list[int]) -> dict:
    project = "mixed-project" if index % 2 == 0 else "other-project"
    marker = f"rangedoc{index:04d}"
    prefix, suffix = f"rangefixture {marker}\nfirst\n", "\nlast\n"
    content = prefix + "x" * (sizes[index % len(sizes)] - len(prefix) - len(suffix)) + suffix
    return {
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": "range://" + marker,
        "subject_id": marker,
        "observed_at": "2026-09-06T10:00:00+08:00",
        "content": content,
        "data_classification": "SYNTHETIC",
        "permission_snapshot": {"readable": True, "project_ids": [project]},
    }


def compile_forbidden_refs(refs: set[str]) -> re.Pattern[str]:
    """Compile literal substring checks once; an empty set must never match."""
    return re.compile("|".join(re.escape(ref) for ref in sorted(refs)) if refs else r"(?!)")


def check_result(
    value: dict, allowed: set[str], forbidden: set[str] | re.Pattern[str], *, require_hit=True,
    allow_budget_limited=False,
) -> set[str]:
    # Check every disclosed ID, including context/trace copies, not just the selected list.
    raw = json.dumps(value, ensure_ascii=False)
    disclosed = (
        forbidden.search(raw) is not None
        if isinstance(forbidden, re.Pattern)
        else any(ref in raw for ref in forbidden)
    )
    assert not disclosed, "CROSS_SCOPE_EVIDENCE_ID_DISCLOSED"
    ids = {ref for item in value.get("evidence", []) for ref in item.get("evidence_ids", [])}
    assert ids <= allowed, "UNEXPECTED_EVIDENCE_ID"
    if require_hit:
        assert ids, "EXPECTED_SCOPED_RECALL_MISSING"
    budget_limited = (
        allow_budget_limited and bool(ids) and value.get("retrieval_status") == "DEGRADED"
        and value.get("warnings") == [{
            "code": "RETRIEVAL_DEGRADED",
            "message": "The returned memory context was limited by the context budget.",
        }]
    )
    assert value.get("retrieval_status") in {"HIT", "MISS"} or budget_limited, "UNUSABLE_RESPONSE"
    return ids


async def observe_resolve(
    client, event, query, config, allowed, forbidden, *, extra=None,
    expect_error=False, require_hit=True, clock=time.monotonic,
):
    """Keep the original call-through-checks boundary and expose its two parts."""
    try:
        result = await asyncio.wait_for(client.call_tool(
            "milai_memory_resolve", {"query": query, **(extra or {})},
        ), config["request_timeout_seconds"])
        event["response_received_s"] = clock()
        event["response"] = result.model_dump(mode="json")
        assert result.is_error is expect_error, "UNEXPECTED_TOOL_OUTCOME"
        if not expect_error:
            value = result.structured_content
            assert isinstance(value, dict)
            event["evidence_ids"] = sorted(check_result(
                value, allowed, forbidden, require_hit=require_hit,
                allow_budget_limited=config.get("allow_budget_limited_view", False),
            ))
            event["retrieval_status"] = value["retrieval_status"]
            event["response_sha256"] = digest(value)
        event["status"] = "EXPECTED_REJECTION" if expect_error else "COMPLETED"
    except BaseException as exc:
        event.update(status="FAILED_OR_CANCELLED", error_type=type(exc).__name__)
        raise
    finally:
        event["end_s"] = clock()
        event["elapsed_ms"] = (event["end_s"] - event["start_s"]) * 1000
        received = event.get("response_received_s")
        event["call_to_response_ms"] = (
            (received - event["start_s"]) * 1000 if received is not None else None
        )
        event["post_response_checks_ms"] = (
            (event["end_s"] - received) * 1000 if received is not None else None
        )


async def run(root: Path) -> dict:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from milai_client import AsyncMilaiClient, HttpxAsyncTransport

    config = json.loads((root / "config.json").read_text())
    assert config["scoped_recall"] and not config["model_transport_enabled"]
    assert config["max_retries"] == 0 and max(config["read_concurrency"]) <= 8
    events, physical, receipts = [], [], {}
    phase = "seed"
    report = {
        "status": "RUNNING", "phases": [], "model_calls": 0,
        "gateway_slo": "NOT_MEASURED", "tenant_fairness": "NOT_TESTED",
        "scope": "ONE_BOUND_MCP_PROJECT_TWO_SOURCE_PROJECTS_SAME_RUNTIME_TENANT",
    }
    log = (root / "sdk-physical.jsonl").open("w")

    class Observed(HttpxAsyncTransport):
        async def send(self, method, path, data, headers):
            assert len(physical) < config["maximum_sdk_physical_calls"], "SDK_CALL_LIMIT"
            event = {
                "phase": phase, "method": method, "path": path, "start_s": time.monotonic(),
                "body_sha256": hashlib.sha256(data or b"").hexdigest(),
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
                log.write(json.dumps(event) + "\n")
                log.flush()

    sdk = AsyncMilaiClient(
        token=os.environ["MILAI_AGENT_SUBMITTER_TOKEN"], max_retries=0,
        base_url=os.environ["MILAI_BASE_URL"],
        transport=Observed(os.environ["MILAI_BASE_URL"], config["request_timeout_seconds"]),
    )
    try:
        capability = (await sdk.capabilities()).raw
        write(root / "capabilities.json", capability)
        assert capability["feature_profile"] == "BASELINE"
        assert capability["semantic_dense"]["provider"] == "deterministic_hash"
        indices = iter(range(config["source_count"]))

        async def seed():
            for index in indices:
                payload = source(index, config["payload_text_bytes"])
                saved = await sdk.capture_evidence(payload, operation_id=f"range-source-{index}")
                receipts[index] = saved.raw

        async with asyncio.TaskGroup() as group:
            for _ in range(config["seed_concurrency"]):
                group.create_task(seed())
        write(root / "source-receipts.json", receipts)
        # Public readiness has a bounded target list. Check deterministic batches once each.
        phase = "readiness"
        for begin in range(0, config["source_count"], config["readiness_batch_size"]):
            targets = [receipts[i]["outbox_id"] for i in range(
                begin, min(begin + config["readiness_batch_size"], config["source_count"])
            )]
            ready = await sdk.wait_for_projection_readiness(
                target_outbox_ids=targets, required_projections=["evidence"],
                expected_versions={"evidence": "evidence-search-v1"},
                timeout_ms=config["drain_timeout_ms"],
            )
            write(root / f"readiness-{begin}.json", ready)
            assert ready["status"] == "READY" and not ready["projection_work_started"]
        allowed = {r["evidence_id"] for i, r in receipts.items() if i % 2 == 0}
        forbidden = {r["evidence_id"] for i, r in receipts.items() if i % 2 == 1}
        forbidden.update(f"rangedoc{i:04d}" for i in receipts if i % 2 == 1)
        forbidden_matcher = compile_forbidden_refs(forbidden)
        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + os.environ["MILAI_CODEX_TOKEN"]},
        ) as http:
            async with Client(
                streamable_http_client(os.environ["MILAI_MIXED_MCP_URL"], http_client=http),
                mode=config["mcp_protocol_mode"],
            ) as client:
                catalog = await client.list_tools()
                write(root / "mcp-catalog.json", catalog.model_dump(mode="json"))

                async def call(query, *, extra=None, expect_error=False, require_hit=True):
                    assert len(events) < config["maximum_mcp_tool_calls"], "MCP_CALL_LIMIT"
                    event = {"phase": phase, "query": query, "start_s": time.monotonic()}
                    events.append(event)
                    await observe_resolve(
                        client, event, query, config, allowed, forbidden_matcher,
                        extra=extra, expect_error=expect_error, require_hit=require_hit,
                    )

                phase = "scope-controls"
                await call("rangefixture")
                await call("rangedoc0001", require_hit=False)
                await call("rangefixture", extra={"requested_scope": {
                    "project_ids": ["other-project"],
                }}, expect_error=True)
                report["scope_controls"] = "PASSED_WITHOUT_TENANT_ISOLATION_CLAIM"
                for concurrency in config["read_concurrency"]:
                    for repeat in range(config["rounds"]):
                        phase = f"c{concurrency}-r{repeat}"
                        reads = iter(range(config["reads_per_round"]))
                        started = time.monotonic()

                        async def reader(reads=reads):
                            for _ in reads:
                                await call("rangefixture")

                        async with asyncio.TaskGroup() as group:
                            for _ in range(concurrency):
                                group.create_task(reader())
                        rows = [e for e in events if e["phase"] == phase]
                        latency = distribution([e["elapsed_ms"] for e in rows])
                        report["phases"].append({
                            "name": phase, "concurrency": concurrency, "latency": latency,
                            "completed_per_second": len(rows) / (time.monotonic() - started),
                            "call_to_response_latency": distribution([
                                e["call_to_response_ms"] for e in rows
                            ]),
                            "post_response_checks_latency": distribution([
                                e["post_response_checks_ms"] for e in rows
                            ]),
                        })
                        if latency["p95_ms"] > config["read_p95_stop_ms"]:
                            report["status"] = "STOPPED_AT_CLIENT_P95_BOUNDARY"
                            return report
                report["status"] = "CLIENT_RANGE_BOUNDARY_MET_NOT_GATEWAY_SLO"
                return report
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        await sdk.close()
        log.close()
        report.update(source_count=len(receipts), sdk_physical_calls=len(physical),
                      mcp_tool_calls=len(events))
        report["returned_view_counts"] = {
            status: sum(e.get("retrieval_status") == status for e in events)
            for status in ("HIT", "MISS", "DEGRADED")
        }
        write(root / "recall-events.json", events)
        write(root / "recall-result.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.root.resolve()))
