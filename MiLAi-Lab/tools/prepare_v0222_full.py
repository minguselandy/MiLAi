"""Offline complete P3/P4 references under the single selected string candidate."""

from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path

from prepare_v0221_http_v2 import CASES, FINISH, READBACK, W2_SYSTEM, save_request
from v0213_provider import payload
from v0218_world import World, digest
from v0220_action_adapter import ActionAdapter
from v0220_evidence import read, save, sha
from v0220_intent_audit import effects
from v0220_provider_hardened import ProviderStop
from v0220_session import Session
from v0220_wire_contract import encoded
from v0222_batch import Batch
from v0222_string_contract import compile_contract


def selected(batch, condition: str) -> None:
    decision = batch.artifact("P1_final_selection")
    if decision != {"status": "STRING_RULE_SIGNAL", "selected_condition": condition}:
        raise ProviderStop("EXACT_SELECTED_STRING_CANDIDATE_REQUIRED")


def resolve_p4_spec(spec: dict, public: dict) -> tuple[dict, dict]:
    """Only a scope-derived checksum changes; never alter actions, intent or frozen scope."""
    result = copy.deepcopy(spec)
    initial = {
        **copy.deepcopy(public),
        "scope": spec["scope"],
        "version": 0,
        "records": {},
        "pending": {},
        "history": [],
    }
    result["initial_state_sha256"] = digest(initial)
    return result, {
        "id": spec["id"],
        "path": "/initial_state_sha256",
        "old": spec["initial_state_sha256"],
        "resolved": result["initial_state_sha256"],
        "reason": "Recompute initial digest from the frozen new scope and unchanged public data",
        "scope_unchanged": result["scope"] == spec["scope"],
        "actions_and_intent_unchanged": result["actions"] == spec["actions"]
        and result["intent"] == spec["intent"],
    }


def write_reference(
    directory: Path, spec: dict, turn: int, canonical: dict, output: dict, condition: str
) -> dict:
    contract = compile_contract(
        canonical["response_format"]["json_schema"]["schema"],
        selected_condition=condition,
    )
    raw = encoded(output)
    contract.validate_output(raw)
    wire = contract.prepare(canonical)
    stem = directory / f"request-{turn:02d}"
    row = {
        "stage": spec["stage"],
        "episode": spec["id"],
        "turn": turn,
        "selected_condition": condition,
        "schema_pair": contract.manifest(),
    }
    for kind, value in (("canonical", canonical), ("wire", wire)):
        path = stem.with_suffix("." + kind + ".json")
        save_request(path, value)
        row[kind] = str(path)
    path = stem.with_suffix(".output.json")
    save(path, {"raw": raw})
    row["output"] = str(path)
    row["hashes"] = {kind: sha(Path(row[kind])) for kind in ("canonical", "wire", "output")}
    return row


class ReferenceProvider:
    def __init__(self, directory: Path, spec: dict, condition: str):
        self.directory, self.spec, self.condition = directory, spec, condition
        self.actions = iter([*spec["actions"], READBACK, FINISH])
        self.rows = []

    def verify(self):
        return {"profile": "OFFLINE_REFERENCE_NO_HTTP"}

    def generate(self, session, body):
        if session != self.spec["id"]:
            raise ProviderStop("REFERENCE_EPISODE_DRIFT")
        action = next(self.actions)
        self.rows.append(
            write_reference(
                self.directory,
                self.spec,
                len(self.rows) + 1,
                body,
                action,
                self.condition,
            )
        )
        return encoded(action)

    def close(self):
        pass


def session(world, directory, spec, validate_binding):
    return Session(
        world,
        directory / "session",
        episode_id=spec["id"],
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent={"authorized_action": spec["expected"]} if spec["stage"] == "P3" else spec["intent"],
        validate_binding=validate_binding,
    )


def prepare_p3(
    directory: Path, spec: dict, public: dict, condition: str, validate_binding
) -> list[dict]:
    world = World.create(directory / "world.sqlite", spec["scope"], public)
    host = session(world, directory, spec, validate_binding)
    messages = copy.deepcopy(host.messages)
    messages[0] = {"role": "system", "content": W2_SYSTEM}
    canonical = payload(
        messages, host.contract.action_schema(finish_only=spec["variant"] == "finish")
    )
    row = write_reference(directory, spec, 1, canonical, spec["expected"], condition)
    if spec["variant"] == "full":
        response = ActionAdapter(world, host.contract).execute(
            spec["expected"], operation_id="reference"
        )
        target = spec["expected"]["arguments"]["object_id"]
        if response.get("committed") is not True or world.snapshot()["records"][target] != {
            "object_id": target,
            **spec["expected"]["arguments"]["data"],
        }:
            raise ProviderStop("P3_REFERENCE_FULL_OBJECT_EFFECT_MISMATCH")
    save(
        directory / "reference-validation.json",
        {
            "status": "OFFLINE_REFERENCE_PASS",
            "live_dispatches": 0,
            "note_enabled": host.contract.enable_note,
            "legal_targets": list(host.contract.write_schemas()),
        },
    )
    return [row]


def prepare_p4(
    directory: Path, spec: dict, public: dict, condition: str, validate_binding
) -> tuple[list[dict], dict]:
    resolved, change = resolve_p4_spec(spec, public)
    world = World.create(directory / "world.sqlite", resolved["scope"], public)
    initial = world.snapshot()
    if digest(initial) != resolved["initial_state_sha256"]:
        raise ProviderStop("RESOLVED_INITIAL_WORLD_MISMATCH")
    host = session(world, directory, resolved, validate_binding)
    provider = ReferenceProvider(directory, resolved, condition)
    outcome = host.run(provider, deadline=time.monotonic() + 60)
    verdict = effects(resolved, initial, world.snapshot(), world.ledger(), host.rows)
    if outcome["status"] != "SESSION_FINISHED_NOT_TASK_VERDICT" or verdict["status"] != "PASS":
        raise ProviderStop("P4_REFERENCE_INDEPENDENT_EFFECT_NOT_MET")
    if len(provider.rows) != len(spec["actions"]) + 2 or not 3 <= len(provider.rows) <= 4:
        raise ProviderStop("REFERENCE_COMPLETE_READBACK_FINISH_REQUIRED")
    save(directory / "initial-world.json", initial)
    save(directory / "final-world.json", world.snapshot())
    save(directory / "final-ledger.json", world.ledger())
    save(directory / "independent-effects.json", verdict)
    return provider.rows, {"spec": resolved, "derived_hash_diff": change}


def prepare(root: Path, binding: str, selected_condition: str = "D11") -> dict:
    batch = Batch(root, binding)
    batch.authorize("P2")
    selected(batch, selected_condition)
    if batch.snapshot()["stop"]:
        raise ProviderStop("BATCH_ALREADY_STOPPED")
    directory = root / "full-reference"
    directory.mkdir(exist_ok=False)
    references = {"P3": [], "P4": []}
    resolved = {"status": "DERIVED_INITIAL_HASHES_RESOLVED", "specs": [], "diffs": [], "files": {}}
    try:
        for stage in ("P3", "P4"):
            for spec in batch.plan[stage]:
                batch.authorize("P2")
                source = CASES / spec["root"] / "public-initial.json"
                public = read(source)
                resolved["files"][str(source)] = sha(source)
                target = directory / stage / spec["id"]
                verify = lambda: batch.authorize("P2")  # noqa: E731
                if stage == "P3":
                    rows = prepare_p3(target, spec, public, selected_condition, verify)
                else:
                    rows, resolution = prepare_p4(target, spec, public, selected_condition, verify)
                    resolved["specs"].append(resolution["spec"])
                    resolved["diffs"].append(resolution["derived_hash_diff"])
                references[stage].extend(rows)
                print(f"offline {stage} {spec['id']} {len(rows)} reference rounds", flush=True)
        if len(references["P3"]) != 16 or len(references["P4"]) != 80:
            raise ProviderStop("COMPLETE_16_PLUS_80_REFERENCE_MATRIX_REQUIRED")
        resolved_path = directory / "P4-resolved-specs.json"
        save(resolved_path, resolved)
        for stage, rows in references.items():
            save(directory / (stage + "-reference-index.json"), rows)
        result = {
            "status": "REFERENCE_PREPARATION_PASS",
            "selected_condition": selected_condition,
            "P3_requests": 16,
            "P4_requests": 80,
            "P4_chains": len(resolved["specs"]),
            "model_requests": 0,
            "http_requests": 0,
            "decoder_membership": "UNOBSERVED",
            "files": {str(p): sha(p) for p in sorted(directory.rglob("*")) if p.is_file()},
        }
        save(directory / "prepared.json", result)
        batch.freeze_artifact("P4_resolved_specs", resolved_path)
        for stage in references:
            batch.freeze_artifact(
                stage + "_references", directory / (stage + "-reference-index.json")
            )
        batch.freeze_artifact(
            "P_full_preparation", directory / "prepared.json", "REFERENCE_PREPARATION_PASS"
        )
        return result
    except Exception as exc:
        save(
            directory / "preparation-error.json",
            {
                "status": "LOCAL_PREPARATION_NOT_MET",
                "exception_type": type(exc).__name__,
                "reason": str(exc),
                "model_requests": 0,
                "http_requests": 0,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--selected-condition", choices=("D10", "D01", "D11"), default="D11")
    args = parser.parse_args()
    prepare(args.root, args.binding_sha256, args.selected_condition)
