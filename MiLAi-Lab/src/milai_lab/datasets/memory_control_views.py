"""Build literal, paged Reader views and measure both configured tokenizers."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.datasets.memory_control_store import body_text, packed, set_meta

BREAKS = re.compile(r"\n+|[.!?。\uff01\uff1f](?:\s+|$)")
SPACE = re.compile(r"\s+")

Span = tuple[int, int, int]


@dataclass(frozen=True)
class SourceObject:
    id: int
    position: int
    kind: str
    role: str
    preview: str
    body: str
    block: int | None


@dataclass
class ViewDraft:
    object_id: int
    tier: str
    page: int
    method: str
    ranges: list[Span]
    literal: str
    reader_tokens: int
    context: int | None = None
    equivalence: str | None = None


def tokenize_path(path: str) -> Tokenizer:
    tokenizer = Tokenizer.from_file(str(Path(path) / "tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def resolve_tokenizers(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    section = config["views"]
    reader_config = json.loads(Path(section["reader_config"]).read_text())
    reader = reader_config["entrypoints"]["functional"]["capacity"]
    encoder = json.loads(Path(section["encoder_config"]).read_text())
    return reader, encoder


def literal_view(ranges: list[Span], objects: dict[int, SourceObject]) -> str:
    return "\n".join(objects[oid].body[start:end] for oid, start, end in ranges)


def pages(body: str, tokenizer: Tokenizer, limit: int) -> list[tuple[int, int, int]]:
    """Prefer complete sentence/line boundaries and retain exact character coverage."""
    result = []
    start = 0
    while start < len(body):
        tail = body[start:]
        encoded = tokenizer.encode(tail, add_special_tokens=False)
        if len(encoded.ids) <= limit:
            result.append((start, len(body), len(encoded.ids)))
            break
        boundary = encoded.offsets[limit][0]
        breaks = [m.end() for m in BREAKS.finditer(tail[:boundary]) if m.end() > boundary // 2]
        if not breaks:
            breaks = [m.end() for m in SPACE.finditer(tail[:boundary]) if m.end() > 0]
        length = breaks[-1] if breaks else boundary
        length = max(1, length)
        cost = len(tokenizer.encode(tail[:length], add_special_tokens=False).ids)
        while cost > limit and length > 1:
            length -= 1
            cost = len(tokenizer.encode(tail[:length], add_special_tokens=False).ids)
        if cost > limit:
            raise ValueError("A single original character exceeds the page budget")
        result.append((start, start + length, cost))
        start += length
    return result


def joined_ranges(parts: list[Span]) -> list[Span]:
    result: list[Span] = []
    for oid, start, end in parts:
        if result and result[-1][0] == oid and result[-1][2] == start:
            result[-1] = (oid, result[-1][1], end)
        else:
            result.append((oid, start, end))
    return result


def insert_views(
    db: sqlite3.Connection,
    rows: list[sqlite3.Row],
    reader: Tokenizer,
    encoder: Tokenizer,
    views: dict[str, Any],
) -> None:
    objects_by_root: dict[int, dict[int, SourceObject]] = defaultdict(dict)
    for row in rows:
        item = SourceObject(
            row["id"],
            row["position"],
            row["kind"],
            row["role"],
            row["preview"],
            body_text(row["body"]),
            row["block"],
        )
        objects_by_root[row["root_id"]][item.id] = item
    objects = [obj for root in objects_by_root.values() for obj in root.values()]
    bodies = [obj for obj in objects if obj.body.strip()]
    sizes = {
        obj.id: len(enc.ids)
        for obj, enc in zip(
            bodies,
            reader.encode_batch([obj.body for obj in bodies], add_special_tokens=False),
            strict=True,
        )
    }
    drafts: list[ViewDraft] = []
    material_limit = views["native_focus_reader_tokens"]
    page_limit = views["page_reader_tokens"]
    for root_id, local in objects_by_root.items():
        extended_by_block: dict[int, list[int]] = defaultdict(list)
        block_objects = {o.block: o.id for o in local.values() if o.kind == "message_block"}
        for obj in local.values():
            if obj.preview:
                drafts.append(
                    ViewDraft(obj.id, "preview", 0, "source_navigation", [], obj.preview, -1)
                )
            if obj.id not in sizes:
                continue
            n_tokens = sizes[obj.id]
            if n_tokens <= page_limit:
                cuts = [(0, len(obj.body), n_tokens)]
            else:
                cuts = pages(obj.body, reader, page_limit)
            for page, (start, end, count) in enumerate(cuts):
                focus = ViewDraft(
                    obj.id,
                    "R2",
                    page,
                    "literal_page" if len(cuts) > 1 else "complete_source_object",
                    [(obj.id, start, end)],
                    obj.body[start:end],
                    count,
                    equivalence="no_native_context"
                    if obj.block is None
                    else "same_material_within_page_budget",
                )
                if obj.block is not None:
                    extended_by_block[obj.block].append(len(drafts))
                drafts.append(focus)
        page_numbers: dict[int, int] = defaultdict(int)
        for block, indexes in extended_by_block.items():
            page_start = 0
            while page_start < len(indexes):
                page_end = page_start + 1
                estimate = drafts[indexes[page_start]].reader_tokens
                while (
                    page_end < len(indexes)
                    and estimate + drafts[indexes[page_end]].reader_tokens + 1 <= material_limit
                ):
                    estimate += drafts[indexes[page_end]].reader_tokens + 1
                    page_end += 1
                selected = indexes[page_start:page_end]
                if len(selected) > 1:
                    ranges = joined_ranges([part for i in selected for part in drafts[i].ranges])
                    text = literal_view(ranges, local)
                    tokens = len(reader.encode(text, add_special_tokens=False).ids)
                    if tokens <= material_limit:
                        anchor = block_objects.get(block, drafts[selected[0]].object_id)
                        page_number = page_numbers[anchor]
                        page_numbers[anchor] += 1
                        context_id = len(drafts)
                        drafts.append(
                            ViewDraft(
                                anchor,
                                "R3",
                                page_number,
                                "dialogue_block_page" if block in block_objects else "section_page",
                                ranges,
                                text,
                                tokens,
                            )
                        )
                        for i in selected:
                            focus = drafts[i]
                            if focus.literal != text:
                                focus.context = context_id
                                focus.equivalence = None
                page_start = page_end
        if block_objects:
            dialogue = "\n".join(o.body for o in local.values() if o.kind == "message")
            lens = [
                len(t.encode(dialogue, add_special_tokens=False).ids) for t in (reader, encoder)
            ]
            db.execute("INSERT INTO root_dialogue_costs VALUES (?,?,?)", (root_id, *lens))
    previews = [x for x in drafts if x.reader_tokens < 0]
    for draft, enc in zip(
        previews,
        reader.encode_batch([x.literal for x in previews], add_special_tokens=False),
        strict=True,
    ):
        draft.reader_tokens = len(enc.ids)
    first_id = db.execute("SELECT coalesce(max(id),0)+1 FROM views").fetchone()[0]
    encoder_counts = [
        len(enc.ids)
        for enc in encoder.encode_batch([x.literal for x in drafts], add_special_tokens=False)
    ]
    db.executemany(
        "INSERT INTO views VALUES (?,?,?,?,?,?,?,?)",
        (
            (
                first_id + i,
                x.object_id,
                x.tier,
                x.page,
                x.method,
                packed(x.ranges),
                x.reader_tokens,
                len_encoder,
            )
            for i, (x, len_encoder) in enumerate(zip(drafts, encoder_counts, strict=True))
        ),
    )
    db.executemany(
        "INSERT INTO candidates VALUES (?,?,?)",
        (
            (first_id + i, first_id + x.context if x.context is not None else None, x.equivalence)
            for i, x in enumerate(drafts)
            if x.tier == "R2"
        ),
    )


def build_views(db: sqlite3.Connection, config: dict[str, Any]) -> None:
    started = time.perf_counter()
    reader_cfg, encoder_cfg = resolve_tokenizers(config)
    reader = tokenize_path(reader_cfg["tokenizer_path"])
    encoder = tokenize_path(encoder_cfg["backbone"])
    db.execute(
        "CREATE TABLE IF NOT EXISTS root_dialogue_costs ("
        "root_id INTEGER PRIMARY KEY REFERENCES roots(id), "
        "reader_tokens INTEGER NOT NULL, encoder_tokens INTEGER NOT NULL)"
    )
    db.commit()
    while roots := db.execute(
        "SELECT id FROM roots WHERE views_built=0 ORDER BY id LIMIT 64"
    ).fetchall():
        ids = [row["id"] for row in roots]
        objects = db.execute(
            "SELECT * FROM objects WHERE root_id BETWEEN ? AND ? ORDER BY root_id,position",
            (ids[0], ids[-1]),
        ).fetchall()
        # All roots in the chunk are committed with their view/task relations.
        wanted = set(ids)
        insert_views(
            db,
            [row for row in objects if row["root_id"] in wanted],
            reader,
            encoder,
            config["views"],
        )
        db.executemany("UPDATE roots SET views_built=1 WHERE id=?", ((i,) for i in ids))
        db.commit()
        if ids[-1] % 4096 < 64:
            print(f"Views built through root {ids[-1]}", flush=True)
    set_meta(
        db,
        "tokenizers",
        {
            "reader": {
                "model": reader_cfg["model"],
                "path": reader_cfg["tokenizer_path"],
                "config": config["views"]["reader_config"],
            },
            "encoder": {
                "model": config["views"]["encoder_model"],
                "path": encoder_cfg["backbone"],
                "config": config["views"]["encoder_config"],
                "chunk_tokens": encoder_cfg["chunk_tokens"],
                "maximum_memory_objects": encoder_cfg["maximum_memory_objects"],
            },
            "literal_views": "Newline-joined original body slices, no special tokens",
            "preview": "Recorded navigation text, no special tokens",
            "state_material": "Full controlled_reader_packet JSON with budget reason and wrappers",
        },
    )
    set_meta(db, "view_build_seconds", time.perf_counter() - started)
    db.commit()
