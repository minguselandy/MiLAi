"""Offline three-layer references for the selected intent-presentation candidate.

These helpers do not authorize an instance, send HTTP, or choose a model action.
Materializers use explicitly offline reference actions in fresh isolated Worlds.
A future coordinator must bind each row to its complete source/spec and trajectory.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path

from prepare_v0221_http_v2 import FINISH, READBACK, W2_SYSTEM, save_request
from prepare_v0222_full import resolve_p4_spec, session
from v0213_provider import payload
from v0218_world import World, digest
from v0220_action_adapter import ActionAdapter
from v0220_evidence import read, save, sha
from v0220_intent_audit import effects
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded, fingerprint
from v0222_presentation_contract import audit_presentation, present
from v0222_string_contract import compile_contract

KINDS = ("canonical", "presented", "wire", "output", "presentation_diff")


def write_reference(directory: Path, spec: dict, turn: int, canonical: dict, output: dict) -> dict:
    """Retain original, presentation-only, and D11 wire without value repair."""
    if spec.get("stage") not in {"P3", "P4"} or type(turn) is not int or turn < 1:
        raise ProviderStop("PRESENTATION_REFERENCE_STAGE_OR_TURN_INVALID")
    presented = present(canonical)
    diff = audit_presentation(canonical, presented)
    compiled = compile_contract(canonical["response_format"]["json_schema"]["schema"], "D11")
    raw = encoded(output)
    compiled.validate_output(raw)
    wire = compiled.prepare(presented)
    stem = directory / f"request-{turn:02d}"
    row = {
        "stage": spec["stage"],
        "episode": spec["id"],
        "turn": turn,
        "selected_condition": "B1",
        "selected_decoder": "D11",
        "schema_pair": compiled.manifest(),
    }
    for kind, value in (
        ("canonical", canonical),
        ("presented", presented),
        ("wire", wire),
        ("output", {"raw": raw}),
        ("presentation_diff", diff),
    ):
        path = stem.with_suffix("." + kind + ".json")
        # Match the old actual canonical/wire serialization exactly.
        if kind in {"canonical", "presented", "wire"}:
            save_request(path, value)
        else:
            save(path, value)
        row[kind] = str(path)
    row["hashes"] = {kind: sha(Path(row[kind])) for kind in KINDS}
    validate_reference(row)
    return row


def validate_reference(row: dict) -> tuple[dict, dict, dict, str]:
    """Recompute a local reference; not a source/spec or live admission gate."""
    if row.get("selected_condition") != "B1" or row.get("selected_decoder") != "D11":
        raise ProviderStop("PRESENTATION_REFERENCE_CANDIDATE_DRIFT")
    if set(row.get("hashes", {})) != set(KINDS):
        raise ProviderStop("ALL_PRESENTATION_REFERENCE_LAYERS_REQUIRED")
    if any(sha(Path(row[kind])) != row["hashes"][kind] for kind in KINDS):
        raise ProviderStop("PRESENTATION_REFERENCE_HASH_DRIFT")
    original, presented, wire = (read(Path(row[k])) for k in KINDS[:3])
    if any(
        Path(row[kind]).read_bytes() != encoded(value).encode()
        for kind, value in zip(KINDS[:3], (original, presented, wire), strict=True)
    ):
        raise ProviderStop("EXACT_PRESENTATION_REFERENCE_SERIALIZATION_REQUIRED")
    diff = audit_presentation(original, presented)
    compiled = compile_contract(original["response_format"]["json_schema"]["schema"], "D11")
    if (
        fingerprint(diff) != fingerprint(read(Path(row["presentation_diff"])))
        or fingerprint(compiled.prepare(presented)) != fingerprint(wire)
        or fingerprint(compiled.manifest()) != fingerprint(row["schema_pair"])
    ):
        raise ProviderStop("PRESENTATION_REFERENCE_COMPILER_OR_DIFF_DRIFT")
    raw = read(Path(row["output"]))["raw"]
    compiled.validate_output(raw)
    return original, presented, wire, raw


class ReferenceProvider:
    """Scripted offline reference, never a model-result or action-selection claim."""

    def __init__(self, directory: Path, spec: dict):
        self.directory, self.spec = directory, spec
        self.actions = iter([*spec["actions"], READBACK, FINISH])
        self.rows: list[dict] = []

    def verify(self):
        return {"profile": "OFFLINE_REFERENCE_NO_HTTP"}

    def generate(self, episode, body):
        if episode != self.spec["id"]:
            raise ProviderStop("REFERENCE_EPISODE_DRIFT")
        action = next(self.actions)
        self.rows.append(
            write_reference(self.directory, self.spec, len(self.rows) + 1, body, action)
        )
        return encoded(action)

    def close(self):
        pass


def prepare_p3(directory: Path, spec: dict, public: dict, validate_binding) -> list[dict]:
    """Build a complete original calibration, with only the selected presentation."""
    if spec.get("stage") != "P3" or spec.get("variant") not in {"full", "finish"}:
        raise ProviderStop("P3_FULL_OR_FINISH_REFERENCE_REQUIRED")
    validate_binding()
    world = World.create(directory / "world.sqlite", spec["scope"], public)
    host = session(world, directory, spec, validate_binding)
    messages = copy.deepcopy(host.messages)
    messages[0] = {"role": "system", "content": W2_SYSTEM}
    original = payload(
        messages, host.contract.action_schema(finish_only=spec["variant"] == "finish")
    )
    row = write_reference(directory, spec, 1, original, spec["expected"])
    if spec["variant"] == "full":
        reply = ActionAdapter(world, host.contract).execute(
            spec["expected"], operation_id="reference"
        )
        args = spec["expected"]["arguments"]
        if reply.get("committed") is not True or world.snapshot()["records"][args["object_id"]] != {
            "object_id": args["object_id"],
            **args["data"],
        }:
            raise ProviderStop("P3_REFERENCE_COMPLETE_OBJECT_EFFECT_REQUIRED")
    save(
        directory / "reference-validation.json",
        {
            "status": "OFFLINE_REFERENCE_PASS",
            "model_requests": 0,
            "http_requests": 0,
            "live_dispatches": 0,
            "note_enabled": host.contract.enable_note,
            "legal_targets": list(host.contract.write_schemas()),
        },
    )
    return [row]


def prepare_p4(directory: Path, spec: dict, public: dict, validate_binding) -> tuple[list, dict]:
    """Original Session/Adapter/SQLite/effects; reference actions are offline only."""
    if spec.get("stage") != "P4":
        raise ProviderStop("P4_REFERENCE_REQUIRED")
    validate_binding()
    resolved, change = resolve_p4_spec(spec, public)
    world = World.create(directory / "world.sqlite", resolved["scope"], public)
    initial = world.snapshot()
    if digest(initial) != resolved["initial_state_sha256"]:
        raise ProviderStop("REFERENCE_DERIVED_INITIAL_DIGEST_MISMATCH")
    host = session(world, directory, resolved, validate_binding)
    provider = ReferenceProvider(directory, resolved)
    result = host.run(provider, deadline=time.monotonic() + 60)
    final, ledger = world.snapshot(), world.ledger()
    verdict = effects(resolved, initial, final, ledger, host.rows)
    if result["status"] != "SESSION_FINISHED_NOT_TASK_VERDICT" or verdict["status"] != "PASS":
        raise ProviderStop("REFERENCE_COMPLETE_INDEPENDENT_EFFECT_NOT_MET")
    if len(provider.rows) != len(resolved["actions"]) + 2 or not 3 <= len(provider.rows) <= 4:
        raise ProviderStop("REFERENCE_COMPLETE_READBACK_FINISH_REQUIRED")
    for name, value in (
        ("initial-world", initial),
        ("final-world", final),
        ("final-ledger", ledger),
        ("independent-effects", verdict),
    ):
        save(directory / (name + ".json"), value)
    return provider.rows, {"spec": resolved, "derived_hash_diff": change}
