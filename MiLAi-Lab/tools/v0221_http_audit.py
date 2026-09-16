"""Independent canonical/wire/HTTP accounting and actual World replay audit."""

from __future__ import annotations

import json
from pathlib import Path

from v02_local_provider import read_events
from v0213_provider import payload
from v0218_world import World, digest
from v0220_evidence import read, sha
from v0220_intent_audit import effects
from v0220_provider_hardened import usage_state
from v0220_session import SessionContract, system_for
from v0220_wire_contract import compile_contract, fingerprint


def audit(root: Path, spec: dict) -> dict:
    directory = root / "episodes" / spec["id"]
    provider = directory / "provider"
    events = read_events(provider / "provider-ledger-v2.jsonl")
    cost = usage_state(events)
    reserved = [e for e in events if e["event"] == "RESERVED"]
    known = {e["request_id"]: e["usage"] for e in events if e["event"] == "USAGE_KNOWN"}
    bindings = [read(p) for p in provider.glob("contract-*-binding.json")]
    worker = read(directory / "worker-result.json")
    checks = {
        "known_bounded_cost": cost["new_generation_allowed"]
        and 0 < cost["requests"] <= (1 if spec["stage"] == "W2" else 4),
        "no_note": not list(directory.glob("note-*.json")),
    }
    originals, outputs = [], []
    for i, event in enumerate(reserved, 1):
        key = event["request_id"]
        path = provider / (key + "-request.json")
        wire = read(path)
        matches = [b for b in bindings if b["wire_request_sha256"] == fingerprint(wire)]
        checks[f"one_original_binding_{i}"] = len(matches) == 1
        if len(matches) != 1:
            raise ValueError("MISSING_CANONICAL_WIRE_BINDING")
        original = matches[0]["original_request"]
        compiled = compile_contract(original["response_format"]["json_schema"]["schema"])
        checks[f"exact_wire_{i}"] = compiled.prepare(original) == wire and (
            sha(path) == event["payload_sha256"] == fingerprint(wire)
        )
        http = read(provider / (key + "-http.json"))
        response = json.loads(http["body"])
        raw = response["choices"][0]["message"]["content"]
        checks[f"http_trace_and_usage_{i}"] = (
            http["status_code"] == 200
            and http["client_request_id"] == key
            and http["request_wire_sha256"] == sha(path)
            and isinstance(response.get("id"), str)
            and bool(response["id"])
            and response["usage"] == known.get(key)
            and response["usage"]["prompt_tokens"]
            == read(provider / (key + "-tokenize.json"))["count"]
        )
        compiled.validate_output(raw)
        originals.append(original)
        outputs.append(raw)
    if spec["stage"] == "W2":
        checks["one_validate_only_request"] = len(reserved) == 1
        checks["frozen_full_presentation"] = originals == [
            read(root / "W2-requests" / (spec["id"] + ".canonical.json"))
        ]
        checks["expected_action"] = (
            spec["variant"] == "finish" or json.loads(outputs[0]) == spec["expected"]
        )
        checks["no_business_dispatch"] = worker["business_dispatches"] == 0 and (
            not (root / "worlds" / (spec["id"] + ".sqlite")).exists()
        )
        checks["worker_success"] = worker["status"] == "VALIDATE_ONLY_PASS"
    else:
        world = World(root / "worlds" / (spec["id"] + ".sqlite"), spec["scope"])
        initial, final = read(directory / "initial-world.json"), world.snapshot()
        turns = [read(p) for p in sorted(directory.glob("turn-*.json"))]
        checks.update(effects(spec, initial, final, world.ledger(), turns)["checks"])
        checks["saved_sqlite_matches"] = read(directory / "final-world.json") == final and (
            read(directory / "final-ledger.json") == world.ledger()
        )
        checks["turn_http_one_to_one"] = outputs == [r["raw"] for r in turns]
        checks["worker_success"] = worker["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
        checks["no_unknown_commit"] = worker["unresolved_operations"] == []
        presentation = read(directory / "initial-presentation.json")
        contract = SessionContract.from_public(initial)
        checks["full_public_presentation"] = (
            presentation["contract"] == contract.documents()
            and (
                presentation["authorized_intent"] == spec["intent"]
                and presentation["inherited_note"] is None
            )
            and {o["resource"] for o in presentation["observations"]}
            == {"task", "policy", "current", "history", "records", "pending"}
        )
        checks["full_source_values"] = all(
            o["content"] == initial[o["resource"]] for o in presentation["observations"]
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
        for i, (row, original) in enumerate(zip(turns, originals, strict=True), 1):
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
            checks[f"exact_session_input_{i}"] = original == expected
            reply = row["response"]
            if reply["status"] in {"PUBLIC_OBSERVATION", "ACTION_EXECUTED_LOCAL_WORLD"}:
                last = {
                    "version": reply["version"],
                    "version_domain": "WORLD",
                    "source": reply["status"],
                    "response_sha256": digest(reply),
                }
            messages.extend(
                [
                    {"role": "assistant", "content": row["raw"]},
                    {"role": "user", "content": json.dumps({"tool_result": reply})},
                ]
            )
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "cost": cost,
        "pid": worker["pid"],
    }
