"""Exact-version triggers and proof-bound v18 recheck completion."""

from __future__ import annotations

from typing import Any

from milai_lab.baselines.langmem_revision_store import RevisionSidecar, canonical_json
from milai_lab.methods.milai_m1.decision_basis import DecisionDeltaError
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


def completion_proof(
    basis: dict[str, Any] | None, delta: dict[str, Any] | None,
    bound: list[dict[str, Any]], delivered: dict[str, dict[str, Any]],
    request_messages: list[dict[str, Any]],
    sidecar: RevisionSidecar, key: ScopeKey,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return acknowledged reasons and actual supporting refs, or reject a false completion.

    This checks delivery, declared role and exact revision. It does not judge whether
    the evidence semantically supports the proposition.
    """
    pending = basis["recheck_reasons"] if basis is not None else []
    if delta is None:
        return [], []
    outcome = delta.get("recheck_outcome")
    if not pending:
        if outcome is not None or delta.get("clear_reason") == "recheck_completed":
            raise DecisionDeltaError("DECISION_RECHECK_OUTCOME_WITHOUT_PENDING")
        return [], []
    if delta["op"] == "clear" and delta.get("clear_reason") == "task_ended":
        return [], []
    if delta["op"] == "clear" and delta.get("clear_reason") != "recheck_completed":
        raise DecisionDeltaError("DECISION_PENDING_CLEAR_INCOMPLETE")
    if outcome is None:
        raise DecisionDeltaError("DECISION_PENDING_RECHECK_OUTCOME_MISSING")
    if outcome == "unresolved":
        if delta["op"] != "set" or delta["status"] != "deferred":
            raise DecisionDeltaError("DECISION_UNRESOLVED_MUST_DEFER")
        return [], []
    if basis is None:
        raise DecisionDeltaError("DECISION_RECHECK_BASIS_MISSING")
    if outcome == "retained" and delta["proposition"] != basis["proposition"]:
        raise DecisionDeltaError("DECISION_RETAINED_PROPOSITION_CHANGED")
    if outcome == "changed" and delta["proposition"] == basis["proposition"]:
        raise DecisionDeltaError("DECISION_CHANGED_PROPOSITION_UNCHANGED")
    namespace = canonical_json(("langmem", key[0], key[1], key[2]))
    latest: dict[str, dict[str, Any]] = {}
    for row in sidecar.rows("revisions"):
        if row["namespace_json"] != namespace:
            continue
        memory_id = row["memory_id"]
        if memory_id not in latest or row["revision"] > latest[memory_id]["revision"]:
            latest[memory_id] = row

    def current_memory(item: dict[str, Any]) -> bool:
        if item["kind"] != "memory":
            return True
        memory_id, revision = item["ref"].removeprefix("memory:").rsplit("@", 1)
        current = latest.get(memory_id)
        return (current is not None and current["revision"] == int(revision)
                and not current["tombstone"]
                and current["content_sha256"] == item["content_sha256"])

    old_refs = {item["ref"] for item in basis["adopted_evidence"]}
    fresh = [item for item in bound
             if item["delivery"] != "continued_exact"
             and item["ref"] not in old_refs
             and item["support_role"] != "contextual"
             and item["ref"] in delivered and current_memory(item)]
    if not fresh:
        raise DecisionDeltaError("DECISION_RECHECK_CURRENT_EVIDENCE_MISSING")
    system = next((str(message.get("content", "")) for message in request_messages
                   if message.get("role") == "system"), "")
    proof_refs: set[str] = set()
    for reason in pending:
        adopted_memory = reason["adopted_ref"].split("@", 1)[0]
        minimum_revision = int(reason["current_ref"].rsplit("@", 1)[1])
        current = [item for item in fresh
                   if item["kind"] == "memory"
                   and item["ref"].split("@", 1)[0] == adopted_memory
                   and int(item["ref"].rsplit("@", 1)[1]) >= minimum_revision]
        if current:
            proof_refs.add(current[0]["ref"])
            continue
        independent = [item for item in fresh
                       if not (item["kind"] == "memory"
                               and item["ref"].split("@", 1)[0]
                               == adopted_memory)]
        if (not independent or (reason["kind"] == "deleted_or_tombstoned"
                                and canonical_json(reason) not in system)):
            raise DecisionDeltaError("DECISION_RECHECK_REASON_UNPROVEN")
        proof_refs.add(independent[0]["ref"])
    return pending, sorted(proof_refs)
