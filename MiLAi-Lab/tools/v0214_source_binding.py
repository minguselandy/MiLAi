"""Trusted local source adapter and deterministic selective acquisition, without gold inputs."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import asdict
from pathlib import Path

from milai_lab.methods import host_acquisition
from milai_lab.methods.acquisition_use import LexicalPolicy, Source, retrieve
from milai_lab.methods.host_acquisition import (
    AcquisitionHelper,
    Binding,
    SourcePage,
    SourceRef,
)
from v02_read_file import read_page

POLICY = LexicalPolicy(chunk_tokens=200, overlap_tokens=40, top_k=4,
                       k1=1.2, b=0.75, evidence_tokens=1600)


class FileSources:
    def __init__(self, roots: dict[Binding, Path], *, page_bytes: int = 4096,
                 source_api=host_acquisition):
        self.roots, self.page_bytes = roots, page_bytes
        self.source_api = source_api
        self.withheld: set[tuple[Binding, str]] = set()
        self.versions: dict[tuple[Binding, str], str] = {}

    async def inventory(self, binding: Binding) -> tuple[SourceRef, ...]:
        return await asyncio.to_thread(self._inventory, binding)

    def _inventory(self, binding: Binding) -> tuple[SourceRef, ...]:
        root = self.roots.get(binding)
        if root is None:
            raise PermissionError("UNBOUND_TASK")
        if not root.is_dir():
            raise FileNotFoundError("SOURCE_ROOT_UNAVAILABLE")
        paths = sorted([*root.glob("source-*.txt"), *root.glob("session_*.jsonl")])
        refs = []
        for path in paths:
            key = (binding, path.name)
            eligible = key not in self.withheld and not path.is_symlink() and path.is_file()
            if eligible:
                self.versions[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            refs.append(self.source_api.SourceRef(
                                  path.name, self.versions.get(key, "WITHHELD_UNKNOWN"),
                                  eligible=eligible,
                                  size_bytes=path.stat().st_size if eligible else None))
        return tuple(refs)

    async def read(self, binding: Binding, ref: SourceRef, cursor: int,
                   request_id: str) -> SourcePage:
        try:
            result = await asyncio.to_thread(read_page, self.roots[binding], ref.source_id,
                                             cursor, self.page_bytes, ref.version)
        except ValueError:
            return self.source_api.SourcePage(
                request_id, binding, ref.source_id, ref.version, "", cursor, None,
                self.source_api.Coverage.UNKNOWN)
        return self.source_api.SourcePage(
                          request_id, binding, ref.source_id, ref.version, result["text"], cursor,
                          result["next"]["offset"] if result["next"] else None,
                          self.source_api.Coverage.COMPLETE if result["status"] == "EOF"
                          else self.source_api.Coverage.PARTIAL)

    async def search(self, binding: Binding, query: str, business_tools: list[dict]) -> dict:
        """Local lexical backend scans only currently eligible bound sources, not Product memory."""
        start = time.monotonic()
        refs = await self.inventory(binding)
        def load():
            sources = []
            for ref in refs:
                path = self.roots[binding] / ref.source_id
                if not ref.eligible or path.is_symlink():
                    continue
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() == ref.version:
                    sources.append(Source(ref.source_id, raw.decode()))
            return sources

        sources = await asyncio.to_thread(load)

        def offsets(text: str) -> list[tuple[int, int]]:
            return [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]

        def count(text: str) -> int:
            return len(offsets(text))

        result = await asyncio.to_thread(retrieve, query, business_tools, sources,
                                         count, offsets, POLICY)
        current = {ref.source_id: ref for ref in await self.inventory(binding) if ref.eligible}
        # Search completion is never full-history coverage, even for a single matching range.
        return {"query": result["query"], "original_question": query,
                "backend": "WORD_CHUNK_BM25_V1", "policy": asdict(POLICY),
                "source_coverage": "PARTIAL", "query_status": result["status"],
                "spans": [{key: value for key, value in asdict(span).items() if key != "text"}
                          for span in result["spans"] if span.source_id in current
                          and span.source_version == current[span.source_id].version],
                "seconds": time.monotonic() - start,
                "bytes_scanned": sum(len(source.text.encode()) for source in sources)}


async def acquire_for_task(helper: AcquisitionHelper, backend: FileSources, binding: Binding,
                           task: dict, *, complete_bytes: int = 32768,
                           max_pages: int = 20) -> tuple[list[SourcePage], dict]:
    if task.get("history_needed") is False:
        return [], {"binding": asdict(binding), "sources": [], "mode": "NO_MEMORY_NEEDED",
                    "coverage": "UNKNOWN"}
    refs = await helper.resolve_sources(binding)
    base = {"binding": asdict(binding), "sources": [asdict(ref) for ref in refs]}
    if not refs:
        return [], {**base, "mode": "NO_SOURCE", "coverage": "UNKNOWN"}
    exact = task.get("exact_source")
    if exact is not None:
        selected = [ref for ref in refs if ref.source_id == exact]
        pages = [await helper.read_source(binding, ref) for ref in selected]
        return pages, {**base, "mode": "EXACT_READ", "coverage": "SOURCE_RANGE_ONLY"}
    if all(ref.size_bytes is not None for ref in refs) and sum(
            ref.size_bytes or 0 for ref in refs) <= complete_bytes:
        results = await asyncio.gather(*(helper.bounded_scan(binding, ref, max_pages=max_pages)
                                         for ref in refs))
        return [page for pages, _ in results for page in pages], {
            **base, "mode": "BOUNDED_SCAN", "coverage": {
                ref.source_id: coverage for ref, (_, coverage) in zip(refs, results, strict=True)}}
    result = await asyncio.wait_for(backend.search(binding, task["question"],
        task["business_tools"]), helper.read_timeout)
    by_id = {ref.source_id: ref for ref in refs}
    # Selection yields offsets only. Evidence shown to the Host comes from actual public reads.
    pages = list(await asyncio.gather(*(helper.read_source(
        binding, by_id[span["source_id"]], span["start_byte"]) for span in result["spans"])))
    return pages, {**base, "mode": "LEXICAL_SEARCH", "search": result, "coverage": "PARTIAL"}
