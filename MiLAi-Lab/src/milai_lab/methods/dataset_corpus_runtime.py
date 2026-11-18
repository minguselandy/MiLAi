"""Bind immutable public sources to the existing MiLAi evidence executor."""

from __future__ import annotations

import json
import sqlite3
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
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
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

    def __init__(self, db: sqlite3.Connection, root_id: int) -> None:
        self.root_id = root_id
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
        self.documents = [
            {"id": row["id"], "index_text": self.search_text(self.views[row["id"]])}
            for row in db.execute(
                """
                SELECT v.id FROM objects o JOIN views v ON v.object_id=o.id
                JOIN candidates c ON c.focus_id=v.id WHERE o.root_id=? ORDER BY o.position,v.page
            """,
                (root_id,),
            )
        ]
        self.cache = SourceSearchCache()

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
        self, pool: CorpusPool, query: str, focus: list[int], reader: Tokenizer, material_limit: int
    ) -> None:
        self.pool, self.focus, self.reader = pool, focus, reader
        self.material_limit = material_limit
        self.state = MemoryControlState(
            task={
                "request": query,
                "retrieval_request": {
                    "query": query,
                    "read_goal": {"evidence": ["original_source"]},
                },
            }
        )
        menu = [pool.descriptor(vid) for vid in focus]

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
        )
        self.state.budget.pop("source_inventory_wall_seconds")
        self.prefix: list[str] = []
        self.opened: dict[int, int] = {}
        self.used_tokens = self.material_cost([])
        self.trial_tokens = self.used_tokens

    def material_cost(self, items: list[dict[str, Any]]) -> int:
        packet = controlled_reader_packet(items, "policy_handoff")
        return len(
            self.reader.encode(json.dumps(packet, ensure_ascii=False), add_special_tokens=False).ids
        )

    def fits(self, items: list[dict[str, Any]]) -> bool:
        self.trial_tokens = self.material_cost(items)
        return self.trial_tokens <= self.material_limit

    def actions(self, state: MemoryControlState) -> list[MemoryAction]:
        state.budget.update(
            reader_material_tokens=self.material_limit,
            remaining_reader_material_tokens=self.material_limit - self.used_tokens,
        )
        return self.ops.actions(state)

    def menu(self, steps: int) -> list[MemoryAction]:
        self.state.budget.update(
            remaining_control_steps=steps - len(self.prefix), reader_capacity_reserved=True
        )
        return self.actions(self.state)

    def execute(self, action: MemoryAction, state: MemoryControlState) -> dict[str, Any]:
        result = self.ops.execute(action, state)
        self.prefix.append(action.id)
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
