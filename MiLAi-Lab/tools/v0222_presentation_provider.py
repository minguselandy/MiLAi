"""Selected whole-intent presentation, with unchanged full acceptance before release."""

from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from pathlib import Path

from v0213_provider import payload
from v0218_world import digest
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop
from v0220_session import SessionContract
from v0220_wire_contract import fingerprint
from v0222_diagnostic import differences
from v0222_presentation_contract import audit_presentation, present
from v0222_presentation_transport import Transport
from v0222_string_contract import compile_contract


class FullProvider:
    def __init__(self, root: Path, *, batch, episode: str, world=None, transport=None):
        self.root, self.batch, self.episode = root, batch, episode
        self.world, self.turn, self.writes, self.readback = world, 0, 0, False
        self.stopped, self.closed, self.pending_wire_hash = False, False, None
        self.outputs, self.actions, self.receipt_hashes = [], [], []
        try:
            claim = batch.admit(episode)
            self.spec = copy.deepcopy(batch.spec(episode))
            if (
                claim["stage"] not in {"P3", "P4"}
                or self.spec["stage"] != claim["stage"]
                or self.spec["id"] != episode
                or batch.plan.get("selected_decoder") != "D11"
                or batch.plan.get("selected_presentation") != "B1"
            ):
                raise ProviderStop("ONLY_SELECTED_PRESENTATION_FULL_STAGES")
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
                    or world.ledger()
                ):
                    raise ProviderStop("P4_REQUIRES_FROZEN_EMPTY_INITIAL_WORLD")
                self.contract = SessionContract.from_public(self.initial)
            elif world is not None:
                raise ProviderStop("P3_VALIDATE_ONLY_NO_WORLD")
            self.provider = Transport(
                root,
                batch=batch,
                episode=episode,
                preflight=self._wire_preflight,
                transport=transport,
            )
        except BaseException as exc:
            self._stop(exc)
            raise

    def _stop(self, exc: BaseException) -> None:
        self.stopped = True
        code = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        # Lock first: persisting a diagnostic may itself fail (disk/full/permissions).
        self.batch.stop(code)

    def _wire_preflight(self, body: dict) -> None:
        if self.pending_wire_hash is None or fingerprint(body) != self.pending_wire_hash:
            raise ProviderStop("WIRE_REQUEST_NOT_PREPARED_OR_DRIFTED")

    def verify(self) -> dict:
        if self.stopped or self.closed:
            raise ProviderStop("PRESENTATION_PROVIDER_STOPPED_NO_RETRY")
        try:
            return self.provider.verify()
        except BaseException as exc:
            self._stop(exc)
            raise

    def _check_world(self) -> None:
        if self.world is None:
            return
        if (
            self.world.path.resolve() != self.batch.root / "worlds" / (self.episode + ".sqlite")
            or self.world.scope != self.spec["scope"]
        ):
            raise ProviderStop("ACTUAL_WORLD_BINDING_DRIFT")
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

    def _admit_request(self, original: dict, presented: dict, wire: dict) -> None:
        if fingerprint(self.spec) != fingerprint(self.batch.spec(self.episode)):
            raise ProviderStop("PRESENTATION_SPEC_DRIFT")
        references = [
            r for r in self.batch.references(self.spec["stage"]) if r["episode"] == self.episode
        ]
        count = 1 if self.spec["stage"] == "P3" else len(self.spec["actions"]) + 2
        if len(references) != count or [r["turn"] for r in references] != list(range(1, count + 1)):
            raise ProviderStop("COMPLETE_ORDERED_EPISODE_REFERENCES_REQUIRED")
        for row in references:
            if row.get("stage") != self.spec["stage"] or any(
                sha(Path(row[kind])) != row["hashes"][kind]
                for kind in ("canonical", "presented", "wire", "output", "presentation_diff")
            ):
                raise ProviderStop("FROZEN_PRESENTATION_REFERENCE_DRIFT")
        first, first_presented, first_wire = (
            read(Path(references[0][kind])) for kind in ("canonical", "presented", "wire")
        )
        if self.spec["stage"] == "P3":
            if self.turn != 0 or any(
                fingerprint(actual) != fingerprint(expected)
                for actual, expected in zip(
                    (original, presented, wire), (first, first_presented, first_wire), strict=True
                )
            ):
                raise ProviderStop("P3_ACTUAL_REQUEST_NOT_EXACT_FROZEN_REFERENCE")
            return
        if self.turn >= 4:
            raise ProviderStop("FOUR_GENERATIONS_MAXIMUM_NO_RETRY")
        if sorted(p.name for p in self.root.parent.glob("turn-*.json")) != [
            f"turn-{i + 1:02d}.json" for i in range(self.turn)
        ]:
            raise ProviderStop("EXACT_COMPLETED_TURN_SET_REQUIRED")
        # Reconstruct the original Session request from its actual saved public turns,
        # never from offline reference responses or the next authorized action.
        messages = copy.deepcopy(first["messages"][:2])
        last = json.loads(first["messages"][-1]["content"])["last_completed_public_observation"]
        for index in range(self.turn):
            row = read(self.root.parent / f"turn-{index + 1:02d}.json")
            if row["raw"] != self.outputs[index] or fingerprint(row["action"]) != fingerprint(
                self.actions[index]
            ):
                raise ProviderStop("ACTUAL_PRIOR_RAW_ACTION_TRACE_DRIFT")
            if type(row.get("turn")) is not int or row["turn"] != index + 1:
                raise ProviderStop("EXACT_COMPLETED_TURN_NUMBER_REQUIRED")
            reply = self.contract.validate_response(row["response"])
            receipt_hash = fingerprint(reply)
            if index < len(self.receipt_hashes):
                if self.receipt_hashes[index] != receipt_hash:
                    raise ProviderStop("PREVIOUSLY_OBSERVED_PUBLIC_RECEIPT_DRIFT")
            else:
                if index != self.turn - 1:
                    raise ProviderStop("UNVERIFIED_OLDER_PUBLIC_RECEIPT")
                self._verify_new_reply(index, reply)
                self.receipt_hashes.append(receipt_hash)
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
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "remaining_generation_opportunities": 4 - self.turn,
                        "final_delivery_reservation": 1,
                        "last_completed_public_observation": last,
                    }
                ),
            }
        )
        expected = payload(messages, self.contract.action_schema(finish_only=self.turn == 3))
        if fingerprint(original) != fingerprint(expected):
            raise ProviderStop("P4_ACTUAL_SESSION_SOURCES_HISTORY_BUDGET_OR_SCHEMA_DRIFT")

    def _operation_reply(self, operation_id: str) -> dict:
        # Read only the Actor's own scoped durable operation, never replay it.
        with sqlite3.connect(self.world.path.as_uri() + "?mode=ro", uri=True) as db:
            self.world._state(db)
            row = db.execute(
                "SELECT request_hash,receipt FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
            rejected = db.execute(
                "SELECT receipt FROM v0220_dispatch WHERE id=?", (operation_id,)
            ).fetchone()
        if row is not None:
            return {
                **json.loads(row[1]),
                "committed": True,
                "version_domain": "WORLD",
                "request_sha256": row[0],
                "business_effect": True,
                "retry_requires": "NONE",
            }
        if rejected and rejected[0] is not None:
            return json.loads(rejected[0])
        return {
            "status": "NOT_OBSERVED",
            "committed": None,
            "operation_id": operation_id,
            "version_domain": "WORLD",
            "retry_requires": "QUERY_OR_EXACT_REPLAY_ONLY",
        }

    def _verify_new_reply(self, index: int, reply: dict) -> None:
        """Bind a newly completed public reply before it can enter another request."""
        action = self.actions[index]
        name, args = action["action"], action["arguments"]
        if name == "put_record":
            operation_id = f"{self.episode}:{index + 1:02d}"
            request = {
                "operation_id": operation_id,
                "action": name,
                **args,
                "scope": self.world.scope,
            }
            ledger = self.world.ledger()
            previous = self.initial if len(ledger) == 1 else ledger[-2]["snapshot"]
            entry = ledger[-1]
            expected = self._operation_reply(operation_id)
            if (
                fingerprint(entry["request"]) != fingerprint(request)
                or digest(entry["snapshot"]) != digest(self.world.snapshot())
                or entry["receipt"]["before_sha256"] != digest(previous)
                or entry["receipt"]["after_sha256"] != digest(entry["snapshot"])
                or expected.get("request_sha256") != digest(request)
                or fingerprint(expected)
                != fingerprint(
                    {
                        **entry["receipt"],
                        "committed": True,
                        "version_domain": "WORLD",
                        "request_sha256": digest(request),
                        "business_effect": True,
                        "retry_requires": "NONE",
                    }
                )
            ):
                raise ProviderStop("ACTUAL_COMMITTED_OPERATION_OR_LEDGER_DRIFT")
        elif name == "read":
            expected = {
                **self.world.read(args["resource"]),
                "version_domain": "WORLD",
                "committed": False,
                "status": "PUBLIC_OBSERVATION",
                "business_effect": False,
            }
        elif name == "operation_status":
            expected = self._operation_reply(args["operation_id"])
        else:
            raise ProviderStop("NO_NEXT_REQUEST_AFTER_TERMINAL_ACTION")
        if fingerprint(reply) != fingerprint(expected):
            raise ProviderStop("ACTUAL_PUBLIC_RECEIPT_NOT_FROM_COMPLETED_ACTION")

    def generate(self, session: str, body: dict) -> str:
        if self.stopped or self.closed:
            raise ProviderStop("PRESENTATION_PROVIDER_STOPPED_NO_RETRY")
        key = "contract-" + uuid.uuid4().hex
        try:
            self.batch.admit(self.episode)
            self._check_world()
            original = copy.deepcopy(body)
            presented = present(original)
            presentation_diff = audit_presentation(original, presented)
            compiled = compile_contract(original["response_format"]["json_schema"]["schema"], "D11")
            wire = compiled.prepare(presented)
            self._admit_request(original, presented, wire)
            self.pending_wire_hash = fingerprint(wire)
            save(
                self.root / (key + "-binding.json"),
                {
                    **compiled.manifest(),
                    "original_request": original,
                    "original_request_sha256": fingerprint(original),
                    "presented_request": presented,
                    "presented_request_sha256": fingerprint(presented),
                    "presentation_diff": presentation_diff,
                    "wire_request_sha256": self.pending_wire_hash,
                    "prompt_diff": compiled.prompt_diff(presented),
                },
            )
            raw = self.provider.generate(session, wire)
            action = compiled.validate_output(raw)
            self.batch.admit(self.episode)
            if (
                action["action"] == "put_record"
                and type(action["arguments"]["expected_version"]) is not int
            ):
                raise ProviderStop("WORLD_VERSION_INTEGER_REQUIRED_BEFORE_DISPATCH")
            next_writes, next_readback = self.writes, self.readback
            mismatch = []
            if self.spec["stage"] == "P3":
                if self.spec["variant"] == "full":
                    mismatch = differences(self.spec["expected"], action)
            elif action["action"] == "put_record":
                if self.writes >= len(self.spec["actions"]):
                    raise ProviderStop("EXTRA_UNAUTHORIZED_WRITE")
                mismatch = differences(self.spec["actions"][self.writes], action)
                next_writes, next_readback = self.writes + 1, False
            elif action["action"] == "request_clarification":
                raise ProviderStop("UNAUTHORIZED_ORACLE_BUSINESS_EFFECT")
            elif action == {"action": "read", "arguments": {"resource": "records"}}:
                next_readback = self.writes == len(self.spec["actions"])
            elif action["action"] == "finish" and (
                self.writes != len(self.spec["actions"]) or not self.readback
            ):
                raise ProviderStop("FINISH_BEFORE_INTENT_AND_PUBLIC_READBACK")
            if mismatch:
                failure = ProviderStop("FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH")
                self._stop(failure)
                save(
                    self.root / (key + "-intent-diff.json"),
                    {"status": "NOT_RELEASED", "differences": mismatch},
                )
                raise failure
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
            self.turn += 1
            self.writes, self.readback = next_writes, next_readback
            self.outputs.append(raw)
            self.actions.append(copy.deepcopy(action))
            return raw
        except BaseException as exc:
            self._stop(exc)
            try:
                save(
                    self.root / (key + "-failure.json"),
                    {
                        "status": "NOT_RELEASED_TO_EXECUTOR",
                        "code": str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__,
                        "issues": getattr(exc, "issues", []),
                        "usage": "Retained raw HTTP/central usage; acceptance failure is not free",
                    },
                )
            except Exception as report_error:
                # The permanent stop already exists; never unlock to save a report.
                self.failure_report_error = type(report_error).__name__
            raise
        finally:
            self.pending_wire_hash = None

    def close(self) -> None:
        if self.closed:
            return
        try:
            self.provider.close()
        except BaseException as exc:
            self._stop(exc)
            raise
        finally:
            self.closed = True
