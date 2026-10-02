"""Frozen research adapter over existing MemoryService, without query capture or mutation."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, replace
from typing import Any

from milai_lab.contracts.correction_relation import (
    EvidenceCandidate,
    QueryView,
    ResearchSnapshot,
    canonical,
    check_sha,
    digest,
    instant,
    text_sha256,
)
from milai_lab.memory.service import MemoryService
from milai_lab.methods.contextual_memory.retrieval import IndexEntry, _bm25_scores
from milai_lab.methods.correction_evidence import source_unit


class FrozenBankReader:
    """Trusted I/O boundary. Selector and Reader receive no reference to this object.

    Integrity scans read complete Store DTOs but perform no semantic classification.
    Their logical I/O is reported separately from index and selected evidence reads.
    Candidate issuance is allowed auxiliary state; all fact/source namespaces freeze.
    """

    def __init__(
        self, service: MemoryService, *, cutoff: str, config_sha256: str,
        token_count: Callable[[str], int], tokenizer_identity: dict[str, Any],
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if (service.mutation_contract != "event_bound_v1"
                or service.candidate_contract != "read_handle_v1"):
            raise ValueError("CORRECTION_BOUND_SOURCE_HANDLES_REQUIRED")
        instant(cutoff)
        check_sha(config_sha256)
        if not tokenizer_identity:
            raise ValueError("CORRECTION_TOKENIZER_IDENTITY_REQUIRED")
        self.service = service
        self.cutoff = cutoff
        self.config_sha256 = config_sha256
        self.token_count = token_count
        self.tokenizer_sha256 = digest(tokenizer_identity)
        self.emit = emit or (lambda event: None)
        self._entries: list[IndexEntry] = []
        self._candidates: dict[str, EvidenceCandidate] = {}
        self._handles: dict[str, list[dict[str, Any]]] = {}
        self._issued: dict[str, ResearchSnapshot] = {}
        self.bank_sha256: str | None = None
        self.index_sha256: str | None = None

    def _fact_state(self, phase: str) -> tuple[str, list[dict[str, Any]]]:
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        namespaces = (
            self.service.namespace, self.service.sources_namespace,
            self.service.observations_namespace, self.service.projections_namespace,
            self.service.backlinks_namespace,
        )
        rows: list[dict[str, Any]] = []
        calls, logical_bytes = 0, 0
        # Public Store search has prefix semantics: retain only exact fact namespaces.
        for namespace in namespaces:
            offset = 0
            while True:
                page = self.service.store.search(namespace, limit=100, offset=offset)
                calls += 1
                logical_bytes += sum(len(canonical(item.value).encode()) for item in page)
                rows.extend({"namespace": list(item.namespace), "id": item.key,
                             "value": item.value} for item in page if item.namespace == namespace)
                if len(page) < 100:
                    break
                offset += len(page)
        rows.sort(key=lambda row: (row["namespace"], row["id"]))
        result = digest(rows)
        self.emit({"event": "correction_bank_integrity_scan", "phase": phase,
                   "bank_sha256": result, "store_search_calls": calls,
                   "logical_bytes": logical_bytes, "wall_ns": time.perf_counter_ns() - wall,
                   "cpu_ns": time.process_time_ns() - cpu,
                   "physical_io_bytes": None, "semantic_classification": False})
        return result, rows

    def _public_read(self, method: str, *arguments: Any) -> Any:
        """Count all synchronous exact Store gets inside a public source/version guard."""
        store = self.service.store
        original = store.get
        calls, logical_bytes = 0, 0
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()

        def measured(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls, logical_bytes
            calls += 1
            value = original(*args, **kwargs)
            if value is not None:
                logical_bytes += len(canonical(value.value).encode())
            return value

        # Root executes this entry serially. Restore even on an integrity or SDK error.
        store.get = measured  # type: ignore[method-assign]
        try:
            return getattr(self.service, method)(*arguments)
        finally:
            store.get = original  # type: ignore[method-assign]
            self.emit({"event": "correction_store_reads", "public_method": method,
                       "calls": calls, "logical_bytes": logical_bytes,
                       "wall_ns": time.perf_counter_ns() - wall,
                       "cpu_ns": time.process_time_ns() - cpu,
                       "physical_io_bytes": None,
                       "timing_scope": "nested inside index/selected-read timings; not additive"})

    def _validate_source(self, ref: str, source: dict[str, Any]) -> None:
        role, origin = source.get("role"), source.get("origin")
        if (source.get("event_id") != ref or source.get("owner") != self.service.owner
                or type(source.get("session")) is not str or not source["session"]
                or role not in {"user", "assistant", "tool"}
                or type(origin) is not str or not origin
                or (role == "user" and origin != "public_user_message")
                or (role == "assistant" and origin != "public_assistant_message")
                or (role == "tool" and origin in {
                    "public_user_message", "public_assistant_message"})):
            raise ValueError("CORRECTION_SOURCE_IDENTITY_INVALID")
        object_ref = source.get("object_ref")
        if object_ref is not None and (
            role != "tool" or type(object_ref) is not dict
            or object_ref.get("owner") != self.service.owner
            or object_ref.get("source_ref") != ref
            or type(object_ref.get("external_id")) is not str
            or object_ref.get("id") != ref + ":" + object_ref["external_id"]
        ):
            raise ValueError("CORRECTION_SOURCE_OBJECT_BINDING_INVALID")

    def freeze_source_index(self) -> dict[str, Any]:
        """Run query-free once after ingestion; the full-text BM25 index is declared."""
        if self.bank_sha256 is not None:
            raise ValueError("CORRECTION_INDEX_ALREADY_FROZEN")
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        before, rows = self._fact_state("freeze_before")
        sources = [row for row in rows if row["namespace"] == list(self.service.sources_namespace)]
        excluded = []
        source_reads, logical_bytes = 0, 0
        for row in sources:
            source = self._public_read("source", row["id"])
            source_reads += 1
            if source is None:
                raise ValueError("CORRECTION_SOURCE_UNAVAILABLE")
            self._validate_source(row["id"], source)
            logical_bytes += len(canonical(source).encode())
            if instant(source["observed_at"]) > instant(self.cutoff):
                excluded.append(row["id"])
                continue
            # String bytes remain exact. Non-string content has a declared, stable text form.
            body = (source["content"] if type(source["content"]) is str
                    else canonical(source["content"]))
            unit = source_unit(row["id"], source["role"], source["observed_at"], body)
            candidate = EvidenceCandidate(
                row["id"], source["role"], source["observed_at"], source["content_sha256"],
                text_sha256(body), len(body), self.token_count(canonical(unit)) + 1,
            )
            self._candidates[row["id"]] = candidate
            self._entries.append(IndexEntry(row["id"], row["id"], body))
        # Order by observed time, then deterministic Store-key order for equal times.
        # This is a common tie convention, not evidence of true arrival order or relevance.
        source_order = {row["id"]: position for position, row in enumerate(sources)}
        self._entries.sort(key=lambda entry: (
            instant(self._candidates[entry.ref].observed_at), source_order[entry.ref]))
        for row in rows:
            if row["namespace"] != list(self.service.namespace):
                continue
            metadata = row["value"].get("_v13_1", {})
            if metadata.get("owner") != self.service.owner:
                continue
            for version in metadata.get("history", []):
                refs = version.get("source_refs", [version.get("source_ref")])
                if not refs or any(ref not in self._candidates for ref in refs):
                    continue
                read = self._public_read("read", row["id"], version["revision"])
                handle = read.get("candidate_handle")
                binding = self._public_read("candidate", handle)
                if not read["ok"] or binding is None or digest(read["value"]) != digest(version):
                    raise ValueError("CORRECTION_VERSION_BINDING_CHANGED")
                frozen = {"handle": handle, "binding": binding}
                for ref in refs:
                    self._handles.setdefault(ref, []).append(frozen)
        after, _ = self._fact_state("freeze_after")
        if before != after:
            raise ValueError("CORRECTION_BANK_CHANGED_DURING_FREEZE")
        self.bank_sha256 = before
        self.index_sha256 = digest({
            "bank_sha256": before, "cutoff": self.cutoff, "config": self.config_sha256,
            "tokenizer": self.tokenizer_sha256,
            "sources": [asdict(self._candidates[e.ref]) for e in self._entries],
            "version_bindings": self._handles,
        })
        receipt = {"event": "correction_source_index", "query_free": True,
                   "index_sha256": self.index_sha256, "bank_sha256": before,
                   "eligible_sources": len(self._entries), "excluded_after_cutoff": excluded,
                   "source_exact_reads": source_reads, "logical_bytes": logical_bytes,
                   "wall_ns": time.perf_counter_ns() - wall,
                   "cpu_ns": time.process_time_ns() - cpu,
                   "index_features": "full source text BM25; no semantic extraction",
                   "version_guard_io": "all exact Store gets counted in correction_store_reads",
                   "io_accounting": "index/selected source bytes overlap Store-get bytes",
                   "physical_io_bytes": None, "generation_requests": 0, "embedding_requests": 0}
        self.emit(receipt)
        return receipt

    def _check_query(self, query: QueryView) -> None:
        if (self.bank_sha256 is None or self.index_sha256 is None
                or query.owner != self.service.owner or query.bank != self.service.namespace
                or query.config_sha256 != self.config_sha256 or query.cutoff != self.cutoff):
            raise ValueError("CORRECTION_QUERY_BINDING_CHANGED")

    @contextmanager
    def guard(self, query: QueryView) -> Iterator[None]:
        self._check_query(query)
        before, _ = self._fact_state("query_before")
        if before != self.bank_sha256:
            raise ValueError("CORRECTION_FROZEN_BANK_CHANGED")
        try:
            yield
        finally:
            after, _ = self._fact_state("query_finally")
            unchanged = before == after
            self.emit({"event": "correction_readonly_assertion", "query_id": query.query_id,
                       "before_sha256": before, "after_sha256": after, "unchanged": unchanged,
                       "auxiliary_candidate_handles_excluded": True})
            if not unchanged:
                raise ValueError("CORRECTION_READONLY_FACT_MUTATION")

    def retrieve(self, query: QueryView, limit: int = 32) -> ResearchSnapshot:
        self._check_query(query)
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError("CORRECTION_CANDIDATE_LIMIT_INVALID")
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        scores = _bm25_scores(self._entries, query.question)
        order = sorted((i for i, score in enumerate(scores) if score > 0),
                       key=lambda i: (-scores[i], i))[:limit]
        assert self.bank_sha256 is not None and self.index_sha256 is not None
        snapshot = ResearchSnapshot(query, self.bank_sha256, self.index_sha256,
                                    self.tokenizer_sha256, tuple(replace(
                                        self._candidates[self._entries[i].ref],
                                        retrieval_score=scores[i]) for i in order))
        self._issued[snapshot.snapshot_sha256] = snapshot
        self.emit({"event": "correction_candidate_pool", "snapshot": asdict(snapshot),
                   "snapshot_sha256": snapshot.snapshot_sha256,
                   "indexed_sources": len(self._entries), "returned_count": len(order),
                   "wall_ns": time.perf_counter_ns() - wall,
                   "cpu_ns": time.process_time_ns() - cpu,
                   "index_text_bytes_scanned": sum(len(e.text.encode()) for e in self._entries),
                   "mechanism": "shared BM25 lexical scoring, no query planning model"})
        return snapshot

    def read_selected(
        self, snapshot: ResearchSnapshot, selected_ids: Sequence[str],
    ) -> list[dict[str, Any]]:
        self._check_query(snapshot.query)
        if self._issued.get(snapshot.snapshot_sha256) != snapshot:
            raise ValueError("CORRECTION_RESEARCH_SNAPSHOT_NOT_ISSUED")
        pool = {c.source_ref: c for c in snapshot.candidates}
        if (len(set(selected_ids)) != len(selected_ids)
                or any(ref not in pool for ref in selected_ids)):
            raise ValueError("CORRECTION_UNSELECTED_SOURCE_READ")
        result = []
        for ref in selected_ids:
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            candidate = pool[ref]
            source = self._public_read("source", ref)
            if source is None:
                raise ValueError("CORRECTION_SOURCE_UNAVAILABLE")
            self._validate_source(ref, source)
            body = (source["content"] if type(source["content"]) is str
                    else canonical(source["content"]))
            if (source["owner"] != snapshot.query.owner
                    or source["role"] != candidate.role
                    or source["observed_at"] != candidate.observed_at
                    or source["content_sha256"] != candidate.source_sha256
                    or text_sha256(body) != candidate.body_text_sha256
                    or len(body) != candidate.codepoints):
                raise ValueError("CORRECTION_SOURCE_SNAPSHOT_CHANGED")
            for frozen in self._handles.get(ref, []):
                bound = self._public_read("candidate", frozen["handle"])
                if bound is None or bound != frozen["binding"]:
                    raise ValueError("CORRECTION_VERSION_BINDING_CHANGED")
                read = self._public_read("read", bound["record_id"], bound["revision"])
                if not read["ok"] or digest(read["value"]) != bound["version_sha256"]:
                    raise ValueError("CORRECTION_VERSION_BINDING_CHANGED")
            result.append(source_unit(ref, source["role"], source["observed_at"], body))
            self.emit({"event": "correction_selected_source_read", "source_ref": ref,
                       "source_sha256": candidate.source_sha256,
                       "body_text_sha256": candidate.body_text_sha256,
                       "range": [0, len(body)], "logical_bytes": len(canonical(source).encode()),
                       "wall_ns": time.perf_counter_ns() - wall,
                       "cpu_ns": time.process_time_ns() - cpu,
                       "version_guard_count": len(self._handles.get(ref, [])),
                       "physical_io_bytes": None})
        return result
