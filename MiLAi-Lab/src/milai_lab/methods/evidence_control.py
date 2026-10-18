"""Dynamic actions executed by the existing evidence and query-structure modules."""
from __future__ import annotations

import copy
import time
from collections.abc import Callable
from typing import Any

from milai_lab.memory.functional_state import body_text
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    pack_candidate,
    project_packs,
)
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.query_structure import (
    build_query_structure,
    cached_structure,
    open_structure,
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
    ) -> None:
        self.service, self.load_pool, self.refresh_call, self.fits = (
            service, load_pool, refresh_call, fits)
        self.materials: list[dict[str, Any]] = []
        self.opened: dict[int, dict[str, Any]] = {}
        self.attempted: set[tuple[int, bool]] = set()
        self.searched = False
        self.used = False
        self.refreshed_inputs: set[tuple[str, ...]] = set()
        self.history_pages: dict[str, dict[str, Any]] = {}
        self.view = cached_structure(service)
        # D1 scans once, explicitly measured; D4 replaces this with an incremental feed.
        started = time.perf_counter()
        self.events = [s for s in service.sources() if s["event_id"] not in excluded_source_refs]
        state.budget["source_inventory_wall_seconds"] = time.perf_counter() - started
        cursor = self.view["arrival_cursor"] if self.view else []
        arrivals = [s for s in self.events if [s["observed_at"], s["event_id"]] > cursor]
        state.new_events = [{"source_ref": s["event_id"], "role": s["role"],
            "content": body_text(s), "origin": s.get("origin"),
            "delivery": "controller_observation; Reader uses visible_evidence",
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

    def adds_source_range(self, item: dict[str, Any], *, expand: bool = False) -> bool:
        """Availability uses actual versioned intervals, never semantic sufficiency."""
        if item["kind"] != "original_source":
            return True
        delivered = [span for opened in self.opened.values()
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
        actions = []
        history_records = set()
        if not self.searched:
            actions.append(MemoryAction("search", "SEARCH", "original request"))
        for i, item in enumerate(self.materials):
            if (i, False) not in self.attempted and self.adds_source_range(item):
                actions.append(MemoryAction(f"read_{i}", "READ", f"candidate {i}", {"index": i}))
            if (i, False) in self.attempted and (i, True) not in self.attempted and (
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

    @staticmethod
    def candidate(item: dict[str, Any], index: int) -> dict[str, Any]:
        return {**pack_candidate(item, index), **{
            k: item[k] for k in ("revision", "version_view") if k in item}}

    def execute(self, action: MemoryAction, state: MemoryControlState) -> dict[str, Any]:
        if action.kind == "SEARCH":
            self.materials = self.load_pool()
            self.searched = True
            state.pending_candidates = [self.candidate(item, i)
                                        for i, item in enumerate(self.materials)]
            return {"ok": True, "status": "searched", "candidates": len(self.materials),
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
