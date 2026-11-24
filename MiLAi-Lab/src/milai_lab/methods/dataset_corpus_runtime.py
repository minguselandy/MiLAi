"""Bind immutable public sources to the existing MiLAi evidence executor."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, cast

from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.datasets.memory_control_protocols import NUMERIC_SCHEMA
from milai_lab.datasets.memory_control_reader_task import ReaderTask
from milai_lab.datasets.memory_control_store import body_text, unpack
from milai_lab.datasets.memory_control_views import SourceObject, Span, literal_view
from milai_lab.memory.reader_projection import merge_source_ranges, subtract_source_ranges
from milai_lab.memory.retrieval import SourceSearchCache
from milai_lab.memory.service import MemoryService
from milai_lab.memory.source_materials import read_original_materials
from milai_lab.methods.control_numeric import (
    OPERATION_FIELDS,
    log_count,
    masked,
    material_units,
)
from milai_lab.methods.control_observation import control_input
from milai_lab.methods.corpus_navigation import delta_preview, excerpt, query_terms
from milai_lab.methods.dataset_reader import DatasetReader, PacketPlan
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
        self._delta_navigation: tuple[
            tuple[str, tuple[int, ...], Tokenizer], dict[int, dict[str, Any]]
        ] | None = None
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

        source_ranges = self.source_ranges(focus.ranges)
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
            expanded = self.source_ranges(detail.ranges)
            positions = [self.objects[oid].position for oid, _, _ in detail.ranges]
            descriptor.update(
                context_source_ranges=expanded,
                context_turn_range=[min(positions), max(positions) + 1],
            )
        return descriptor

    def source_ranges(self, spans: Sequence[Span]) -> list[dict[str, Any]]:
        return [
            {"source_ref": self.ref(oid), "source_revision": 1, "start": start, "end": end}
            for oid, start, end in spans
        ]

    def navigation_delta(
        self, query: str, focus: list[int], encoder: Tokenizer,
    ) -> tuple[dict[int, dict[str, Any]], dict[str, int | float]]:
        wall, cpu = time.perf_counter(), time.process_time()
        key = (query, tuple(focus), encoder)
        hit = self._delta_navigation is not None and self._delta_navigation[0] == key
        scanned = 0
        if hit:
            assert self._delta_navigation is not None
            result = self._delta_navigation[1]
        else:
            terms = query_terms(query)
            refs = {oid: self.ref(oid) for oid in self.objects}
            reverse = {ref: oid for oid, ref in refs.items()}
            result = {}
            for vid in focus:
                view = self.views[vid]
                expansion = None
                if view.context_id is not None:
                    additional = subtract_source_ranges(
                        self.source_ranges(self.views[view.context_id].ranges),
                        self.source_ranges(view.ranges),
                    )
                    expansion = [
                        (reverse[r["source_ref"]], r["start"], r["end"]) for r in additional
                    ]
                scanned += sum(end - start for _, start, end in [*view.ranges, *(expansion or [])])
                result[vid] = delta_preview(
                    terms, view.ranges, expansion, self.objects, refs, encoder, source_revision=1,
                )
            self._delta_navigation = key, result
        return result, {
            "navigation_wall_ms": (time.perf_counter() - wall) * 1000,
            "navigation_cpu_ms": (time.process_time() - cpu) * 1000,
            "navigation_cache_hit": int(hit),
            "navigation_scanned_chars": scanned,
            "navigation_prepared_tokens": sum(r["encoder_tokens"] for r in result.values()),
        }

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
        navigation_delta: dict[int, dict[str, Any]] | None = None,
        navigation_costs: dict[str, int | float] | None = None,
        numeric_observation: bool = False,
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
        self._preflight_material: dict[str, int | None] = {}
        self.shared_preflight = shared_preflight
        self.navigation_delta = navigation_delta
        self.navigation_costs = navigation_costs or {}
        self.numeric_observation = numeric_observation
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
            self._preflight_material[action.id] = (
                None if reason == "source_unavailable" else material_tokens
            )
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
        actions = self.ops.actions(state)
        if self.navigation_delta is not None:
            pending = set()
            for candidate in state.pending_candidates:
                index = candidate["item_index"]
                if self.focus[index] in self.navigation_delta:
                    candidate["navigation"] = self.navigation_delta[self.focus[index]]
                    pending.add(index)
            state.navigation_upgrades = {
                a.parameters["index"]: self.navigation_delta[self.focus[a.parameters["index"]]]
                for a in actions if a.kind == "READ" and a.parameters["index"] not in pending
            }
        return actions

    def actions(self, state: MemoryControlState) -> list[MemoryAction]:
        actions = self.feasible_menu(self.raw_actions(state))
        self.observe_numeric(actions)
        return actions

    def action_binding(self, action: MemoryAction) -> dict[str, Any]:
        """A replayable binding with the actual registered tier and source intervals."""
        vid = self.pool.bound_view(self.focus, action)
        return {**asdict(action), **(
            {"view_id": vid, "requested_span_role": (
                "context" if action.parameters.get("expand_context") else "focus"
            ), "source_ranges": self.pool.source_ranges(self.pool.views[vid].ranges)}
            if vid is not None else {}
        )}

    def proposed_material_cost(self, action: MemoryAction) -> dict[str, Any]:
        if action.kind == "READ":
            self.feasibility(action)
            tokens = self._preflight_material.get(action.id)
            if tokens is not None:
                return {
                    "cost_status": "exact",
                    "incremental_material_tokens": tokens - self.used_tokens,
                }
        if action.kind == "HANDOFF" and not action.parameters:
            return {"cost_status": "exact", "incremental_material_tokens": 0}
        return {"cost_status": "unknown", "incremental_material_tokens": None}

    @staticmethod
    def exposed_navigation_tokens(observation: dict[str, Any]) -> int:
        return sum(
            int(item.get("navigation", item.get("navigation_excerpt", {})).get("encoder_tokens", 0))
            for item in observation["pending_candidates"]
        ) + sum(
            int(item["encoder_tokens"])
            for item in observation.get("navigation_upgrades", {}).values()
        )

    def observe_numeric(self, actions: list[MemoryAction]) -> None:
        if not self.numeric_observation:
            return
        pool = self.pool
        delivered = merge_source_ranges([
            span for item in self.ops.opened.values() for span in item.get("source_ranges", [])
        ])
        by_action = {}

        def novelty(ranges: list[dict[str, Any]]) -> tuple[float | None, float | None]:
            width = sum(r["end"] - r["start"] for r in ranges)
            if not width:
                return None, None
            new = sum(r["end"] - r["start"] for r in subtract_source_ranges(ranges, delivered))
            return new / width, (width - new) / width

        for action in actions:
            features: list[float | None] = [float(action.kind == kind) for kind in OPERATION_FIELDS]
            if action.kind == "READ":
                focus = pool.views[self.focus[action.parameters["index"]]]
                context = pool.views[focus.context_id] if focus.context_id is not None else None
                expanded = bool(action.parameters.get("expand_context"))
                focus_ranges = merge_source_ranges(pool.source_ranges(focus.ranges))
                context_ranges = (
                    merge_source_ranges(pool.source_ranges(context.ranges)) if context else []
                )
                expansion = subtract_source_ranges(context_ranges, focus_ranges)
                self.feasibility(action)
                tokens = self._preflight_material.get(action.id)
                incremental = None if tokens is None else tokens - self.used_tokens
                features.extend((
                    float(not expanded), float(expanded), float(context is not None),
                    material_units(focus.reader_tokens),
                    material_units(context.reader_tokens if context else None),
                    log_count(len(focus_ranges)),
                    log_count(len(context_ranges) if context else None),
                    *novelty(context_ranges if expanded else focus_ranges), *novelty(expansion),
                    material_units(incremental), float(tokens is not None), 0.0,
                ))
            else:
                handoff = action.kind == "HANDOFF" and not action.parameters
                features.extend([None] * 11 + ([0.0, 1.0, 0.0] if handoff else [None, 0.0, 0.0]))
            by_action[action.id] = masked(features)
        self.state.control_numeric = {
            "schema": NUMERIC_SCHEMA,
            "state": masked((
                material_units(self.material_limit),
                material_units(self.material_limit - self.used_tokens),
                material_units(self.used_tokens),
                log_count(self.state.budget.get("successful_reads")),
                log_count(self.state.budget.get("remaining_control_steps")),
                log_count(len(actions)),
                log_count(len(self.opened)),
                float(self.host is not None),
            )),
            "actions": by_action,
        }

    def menu(self, steps: int) -> list[MemoryAction]:
        self.state.budget.update(
            remaining_control_steps=steps - len(self.prefix), reader_capacity_reserved=True
        )
        return self.raw_actions(self.state)

    def execute(self, action: MemoryAction, state: MemoryControlState) -> dict[str, Any]:
        self.trial_failure = None
        result = self.ops.execute(action, state)
        if state.action_history is not None:
            state.action_history.append(action.id)
        if self.host is None or result["ok"]:
            self.prefix.append(action.id)
        elif self.trial_failure:
            result["status"] = self.trial_failure
        self._feasibility.clear()
        self._preflight_material.clear()
        state.control_numeric = None
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
        self.observe_numeric(actions)
        return control_input(self.state, actions)
