"""Independent source, presentation, raw HTTP and isolated-effect reconstruction."""

from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from prepare_v0221_http_v2 import CASES, FINISH, READBACK, W2_SYSTEM
from v02_local_provider import read_events
from v0213_provider import MODEL, TOKENIZE_KEYS, payload
from v0218_world import digest
from v0220_evidence import sha
from v0220_intent_audit import effects
from v0220_provider_hardened import ProviderStop, usage_state, valid_usage
from v0220_session import PREFETCH, SessionContract, system_for
from v0220_wire_contract import encoded, fingerprint
from v0222_diagnostic import differences
from v0222_http import strict_http_json
from v0222_presentation_contract import audit_presentation, present
from v0222_presentation_references import KINDS
from v0222_presentation_references import validate_reference as validate_local_reference
from v0222_string_contract import compile_contract


def read(path: Path):
    return strict_http_json(path.read_text(encoding="utf-8"))


def initial_for(spec: dict) -> dict:
    if spec["stage"] == "P4":
        ordered = [
            {k: action["arguments"][k] for k in ("object_id", "data")} for action in spec["actions"]
        ]
        if fingerprint(spec["intent"].get("ordered_writes")) != fingerprint(ordered):
            raise ProviderStop("WHOLE_CHAIN_INTENT_NOT_BOUND_TO_AUTHORIZED_WRITES")
    public = read(CASES / spec["root"] / "public-initial.json")
    # World stores sorted JSON; reproduce its public read representation without
    # opening a World or dispatching any reference business action.
    initial = strict_http_json(
        encoded(
            {
                **copy.deepcopy(public),
                "scope": spec["scope"],
                "version": 0,
                "records": {},
                "pending": {},
                "history": [],
            }
        )
    )
    if spec["stage"] == "P4" and digest(initial) != spec["initial_state_sha256"]:
        raise ProviderStop("SOURCE_DERIVED_INITIAL_STATE_DRIFT")
    return initial


def presentation_for(spec: dict, initial: dict) -> dict:
    contract = SessionContract.from_public(initial)
    observations = [
        {
            "resource": resource,
            "version": initial["version"],
            "content": initial[resource],
            "content_sha256": digest(initial[resource]),
            "version_domain": "WORLD",
            "committed": False,
            "status": "PUBLIC_OBSERVATION",
            "business_effect": False,
        }
        for resource in PREFETCH
    ]
    return {
        "profile": "INTENT_ORACLE",
        "contract": contract.documents(),
        "origin": "HARNESS_PUBLIC_PREFETCH",
        "observations": observations,
        "inherited_note": None,
        "authorized_intent": {"authorized_action": spec["expected"]}
        if spec["stage"] == "P3"
        else spec["intent"],
    }


def rebuild_requests(spec: dict, initial: dict, turns: list[dict]) -> list[dict]:
    presentation = presentation_for(spec, initial)
    contract = SessionContract.from_public(initial)
    messages = [
        {
            "role": "system",
            "content": W2_SYSTEM
            if spec["stage"] == "P3"
            else system_for("INTENT_ORACLE", "ORACLE"),
        },
        {"role": "user", "content": json.dumps(presentation, ensure_ascii=False)},
    ]
    if spec["stage"] == "P3":
        return [payload(messages, contract.action_schema(finish_only=spec["variant"] == "finish"))]
    observation = presentation["observations"][-1]
    last = {
        "version": observation["version"],
        "version_domain": "WORLD",
        "source": "PUBLIC_OBSERVATION",
        "response_sha256": digest(observation),
    }
    requests = []
    for i, turn in enumerate(turns, 1):
        if type(turn["turn"]) is not int or turn["turn"] != i:
            raise ProviderStop("EXACT_CONTIGUOUS_SESSION_TURNS_REQUIRED")
        requests.append(
            payload(
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
        )
        reply = turn["response"]
        contract.validate_response(reply)
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
    return requests


def world_evidence(path: Path, spec: dict) -> tuple[dict, list, dict]:
    """Read actual SQLite in read-only mode and close it, with no World helper."""
    before = sha(path)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        final = strict_http_json(
            db.execute("SELECT body FROM state WHERE singleton=1").fetchone()[0]
        )
        ledger = [
            strict_http_json(r[0])
            for r in db.execute("SELECT event FROM ledger ORDER BY sequence").fetchall()
        ]
        operations = db.execute(
            "SELECT id,request_hash,receipt FROM operations ORDER BY id"
        ).fetchall()
        dispatch = db.execute(
            "SELECT id,request,receipt FROM v0220_dispatch ORDER BY id"
        ).fetchall()
    expected_operations = sorted(
        [(e["request"]["operation_id"], digest(e["request"]), e["receipt"]) for e in ledger]
    )
    decoded_operations = [(i, h, strict_http_json(r)) for i, h, r in operations]
    expected_dispatch = sorted(
        [
            (
                e["request"]["operation_id"],
                e["request"],
                {
                    **e["receipt"],
                    "committed": True,
                    "version_domain": "WORLD",
                    "request_sha256": digest(e["request"]),
                    "business_effect": True,
                    "retry_requires": "NONE",
                },
            )
            for e in ledger
        ]
    )
    decoded_dispatch = [
        (i, strict_http_json(q), strict_http_json(r) if r is not None else None)
        for i, q, r in dispatch
    ]
    checks = {
        "SQL_integrity": integrity,
        "SQL_read_only_hash_stable": sha(path) == before,
        "SQL_scope": final["scope"] == spec["scope"],
        "SQL_operations": fingerprint(decoded_operations) == fingerprint(expected_operations),
        "SQL_dispatch_receipts": fingerprint(decoded_dispatch) == fingerprint(expected_dispatch),
        "SQL_no_unknown_dispatch": all(r is not None for _, _, r in dispatch),
    }
    return final, ledger, checks


def public_trajectory(initial: dict, ledger: list, turns: list) -> bool:
    """Rebuild every public reply from actual committed prefixes, not saved replies."""
    state, committed = initial, {}
    position = 0
    for row in turns:
        if row["before_sha256"] != digest(state):
            return False
        action, args = row["action"]["action"], row["action"]["arguments"]
        if action == "put_record":
            if position >= len(ledger):
                return False
            event = ledger[position]
            position += 1
            state = event["snapshot"]
            reply = {
                **event["receipt"],
                "committed": True,
                "version_domain": "WORLD",
                "request_sha256": digest(event["request"]),
                "business_effect": True,
                "retry_requires": "NONE",
            }
            committed[event["request"]["operation_id"]] = reply
        elif action == "read":
            resource = args["resource"]
            reply = {
                "resource": resource,
                "version": state["version"],
                "content": state[resource],
                "content_sha256": digest(state[resource]),
                "version_domain": "WORLD",
                "committed": False,
                "status": "PUBLIC_OBSERVATION",
                "business_effect": False,
            }
        elif action == "operation_status":
            operation = args["operation_id"]
            reply = committed.get(
                operation,
                {
                    "status": "NOT_OBSERVED",
                    "committed": None,
                    "operation_id": operation,
                    "version_domain": "WORLD",
                    "retry_requires": "QUERY_OR_EXACT_REPLAY_ONLY",
                },
            )
        elif action == "finish":
            reply = {
                "version_domain": "SESSION",
                "committed": False,
                "business_effect": False,
                "task_outcome": "NOT_EVALUATED",
                "status": "SESSION_FINISHED",
            }
        else:
            return False
        if (
            row["dispatch_attempted"] is not True
            or row["after_sha256"] != digest(state)
            or fingerprint(row["response"]) != fingerprint(reply)
        ):
            return False
    return position == len(ledger)


def validate_reference(batch, reference: dict, spec: dict) -> tuple[dict, dict, dict, str]:
    turn = reference.get("turn")
    if (
        reference.get("stage") != spec["stage"]
        or reference.get("episode") != spec["id"]
        or type(turn) is not int
        or not 1 <= turn <= (1 if spec["stage"] == "P3" else len(spec["actions"]) + 2)
    ):
        raise ProviderStop("REFERENCE_SPEC_POSITION_DRIFT")
    directory = batch.root / "full-reference" / spec["stage"] / spec["id"]
    for kind in KINDS:
        expected = directory / f"request-{turn:02d}.{kind}.json"
        if Path(reference[kind]).resolve() != expected.resolve():
            raise ProviderStop("REFERENCE_PATH_OUTSIDE_EXACT_POSITION")
        read(expected)  # Strict parse before the local layer validator.
    original, presented, wire, raw = validate_local_reference(reference)
    initial = initial_for(spec)
    turns = (
        []
        if spec["stage"] == "P3"
        else [read(p) for p in sorted((directory / "session").glob("turn-*.json"))]
    )
    if spec["stage"] == "P4":
        final, ledger, checks = world_evidence(directory / "world.sqlite", spec)
        checks.update(effects(spec, initial, final, ledger, turns)["checks"])
        checks["complete_actual_public_replies"] = public_trajectory(initial, ledger, turns)
        if not all(checks.values()) or len(turns) != len(spec["actions"]) + 2:
            raise ProviderStop("COMPLETE_REFERENCE_SQL_TRAJECTORY_NOT_PROVEN")
        contract = SessionContract.from_public(initial)
        expected_actions = [*spec["actions"], READBACK, FINISH]
        for i, (row, expected_action) in enumerate(zip(turns, expected_actions, strict=True), 1):
            decoded = contract.decode(row["raw"], finish_only=i == 4)
            if fingerprint(decoded) != fingerprint(expected_action) or fingerprint(
                decoded
            ) != fingerprint(row["action"]):
                raise ProviderStop("REFERENCE_RAW_ACTION_TRAJECTORY_DRIFT")
        expected_output = [*spec["actions"], READBACK, FINISH][turn - 1]
    else:
        expected_output = spec["expected"]
    expected_request = rebuild_requests(spec, initial, turns)[turn - 1]
    if fingerprint(original) != fingerprint(expected_request):
        raise ProviderStop("REFERENCE_ORIGINAL_NOT_REBUILT_FROM_COMPLETE_PUBLIC_SOURCE")
    if fingerprint(strict_http_json(raw)) != fingerprint(expected_output):
        raise ProviderStop("REFERENCE_OUTPUT_NOT_ORIGINAL_COMPLETE_AUTHORIZED_ACTION")
    return original, presented, wire, raw


def verify_identity(directory: Path, expected: dict) -> set[Path]:
    files, values = set(), {}
    for name, route in (("models", "/v1/models"), ("version", "/version")):
        attempt, receipt = directory / (name + "-attempt.json"), directory / (name + ".json")
        if read(attempt) != {"method": "GET", "route": route}:
            raise ProviderStop("IDENTITY_ACTUAL_ATTEMPT_DRIFT")
        envelope = read(receipt)
        if envelope["status_code"] != 200:
            raise ProviderStop("IDENTITY_HTTP_200_REQUIRED")
        values[name] = strict_http_json(envelope["body"])
        files.update((attempt, receipt))
    models = values["models"]["data"]
    if (
        len(models) != 1
        or models[0]["id"] != expected["model"]
        or type(models[0].get("max_model_len")) is not int
        or models[0]["max_model_len"] != expected["context"]
        or values["version"]["version"] != expected["version"]
    ):
        raise ProviderStop("ACTUAL_HTTP_IDENTITY_DRIFT")
    return files


def validate_preflight(batch, value: dict, stage: str) -> None:
    if stage not in {"P3", "P4"}:
        raise ProviderStop("COMPLETE_ACTUAL_PREFLIGHT_REQUIRED")
    refs = batch.references(stage)
    expected_positions = [
        (spec["id"], turn)
        for spec in batch.plan[stage]
        for turn in range(1, 2 if stage == "P3" else len(spec["actions"]) + 3)
    ]
    if (
        value.get("status") != "G_PREFLIGHT_PASS"
        or value.get("stage") != stage
        or value.get("reason") is not None
        or value.get("model_requests") != 0
        or len(value.get("rows", [])) != len(refs)
        or [(r["episode"], r["turn"]) for r in refs] != expected_positions
    ):
        raise ProviderStop("COMPLETE_ACTUAL_PREFLIGHT_REQUIRED")
    directory = batch.root / (stage + "-preflight")
    files = verify_identity(directory / "identity-start", batch.plan["http_identity"])
    files |= verify_identity(directory / "identity-final", batch.plan["http_identity"])
    calls = []
    for row, reference in zip(value["rows"], refs, strict=True):
        spec = batch.spec(reference["episode"])
        _, _, wire, raw = validate_reference(batch, reference, spec)
        counts = {}
        for kind, body in (
            ("input", {k: wire[k] for k in TOKENIZE_KEYS}),
            ("output", {"model": MODEL, "prompt": raw, "add_special_tokens": False}),
        ):
            stem = directory / f"{reference['episode']}-{reference['turn']:02d}-{kind}"
            request_path, attempt_path, http_path = (
                stem.with_suffix("." + suffix + ".json")
                for suffix in ("request", "attempt", "http")
            )
            attempt = {
                "episode": reference["episode"],
                "turn": reference["turn"],
                "kind": kind,
                "method": "POST",
                "route": "/tokenize",
            }
            if (
                fingerprint(read(request_path)) != fingerprint(body)
                or read(attempt_path) != attempt
            ):
                raise ProviderStop("PREFLIGHT_ACTUAL_REQUEST_OR_ATTEMPT_DRIFT")
            receipt = read(http_path)
            count = strict_http_json(receipt["body"])["count"]
            if receipt["status_code"] != 200 or type(count) is not int or count < 0:
                raise ProviderStop("PREFLIGHT_HTTP_OR_STRICT_COUNT_INVALID")
            counts[kind] = count
            calls.append(attempt)
            files.update((request_path, attempt_path, http_path))
        if counts["input"] + 4096 > 65536 or counts["output"] + 1 > 4096:
            raise ProviderStop("COMPLETE_INPUT_OR_OUTPUT_CAPACITY_NOT_MET")
        if fingerprint(row) != fingerprint(
            {
                "episode": reference["episode"],
                "turn": reference["turn"],
                "counts": counts,
                "reference_hashes": reference["hashes"],
            }
        ):
            raise ProviderStop("PREFLIGHT_ROWS_NOT_RECOMPUTED_FROM_RAW")
    wanted_files = {str(p): sha(p) for p in files}
    observed_files = set(directory.rglob("*.json")) - {directory / "result.json"}
    if observed_files != files:
        raise ProviderStop("UNACCOUNTED_PREFLIGHT_EVIDENCE_FILES")
    if fingerprint(value.get("tokenize_calls")) != fingerprint(calls) or fingerprint(
        value.get("files")
    ) != fingerprint(wanted_files):
        raise ProviderStop("PREFLIGHT_COMPLETE_RECEIPT_BINDING_REQUIRED")


def audit_episode(batch, episode: str) -> dict:
    spec = batch.spec(episode)
    directory = batch.root / "episodes" / episode
    provider = directory / "provider"
    worker = read(directory / "worker-result.json")
    events = read_events(provider / "provider-ledger-v2.jsonl")
    cost = usage_state(events)
    reserved = [e for e in events if e["event"] == "RESERVED"]
    known = [e for e in events if e["event"] == "USAGE_KNOWN"]
    limit = 1 if spec["stage"] == "P3" else 4
    if (
        not cost["new_generation_allowed"]
        or not 0 < len(reserved) <= limit
        or len(known) != len(reserved)
    ):
        raise ProviderStop("COMPLETE_KNOWN_BOUNDED_EPISODE_COST_REQUIRED")
    initial = initial_for(spec)
    turns = (
        [] if spec["stage"] == "P3" else [read(p) for p in sorted(directory.glob("turn-*.json"))]
    )
    originals = rebuild_requests(spec, initial, turns)
    if len(originals) != len(reserved):
        raise ProviderStop("RAW_AND_REBUILT_TURNS_MUST_BE_ONE_TO_ONE")
    binding_paths = list(provider.glob("contract-*-binding.json"))
    bindings = [read(p) for p in binding_paths]
    if len(bindings) != len(reserved):
        raise ProviderStop("ONE_CANONICAL_BINDING_PER_ACTUAL_GENERATION")
    identities = list(provider.glob("identity-*"))
    if len(identities) != 1:
        raise ProviderStop("ONE_COLD_CLIENT_IDENTITY_REQUIRED")
    expected_provider_files = verify_identity(identities[0], batch.plan["http_identity"])
    expected_provider_files.add(provider / "provider-ledger-v2.jsonl")
    expected_provider_files.update(binding_paths)
    outputs = []
    for event, original in zip(reserved, originals, strict=True):
        key = event["request_id"]
        expected_provider_files.update(
            provider / (key + "-" + suffix + ".json")
            for suffix in (
                "request",
                "http",
                "tokenize-request",
                "tokenize-http",
                "tokenize",
                "lineage",
                "visible",
            )
        )
        actual_path = provider / (key + "-request.json")
        actual = read(actual_path)
        presented = present(original)
        compiled = compile_contract(original["response_format"]["json_schema"]["schema"], "D11")
        wire = compiled.prepare(presented)
        if actual_path.read_bytes() != encoded(wire).encode():
            raise ProviderStop("ACTUAL_WIRE_NOT_REBUILT_FROM_ORIGINAL_SESSION")
        matches = [b for b in bindings if b["wire_request_sha256"] == fingerprint(actual)]
        if len(matches) != 1:
            raise ProviderStop("UNIQUE_ACTUAL_CANONICAL_BINDING_REQUIRED")
        binding = matches[0]
        required_binding = {
            **compiled.manifest(),
            "original_request": original,
            "original_request_sha256": fingerprint(original),
            "presented_request": presented,
            "presented_request_sha256": fingerprint(presented),
            "presentation_diff": audit_presentation(original, presented),
            "wire_request_sha256": fingerprint(wire),
            "prompt_diff": compiled.prompt_diff(presented),
        }
        if fingerprint(binding) != fingerprint(required_binding):
            raise ProviderStop("PRESENTATION_OR_D11_BINDING_NOT_INDEPENDENTLY_REBUILT")
        http = read(provider / (key + "-http.json"))
        body = strict_http_json(http["body"])
        count_http = read(provider / (key + "-tokenize-http.json"))
        count = strict_http_json(count_http["body"])["count"]
        settled = [e for e in known if e["request_id"] == key]
        raw = body["choices"][0]["message"]["content"]
        if (
            http["status_code"] != 200
            or http["client_request_id"] != key
            or http["request_wire_sha256"] != sha(actual_path)
            or event["payload_sha256"] != sha(actual_path)
            or event["session"] != episode
            or count_http["status_code"] != 200
            or type(count) is not int
            or count < 0
            or count + 4096 > 65536
            or event["prompt_tokens"] != count
            or type(event.get("output_cap")) is not int
            or event["output_cap"] != 4096
            or type(event.get("raw_upper_bound")) is not int
            or event["raw_upper_bound"] != count + 4096
            or event.get("cumulative_raw_cap", "MISSING") is not None
            or fingerprint(read(provider / (key + "-tokenize.json")))
            != fingerprint({"count": count})
            or fingerprint(read(provider / (key + "-lineage.json")))
            != fingerprint(batch.auth["historical"])
            or fingerprint(read(provider / (key + "-tokenize-request.json")))
            != fingerprint({k: wire[k] for k in TOKENIZE_KEYS})
            or len(settled) != 1
            or not valid_usage(body.get("usage"))
            or fingerprint(settled[0]["usage"]) != fingerprint(body["usage"])
            or body["usage"]["prompt_tokens"] != count
            or body["usage"]["completion_tokens"] > 4096
            or not isinstance(body.get("id"), str)
            or not body["id"]
            or not isinstance(raw, str)
            or read(provider / (key + "-visible.json"))["content"] != raw
        ):
            raise ProviderStop("ACTUAL_HTTP_TOKENIZE_USAGE_OR_VISIBLE_EVIDENCE_DRIFT")
        action = compiled.validate_output(raw)
        binding_path = binding_paths[bindings.index(binding)]
        validation_path = binding_path.with_name(
            binding_path.name.removesuffix("-binding.json") + "-validation.json"
        )
        expected_provider_files.add(validation_path)
        if read(validation_path) != {
            "status": "PUBLIC_CONTRACT_AND_INTENT_PASS",
            "output_sha256": fingerprint(raw),
            "released_to_host": True,
            "business_effect": False,
            "host_mode": "VALIDATE_ONLY" if spec["stage"] == "P3" else "ISOLATED_SESSION",
        }:
            raise ProviderStop("EXACT_VALIDATED_RAW_RELEASE_EVIDENCE_REQUIRED")
        if (
            action["action"] == "put_record"
            and type(action["arguments"]["expected_version"]) is not int
        ):
            raise ProviderStop("STRICT_CAS_INTEGER_REQUIRED")
        if (
            spec["stage"] == "P3"
            and spec["variant"] == "full"
            and differences(spec["expected"], action)
        ):
            raise ProviderStop("FULL_INTENT_FIDELITY_NOT_MET")
        outputs.append(raw)
    if {p for p in provider.rglob("*") if p.is_file()} != expected_provider_files:
        raise ProviderStop("EXACT_ACCOUNTED_PROVIDER_FILE_SET_REQUIRED")
    checks = {
        "source_requests_raw_presentation_D11_usage_and_identity": True,
        "no_note": not list(directory.rglob("note-*.json")),
        "no_failure_artifacts": not list(provider.glob("contract-*-failure.json")),
    }
    if spec["stage"] == "P3":
        checks.update(
            {
                "validate_only": worker["status"] == "VALIDATE_ONLY_PASS",
                "one_full_or_finish": len(reserved) == 1,
                "no_business_world": worker["business_dispatches"] == 0
                and not (batch.root / "worlds" / (episode + ".sqlite")).exists(),
                "worker_raw": worker["raw"] == outputs[0],
            }
        )
    else:
        final, ledger, sql_checks = world_evidence(
            batch.root / "worlds" / (episode + ".sqlite"), spec
        )
        checks.update(sql_checks)
        checks.update(effects(spec, initial, final, ledger, turns)["checks"])
        checks["complete_actual_public_replies"] = public_trajectory(initial, ledger, turns)
        contract = SessionContract.from_public(initial)
        checks.update(
            {
                "raw_actions": outputs == [t["raw"] for t in turns]
                and all(
                    fingerprint(contract.decode(t["raw"], finish_only=i == 4))
                    == fingerprint(t["action"])
                    for i, t in enumerate(turns, 1)
                ),
                "saved_initial": fingerprint(read(directory / "initial-world.json"))
                == fingerprint(initial),
                "saved_final": fingerprint(read(directory / "final-world.json"))
                == fingerprint(final),
                "saved_ledger": fingerprint(read(directory / "final-ledger.json"))
                == fingerprint(ledger),
                "saved_initial_presentation": fingerprint(
                    read(directory / "initial-presentation.json")
                )
                == fingerprint(presentation_for(spec, initial)),
                "worker_finish": worker["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT",
                "no_unknown_commit": worker["unresolved_operations"] == [],
            }
        )
    files = {
        str(p): sha(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.suffix in {".json", ".jsonl"} and p.name != "independent-audit.json"
    }
    if spec["stage"] == "P4":
        world_path = batch.root / "worlds" / (episode + ".sqlite")
        # Each World belongs to just this now-terminal worker. Unlike the shared
        # coordinator DB, it is never mutated by later episodes or gate freezes.
        files[str(world_path)] = sha(world_path)
    return {
        "id": episode,
        "stage": spec["stage"],
        "status": "PASS" if all(checks.values()) else "FAIL",
        "pid": worker["pid"],
        "cost": cost,
        "checks": checks,
        "files": files,
    }
