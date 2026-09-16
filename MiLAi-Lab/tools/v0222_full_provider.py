"""One selected string-compatible Provider; canonical validation before any action."""

from __future__ import annotations

import copy
import uuid
from pathlib import Path

from v0213_provider import payload
from v0218_world import digest
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_diagnostic import differences
from v0222_string_contract import compile_contract
from v0222_transport import Transport


def resolved_spec(batch, episode: str) -> dict:
    original = next(s for stage in ("P3", "P4") for s in batch.plan[stage] if s["id"] == episode)
    if original["stage"] == "P3":
        return original
    spec = next(s for s in batch.artifact("P4_resolved_specs")["specs"] if s["id"] == episode)
    left, right = copy.deepcopy(original), copy.deepcopy(spec)
    left.pop("initial_state_sha256")
    right.pop("initial_state_sha256")
    if fingerprint(left) != fingerprint(right):
        raise ProviderStop("RESOLVED_SPEC_MAY_ONLY_UPDATE_DECLARED_INITIAL_DIGEST")
    return spec


class FullProvider:
    def __init__(self, root: Path, *, batch, episode: str, world=None, transport=None):
        claim = batch.admit(episode)
        if claim["stage"] not in {"P3", "P4"}:
            raise ProviderStop("FULL_PROVIDER_ONLY_FOR_FULL_STAGES")
        self.batch, self.root, self.episode = batch, root, episode
        self.spec = resolved_spec(batch, episode)
        self.world, self.turn, self.writes, self.readback = world, 0, 0, False
        self.pending_wire_hash = None
        self.stopped = False
        if batch.artifact("P1_final_selection")["selected_condition"] != "D11":
            raise ProviderStop("ONLY_FROZEN_SELECTED_D11_CANDIDATE")
        if batch.artifact("P2_gate")["status"] != "G_P2_PASS":
            raise ProviderStop("P2_NOT_ADMITTED")
        if self.spec["stage"] == "P4":
            if (
                world is None
                or world.path.resolve() != batch.root / "worlds" / (episode + ".sqlite")
                or world.scope != self.spec["scope"]
            ):
                raise ProviderStop("FROZEN_INTENT_AND_WORLD_BINDING_REQUIRED")
            self.initial = world.snapshot()
            if (
                digest(self.initial) != self.spec["initial_state_sha256"]
                or self.initial["version"] != 0
                or self.initial["records"]
            ):
                raise ProviderStop("P4_REQUIRES_FROZEN_EMPTY_INITIAL_WORLD")
        elif world is not None:
            raise ProviderStop("P3_VALIDATE_ONLY_NO_WORLD")
        self.provider = Transport(
            root, batch=batch, episode=episode, preflight=self._wire_preflight, transport=transport
        )

    def _wire_preflight(self, wire: dict) -> None:
        if self.pending_wire_hash is None or fingerprint(wire) != self.pending_wire_hash:
            raise ProviderStop("WIRE_REQUEST_NOT_PREPARED_OR_DRIFTED")

    def verify(self) -> dict:
        if self.stopped:
            raise ProviderStop("FULL_PROVIDER_STOPPED")
        return self.provider.verify()

    def _check_world(self) -> None:
        if self.world is None:
            return
        expected = copy.deepcopy(self.initial)
        for action in self.spec["actions"][: self.writes]:
            args = action["arguments"]
            expected["records"][args["object_id"]] = {
                "object_id": args["object_id"],
                **args["data"],
            }
            expected["pending"].pop(args["object_id"], None)
            expected["version"] += 1
            expected["history"].append(
                {
                    "kind": "business_action",
                    "action": "put_record",
                    "object_id": args["object_id"],
                    "data": args["data"],
                }
            )
        if (
            digest(self.world.snapshot()) != digest(expected)
            or len(self.world.ledger()) != self.writes
        ):
            raise ProviderStop("ACTUAL_WORLD_DEVIATES_FROM_AUTHORIZED_PREFIX")

    def _admit_request(self, body: dict, wire: dict) -> None:
        references = [
            r for r in self.batch.references(self.spec["stage"]) if r["episode"] == self.episode
        ]
        if not references:
            raise ProviderStop("COMPLETE_REFERENCE_EPISODE_REQUIRED")
        for row in references:
            for kind in ("canonical", "wire", "output"):
                if sha(Path(row[kind])) != row["hashes"][kind]:
                    raise ProviderStop("FULL_REFERENCE_DRIFT")
        if self.spec["stage"] == "P3":
            if (
                len(references) != 1
                or fingerprint(body) != fingerprint(read(Path(references[0]["canonical"])))
                or fingerprint(wire) != fingerprint(read(Path(references[0]["wire"])))
            ):
                raise ProviderStop("P3_ACTUAL_REQUEST_NOT_EXACT_FROZEN_REFERENCE")
        else:
            initial_request = read(Path(references[0]["canonical"]))
            if fingerprint(body["messages"][:2]) != fingerprint(initial_request["messages"][:2]):
                raise ProviderStop("P4_COMPLETE_INITIAL_SOURCES_AND_INTENT_MUST_REMAIN_PRESENT")
            if self.turn == 0 and fingerprint(body) != fingerprint(initial_request):
                raise ProviderStop("P4_INITIAL_REQUEST_NOT_EXACT_FROZEN_REFERENCE")
            expected_schema = initial_request["response_format"]["json_schema"]["schema"]
            if self.turn == 3:
                from v0220_session import SessionContract

                expected_schema = SessionContract.from_public(self.initial).action_schema(
                    finish_only=True
                )
            if fingerprint(body) != fingerprint(payload(body["messages"], expected_schema)):
                raise ProviderStop("P4_SCHEMA_OR_PARAMETER_DRIFT")

    def generate(self, session: str, body: dict) -> str:
        if self.stopped:
            raise ProviderStop("FULL_PROVIDER_STOPPED_NO_RETRY")
        key = "contract-" + uuid.uuid4().hex
        try:
            self.batch.admit(self.episode)
            self._check_world()
            plan = compile_contract(body["response_format"]["json_schema"]["schema"], "D11")
            wire = plan.prepare(body)
            self._admit_request(body, wire)
            self.pending_wire_hash = fingerprint(wire)
            save(
                self.root / (key + "-binding.json"),
                {
                    **plan.manifest(),
                    "original_request": body,
                    "original_request_sha256": fingerprint(body),
                    "wire_request_sha256": self.pending_wire_hash,
                    "prompt_diff": plan.prompt_diff(body),
                },
            )
            raw = self.provider.generate(session, wire)
            action = plan.validate_output(raw)
            self.batch.admit(self.episode)
            if (
                action["action"] == "put_record"
                and type(action["arguments"]["expected_version"]) is not int
            ):
                raise ProviderStop("WORLD_VERSION_INTEGER_REQUIRED_BEFORE_DISPATCH")
            mismatch = []
            if self.spec["stage"] == "P3":
                if self.spec["variant"] == "full":
                    mismatch = differences(self.spec["expected"], action)
            else:
                name = action["action"]
                if name == "put_record":
                    if self.writes >= len(self.spec["actions"]):
                        raise ProviderStop("EXTRA_UNAUTHORIZED_WRITE")
                    mismatch = differences(self.spec["actions"][self.writes], action)
                    if not mismatch:
                        self.writes += 1
                        self.readback = False
                elif name == "request_clarification":
                    raise ProviderStop("UNAUTHORIZED_ORACLE_BUSINESS_EFFECT")
                elif action == {"action": "read", "arguments": {"resource": "records"}}:
                    self.readback = self.writes == len(self.spec["actions"])
                elif name == "finish" and (
                    self.writes != len(self.spec["actions"]) or not self.readback
                ):
                    raise ProviderStop("FINISH_BEFORE_INTENT_AND_PUBLIC_READBACK")
            if mismatch:
                save(
                    self.root / (key + "-intent-diff.json"),
                    {"status": "NOT_RELEASED", "differences": mismatch},
                )
                raise ProviderStop("FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH")
            self.turn += 1
            save(
                self.root / (key + "-validation.json"),
                {
                    "status": "PUBLIC_CONTRACT_AND_INTENT_PASS",
                    "output_sha256": fingerprint(raw),
                    "released_to_host": True,
                    "business_effect": False,
                    "host_mode": "VALIDATE_ONLY"
                    if self.spec["stage"] == "P3"
                    else "ISOLATED_SESSION",
                },
            )
            return raw
        except BaseException as exc:
            self.stopped = True
            code = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
            save(
                self.root / (key + "-failure.json"),
                {
                    "status": "NOT_RELEASED_TO_EXECUTOR",
                    "code": code,
                    "issues": getattr(exc, "issues", []),
                    "usage": (
                        "Retained in original HTTP/central ledger; validation failure is not free"
                    ),
                },
            )
            self.batch.stop(code)
            raise
        finally:
            self.pending_wire_hash = None

    def close(self) -> None:
        self.provider.close()
