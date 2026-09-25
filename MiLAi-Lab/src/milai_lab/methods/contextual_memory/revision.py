"""Local ChangeSet commits and exact-version support evaluation."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from .query_context import scope_result
from .store import Justification, SupportItem

if TYPE_CHECKING:
    from milai_lab.methods.contextual_user_memory import ContextualMemory


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _group_status(
    memory: ContextualMemory, group: Justification, *, valid_at: str,
    known_at: str, seen: set[str], scope: str,
) -> str:
    if group.withdrawn_at and (not known_at or group.withdrawn_at <= known_at):
        return "UNUSABLE"
    if known_at and group.known_at > known_at:
        return "UNUSABLE"
    if scope == "UNUSABLE":
        return scope
    pending = scope == "PENDING"
    for item in group.items:
        ref = item.ref
        if ref in memory.sources:
            try:
                current = memory.resolve_at(ref, known_at)
            except ValueError:
                return "UNUSABLE"
            if current != ref:
                return "UNUSABLE"
            continue
        try:
            if memory.resolve_at(ref, known_at) != ref:
                return "UNUSABLE"
        except (KeyError, ValueError):
            return "UNUSABLE"
        applicability = memory.claim_applicability(ref, valid_at=valid_at, known_at=known_at)
        if applicability == "UNUSABLE":
            return "UNUSABLE"
        if applicability == "PENDING":
            pending = True
        child = support_view(memory, ref, valid_at=valid_at, known_at=known_at, seen=seen)
        state = child["support_status"]
        if state == "UNUSABLE":
            return "UNUSABLE"
        if state != "USABLE":
            pending = True
    return "PENDING" if pending else "USABLE"


def support_view(
    memory: ContextualMemory, ref: str, *, valid_at: str = "",
    known_at: str = "", seen: set[str] | None = None,
) -> dict[str, Any]:
    """Keep support, opposition, applicability and existence separate."""
    if seen is None:
        seen = set()
    if ref in seen:
        return {"support_status": "PENDING", "opposition_status": "UNSUPPORTED", "disputed": False,
                "justifications": []}
    seen = seen | {ref}
    groups = [
        memory.revisions.groups[key]
        for key in sorted(memory.revisions.by_target.get(ref, set()))
        if not known_at or memory.revisions.groups[key].known_at <= known_at
    ]
    by_polarity: dict[str, list[str]] = {"support": [], "oppose": []}
    items: list[dict[str, Any]] = []
    for group in groups:
        scope = scope_result(
            group.conditions, group.valid_from, group.valid_until,
            memory.state.query_context, memory.state.conditions, valid_at,
        )
        status = _group_status(
            memory, group, valid_at=valid_at, known_at=known_at,
            seen=seen, scope=scope["status"],
        )
        by_polarity[group.polarity].append(status)
        group_view = asdict(group)
        if known_at and group.withdrawn_at > known_at:
            group_view["withdrawn_at"] = ""
        items.append({
            **group_view, "status": status,
            "scope_status": scope["status"], "scope_reasons": scope["reasons"],
        })

    def aggregate(values: list[str]) -> str:
        if "USABLE" in values:
            return "USABLE"
        if "PENDING" in values:
            return "PENDING"
        return "UNUSABLE" if values else "UNSUPPORTED"

    positive = aggregate(by_polarity["support"])
    negative = aggregate(by_polarity["oppose"])
    return {
        "support_status": positive,
        "opposition_status": negative,
        "disputed": negative == "USABLE",
        "justifications": items,
    }


def affected_claims(memory: ContextualMemory, refs: set[str]) -> list[str]:
    """Follow only declared direct reverse relations, including alternate paths."""
    pending = list(refs)
    touched: set[str] = set()
    while pending:
        ref = pending.pop()
        keys = (
            memory.revisions.by_source.get(ref, set())
            | memory.revisions.by_claim.get(ref, set())
        )
        for key in keys:
            target = memory.revisions.groups[key].target_ref
            if target not in touched:
                touched.add(target)
                pending.append(target)
    return sorted(touched)


def mark_affected(
    memory: ContextualMemory, refs: set[str], *, reviewed: set[str],
) -> dict[str, Any]:
    """Resolve the whole known closure now; defer only further semantic interpretation."""
    affected = affected_claims(memory, refs)
    for ref in reviewed:
        memory.revisions.pending.pop(ref, None)
    statuses = {}
    for ref in affected:
        if ref in reviewed or memory.resolve(ref) != ref:
            continue
        status = support_view(memory, ref)["support_status"]
        statuses[ref] = status
        memory.revisions.pending[ref] = {
            "ref": ref, "reason_refs": sorted(refs), "support_status": status,
            "known_at": memory._known_now(),
        }
    return {"affected_refs": affected, "structural_status": statuses,
            "pending_refs": sorted(memory.revisions.pending)}


def maintenance_records(
    memory: ContextualMemory, query: str, *, max_bytes: int,
) -> list[dict[str, Any]]:
    """A bounded next proposal: all known work in eager mode, query order in pending mode."""
    pending = memory.revisions.pending
    if not pending:
        return []
    if memory.maintenance_mode == "pending":
        ranking = memory._rank(query, sources=False)
        order = [ref for ref in ranking.refs if ref in pending]
    else:
        order = sorted(pending)
    limit = 4 if memory.maintenance_mode == "pending" else len(pending)
    records = []
    used = 0
    for ref in order:
        item = memory.read(ref, include_sources=False)
        item["pending_review"] = pending[ref]
        size = len(json.dumps(item, ensure_ascii=False).encode())
        if used + size > max_bytes:
            continue
        records.append(item)
        used += size
        if len(records) == limit:
            break
    return records


def _exact_ref(memory: ContextualMemory, ref: str, aliases: dict[str, str]) -> str:
    actual = aliases.get(ref, ref)
    if actual in memory.sources:
        return actual
    if actual.startswith("new:"):
        raise ValueError("UNKNOWN_ALIAS")
    if actual not in memory.history and actual not in memory._known_refs():
        raise ValueError("UNKNOWN_REFERENCE")
    return actual


def _would_cycle(memory: ContextualMemory, target: str, items: tuple[SupportItem, ...]) -> bool:
    pending = [item.ref for item in items if item.ref not in memory.sources]
    visited: set[str] = set()
    while pending:
        ref = pending.pop()
        if ref == target:
            return True
        if ref in visited:
            continue
        visited.add(ref)
        for key in memory.revisions.by_target.get(ref, set()):
            group = memory.revisions.groups[key]
            if not group.withdrawn_at:
                pending.extend(item.ref for item in group.items if item.ref not in memory.sources)
    return False


_STAGED = (
    "workspace", "state", "sources", "source_replacements", "retained", "task_sources",
    "forgotten", "details", "history", "vectors", "seen", "next_card", "expansion",
    "latest_search", "coverage_binding", "revisions", "source_known_at",
    "source_replacement_at", "last_known_at",
)


def apply_changeset(memory: ContextualMemory, changeset: dict[str, Any]) -> dict[str, Any]:
    if memory.profile != "support":
        raise ValueError("CHANGESET_REQUIRES_SUPPORT_PROFILE")
    aliases: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    for proposed in changeset["groups"]:
        copy_started = perf_counter()
        staged = copy.copy(memory)
        for name in _STAGED:
            setattr(staged, name, copy.deepcopy(getattr(memory, name)))
        copy_seconds = perf_counter() - copy_started
        staged_counts = {
            "sources": len(staged.sources),
            "claims": len(staged.workspace.cards),
            "historical_versions": len(staged.history),
            "support_groups": len(staged.revisions.groups),
            "vector_entries": len(staged.vectors),
        }
        local_aliases = dict(aliases)
        operations: list[dict[str, Any]] = []
        touched: set[str] = set()
        reason_refs: list[str] = []
        try:
            if (len(proposed["operations"]) > 1
                    and any(item["op"] == "task_override" for item in proposed["operations"])):
                raise ValueError("TASK_OVERRIDE_REQUIRES_OWN_GROUP")
            for operation in proposed["operations"]:
                kind = operation["op"]
                if kind == "claim":
                    wanted = operation.get("target_ref")
                    target = _exact_ref(staged, wanted, local_aliases) if wanted else None
                    if target is not None and target in staged.sources:
                        raise ValueError("TARGET_MUST_BE_CLAIM")
                    kwargs = {key: operation[key] for key in (
                        "content", "source_refs", "subject", "context", "certainty", "persistence",
                        "conditions", "valid_from", "valid_until",
                        "uncertain_start", "uncertain_end",
                    ) if key in operation}
                    receipt = staged.save(target_ref=target, **kwargs)
                    record = receipt["record"]
                    if record["status"] not in {"SAVED", "REUSED"}:
                        raise ValueError(record["status"])
                    actual = record["ref"]
                    if target is not None:
                        touched.add(target)
                    touched.add(actual)
                    alias = operation.get("alias")
                    if alias:
                        if alias in local_aliases or not alias.startswith("new:"):
                            raise ValueError("INVALID_OR_DUPLICATE_ALIAS")
                        local_aliases[alias] = actual
                    operations.append({"op": kind, "status": record["status"], "ref": actual})
                elif kind == "justification":
                    target = _exact_ref(staged, operation["target_ref"], local_aliases)
                    if target in staged.sources or staged.resolve(target) != target:
                        raise ValueError("JUSTIFICATION_TARGET_REQUIRES_CURRENT_CLAIM")
                    items = tuple(
                        SupportItem(
                            _exact_ref(staged, item["ref"], local_aliases),
                            item.get("start"), item.get("end"),
                        ) for item in operation["items"]
                    )
                    if not items:
                        raise ValueError("EMPTY_JUSTIFICATION")
                    for item in items:
                        body = (staged.sources[item.ref].content if item.ref in staged.sources
                                else staged._view(item.ref, False)["text"])
                        if (item.start is None) != (item.end is None):
                            raise ValueError("INCOMPLETE_SOURCE_RANGE")
                        if (item.start is not None and item.end is not None
                                and not (0 <= item.start < item.end <= len(body))):
                            raise ValueError("INVALID_SOURCE_RANGE")
                    if _would_cycle(staged, target, items):
                        raise ValueError("CYCLIC_JUSTIFICATION")
                    target_detail = staged.details[staged._handle(target)]
                    if target_detail.persistence == "durable":
                        for item in items:
                            if item.ref in staged.sources:
                                staged._retain(item.ref)
                            elif staged.details[staged._handle(item.ref)].persistence == "task":
                                raise ValueError("DURABLE_SUPPORT_CANNOT_USE_TASK_CLAIM")
                    else:
                        staged.task_sources.update(
                            item.ref for item in items
                            if item.ref in staged.sources and item.ref not in staged.retained
                        )
                    group_id = f"{staged.scope}/group:{staged.revisions.next_group}"
                    staged.revisions.next_group += 1
                    group = Justification(
                        group_id, target, operation["polarity"], items,
                        dict(operation.get("conditions", {})),
                        operation.get("valid_from", ""), operation.get("valid_until", ""),
                        staged._known_now(),
                    )
                    staged.revisions.add(group)
                    touched.add(target)
                    operations.append({
                        "op": kind, "status": "ADDED", "group_id": group_id,
                        "target_ref": target,
                    })
                elif kind == "retract_justification":
                    key = operation["group_id"]
                    group = staged.revisions.groups[key]
                    if group.withdrawn_at:
                        raise ValueError("JUSTIFICATION_ALREADY_WITHDRAWN")
                    staged.revisions.groups[key] = replace(
                        group, withdrawn_at=staged._known_now(),
                    )
                    touched.add(group.target_ref)
                    operations.append({"op": kind, "status": "WITHDRAWN", "group_id": key})
                elif kind == "review":
                    target = _exact_ref(staged, operation["target_ref"], local_aliases)
                    if target not in staged.seen or target not in staged.revisions.pending:
                        raise ValueError("REVIEW_REQUIRES_READ_PENDING_CLAIM")
                    if operation["decision"] == "keep":
                        staged.revisions.pending.pop(target)
                    operations.append({"op": kind, "status": "REVIEWED", "target_ref": target,
                                       "decision": operation["decision"]})
                elif kind == "state_change":
                    old_ref = _exact_ref(staged, operation["old_ref"], local_aliases)
                    if old_ref in staged.sources or staged.resolve(old_ref) != old_ref:
                        raise ValueError("VERSION_CONFLICT")
                    prior = staged.details[staged._handle(old_ref)]
                    if prior.valid_until or prior.uncertain_end:
                        raise ValueError("STATE_ALREADY_ENDED")
                    boundary = operation.get("valid_from", "")
                    if boundary:
                        try:
                            date.fromisoformat(boundary)
                        except ValueError as error:
                            raise ValueError("INVALID_STATE_CHANGE_BOUNDARY") from error
                        if prior.valid_from and boundary <= prior.valid_from:
                            raise ValueError("INVALID_STATE_CHANGE_BOUNDARY")
                        if prior.valid_until and boundary >= prior.valid_until:
                            raise ValueError("INVALID_STATE_CHANGE_BOUNDARY")
                    closed = staged.save(
                        target_ref=old_ref,
                        valid_until=boundary if boundary else None,
                        uncertain_end=not bool(boundary),
                    )["record"]
                    if closed["status"] != "SAVED":
                        raise ValueError(closed["status"])
                    closed_ref = closed["ref"]
                    for key in sorted(staged.revisions.by_target.get(old_ref, set())):
                        original = staged.revisions.groups[key]
                        if original.withdrawn_at:
                            continue
                        group_id = f"{staged.scope}/group:{staged.revisions.next_group}"
                        staged.revisions.next_group += 1
                        staged.revisions.add(replace(
                            original, group_id=group_id, target_ref=closed_ref,
                            known_at=staged._known_now(), withdrawn_at="",
                        ))
                    new = staged.save(
                        content=operation["content"],
                        source_refs=operation.get("source_refs", []),
                        subject=operation.get("subject", prior.subject),
                        context=operation.get("context", prior.context),
                        certainty=operation.get("certainty", prior.certainty),
                        conditions=operation.get("conditions", prior.conditions),
                        persistence=prior.persistence,
                        valid_from=boundary,
                        uncertain_start=not bool(boundary),
                    )["record"]
                    if new["status"] not in {"SAVED", "REUSED"}:
                        raise ValueError(new["status"])
                    new_ref = new["ref"]
                    alias = operation.get("alias")
                    if alias:
                        if alias in local_aliases:
                            raise ValueError("INVALID_OR_DUPLICATE_ALIAS")
                        local_aliases[alias] = new_ref
                    touched.update((old_ref, closed_ref, new_ref))
                    operations.append({
                        "op": kind, "status": "CHANGED", "old_ref": old_ref,
                        "closed_ref": closed_ref, "new_ref": new_ref,
                        "valid_from": boundary, "event_known_at": staged.last_known_at,
                    })
                elif kind == "task_override":
                    target = _exact_ref(staged, operation["target_ref"], local_aliases)
                    if target in staged.sources or staged.resolve(target) != target:
                        raise ValueError("VERSION_CONFLICT")
                    staged.state.overrides[target] = {
                        "content": operation["content"], "task_id": staged.state.task_id,
                        "known_at": staged._known_now(),
                    }
                    touched.add(target)
                    operations.append({"op": kind, "status": "OVERRIDDEN", "target_ref": target})
                elif kind == "reinterpret":
                    old_ref = _exact_ref(staged, operation["target_ref"], local_aliases)
                    if old_ref in staged.sources or staged.resolve(old_ref) != old_ref:
                        raise ValueError("VERSION_CONFLICT")
                    chosen = []
                    for key in operation["group_ids"]:
                        group = staged.revisions.groups[key]
                        if group.target_ref != old_ref or group.withdrawn_at:
                            raise ValueError("GROUP_NOT_ACTIVE_ON_TARGET_VERSION")
                        chosen.append(group)
                    kwargs = {key: operation[key] for key in (
                        "content", "source_refs", "subject", "context", "certainty",
                        "conditions", "valid_from", "valid_until",
                    ) if key in operation}
                    corrected = staged.save(target_ref=old_ref, **kwargs)["record"]
                    if corrected["status"] != "SAVED" or corrected["ref"] == old_ref:
                        raise ValueError("REINTERPRET_REQUIRES_NEW_VERSION")
                    new_ref = corrected["ref"]
                    transferred: list[dict[str, str]] = []
                    for original in chosen:
                        if _would_cycle(staged, new_ref, original.items):
                            raise ValueError("CYCLIC_JUSTIFICATION")
                        staged.revisions.groups[original.group_id] = replace(
                            original, withdrawn_at=staged._known_now(),
                        )
                        group_id = f"{staged.scope}/group:{staged.revisions.next_group}"
                        staged.revisions.next_group += 1
                        staged.revisions.add(replace(
                            original, group_id=group_id, target_ref=new_ref,
                            known_at=staged._known_now(), withdrawn_at="",
                        ))
                        transferred.append({"from_group_id": original.group_id,
                                            "to_group_id": group_id})
                    alias = operation.get("alias")
                    if alias:
                        if alias in local_aliases:
                            raise ValueError("INVALID_OR_DUPLICATE_ALIAS")
                        local_aliases[alias] = new_ref
                    touched.update((old_ref, new_ref))
                    operations.append({
                        "op": kind, "status": "REINTERPRETED", "old_ref": old_ref,
                        "new_ref": new_ref, "explicit_group_transfers": transferred,
                    })
                else:
                    raise ValueError("UNKNOWN_CHANGE_OPERATION")
            reason_refs = [
                _exact_ref(staged, ref, local_aliases)
                for ref in proposed.get("reason_refs", [])
            ]
            durable = any(operation["op"] != "task_override" for operation in operations) and any(
                ref not in staged.sources
                and staged.details[staged._handle(ref)].persistence == "durable"
                for ref in touched
            )
            for ref in reason_refs:
                if ref in staged.sources:
                    if durable:
                        staged._retain(ref)
                    else:
                        staged.task_sources.add(ref)
                elif durable and staged.details[staged._handle(ref)].persistence == "task":
                    raise ValueError("DURABLE_REASON_CANNOT_USE_TASK_CLAIM")
        except (ValueError, KeyError) as error:
            failure: dict[str, Any] = {
                "status": "VERSION_CONFLICT" if str(error) == "VERSION_CONFLICT" else "ERROR",
                "error": str(error), "operations": [],
                "metrics": {"copy_seconds": copy_seconds, "commit_seconds": 0.0,
                            "staged_counts": staged_counts, "touched_count": len(touched)},
            }
            memory.revisions.changesets.append({
                "committed_at": "", "reason_refs": reason_refs, "outcome": failure,
            })
            results.append(failure)
            continue
        commit_started = perf_counter()
        for name in _STAGED:
            setattr(memory, name, getattr(staged, name))
        memory._invalidate_coverage()
        new_aliases = {key: value for key, value in local_aliases.items() if key not in aliases}
        aliases = local_aliases
        maintenance = mark_affected(memory, touched, reviewed=touched)
        commit_seconds = perf_counter() - commit_started
        outcome = {"status": "APPLIED", "operations": operations,
                   "aliases": new_aliases,
                   "reason_refs": reason_refs,
                   "usable_refs": list(dict.fromkeys(new_aliases.values())),
                   "affected_refs": sorted(touched | set(affected_claims(memory, touched))),
                   "maintenance": maintenance,
                   "metrics": {"copy_seconds": copy_seconds,
                               "commit_seconds": commit_seconds,
                               "staged_counts": staged_counts,
                               "touched_count": len(touched)}}
        memory.revisions.changesets.append({
            "committed_at": memory._known_now(),
            "reason_refs": reason_refs, "outcome": outcome,
        })
        results.append(outcome)
    return {"groups": results, "aliases": aliases,
            "pending_refs": sorted(memory.revisions.pending)}
