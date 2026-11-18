"""Bind immutable public sources to the existing MiLAi evidence executor."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, cast

from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.datasets.memory_control_store import body_text, unpack
from milai_lab.datasets.memory_control_views import SourceObject, Span, literal_view
from milai_lab.memory.retrieval import SourceSearchCache
from milai_lab.memory.service import MemoryService
from milai_lab.memory.source_materials import read_original_materials
from milai_lab.methods.control_observation import control_input
from milai_lab.methods.corpus_navigation import excerpt, query_terms
from milai_lab.methods.dataset_reader import DatasetReader, PacketPlan, ReaderTask
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.literal_delivery_union import (
    DELIVERY_PROTOCOL,
    LiteralDelivery,
    literal_delivery,
)
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState


@dataclass(frozen=True)
class ReadView:
    id: int
    object_id: int
    ranges: list[Span]
    reader_tokens: int
    encoder_tokens: int
    context_id: int | None


class CorpusPool:
    """A search index for exactly one paper, paragraph pool, or dialogue."""

    forget_epoch = 0  # The pinned snapshot has no mutations.

    def __init__(self, db: sqlite3.Connection, root_id: int, *, load_sources: bool = True) -> None:
        self.root_id = root_id
        self._documents: list[dict[str, Any]] | None = None
        self.cache = SourceSearchCache()
        if not load_sources:
            self.objects = {}
            self.by_ref = {}
            self.views = {}
            self.focus_ids = []
            return
        self.objects = {
            row["id"]: SourceObject(
                row["id"],
                row["position"],
                row["kind"],
                row["role"],
                row["preview"],
                body_text(row["body"]),
                row["block"],
            )
            for row in db.execute(
                "SELECT * FROM objects WHERE root_id=? ORDER BY position", (root_id,)
            )
        }
        self.by_ref = {self.ref(oid): obj for oid, obj in self.objects.items()}
        self.views = {
            row["id"]: ReadView(
                row["id"],
                row["object_id"],
                [tuple(span) for span in unpack(row["ranges"])],
                row["reader_tokens"],
                row["encoder_tokens"],
                row["context_id"],
            )
            for row in db.execute(
                """
                SELECT v.*,c.context_id FROM objects o JOIN views v ON v.object_id=o.id
                LEFT JOIN candidates c ON c.focus_id=v.id
                WHERE o.root_id=? AND v.tier IN ('R2','R3') ORDER BY o.position,v.page,v.tier
            """,
                (root_id,),
            )
        }
        self.focus_ids = [row["id"] for row in db.execute("""
            SELECT v.id FROM objects o JOIN views v ON v.object_id=o.id
            JOIN candidates c ON c.focus_id=v.id WHERE o.root_id=? ORDER BY o.position,v.page
        """, (root_id,))]

    @property
    def documents(self) -> list[dict[str, Any]]:
        if self._documents is None:
            self._documents = [{"id": vid, "index_text": self.search_text(self.views[vid])}
                               for vid in self.focus_ids]
        return self._documents

    def ref(self, oid: int) -> str:
        return f"s{self.objects[oid].position}"

    def source(self, ref: str) -> dict[str, Any] | None:
        obj = self.by_ref.get(ref)
        if obj is None or obj.kind == "message_block":
            return None
        return {
            "event_id": ref,
            "content": obj.body,
            "role": obj.role,
            "origin": (
                "figure_caption_only"
                if obj.kind == "caption_only"
                else "dialogue"
                if obj.kind == "message"
                else "reference_document"
            ),
            "session": "visible_source_scope",
            "source_revision": 1,
            "observed_at": None,
        }

    def source_arrivals(self, since: str | None) -> dict[str, Any]:
        return {"events": [], "rows_materialized": 0, "query": "immutable_snapshot"}

    def read_source_materials(self, materials: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        return read_original_materials(materials, self.source)

    def search_text(self, view: ReadView) -> str:
        obj = self.objects[view.object_id]
        prefix = obj.preview + "\n" if obj.kind != "message" and obj.preview else ""
        return prefix + literal_view(view.ranges, self.objects)

    def rank(self, query: str, limit: int) -> list[int]:
        ranked, _ = self.cache.rank(
            self.documents,
            query,
            limit,
            scope=(self.root_id,),
            tokenization="unicode_v1",
            timings={},
        )
        return [row["id"] for row in ranked]

    def descriptor(self, focus_id: int) -> dict[str, Any]:
        focus = self.views[focus_id]
        detail = self.views[focus.context_id] if focus.context_id is not None else None
        obj = self.objects[focus.object_id]

        def ranges(view: ReadView) -> list[dict[str, Any]]:
            return [
                {"source_ref": self.ref(oid), "source_revision": 1, "start": start, "end": end}
                for oid, start, end in view.ranges
            ]

        source_ranges = ranges(focus)
        descriptor = {
            "kind": "original_source",
            "id": f"source-page:{focus_id}",
            "session_id": "visible_source_scope",
            "turn_range": [obj.position, obj.position + 1],
            "index_text": obj.preview,
            "source_ranges": source_ranges,
            "focus_source_ranges": source_ranges,
            "evidence_representation": {
                "level": "R2",
                "focus_reader_tokens": focus.reader_tokens,
                "context_reader_tokens": detail.reader_tokens if detail else None,
                "caption_only": obj.kind == "caption_only",
            },
        }
        if detail is not None:
            expanded = ranges(detail)
            positions = [self.objects[oid].position for oid, _, _ in detail.ranges]
            descriptor.update(
                context_source_ranges=expanded,
                context_turn_range=[min(positions), max(positions) + 1],
            )
        return descriptor

    def navigation(
        self, query: str, focus: list[int], encoder: Tokenizer, limit: int,
    ) -> dict[int, dict[str, Any]]:
        if limit <= 0:
            raise ValueError("Positive navigation token capacity is required")
        terms = query_terms(query)
        result = {}
        for vid in focus:
            found = excerpt(terms, self.views[vid].ranges, self.objects, encoder, limit)
            if found is not None:
                oid, fields = found
                result[vid] = {
                    "source_ref": self.ref(oid), "source_revision": 1, **fields,
                }
        return result

    def normalized_delivery(self, opened: dict[int, dict[str, Any]]) -> LiteralDelivery:
        return literal_delivery(opened, self.read_source_materials,
                                lambda ref: self.by_ref[ref].position)

    def bound_view(self, candidates: list[int], action: MemoryAction) -> int | None:
        if action.kind != "READ":
            return None
        focus = self.views[candidates[action.parameters["index"]]]
        if action.parameters.get("expand_context"):
            if focus.context_id is None:
                raise ValueError("READ binding offers unavailable context")
            return focus.context_id
        return focus.id


class CorpusExecution:
    """Replay actually opened views and use EvidenceOperations for all legal actions."""

    def __init__(
        self, pool: CorpusPool, query: str, focus: list[int], reader: Tokenizer,
        material_limit: int,
        *, public_task: ReaderTask | None = None, host: DatasetReader | None = None,
        navigation: dict[int, dict[str, Any]] | None = None,
        shared_preflight: dict[tuple[tuple[str, ...], str], tuple[int, bool | None, str | None]]
        | None = None,
    ) -> None:
        self.pool, self.focus, self.reader = pool, focus, reader
        self.material_limit = material_limit
        if (public_task is None) != (host is None):
            raise ValueError("Exact delivery requires both a public Reader task and its Host")
        self.public_task, self.host = public_task, host
        self.preflight_wall_ms = 0.0
        self._feasibility: dict[str, tuple[bool | None, str | None]] = {}
        self.shared_preflight = shared_preflight
        self.state = MemoryControlState(
            task={
                "request": query,
                "retrieval_request": {
                    "query": query,
                    "read_goal": {"evidence": ["original_source"]},
                },
            }
        )
        navigation = navigation or {}
        menu = [pool.descriptor(vid) for vid in focus]
        if host is not None:
            for rank, (vid, item) in enumerate(zip(focus, menu, strict=True)):
                item["control_pool_rank"] = rank
                if vid in navigation:
                    item["navigation_excerpt"] = navigation[vid]

        def unavailable(*_: Any) -> Any:
            raise RuntimeError("The pinned static corpus has no version generation")

        # This read-only configuration touches only the Source access methods
        # implemented by CorpusPool. The original menu, binding and READ remain shared.
        self.ops = EvidenceOperations(
            cast(MemoryService, pool),
            self.state,
            load_pool=lambda: menu,
            refresh_call=unavailable,
            fits=self.fits,
            internal_views=False,
            view_updates=False,
            source_directory_only=True,
            material_protocol=DELIVERY_PROTOCOL if host else None,
            delivery_projection=(lambda items: pool.normalized_delivery(items).evidence)
            if host else None,
        )
        self.state.budget.pop("source_inventory_wall_seconds")
        self.prefix: list[str] = []
        self.opened: dict[int, int] = {}
        self.initial_packet = self.plan_packet([]) if host else None
        self.used_tokens = (self.initial_packet.material_tokens if self.initial_packet
                            else self.material_cost([]))
        self.trial_tokens = self.used_tokens
        self.trial_failure: str | None = None

    def material_cost(self, items: list[dict[str, Any]]) -> int:
        packet = controlled_reader_packet(items, "policy_handoff")
        return len(
            self.reader.encode(json.dumps(packet, ensure_ascii=False), add_special_tokens=False).ids
        )

    def fits(self, items: list[dict[str, Any]]) -> bool:
        if self.host is not None:
            plan = self.plan_packet(items)
            self.trial_tokens, self.trial_failure = plan.material_tokens, plan.failure_reason
            return plan.feasible is True
        self.trial_tokens = self.material_cost(items)
        return self.trial_tokens <= self.material_limit

    def plan_packet(self, evidence: list[dict[str, Any]]) -> PacketPlan:
        if self.host is None or self.public_task is None:
            raise ValueError("No Reader protocol with full Host capacity")
        return self.host.plan(evidence, self.public_task, self.material_limit)

    def feasibility(self, action: MemoryAction) -> tuple[bool | None, str | None]:
        if self.host is None or action.kind != "READ":
            return None, None
        if action.id not in self._feasibility:
            started = time.perf_counter()
            key = (tuple(self.prefix), action.id)
            counts = self.shared_preflight.get(key) if self.shared_preflight is not None else None
            if counts is None:
                index = action.parameters["index"]
                item = self.ops.open_bound_read(index,
                                                action.parameters.get("expand_context", False))
                if item.get("body_delivered") is False:
                    counts = 0, False, "source_unavailable"
                else:
                    evidence = self.ops.project_delivery({**self.ops.opened, index: item})
                    packet = self.plan_packet(evidence)
                    counts = (packet.material_tokens, packet.host_fits,
                              self.public_task.invalid_reason if self.public_task else None)
                    if packet.host_fits is False:
                        counts = packet.material_tokens, False, "host_request_capacity_exceeded"
                if self.shared_preflight is not None:
                    self.shared_preflight[key] = counts
            material_tokens, host_fits, reason = counts
            result = ((False, "material_budget_exhausted") if material_tokens > self.material_limit
                      else (host_fits, reason))
            self._feasibility[action.id] = result
            self.preflight_wall_ms += (time.perf_counter() - started) * 1000
        return self._feasibility[action.id]

    def feasible_menu(self, actions: list[MemoryAction]) -> list[MemoryAction]:
        if self.host is None:
            return actions
        return [action for action in actions if action.kind != "READ"
                or self.feasibility(action)[0] is True]

    def raw_actions(self, state: MemoryControlState) -> list[MemoryAction]:
        state.budget.update(
            reader_material_tokens=self.material_limit,
            remaining_reader_material_tokens=self.material_limit - self.used_tokens,
        )
        if self.host is not None:
            state.budget["successful_reads"] = sum(a != "search" for a in self.prefix)
        return self.ops.actions(state)

    def actions(self, state: MemoryControlState) -> list[MemoryAction]:
        return self.feasible_menu(self.raw_actions(state))

    def menu(self, steps: int) -> list[MemoryAction]:
        self.state.budget.update(
            remaining_control_steps=steps - len(self.prefix), reader_capacity_reserved=True
        )
        return self.raw_actions(self.state)

    def execute(self, action: MemoryAction, state: MemoryControlState) -> dict[str, Any]:
        self.trial_failure = None
        result = self.ops.execute(action, state)
        if self.host is None or result["ok"]:
            self.prefix.append(action.id)
        elif self.trial_failure:
            result["status"] = self.trial_failure
        self._feasibility.clear()
        if result["ok"] and (vid := self.pool.bound_view(self.focus, action)) is not None:
            self.opened[action.parameters["index"]] = vid
            self.used_tokens = self.trial_tokens
            state.budget["remaining_reader_material_tokens"] = (
                self.material_limit - self.used_tokens
            )
        return result

    def take(self, action: MemoryAction) -> bool:
        result = self.execute(action, self.state)
        self.state.last_result = {"action": asdict(action), **result}
        return bool(result["ok"])

    def replay(self, steps: int, prefix: list[str]) -> list[MemoryAction]:
        for identifier in prefix:
            action = next(action for action in self.menu(steps) if action.id == identifier)
            if not self.take(action):
                raise ValueError("Recorded prefix did not deliver its original view")
        return self.menu(steps)

    def online(self, actions: list[MemoryAction]) -> dict[str, Any]:
        return control_input(self.state, actions)
