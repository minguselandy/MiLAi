"""Coalent ports over the existing owner-scoped Store and native Source revisions.

The experiment supplies the reviewed native-version Coalent package explicitly.
Retrieval opportunity belongs to the supplied search function; this port neither
widens its source set nor interprets source content.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Any

from milai_lab.memory.functional_state import body_text
from milai_lab.memory.service import MemoryService


class StoreCognitionStore:
    """Persist upstream cognition units in the bank's ordinary Store."""

    def __init__(self, service: MemoryService) -> None:
        self.service = service
        self.namespace = (*service.namespace, "coalent_native_v1", service.owner)

    @staticmethod
    def _decode(value: dict[str, Any]) -> Any:
        from coalent.semantic.serde import cognition_from_json

        return cognition_from_json(json.dumps(value, ensure_ascii=False))

    def get(self, unit_id: str) -> Any:
        item = self.service.store.get(self.namespace, unit_id)
        return self._decode(item.value) if item is not None else None

    def put(self, unit: Any) -> None:
        from coalent.semantic.serde import cognition_to_json

        self.service.store.put(self.namespace, unit.id,
                               json.loads(cognition_to_json(unit)), index=False)

    def delete(self, unit_id: str) -> None:
        self.service.store.delete(self.namespace, unit_id)

    def all(self) -> list[Any]:
        return [self._decode(row["value"]) for row in self.service._rows(self.namespace)]

    def __len__(self) -> int:
        return len(self.all())

    def sync_sources(self, cache: Any) -> dict[str, Any]:
        """Apply current visibility/revisions of sources actually bound by the cache.

        New, unbound sources remain discoverable through the retriever. They are
        not automatically declared relevant or used to invalidate every unit.
        The caller runs this before serving cached material, including after reload.
        """
        refs = sorted({ref for unit in self.all() for ref in unit.provenance.artifact_ids()})
        changes = []
        for ref in refs:
            if not cache.has_source(ref):
                continue  # A prior deletion may already have evicted the same unit.
            source = self.service.source(ref)
            result = (cache.source_deleted(ref) if source is None else
                      cache.source_changed(ref, version=str(source.get("source_revision", 1))))
            changes.append({"source_ref": ref, "visible": source is not None,
                            "invalidation": asdict(result)})
        return {"bound_sources_enumerated": len(refs), "changes": changes,
                "scope": "Current native Source visibility/revisions; no content validation"}


class SourceRetriever:
    """Read exactly the source IDs returned by the caller's existing retrieval path."""

    def __init__(self, service: MemoryService,
                 search: Callable[[str, str | None], Sequence[str]],
                 record: Callable[[dict[str, Any]], None]) -> None:
        self.service, self.search, self.record = service, search, record

    def retrieve(self, query: str, *, namespace: str | None = None) -> list[Any]:
        from coalent.semantic.ports import Chunk

        refs = list(dict.fromkeys(self.search(query, namespace)))
        chunks, unavailable = [], []
        for ref in refs:
            source = self.service.source(ref)
            if source is None:
                unavailable.append(ref)
                continue
            payload = {"source_ref": ref, "role": source["role"], "content": body_text(source),
                       "session": source["session"], "reported_at": source.get("occurred_at"),
                       "captured_at": source["observed_at"]}
            chunks.append(Chunk(artifact_id=ref,
                version=str(source.get("source_revision", 1)),
                text=json.dumps(payload, ensure_ascii=False),
                meta={"source": ref, "title": source["session"],
                      "date": source.get("occurred_at") or "unknown"}))
        self.record({"event": "coalent_sources_retrieved", "query": query,
            "namespace": namespace, "requested_source_refs": refs,
            "visible_source_refs": [c.artifact_id for c in chunks],
            "unavailable_source_refs": unavailable,
            "scope": "Complete original source bodies with roles and distinct clocks; "
                     "search opportunity and model costs belong to the supplied caller"})
        return chunks
