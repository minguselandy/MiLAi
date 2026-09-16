"""Two next-action generations from one actual memory-bearing Actor input.

Both branches see identical experience, notes, facts, native history and tools.
Only the candidate consumption instruction is replaced by ordinary consumption.
No business or memory action is executed; this cannot establish outcome benefit.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from reasoningbank_provider import NativeProvider
from replay_v0213_cost import save, sha
from v02_local_provider import accounting, read_events

ORDINARY = (
    "Use the supplied experience and working notes as fallible reference material. "
    "Decide whether they apply to the current task and the actual observations. "
    "Read published source material when needed. Follow the original native task, "
    "tool and final-answer format."
)


def action_value(message):
    return {
        "content": message.get("content"),
        "tool_calls": [
            {"name": call["function"]["name"],
             "arguments": json.loads(call["function"]["arguments"])}
            for call in message.get("tool_calls", [])
        ],
    }


def run(config: dict) -> None:
    root = Path(config["output_root"])
    root.mkdir(parents=True, exist_ok=False)
    save(root / "config.json", config)
    provider = NativeProvider(
        root / "provider", max_tokens=config["max_tokens"], max_requests=config["max_requests"],
        deadline=time.monotonic() + config["wall_seconds"], tool_transport="template_completion",
    )
    try:
        provider.verify()
        policy = Path(config["candidate_actor_policy"]).read_text().strip()
        if sha(policy.encode()) != config["candidate_actor_policy_sha256"]:
            raise ValueError("CONSUMPTION_POLICY_CHANGED")
        rows = []
        for entry in config["inputs"]:
            source = Path(entry["request"])
            if not source.exists():
                rows.append({"id": entry["id"], "status": "MISSING_ACTUAL_INPUT"})
                continue
            original = json.loads(source.read_text())
            if policy not in original["messages"][0]["content"]:
                rows.append({"id": entry["id"], "status": "NO_CANDIDATE_CONSUMPTION_INSTRUCTION"})
                continue
            branches = {}
            for name in ("candidate", "ordinary"):
                messages = copy.deepcopy(original["messages"])
                if name == "ordinary":
                    messages[0]["content"] = messages[0]["content"].replace(policy, ORDINARY, 1)
                branches[name] = provider.generate_message(
                    entry["id"] + "/" + name, messages, tools=original.get("tools")
                )
            rows.append({
                "id": entry["id"], "status": "COMPLETED", "source_request": str(source),
                "source_sha256": sha(source.read_bytes()), "choices": branches,
                "same_action_content": (
                    action_value(branches["candidate"]) == action_value(branches["ordinary"])
                ),
                "same_declared_tool_calls": (
                    action_value(branches["candidate"])["tool_calls"]
                    == action_value(branches["ordinary"])["tool_calls"]
                ) if any(branch.get("tool_calls") for branch in branches.values()) else None,
                "executed_actions": 0,
            })
            save(root / "progress.json", rows)
        save(root / "result.json", {
            "status": "COMPLETED", "planned": len(config["inputs"]), "rows": rows,
            "executed_actions": 0, "usage": accounting(read_events(provider.ledger)),
            "interpretation": (
                "Instruction-only next-action diagnostic; no outcome counterfactual. "
                "Text differences alone do not establish different business actions."
            ),
        })
    except Exception as error:
        save(root / "failure.json", {
            "reason": str(error), "usage": accounting(read_events(provider.ledger)),
        })
        raise
    finally:
        provider.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    run(json.loads(parser.parse_args().config.read_text()))


if __name__ == "__main__":
    main()
