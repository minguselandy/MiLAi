"""Compare actual saved adoption under old/all and selected-only projection.

Replays immutable embedding and adoption outputs after checking their exact
inputs. Generates one next response per branch; never executes business actions.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from milai_lab.methods.experience_revision import ExperienceRevisionSession
from milai_lab.methods.reasoning_bank import BankConfig, ExperienceBank
from reasoningbank_provider import NativeProvider
from replay_v0213_cost import save, sha
from run_reasoningbank_lifelong import save_source_binding
from v02_local_provider import accounting, read_events


def load(path):
    return json.loads(Path(path).read_text())


def reconstruct(config, task_id, policies):
    old = Path(config["prior_run"])
    ledger = read_events(old / "provider/provider-ledger.jsonl")
    events = [
        e for e in ledger if e.get("session") == f"db_bench:{task_id}" and e["event"] == "SETTLED"
    ]
    actor_id = next(e["request_id"] for e in events if e["role"] == "actor")
    old_request = load(old / f"provider/{actor_id}-request.json")
    marker = "Auxiliary memory interface:"
    old_system = old_request["messages"][0]["content"]
    if marker not in old_system:
        raise ValueError("SAVED_ACTOR_MEMORY_INTERFACE_MISSING")
    saved_interface = marker + old_system.split(marker, 1)[1]
    adopted = [e["request_id"] for e in events if e["role"] == "adopt"]
    embedding_id = next(
        e["request_id"]
        for e in read_events(old / "embedding/embedding-ledger.jsonl")
        if e.get("session") == f"db_bench:{task_id}" and e["event"] == "SETTLED"
    )
    embedding_request = load(old / f"embedding/{embedding_id}-request.json")
    embedding_reply = json.loads(load(old / f"embedding/{embedding_id}-http.json")["body"])
    vectors = [
        row["embedding"] for row in sorted(embedding_reply["data"], key=lambda r: r["index"])
    ]
    query = embedding_request["input"][0]
    saved = load(config["support_bank"])
    # This is a noncommitting replay of an old bank for an implementation
    # diagnostic, not a newly formed v0.5 bank or a fresh held-out task.
    saved["scope"]["method_version"] = ExperienceRevisionSession.method_version
    bank_config = BankConfig(**load(old / "config.json").get("bank_config", {}))
    outputs = {}
    for mode in ("legacy_all", "selected"):
        remaining = iter(adopted)
        consumed = []

        def generate(call, remaining=remaining, consumed=consumed):
            request_id = next(remaining)
            prior = load(old / f"provider/{request_id}-request.json")
            if list(call.messages) != prior["messages"] or call.role != "adopt":
                raise ValueError(f"ADOPTION_PREFIX_MISMATCH:{task_id}:{request_id}")
            consumed.append(request_id)
            return load(old / f"provider/{request_id}-message.json")["content"]

        def embed(texts):
            if texts != embedding_request["input"]:
                raise ValueError(f"EMBEDDING_PREFIX_MISMATCH:{task_id}")
            return copy.deepcopy(vectors)

        bank = ExperienceBank.restore(saved, scope=saved["scope"], contract=saved["contract"])
        memory = ExperienceRevisionSession(
            bank=bank,
            config=bank_config,
            policies=policies,
            generate=generate,
            embed=embed,
            projection_mode=mode,
        )
        memory.start(f"db_bench:{task_id}", query)
        if consumed != adopted:
            raise ValueError(f"INCOMPLETE_ADOPTION_REPLAY:{task_id}")
        context = memory.memory_context()
        if context:
            context += "\n\n" + saved_interface
        messages = copy.deepcopy(old_request["messages"])
        # The native system prompt is the same for this frozen DB adapter.
        messages[0]["content"] = "You are a helpful assistant." + (
            "\n\n" + context if context else ""
        )
        if mode == "legacy_all" and messages != old_request["messages"]:
            raise ValueError(f"ORIGINAL_ACTOR_INPUT_MISMATCH:{task_id}")
        outputs[mode] = {
            "messages": messages,
            "selected_refs": memory.workspace.frame.selected_refs,
            "retrieved": memory.selected,
            "projected_versions": dict(memory._projected_versions),
            "input_sha256": sha(json.dumps(messages, ensure_ascii=False).encode()),
        }
    return {
        "id": task_id,
        "prior_actor_request": str(old / f"provider/{actor_id}-request.json"),
        "prefix_checked": True,
        "branches": outputs,
    }


def execute(config):
    root = Path(config["output_root"])
    root.mkdir(parents=True, exist_ok=False)
    save(root / "config.json", config)
    lab = Path(__file__).resolve().parents[1]
    save_source_binding(root, lab, config)
    policies = {p.stem: p.read_text() for p in Path(config["prior_policy_root"]).glob("*.txt")}
    cases = [reconstruct(config, task_id, policies) for task_id in config["ids"]]
    save(root / "reconstructed-inputs.json", cases)
    if config.get("check_only"):
        return {"status": "PREFIX_REPLAY_PASS", "cases": len(cases), "generations": 0}
    provider = NativeProvider(
        root / "provider",
        max_tokens=config["max_tokens"],
        max_requests=config["max_requests"],
        deadline=time.monotonic() + config["wall_seconds"],
    )
    provider.verify()
    try:
        for index, case in enumerate(cases):
            modes = ("legacy_all", "selected") if index % 2 == 0 else ("selected", "legacy_all")
            for mode in modes:
                branch = case["branches"][mode]
                branch["response"] = provider.generate_message(
                    f"projection:{case['id']}:{mode}", branch["messages"]
                )
                save(root / f"case-{case['id']}-{mode}.json", {"id": case["id"], **branch})
    finally:
        save(root / "usage.json", accounting(read_events(provider.ledger)))
        provider.client.close()
    result = {
        "status": "NEXT_RESPONSE_DIAGNOSTIC_COMPLETE",
        "cases": cases,
        "business_actions": 0,
        "native_outcomes": None,
        "interpretation": "Shared-prefix next responses only; no business execution or score.",
    }
    save(root / "result.json", result)
    return {"status": result["status"], "cases": len(cases)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    print(json.dumps(execute(load(args.config)), ensure_ascii=False))
