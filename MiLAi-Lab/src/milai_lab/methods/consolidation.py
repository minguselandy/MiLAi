"""Finite episodic replay through the caller's existing maintenance path.

Original source identities are retained. Replaying an experience adds neither a
captured event nor independent factual support, and never schedules background
models. An explicit correction can be selected immediately.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any, Protocol

from milai_lab.memory.edit_units import issue_evidence
from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.functional_state import FunctionalRejection, body_text


class MaintenanceCallback(Protocol):
    """Bind transport, permission and commits outside this selection module."""

    def __call__(
        self,
        *,
        delivery: dict[str, Any],
        record_ids: list[str],
        episode_ids: list[str],
        request_id: str,
    ) -> dict[str, Any]: ...


class ReconcileCallback(Protocol):
    """Inspect the original maintenance identity without generating or committing."""

    def __call__(self, *, request_id: str) -> dict[str, Any] | None: ...


def _maintenance_result(result: dict[str, Any], maintained: dict[str, Any]) -> dict[str, Any]:
    receipts = maintained.get("receipts", [])
    if not receipts and maintained["status"] != "completed":
        receipts = result.get("receipts", [])
    updated = {
        **copy.deepcopy(result),
        "status": maintained["status"],
        "phase": maintained.get("phase", result.get("phase")),
        "semantic_write_performed": result.get("semantic_write_performed", False)
        or maintained.get("semantic_write_performed", False),
        "receipts": [
            {
                key: receipt[key]
                for key in (
                    "ok",
                    "status",
                    "original_status",
                    "id",
                    "revision",
                    "effect",
                    "replayed",
                    "reason",
                )
                if key in receipt
            }
            for receipt in receipts
        ],
    }
    for key in ("outcome", "unprocessed"):
        if key in maintained:
            updated[key] = copy.deepcopy(maintained[key])
        elif maintained["status"] == "completed":
            updated.pop(key, None)
    return updated


def _delivery_sources(index: EpisodeIndex, refs: list[str]) -> list[dict[str, Any]]:
    sources = []
    for ref in refs:
        event = index.service.source(ref)
        if event is None:
            raise FunctionalRejection("CONSOLIDATION_SOURCE_UNAVAILABLE")
        text = body_text(event)
        sources.append(
            {
                **issue_evidence(index.service, ref, 0, len(text)),
                "role": event["role"],
                "observed_at": event["observed_at"],
                "occurred_at": event.get("occurred_at"),
                "text": text,
                "body_delivered": True,
                "semantic_support": "unchecked",
            }
        )
    return sources


def consolidate(
    index: EpisodeIndex,
    *,
    request_id: str,
    maintain: MaintenanceCallback,
    reconcile: ReconcileCallback | None = None,
    episode_ids: Sequence[str] | None = None,
    record_ids: Sequence[str] = (),
    prior_episode_ids: Sequence[str] = (),
    limit: int = 20,
) -> dict[str, Any]:
    """Maintain specified episodes/records or at most ``limit`` pending episodes.

    The callback decides whether any proposal is warranted and commits through
    the existing service. A completed empty proposal counts as processed work,
    never as a new fact. A pending callback is inspected only by the separate
    readonly reconciler under its original ID. Missing or unknown outcomes remain
    unfinished; a new semantic attempt needs a new ID.
    """
    if not request_id or not 1 <= limit <= 100:
        raise FunctionalRejection("CONSOLIDATION_ID_OR_LIMIT_INVALID")
    service = index.service
    namespace = (*service.namespace, "consolidation")
    selected_record_ids = list(dict.fromkeys(record_ids))
    selected_episode_ids = (
        list(dict.fromkeys(episode_ids))
        if episode_ids is not None
        else ([] if selected_record_ids else None)
    )
    selection: dict[str, Any] = {
        "episode_ids": selected_episode_ids,
        "record_ids": selected_record_ids,
        "prior_episode_ids": list(dict.fromkeys(prior_episode_ids)),
        "limit": limit,
    }
    previous = service.store.get(namespace, request_id)
    if previous is not None:
        state = previous.value
        if state["selection"] != selection:
            raise FunctionalRejection("CONSOLIDATION_REQUEST_SELECTION_CHANGED")
        if any(service.source(ref) is None for ref in state["visible_source_refs"]) or any(
            not service.read(record_id, revision).get("ok")
            for record_id, revision in state["record_revisions"].items()
        ):
            return {"status": "visibility_revoked", "request_id": request_id, "replayed": True}
        inspected = None
        if state["result"]["status"] != "completed" and reconcile is not None:
            inspected = reconcile(request_id=request_id)
            if inspected is not None:
                state["result"] = _maintenance_result(state["result"], inspected)
                service.store.put(namespace, request_id, state, index=False)
        if state["result"]["status"] == "completed":
            ids = state["result"]["episode_ids"]
            if inspected is not None:
                index.mark_consolidated(ids, request_id)
            else:
                unmarked = [
                    episode_id
                    for episode_id in ids
                    if service.store.get(index.consolidated_namespace, episode_id) is None
                ]
                if unmarked:
                    index.mark_consolidated(unmarked, request_id)
        return {
            **copy.deepcopy(state["result"]),
            "replayed": True,
            **({"reconciled": True} if inspected is not None else {}),
        }
    if len(selected_record_ids) > limit:
        raise FunctionalRejection("CONSOLIDATION_RECORD_SELECTION_EXCEEDS_LIMIT")
    episodes = index.select(
        episode_ids=selected_episode_ids, pending_only=selected_episode_ids is None, limit=limit
    )
    if selected_episode_ids is not None and len(episodes) != len(selected_episode_ids):
        raise FunctionalRejection("CONSOLIDATION_EPISODE_UNAVAILABLE")
    prior = index.select(episode_ids=prior_episode_ids, limit=limit)
    if len(prior) != len(selection["prior_episode_ids"]):
        raise FunctionalRejection("CONSOLIDATION_PRIOR_EPISODE_UNAVAILABLE")
    refs = list(dict.fromkeys(ref for episode in episodes for ref in episode["source_refs"]))
    record_refs = []
    record_revisions = {}
    for record_id in selected_record_ids:
        record = service.read(record_id)
        if not record.get("ok"):
            raise FunctionalRejection("CONSOLIDATION_RECORD_UNAVAILABLE")
        record_refs.extend(service._version_source_refs(record["value"]))
        record_revisions[record_id] = record["value"]["revision"]
    if not refs:
        refs = list(dict.fromkeys(record_refs))
    old_refs = list(
        dict.fromkeys(
            [
                *(ref for episode in prior for ref in episode["source_refs"]),
                *record_refs,
            ]
        )
    )
    old_refs = [ref for ref in old_refs if ref not in refs]
    ids = [episode["episode_id"] for episode in episodes]
    result: dict[str, Any] = {
        "status": "empty" if not refs else "incomplete",
        "phase": "empty" if not refs else "maintenance_pending",
        "request_id": request_id,
        "episode_ids": ids,
        "record_ids": selected_record_ids,
        "source_refs": refs,
        "semantic_write_performed": False,
        "new_independent_support": False,
    }
    if not refs:
        return result
    delivery = {
        "sources": _delivery_sources(index, refs),
        "prior_context": _delivery_sources(index, old_refs),
        "episode_context": [
            {key: episode[key] for key in ("episode_id", "source_refs", "descriptions")}
            for episode in [*episodes, *prior]
        ],
        "replay": True,
        "new_independent_support": False,
    }
    state = {
        "selection": selection,
        "visible_source_refs": [*refs, *old_refs],
        "record_revisions": record_revisions,
        "result": result,
    }
    service.store.put(namespace, request_id, state, index=False)
    maintained = maintain(
        delivery=delivery, record_ids=selected_record_ids, episode_ids=ids, request_id=request_id
    )
    result = _maintenance_result(result, maintained)
    state["result"] = result
    service.store.put(namespace, request_id, state, index=False)
    if result["status"] == "completed":
        index.mark_consolidated(ids, request_id)
    return {**copy.deepcopy(result), "replayed": False}
