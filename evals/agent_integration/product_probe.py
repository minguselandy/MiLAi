from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path

import milai_openworker_mcp
from milai_client import (
    AgentRecallPolicy,
    TaskMemoryBudget,
    TaskMemoryIdentity,
    TokenBudget,
)
from milai_openworker_mcp import (
    McpUnixClient,
    McpUnixClientError,
    MemoryWriteHandoff,
    MemoryWriteIntent,
    TargetTokenizerCounter,
    build_task_memory_controller,
)


class ProductProbeError(RuntimeError):
    pass


def _product_origin() -> str:
    origin = Path(milai_openworker_mcp.__file__).resolve()
    prefix = Path(sys.prefix).resolve()
    if not origin.is_relative_to(prefix):
        raise ProductProbeError("probe did not import the fresh-installed product")
    return str(origin)


def _catalog(socket_path: Path) -> dict[str, object]:
    with McpUnixClient(socket_path) as client:
        tools = client.list_tools()
    return {"product_origin": _product_origin(), "tools": list(tools)}


def _cache(socket_path: Path, tokenizer_json: Path, query: str) -> dict[str, object]:
    counter = TargetTokenizerCounter(tokenizer_json)
    digest = hashlib.sha256(b"milai-openworker-product-probe-v1").hexdigest()
    client = McpUnixClient(socket_path)
    controller = build_task_memory_controller(
        client,
        compiler_digest=digest,
        router_digest=digest,
        policy_digest=digest,
    )
    identity = TaskMemoryIdentity(
        tenant_id="mcp-socket-capability",
        session_id="hardened-cache-session",
        agent_id="openworker",
        profile_id="reader-lite",
        task_epoch="hardened-cache-task",
    )
    policy = AgentRecallPolicy(
        scope={"host_policy": "reader-lite"},
        authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        max_limit=3,
    )
    token_budget = TokenBudget.for_class("STANDARD", counter=counter)
    task_budget = TaskMemoryBudget(
        max_prepare_context_calls=11,
        max_full_recall_calls=1,
        max_delta_refreshes=1,
        max_memory_tokens_injected=512,
        max_validation_calls=9,
        memory_deadline_ms=5_000,
    )
    records: list[dict[str, object]] = []
    try:
        for index in range(10):
            started = time.perf_counter()
            prepared = controller.prepare_context(
                query,
                identity=identity,
                event="TASK_START" if index == 0 else "MODEL_RETRY",
                active_goal="answer the current synthetic project runtime version",
                recall_policy=policy,
                token_counter=counter,
                token_budget=token_budget,
                task_budget=task_budget,
                constraints=("preserve current OpenIssue and uncertainty",),
            )
            records.append(
                {
                    "index": index,
                    "route": prepared.route,
                    "status": prepared.status,
                    "latency_ms": round((time.perf_counter() - started) * 1_000, 6),
                    "context_injected": (
                        prepared.delta is not None
                        and prepared.delta.delta.rendered_context is not None
                    ),
                    "memory_tokens": (
                        prepared.delta.metrics.actual_tokens
                        if prepared.delta is not None
                        else 0
                    ),
                    "usage": prepared.usage,
                }
            )
    finally:
        client.close()
    cache = records[1:]
    latencies = sorted(float(record["latency_ms"]) for record in cache)
    p95_index = max(
        0, min(len(latencies) - 1, int(0.95 * len(latencies) + 0.999999) - 1)
    )
    result = {
        "product_origin": _product_origin(),
        "records": records,
        "validated_cache_hits": sum(
            record["route"] == "CACHE" and record["status"] == "UNCHANGED"
            for record in cache
        ),
        "cache_opportunities": len(cache),
        "validated_cache_hit_rate": (
            sum(record["route"] == "CACHE" for record in cache) / len(cache)
        ),
        "validated_cache_warm_p95_ms": latencies[p95_index],
        "validated_cache_warm_mean_ms": statistics.fmean(latencies),
        "context_injections": sum(
            bool(record["context_injected"]) for record in records
        ),
        "full_recall_calls": (records[-1]["usage"] or {}).get("full_recall_calls"),
        "validation_calls": (records[-1]["usage"] or {}).get("validation_calls"),
    }
    client = McpUnixClient(socket_path)
    controller = build_task_memory_controller(
        client,
        compiler_digest=digest,
        router_digest=digest,
        policy_digest=digest,
    )
    try:
        replay = controller.prepare_context(
            query,
            identity=identity,
            event="TASK_START",
            active_goal="answer the current synthetic project runtime version",
            recall_policy=policy,
            token_counter=counter,
            token_budget=token_budget,
            task_budget=task_budget,
            constraints=("preserve current OpenIssue and uncertainty",),
        )
        exhausted = controller.prepare_context(
            query,
            identity=identity,
            event="EXPLICIT_MEMORY_REQUEST",
            active_goal="answer the current synthetic project runtime version",
            recall_policy=policy,
            token_counter=counter,
            token_budget=token_budget,
            task_budget=task_budget,
            constraints=("preserve current OpenIssue and uncertainty",),
        )
    finally:
        client.close()
    result["budget_terminal"] = {
        "initial_status": replay.status,
        "status": exhausted.status,
        "reason": exhausted.reason,
        "validation_token_absent": exhausted.validation_token is None,
        "full_recall_calls_before_exhaustion": (replay.usage or {}).get(
            "full_recall_calls"
        ),
    }
    if (
        records[0]["status"] != "READY"
        or result["validated_cache_hits"] != 9
        or result["context_injections"] != 1
        or result["full_recall_calls"] != 1
        or result["validation_calls"] != 9
        or result["budget_terminal"]
        != {
            "initial_status": "READY",
            "status": "BUDGET_EXHAUSTED",
            "reason": "FULL_RECALL_CALL_BUDGET_EXHAUSTED",
            "validation_token_absent": True,
            "full_recall_calls_before_exhaustion": 1,
        }
    ):
        raise ProductProbeError(
            "validated cache workload did not meet its exact contract"
        )
    return result


def _settle(socket_path: Path, marker: str, observed_at: str) -> dict[str, object]:
    client = McpUnixClient(socket_path)
    try:
        tools = client.list_tools()
        handoff = MemoryWriteHandoff(client)
        intent = MemoryWriteIntent(
            intent_id=f"hardened-{marker}",
            task_epoch=f"task-{marker}",
            source_type="TOOL_OBSERVATION",
            source_ref=f"openworker://{marker}/task-end",
            subject_id=marker,
            observed_at=observed_at,
            content=f"{marker} task outcome observed runtime Python 3.11",
            permission_snapshot={"readable": True, "scope": "synthetic-agent-e2e"},
            proposal={
                "operation": "CREATE",
                "requested_authority": "INFORMATIONAL",
                "scope_predicate": {"project_ids": ["milai-agent-e2e"]},
                "model_id": "host-deterministic",
                "template_version": "memory-write-intent-v1",
                "input_snapshot_hash": "0" * 64,
                "proposed_patch": {
                    "subject_id": f"settlement-{marker}",
                    "predicate": "task.runtime.observation",
                    "claim_type": "FACT",
                    "payload": {"python": "3.11", "source": "task-settlement"},
                    "authority": "INFORMATIONAL",
                    "confidence": 1.0,
                },
            },
        )
        first = handoff.handoff(intent, confirmation="HANDOFF")
        second = handoff.handoff(intent, confirmation="HANDOFF")
    finally:
        client.close()
    forbidden = {
        "milai_proposal_review",
        "milai_claim_create",
        "milai_claim_update",
        "milai_open_issue_resolve",
    }
    if forbidden & set(tools) or first.canonical_changed or not second.deduplicated:
        raise ProductProbeError("submitter lane violated settlement isolation")
    return {
        "product_origin": _product_origin(),
        "tools": list(tools),
        "first": asdict(first),
        "second": asdict(second),
    }


def _reader_write_negative(socket_path: Path) -> dict[str, object]:
    client = McpUnixClient(socket_path)
    try:
        try:
            client.capture_evidence(
                {
                    "operation_id": "reader-write-negative",
                    "source_type": "TOOL_OBSERVATION",
                    "source_ref": "openworker://reader/write-negative",
                    "subject_id": "reader-negative",
                    "observed_at": "2026-08-23T12:00:00+08:00",
                    "content": "must not be written",
                    "permission_snapshot": {"readable": True},
                    "confirmation": "CAPTURE",
                    "retention_state": "READABLE",
                    "data_classification": "SYNTHETIC",
                }
            )
        except McpUnixClientError as exc:
            outcome = str(exc)
        else:
            raise ProductProbeError(
                "reader lane unexpectedly accepted Evidence capture"
            )
    finally:
        client.close()
    return {"product_origin": _product_origin(), "reader_write_result": outcome}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exercise fresh-installed OpenWorker product APIs"
    )
    parser.add_argument(
        "mode", choices=("catalog", "cache", "settle", "reader-write-negative")
    )
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--tokenizer-json", type=Path)
    parser.add_argument("--query")
    parser.add_argument("--marker")
    parser.add_argument("--observed-at")
    args = parser.parse_args()
    if args.mode == "catalog":
        result = _catalog(args.socket)
    elif args.mode == "cache":
        if args.tokenizer_json is None or args.query is None:
            raise SystemExit("cache mode requires tokenizer and query")
        result = _cache(args.socket, args.tokenizer_json, args.query)
    elif args.mode == "settle":
        if args.marker is None or args.observed_at is None:
            raise SystemExit("settle mode requires marker and observed-at")
        result = _settle(args.socket, args.marker, args.observed_at)
    else:
        result = _reader_write_negative(args.socket)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
