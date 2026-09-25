"""Shared source-range BM25/vector ranking and session adjacency."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from milai_lab.methods.reasoning_bank import normalized

if TYPE_CHECKING:
    from milai_lab.methods.contextual_user_memory import ContextualMemory

SOURCE_RANGE_CHARS = 2048
SOURCE_RANGE_STEP = 1792
_TERMS = re.compile(r"[^\W_]+", re.UNICODE)
_HAN = re.compile(r"([\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]+)")


@dataclass(frozen=True)
class IndexEntry:
    key: str
    ref: str
    text: str
    span: tuple[int, int] | None = None


@dataclass
class Ranked:
    refs: list[str] = field(default_factory=list)
    spans: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    date_pending: set[str] = field(default_factory=set)


def tokenize(value: str) -> list[str]:
    # Space-free Han sentences cannot be a single lexical term: a shorter query
    # would never match. Characters support one-character queries, adjacent pairs
    # reward phrase overlap without a language model or dictionary dependency.
    terms: list[str] = []
    for part in _HAN.split(value.casefold()):
        if _HAN.fullmatch(part):
            terms.extend(part)
            terms.extend(part[index:index + 2] for index in range(len(part) - 1))
        else:
            terms.extend(_TERMS.findall(part))
    return terms


def merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge only overlapping or touching ranges; never invent an intervening excerpt."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(set(spans)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _date_bounds(date_from: str, date_to: str) -> tuple[date | None, date | None]:
    try:
        lower = date.fromisoformat(date_from) if date_from else None
        upper = date.fromisoformat(date_to) if date_to else None
    except ValueError as error:
        raise ValueError("INVALID_EVENT_DATE_FILTER") from error
    if lower and upper and lower > upper:
        raise ValueError("INVALID_EVENT_DATE_FILTER")
    return lower, upper


def _date_match(value: str, lower: date | None, upper: date | None) -> str:
    if lower is None and upper is None:
        return "MATCH"
    if not value:
        return "PENDING"
    try:
        observed = date.fromisoformat(value[:10])
    except ValueError:
        return "PENDING"
    return (
        "MATCH" if (lower is None or observed >= lower) and (upper is None or observed <= upper)
        else "OUTSIDE"
    )


def date_status(
    memory: ContextualMemory, ref: str, date_from: str = "", date_to: str = "",
) -> str:
    lower, upper = _date_bounds(date_from, date_to)
    if ref in memory.sources:
        return _date_match(memory.sources[ref].date, lower, upper)
    if ref in memory.history:
        source_refs = memory.history[ref]["source_refs"]
    else:
        source_refs = memory.workspace.cards[memory._handle(ref)].source_refs
    if not source_refs:
        return "PENDING" if lower or upper else "MATCH"
    statuses = [
        _date_match(memory.sources[source].date, lower, upper)
        for source in source_refs if source in memory.sources
    ]
    if "MATCH" in statuses:
        return "MATCH"
    return "PENDING" if "PENDING" in statuses or not statuses else "OUTSIDE"


def index_entries(
    memory: ContextualMemory, *, sources: bool = True, records: bool = True,
    valid_at: str = "", known_at: str = "", date_from: str = "", date_to: str = "",
    session_id: str = "",
) -> tuple[list[IndexEntry], set[str]]:
    _date_bounds(date_from, date_to)
    entries: list[IndexEntry] = []
    uncertain: set[str] = set()
    if sources:
        ordered = sorted(memory.sources, key=lambda ref: (memory.source_sequence[ref], ref))
        for ref in ordered:
            source = memory.sources[ref]
            if session_id and source.session_id != session_id:
                continue
            if known_at and memory.source_known_at[ref] > known_at:
                continue
            if memory.resolve_at(ref, known_at) != ref:
                continue
            status = date_status(memory, ref, date_from, date_to)
            if status == "OUTSIDE":
                continue
            if status == "PENDING":
                uncertain.add(ref)
            body = source.content
            if len(body) <= SOURCE_RANGE_CHARS:
                entries.append(IndexEntry(ref, ref, memory._text(ref)))
            else:
                for start in range(0, len(body), SOURCE_RANGE_STEP):
                    end = min(start + SOURCE_RANGE_CHARS, len(body))
                    entries.append(IndexEntry(
                        f"{ref}#{start}:{end}", ref, body[start:end], (start, end),
                    ))
    if records:
        for card in sorted(memory.workspace.cards.values(), key=lambda item: item.handle):
            try:
                ref = memory.resolve_at(memory._ref(card), known_at)
            except ValueError:
                continue
            if (memory.claim_applicability(
                ref, valid_at=valid_at, known_at=known_at,
            ) == "UNUSABLE"):
                continue
            if session_id:
                source_refs = (
                    memory.history[ref]["source_refs"] if ref in memory.history
                    else card.source_refs
                )
                if not any(
                    source in memory.sources and memory.sources[source].session_id == session_id
                    for source in source_refs
                ):
                    continue
            status = date_status(memory, ref, date_from, date_to)
            if status == "OUTSIDE":
                continue
            if status == "PENDING":
                uncertain.add(ref)
            entries.append(IndexEntry(ref, ref, memory._text(ref)))
    return entries, uncertain


def _bm25_scores(entries: list[IndexEntry], query: str) -> list[float]:
    """Robertson BM25 with ReFind's k1/b/idf form and Unicode tokenization."""
    terms = list(dict.fromkeys(tokenize(query)))
    documents = [Counter(tokenize(entry.text)) for entry in entries]
    lengths = [sum(counts.values()) for counts in documents]
    average = sum(lengths) / len(lengths) if lengths else 0.0
    frequencies = Counter(term for counts in documents for term in counts)
    count = len(entries)
    scores: list[float] = []
    for counts, length in zip(documents, lengths, strict=True):
        total = 0.0
        for term in terms:
            frequency = counts.get(term, 0)
            if not frequency or not average:
                continue
            df = frequencies[term]
            inverse = math.log((count - df + 0.5) / (df + 0.5) + 1.0)
            total += inverse * (frequency * 2.2) / (
                frequency + 1.2 * (0.25 + 0.75 * length / average)
            )
        scores.append(total)
    return scores


def rank(
    memory: ContextualMemory, query: str, *, sources: bool = True,
    records: bool = True, valid_at: str = "", known_at: str = "",
    date_from: str = "", date_to: str = "", session_id: str = "",
    max_spans: int = 4,
) -> Ranked:
    entries, uncertain = index_entries(
        memory, sources=sources, records=records, valid_at=valid_at,
        known_at=known_at, date_from=date_from, date_to=date_to,
        session_id=session_id,
    )
    if not entries:
        return Ranked(date_pending=uncertain)
    pending = [entry for entry in entries if entry.key not in memory.vectors]
    if pending:
        embedded = memory.embed([entry.text for entry in pending])
        for entry, vector in zip(pending, embedded, strict=True):
            memory.vectors[entry.key] = normalized(vector, memory.embedding_dimension)
    query_vector = normalized(memory.embed([query])[0], memory.embedding_dimension)
    vector_order = sorted(
        range(len(entries)),
        key=lambda index: (
            -sum(a * b for a, b in zip(
                query_vector, memory.vectors[entries[index].key], strict=True,
            )), index,
        ),
    )
    bm25 = _bm25_scores(entries, query)
    lexical_order = sorted(
        (index for index, score in enumerate(bm25) if score > 0),
        key=lambda index: (-bm25[index], index),
    )
    scores: dict[str, float] = {}
    vector_positions: dict[str, int] = {}
    for route, order in enumerate((vector_order, lexical_order)):
        seen: set[str] = set()
        for index in order:
            ref = entries[index].ref
            if ref in seen:
                continue
            seen.add(ref)
            position = len(seen)
            scores[ref] = scores.get(ref, 0.0) + 1.0 / (60 + position)
            if route == 0:
                vector_positions[ref] = position
    spans: dict[str, list[tuple[int, int]]] = {}
    for index in lexical_order:
        entry = entries[index]
        if entry.span is not None:
            selected = spans.setdefault(entry.ref, [])
            if len(selected) < max_spans:
                selected.append(entry.span)
    for index in vector_order:
        entry = entries[index]
        if entry.span is not None and entry.ref not in spans:
            spans[entry.ref] = [entry.span]
    return Ranked(
        refs=sorted(scores, key=lambda ref: (-scores[ref], vector_positions[ref], ref)),
        spans={ref: merge_spans(values) for ref, values in spans.items()},
        date_pending=uncertain,
    )


def adjacent_sources(
    memory: ContextualMemory, ref: str, *, window: int = 1,
    known_at: str = "", date_from: str = "", date_to: str = "",
) -> list[str]:
    if ref not in memory.sources or window < 1:
        return []
    anchor = memory.sources[ref]
    if not anchor.session_id:
        return []
    session = sorted(
        (
            candidate for candidate, source in memory.sources.items()
            if source.session_id == anchor.session_id and source.artifact == anchor.artifact
            and (not known_at or memory.source_known_at[candidate] <= known_at)
            and date_status(memory, candidate, date_from, date_to) != "OUTSIDE"
        ),
        key=lambda candidate: memory.source_sequence[candidate],
    )
    if ref not in session:
        return []
    position = session.index(ref)
    return session[max(0, position - window):position] + session[
        position + 1:position + window + 1
    ]
