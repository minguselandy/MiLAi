"""Persistent support relations and their direct reverse indexes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Polarity = Literal["support", "oppose"]


@dataclass(frozen=True)
class SupportItem:
    ref: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class Justification:
    group_id: str
    target_ref: str
    polarity: Polarity
    items: tuple[SupportItem, ...]
    conditions: dict[str, str] = field(default_factory=dict)
    valid_from: str = ""
    valid_until: str = ""
    known_at: str = ""
    withdrawn_at: str = ""


@dataclass
class RevisionStore:
    groups: dict[str, Justification] = field(default_factory=dict)
    by_source: dict[str, set[str]] = field(default_factory=dict)
    by_claim: dict[str, set[str]] = field(default_factory=dict)
    by_target: dict[str, set[str]] = field(default_factory=dict)
    changesets: list[dict[str, Any]] = field(default_factory=list)
    next_group: int = 1
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, group: Justification) -> None:
        self.groups[group.group_id] = group
        self.by_target.setdefault(group.target_ref, set()).add(group.group_id)
        for item in group.items:
            index = self.by_source if "/source:" in item.ref else self.by_claim
            index.setdefault(item.ref, set()).add(group.group_id)

    def rebuild(self) -> None:
        groups = list(self.groups.values())
        self.groups.clear()
        self.by_source.clear()
        self.by_claim.clear()
        self.by_target.clear()
        for group in groups:
            self.add(group)

    def remove(self, group_id: str) -> None:
        self.groups.pop(group_id)
        self.rebuild()

    def prune_refs(self, removed: set[str]) -> None:
        self.pending = {
            ref: item for ref, item in self.pending.items()
            if ref not in removed and not set(item["reason_refs"]) & removed
        }
        self.groups = {
            key: group for key, group in self.groups.items()
            if group.target_ref not in removed
            and all(item.ref not in removed for item in group.items)
        }
        self.rebuild()
        self.changesets = [
            entry for entry in self.changesets
            if not any(ref in removed for ref in entry.get("reason_refs", []))
            and not any(ref in removed for ref in entry["outcome"].get("aliases", {}).values())
            and not any(
                any(operation.get(key) in removed for key in (
                    "ref", "target_ref", "old_ref", "closed_ref", "new_ref",
                ))
                for operation in entry["outcome"]["operations"]
            )
        ]

    def dump(self, available: set[str], *, include_task: bool = False) -> dict[str, Any]:
        groups = {
            key: asdict(group)
            for key, group in self.groups.items()
            if group.target_ref in available
            and all(item.ref in available for item in group.items)
        }
        return {
            "groups": groups,
            "changesets": [
                entry for entry in self.changesets
                if include_task or not any(
                    operation["op"] == "task_override"
                    for operation in entry["outcome"]["operations"]
                )
                if all(ref in available for ref in entry["reason_refs"])
                and all(ref in available for ref in entry["outcome"].get("aliases", {}).values())
                and all(
                    all(
                        not operation.get(key) or operation[key] in available
                        for key in ("ref", "target_ref", "old_ref", "closed_ref", "new_ref")
                    )
                    for operation in entry["outcome"]["operations"]
                )
            ],
            "next_group": self.next_group,
            "pending": {ref: item for ref, item in self.pending.items() if ref in available
                        and set(item["reason_refs"]) <= available},
        }

    @classmethod
    def load(cls, value: dict[str, Any]) -> RevisionStore:
        store = cls(next_group=value["next_group"], changesets=value["changesets"],
                    pending=value["pending"])
        for key, entry in value["groups"].items():
            group = Justification(
                group_id=key,
                target_ref=entry["target_ref"],
                polarity=entry["polarity"],
                items=tuple(SupportItem(**item) for item in entry["items"]),
                conditions=dict(entry["conditions"]),
                valid_from=entry["valid_from"],
                valid_until=entry["valid_until"],
                known_at=entry["known_at"],
                withdrawn_at=entry["withdrawn_at"],
            )
            store.add(group)
        return store
