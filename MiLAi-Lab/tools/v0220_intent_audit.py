"""Evaluator-only exact-intent and actual-effect audit. Never imported by the actor."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from v02_local_provider import accounting, read_events
from v0213_provider import payload
from v0218_world import World, digest
from v0220_evidence import read, sha
from v0220_session import SessionContract, system_for


def effects(spec: dict, initial: dict, final: dict, ledger: list, turns: list) -> dict:
    """Reconstruct requested state transitions independently of World.act."""
    wanted = spec["actions"]
    business = [
        r
        for r in turns
        if r.get("action", {}).get("action") in {"put_record", "request_clarification"}
    ]
    accepted = [r for r in business if r["response"].get("committed") is True]
    faithful = [r["action"] for r in business] == wanted
    checks = {
        "initial_frozen": digest(initial) == spec["initial_state_sha256"],
        "intent_fidelity": faithful,
        "all_first_submissions_accepted": len(accepted) == len(wanted) == len(business),
        "no_protocol_rejections": not any(
            r["response"]["status"] == "ACTION_REJECTED" for r in turns
        ),
        "no_unknown_commit": not any(r["response"]["status"] == "COMMIT_UNKNOWN" for r in turns),
        "exact_effect_count": len(ledger) == len(wanted),
        "scope_preserved": initial["scope"] == final["scope"] == spec["scope"],
        "finished": bool(turns) and turns[-1]["response"]["status"] == "SESSION_FINISHED",
    }
    replay = copy.deepcopy(initial)
    expected_ledger = []
    for index, action in enumerate(wanted):
        args = action["arguments"]
        before = digest(replay)
        replay["records"][args["object_id"]] = {"object_id": args["object_id"], **args["data"]}
        replay["pending"].pop(args["object_id"], None)
        replay["version"] += 1
        replay["history"].append(
            {
                "kind": "business_action",
                "action": "put_record",
                "object_id": args["object_id"],
                "data": args["data"],
            }
        )
        if index < len(accepted):
            turn = accepted[index]
            operation = f"{spec['id']}:{turn['turn']:02d}"
            receipt = {
                "status": "ACTION_EXECUTED_LOCAL_WORLD",
                "operation_id": operation,
                "version": replay["version"],
                "object_id": args["object_id"],
                "action": "put_record",
                "before_sha256": before,
                "after_sha256": digest(replay),
            }
            request = {
                "operation_id": operation,
                "scope": spec["scope"],
                "action": "put_record",
                **args,
            }
            expected_ledger.append(
                {"request": request, "receipt": receipt, "snapshot": copy.deepcopy(replay)}
            )
            checks[f"receipt_{index}"] = turn["response"] == {
                **receipt,
                "committed": True,
                "version_domain": "WORLD",
                "request_sha256": digest(request),
                "business_effect": True,
                "retry_requires": "NONE",
            }
    checks["independent_effect_replay"] = final == replay and ledger == expected_ledger
    last_write = max([r["turn"] for r in accepted], default=0)
    reads = [
        r
        for r in turns
        if r.get("action") == {"action": "read", "arguments": {"resource": "records"}}
        and r["turn"] > last_write
    ]
    checks["post_commit_public_readback"] = bool(reads) and all(
        r["response"]["content"] == final["records"]
        and r["response"]["content_sha256"] == digest(final["records"])
        and r["response"]["version"] == final["version"]
        for r in reads
    )
    for r in turns:
        if r not in accepted:
            checks[f"no_hidden_effect_turn_{r['turn']}"] = r["before_sha256"] == r["after_sha256"]
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "business_attempts": len(business),
        "first_accepted": len(accepted),
        "effects": len(ledger),
        "intent_profile": "INTENT_ORACLE_NOT_NATURAL_TASK",
    }


def audit(root: Path, spec: dict) -> dict:
    directory = root / "episodes" / spec["id"]
    world = World(root / "worlds" / f"{spec['id']}.sqlite", spec["scope"])
    initial, final = read(directory / "initial-world.json"), world.snapshot()
    turns = [read(p) for p in sorted(directory.glob("turn-*.json"))]
    result = effects(spec, initial, final, world.ledger(), turns)
    checks = result["checks"]
    checks["saved_final_matches_sqlite"] = read(directory / "final-world.json") == final
    checks["saved_ledger_matches_sqlite"] = read(directory / "final-ledger.json") == world.ledger()
    worker = read(directory / "worker-result.json")
    events = read_events(directory / "provider-ledger.jsonl")
    cost = accounting(events)
    checks["settled_bounded_cost"] = (
        0 < cost["requests"] <= 4
        and not cost["pending"]
        and not cost["violations"]
        and cost == worker["cost"]
        and cost["requests"] == len(turns)
    )
    checks["worker_finished"] = worker["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    checks["no_unresolved_operation"] = worker["unresolved_operations"] == []
    presentation = read(directory / "initial-presentation.json")
    contract = SessionContract.from_public(initial)
    checks["full_contract_presented"] = presentation["contract"] == contract.documents()
    checks["only_authorized_intent"] = presentation["authorized_intent"] == spec["intent"]
    checks["no_inherited_note"] = presentation["inherited_note"] is None
    checks["full_public_sources"] = all(
        o["content"] == initial[o["resource"]]
        and o["version"] == initial["version"]
        and o["content_sha256"] == digest(o["content"])
        for o in presentation["observations"]
    ) and {o["resource"] for o in presentation["observations"]} == {
        "task",
        "policy",
        "current",
        "history",
        "records",
        "pending",
    }
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
    reserved = [e for e in events if e["event"] == "RESERVED"]
    settled = {e["request_id"]: e for e in events if e["event"] == "SETTLED"}
    for row, reservation in zip(turns, reserved, strict=False):
        turn, request_id = row["turn"], reservation["request_id"]
        expected = payload(
            [
                *messages,
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "remaining_generation_opportunities": 5 - turn,
                            "final_delivery_reservation": 1,
                            "last_completed_public_observation": last,
                        }
                    ),
                },
            ],
            contract.action_schema(finish_only=turn == 4),
        )
        path = directory / f"{request_id}-request.json"
        body = read(path)
        checks[f"exact_http_input_{turn}"] = (
            body == expected and sha(path) == reservation["payload_sha256"]
        )
        http = read(directory / f"{request_id}-http.json")
        response = json.loads(http["body"])
        checks[f"actual_http_output_usage_{turn}"] = (
            http["status_code"] == 200
            and response["choices"][0]["message"]["content"] == row["raw"]
            and response["usage"] == settled.get(request_id, {}).get("usage")
            and read(directory / f"{request_id}-tokenize.json")["count"]
            == response["usage"]["prompt_tokens"]
        )
        checks[f"decode_and_schema_{turn}"] = contract.decode(
            row["raw"], finish_only=turn == 4
        ) == row.get("action")
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
    result.update(status="PASS" if all(checks.values()) else "FAIL", cost=cost, pid=worker["pid"])
    return result
