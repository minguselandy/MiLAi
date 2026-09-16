"""Version-bound use evidence, separate from correctness or causal attribution.

This is a Lab artifact stored in the existing bank transaction. Requests must be
confirmed by the runner, not merely assembled or selected. A task outcome belongs
to its ordered exposure sequence; no per-card reward is manufactured from it.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from typing import Any

from milai_lab.methods.controlled_workspace import MemoryCard

UTILITY_FORMAT = "experience-version-utility-v1"


def version_key(handle: str, revision: int) -> str:
    if not handle or type(revision) is not int or revision < 1:
        raise ValueError("INVALID_UTILITY_VERSION")
    return f"{handle}@{revision}"


class VersionUtility:
    """Mutate only a caller-owned task overlay, committed with the experience bank."""

    def __init__(self, state: dict[str, Any]) -> None:
        if not state:
            state.update(format=UTILITY_FORMAT, versions={}, tasks={})
        if state.get("format") != UTILITY_FORMAT:
            raise ValueError("UTILITY_FORMAT_MISMATCH")
        self.state = state

    def validate(
        self,
        cards: dict[str, MemoryCard],
        historical_cards: dict[str, dict[str, Any]],
        completed_tasks: list[str],
    ) -> None:
        available = {version_key(c.handle, c.revision): c for c in cards.values()}
        available.update({ref: MemoryCard(**card) for ref, card in historical_cards.items()})
        for key, record in self.state["versions"].items():
            if key not in available or key != version_key(record["memory_ref"], record["revision"]):
                raise ValueError("UTILITY_BANK_VERSION_MISMATCH")
            self.register(available[key])
            parent = record["predecessor"]
            if parent is not None and parent not in self.state["versions"]:
                raise ValueError("UTILITY_PREDECESSOR_MISSING")
        if not self.state["tasks"].keys() <= set(completed_tasks):
            raise ValueError("UTILITY_COMPLETED_POSITION_MISMATCH")
        for task_id, row in self.state["tasks"].items():
            if row["task_id"] != task_id or row["feedback_regime"] not in {"H", "R"}:
                raise ValueError("UTILITY_TASK_BINDING_MISMATCH")
            if row["native_result"] is not None and (
                type(row["native_result"]) is not bool
                or row["feedback_regime"] == "H"
                or (
                    row["scope"].get("split") == "TEST"
                    and row["scope"].get("protocol") in {"F", "G"}
                )
            ):
                raise ValueError("NATIVE_RESULT_NOT_ALLOWED_FOR_METHOD")
            for request in row["exposures"]:
                if any(
                    version_key(v["memory_ref"], v["revision"]) not in available
                    for v in request["versions"]
                ):
                    raise ValueError("UTILITY_EXPOSED_VERSION_UNKNOWN")

    def register(
        self,
        card: MemoryCard,
        *,
        predecessor: str | None = None,
        reason: str = "",
        feedback_refs: tuple[str, ...] = (),
    ) -> str:
        key = version_key(card.handle, card.revision)
        signature = hashlib.sha256(
            json.dumps(asdict(card), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        versions = self.state["versions"]
        if key in versions:
            if versions[key]["card_sha256"] != signature:
                raise ValueError("UTILITY_VERSION_CONTENT_CHANGED")
            return key
        if predecessor is not None and predecessor not in versions:
            raise ValueError("UTILITY_PREDECESSOR_MISSING")
        versions[key] = {
            "memory_ref": card.handle,
            "revision": card.revision,
            "card_sha256": signature,
            "predecessor": predecessor,
            "reason": reason,
            "feedback_refs": list(feedback_refs),
            "cold_start": "uncalibrated; retain predecessor evidence; no extra exploration",
        }
        return key

    def confirm(
        self,
        sequence: list[dict[str, Any]],
        *,
        receipt: dict[str, Any],
        versions: list[tuple[str, int]],
        task_id: str,
    ) -> None:
        if (
            receipt.get("session") != task_id
            or receipt.get("role") != "actor"
            or receipt.get("status") != "SETTLED"
            or not isinstance(receipt.get("request_id"), str)
            or not receipt["request_id"]
            or not isinstance(receipt.get("payload_sha256"), str)
            or len(receipt["payload_sha256"]) != 64
        ):
            raise ValueError("UTILITY_REQUIRES_CONFIRMED_ACTOR_REQUEST")
        if any(x["request_id"] == receipt["request_id"] for x in sequence):
            raise ValueError("UTILITY_REQUEST_ALREADY_CONFIRMED")
        keys = [version_key(ref, rev) for ref, rev in versions]
        if not set(keys) <= self.state["versions"].keys():
            raise ValueError("UTILITY_EXPOSED_VERSION_UNKNOWN")
        sequence.append(
            {
                "request_id": receipt["request_id"],
                "payload_sha256": receipt["payload_sha256"],
                "versions": [{"memory_ref": ref, "revision": rev} for ref, rev in versions],
            }
        )

    def finish(
        self,
        *,
        task_id: str,
        scope: dict[str, str],
        selector_version: str,
        feedback_regime: str,
        sequence: list[dict[str, Any]],
        result_ref: str,
        native_result: bool | None,
        costs: dict[str, Any],
        decision_ref: str,
    ) -> dict[str, Any]:
        if feedback_regime not in {"H", "R"}:
            raise ValueError("UNKNOWN_UTILITY_FEEDBACK_REGIME")
        reward_allowed = feedback_regime == "R" and not (
            scope.get("split") == "TEST" and scope.get("protocol") in {"F", "G"}
        )
        if native_result is not None and (type(native_result) is not bool or not reward_allowed):
            raise ValueError("NATIVE_RESULT_NOT_ALLOWED_FOR_METHOD")
        if not result_ref or not selector_version or not decision_ref:
            raise ValueError("UTILITY_REQUIRES_RESULT_AND_DECISION_BINDING")
        if task_id in self.state["tasks"]:
            raise ValueError("UTILITY_TASK_ALREADY_COMMITTED")
        combinations = {
            tuple(sorted((v["memory_ref"], v["revision"]) for v in request["versions"]))
            for request in sequence
        }
        row = {
            "scope": copy.deepcopy(scope),
            "task_id": task_id,
            "selector_version": selector_version,
            "feedback_regime": feedback_regime,
            "decision_ref": decision_ref,
            "exposures": copy.deepcopy(sequence),
            "attribution": "ordered_sequence_only" if len(combinations) > 1 else "single_bundle",
            "result_ref": result_ref,
            "native_result": native_result,
            "signal": "native_result" if native_result is not None else "visible_evidence_only",
            "costs": copy.deepcopy(costs),
        }
        self.state["tasks"][task_id] = row
        return copy.deepcopy(row)

    def selection_view(self, versions: dict[str, int], *, limit: int = 4) -> dict[str, Any]:
        """Bounded observations, never an average reward assigned to each card.

        Predecessor evidence remains discoverable after rewriting. Its result is
        explicitly historical, and does not calibrate the new text.
        """
        keys = {version_key(ref, rev) for ref, rev in versions.items()}
        lineage = set(keys)
        pending = list(keys)
        while pending:
            parent = self.state["versions"].get(pending.pop(), {}).get("predecessor")
            if parent and parent not in lineage:
                lineage.add(parent)
                pending.append(parent)
        related = []
        for row in self.state["tasks"].values():
            exposed = {
                version_key(v["memory_ref"], v["revision"])
                for request in row["exposures"]
                for v in request["versions"]
            }
            if exposed & lineage:
                related.append(
                    {
                        "decision_ref": row["decision_ref"],
                        "result_ref": row["result_ref"],
                        "exposed_versions": sorted(exposed),
                        "contains_current_versions": bool(exposed & keys),
                        "native_result": row["native_result"],
                        "feedback_regime": row["feedback_regime"],
                        "attribution": row["attribution"],
                        "costs": row["costs"],
                    }
                )
        return {
            "versions": {key: copy.deepcopy(self.state["versions"][key]) for key in sorted(keys)},
            "recent_related_sequences": related[-limit:],
            "related_sequences": len(related),
            "interpretation": (
                "Association, not causal contribution. Predecessor scores do not transfer."
            ),
        }
