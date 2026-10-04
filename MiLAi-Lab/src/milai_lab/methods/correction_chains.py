"""Query-free, span-bound public correction components and shared candidate expansion."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from milai_lab.contracts.correction_relation import (
    BoundSourceSpan,
    ChainGroup,
    EvidenceSpanCandidate,
    SourceRelation,
    candidate_identity,
    canonical,
    digest,
    text_sha256,
)
from milai_lab.methods.correction_evidence import render_material, source_unit


@dataclass(frozen=True)
class CompiledChains:
    groups: tuple[ChainGroup, ...]
    adjacency: dict[str, tuple[str, ...]]
    relation_members: dict[str, tuple[str, ...]]
    frozen_order: tuple[str, ...]


def compile_chains(
    relations: tuple[SourceRelation, ...], candidates: list[EvidenceSpanCandidate],
    sources: dict[str, dict[str, Any]], token_count: Callable[[str], int],
) -> CompiledChains:
    """Bind literal spans only: neither annotations nor quote matches verify revision truth.

    Shared Source identity does not create graph edges. An edge exists only between
    indexed spans actually touched by an explicitly supplied, verified-span annotation.
    """
    order = tuple(candidate_identity(c) for c in candidates)
    positions = {key: i for i, key in enumerate(order)}
    by_source: dict[str, list[EvidenceSpanCandidate]] = {}
    units = {}
    for candidate in candidates:
        by_source.setdefault(candidate.source_ref, []).append(candidate)
        value = sources[candidate.source_ref]["content"]
        body = value if type(value) is str else canonical(value)
        units[candidate.candidate_id] = source_unit(
            candidate.source_ref, candidate.role, candidate.observed_at,
            body[candidate.start:candidate.end], start=candidate.start,
            candidate_id=candidate.candidate_id)

    def members(span: BoundSourceSpan) -> set[str]:
        source = sources.get(span.source_ref)
        if source is None:
            raise ValueError("CORRECTION_RELATION_SOURCE_UNAVAILABLE_OR_AFTER_CUTOFF")
        body = source["content"] if type(source["content"]) is str else canonical(source["content"])
        if (source["content_sha256"] != span.source_sha256
                or text_sha256(body) != span.body_text_sha256 or span.end > len(body)
                or text_sha256(body[span.start:span.end]) != span.span_sha256):
            raise ValueError("CORRECTION_RELATION_SOURCE_SPAN_CHANGED")
        touched = [candidate for candidate in by_source.get(span.source_ref, [])
                   if candidate.start < span.end and candidate.end > span.start]
        intervals = sorted((max(c.start, span.start), min(c.end, span.end)) for c in touched)
        cursor = span.start
        for start, end in intervals:
            if start != cursor:
                raise ValueError("CORRECTION_RELATION_SPAN_NOT_FULLY_INDEXED")
            cursor = end
        if cursor != span.end:
            raise ValueError("CORRECTION_RELATION_SPAN_NOT_FULLY_INDEXED")
        return {candidate.candidate_id for candidate in touched}

    adjacency: dict[str, set[str]] = {key: set() for key in order}
    relation_members = {}
    for relation in relations:
        if relation.relation_id in relation_members:
            raise ValueError("CORRECTION_DUPLICATE_RELATION")
        linked = set().union(*(members(span) for group in (
            relation.predecessor_spans, relation.successor_spans, relation.witness_spans)
            for span in group))
        relation_members[relation.relation_id] = tuple(sorted(linked, key=positions.__getitem__))
        for key in linked:
            adjacency[key].update(linked - {key})
    groups = []
    visited: set[str] = set()
    for key in order:
        if key in visited:
            continue
        component, pending = {key}, [key]
        while pending:
            for member in adjacency[pending.pop()] - component:
                component.add(member)
                pending.append(member)
        visited.update(component)
        ids = tuple(sorted(component, key=positions.__getitem__))
        relation_ids = tuple(rid for rid, values in relation_members.items()
                             if component.intersection(values))
        groups.append(ChainGroup("group-" + digest([ids, relation_ids]), ids, relation_ids,
                                 token_count(render_material([units[member] for member in ids]))))
    return CompiledChains(tuple(groups), {
        key: tuple(sorted(values, key=positions.__getitem__)) for key, values in adjacency.items()
    }, relation_members, order)


def expand_candidate_pool(
    chains: CompiledChains, ordinary_ranking: list[str], limit: int,
) -> tuple[list[str], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Seed-first full closure if it fits; explicit deterministic truncation at shared K.

    No fixed seed/expansion quota. Distances use actual supplied relation edges;
    stable ties never contribute semantic relevance or imply temporal validity.
    """
    positions = {key: i for i, key in enumerate(chains.frozen_order)}
    ranks = {key: i for i, key in enumerate(ordinary_ranking)}
    pool: list[str] = []
    seeds = []
    for seed in ordinary_ranking:
        if len(pool) >= limit:
            break
        if seed in pool:
            continue
        seeds.append(seed)
        distance = {seed: 0}
        pending = deque([seed])
        while pending:
            key = pending.popleft()
            for member in chains.adjacency[key]:
                if member not in distance:
                    distance[member] = distance[key] + 1
                    pending.append(member)
        closure = sorted(distance, key=lambda key: (
            distance[key], ranks.get(key, len(ranks)), positions[key]))
        pool.extend(key for key in closure if key not in pool)
        del pool[limit:]
    pool_set = set(pool)
    relevant = {key for group in chains.groups if set(group.candidate_ids).intersection(ranks)
                for key in group.candidate_ids}
    omitted = tuple(key for key in chains.frozen_order if key in relevant and key not in pool_set)
    unclosed = tuple(rid for rid, ids in chains.relation_members.items()
                     if pool_set.intersection(ids) and not set(ids) <= pool_set)
    return pool, tuple(seeds), omitted, unclosed
