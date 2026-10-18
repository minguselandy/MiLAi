"""Dynamic actions executed by the existing evidence and query-structure modules."""
from __future__ import annotations

import copy
import time
from collections.abc import Callable
from typing import Any

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import open_evidence_packs, pack_candidate, project_packs
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.query_structure import (
    build_query_structure,
    cached_structure,
    open_structure,
)


class EvidenceOperations:
    """A request-local material set; persistent views remain in the original Store."""

    def __init__(
        self, service: MemoryService, state: MemoryControlState, *,
        load_pool: Callable[[], list[dict[str, Any]]],
        refresh_call: Callable[[list[dict[str, str]], dict[str, Any]], dict[str, Any]],
        fits: Callable[[list[dict[str, Any]]], bool],
        excluded_source_refs: tuple[str, ...] = (),
    ) -> None:
        self.service, self.load_pool, self.refresh_call, self.fits = (
            service, load_pool, refresh_call, fits)
        self.materials: list[dict[str, Any]] = []
        self.opened: dict[int, dict[str, Any]] = {}
        self.attempted: set[tuple[int, bool]] = set()
        self.searched = False
        self.used = False
        self.refreshed_inputs: set[tuple[str, ...]] = set()
        self.view = cached_structure(service)
        # D1 scans once, explicitly measured; D4 replaces this with an incremental feed.
        started = time.perf_counter()
        self.events = [s for s in service.sources() if s["event_id"] not in excluded_source_refs]
        state.budget["source_inventory_wall_seconds"] = time.perf_counter() - started
        cursor = self.view["arrival_cursor"] if self.view else []
        arrivals = [s for s in self.events if [s["observed_at"], s["event_id"]] > cursor]
        state.new_events = [{"source_ref": s["event_id"], "role": s["role"],
            "reported_at": s.get("occurred_at"), "captured_at": s["observed_at"]}
            for s in arrivals]
        state.budget["visible_sources_enumerated"] = len(self.events)
        if self.view:
            opened = open_structure(service, self.view)
            state.views = [{"id": self.view["id"], "scope": self.view["index_text"],
                "revision": self.view["revision"], "visibility": opened["visibility"],
                "pending_events": [s["event_id"] for s in arrivals],
                "source_bindings": self.view["source_bindings"],
                "semantics": "binding status is not semantic correctness"}]

    def source_refs(self) -> tuple[str, ...]:
        return tuple(sorted({span["source_ref"] for item in self.opened.values()
            for span in [*item.get("source_ranges", []), *item.get("support_turns", [])]}))

    def actions(self, state: MemoryControlState) -> list[MemoryAction]:
        actions = []
        if not self.searched:
            actions.append(MemoryAction("search", "SEARCH", "original request"))
        for i, item in enumerate(self.materials):
            if (i, False) not in self.attempted:
                actions.append(MemoryAction(f"read_{i}", "READ", f"candidate {i}", {"index": i}))
            if (i, False) in self.attempted and (i, True) not in self.attempted and (
                item.get("context_source_ranges") != item.get("source_ranges")
            ) and item.get("context_source_ranges"):
                actions.append(MemoryAction(f"context_{i}", "READ", f"candidate {i} context",
                                            {"index": i, "expand_context": True}))
        if self.view and not self.used and state.views[0]["visibility"] == "visible":
            actions.append(MemoryAction("use_view", "USE_VIEW", self.view["id"]))
        refs = self.source_refs()
        if refs and refs not in self.refreshed_inputs:
            actions.append(MemoryAction("refresh_view", "REFRESH_VIEW", "current source scope",
                                       {"source_refs": list(refs)}))
        actions.append(MemoryAction("handoff", "HANDOFF", "Reader with opened evidence"))
        return actions

    def _deliver(self, state: MemoryControlState) -> None:
        state.visible_evidence = project_packs(list(self.opened.values()), list(self.opened))

    def execute(self, action: MemoryAction, state: MemoryControlState) -> dict[str, Any]:
        if action.kind == "SEARCH":
            self.materials = self.load_pool()
            self.searched = True
            state.pending_candidates = [pack_candidate(item, i)
                                        for i, item in enumerate(self.materials)]
            return {"ok": True, "status": "searched", "candidates": len(self.materials),
                    "scope": "captured visible pool, not a sufficiency judgment"}
        if action.kind == "READ":
            i, expand = action.parameters["index"], action.parameters.get("expand_context", False)
            self.attempted.add((i, expand))
            item = open_evidence_packs(self.service, [self.materials[i]],
                                      expand_context=expand, refresh_current=True)[0]
            trial = {**self.opened, i: item}
            if not self.fits(project_packs(list(trial.values()), list(trial))):
                return {"ok": False, "status": "material_budget_exhausted", "index": i}
            self.opened = trial
            self._deliver(state)
            state.pending_candidates = [c for c in state.pending_candidates
                                        if c["item_index"] != i]
            return {"ok": item.get("body_delivered") is not False,
                    "status": "opened", "index": i, "visibility": item.get("visibility")}
        if action.kind == "USE_VIEW":
            assert self.view is not None
            item = open_structure(self.service, self.view)
            self.used = True
        elif action.kind == "REFRESH_VIEW":
            refs = self.source_refs()
            self.refreshed_inputs.add(refs)
            built, report = build_query_structure(self.service, state.task["request"],
                state.task["query_time"], list(refs), policy="incremental", call=self.refresh_call,
                source_events=self.events, force_refresh=True)
            if built is None:
                return {"ok": False, "status": "empty_source_pool", "report": report}
            item = built
            self.view = copy.deepcopy(item)
            state.views = [{"id": item["id"], "revision": item["revision"],
                "scope": item["index_text"], "pending_events": [], "visibility": "visible",
                "source_bindings": item["source_bindings"]}]
            self.used = True
        else:
            raise ValueError(f"Non-executable operation: {action.kind}")
        item["query_time"] = state.task["query_time"]
        trial = {**self.opened, -1: item}
        delivered = self.fits(project_packs(list(trial.values()), list(trial)))
        if delivered:
            self.opened = trial
            self._deliver(state)
        return {"ok": item.get("body_delivered") is not False and delivered,
                "status": "view_opened" if delivered else "material_budget_exhausted",
                "view_id": item["id"], "revision": item.get("revision"),
                **({"report": report} if action.kind == "REFRESH_VIEW" else {})}

    def reader_evidence(self) -> list[dict[str, Any]]:
        """Recheck visibility on delivery, including after a later same-request forget."""
        actual = open_evidence_packs(self.service, list(self.opened.values()), refresh_current=True)
        return project_packs(actual, list(self.opened))
