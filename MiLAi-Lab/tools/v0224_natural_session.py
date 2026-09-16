"""Prospective D2 natural Host with the same typed review slot in both policies.

Only public task evidence is available. A brief ordinary review is part of the
same response as its business action, never a compulsory extra model call.
The original World, business contract, CAS, operation journal and receipts remain.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from pathlib import Path

from jsonschema import Draft202012Validator

from v0213_provider import payload
from v0218_policy_host import BASE_SYSTEM
from v0218_world import World, digest
from v0220_action_adapter import ActionAdapter
from v0220_action_contract import ContractError, unique_object
from v0220_evidence import save
from v0220_session import MECHANICS, PREFETCH, SessionContract, check_public

PROFILES = {"NATURAL_NO_CARRY": {"N0-exec": 16, "R0-exec": 16}}
REVIEW = (
    "Use the review field for a brief ordinary work summary of relevant observations "
    "and the action needed for this task before a business mutation. The review and "
    "action belong to the same response. This is a concise work summary, not a hidden "
    "reasoning transcript. No separate review call or Note write is required."
)
NEUTRAL = "The review field is available for an optional brief work summary; it may be empty."


def system_for(profile, arm):
    if arm not in PROFILES.get(profile, {}):
        raise ValueError("NATURAL_NO_CARRY_PROFILE_REQUIRED")
    return "\n".join(
        [
            BASE_SYSTEM,
            MECHANICS,
            "No prior-session Note is inherited. The optional notebook is LOCAL_SESSION_ONLY, "
            "not Product memory and not available to later sessions.",
            "Every response has action, arguments and a review string. The review is advisory, "
            "not a business command or authority; an empty review is allowed.",
            REVIEW if arm == "R0-exec" else NEUTRAL,
        ]
    )


def review_schema(business_schema):
    result = copy.deepcopy(business_schema)
    for branch in result["anyOf"]:
        branch["properties"]["review"] = {"type": "string", "maxLength": 1024}
        branch["required"].append("review")
    return result


def decode_envelope(raw, contract, *, finish_only=False):
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, TypeError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("INVALID_JSON") from None
    try:
        json.dumps(value, allow_nan=False)
        check_public(value)
    except (ValueError, TypeError):
        raise ContractError("NONPUBLIC_OR_NONFINITE") from None
    if list(
        Draft202012Validator(
            review_schema(contract.action_schema(finish_only=finish_only))
        ).iter_errors(value)
    ):
        raise ContractError("REVIEW_ACTION_ENVELOPE_SCHEMA")
    # Explicit envelope decomposition; no business value, target or version is changed.
    action = {key: value[key] for key in ("action", "arguments")}
    return value["review"], contract.validate(action, finish_only=finish_only)


class NaturalSession:
    def __init__(
        self,
        world: World,
        directory: Path,
        *,
        episode_id: str,
        profile: str,
        arm: str,
        intent: dict | None = None,
        forbidden_literals: tuple[str, ...] = (),
        validate_binding: Callable[[], None],
        prior_rejection_counts: dict[str, int] | None = None,
    ):
        self.system = system_for(profile, arm)
        if not episode_id or (profile == "NATURAL_NO_CARRY") != (intent is None):
            raise ValueError("ORACLE_NATURAL_INPUT_ISOLATION")
        validate_binding()
        self.validate_binding = validate_binding
        self.world, self.directory = world, directory
        self.episode_id, self.profile, self.arm = episode_id, profile, arm
        self.binding = (episode_id, profile, arm)
        self.rejection_counts = dict(prior_rejection_counts or {})
        self.last_rejection_signature = None
        self.consecutive_rejections = 0
        self.forbidden_literals = forbidden_literals
        self.contract = SessionContract.from_public(
            world.snapshot(), enable_note=profile == "NATURAL_NO_CARRY"
        )
        self.adapter = ActionAdapter(world, self.contract)
        if self.adapter.journal.unresolved():
            raise ValueError("UNRESOLVED_COMMIT_NO_NEW_SESSION")
        self.cap = PROFILES[profile][arm]
        self.notes, self.rows, self.observations = [], [], []
        self.finished, self.stopped = False, False
        self.last_observation = None
        self.scope = world.scope
        self.world_path = world.path.resolve()
        self.contract_fingerprint = self.contract.fingerprint
        self.guard(world.snapshot())
        self.guard(intent)
        # Fresh directory prevents accidental continuation or cross-arm cache reuse.
        directory.mkdir(parents=True, exist_ok=False)
        save(
            directory / "session-binding.json",
            {
                "episode_id": episode_id,
                "scope": self.scope,
                "world_path": str(self.world_path),
                "profile": profile,
                "arm": arm,
                "contract_sha256": self.contract_fingerprint,
                "inherited_note": False,
                "carrier": "LOCAL_SESSION_ONLY" if self.contract.enable_note else "NONE",
            },
        )
        before = digest(world.snapshot())
        for resource in PREFETCH:
            response = self.adapter.read(resource)
            self.guard(response)
            self.observe(response)
            self.observations.append(response)
        if digest(world.snapshot()) != before:
            raise ValueError("PREFETCH_NOT_SINGLE_STABLE_WORLD")
        initial = {
            "profile": profile,
            "contract": self.contract.documents(),
            "origin": "HARNESS_PUBLIC_PREFETCH",
            "observations": self.observations,
            "inherited_note": None,
            "review_envelope": "SAME_CALL_REVIEW_V1",
        }
        if intent is not None:
            initial["authorized_intent"] = copy.deepcopy(intent)
        self.messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": json.dumps(initial, ensure_ascii=False)},
        ]
        self.guard(initial)
        save(directory / "initial-presentation.json", initial)

    def guard(self, value: object) -> None:
        check_public(value, self.forbidden_literals)

    def validate_runtime(self) -> None:
        self.validate_binding()
        if (
            self.world.scope != self.scope
            or self.world.path.resolve() != self.world_path
            or self.adapter.world is not self.world
            or self.contract.fingerprint != self.contract_fingerprint
            or self.system != system_for(self.profile, self.arm)
            or (self.episode_id, self.profile, self.arm) != self.binding
        ):
            raise ValueError("SESSION_BINDING_DRIFT")
        self.adapter._verify_contract()
        self.guard(self.world.snapshot())

    def observe(self, response: dict) -> None:
        if response["status"] in {"PUBLIC_OBSERVATION", "ACTION_EXECUTED_LOCAL_WORLD"}:
            self.last_observation = {
                "version": response["version"],
                "version_domain": "WORLD",
                "source": response["status"],
                "response_sha256": digest(response),
            }

    def dispatch(self, action: dict, turn: int) -> dict:
        self.validate_runtime()
        if self.stopped or self.finished or self.adapter.journal.unresolved():
            raise ValueError("SESSION_STOPPED_NO_NEW_ACTION")
        self.guard(action)
        value = self.contract.validate(action)
        name, args = value["action"], value["arguments"]
        if name in {"put_record", "request_clarification"}:
            response = self.adapter.execute(value, operation_id=f"{self.episode_id}:{turn:02d}")
        elif name == "read":
            response = self.adapter.read(args["resource"])
        elif name == "operation_status":
            response = self.adapter.operation_status(args["operation_id"])
        else:
            response = {
                "version_domain": "SESSION",
                "committed": False,
                "business_effect": False,
                "task_outcome": "NOT_EVALUATED",
                "status": "SESSION_FINISHED",
            }
            if name == "save_note":
                note = {"content": args["note"], "sequence": len(self.notes) + 1}
                save(self.directory / f"note-{note['sequence']:02d}.json", note)
                self.notes.append(note)
                response.update(
                    status="LOCAL_SESSION_NOTE_SAVED",
                    carrier="LOCAL_SESSION_ONLY",
                    note_saved=True,
                    note_sequence=note["sequence"],
                    content_sha256=digest(args["note"]),
                )
            else:
                self.finished = True
        response = self.contract.validate_response(response)
        self.guard(response)
        if response["status"] == "COMMIT_UNKNOWN":
            self.stopped = True
        self.observe(response)
        return response

    def run(self, provider, *, deadline: float) -> dict:
        """Provider retains actual HTTP/usage ledger. No repair model or implicit retry.

        Recovery stimuli are not synthesized here; a frozen runner must arrange them.
        The current entry stops on every unexpected contract rejection. A later V3
        wrapper must explicitly account for its one expected rejection before use.
        """
        result = {
            "status": "INCOMPLETE",
            "profile": self.profile,
            "arm": self.arm,
            "episode_id": self.episode_id,
            "task_outcome": "NOT_EVALUATED",
        }
        try:
            self.validate_runtime()
            provider.verify()
            for turn in range(1, self.cap + 1):
                self.validate_runtime()
                if self.stopped or self.adapter.journal.unresolved():
                    result["status"] = "COMMIT_UNKNOWN_STOP"
                    break
                if time.monotonic() >= deadline:
                    result["status"] = "EPISODE_DEADLINE"
                    break
                schema = review_schema(self.contract.action_schema(finish_only=turn == self.cap))
                body = payload(
                    [
                        *self.messages,
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "remaining_generation_opportunities": self.cap + 1 - turn,
                                    "final_delivery_reservation": 1,
                                    "last_completed_public_observation": self.last_observation,
                                }
                            ),
                        },
                    ],
                    schema,
                )
                self.guard(body)
                raw = provider.generate(self.episode_id, body)
                self.guard(raw)
                row = {"turn": turn, "raw": raw, "before_sha256": digest(self.world.snapshot())}
                try:
                    review, action = decode_envelope(
                        raw, self.contract, finish_only=turn == self.cap
                    )
                    row["review"] = review
                except ContractError as exc:
                    response = self.adapter.rejected(
                        exc.code, operation_id=None, path=exc.path, rule=exc.rule
                    )
                    row["dispatch_attempted"] = False
                else:
                    # Save exact original intent before dispatch. A lost receipt is not lost intent.
                    save(self.directory / f"intent-{turn:02d}.json", action)
                    row["action"] = action
                    row["dispatch_attempted"] = True
                    response = self.dispatch(action, turn)
                row.update(response=response, after_sha256=digest(self.world.snapshot()))
                save(self.directory / f"turn-{turn:02d}.json", row)
                self.rows.append(row)
                self.messages.extend(
                    [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": json.dumps({"tool_result": response})},
                    ]
                )
                if response["status"] == "COMMIT_UNKNOWN":
                    result["status"] = "COMMIT_UNKNOWN_STOP"
                    break
                if response["status"] == "ACTION_REJECTED":
                    code = response["code"]
                    self.rejection_counts[code] = self.rejection_counts.get(code, 0) + 1
                    signature = digest({key: response.get(key) for key in ("code", "path", "rule")})
                    self.consecutive_rejections = (
                        self.consecutive_rejections + 1
                        if signature == self.last_rejection_signature
                        else 1
                    )
                    self.last_rejection_signature = signature
                    if self.consecutive_rejections >= 2:
                        result.update(status="PROTOCOL_REJECTION_STOP", code=code)
                        self.stopped = True
                        break
                else:
                    self.last_rejection_signature = None
                    self.consecutive_rejections = 0
                if self.finished:
                    result["status"] = "SESSION_FINISHED_NOT_TASK_VERDICT"
                    break
            else:
                result["status"] = "GENERATION_LIMIT"
        except Exception as exc:
            # Provider retains its HTTP and reservations. Do not echo exception bodies.
            self.stopped = True
            result.update(status="FAIL_CLOSED", exception_type=type(exc).__name__)
        finally:
            self.stopped = True
            try:
                provider.close()
            except Exception as exc:
                result.update(close_exception_type=type(exc).__name__)
        result.update(
            completed_turns=len(self.rows),
            note_writes=len(self.notes),
            rejection_counts=self.rejection_counts,
            rejection_signature_fields=["code", "path", "rule"],
            consecutive_rejections=self.consecutive_rejections,
        )
        save(self.directory / "session-result.json", result)
        return result
