"""Read-only inference over a prebuilt artifact using the ordinary evidence executor.

Queries, allowances, history cursors and delivered references live only in this
task-local object. No Source capture, authorization-handle issuance, View update,
recency touch or persistent retrieval snapshot is performed.
"""
from __future__ import annotations

import copy
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional import normalize_read_goal
from milai_lab.memory.functional_state import FunctionalRejection, canonical
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    project_packs,
)
from milai_lab.methods.intent_retrieval import retrieval_packet
from milai_lab.methods.memory_control import (
    MemoryAction,
    MemoryControlState,
    MemoryPolicy,
    run_memory_control,
)
from milai_lab.methods.source_observations import SourceObservationBudget


@contextmanager
def open_readonly_store(database: Path) -> Iterator[SqliteStore]:
    """Open an already-prepared SDK artifact with SQLite's own write prohibition."""
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True,
                                 check_same_thread=False)) as connection:
        store = SqliteStore(connection)
        store.setup()  # Existing schema only; an artifact needing migration must be built offline.
        yield store


class ReadOnlyMemoryService(MemoryService):
    """Retrieval port: reads never issue mutation credentials or persist history cursors."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.history_snapshots: dict[str, dict[str, Any]] = {}

    def read(self, memory_id: str, revision: int | None = None, *,
             issue_candidate: bool = False) -> dict[str, Any]:
        return super().read(memory_id, revision, issue_candidate=False)

    def history_index(self, memory_id: str, *, cursor: str | None = None, limit: int = 6,
                      source_ref: str | None = None,
                      transient_snapshots: dict[str, dict[str, Any]] | None = None,
                      ) -> dict[str, Any]:
        return super().history_index(memory_id, cursor=cursor, limit=limit,
            source_ref=source_ref, transient_snapshots=self.history_snapshots)


class ReadOnlyRetrieval:
    """Finite retrieval with the same Source/View/range/return-budget semantics.

    One instance belongs to one task. Persistent memory is supplied by a prebuilt
    ReadOnlyMemoryService; public turns are tracked without storing their text.
    """

    def __init__(self, service: ReadOnlyMemoryService, token_count: Callable[[str], int],
                 policy: MemoryPolicy, *, material_limit: int = 2048, read_limit: int = 8,
                 control_steps: int = 8, source_top_k: int = 16, semantic_top_k: int = 16,
                 view_capacity: int = 1, source_observation_tokens: int | None = None,
                 record: Callable[[dict[str, Any]], None] = lambda _: None,
                 available: Callable[[], bool] = lambda: True,
                 return_envelope: Callable[[dict[str, Any]], Any] | None = None,
                 rank_pool: Callable[[str, list[dict[str, Any]]],
                                     list[dict[str, Any]]] | None = None) -> None:
        self.service, self.token_count, self.policy = service, token_count, policy
        self.material_limit, self.read_limit, self.control_steps = (
            material_limit, read_limit, control_steps)
        self.source_top_k, self.semantic_top_k = source_top_k, semantic_top_k
        self.view_capacity = view_capacity
        self.source_observation_tokens = source_observation_tokens
        self.record, self.available, self.return_envelope = record, available, return_envelope
        self.rank_pool = rank_pool
        self.turn: str | None = None
        self.remaining_reads = 0
        self.snapshots: dict[str, list[dict[str, Any]]] = {}
        self.session_id = "readonly-" + str(uuid.uuid4())

    def begin_turn(self, turn: str) -> None:
        if turn != self.turn:
            self.turn, self.remaining_reads = turn, self.read_limit

    def return_tokens(self, packet: dict[str, Any]) -> int:
        return self.token_count(canonical(
            self.return_envelope(packet) if self.return_envelope else packet))

    def retrieve(self, request: RetrievalRequest) -> dict[str, Any]:
        if self.turn is None:
            raise ValueError("READ_ONLY_RETRIEVAL_REQUIRES_PUBLIC_TURN")
        key = f"{self.session_id}:{len(self.snapshots)}"
        known = []
        for ref in request.task_context.known_evidence_refs:
            items = self.snapshots.get(ref.snapshot_id)
            if items is None or ref.item_index >= len(items):
                raise FunctionalRejection("RETRIEVAL_REFERENCE_NOT_DELIVERED")
            known.append(copy.deepcopy(items[ref.item_index]))
        steps = min(self.control_steps, request.limits.max_control_steps
                    if request.limits.max_control_steps is not None else self.control_steps)
        limit = min(self.material_limit, request.limits.max_return_tokens or self.material_limit)
        known_read_exhausted = bool(known) and not self.remaining_reads
        if known:
            if not self.remaining_reads:
                steps, known = 0, []
            else:
                self.remaining_reads -= 1
                known = open_evidence_packs(self.service, known)
        state = MemoryControlState(task={"request": request.query,
            "query_time": request.task_context.as_of or "", "mode": "retrieve",
            "read_goal": normalize_read_goal(request.read_goal),
            "retrieval_request": request.project(),
            "known_evidence": project_packs(known, list(range(len(known))))},
            budget={"max_return_tokens": limit, "persistent_memory_read_only": True})

        def search(query: str, count: int) -> list[dict[str, Any]]:
            original = self.service.search_sources(query, limit=min(count, self.source_top_k),
                                                    tokenization="unicode_v1")
            records = self.service.search(query, limit=min(count, self.semantic_top_k),
                                          include_raw=False)["records"]
            materials = build_evidence_packs(self.service, request.query,
                request.task_context.as_of or "", original["source_materials"], records)
            return self.rank_pool(query, materials) if self.rank_pool else materials

        def fits(items: dict[int, dict[str, Any]]) -> bool:
            usage = {"control_steps": steps, "known_reference_reads": len(known),
                "operations": steps, "read_operations": steps, "material_budget_rejections": steps}
            return all(self.return_tokens(retrieval_packet(key, list(items.values()), list(items),
                list(range(len(items))), reason, usage, ok=False)) <= limit for reason in (
                    "policy_handoff", "budget_exhausted", "no_available_operation",
                    "operation_outcome_unknown"))

        def no_refresh(*_args: Any) -> dict[str, Any]:
            raise ValueError("READ_ONLY_VIEW_REFRESH_UNAVAILABLE")

        operations = EvidenceOperations(self.service, state, load_pool=lambda: search(
            request.query, self.source_top_k), search_pool=search, refresh_call=no_refresh,
            fits=lambda evidence: self.token_count(canonical(evidence)) <= limit,
            fits_materials=fits, delivery_selection=True, view_updates=False,
            known_materials=known, view_capacity=self.view_capacity,
            source_observation=(SourceObservationBudget(self.source_observation_tokens,
                self.token_count) if self.source_observation_tokens is not None else None))
        memory = self

        class Admitted:
            def actions(self, observed: MemoryControlState) -> list[MemoryAction]:
                offered = operations.actions(observed)
                observed.budget["acquisition_reads_remaining"] = memory.remaining_reads
                return offered if memory.remaining_reads else [
                    action for action in offered if action.kind == "HANDOFF"]

            def execute(self, action: MemoryAction, observed: MemoryControlState) -> dict[str, Any]:
                if action.kind != "HANDOFF":
                    memory.remaining_reads -= 1
                return operations.execute(action, observed)

        result = run_memory_control(state, self.policy, Admitted(), max_steps=steps,
            record=self.record, can_continue=lambda: self.available()
                and (bool(self.remaining_reads) or bool(operations.observed)))
        trace = result["trace"]
        items = open_evidence_packs(self.service, list(operations.opened.values()))
        packet = retrieval_packet(key, items, list(operations.opened), list(range(len(items))),
            result["reason"], {"control_steps": len(trace), "known_reference_reads": len(known),
                "operations": sum("result" in event for event in trace),
                "read_operations": sum(any(a["id"] == e["selected"] and a["kind"] == "READ"
                    for a in e["actions"]) for e in trace),
                "material_budget_rejections": sum(e.get("result", {}).get("status")
                    == "material_budget_exhausted" for e in trace)},
            ok=not known_read_exhausted and result["reason"] != "operation_outcome_unknown")
        if self.return_tokens(packet) > limit:
            raise FunctionalRejection("RETRIEVAL_RETURN_ENVELOPE_EXCEEDS_LIMIT")
        self.snapshots[key] = copy.deepcopy(items)
        self.record({"event": "readonly_retrieve_result", "request": request.project(),
                     "result": packet, "control": result})
        return packet
