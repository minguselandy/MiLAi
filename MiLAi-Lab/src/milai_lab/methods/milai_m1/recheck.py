"""Exact-version triggers and proof-bound acknowledgements for M1."""

from __future__ import annotations

from typing import Any

from milai_lab.baselines.langmem_revision_store import RevisionSidecar, canonical_json
from milai_lab.methods.milai_m1.state_store import DecisionBasisStore, ScopeKey


def refresh_rechecks(
    store: DecisionBasisStore, sidecar: RevisionSidecar, key: ScopeKey,
) -> None:
    basis = store.get(key)
    if basis is None:
        return
    namespace = canonical_json(("langmem", key[0], key[1], key[2]))
    revisions = [row for row in sidecar.rows("revisions")
                 if row["namespace_json"] == namespace]
    newest: dict[str, dict[str, Any]] = {}
    for row in revisions:
        memory_id = row["memory_id"]
        if memory_id not in newest or row["revision"] > newest[memory_id]["revision"]:
            newest[memory_id] = row
    for binding in basis["adopted_bindings"]:
        if binding["kind"] != "memory":
            continue
        ref = binding["ref"]
        prefix, revision_text = ref.rsplit("@", 1)
        memory_id = prefix.removeprefix("memory:")
        latest = newest.get(memory_id)
        if latest is None or int(latest["revision"]) <= int(revision_text):
            continue
        store.add_reason(key, {
            "kind": "deleted_or_tombstoned" if latest["tombstone"] else "revision_changed",
            "adopted_ref": ref,
            "current_ref": f"memory:{memory_id}@{latest['revision']}",
            "current_content_sha256": latest["content_sha256"],
        })


def acknowledgements(
    basis: dict[str, Any] | None, delta: dict[str, Any] | None,
    delivered: dict[str, dict[str, Any]], request_messages: list[dict[str, Any]],
    current_user_ref: str | None,
) -> list[dict[str, Any]]:
    if basis is None or delta is None:
        return []
    system = next((str(message.get("content", "")) for message in request_messages
                   if message.get("role") == "system"), "")
    acknowledged = []
    for reason in basis["recheck_reasons"]:
        kind = reason["kind"]
        if kind == "revision_changed":
            material = delivered.get(reason["current_ref"])
            if (material is not None and material["content_sha256"]
                    == reason["current_content_sha256"]):
                acknowledged.append(reason)
        elif kind == "deleted_or_tombstoned":
            if canonical_json(reason) in system:
                acknowledged.append(reason)
        elif kind == "task_identity_changed":
            if current_user_ref is not None and canonical_json(reason) in system:
                acknowledged.append(reason)
    return acknowledged
