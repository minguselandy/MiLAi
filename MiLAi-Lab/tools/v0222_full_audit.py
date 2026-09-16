"""Independent full-contract/intent/SQLite auditor; never imported by the actor."""

from __future__ import annotations

import json
from pathlib import Path

from v02_local_provider import read_events
from v0213_provider import TOKENIZE_KEYS, payload
from v0218_world import World, digest
from v0220_evidence import read, sha
from v0220_intent_audit import effects
from v0220_provider_hardened import usage_state
from v0220_session import SessionContract, system_for
from v0220_wire_contract import fingerprint
from v0222_diagnostic import differences
from v0222_full_provider import resolved_spec
from v0222_http import strict_http_json
from v0222_string_contract import compile_contract


def audit(batch, episode: str) -> dict:
    root, spec = batch.root, resolved_spec(batch, episode)
    directory = root / "episodes" / episode
    provider = directory / "provider"
    worker = read(directory / "worker-result.json")
    events = read_events(provider / "provider-ledger-v2.jsonl")
    cost = usage_state(events)
    reserved = [e for e in events if e["event"] == "RESERVED"]
    known = {e["request_id"]: e["usage"] for e in events if e["event"] == "USAGE_KNOWN"}
    bindings = [read(p) for p in provider.glob("contract-*-binding.json")]
    checks = {
        "known_bounded_cost": cost["new_generation_allowed"]
        and 0 < cost["requests"] <= (1 if spec["stage"] == "P3" else 4),
        "no_note": not list(directory.glob("note-*.json")),
        "one_binding_per_generation": len(bindings) == len(reserved),
    }
    originals, outputs = [], []
    for i, event in enumerate(reserved, 1):
        key = event["request_id"]
        request = provider / (key + "-request.json")
        wire = read(request)
        matches = [b for b in bindings if b["wire_request_sha256"] == fingerprint(wire)]
        if len(matches) != 1:
            raise ValueError("CANONICAL_BINDING_NOT_UNIQUE")
        binding = matches[0]
        original = binding["original_request"]
        compiled = compile_contract(original["response_format"]["json_schema"]["schema"], "D11")
        http = read(provider / (key + "-http.json"))
        response = strict_http_json(http["body"])
        raw = response["choices"][0]["message"]["content"]
        tokenize_http = read(provider / (key + "-tokenize-http.json"))
        tokenized = strict_http_json(tokenize_http["body"])
        checks[f"actual_tokenize_input_and_receipt_{i}"] = (
            tokenize_http["status_code"] == 200
            and fingerprint(read(provider / (key + "-tokenize-request.json")))
            == fingerprint({k: wire[k] for k in TOKENIZE_KEYS})
            and type(tokenized["count"]) is int
            and tokenized["count"] == event["prompt_tokens"]
        )
        checks[f"exact_wire_and_compiler_{i}"] = (
            fingerprint(compiled.prepare(original)) == fingerprint(wire)
            and sha(request) == event["payload_sha256"] == fingerprint(wire)
            and binding["prompt_diff"] == compiled.prompt_diff(original)
            and all(binding[k] == v for k, v in compiled.manifest().items())
        )
        checks[f"raw_trace_usage_{i}"] = (
            http["status_code"] == 200
            and http["client_request_id"] == key
            and http["request_wire_sha256"] == sha(request)
            and isinstance(response.get("id"), str)
            and bool(response["id"])
            and response["usage"] == known.get(key)
            and response["usage"]["prompt_tokens"]
            == tokenized["count"]
            == read(provider / (key + "-tokenize.json"))["count"]
            and read(provider / (key + "-visible.json"))["content"] == raw
        )
        compiled.validate_output(raw)
        originals.append(original)
        outputs.append(raw)
    if spec["stage"] == "P3":
        reference = next(r for r in batch.references("P3") if r["episode"] == episode)
        checks["one_validate_only_request"] = len(reserved) == 1
        checks["exact_frozen_presentation"] = fingerprint(originals) == fingerprint(
            [read(Path(reference["canonical"]))]
        )
        checks["full_intent_fidelity"] = spec["variant"] == "finish" or not differences(
            spec["expected"], json.loads(outputs[0])
        )
        checks["no_business_world_or_dispatch"] = (
            worker["business_dispatches"] == 0
            and not (root / "worlds" / (episode + ".sqlite")).exists()
        )
        checks["worker_status"] = worker["status"] == "VALIDATE_ONLY_PASS"
    else:
        world = World(root / "worlds" / (episode + ".sqlite"), spec["scope"])
        initial, final = read(directory / "initial-world.json"), world.snapshot()
        turns = [read(path) for path in sorted(directory.glob("turn-*.json"))]
        checks.update(effects(spec, initial, final, world.ledger(), turns)["checks"])
        checks["saved_SQLite_and_ledger_match"] = (
            read(directory / "final-world.json") == final
            and read(directory / "final-ledger.json") == world.ledger()
        )
        checks["raw_turns_one_to_one"] = outputs == [r["raw"] for r in turns]
        checks["worker_status"] = worker["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
        checks["no_unknown_commit"] = worker["unresolved_operations"] == []
        presentation = read(directory / "initial-presentation.json")
        contract = SessionContract.from_public(initial)
        checks["raw_actions_independently_decoded"] = all(
            fingerprint(contract.decode(turn["raw"])) == fingerprint(turn["action"])
            for turn in turns
        )
        raw_business = [
            contract.decode(turn["raw"])
            for turn in turns
            if contract.decode(turn["raw"])["action"] in {"put_record", "request_clarification"}
        ]
        checks["raw_business_intent_fidelity"] = not differences(spec["actions"], raw_business)
        checks["full_public_presentation"] = (
            presentation["contract"] == contract.documents()
            and presentation["authorized_intent"] == spec["intent"]
            and presentation["inherited_note"] is None
            and {o["resource"] for o in presentation["observations"]}
            == {"task", "policy", "current", "history", "records", "pending"}
            and all(o["content"] == initial[o["resource"]] for o in presentation["observations"])
        )
        messages = [
            {"role": "system", "content": system_for("INTENT_ORACLE", "ORACLE")},
            {"role": "user", "content": json.dumps(presentation, ensure_ascii=False)},
        ]
        observation = presentation["observations"][-1]
        last = {
            "version": observation["version"],
            "version_domain": "WORLD",
            "source": "PUBLIC_OBSERVATION",
            "response_sha256": digest(observation),
        }
        for i, (turn, original) in enumerate(zip(turns, originals, strict=True), 1):
            expected = payload(
                [
                    *messages,
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "remaining_generation_opportunities": 5 - i,
                                "final_delivery_reservation": 1,
                                "last_completed_public_observation": last,
                            }
                        ),
                    },
                ],
                contract.action_schema(finish_only=i == 4),
            )
            checks[f"actual_session_request_rebuilt_{i}"] = fingerprint(original) == fingerprint(
                expected
            )
            reply = turn["response"]
            if reply["status"] in {"PUBLIC_OBSERVATION", "ACTION_EXECUTED_LOCAL_WORLD"}:
                last = {
                    "version": reply["version"],
                    "version_domain": "WORLD",
                    "source": reply["status"],
                    "response_sha256": digest(reply),
                }
            messages.extend(
                [
                    {"role": "assistant", "content": turn["raw"]},
                    {"role": "user", "content": json.dumps({"tool_result": reply})},
                ]
            )
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "cost": cost,
        "pid": worker["pid"],
        "stage": spec["stage"],
        "episode": episode,
    }
