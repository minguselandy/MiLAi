"""Accurate source pages and bounded correction-aware material packets."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from .retrieval import adjacent_sources

if TYPE_CHECKING:
    from milai_lab.methods.contextual_user_memory import ContextualMemory


def _page(body: str, start: int, end: int) -> dict[str, Any]:
    return {
        "start": start, "end": end, "total_chars": len(body),
        "complete": start == 0 and end == len(body),
        "content_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def base_material(
    memory: ContextualMemory, ref: str, spans: list[tuple[int, int]] | None = None,
    *, valid_at: str = "", known_at: str = "", date_pending: bool = False,
) -> dict[str, Any]:
    item = memory._view(ref, False, valid_at=valid_at, known_at=known_at)
    if ref in memory.sources:
        item["source_sequence"] = memory.source_sequence[ref]
    field = "content" if ref in memory.sources else "text"
    body = item[field]
    if ref in memory.sources and spans:
        excerpts = [
            {"content": body[start:end], "page": _page(body, start, end)}
            for start, end in spans
        ]
        if len(excerpts) > 1:
            item.pop("content")
            item["excerpts"] = excerpts
        else:
            item["content"] = excerpts[0]["content"]
            item["page"] = excerpts[0]["page"]
    else:
        item["page"] = _page(body, 0, len(body))
    if date_pending:
        item["event_date_match"] = "PENDING"
    return item


def _view_ref(memory: ContextualMemory, ref: str, known_at: str) -> str | None:
    try:
        return memory.resolve_at(ref, known_at)
    except (KeyError, ValueError):
        return None


def _source_relations(
    memory: ContextualMemory, ref: str, known_at: str,
) -> list[tuple[str, str, int]]:
    relations: list[tuple[str, str, int]] = []
    current = _view_ref(memory, ref, known_at)
    if current and current != ref:
        relations.append((current, "source_replacement", 0))
    for old in memory.source_replacements:
        if _view_ref(memory, old, known_at) == ref and old != ref:
            relations.append((old, "source_predecessor", 2))
    # Ordinary revisions have only provenance; exact historical cards preserve it.
    for old, prior in memory.history.items():
        if (known_at and prior["known_at"] > known_at) or ref not in prior["source_refs"]:
            continue
        target = _view_ref(memory, old, known_at)
        if target and target != old:
            relations.append((target, "revised_interpretation", 0))
    # H1/H4 references are exact source versions in the direct reverse index.
    for key in sorted(memory.revisions.by_source.get(ref, set())):
        group = memory.revisions.groups[key]
        if known_at and group.known_at > known_at:
            continue
        target = _view_ref(memory, group.target_ref, known_at)
        if target and target == group.target_ref:
            relations.append((target, "supported_interpretation", 1))
    return relations


def _direct_interpretations(
    memory: ContextualMemory, source_ref: str, known_at: str,
) -> list[tuple[str, str, int]]:
    """Current-at-cutoff interpretations that directly cite this exact source."""
    direct = []
    for handle in sorted(memory.workspace.cards):
        card = memory.workspace.cards[handle]
        target = _view_ref(memory, memory._ref(card), known_at)
        if target is None:
            continue
        source_refs = (
            memory.history[target]["source_refs"] if target in memory.history
            else card.source_refs
        )
        if source_ref in source_refs:
            direct.append((target, "direct_interpretation", 0))
    return direct


def _claim_relations(
    memory: ContextualMemory, ref: str, known_at: str,
) -> list[tuple[str, str, int]]:
    relations: list[tuple[str, str, int]] = []
    current = _view_ref(memory, ref, known_at)
    if current and current != ref:
        relations.append((current, "current_interpretation", 0))
    elif current == ref:
        versions = [
            old for old in memory.history
            if memory._handle(old) == memory._handle(ref)
            and (not known_at or memory.history[old]["known_at"] <= known_at)
        ]
        if versions:
            previous = max(versions, key=lambda value: int(value.rsplit("@", 1)[1]))
            relations.append((previous, "prior_interpretation", 1))
    item = memory._view(ref, False, known_at=known_at)
    for source in item["source_refs"]:
        current_source = _view_ref(memory, source, known_at)
        if current_source:
            relations.append((source, "source_provenance", 2))
            if current_source != source:
                relations.append((current_source, "source_replacement", 0))
    for key in sorted(memory.revisions.by_target.get(ref, set())):
        group = memory.revisions.groups[key]
        if known_at and group.known_at > known_at:
            continue
        for support in group.items:
            source = _view_ref(memory, support.ref, known_at)
            if source:
                relations.append((support.ref, "declared_support", 2))
                if source != support.ref:
                    relations.append((source, "support_replacement", 0))
    return relations


def associated_refs(
    memory: ContextualMemory, ref: str, *, known_at: str = "",
    neighbor_window: int = 0, date_from: str = "", date_to: str = "",
) -> list[tuple[str, str, int]]:
    candidates = (
        _source_relations(memory, ref, known_at) if ref in memory.sources
        else _claim_relations(memory, ref, known_at)
    )
    if ref in memory.sources and neighbor_window:
        for adjacent in adjacent_sources(
            memory, ref, window=neighbor_window, known_at=known_at,
            date_from=date_from, date_to=date_to,
        ):
            relation = (
                "session_previous" if memory.source_sequence[adjacent] < memory.source_sequence[ref]
                else "session_next"
            )
            candidates.append((adjacent, relation, 3))
            for correction, _, priority in _source_relations(memory, adjacent, known_at):
                if priority <= 1:
                    candidates.append((correction, "session_neighbor_correction", 1))
    found: set[str] = {ref}
    ordered: list[tuple[str, str, int]] = []
    for candidate, relation, priority in sorted(candidates, key=lambda value: (value[2], value[0])):
        if candidate not in found:
            found.add(candidate)
            ordered.append((candidate, relation, priority))
    return ordered


def _bytes(item: dict[str, Any]) -> int:
    return len(json.dumps(item, ensure_ascii=False).encode())


def _fits_associated(
    packet: dict[str, Any], associated: dict[str, Any], max_bytes: int,
) -> bool:
    return _bytes({
        **packet,
        "associated_materials": [*packet["associated_materials"], associated],
    }) <= max_bytes


def _compact_body(item: dict[str, Any], max_chars: int) -> dict[str, Any]:
    copy = dict(item)
    excerpts = copy.pop("excerpts", None)
    if excerpts:
        first = excerpts[0]
        copy["content"] = first["content"]
        copy["page"] = first["page"]
        copy["unexpanded_ranges"] = [
            {"start": entry["page"]["start"], "end": entry["page"]["end"]}
            for entry in excerpts[1:]
        ]
    key = "content" if copy["kind"] == "source" else "text"
    body = copy[key]
    if len(body) > max_chars:
        copy[key] = body[:max_chars]
        page = copy["page"]
        copy["page"] = {
            **page, "end": page["start"] + max_chars, "complete": False,
        }
        copy["requires_expansion"] = True
    if excerpts:
        copy["requires_expansion"] = True
    if max_chars == 0:
        copy["requires_expansion"] = True
    return copy


def _fit_base(packet: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    if _bytes(packet) <= max_bytes:
        return packet
    if packet.get("sources"):
        packet = dict(packet)
        packet["unexpanded_sources"] = list(dict.fromkeys(
            [*packet.get("unexpanded_sources", []),
             *(source["ref"] for source in packet["sources"])]
        ))
        packet.pop("sources")
        if _bytes(packet) <= max_bytes:
            return packet
    for chars in (1024, 256, 0):
        compact = _compact_body(packet, chars)
        if _bytes(compact) <= max_bytes:
            return compact
    minimum = {
        "ref": packet["ref"], "kind": packet["kind"], "requires_expansion": True,
        "associated_materials": [],
        "unexpanded_associated_refs": packet.get("unexpanded_associated_refs", []),
        "required_associated_refs": list(dict.fromkeys([
            *packet.get("required_associated_refs", []),
            *(item["ref"] for item in packet.get("associated_materials", [])),
        ])),
    }
    return minimum if _bytes(minimum) <= max_bytes else {
        "ref": packet["ref"], "requires_expansion": True,
    }


def linked_packet(
    memory: ContextualMemory, ref: str, *,
    spans: list[tuple[int, int]] | None = None, valid_at: str = "",
    known_at: str = "", max_bytes: int = 16000,
    date_pending: bool = False, neighbor_window: int = 0,
    date_from: str = "", date_to: str = "",
    base_override: dict[str, Any] | None = None,
    correction_only: bool = False,
) -> dict[str, Any]:
    """Keep direct correction/limits with the base; defer excess expansion explicitly."""
    base = base_override or base_material(
        memory, ref, spans, valid_at=valid_at, known_at=known_at,
        date_pending=date_pending,
    )
    candidates = associated_refs(
        memory, ref, known_at=known_at,
        neighbor_window=0 if correction_only else neighbor_window,
        date_from=date_from, date_to=date_to,
    )
    if correction_only:
        candidates = [item for item in candidates if item[1] in {
            "source_replacement", "revised_interpretation",
        }]
        included = {candidate for candidate, _, _ in candidates}
        for item in _direct_interpretations(memory, ref, known_at):
            if item[0] not in included:
                candidates.append(item)
                included.add(item[0])
        if not candidates:
            return base
    packet = {**base, "associated_materials": [], "unexpanded_associated_refs": [],
              "required_associated_refs": []}
    if not candidates:
        return _fit_base(packet, max_bytes)
    for candidate, relation, priority in candidates:
        associated = base_material(memory, candidate, valid_at=valid_at, known_at=known_at)
        associated["relation"] = relation
        if priority <= 1 and not _fits_associated(packet, associated, max_bytes):
            packet = _compact_body(packet, 256)
            if not _fits_associated(packet, associated, max_bytes):
                packet = _compact_body(packet, 0)
        if _fits_associated(packet, associated, max_bytes):
            packet["associated_materials"].append(associated)
            continue
        packet["unexpanded_associated_refs"].append(candidate)
        if priority <= 1:
            packet["required_associated_refs"].append(candidate)
            packet = _compact_body(packet, 0)
    return _fit_base(packet, max_bytes)
