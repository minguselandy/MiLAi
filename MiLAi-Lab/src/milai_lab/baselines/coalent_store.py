"""Coalent ports over the existing owner-scoped Store and native Source revisions.

The experiment supplies the reviewed native-version Coalent package explicitly.
Retrieval opportunity belongs to the supplied search function; this port neither
widens its source set nor interprets source content.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Any, Literal, cast

from milai_lab.memory.functional_state import body_text, canonical, reference_key
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

    def bind_artifact(self, artifact_id: str, kind: str, value: str,
                      sources: list[dict[str, Any]]) -> str:
        """Bind one source/document revision using exact native IDs and versions."""
        bindings = [{"source_ref": s["event_id"],
                     "source_revision": s.get("source_revision", 1)} for s in sources]
        version = (str(bindings[0]["source_revision"]) if kind == "source" else
                   canonical(sorted((b["source_ref"], b["source_revision"]) for b in bindings)))
        self.service.store.put((*self.namespace, "artifacts"), artifact_id,
                               {"kind": kind, "value": value}, index=False)
        self.service.store.put((*self.namespace, "bindings"),
            reference_key([artifact_id, version]), {"bindings": bindings}, index=False)
        return version

    def source_bindings(self, artifact_id: str, version: str) -> list[dict[str, Any]]:
        item = self.service.store.get((*self.namespace, "bindings"),
                                      reference_key([artifact_id, version]))
        if item is None:
            raise ValueError("COALENT_NATIVE_ARTIFACT_BINDING_MISSING")
        return cast(list[dict[str, Any]], item.value["bindings"])

    def sync_sources(self, cache: Any, *,
                     excluded_source_refs: tuple[str, ...] = ()) -> dict[str, Any]:
        """Apply current visibility/revisions of sources actually bound by the cache.

        New, unbound sources remain discoverable through the retriever. They are
        not automatically declared relevant or used to invalidate every unit.
        The caller runs this before serving cached material, including after reload.
        """
        artifacts = sorted({ref for unit in self.all() for ref in unit.provenance.artifact_ids()})
        changes = []
        exposed: set[str] = set()
        session_sources: dict[str, list[dict[str, Any]]] | None = None
        for artifact_id in artifacts:
            if not cache.has_source(artifact_id):
                continue  # An earlier deletion may already have evicted this owner.
            item = self.service.store.get((*self.namespace, "artifacts"), artifact_id)
            if item is None:
                raise ValueError("COALENT_NATIVE_ARTIFACT_SCOPE_MISSING")
            scope = item.value
            if scope["kind"] == "source":
                source = self.service.source(scope["value"])
                sources = [source] if source is not None else []
                version = str(source.get("source_revision", 1)) if source is not None else ""
            else:
                if session_sources is None:
                    session_sources = {}
                    for source in self.service.source_arrivals()["events"]:
                        if source["event_id"] not in excluded_source_refs:
                            session_sources.setdefault(source["session"], []).append(source)
                sources = session_sources.get(scope["value"], [])
                version = canonical(sorted((s["event_id"], s.get("source_revision", 1))
                                           for s in sources))
            exposed.update(s["event_id"] for s in sources)
            result = (cache.source_changed(artifact_id, version=version) if sources
                      else cache.source_deleted(artifact_id))
            changes.append({"artifact_id": artifact_id, "visible": bool(sources),
                            "invalidation": asdict(result)})
        return {"bound_artifacts_enumerated": len(artifacts),
                "checked_source_refs": sorted(exposed), "changes": changes,
                "scope": "Native source/session membership and revisions; no content validation"}


class SourceRetriever:
    """Read exactly the IDs from the existing retrieval path, one chunk per message.

    Session artifacts require the complete sessions from the native session search.
    Current live-input exclusions must also be supplied to freshness synchronization.
    Artifact grouping changes neither message roles nor original bodies.
    """

    def __init__(self, service: MemoryService,
                 search: Callable[[str, str | None], Sequence[str]],
                 record: Callable[[dict[str, Any]], None], *,
                 artifact_scope: Literal["source", "session"] = "source") -> None:
        if artifact_scope not in {"source", "session"}:
            raise ValueError("COALENT_SOURCE_ARTIFACT_SCOPE_INVALID")
        self.service, self.search, self.record = service, search, record
        self.artifact_scope = artifact_scope
        self.persistence = StoreCognitionStore(service)

    def retrieve(self, query: str, *, namespace: str | None = None) -> list[Any]:
        from coalent.semantic.ports import Chunk

        refs = list(dict.fromkeys(self.search(query, namespace)))
        chunks, unavailable, available = [], [], []
        for ref in refs:
            source = self.service.source(ref)
            if source is None:
                unavailable.append(ref)
                continue
            available.append(source)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for source in available:
            key = source["session"] if self.artifact_scope == "session" else source["event_id"]
            grouped.setdefault(key, []).append(source)
        revisions = {}
        for key, sources in grouped.items():
            artifact_id = (reference_key(["session", key])
                           if self.artifact_scope == "session" else key)
            version = self.persistence.bind_artifact(artifact_id, self.artifact_scope, key, sources)
            for source in sources:
                revisions[source["event_id"]] = (artifact_id, version)
        for source in available:
            ref = source["event_id"]
            artifact_id, version = revisions[ref]
            payload = {"source_ref": ref, "role": source["role"], "origin": source["origin"],
                       "content": body_text(source), "object_ref": source.get("object_ref"),
                       "session": source["session"], "reported_at": source.get("occurred_at"),
                       "captured_at": source["observed_at"],
                       "calendar_context": source.get("calendar_context")}
            chunks.append(Chunk(artifact_id=artifact_id, version=version,
                text=json.dumps(payload, ensure_ascii=False),
                meta={"source": artifact_id, "title": source["session"],
                      "date": source.get("occurred_at") or "unknown"}))
        self.record({"event": "coalent_sources_retrieved", "query": query,
            "namespace": namespace, "requested_source_refs": refs,
            "visible_source_refs": [s["event_id"] for s in available],
            "artifact_scope": self.artifact_scope, "artifacts": len(grouped),
            "unavailable_source_refs": unavailable,
            "scope": "Complete original source bodies with roles and distinct clocks; "
                     "search opportunity and model costs belong to the supplied caller"})
        return chunks
