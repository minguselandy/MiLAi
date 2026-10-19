"""Dynamic actions executed by the existing evidence and query-structure modules."""
from __future__ import annotations

import copy
import time
from collections.abc import Callable
from typing import Any

from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]

from milai_lab.memory.functional_state import FunctionalRejection, body_text
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    pack_candidate,
    project_packs,
)
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.query_structure import (
    QueryStructurePolicy,
    build_query_structure,
    cached_structures,
    next_structure_slot,
    open_structure,
    structure_slots,
    touch_structure,
)


def controlled_reader_packet(evidence: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    return {"ok": True, "schema": "question_evidence_v1", "evidence": evidence,
        "control_handoff": reason,
        "instructions": "Answer the original request from delivered evidence. "
            "Interpretations are model-derived, not original sources. Handoff does not "
            "certify sufficiency. Report missing conditions or sources explicitly."}


class EvidenceOperations:
    """A request-local material set; persistent views remain in the original Store."""

    def __init__(
        self, service: MemoryService, state: MemoryControlState, *,
        load_pool: Callable[[], list[dict[str, Any]]],
        refresh_call: Callable[[list[dict[str, str]], dict[str, Any]], dict[str, Any]],
        fits: Callable[[list[dict[str, Any]]], bool],
        excluded_source_refs: tuple[str, ...] = (),
        view_capacity: int = 1,
        view_policy: QueryStructurePolicy = "incremental",
        known_materials: list[dict[str, Any]] | None = None,
        search_pool: Callable[[str, int], list[dict[str, Any]]] | None = None,
        search_batch_sizes: tuple[int, ...] = (8, 16),
        max_searches: int = 2,
        fits_materials: Callable[[dict[int, dict[str, Any]]], bool] | None = None,
    ) -> None:
        self.service, self.load_pool, self.refresh_call, self.fits = (
            service, load_pool, refresh_call, fits)
        self.materials: list[dict[str, Any]] = []
        self.opened: dict[int, dict[str, Any]] = {}
        self.known_materials = known_materials or []
        self.search_pool = search_pool
        self.search_batch_sizes = search_batch_sizes
        self.max_searches = max_searches
        self.search_attempts: set[tuple[str, int]] = set()
        self.fits_materials = fits_materials
        self.attempted: set[tuple[int, bool]] = set()
        self.searched = False
        self.view_capacity = view_capacity
        self.view_policy = view_policy
        self.used: set[str] = set()
        self.refreshed_inputs: set[tuple[str, tuple[str, ...], bool]] = set()
        self.history_pages: dict[str, dict[str, Any]] = {}
        self.visibility_epoch = service.forget_epoch
        self.views = cached_structures(service, view_capacity)
        started = time.perf_counter()
        cursors = [v["arrival_cursor"][0] for v in self.views.values() if v["arrival_cursor"]]
        since = min(cursors) if cursors else None
        feed = service.source_arrivals(since)
        boundary_views = [v for v in self.views.values()
                          if v["arrival_cursor"] and v["arrival_cursor"][0] == since]
        seen = set.intersection(*(set(v.get("arrival_boundary_refs", [v["arrival_cursor"][1]]))
                                  for v in boundary_views)) if boundary_views else set()
        arrivals = [e for e in feed["events"] if e["event_id"] not in excluded_source_refs
                    and (e["observed_at"] != since or e["event_id"] not in seen)]
        by_ref = {e["event_id"]: e for e in arrivals}
        bound_refs = {b["source_ref"] for view in self.views.values()
                      for b in view["source_bindings"].values()}
        for ref in bound_refs - set(by_ref):
            source = service.source(ref)
            if source is not None and ref not in excluded_source_refs:
                by_ref[ref] = source
        self.events = list(by_ref.values())
        state.budget.update(source_inventory_wall_seconds=time.perf_counter() - started,
            visible_sources_enumerated=len(self.events), source_feed_rows=feed["rows_materialized"],
            source_discovery=feed["query"], bound_source_lookups=len(bound_refs))
        state.new_events = [{"source_ref": e["event_id"], "role": e["role"],
            "content": body_text(e), "origin": e.get("origin"),
            "delivery": "controller_observation; Reader uses visible_evidence",
            "reported_at": e.get("occurred_at"), "captured_at": e["observed_at"]}
            for e in arrivals]
        self.view_observation(state)

    @staticmethod
    def pending(view: dict[str, Any], event: dict[str, Any]) -> bool:
        cursor = view["arrival_cursor"]
        if not cursor:
            return True
        return (event["captured_at"] > cursor[0] or (event["captured_at"] == cursor[0]
            and event["source_ref"] not in view.get("arrival_boundary_refs", [cursor[1]])))

    def view_observation(self, state: MemoryControlState) -> dict[str, dict[str, Any]]:
        opened = {slot: open_structure(self.service, item) for slot, item in self.views.items()}
        state.views = [{"id": view["id"], "slot": slot,
            "scope": opened[slot].get("index_text"), "built_for": opened[slot].get("built_for"),
            "revision": view["revision"], "visibility": opened[slot]["visibility"],
            "pending_events": [e["source_ref"] for e in state.new_events if self.pending(view, e)],
            "source_bindings": view["source_bindings"],
            **({"retrieval_request": view["retrieval_request"]}
               if "retrieval_request" in view else {}),
            "semantics": "binding/inventory status is not semantic correctness or full coverage"}
            for slot, view in self.views.items()]
        return opened

    def refresh_visibility(self, state: MemoryControlState) -> None:
        epoch = self.service.forget_epoch
        if epoch == self.visibility_epoch:
            return
        self.visibility_epoch = epoch
        self.events = [s for e in self.events
                       if (s := self.service.source(e["event_id"])) is not None]
        visible = {s["event_id"] for s in self.events}
        state.new_events = [e for e in state.new_events if e["source_ref"] in visible]
        self.materials = [open_evidence_packs(self.service, [m], refresh_current=True)[0]
            if m["kind"] != "stored_revision" else m for m in self.materials]
        self.opened = dict(zip(self.opened, open_evidence_packs(
            self.service, list(self.opened.values()), refresh_current=True), strict=True))
        self._deliver(state)
        state.pending_candidates = [self.candidate(m, i) for i, m in enumerate(self.materials)
                                    if i not in self.opened]
        self.history_pages.clear()
        self.view_observation(state)

    def refresh_refs(self, state: MemoryControlState, slot: str) -> tuple[str, ...]:
        view = self.views.get(slot)
        visible = {s["event_id"] for s in self.events}
        arrivals = {e["source_ref"] for e in state.new_events if not view or self.pending(view, e)}
        prior = {b["source_ref"] for b in view["source_bindings"].values()} if view else set()
        refs = (set(self.source_refs()) or (prior | arrivals)) & visible
        metadata = next((v for v in state.views if v["slot"] == slot), None)
        changed = (self.view_policy == "rebuild" or not view or arrivals
            or refs != set(view["retrieved_sources"])
            or view.get("built_for") != state.task["request"]
            or view["query_time"] != state.task["query_time"]
            or view.get("retrieval_request") != state.task.get("retrieval_request")
            or (metadata is not None and metadata["visibility"] != "visible"))
        return tuple(sorted(refs)) if changed else ()

    def source_refs(self) -> tuple[str, ...]:
        return tuple(sorted({span["source_ref"] for item in self.opened.values()
            for span in [*item.get("source_ranges", []), *item.get("support_turns", [])]}))

    def observation_source_refs(self, state: MemoryControlState) -> list[str]:
        """Origins of controller-visible bodies/excerpts, distinct from Reader delivery."""
        refs = {event["source_ref"] for event in state.new_events}
        for view in state.views:
            if view["visibility"] == "visible":
                refs.update(b["source_ref"] for b in view["source_bindings"].values())
        for candidate in state.pending_candidates:
            item = self.materials[candidate["item_index"]]
            if item.get("body_delivered") is not False:
                refs.update(span["source_ref"] for span in [
                    *item.get("focus_source_ranges", item.get("source_ranges", [])),
                    *item.get("revision_evidence", []), *item.get("support_turns", [])])
        return sorted(refs)

    def adds_source_range(self, item: dict[str, Any], *, expand: bool = False) -> bool:
        """Availability uses actual versioned intervals, never semantic sufficiency."""
        if item["kind"] != "original_source":
            return True
        delivered = [span for opened in [*self.opened.values(), *self.known_materials]
                     if opened.get("body_delivered") is not False
                     for span in opened.get("source_ranges", [])]
        for target in item["context_source_ranges" if expand else "source_ranges"]:
            intervals = sorted((span["start"], span["end"]) for span in delivered
                if (span["source_ref"], span["source_revision"]) == (
                    target["source_ref"], target["source_revision"]))
            end = target["start"]
            for left, right in intervals:
                if left > end:
                    break
                end = max(end, right)
            if end < target["end"]:
                return True
        return False

    def actions(self, state: MemoryControlState) -> list[MemoryAction]:
        self.refresh_visibility(state)
        actions = []
        history_records = set()
        if self.search_pool is not None:
            actions.extend(self.search_actions(state))
        elif not self.searched:
            actions.append(MemoryAction("search", "SEARCH", "original request"))
        for i, item in sorted(enumerate(self.materials),
                              key=lambda pair: pair[1].get("control_pool_rank", pair[0])):
            if item.get("body_delivered") is False:
                continue
            if (i, False) not in self.attempted and self.adds_source_range(item):
                actions.append(MemoryAction(f"read_{i}", "READ", f"candidate {i}", {"index": i}))
            if (i, True) not in self.attempted and (
                item.get("context_source_ranges") != item.get("source_ranges")
            ) and item.get("context_source_ranges") and self.adds_source_range(item, expand=True):
                actions.append(MemoryAction(f"context_{i}", "READ", f"candidate {i} context",
                                            {"index": i, "expand_context": True}))
            if item["kind"] == "semantic_view" and item.get("version_view") != (
                "historical_exact_revision"
            ) and item["record_id"] not in history_records:
                history_records.add(item["record_id"])
                page = self.history_pages.get(item["record_id"])
                if page is None or page.get("next_cursor"):
                    actions.append(MemoryAction(f"history_{i}", "READ",
                        f"candidate {i} stored-version directory", {"index": i,
                            "history_directory": True,
                            "cursor": page["next_cursor"] if page else None}))
        for slot in structure_slots(self.view_capacity):
            view = self.views.get(slot)
            meta = next((v for v in state.views if v["slot"] == slot), None)
            suffix = "" if self.view_capacity == 1 else "_" + slot
            if view and slot not in self.used and meta and meta["visibility"] == "visible":
                actions.append(MemoryAction("use_view" + suffix, "USE_VIEW", view["id"],
                                            {"slot": slot}))
            if view is None and self.view_capacity > 1:
                continue
            refs = self.refresh_refs(state, slot)
            if refs and (slot, refs, False) not in self.refreshed_inputs:
                actions.append(MemoryAction("refresh_view" + suffix, "REFRESH_VIEW",
                    view["id"] if view else "current source scope",
                    {"source_refs": list(refs), "slot": slot}))
        if self.view_capacity > 1:
            refs = tuple(sorted(set(self.source_refs()) or {
                event["source_ref"] for event in state.new_events}))
            duplicate = any(v.get("built_for") == state.task["request"]
                and set(v["retrieved_sources"]) == set(refs)
                and v["query_time"] == state.task["query_time"]
                and v.get("retrieval_request") == state.task.get("retrieval_request")
                for v in self.views.values())
            slot = next_structure_slot(self.service, self.view_capacity)
            if refs and not duplicate and (slot, refs, True) not in self.refreshed_inputs:
                actions.append(MemoryAction("new_view", "REFRESH_VIEW", "new selected source scope",
                    {"slot": slot, "source_refs": list(refs), "new_scope": True,
                     "replaces": self.views[slot]["id"] if slot in self.views else None}))
        actions.append(MemoryAction("handoff", "HANDOFF", "Reader with opened evidence"))
        return actions

    def search_actions(self, state: MemoryControlState) -> list[MemoryAction]:
        """Bind searches to the request or actually opened text, never offline answers."""
        if len(self.search_attempts) >= self.max_searches:
            return []
        query = state.task["request"]
        goal = state.task.get("read_goal")
        points = goal.get("required_points", []) if isinstance(goal, dict) else []
        queries = [(query, "Host query"), *(
            (point, "Host required point") for point in points)]
        queries.extend((item["index_text"], "opened evidence")
            for item in [*self.opened.values(), *self.known_materials]
            if item.get("body_delivered") is not False and item.get("index_text"))
        unique = dict(queries)
        return [MemoryAction(f"search_{i}_{limit}", "SEARCH", origin,
                             {"query": text, "limit": limit})
                for i, (text, origin) in enumerate(unique.items())
                for limit in self.search_batch_sizes if (text, limit) not in self.search_attempts]

    def _deliver(self, state: MemoryControlState) -> None:
        state.visible_evidence = project_packs(list(self.opened.values()), list(self.opened))

    def fits_delivery(self, items: dict[int, dict[str, Any]]) -> bool:
        if self.fits_materials is not None:
            return self.fits_materials(items)
        return self.fits(project_packs(list(items.values()), list(items)))

    @staticmethod
    def candidate(item: dict[str, Any], index: int) -> dict[str, Any]:
        return {**pack_candidate(item, index), **{
            k: item[k] for k in ("revision", "version_view", "control_pool_rank",
                                "control_dense_score") if k in item}}

    def execute(self, action: MemoryAction, state: MemoryControlState) -> dict[str, Any]:
        if action.kind == "SEARCH":
            if self.search_pool is None:
                self.materials = self.load_pool()
            else:
                query, limit = action.parameters["query"], action.parameters["limit"]
                self.search_attempts.add((query, limit))
                found = self.search_pool(query, limit)
                # Preserve the indices of earlier observations as the actual pool grows.
                def identity(item: dict[str, Any]) -> tuple[Any, ...]:
                    return (item["kind"], item.get("id", item.get("record_id")),
                            item.get("revision"), item.get("version_view"))

                existing_items = {identity(item) for item in self.materials}
                for item in found:
                    if identity(item) not in existing_items:
                        self.materials.append(item)
                        existing_items.add(identity(item))
            self.searched = True
            state.pending_candidates = [self.candidate(item, i)
                                        for i, item in enumerate(self.materials)
                                        if i not in self.opened]
            return {"ok": True, "status": "searched", "candidates": len(self.materials),
                    **action.parameters,
                    "scope": "captured visible pool, not a sufficiency judgment"}
        if action.kind == "READ":
            i, expand = action.parameters["index"], action.parameters.get("expand_context", False)
            target = self.materials[i]
            if action.parameters.get("history_directory"):
                page = self.service.history_index(target["record_id"],
                    cursor=action.parameters["cursor"], limit=4)
                self.history_pages[target["record_id"]] = page
                existing = {(m.get("record_id"), m.get("revision")) for m in self.materials}
                for revision in page.get("revisions", []):
                    if revision > target["revision"] or (target["record_id"], revision) in existing:
                        continue
                    item = {"kind": "stored_revision", "record_id": target["record_id"],
                        "revision": revision, "version_view": "historical_exact_revision",
                        "index_text": f"Actual stored revision {revision} of candidate {i}"}
                    state.pending_candidates.append(self.candidate(item, len(self.materials)))
                    self.materials.append(item)
                return {**page, "status": "history_directory" if page["ok"] else page["status"],
                        "body_delivered": False}
            self.attempted.add((i, expand))
            if target["kind"] == "stored_revision":
                actual = self.service.read(target["record_id"], target["revision"])
                if not actual["ok"]:
                    return actual
                packs = build_evidence_packs(self.service, state.task["request"],
                    state.task["query_time"], [], [{**actual, "historical_selection": True,
                        "fixed_history_pool": True}])
                self.materials[i] = next(p for p in packs if p["record_id"] == target["record_id"]
                                        and p["revision"] == target["revision"])
            item = open_evidence_packs(self.service, [self.materials[i]],
                                      expand_context=expand, refresh_current=True)[0]
            trial = {**self.opened, i: item}
            if not self.fits_delivery(trial):
                return {"ok": False, "status": "material_budget_exhausted", "index": i}
            self.opened = trial
            known = {source["event_id"] for source in self.events}
            for ref in self.source_refs():
                if ref not in known and (source := self.service.source(ref)) is not None:
                    self.events.append(source)
                    known.add(ref)
            self._deliver(state)
            state.pending_candidates = [c for c in state.pending_candidates
                                        if c["item_index"] != i]
            return {"ok": item.get("body_delivered") is not False,
                    "status": "opened", "index": i, "visibility": item.get("visibility")}
        if action.kind == "USE_VIEW":
            slot = action.parameters.get("slot", "current")
            item = self.view_observation(state)[slot]
            self.used.add(slot)
            if self.view_capacity > 1:
                touch_structure(self.service, slot)
        elif action.kind == "REFRESH_VIEW":
            refs = tuple(action.parameters["source_refs"])
            slot = action.parameters.get("slot", "current")
            replace = action.parameters.get("new_scope", False)
            self.refreshed_inputs.add((slot, refs, replace))
            events = [s for e in self.events
                      if (s := self.service.source(e["event_id"])) is not None]
            try:
                built, report = build_query_structure(self.service, state.task["request"],
                    state.task["query_time"], list(refs), policy=self.view_policy,
                    call=self.refresh_call,
                    source_events=events, force_refresh=True, slot=slot,
                    capacity=self.view_capacity, replace_slot=replace,
                    retrieval_request=state.task.get("retrieval_request"))
            except (FunctionalRejection, ValidationError) as error:
                # These checks precede the cache write. Preserve a definite failure
                # as feedback; the attempted input cannot silently be regenerated.
                return {"ok": False, "status": "view_rejected", "effect": "none",
                        "error_type": type(error).__name__, "reason": str(error)}
            if built is None:
                return {"ok": False, "status": "empty_source_pool", "report": report}
            self.views[slot] = copy.deepcopy(built)
            item = self.view_observation(state)[slot]
            self.used.add(slot)
        else:
            raise ValueError(f"Non-executable operation: {action.kind}")
        item["query_time"] = state.task["query_time"]
        view_index = -1 - structure_slots(self.view_capacity).index(slot)
        trial = {**self.opened, view_index: item}
        delivered = self.fits_delivery(trial)
        if delivered:
            self.opened = trial
            self._deliver(state)
        available = item.get("body_delivered") is not False
        return {"ok": available and delivered,
                "status": ("material_budget_exhausted" if not delivered else
                           "view_opened" if available else item["visibility"]),
                "view_id": item["id"], "revision": self.views[slot]["revision"],
                **({"report": report} if action.kind == "REFRESH_VIEW" else {})}

    def reader_evidence(self) -> list[dict[str, Any]]:
        """Recheck visibility on delivery, including after a later same-request forget."""
        actual = open_evidence_packs(self.service, list(self.opened.values()), refresh_current=True)
        return project_packs(actual, list(self.opened))
