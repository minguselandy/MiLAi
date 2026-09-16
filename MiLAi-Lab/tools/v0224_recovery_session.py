"""Prospective D1: one predeclared publication and one genuine CAS rejection.

The given initial intent is mechanical calibration, not a natural task score.
The unchanged World commits the publication; no rejection or receipt is mocked.
"""

import copy
import json
import time

from v0213_provider import payload
from v0218_world import digest
from v0220_action_contract import ContractError
from v0220_evidence import save
from v0220_session import Session


class RecoverySession(Session):
    def __init__(self, *args, event, **kwargs):
        if kwargs.get("profile") != "RECOVERY_ORACLE" or kwargs.get("arm") != "ORACLE":
            raise ValueError("EXPLICIT_RECOVERY_ORACLE_PROFILE_REQUIRED")
        if type(event) is not dict or set(event) != {"event_id", "current"}:
            raise ValueError("EXACT_PREDECLARED_PUBLICATION_REQUIRED")
        self.event = copy.deepcopy(event)
        self.event_sha256 = digest(event)
        self.event_published = False
        self.expected_rejection_turn = None
        super().__init__(*args, **kwargs)
        save(self.directory / "recovery-stimulus-binding.json", self.event)

    def dispatch(self, action, turn):
        self.validate_runtime()
        if digest(self.event) != self.event_sha256:
            raise ValueError("RECOVERY_PUBLICATION_BINDING_DRIFT")
        if action["action"] in {"put_record", "request_clarification"} and not self.event_published:
            before = self.world.snapshot()
            published = self.world.publish(**self.event)
            self.event_published = True
            save(
                self.directory / "actual-recovery-publication.json",
                {
                    "turn": turn,
                    "event": self.event,
                    "receipt": published,
                    "before": before,
                    "after": self.world.snapshot(),
                    "origin": "PREDECLARED_HARNESS_EVENT_NOT_AGENT_TOOL",
                },
            )
        return super().dispatch(action, turn)

    def run(self, provider, *, deadline: float) -> dict:
        """Provider retains actual HTTP/usage ledger. No repair model or implicit retry.

        Dispatch publishes the frozen event before the first business attempt.
        Only the resulting first CAS rejection permits bounded recovery.
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
                finish_only = turn == self.cap or (
                    self.expected_rejection_turn is not None
                    and turn > self.expected_rejection_turn + 3
                )
                schema = self.contract.action_schema(finish_only=finish_only)
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
                    action = self.contract.decode(raw, finish_only=finish_only)
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
                    expected = (
                        code == "VERSION_CONFLICT"
                        and self.event_published
                        and self.expected_rejection_turn is None
                        and response.get("committed") is False
                        and response.get("business_effect") is False
                    )
                    if expected:
                        self.expected_rejection_turn = turn
                    else:
                        result.update(status="PROTOCOL_REJECTION_STOP", code=code)
                        self.stopped = True
                        break
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
            expected_error_exercised=self.expected_rejection_turn is not None,
            expected_rejection_turn=self.expected_rejection_turn,
            recovery_generation_cap_after_error=3,
        )
        save(self.directory / "session-result.json", result)
        return result
