"""Small shared types for the Lab contextual memory method."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast


@dataclass(frozen=True)
class Observation:
    event_id: str
    content: str
    role: str
    artifact: str
    session_id: str = ""
    date: str = ""
    supersedes: str = ""
    actor_ref: str = ""


@dataclass
class Interpretation:
    author: str
    subject: str = ""
    about_ref: str = "unresolved"
    context: str = ""
    certainty: str = "explicit"
    persistence: str = "durable"
    dependencies: list[str] = field(default_factory=list)
    conditions: dict[str, str] = field(default_factory=dict)
    valid_from: str = ""
    valid_until: str = ""
    known_at: str = ""
    uncertain_start: bool = False
    uncertain_end: bool = False
    basis_change: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    task_id: str
    context: str = ""
    subject: str = "current_user"
    uncertainty: str = ""
    intentions: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    recent_refs: list[str] = field(default_factory=list)
    unavailable_refs: list[str] = field(default_factory=list)
    coverage: Literal["SUFFICIENT", "GAP", "UNKNOWN"] = "UNKNOWN"
    conditions: dict[str, str] = field(default_factory=dict)
    query_context: dict[str, Any] = field(default_factory=dict)
    valid_at: str = ""
    known_at: str = ""
    overrides: dict[str, dict[str, str]] = field(default_factory=dict)


Completion = Literal["complete", "partial_failure", "failed", "pending"]


@dataclass(frozen=True)
class ReceiptOutcome:
    """Actual completed parts of one memory operation, not a truth judgment."""

    completion: Completion
    succeeded: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    usable_refs: tuple[str, ...] = ()
    operation_id: str = ""
    decision: Literal["REJECTED", "NO_CHANGE", "COMMITTED", "PARTIAL"] = "NO_CHANGE"
    memory_changes: tuple[str, ...] = ()
    cleanup_effects: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.completion == "complete"


_SAVE_SUCCESS = {"source": {"RETAINED", "TASK_ONLY"}, "record": {"SAVED", "REUSED"}}
_INCOMPLETE = {"ERROR", "VERSION_CONFLICT", "PARTIAL", "PENDING"}


def receipt_outcome(name: str, result: dict[str, Any]) -> ReceiptOutcome:
    """Interpret only the declared status fields of a memory tool receipt.

    ``dependency_status`` in a read or search result describes material and is
    deliberately not treated as an operation failure.
    """
    succeeded: list[str] = []
    failed: list[str] = []
    pending: list[str] = []
    usable_refs: list[str] = []
    status = result.get("status")

    if name == "memory_save":
        if status == "NO_CHANGE":
            pass
        elif status == "FORGOTTEN":
            if result.get("memory_changes"):
                succeeded.append("forget")
            else:
                failed.append("operation:EMPTY_FORGOTTEN_RECEIPT")
            pending.extend(result.get("cleanup_effects", []))
        else:
            for part, valid in _SAVE_SUCCESS.items():
                section = result.get(part)
                if not isinstance(section, dict):
                    continue
                part_status = section.get("status")
                if part_status in valid:
                    succeeded.append(part)
                    if isinstance(section.get("ref"), str):
                        usable_refs.append(section["ref"])
                elif part_status == "PENDING":
                    pending.append(part)
                else:
                    failed.append(f"{part}:{part_status or 'MISSING_STATUS'}")
            changeset = result.get("changeset")
            if isinstance(changeset, dict):
                pending.extend(f"maintenance:{ref}" for ref in changeset.get("pending_refs", []))
                if not changeset.get("groups"):
                    succeeded.append("changeset")
                for index, group in enumerate(changeset.get("groups", [])):
                    group_status = group.get("status")
                    if group_status == "APPLIED":
                        succeeded.append(f"group:{index}")
                        usable_refs.extend(group.get("usable_refs", []))
                    elif group_status == "PENDING":
                        pending.append(f"group:{index}")
                    else:
                        failed.append(f"group:{index}:{group_status or 'MISSING_STATUS'}")
            if status == "PENDING":
                pending.append("operation")
            elif status in {"ERROR", "VERSION_CONFLICT", "PARTIAL"}:
                failed.append(f"operation:{status}")
            elif status is not None:
                failed.append(f"operation:{status}")
            elif not succeeded and not failed and not pending:
                failed.append("operation:MISSING_RESULT")
    elif name in {"memory_read", "memory_search", "memory_state"}:
        if status == "PENDING":
            pending.append("operation")
        elif status in _INCOMPLETE:
            failed.append(f"operation:{status}")
        elif name == "memory_state" and status != "UPDATED":
            failed.append(f"operation:{status or 'MISSING_STATUS'}")
        elif name == "memory_read" and (
            status not in {None, "CURRENT", "SUPERSEDED"}
            or not isinstance(result.get("ref"), str)
            or result.get("kind") not in {"source", "interpretation"}
        ):
            failed.append("operation:INVALID_READ_RESULT")
        elif name == "memory_search" and (
            status is not None or not isinstance(result.get("materials"), list)
        ):
            failed.append("operation:INVALID_SEARCH_RESULT")
        else:
            succeeded.append(name.removeprefix("memory_"))
            if name == "memory_read":
                for key in ("ref", "current_ref"):
                    if isinstance(result.get(key), str):
                        usable_refs.append(result[key])
            elif name == "memory_search":
                for key in ("materials", "expanded_materials"):
                    for item in result.get(key, []):
                        if isinstance(item, dict) and isinstance(item.get("ref"), str):
                            usable_refs.append(item["ref"])
    else:
        failed.append("operation:UNKNOWN_MEMORY_TOOL")

    if failed:
        completion: Completion = "partial_failure" if succeeded else "failed"
    elif pending:
        completion = "pending"
    else:
        completion = "complete"
    decision = result.get("decision")
    if decision not in {"REJECTED", "NO_CHANGE", "COMMITTED", "PARTIAL"}:
        decision = (
            "PARTIAL" if failed and succeeded else
            "REJECTED" if failed else
            "COMMITTED" if succeeded else "NO_CHANGE"
        )
    if result.get("completion") == "pending" and not failed:
        completion = "pending"
    return ReceiptOutcome(
        completion,
        tuple(succeeded),
        tuple(failed),
        tuple(pending),
        tuple(dict.fromkeys(usable_refs)),
        result.get("operation_id", ""),
        cast(Literal["REJECTED", "NO_CHANGE", "COMMITTED", "PARTIAL"], decision),
        tuple(result.get("memory_changes", ())),
        tuple(result.get("cleanup_effects", ())),
    )
