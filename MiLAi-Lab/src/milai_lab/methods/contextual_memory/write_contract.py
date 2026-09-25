"""Versioned ordinary write predicates and exact calendar-date inputs."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Any

WRITE_CONTRACT_VERSION = "contextual-write-contract-v13"

WRITE_RULES = (
    "Memory can preserve personal information, ongoing work matters and observed lessons. "
    "A supported decision or commitment can matter after this session even if temporary; "
    "use durable persistence and retain its status and scope. task persistence is only "
    "for disposable notes in the current session, not for every record about a task. "
    "Separate instructions from facts and updates actually stated with them. "
    "Record who a claim is about, one independently changeable matter, its current "
    "meaning and scope, evidence, and explicit certainty. Keep speaker, author, and "
    "subject distinct: a user's direct fact is not an author's experience, question, "
    "or suggestion. Write a self-contained claim of about 250 words or fewer, with "
    "its actual conditions; keep batch handles out of permanent prose. CREATE adds a "
    "new matter. REVISE only when subject and matter match a delivered exact version; "
    "prefer content_patch with exact old/new fragments for a local correction, so unchanged "
    "prose and complete lists remain intact; use full content when reorganization is needed. "
    "Full REVISE replaces source_refs and independent dependencies in full. For a local "
    "change to a fully delivered exact target, basis_mode=delta uses content_patch and "
    "source_delta/dependency_delta add/remove; old relationships are inherited without "
    "claiming their bodies were reread. Use full REVISE for metadata or global meaning changes. "
    "Preserve operational names, labels, identifiers, units and "
    "required literal text in their original language. Enumerated requirements must remain "
    "complete: a replacement includes the stated new item and every unaffected item. "
    "Compose the record in the source language unless translation is explicitly requested. "
    "RETAIN_SOURCE keeps original material without "
    "inventing an interpretation. NO_CHANGE is for a required proposal receipt; "
    "otherwise continue without a write. Directly stated content is explicit; marked "
    "interpretation is inferred; unresolved meaning is uncertain. One tool result "
    "does not establish a universal rule."
)


def apply_content_patch(
    text: str, patches: Sequence[Mapping[str, str]], *,
    visible_spans: Sequence[tuple[int, int]] | None = None,
) -> str:
    """Apply unambiguous nonoverlapping replacements against one exact original version."""
    if isinstance(patches, (str, bytes)) or not 1 <= len(patches) <= 8:
        raise ValueError("INVALID_CONTENT_PATCH")
    matches: list[tuple[int, int, str]] = []
    for patch in patches:
        if (not isinstance(patch, Mapping) or set(patch) != {"old", "new"}
                or not isinstance(patch["old"], str) or not patch["old"]
                or not isinstance(patch["new"], str)):
            raise ValueError("INVALID_CONTENT_PATCH")
        old = patch["old"]
        start = text.find(old)
        if start < 0:
            raise ValueError("CONTENT_PATCH_OLD_NOT_FOUND")
        if text.find(old, start + 1) >= 0:
            raise ValueError("CONTENT_PATCH_OLD_AMBIGUOUS")
        matches.append((start, start + len(old), patch["new"]))
    matches.sort()
    if any(left[1] > right[0] for left, right in pairwise(matches)):
        raise ValueError("CONTENT_PATCH_OVERLAP")
    if visible_spans is not None:
        covered: list[list[int]] = []
        for start, end in sorted(visible_spans):
            if not 0 <= start < end <= len(text):
                raise ValueError("CONTENT_PATCH_VISIBLE_RANGE_INVALID")
            if covered and start <= covered[-1][1]:
                covered[-1][1] = max(covered[-1][1], end)
            else:
                covered.append([start, end])
        if any(not any(low <= start and end <= high for low, high in covered)
               for start, end, _ in matches):
            raise ValueError("CONTENT_PATCH_OLD_NOT_DELIVERED")
    parts: list[str] = []
    cursor = 0
    for start, end, new in matches:
        parts.extend((text[cursor:start], new))
        cursor = end
    return "".join([*parts, text[cursor:]])


def normalize_basis_delta(
    old_refs: Sequence[str], delta: Mapping[str, Sequence[str]], *, kind: str,
) -> tuple[list[str], dict[str, list[str]]]:
    """Apply a relationship change to an exact version, retaining stable old order."""
    if not isinstance(delta, Mapping) or set(delta) != {"add", "remove"} or any(
        not isinstance(delta[key], list) or any(not isinstance(ref, str) for ref in delta[key])
        for key in ("add", "remove")
    ):
        raise ValueError(f"INVALID_{kind.upper()}_DELTA")
    old = list(dict.fromkeys(old_refs))
    added = list(dict.fromkeys(delta["add"]))
    removed = list(dict.fromkeys(delta["remove"]))
    if set(added) & set(removed):
        raise ValueError(f"{kind.upper()}_DELTA_OVERLAP")
    if not set(removed) <= set(old):
        raise ValueError(f"{kind.upper()}_DELTA_REMOVE_NOT_IN_TARGET")
    actual_add = [ref for ref in added if ref not in old]
    inherited = [ref for ref in old if ref not in removed]
    return [*inherited, *actual_add], {
        "inherited": inherited, "added": actual_add, "removed": removed,
    }


@dataclass(frozen=True)
class ConditionDefinition:
    meaning: str
    comparison: str = "exact"
    value_type: type = str


# Trusted generic definitions; proposals may use them but cannot add new keys.
CONDITION_DEFINITIONS = {
    "setting": ConditionDefinition("Environment in which the claim applies"),
}

_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def validate_conditions(value: dict[str, str] | None) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("INVALID_CLAIM_CONDITION")
    for key, item in value.items():
        definition = CONDITION_DEFINITIONS.get(key)
        if definition is None:
            raise ValueError("UNKNOWN_CONDITION_DEFINITION")
        if not isinstance(item, definition.value_type) or not item:
            raise ValueError("INVALID_CLAIM_CONDITION")


def validate_date(value: str | None, field: str) -> None:
    if value is None or value == "":
        return
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise ValueError(f"INVALID_{field.upper()}")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"INVALID_{field.upper()}") from error


def validate_changeset_fields(changeset: dict[str, Any]) -> None:
    for group in changeset.get("groups", []):
        for operation in group.get("operations", []):
            validate_conditions(operation.get("conditions"))
            validate_date(operation.get("valid_from"), "valid_from")
            validate_date(operation.get("valid_until"), "valid_until")


def ordinary_save_schema(parameters: dict[str, Any]) -> dict[str, Any]:
    """Select target and evidence before composing a replacement in ordered decoding."""
    branches = []
    delta_fields = {"basis_mode", "source_delta", "dependency_delta"}
    delta = deepcopy(parameters)
    delta["properties"] = {
        "op": {"const": "REVISE"},
        "basis_mode": {"const": "delta"},
        "target_ref": delta["properties"]["target_ref"],
        "content_patch": delta["properties"]["content_patch"],
        "source_delta": delta["properties"]["source_delta"],
        "dependency_delta": delta["properties"]["dependency_delta"],
    }
    delta["required"] = ["op", "basis_mode", "target_ref", "content_patch", "source_delta"]
    branches.append(delta)
    for op, required, allowed, leading in (
        ("CREATE", ["op", "about_ref", "source_refs", "certainty", "content"],
         set(parameters["properties"])
         - {"source_ref", "target_ref", "content_patch"} - delta_fields,
         ("about_ref", "source_refs", "certainty", "content")),
        ("REVISE", ["op", "target_ref", "about_ref", "source_refs", "dependencies",
                    "certainty", "content_patch"],
         set(parameters["properties"]) - {"source_ref", "content"} - delta_fields,
         ("target_ref", "about_ref", "source_refs", "dependencies", "certainty",
          "content_patch")),
        ("REVISE", ["op", "target_ref", "about_ref", "source_refs", "dependencies",
                    "certainty", "content"],
         set(parameters["properties"]) - {"source_ref", "content_patch"} - delta_fields,
         ("target_ref", "about_ref", "source_refs", "dependencies", "certainty", "content")),
        ("RETAIN_SOURCE", ["op", "source_ref"], {"op", "source_ref", "persistence"},
         ("source_ref",)),
        ("NO_CHANGE", ["op"], {"op"}, ()),
    ):
        branch = deepcopy(parameters)
        available = {
            key: value for key, value in branch["properties"].items()
            if key != "op" and key in allowed
        }
        branch["properties"] = {
            "op": {"const": op},
            **{key: available.pop(key) for key in leading},
            **available,
        }
        branch["required"] = required
        if op in {"CREATE", "REVISE"}:
            branch["properties"]["source_refs"] = {
                **branch["properties"]["source_refs"],
                "description": (
                    "Complete supporting sources for the entire replacement, including old "
                    "sources for retained historical details, not just the newest observation. "
                    "Omitted sources are not inherited. Assistant-generated text alone cannot "
                    "establish a durable fact about the current user."
                ),
            }
            if "content" in branch["properties"]:
                branch["properties"]["content"] = {
                    **branch["properties"]["content"],
                    "description": (
                        "Full current interpretation when local replacement cannot express the "
                        "change. Preserve exact labels and all unaffected requirements. Put "
                        "references in source_refs, not temporary handles in the prose."
                    ),
                }
            else:
                branch["properties"]["content_patch"]["description"] = (
                    "Replace exact old fragments of the delivered target version. Each old "
                    "fragment must occur exactly once; unchanged text remains verbatim. "
                    "Use this for localized corrections, including list-item changes."
                )
        branches.append(branch)
    return {"oneOf": branches}
