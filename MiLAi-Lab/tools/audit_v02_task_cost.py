"""Recompute historical task costs and observable input sizes without any Host/Provider run."""

from __future__ import annotations

import hashlib
import json
import statistics
import tomllib
from collections import Counter
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
LEDGER = LAB / "studies/active/MILA_V02_PAYLOAD_FIDELITY_RESULTS.json"
EXPECTED = "9bfa7b2addd16c87a804b7435d06ad42736b39f88a46c696276f23598814c256"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def command_rows(events: list[dict]) -> list[dict]:
    rows = []
    for event in events:
        item = event.get("item", {})
        if event.get("type") != "item.completed" or item.get("type") != "command_execution":
            continue
        output = item.get("aggregated_output", "").encode()
        missing = next((name for name in ("python3", "python", "jq")
                        if f"{name}: command not found".encode() in output), None)
        rows.append({"id": item["id"], "exit_code": item.get("exit_code"),
                     "command_sha256": sha(item.get("command", "").encode()),
                     "output_bytes": len(output), "output_sha256": sha(output),
                     "missing_program": missing})
    return rows


def main() -> None:
    assert sha(LEDGER.read_bytes()) == EXPECTED, "Historical ledger identity changed"
    ledger = json.loads(LEDGER.read_text())
    sessions = []
    for a in ledger["allocations"]:
        if not a["model_started"]:
            continue
        directory = LAB / a["artifact"]
        events = [json.loads(line) for line in
                  (directory / "events.jsonl").read_text().splitlines()]
        usage = [e["usage"] for e in events if e.get("type") == "turn.completed"]
        assert sum(u["input_tokens"] + u["output_tokens"] for u in usage) == a["tokens"]
        commands = command_rows(events)
        counts = Counter(c["output_sha256"] for c in commands if c["output_bytes"])
        repeated = [{"sha256": digest, "occurrences": count,
                     "bytes_each": next(c["output_bytes"] for c in commands
                                        if c["output_sha256"] == digest)}
                    for digest, count in counts.items() if count > 1]
        workspace = Path(json.loads((directory / "host-paths.json").read_text())["workspace"])
        profile = tomllib.loads((directory / "host-profile.toml").read_text())
        catalog = json.loads((directory / "tool-catalog.json").read_text())
        model = json.loads((directory / "model-catalog-identity.json").read_text())[
            "selected_metadata"]
        host_config = tomllib.loads((directory / "host-config.toml").read_text())
        sessions.append({"allocation_id": a["allocation_id"], "arm": a["arm"],
            "raw_tokens": a["tokens"], "input_tokens": a["input_tokens"],
            "cached_input_tokens": a["cached_input_tokens"],
            "uncached_input_tokens": a["input_tokens"] - a["cached_input_tokens"],
            "output_tokens": a["output_tokens"], "online_seconds": a["operational_online_seconds"],
            "turn_completed_records": len(usage), "provider_request_count": None,
            "commands": commands, "repeated_command_outputs": repeated,
            "command_output_bytes_total": sum(c["output_bytes"] for c in commands),
            "readable_fixed_components": {
                "user_prompt_bytes": (directory / "user-prompt.txt").stat().st_size,
                "developer_instructions_bytes": len(profile["developer_instructions"].encode()),
                "mcp_instructions_bytes": len(catalog["instructions"].encode()),
                "mcp_tool_schema_json_bytes": json_bytes(catalog["tools"]["tools"]),
                "mcp_tools": len(catalog["tools"]["tools"]),
                "model_message_catalog_bytes": [json_bytes(m.get("model_messages")) for m in model],
                "model_message_component_bytes": [{k: len(v.encode()) if isinstance(v, str)
                                                   else json_bytes(v)
                                                   for k, v in m["model_messages"].items()}
                                                  for m in model],
                "model_catalog_context_window": [m.get("context_window") for m in model],
                "model_catalog_truncation_policy": [m.get("truncation_policy") for m in model],
                "configured_tool_output_token_limit": host_config.get("tool_output_token_limit"),
                "rollout_budget": host_config["features"]["rollout_budget"],
                "actual_initial_provider_tokens": None},
            "workspace_files": [{"path": str(p.relative_to(workspace)), "bytes": p.stat().st_size,
                                 "sha256": sha(p.read_bytes())}
                                for p in sorted(workspace.rglob("*"))
                                if p.is_file() and not p.is_symlink()],
            "events_sha256": sha((directory / "events.jsonl").read_bytes())})
    groups = {}
    for arm in ("G", "F", "S"):
        subset = [s for s in sessions if s["arm"] == arm]
        groups[arm] = {"sessions": len(subset),
            **{key: {"sum": sum(s[key] for s in subset),
                     "mean": statistics.mean(s[key] for s in subset),
                     "min": min(s[key] for s in subset), "max": max(s[key] for s in subset)}
               for key in ("raw_tokens", "uncached_input_tokens", "output_tokens",
                           "online_seconds")}}
    failures = Counter(c["missing_program"] or "OTHER" for s in sessions if s["arm"] != "G"
                       for c in s["commands"] if c["exit_code"] != 0)
    result = {"status": "READ_ONLY_AUDIT_COMPLETE", "historical_ledger_sha256": EXPECTED,
        "historical_allocations": len(ledger["allocations"]), "actual_sessions": len(sessions),
        "historical_raw_tokens": sum(s["raw_tokens"] for s in sessions),
        "groups": groups, "followup_nonzero_exit_counts": dict(failures), "sessions": sessions,
        "new_model_allocations": 0, "new_model_tokens": 0, "actual_currency_cost": None,
        "fixed_components_are_bytes_not_provider_tokens": True,
        "overlapping_config_components_must_not_be_summed_as_prompt": True,
        "later_model_inputs": "UNOBSERVED", "cost_attribution_to_failed_commands": None}
    target = LAB / "artifacts/v02-cost-first/run-20260906a/cost-audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"historical_raw_tokens": result["historical_raw_tokens"],
                      "groups": groups, "failures": failures}))


if __name__ == "__main__":
    main()
