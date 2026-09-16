#!/usr/bin/env python3
"""Reduce Product-03 Host traces to a bounded identity linkage and summary."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _records(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--linkage", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    records = _records(args.trace)
    providers = {
        str(item["trace_id"]): item
        for item in records
        if item.get("event") == "PROVIDER_ANSWER" and item.get("trace_id")
    }
    contexts = [
        item for item in records if item.get("event") == "HOST_MCP_PREPARE_CONTEXT"
    ]
    linkage: list[dict[str, Any]] = []
    for item in contexts:
        trace_id = str(item.get("trace_id") or "")
        provider = providers.get(trace_id)
        execution = item.get("recall_execution_trace") or {}
        acquisition = execution.get("acquisition_state") or {}
        linkage.append(
            {
                "schema": "milai.product03.identity-link.v1",
                "task_session_sha256": item.get("task_session_sha256"),
                "task_operation_sha256": item.get("task_operation_sha256"),
                "host_mcp_attempt_trace_id": item.get("attempt_trace_id"),
                "runtime_trace_id": trace_id or None,
                "runtime_request_id": execution.get("runtime_request_id"),
                "mcp_tool": item.get("mcp_tool"),
                "logical_mcp_calls": execution.get("logical_mcp_calls"),
                "memory_status": item.get("memory_status"),
                "canonical_mutation": acquisition.get("canonical_mutation"),
                "provider_called": provider is not None,
                "provider_logical_request_id": (
                    provider.get("logical_request_id") if provider else None
                ),
                "provider_finish_reason": (
                    provider.get("finish_reason") if provider else None
                ),
                "provider_memory_tool_count": (
                    len(provider.get("excluded_memory_tools") or []) * 0
                    if provider
                    else 0
                ),
            }
        )

    args.linkage.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in linkage),
        encoding="utf-8",
    )
    memory_ms = [
        float(item["memory_control_ms"])
        for item in contexts
        if isinstance(item.get("memory_control_ms"), (int, float))
    ]
    provider_events = list(providers.values())
    summary = {
        "schema": "milai.product03.trace-summary.v1",
        "source_trace": str(args.trace),
        "native_operations": sum(
            item.get("event") == "HOST_NATIVE_TASK_BOUND" for item in records
        ),
        "mcp_attempts": sum(
            item.get("event") == "HOST_MCP_PREPARE_ATTEMPT" for item in records
        ),
        "mcp_contexts": len(contexts),
        "mcp_insufficient": sum(
            item.get("event") == "HOST_MCP_MEMORY_INSUFFICIENT" for item in records
        ),
        "provider_answers": len(provider_events),
        "provider_terminal_stop": sum(
            item.get("finish_reason") == "stop" for item in provider_events
        ),
        "canonical_mutation_true": sum(
            (item.get("recall_execution_trace") or {})
            .get("acquisition_state", {})
            .get("canonical_mutation")
            is True
            for item in contexts
        ),
        "memory_control_ms": {
            "mean": round(statistics.fmean(memory_ms), 3) if memory_ms else None,
            "max": round(max(memory_ms), 3) if memory_ms else None,
        },
        "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in provider_events),
        "completion_tokens": sum(
            int(item.get("completion_tokens") or 0) for item in provider_events
        ),
        "linkage_rows": len(linkage),
    }
    args.summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
