"""Dynamic actions executed by the existing evidence and query-structure modules."""
from __future__ import annotations

import copy
import time
from collections.abc import Callable
from itertools import combinations
from typing import Any

from jsonschema.exceptions import ValidationError

from milai_lab.memory.functional_state import FunctionalRejection, body_text, reference_key
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    pack_candidate,
    project_pack,
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
from milai_lab.methods.source_observations import SourceObservationBudget, SourceObservationPages


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
        internal_views: bool = True,
        known_materials: list[dict[str, Any]] | None = None,
        search_pool: Callable[[str, int], list[dict[str, Any]]] | None = None,
        search_batch_sizes: tuple[int, ...] = (8, 16),
        max_searches: int = 2,
        fits_materials: Callable[[dict[int, dict[str, Any]]], bool] | None = None,
        source_observation: SourceObservationBudget | None = None,
        delivery_selection: bool = False,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        self.service, self.load_pool, self.refresh_call, self.fits = (
            service, load_pool, refresh_call, fits)
        self.materials: list[dict[str, Any]] = []
        self.opened: dict[int, dict[str, Any]] = {}
        self.delivery_selection = delivery_selection
        self.observed: dict[int, dict[str, Any]] = {}
        self.delivered_view_slots: dict[str, int] = {}
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
        self.internal_views = internal_views
        self.checkpoint_configuration = {
            "view_capacity": view_capacity, "view_policy": view_policy,
            "search_batch_sizes": list(search_batch_sizes), "max_searches": max_searches,
            "delivery_selection": delivery_selection,
            "source_observation_tokens": (source_observation.max_tokens
                                          if source_observation else None),
            **({"internal_views": False} if not internal_views else {}),
        }
        if checkpoint is not None:
            self.restore_checkpoint(checkpoint, source_observation)
            return
        self.used: set[str] = set()
        self.refreshed_inputs: set[tuple[str, tuple[str, ...], bool]] = set()
        self.history_pages: dict[str, dict[str, Any]] = {}
        self.observed_source_attempts: set[tuple[str, int, int]] = set()
        self.visibility_epoch = service.forget_epoch
        self.views = cached_structures(service, view_capacity) if internal_views else {}
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
        bound_refs = {b["source_ref"] for view in [
            *self.views.values(), *(item for item in self.known_materials
                if item["kind"] == "query_structure" and item.get("body_delivered") is not False)]
                      for b in view["source_bindings"].values()}
        for ref in bound_refs - set(by_ref):
            source = service.source(ref)
            if source is not None and ref not in excluded_source_refs:
                by_ref[ref] = source
        self.events = list(by_ref.values())
        self.source_directory = by_ref
        state.budget.update(source_inventory_wall_seconds=time.perf_counter() - started,
            visible_sources_enumerated=len(self.events), source_feed_rows=feed["rows_materialized"],
            source_discovery=feed["query"], bound_source_lookups=len(bound_refs))
        state.new_events = [{"source_ref": e["event_id"], "role": e["role"],
            "content": body_text(e), "origin": e.get("origin"),
            "delivery": "controller_observation; Reader uses visible_evidence",
            "reported_at": e.get("occurred_at"), "captured_at": e["observed_at"]}
            for e in arrivals]
        self.source_pages = (SourceObservationPages(state.new_events, source_observation)
                             if source_observation is not None else None)
        if self.source_pages is not None:
            self._observe_source_page(state)
        self.view_observation(state)
        if self.delivery_selection:
            self._deliver(state)

    def checkpoint(self) -> dict[str, Any]:
        """Save actual request-local executor state alongside a Store snapshot.

        These private experiment artifacts never enter the policy observation.
        Material indices, attempted bindings and generated View revisions are retained.
        """
        values = {name: copy.deepcopy(getattr(self, name)) for name in (
            "materials", "known_materials", "delivered_view_slots", "searched", "history_pages",
            "visibility_epoch", "views", "events", "source_directory")}
        values.update(configuration=self.checkpoint_configuration,
            opened=list(self.opened.items()), observed=list(self.observed.items()),
            search_attempts=sorted(self.search_attempts), attempted=sorted(self.attempted),
            used=sorted(self.used), refreshed_inputs=sorted(self.refreshed_inputs),
            observed_source_attempts=sorted(self.observed_source_attempts),
            source_pages=self.source_pages.checkpoint() if self.source_pages else None)
        return copy.deepcopy(values)

    def restore_checkpoint(self, saved: dict[str, Any],
                           source_observation: SourceObservationBudget | None) -> None:
        if saved["configuration"] != self.checkpoint_configuration:
            raise ValueError("CONTROL_CHECKPOINT_CONFIGURATION_CHANGED")
        for name in ("materials", "known_materials", "delivered_view_slots", "searched",
                     "history_pages", "visibility_epoch", "views", "events", "source_directory"):
            setattr(self, name, copy.deepcopy(saved[name]))
        self.opened = {index: copy.deepcopy(item) for index, item in saved["opened"]}
        self.observed = {index: copy.deepcopy(item) for index, item in saved["observed"]}
        self.search_attempts = {(query, limit) for query, limit in saved["search_attempts"]}
        self.attempted = {(index, expand) for index, expand in saved["attempted"]}
        self.used = set(saved["used"])
        self.refreshed_inputs = {(slot, tuple(refs), replace)
                                for slot, refs, replace in saved["refreshed_inputs"]}
        self.observed_source_attempts = {(ref, start, end)
                                        for ref, start, end in saved["observed_source_attempts"]}
        self.source_pages = None
        if saved["source_pages"] is not None:
            assert source_observation is not None
            self.source_pages = SourceObservationPages.restore(saved["source_pages"],
                                                                source_observation)

    @property
    def acquired(self) -> dict[int, dict[str, Any]]:
        return self.observed if self.delivery_selection else self.opened

    def _observe_source_page(self, state: MemoryControlState) -> None:
        assert self.source_pages is not None
        page = self.source_pages.current
        state.new_events = copy.deepcopy(page["events"])
        state.budget["source_observation"] = {
            **{key: value for key, value in page.items() if key != "events"},
            "max_tokens": self.source_pages.budget.max_tokens,
            "tokenizer": "Host text tokenizer; complete controller input checked separately"}

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
            **({"interpretation": copy.deepcopy(opened[slot]["structure"]),
                "interpretation_semantics": opened[slot]["semantics"],
                "query_time": opened[slot]["query_time"],
                "delivery": "controller_observation; Host receives only selected evidence"}
               if opened[slot].get("body_delivered") is not False else {}),
            **({"retrieval_request": view["retrieval_request"]}
               if "retrieval_request" in view else {}),
            "semantics": "binding/inventory status is not semantic correctness or full coverage"}
            for slot, view in self.views.items()]
        if self.source_pages is not None:
            for metadata in state.views:
                view = self.views[metadata["slot"]]
                metadata.update(pending_event_count=sum(
                    event["source_ref"] in self.source_pages.visible and self.pending(view, event)
                    for event in self.source_pages.events),
                    pending_events_scope="IDs on current source page; count covers all arrivals")
        return opened

    def refresh_visibility(self, state: MemoryControlState) -> None:
        epoch = self.service.forget_epoch
        if epoch == self.visibility_epoch:
            return
        self.visibility_epoch = epoch
        self.events = [s for e in self.events
                       if (s := self.service.source(e["event_id"])) is not None]
        self.source_directory = {s["event_id"]: s for s in self.events}
        visible = {s["event_id"] for s in self.events}
        state.new_events = [e for e in state.new_events if e["source_ref"] in visible]
        if self.source_pages is not None:
            self.source_pages.restrict(visible)
            self._observe_source_page(state)
        self.materials = [open_evidence_packs(self.service, [m], refresh_current=True)[0]
            if m["kind"] != "stored_revision" else m for m in self.materials]
        self.opened = dict(zip(self.opened, open_evidence_packs(
            self.service, list(self.opened.values()), refresh_current=True), strict=True))
        if self.delivery_selection:
            self.observed = dict(zip(self.observed, open_evidence_packs(
                self.service, list(self.observed.values()), refresh_current=True), strict=True))
        self._deliver(state)
        state.pending_candidates = [self.candidate(m, i) for i, m in enumerate(self.materials)
                                    if i not in self.acquired
                                    and not m.get("source_observation_read")]
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
        return tuple(sorted({span["source_ref"] for item in self.acquired.values()
            for span in [*item.get("source_ranges", []), *item.get("support_turns", [])]}))

    def observation_source_refs(self, state: MemoryControlState) -> list[str]:
        """Origins of controller-visible bodies/excerpts, distinct from Reader delivery."""
        refs = {event["source_ref"] for event in state.new_events}
        refs.update(self.source_refs())
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
        delivered = [span for opened in [*self.acquired.values(), *self.known_materials]
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

    def view_source_reads(self, state: MemoryControlState) -> list[MemoryAction]:
        """Bound locations allow original reads without claiming prior body delivery."""
        views = [view for view in state.views if view["visibility"] == "visible"]
        views.extend(item for item in self.known_materials
                     if item["kind"] == "query_structure"
                     and item.get("body_delivered") is not False)
        bindings = sorted({(binding["source_ref"], binding["source_revision"])
                           for view in views for binding in view["source_bindings"].values()})
        actions = []
        for number, (ref, revision) in enumerate(bindings):
            source = self.source_directory.get(ref)
            if source is None or source.get("source_revision", 1) != revision:
                continue
            end = len(body_text(source))
            span = {"source_ref": ref, "source_revision": revision, "start": 0, "end": end}
            if (ref, 0, end) not in self.observed_source_attempts and self.adds_source_range(
                    {"kind": "original_source", "source_ranges": [span]}):
                actions.append(MemoryAction(f"view_source_{number}", "READ",
                    "View-bound original source; location is not delivered evidence",
                    {"observed_source": span}))
        return actions

    def actions(self, state: MemoryControlState) -> list[MemoryAction]:
        self.refresh_visibility(state)
        actions = []
        history_records = set()
        if self.search_pool is not None:
            actions.extend(self.search_actions(state))
        elif not self.searched:
            actions.append(MemoryAction("search", "SEARCH", "original request"))
        if self.source_pages is not None:
            actions.extend(MemoryAction("source_page_" + direction, "READ",
                direction + " source-observation page (not Reader delivery)",
                {"source_observation_cursor": cursor})
                for direction, cursor in self.source_pages.navigation().items())
            for number, event in enumerate(state.new_events):
                ranges = [("fragment", event["source_range"])]
                if event["source_range"] != [0, event["source_characters"]]:
                    ranges.append(("full", [0, event["source_characters"]]))
                for extent, (start, end) in ranges:
                    source = self.source_directory[event["source_ref"]]
                    span = {"source_ref": event["source_ref"],
                            "source_revision": source.get("source_revision", 1),
                            "start": start, "end": end}
                    identity = (event["source_ref"], start, end)
                    if identity not in self.observed_source_attempts and self.adds_source_range(
                            {"kind": "original_source", "source_ranges": [span]}):
                        actions.append(MemoryAction(f"source_{extent}_{number}", "READ",
                            f"observed source {number} {extent} as original Reader evidence",
                            {"observed_source": span}))
        listed_spans = [action.parameters["observed_source"] for action in actions
                        if "observed_source" in action.parameters]
        actions.extend(action for action in self.view_source_reads(state)
                       if action.parameters["observed_source"] not in listed_spans)
        for i, item in sorted(enumerate(self.materials),
                              key=lambda pair: pair[1].get("control_pool_rank", pair[0])):
            if item.get("source_observation_read"):
                continue
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
        for slot in (structure_slots(self.view_capacity) if self.internal_views else []):
            view = self.views.get(slot)
            meta = next((v for v in state.views if v["slot"] == slot), None)
            suffix = "" if self.view_capacity == 1 else "_" + slot
            if view and slot not in self.used and meta and meta["visibility"] == "visible":
                actions.append(MemoryAction("use_view" + suffix, "USE_VIEW", view["id"],
                                            {"slot": slot}))
                if self.delivery_selection:
                    actions.append(MemoryAction("use_view_only" + suffix, "USE_VIEW", view["id"],
                        {"slot": slot, "replace_delivery": True}))
            if view is None and self.view_capacity > 1:
                continue
            refs = self.refresh_refs(state, slot)
            if refs and (slot, refs, False) not in self.refreshed_inputs:
                actions.append(MemoryAction("refresh_view" + suffix, "REFRESH_VIEW",
                    view["id"] if view else "current source scope",
                    {"source_refs": list(refs), "slot": slot}))
        if self.internal_views and self.view_capacity > 1:
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
        if self.delivery_selection:
            actions.extend(MemoryAction(a.id + "_observe", "READ",
                a.target + "; controller observation only", {**a.parameters, "observe_only": True})
                for a in list(actions) if a.kind == "READ"
                and not a.parameters.get("history_directory")
                and "source_observation_cursor" not in a.parameters)
        actions.append(MemoryAction("handoff", "HANDOFF", "Reader with opened evidence"))
        if self.delivery_selection:
            actions.extend(self.delivery_actions())
        return actions

    def delivery_actions(self) -> list[MemoryAction]:
        """Small acquired packets: single/pair, a View with up to two originals, or all."""
        indices = tuple(self.observed)
        originals = tuple(i for i, item in self.observed.items()
                          if item["kind"] == "original_source")
        views = [i for i, item in self.observed.items() if item["kind"] == "query_structure"]
        choices = [*combinations(indices, 1), *combinations(indices, 2),
                   *((v, *pair) for v in views for pair in combinations(originals, 2)),
                   originals, indices]
        actions = []
        for selected in dict.fromkeys(choices):
            if not selected:
                continue
            items = {i: self.observed[i] for i in selected}
            if items != self.opened and self.fits_delivery(items):
                actions.append(MemoryAction("handoff_select_" + "_".join(map(str, selected)),
                    "HANDOFF", "selected acquired material",
                    {"delivery_indices": list(selected)}))
        return actions

    def search_actions(self, state: MemoryControlState) -> list[MemoryAction]:
        """Bind searches to the request or actually opened text, never offline answers."""
        if len(self.search_attempts) >= self.max_searches:
            return []
        query = state.task["request"]
        goal = state.task.get("read_goal")
        points = goal.get("required_points", []) if isinstance(goal, dict) else []
        if self.delivery_selection:
            # Refer to actual request/material inputs instead of repeating long
            # source text for every batch-size option.
            bound: list[tuple[str, str, dict[str, Any]]] = [
                (query, "Host query", {"query_from": "request"})]
            bound.extend((point, "Host required point",
                          {"query_from": "required_point", "index": i})
                         for i, point in enumerate(points))
            bound.extend((item["index_text"], "acquired material",
                          {"query_from": "observed_material", "index": i})
                         for i, item in self.observed.items()
                         if item.get("body_delivered") is not False and item.get("index_text"))
            bound.extend((item["index_text"], "known material",
                          {"query_from": "known_material", "index": i})
                         for i, item in enumerate(self.known_materials)
                         if item.get("body_delivered") is not False and item.get("index_text"))
            unique_bound = {text: (origin, parameters) for text, origin, parameters in bound}
            return [MemoryAction(f"search_{i}_{limit}", "SEARCH", origin,
                                 {**parameters, "limit": limit})
                    for i, (text, (origin, parameters)) in enumerate(unique_bound.items())
                    for limit in self.search_batch_sizes
                    if (text, limit) not in self.search_attempts]
        queries = [(query, "Host query"), *(
            (point, "Host required point") for point in points)]
        queries.extend((item["index_text"], "opened evidence")
            for item in [*self.acquired.values(), *self.known_materials]
            if item.get("body_delivered") is not False and item.get("index_text"))
        unique = dict(queries)
        return [MemoryAction(f"search_{i}_{limit}", "SEARCH", origin,
                             {"query": text, "limit": limit})
                for i, (text, origin) in enumerate(unique.items())
                for limit in self.search_batch_sizes if (text, limit) not in self.search_attempts]

    def _deliver(self, state: MemoryControlState) -> None:
        state.visible_evidence = project_packs(list(self.opened.values()), list(self.opened))
        if self.delivery_selection:
            state.observed_materials = [{"item_index": i,
                "selected": self.opened.get(i) == item,
                **{key: copy.deepcopy(item[key]) for key in (
                    "kind", "id", "revision", "version_view", "visibility", "body_delivered",
                    "source_ranges", "source_bindings") if key in item}}
                for i, item in self.observed.items()]
            # Per-item source aliases distinguish these controller-only bodies from delivery.
            state.observed_evidence = [project_pack(item, i) for i, item in self.observed.items()
                                       if self.opened.get(i) != item]

    def fits_delivery(self, items: dict[int, dict[str, Any]]) -> bool:
        if self.fits_materials is not None:
            return self.fits_materials(items)
        return self.fits(project_packs(list(items.values()), list(items)))

    @staticmethod
    def candidate(item: dict[str, Any], index: int) -> dict[str, Any]:
        return {**pack_candidate(item, index), **{
            k: item[k] for k in ("revision", "version_view", "control_pool_rank",
                                "control_pool_selected", "control_dense_score") if k in item}}

    def internal_pool(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Disable internally retrieved derivations; explicit caller-known material stays intact."""
        return items if self.internal_views else [item for item in items if item["kind"] not in {
            "query_structure", "semantic_view", "stored_revision"}]

    def execute(self, action: MemoryAction, state: MemoryControlState) -> dict[str, Any]:
        if action.kind == "HANDOFF":
            selected = {i: self.observed[i] for i in action.parameters["delivery_indices"]}
            if not self.fits_delivery(selected):
                return {"ok": False, "status": "material_budget_exhausted"}
            self.opened = selected
            self._deliver(state)
            return {"ok": True, "status": "delivery_selected",
                    "delivery_indices": list(selected)}
        if action.kind == "SEARCH":
            if self.search_pool is None:
                self.materials = self.internal_pool(self.load_pool())
            else:
                parameters = action.parameters
                if "query_from" not in parameters:
                    query = parameters["query"]
                elif parameters["query_from"] == "request":
                    query = state.task["request"]
                elif parameters["query_from"] == "required_point":
                    query = state.task["read_goal"]["required_points"][parameters["index"]]
                else:
                    material = (self.observed[parameters["index"]]
                                if parameters["query_from"] == "observed_material"
                                else self.known_materials[parameters["index"]])
                    query = material["index_text"]
                limit = parameters["limit"]
                self.search_attempts.add((query, limit))
                found = self.internal_pool(self.search_pool(query, limit))
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
                                        if i not in self.acquired
                                        and not item.get("source_observation_read")]
            return {"ok": True, "status": "searched", "candidates": len(self.materials),
                    **action.parameters,
                    **({"query": query} if self.search_pool is not None else {}),
                    "scope": "captured visible pool, not a sufficiency judgment"}
        if action.kind == "READ":
            if "source_observation_cursor" in action.parameters:
                assert self.source_pages is not None
                self.source_pages.open(tuple(action.parameters["source_observation_cursor"]))
                self._observe_source_page(state)
                self.view_observation(state)
                return {"ok": True, "status": "source_observation_page", "body_delivered": False,
                        "reader_evidence_changed": False,
                        **state.budget["source_observation"]}
            if "observed_source" in action.parameters:
                span = action.parameters["observed_source"]
                self.observed_source_attempts.add((span["source_ref"], span["start"], span["end"]))
                source = self.source_directory[span["source_ref"]]
                i, expand = len(self.materials), False
                self.materials.append({"kind": "original_source",
                    "id": "observed-source:" + reference_key(span),
                    "session_id": source["session"], "turn_range": [0, 1],
                    "source_ranges": [span], "source_observation_read": True})
            else:
                i, expand = (action.parameters["index"],
                             action.parameters.get("expand_context", False))
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
            if self.delivery_selection:
                self.observed[i] = item
            trial = {**self.opened, i: item}
            observing = action.parameters.get("observe_only", False)
            delivered = not observing and self.fits_delivery(trial)
            if delivered:
                self.opened = trial
            elif not self.delivery_selection:
                return {"ok": False, "status": "material_budget_exhausted", "index": i}
            known = {source["event_id"] for source in self.events}
            for ref in self.source_refs():
                if ref not in known and (source := self.service.source(ref)) is not None:
                    self.events.append(source)
                    self.source_directory[ref] = source
                    known.add(ref)
            self._deliver(state)
            state.pending_candidates = [c for c in state.pending_candidates
                                        if c["item_index"] != i]
            return {"ok": item.get("body_delivered") is not False and (observing or delivered),
                    "status": ("observed" if observing else "opened" if delivered
                               else "material_budget_exhausted"),
                    "index": i, "visibility": item.get("visibility")}
        if action.kind == "USE_VIEW" and self.internal_views:
            slot = action.parameters.get("slot", "current")
            item = self.view_observation(state)[slot]
            self.used.add(slot)
            if self.view_capacity > 1:
                touch_structure(self.service, slot)
        elif action.kind == "REFRESH_VIEW" and self.internal_views:
            refs = tuple(action.parameters["source_refs"])
            slot = action.parameters.get("slot", "current")
            replace = action.parameters.get("new_scope", False)
            self.refreshed_inputs.add((slot, refs, replace))
            events = [s for e in self.events
                      if (s := self.service.source(e["event_id"])) is not None]
            coverage = None
            if self.source_pages is not None:
                # A partial observation cannot acknowledge every unseen arrival.
                observed = {event["source_ref"] for event in state.new_events}
                observed.update(refs)
                observed.update(binding["source_ref"] for view in self.views.values()
                                for binding in view["source_bindings"].values())
                events = [event for event in events if event["event_id"] in observed]
                coverage = self.source_pages.coverage()
            try:
                built, report = build_query_structure(self.service, state.task["request"],
                    state.task["query_time"], list(refs), policy=self.view_policy,
                    call=self.refresh_call,
                    source_events=events, force_refresh=True, slot=slot,
                    capacity=self.view_capacity, replace_slot=replace,
                    retrieval_request=state.task.get("retrieval_request"),
                    arrival_coverage=coverage)
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
        if self.delivery_selection:
            view_index = next((i for i, prior in self.observed.items()
                               if prior["kind"] == "query_structure" and prior["id"] == item["id"]),
                              min([0, *self.observed]) - 1)
            self.observed[view_index] = item
        trial = ({} if action.parameters.get("replace_delivery") else dict(self.opened))
        if self.delivery_selection and slot in self.delivered_view_slots:
            trial.pop(self.delivered_view_slots[slot], None)
        trial[view_index] = item
        delivered = self.fits_delivery(trial)
        if delivered:
            self.opened = trial
            if self.delivery_selection:
                self.delivered_view_slots[slot] = view_index
        if delivered or self.delivery_selection:
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
