"""Summarize recorded external facts; semantic evaluation remains separately attributed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def session_facts(root: Path) -> dict[str, Any]:
    allocation = read(root / "allocation.json")
    if not (root / "result.json").exists():
        return {"session": root.name, "allocation": allocation, "terminal_receipt": False}
    result = read(root / "result.json")
    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    tools = [i for i in items if i.get("type") in
             ("command_execution", "mcp_tool_call", "file_change")]
    usage = result.get("usage")
    total = (sum(u["input_tokens"] + u["output_tokens"] for u in usage)
             if usage and all("input_tokens" in u and "output_tokens" in u for u in usage)
             else None)
    payload_before = read(root / "before.json")["payload"]
    payload_after = read(root / "after.json")["payload"]
    return {
        "session": root.name, "allocation": allocation, "terminal_receipt": True,
        "returncode": result["returncode"], "stop_reason": result["stop_reason"],
        "elapsed_seconds": result["elapsed_seconds"], "usage": usage,
        "total_input_output_tokens": total, "completed_tool_calls": len(tools),
        "tool_failure_count": sum(i.get("status") == "failed" for i in tools),
        "file_change_calls": sum(i.get("type") == "file_change" for i in tools),
        "resolve_calls": [i["arguments"] for i in tools
                          if i.get("tool") == "milai_memory_resolve"],
        "state_versions": [result["before_version"], result["after_version"]],
        "save_status": result.get("save_status"),
        "payload_changed": payload_before != payload_after,
        "payload_bytes": [len(json.dumps(p, ensure_ascii=False).encode())
                          for p in (payload_before, payload_after)],
        "reported_host_errors": [i.get("message") for i in items if i.get("type") == "error"],
        "external_messages": [i["text"] for i in items if i.get("type") == "agent_message"],
        "later_request_inputs": "UNOBSERVED",
        "semantic_review": read(root / "evaluation.json")
        if (root / "evaluation.json").exists() else None,
    }


def pair_controls(left: Path, right: Path) -> dict[str, bool]:
    allocations = [read(p / "allocation.json") for p in (left, right)]
    before = [read(p / "before.json") for p in (left, right)]
    models = [read(p / "model-catalog-identity.json")["selected_metadata"] for p in (left, right)]
    return {
        "same_fixture": allocations[0]["fixture_sha256"] == allocations[1]["fixture_sha256"],
        "same_code": all(allocations[0][key] == allocations[1][key] for key in
                         ("runner_sha256", "wrapper_sha256", "config_sha256")),
        "same_product_pin": allocations[0]["product_pin"] == allocations[1]["product_pin"],
        "same_initial_payload": before[0]["payload"] == before[1]["payload"],
        "separate_state": before[0]["state_id"] != before[1]["state_id"],
        "separate_project": allocations[0]["project"] != allocations[1]["project"],
        "same_model_metadata": bool(models[0]) and models[0] == models[1],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = [session_facts(path) for path in sorted((args.root / "sessions").iterdir())]
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote facts for {len(result)} allocated sessions")


if __name__ == "__main__":
    main()
