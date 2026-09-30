"""Opt-in common raw retrieval, bounded delivery and one observed semantic boundary."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from milai_lab.baselines.benchmark_memories import raw_chunks, raw_index
from milai_lab.memory.embeddings import normalized
from milai_lab.memory.service import MemoryService
from milai_lab.memory.service_tools import create_service_tools
from milai_lab.methods.contextual_memory.retrieval import IndexEntry, _bm25_scores, hybrid_order

HEADER = "[Archived evidence; observations are historical and prose is unchecked]\n"
POLICY: dict[str, Any] = {
    "budget": 2048,
    "max_records": 6,
    "chunk_chars": 2048,
    "chunk_step": 1792,
    "bm25_k1": 1.2,
    "bm25_b": 0.75,
    "rrf_k": 60,
    "dense_min_cosine": 0.2,
    "admission": "bm25>0 OR cosine>=0.2",
    "query": "actual current public user text",
    "refresh": "same selected source ranges, record identities and object fields",
    "range_basis": "serialized_original_event_json",
    "empty": "historical_empty with actual current source metadata; no historical items",
    "trimming": "whole fields then explicit text/candidate truncation; retain conflicts",
    "unit_order": "selected records, selected object fields, selected source ranges",
    "candidate_limit": "six distinct record/object identities; source ranges are supporting leaves",
    "extra_query": "search_memory executes each explicit query and charges independently",
    "source_index": "actual trusted boundary metadata shares the ordinary 2048-token budget",
    "source_index_page_members": 6,
    "ordinary_delivery": "one System packet; matching current-turn recall_context body "
    "is a reference",
}


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


class GroundedMemoryRecipe:
    """One ordinary query per public turn; packets and writer cues are never captured."""

    def __init__(
        self,
        service: MemoryService,
        token_count: Callable[[str], int],
        *,
        embeddings: Any = None,
        representation: str = "milai",
        raw_index_storage: str = "bank_prefix",
        observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if representation not in {"raw", "receipt", "milai"}:
            raise ValueError("V13_PACKET_POLICY_INVALID")
        if raw_index_storage not in {"bank_prefix", "owner_bank_v1"}:
            raise ValueError("V13_RAW_INDEX_STORAGE_INVALID")
        if raw_index_storage != "bank_prefix" and service.mutation_contract != "event_bound_v1":
            raise ValueError("V13_RAW_INDEX_STORAGE_REQUIRES_EVENT_BOUND")
        self.service, self.token_count, self.embeddings = service, token_count, embeddings
        self.representation, self.observer = representation, observer
        self.namespace = (*service.namespace, "v13_2_recipe")
        self.raw_index_storage = raw_index_storage
        self.index_namespace = self.namespace
        if raw_index_storage == "owner_bank_v1":
            # The installed public SDK uses a textual prefix LIKE. A different
            # leading literal also avoids partial-component prefix matches.
            leading = ".".join(service.namespace)[0].casefold()
            if leading in {"%", "_"}:
                raise ValueError("V13_RAW_INDEX_BANK_PREFIX_REQUIRES_LITERAL")
            root = "derived-raw-index-v1" if leading != "d" else "separate-raw-index-v1"
            self.index_namespace = (root, _hash([service.owner, service.namespace]), service.owner)
        self.policy = {
            **POLICY,
            "representation": representation,
            "candidate_contract": service.candidate_contract,
            "source_backlinks": service.source_backlinks,
        }
        if service.mutation_contract == "event_bound_v1":
            self.policy["history_discovery"] = "actual revisions; bounded menus; visible coverage"
        if raw_index_storage != "bank_prefix":
            self.policy["raw_index_storage"] = raw_index_storage

    def _index_binding(self) -> dict[str, Any]:
        return {"schema": "owner_bank_raw_index_v1", "owner": self.service.owner,
                "bank_namespace": list(self.service.namespace),
                "document_contract": "raw_chunks_current_record_v1:2048:1792"}

    def _previous_index(self) -> tuple[dict[str, Any] | None, str]:
        item = self.service.store.get(self.index_namespace, "raw_index")
        if self.raw_index_storage == "bank_prefix":
            return (item.value if item is not None else None), "bank_prefix"
        if item is None:
            old = self.service.store.get(self.namespace, "raw_index")
            return None, "legacy_inline_ignored" if old is not None else "missing_rebuild"
        value = item.value
        if any(value.get(key) != expected for key, expected in self._index_binding().items()):
            return None, "binding_invalid_rebuild"
        if value.get("status") != "complete":
            return None, "pending_rebuild"
        index = value.get("index")
        if (not isinstance(index, dict) or value.get("index_sha256") != _hash(index)):
            return None, "hash_invalid_rebuild"
        return index, "complete_reuse"

    def _index_pending(self, reason: str) -> None:
        if self.raw_index_storage != "bank_prefix":
            value = {**self._index_binding(), "status": "pending", "reason": reason}
            self.service.store.put(self.index_namespace, "raw_index", value, index=False)
            self._emit({"event": "v13_derived_raw_index", **value,
                        "index_namespace": list(self.index_namespace),
                        "legacy_inline_removed": False})

    def _index_complete(self, index: dict[str, Any]) -> None:
        value = index
        if self.raw_index_storage != "bank_prefix":
            value = {**self._index_binding(), "status": "complete", "index": index,
                     "index_sha256": _hash(index)}
        self.service.store.put(self.index_namespace, "raw_index", value, index=False)
        if self.raw_index_storage != "bank_prefix":
            self._emit({"event": "v13_derived_raw_index", **self._index_binding(),
                        "status": "complete", "index_sha256": value["index_sha256"],
                        "index_namespace": list(self.index_namespace),
                        "new_embedding_chunks": index["new_embedding_chunks"],
                        "legacy_inline_removed": False})

    def _emit(self, value: dict[str, Any]) -> None:
        if self.observer is not None:
            self.observer(value)

    def _record(self, row: dict[str, Any], *, delivery: bool = False) -> dict[str, Any]:
        version = row.get("value") or {}
        result = {
            "id": row["id"],
            "revision": version.get("revision"),
            "content": version.get("content", ""),
            "kind": version.get("kind"),
            "scope": version.get("scope", {}),
            "basis": version.get("basis"),
            "content_verification": "unchecked",
            "source_refs": version.get("source_refs", [version.get("source_ref")]),
            "source_status": row.get("source_status", version.get("source_status", "unknown")),
            "fields": version.get("fields", {}),
            "fields_verification": version.get("fields_verification", "unchecked"),
            "object_ref": version.get("object_ref"),
        }
        if self.service.candidate_contract == "read_handle_v1" and "candidate_handle" in row:
            result["candidate_handle"] = row["candidate_handle"]
        if delivery and self.service.mutation_contract == "event_bound_v1":
            result["source_bindings"] = version.get("source_bindings")
            result["read_more"] = {"tool": "read_memory", "id": row["id"],
                                   "revision": version.get("revision")}
            index = self.service.history_index(row["id"])
            result["history_index"] = {key: index[key] for key in (
                "status", "revision_count", "revisions", "omitted_count",
                "index_hash", "next_cursor"
            ) if key in index}
            result["history_index"]["read_more"] = {"tool": "read_memory", "id": row["id"],
                "view": "history", "cursor": result["history_index"].get("next_cursor")}
        return result

    def _snapshot(self, current_source: str) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        captured = [self.service.source(row["event_id"]) for row in self.service.sources()]
        sources = [row for row in captured if row is not None]
        records = self.service.records() if self.representation == "milai" else []
        observations = (
            self.service.observations() if self.representation != "raw" else {"objects": []}
        )
        revision = _hash(
            {
                "sources": [(row["event_id"], row["content_sha256"]) for row in sources],
                "records": [
                    (row["id"], (row.get("value") or {}).get("revision")) for row in records
                ],
                "observations": observations,
            }
        )
        documents = [row for row in sources if row["event_id"] != current_source]
        documents += [
            {
                "event_id": "record:" + row["id"],
                "role": "semantic_record",
                "record_id": row["id"],
                "owner": self.service.owner,
                "content": self._record(row),
            }
            for row in records
            if row["ok"]
        ]
        return documents, observations, revision

    def _retrieve(
        self, documents: list[dict[str, Any]], query: str
    ) -> tuple[list[dict[str, Any]], str]:
        previous, index_state = self._previous_index()
        chunks = [vars(row) for row in raw_chunks(documents)]
        if not chunks:
            return [], "empty"
        entries = [IndexEntry(row["id"], row["source_id"], row["content"]) for row in chunks]
        lexical = _bm25_scores(entries, query)
        degradation = "dense_unavailable"
        if self.embeddings is not None:
            try:
                self._index_pending(index_state)
                index = raw_index(
                    documents,
                    self.embeddings.embed_documents,
                    previous,
                )
                self._index_complete(index)
                query_vector = self.embeddings.embed_query(query)
                query_norm = normalized(query_vector, len(query_vector))
                cosines = [
                    sum(
                        a * b
                        for a, b in zip(
                            query_norm, normalized(vector, len(query_vector)), strict=True
                        )
                    )
                    for vector in index["vectors"]
                ]
                order = hybrid_order(entries, query, index["vectors"], query_vector)
                admitted = [
                    position
                    for position in order
                    if lexical[position] > 0 or cosines[position] >= POLICY["dense_min_cosine"]
                ]
                return [chunks[position] for position in admitted], "bm25_dense_rrf60"
            except Exception as error:
                degradation = "dense_unavailable:" + type(error).__name__
                self._emit(
                    {
                        "event": "v13_packet_retrieval_degraded",
                        "reason": str(error),
                        "error_type": type(error).__name__,
                    }
                )
        order = sorted(
            (position for position, score in enumerate(lexical) if score > 0),
            key=lambda position: (-lexical[position], position),
        )
        return [chunks[position] for position in order], degradation

    def _select(
        self, ranked: list[dict[str, Any]], observations: dict[str, Any],
        snapshot_versions: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Freeze identities at first query; dirty refresh cannot introduce unrelated records."""
        selected = []
        matched_identities: set[tuple[str, int]] = set()
        for row in ranked[: POLICY["max_records"]]:
            ref = row["source_id"]
            records = (
                [self.service.read(ref.removeprefix("record:"))]
                if ref.startswith("record:")
                else self.service.backlink_candidates([ref], POLICY["max_records"])
                if self.representation == "milai"
                else []
            )
            refs = {ref}
            matched_versions = []
            source_matches = []
            for record in records:
                version = record.get("value") or {}
                refs.update(version.get("source_refs", [version.get("source_ref")]))
                if ref.startswith("record:"):
                    revision = (snapshot_versions or {}).get(record["id"])
                    if revision is not None:
                        matched_versions.append({"record_id": record["id"], "revision": revision,
                                                 "matched_via": "actual_record_snapshot"})
                else:
                    for match in record.get("source_matches", []):
                        source_matches.append({"record_id": record["id"],
                            **{key: value for key, value in match.items()
                               if key != "current_revision_at_read"},
                            "current_revision_at_match_snapshot":
                            match["current_revision_at_read"]})
                        matched_versions.extend({"record_id": record["id"], "revision": revision,
                            "matched_via": "actual_source_citation", "source_ref": ref,
                            "source_hash": match["source_hash"]}
                            for revision in match["matched_revisions"])
            fields = [
                [obj["object_ref"]["id"], name]
                for obj in observations["objects"]
                for name, field in obj["fields"].items()
                if any(event["source_event_id"] in refs for event in field["history"])
            ]
            bounded_matches = []
            for match in matched_versions:
                identity = (match["record_id"], match["revision"])
                if identity in matched_identities or len(matched_identities) < 6:
                    matched_identities.add(identity)
                    bounded_matches.append(match)
            selected.append(
                {
                    **row,
                    "record_ids": [record["id"] for record in records if record["ok"]],
                    "object_fields": fields,
                    **({"matched_versions": bounded_matches,
                        "source_matches": source_matches}
                       if self.service.mutation_contract == "event_bound_v1" else {}),
                }
            )
        return selected

    def _units(
        self, selected: list[dict[str, Any]], observations: dict[str, Any]
    ) -> list[dict[str, Any]]:
        units = []
        delivered_records: set[str] = set()
        historical: set[tuple[str, int]] = set()
        for selected_row in selected:
            ref, entry_id = selected_row["source_id"], selected_row["id"]
            if not ref.startswith("record:"):
                event = self.service.source(ref)
                if event is None:
                    continue
                # raw_chunks indexes json.dumps(event), not source.content offsets.
                units.append(
                    {
                        "unit_id": "source:" + entry_id,
                        "type": "source",
                        "source_ref": ref,
                        "role": event["role"],
                        "source_hash": event["content_sha256"],
                        "observed_at": event["observed_at"],
                        "excerpt": selected_row["content"],
                        "range": [selected_row["start"], selected_row["end"]],
                        "range_basis": POLICY["range_basis"],
                        "read_more": {"tool": "read_source", "source_ref": ref},
                    }
                )
            for memory_id in selected_row["record_ids"]:
                if (memory_id in delivered_records
                        and self.service.mutation_contract == "event_bound_v1"):
                    continue
                row = self.service.read(memory_id)
                if row["ok"]:
                    delivered_records.add(memory_id)
                    record = self._record(row, delivery=len(delivered_records) <= 6)
                    matches = [match for selected_match in selected
                               for match in selected_match.get("matched_versions", [])
                               if match["record_id"] == memory_id]
                    if self.service.mutation_contract == "event_bound_v1":
                        revisions = sorted({match["revision"] for match in matches})
                        record["matched_revisions"] = revisions[:6]
                        match_map = {(_match["source_ref"], _match["record_id"]): _match
                            for selection in selected
                            for _match in selection.get("source_matches", [])
                            if _match["record_id"] == memory_id}
                        source_matches = [{**{key: match[key] for key in (
                            "source_ref", "source_hash", "matched_revisions",
                            "matched_revision_count", "matched_revision_set_hash",
                            "omitted_matched_revision_count",
                            "current_revision_at_match_snapshot")},
                            **({"read_more": match["read_more"]}
                               if match["omitted_matched_revision_count"] else {}),
                            "current_revision_at_read": row["value"]["revision"],
                            "current_version_cites_source": match["source_ref"] in
                            (row["value"].get("source_refs", [row["value"].get("source_ref")]))}
                            for match in match_map.values()]
                        record["source_matches"] = source_matches[:6]
                        record["source_match_count"] = len(source_matches)
                        if len(source_matches) > 6:
                            record["source_match_set_hash"] = _hash(source_matches)
                            record["omitted_source_match_count"] = len(source_matches) - 6
                            record["source_matches_read_more"] = {
                                "tool": "read_memory", "id": memory_id, "view": "history"}
                    units.append(
                        {
                            "unit_id": "record:" + memory_id,
                            "type": "record",
                            "record": record,
                            **({"version_sha256": _hash(row["value"])}
                               if self.service.mutation_contract == "event_bound_v1" else {}),
                        }
                    )
                    if self.service.mutation_contract == "event_bound_v1":
                        self._light_semantic(record)
                    for match in matches:
                        identity = (memory_id, match["revision"])
                        if (identity in historical or match["revision"] == row["value"]["revision"]
                                or len(historical) >= POLICY["max_records"]):
                            continue
                        old = self.service.read(*identity)
                        if not old["ok"]:
                            continue
                        historical.add(identity)
                        old_record = self._record(old)
                        old_record.pop("candidate_handle", None)
                        self._light_semantic(old_record)
                        units.append({"unit_id": "history:" + memory_id + ":" + str(identity[1]),
                            "type": "historical_record", "record": old_record,
                            "source_bindings": old["value"].get("source_bindings"),
                            "matched_via": match["matched_via"], "historical": True,
                            "version_sha256": _hash(old["value"]),
                            "current_verified": False,
                            "read_more": {"tool": "read_memory", "id": memory_id,
                                          "revision": identity[1]}})
            for object_id, name in selected_row["object_fields"]:
                obj = next(
                    (
                        row
                        for row in observations["objects"]
                        if row["object_ref"]["id"] == object_id
                    ),
                    None,
                )
                if obj is None or name not in obj["fields"]:
                    continue
                field = obj["fields"][name]
                candidates = [
                    {
                        key: row[key]
                        for key in (
                            "observation_id",
                            "source_event_id",
                            "source_hash",
                            "field_paths",
                            "literal_value",
                            "resource_version",
                            "version_domain",
                            "observed_at",
                        )
                    }
                    for row in field["candidates"]
                ]
                units.append(
                    {
                        "unit_id": "field:" + object_id + ":" + name,
                        "type": "observation_field",
                        "object_ref": obj["object_ref"],
                        "field": name,
                        "status": field["status"],
                        "selection": field["selection"],
                        "candidate_count": len(candidates),
                        "candidates": candidates,
                        "current_verified": False,
                    }
                )
        priority = {"record": 0, "historical_record": 1, "observation_field": 2, "source": 3}
        return sorted(units, key=lambda row: priority[row["type"]])

    @staticmethod
    def _light_semantic(record: dict[str, Any]) -> None:
        """Omit empty operational placeholders; preserve actual semantic scope and support."""
        if not record.get("fields"):
            record.pop("fields", None)
            record.pop("fields_verification", None)
        if record.get("object_ref") is None:
            record.pop("object_ref", None)

    @staticmethod
    def _descriptor(unit: dict[str, Any]) -> dict[str, Any]:
        value = {"unit_id": unit["unit_id"], "type": unit["type"],
                 "unit_snapshot_hash": _hash(unit), "content_verification": "unchecked"}
        if unit["type"] in {"record", "historical_record"}:
            record = unit["record"]
            value.update(id=record["id"], revision=record["revision"],
                         view_at_snapshot="historical" if unit["type"] == "historical_record"
                         else "current_at_snapshot", current_verified=False,
                         version_sha256=unit.get("version_sha256"),
                         read_more={"tool": "read_memory", "id": record["id"],
                                    "revision": record["revision"]})
        elif unit["type"] == "source":
            value.update(source_ref=unit["source_ref"], role=unit["role"],
                         source_hash=unit["source_hash"], read_more=unit["read_more"])
        else:
            value.update(object_id=unit["object_ref"]["id"], field=unit["field"],
                         read_more={"tool": "read_observations",
                                    "object_id": unit["object_ref"]["id"]})
        return value

    def _coverage(
        self, units: list[dict[str, Any]], chosen: list[dict[str, Any]],
        *, request_ref: str | None = None,
        inventory: list[dict[str, Any]] | None = None, selection_count: int = 0,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        available = {unit["unit_id"]: self._descriptor(unit) for unit in units}
        descriptors = {row["unit_id"]: {**row, "availability": "unavailable"}
                       for row in inventory or [] if row["unit_id"] not in available}
        unavailable = len(descriptors)
        descriptors.update(available)
        delivered = {unit["unit_id"] for unit in chosen}
        omitted = [value for key, value in descriptors.items() if key not in delivered]
        truncated = sum(bool(unit.get("content_truncated") or unit.get("omitted_candidate_count")
                             or unit.get("record", {}).get("content_truncated")) for unit in chosen)
        digest = _hash([self.service.owner, self.namespace, request_ref, omitted])
        status = ("no_matches" if not selection_count and not descriptors else
                  "selected_unavailable" if not units else
                  "partial_unavailable" if unavailable else "selected")
        return {"selection_status": status, "retrieved_selection_count": selection_count,
                "selected_unit_count": len(descriptors), "delivered_unit_count": len(delivered),
                "unavailable_unit_count": unavailable,
                "omitted_unit_count": len(omitted), "omitted_set_hash": digest,
                "truncated_unit_count": truncated, "bank_exhaustive": False,
                "delivery_status": "partial" if omitted or truncated or unavailable
                or (not units and selection_count)
                else "complete_selection",
                "read_more": {"tool": "recall_context", "cursor": "selected-" + digest[:24] + ":0"}
                if omitted else None}, omitted

    def _packet(
        self, units: list[dict[str, Any]], revision: str | None,
        source_index: dict[str, Any] | None = None, *,
        request_ref: str | None = None, query_kind: str = "ordinary_public",
        coverage: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        packet = {
            "ok": True,
            "schema": "bounded_evidence_v1",
            "owner": self.service.owner,
            "bank_revision": revision,
            "items": units,
            "current_verified": False,
        }
        if source_index is not None:
            packet.update(source_index=source_index, historical_empty=not units,
                          request_ref=request_ref, query_kind=query_kind)
            packet["coverage"] = coverage if coverage is not None else {
                "selection_status": "not_retrieved", "selected_unit_count": None,
                "delivered_unit_count": 0, "omitted_unit_count": None,
                "bank_exhaustive": False, "read_more": None,
            }
        identities = {
            "record:" + unit["record"]["id"] for unit in units
            if unit["type"] in {"record", "historical_record"}
        }
        identities.update(
            "object:" + unit["object_ref"]["id"]
            for unit in units
            if unit["type"] == "observation_field"
        )
        packet["candidate_count"] = len(identities)
        packet["packet_hash"] = _hash(packet)
        return packet, HEADER + _json(packet)

    def _fit(
        self, units: list[dict[str, Any]], revision: str,
        source_index: dict[str, Any] | None = None, *,
        request_ref: str | None = None, query_kind: str = "ordinary_public",
        material_budget: int = 2048,
        inventory: list[dict[str, Any]] | None = None, selection_count: int = 0,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        chosen: list[dict[str, Any]] = []
        omitted, delivered = [], set()
        candidates: set[str] = set()

        def material(values: list[dict[str, Any]]) -> str:
            return self._packet(values, revision, source_index, request_ref=request_ref,
                                query_kind=query_kind,
                                coverage=self._coverage(units, values, request_ref=request_ref,
                                    inventory=inventory, selection_count=selection_count)[0]
                                if source_index is not None else None)[1]

        for unit in units:
            key = unit["unit_id"]
            if key in delivered:
                continue
            identity = (
                "record:" + unit["record"]["id"]
                if unit["type"] in {"record", "historical_record"}
                else "object:" + unit["object_ref"]["id"]
                if unit["type"] == "observation_field"
                else None
            )
            if (
                identity is not None
                and identity not in candidates
                and len(candidates) >= POLICY["max_records"]
            ):
                omitted.append(key)
                continue
            value = json.loads(_json(unit))
            if self.token_count(material([*chosen, value])) > material_budget:
                # Candidate omission is explicit and never resolves a conflict by choosing a winner.
                if value["type"] == "observation_field":
                    value["omitted_candidate_count"] = value["candidate_count"]
                    value["candidate_set_hash"] = _hash(value["candidates"])
                    value["candidates"] = []
                    value["read_more"] = {
                        "tool": "read_observations",
                        "object_id": value["object_ref"]["id"],
                    }
                field = "excerpt" if value["type"] == "source" else "content"
                target = value if field == "excerpt" else value.get("record", {})
                if field in target:
                    body = target[field]
                    low, high = 0, len(body)
                    target["content_truncated"] = True
                    target["full_content_sha256"] = hashlib.sha256(body.encode()).hexdigest()
                    while low < high:
                        middle = (low + high + 1) // 2
                        target[field] = body[:middle]
                        if (
                            self.token_count(material([*chosen, value]))
                            <= material_budget
                        ):
                            low = middle
                        else:
                            high = middle - 1
                    target[field] = body[:low]
                    if field == "excerpt":
                        value["range"][1] = value["range"][0] + low
            if self.token_count(material([*chosen, value])) > material_budget:
                omitted.append(key)
                continue
            chosen.append(value)
            delivered.add(key)  # only actually delivered cards are deduplicated
            if identity is not None:
                candidates.add(identity)
        return chosen, omitted

    def _request_ref(self, session: str, turn_id: str) -> str:
        return "request-" + _hash([self.service.namespace, session, turn_id])[:24]

    def _source_index(
        self, session: str, *, cursor: str | None = None, request_ref: str | None = None,
        revision: str | None = None, query_kind: str = "metadata_only",
        material_budget: int = 2048,
    ) -> dict[str, Any]:
        for limit in range(POLICY["source_index_page_members"], 0, -1):
            index = self.service.source_boundary(session, cursor=cursor, limit=limit)
            if index["next_cursor"] is not None:
                index["read_more"] = {"tool": "read_current_sources",
                                      "cursor": index["next_cursor"]}
            _, material = self._packet([], revision, index, request_ref=request_ref,
                                       query_kind=query_kind)
            if self.token_count(material) <= material_budget:
                return index
        raise ValueError("V13_SOURCE_INDEX_MEMBER_EXCEEDS_MATERIAL_BUDGET")

    def current_sources_tool(
        self, cursor: str | None, config: RunnableConfig,
    ) -> dict[str, Any]:
        cfg = config["configurable"]
        if cfg.get("user_id") != self.service.owner or not cfg.get("v13_session"):
            raise ValueError("V13_PACKET_OWNER_MISMATCH")
        index = self._source_index(cfg["v13_session"], cursor=cursor)
        return self._packet([], None, index, query_kind="metadata_only")[0]

    def prepare_context(
        self,
        public_request: str,
        *,
        owner: str,
        session: str,
        turn_id: str,
        explicit_query: str | None = None,
        material_budget: int = 2048,
    ) -> dict[str, Any]:
        if owner != self.service.owner:
            raise ValueError("V13_PACKET_OWNER_MISMATCH")
        if type(material_budget) is not int or not 1 <= material_budget <= POLICY["budget"]:
            raise ValueError("V13_PACKET_MATERIAL_BUDGET_INVALID")
        current_source = self.service.event_id(session, turn_id, "user")
        actual = self.service.source(current_source)
        if actual is None or actual["content"] != public_request:
            raise ValueError("V13_PACKET_ACTUAL_PUBLIC_REQUEST_REQUIRED")
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        query = public_request if explicit_query is None else explicit_query
        if not isinstance(query, str):
            raise ValueError("V13_PACKET_QUERY_INVALID")
        key = (
            "packet:" + _hash([session, turn_id])
            if explicit_query is None
            else "query:" + _hash([session, turn_id, query])
        )
        request_ref = self._request_ref(session, turn_id)
        query_kind = "ordinary_public" if explicit_query is None else "explicit_additional"
        cached = self.service.store.get(self.namespace, key)
        documents, observations, revision = self._snapshot(current_source)
        source_index = (self._source_index(session, request_ref=request_ref, revision=revision,
                                         query_kind=query_kind, material_budget=material_budget)
                        if self.service.mutation_contract == "event_bound_v1" else None)
        if cached is not None and explicit_query is None:
            state = cached.value
            if state["query_hash"] != _hash(public_request) or state["policy"] != self.policy:
                raise ValueError("V13_PACKET_TURN_CHANGED")
            if (state["bank_revision"] == revision
                    and state["packet"].get("source_index") == source_index
                    and state.get("material_budget", POLICY["budget"]) == material_budget):
                result = {**state, "reused": True, "retrieval_calls": 0}
                self._emit(
                    {"event": "v13_evidence_packet_reused", "packet_hash": state["packet_hash"]}
                )
                return result
            selected, retrieval, calls = state["selected"], state["retrieval"], 0
        else:
            ranked, retrieval = self._retrieve(documents, query)
            snapshot_versions = {row["record_id"]: row["content"]["revision"] for row in documents
                                 if row.get("role") == "semantic_record"}
            selected, calls = self._select(ranked, observations, snapshot_versions), 1
        units = self._units(selected, observations)
        inventory = (cached.value.get("selected_inventory", [])
                     if source_index is not None and cached is not None
                     and explicit_query is None else None)
        chosen, omitted = self._fit(units, revision, source_index,
                                    request_ref=request_ref, query_kind=query_kind,
                                    material_budget=material_budget, inventory=inventory,
                                    selection_count=len(selected))
        coverage, omitted_menu = (self._coverage(units, chosen, request_ref=request_ref,
                                                inventory=inventory, selection_count=len(selected))
                                 if source_index is not None else (None, []))
        packet, material = self._packet(chosen, revision, source_index,
                                        request_ref=request_ref, query_kind=query_kind,
                                        coverage=coverage)
        if not chosen and source_index is None:
            material = ""
        if self.token_count(material) > material_budget:
            raise ValueError("V13_PACKET_METADATA_EXCEEDS_MATERIAL_BUDGET")
        state = {
            "policy": self.policy,
            "query_hash": _hash(query),
            "query_kind": query_kind,
            "actual_public_request_hash": _hash(public_request),
            "bank_revision": revision,
            "packet": packet,
            "packet_hash": packet["packet_hash"],
            "material": material,
            "material_tokens": self.token_count(material),
            "material_budget": material_budget,
            "selected": selected,
            "omitted_ids": omitted,
            "retrieval": retrieval,
            "retrieval_calls": calls,
            "reused": False,
            "wall_ns": time.perf_counter_ns() - wall,
            "cpu_ns": time.process_time_ns() - cpu,
            "measurement": "whole source/record/fact snapshot scans; Store IO not fully counted",
            "recall_packet_hashes": (cached.value.get("recall_packet_hashes", [])
                                     if cached is not None and explicit_query is None else []),
        }
        if source_index is not None:
            all_descriptors = {row["unit_id"]: row for row in inventory or []}
            all_descriptors.update({unit["unit_id"]: self._descriptor(unit) for unit in units})
            state.update(omitted_menu=omitted_menu,
                         selected_inventory=list(all_descriptors.values()))
        self.service.store.put(self.namespace, key, state, index=False)
        self.service.store.put(
            self.namespace, "last_packet:" + _hash([session, turn_id]), {"key": key}, index=False
        )
        self._emit({"event": "v13_evidence_packet", **state})
        return state

    def selected_page_tool(self, cursor: str, config: RunnableConfig) -> dict[str, Any]:
        """Explicit paid pointer page over actual omitted selection; never retrieves again."""
        _, cfg = self._public_source(config)
        cached = self.service.store.get(
            self.namespace, "packet:" + _hash([cfg["v13_session"], cfg["v13_turn_id"]]))
        if cached is None:
            raise ValueError("V13_SELECTED_PAGE_NOT_READY")
        menu = cached.value.get("omitted_menu", [])
        digest = _hash([self.service.owner, self.namespace,
                       self._request_ref(cfg["v13_session"], cfg["v13_turn_id"]), menu])
        prefix, separator, offset = cursor.rpartition(":")
        if (separator != ":" or prefix != "selected-" + digest[:24]
                or not offset.isdecimal() or not 0 <= int(offset) < len(menu)):
            raise ValueError("V13_SELECTED_CURSOR_CHANGED_OR_INVALID")
        start = int(offset)
        chosen: list[dict[str, Any]] = []
        identities: set[str] = set()

        def packet() -> dict[str, Any]:
            end = start + len(chosen)
            value = {"ok": True, "schema": "selected_evidence_menu_v1",
                     "owner": self.service.owner, "query_kind": "explicit_selected_page",
                     "selection_hash": digest, "items": chosen, "total_unit_count": len(menu),
                     "start": start, "omitted_count": len(menu) - end,
                     "next_cursor": "selected-" + digest[:24] + ":" + str(end)
                     if end < len(menu) else None, "retrieval_calls": 0,
                     "current_verified": False, "content_verification": "unchecked"}
            value["packet_hash"] = _hash(value)
            return value

        for row in menu[start:]:
            if row.get("availability") == "unavailable":
                pass  # A pointer to unavailable selected material is never a successful read.
            elif row["type"] == "source":
                source = self.service.source(row["source_ref"])
                if (source is None or source["role"] != row["role"]
                        or source["content_sha256"] != row["source_hash"]):
                    raise ValueError("V13_SELECTED_SOURCE_CHANGED")
            elif row["type"] in {"record", "historical_record"}:
                version = self.service.read(row["id"], row["revision"])
                if (not version["ok"] or _hash(version["value"]) != row["version_sha256"]):
                    raise ValueError("V13_SELECTED_REVISION_UNAVAILABLE")
            identity = ("record:" + row["id"] if "id" in row else
                        "object:" + row["object_id"] if "object_id" in row else None)
            if identity is not None and identity not in identities and len(identities) >= 6:
                break
            chosen.append(row)
            if self.token_count(_json(packet())) > POLICY["budget"]:
                chosen.pop()
                break
            if identity is not None:
                identities.add(identity)
        if not chosen:
            raise ValueError("V13_SELECTED_MENU_MEMBER_EXCEEDS_BUDGET")
        result = packet()
        self._emit({"event": "v13_explicit_selected_page", "material_tokens":
                    self.token_count(_json(result)), "packet_hash": result["packet_hash"],
                    "retrieval_calls": 0})
        return result

    def _public_source(self, config: RunnableConfig) -> tuple[dict[str, Any], dict[str, Any]]:
        cfg = config["configurable"]
        if cfg.get("user_id") != self.service.owner:
            raise ValueError("V13_PACKET_OWNER_MISMATCH")
        source = self.service.source(
            self.service.event_id(cfg["v13_session"], cfg["v13_turn_id"], "user")
        )
        if source is None:
            raise ValueError("V13_PACKET_ACTUAL_PUBLIC_REQUEST_REQUIRED")
        return source, dict(cfg)

    def recall_tool(self, config: RunnableConfig) -> dict[str, Any]:
        """The ordinary no-query recall shares the public turn's fixed prefetch packet."""
        source, cfg = self._public_source(config)
        packet = self.prepare_context(
            source["content"],
            owner=cfg["user_id"],
            session=cfg["v13_session"],
            turn_id=cfg["v13_turn_id"],
        )
        self._emit(
            {
                "event": "v13_autonomous_recall",
                "query_policy": POLICY["query"],
                "packet_hash": packet["packet_hash"],
            }
        )
        key = "packet:" + _hash([cfg["v13_session"], cfg["v13_turn_id"]])
        state = {**packet, "recall_packet_hashes": list(dict.fromkeys([
            *packet.get("recall_packet_hashes", []), packet["packet_hash"]]))}
        self.service.store.put(self.namespace, key, state, index=False)
        return dict(packet["packet"])

    def search_tool(self, query: str, config: RunnableConfig) -> dict[str, Any]:
        """Every explicit extra query uses its actual parameters and paid retrieval."""
        source, cfg = self._public_source(config)
        packet = self.prepare_context(
            source["content"],
            owner=cfg["user_id"],
            session=cfg["v13_session"],
            turn_id=cfg["v13_turn_id"],
            explicit_query=query,
        )
        self._emit(
            {
                "event": "v13_explicit_additional_recall",
                "requested_query": query,
                "query_policy": "actual explicit query; separate paid retrieval",
                "packet_hash": packet["packet_hash"],
            }
        )
        return dict(packet["packet"])

    def hook(self, base_system: str, *, prefetch: bool = True) -> Callable[..., dict[str, Any]]:
        def prepare(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
            cfg = config["configurable"]
            human = next(
                row for row in reversed(state["messages"]) if isinstance(row, HumanMessage)
            )
            actual, _ = self._public_source(config)
            if actual["content"] != human.content or actual["event_id"] != self.service.event_id(
                cfg["v13_session"], str(human.id), "user"
            ):
                raise ValueError("V13_PACKET_ACTUAL_PUBLIC_REQUEST_REQUIRED")
            request_ref = self._request_ref(cfg["v13_session"], str(human.id))
            ordinary = self.service.store.get(
                self.namespace, "packet:" + _hash([cfg["v13_session"], str(human.id)])
            )
            current_start = max(index for index, row in enumerate(state["messages"])
                                if row is human)
            recalls: dict[int, dict[str, Any]] = {}
            for position, row in enumerate(state["messages"][current_start + 1:],
                                           start=current_start + 1):
                if not isinstance(row, ToolMessage) or row.name != "recall_context":
                    continue
                try:
                    body = json.loads(str(row.content))
                except (TypeError, ValueError):
                    continue
                if (ordinary is not None and isinstance(body, dict) and body.get("ok") is True
                        and row.status == "success" and body.get("schema") == "bounded_evidence_v1"
                        and body.get("owner") == self.service.owner
                        and body.get("request_ref") == request_ref
                        and body.get("query_kind") == "ordinary_public"
                        and body.get("packet_hash") in ordinary.value.get(
                            "recall_packet_hashes", [])
                        and body.get("packet_hash") == _hash({
                            key: value for key, value in body.items() if key != "packet_hash"})):
                    recalls[position] = body
            reference_bodies: dict[int, str] = {}
            if prefetch or recalls:
                available = POLICY["budget"]
                for _ in range(6):
                    context = self.prepare_context(
                        str(human.content), owner=cfg["user_id"], session=cfg["v13_session"],
                        turn_id=str(human.id), material_budget=available,
                    )
                    packet, material = context["packet"], context["material"]
                    reference_bodies = {position: _json({
                        "ok": body["ok"], "packet_hash": body["packet_hash"],
                        "presented_packet_hash": packet["packet_hash"],
                    }) for position, body in recalls.items()}
                    total = self.token_count(material) + sum(
                        self.token_count(body) for body in reference_bodies.values())
                    if total <= POLICY["budget"]:
                        break
                    # Same frozen selections, no new dense query. Leave a small margin
                    # because a new packet hash can tokenize differently after trimming.
                    available -= total - POLICY["budget"] + 16
                else:
                    raise ValueError("V13_ORDINARY_TOTAL_MATERIAL_BUDGET_EXCEEDED")
            else:
                index = self._source_index(cfg["v13_session"], request_ref=request_ref)
                packet, material = self._packet([], None, index, request_ref=request_ref,
                                                query_kind="metadata_only")
            # Only this tool's actual current-turn packet is repeated in the System view.
            # The complete Graph/checkpoint receipt and all other tool bodies are unchanged.
            projected = [row.model_copy(update={"content": reference_bodies[position]})
                if position in recalls else row
                for position, row in enumerate(state["messages"])]
            self._emit({"event": "v13_current_source_delivery",
                        "packet_hash": packet["packet_hash"],
                        "source_index_hash": packet["source_index"]["source_index_hash"],
                        "material": material, "material_tokens": self.token_count(material),
                        "reference_tokens": sum(self.token_count(body)
                                                for body in reference_bodies.values()),
                        "ordinary_total_tokens": self.token_count(material) + sum(
                            self.token_count(body) for body in reference_bodies.values()),
                        "historical_empty": packet["historical_empty"],
                        "projected_recall_ids": [state["messages"][position].tool_call_id
                                                 for position in recalls],
                        "projected_recall_positions": list(recalls),
                        "budget_scope": "current index, one ordinary packet "
                        "and recall reference bodies; "
                        "chat envelope and explicit reads extra"})
            return {
                "llm_input_messages": [
                    SystemMessage(
                        content=base_system
                        + ("\n" + material if material else "")
                    ),
                    *projected,
                ]
            }

        return prepare

    def maintain(
        self,
        model: Any,
        *,
        session: str,
        turn_id: str,
        source_refs: list[str],
        config: RunnableConfig,
        instruction: str,
        repairs: int = 0,
    ) -> dict[str, Any]:
        """At most one generation plus one enabled repair; up to six non-atomic mutations each."""
        if repairs not in {0, 1}:
            raise ValueError("V13_WRITER_REPAIR_POLICY_INVALID")
        user_ref = self.service.event_id(session, turn_id, "user")
        if user_ref not in source_refs or any(
            self.service.source(ref) is None for ref in source_refs
        ):
            raise ValueError("V13_WRITER_ACTUAL_BOUNDARY_REQUIRED")
        key = "maintenance:" + _hash([session, turn_id])
        old = self.service.store.get(self.namespace, key)
        if old is not None:
            return {**old.value, "replayed": True}
        # A successful Host proposal sourced in this user message suppresses redundant maintenance.
        accepted = self.service.semantic_receipts(user_ref)
        if accepted:
            receipt = {
                "status": "skipped_host_committed",
                "generation_calls": 0,
                "host_receipts": accepted,
                "effect": "none",
            }
            self.service.store.put(self.namespace, key, receipt, index=False)
            self._emit({"event": "v13_semantic_boundary", **receipt})
            return receipt
        pending: dict[str, Any] = {
            "status": "pending",
            "effect": "unconfirmed",
            "generation_calls": 0,
            "phase": "actual_public_events_boundary",
            "source_refs": source_refs,
            "batch_atomic": False,
            "receipts": [],
        }
        self.service.store.put(self.namespace, key, pending, index=False)
        self.service.bind_source_boundary(session, turn_id + ":closed", source_refs)
        tools = [
            tool
            for tool in create_service_tools(self.service, replay_requested=True)
            if tool.name in {"manage_memory", "revise_memory"}
        ]
        last = self.service.store.get(self.namespace, "last_packet:" + _hash([session, turn_id]))
        existing_packet = self.service.store.get(
            self.namespace, last.value["key"] if last else "packet:" + _hash([session, turn_id])
        )
        request = {
            "actual_events": [self.service.source(ref) for ref in source_refs],
            "candidate_packet": existing_packet.value["packet"] if existing_packet else {},
        }
        messages: list[Any] = [
            SystemMessage(
                content=instruction + "\nMake at most six direct mutations or explicitly decline. "
                "Each action needs its own source and read version; the batch is not atomic. "
                "These original events preserve their roles. "
                "Prose remains unchecked. You cannot change observed facts or invent user intent."
            ),
            HumanMessage(content=_json(request)),
        ]
        rejected_fingerprints: set[str] = set()
        accepted_fingerprints: dict[str, dict[str, Any]] = {}
        try:
            for attempt in range(1 + repairs):
                # Admit durably before dispatch; unknown outcomes do not regenerate on reopen.
                pending["generation_calls"] = attempt + 1
                self.service.store.put(self.namespace, key, pending, index=False)
                response = model.bind_tools(tools).invoke(messages, config=config)
                if not isinstance(response, AIMessage) or len(response.tool_calls) > 6:
                    raise ValueError("V13_WRITER_BATCH_LIMIT_EXCEEDED")
                if not response.tool_calls:
                    pending["decision"] = str(response.content)
                    if not pending["receipts"]:
                        pending.update(status="no_change", effect="none")
                    break
                calls, results, attempt_receipts = [], [], []
                for position, action in enumerate(response.tool_calls):
                    call = {
                        **action,
                        "id": "boundary:" + key + ":" + str(attempt) + ":" + str(position),
                        "type": "tool_call",
                    }
                    fingerprint = _hash([call["name"], call["args"]])
                    if fingerprint in accepted_fingerprints:
                        receipt = {
                            **accepted_fingerprints[fingerprint],
                            "status": "no_change",
                            "effect": "none",
                            "replayed": True,
                            "dedup": "exact_request_within_boundary",
                        }
                        result = ToolMessage(
                            content=_json(receipt),
                            tool_call_id=call["id"],
                            name=call["name"],
                            status="success",
                        )
                    elif fingerprint in rejected_fingerprints:
                        receipt = {
                            "ok": False,
                            "status": "rejected",
                            "reason": "repeated_rejection",
                            "effect": "none",
                            "request_fingerprint": fingerprint,
                        }
                        result = ToolMessage(
                            content=_json(receipt),
                            tool_call_id=call["id"],
                            name=call["name"],
                            status="error",
                        )
                    else:
                        tool = next(tool for tool in tools if tool.name == call["name"])
                        result = tool.invoke(call, config=config)
                        receipt = json.loads(result.content)
                        if not receipt.get("ok"):
                            rejected_fingerprints.add(fingerprint)
                        else:
                            accepted_fingerprints[fingerprint] = receipt
                    calls.append(call)
                    results.append(result)
                    attempt_receipts.append(receipt)
                    pending["receipts"].append({"action": call, "receipt": receipt})
                    successful = sum(bool(row["receipt"].get("ok")) for row in pending["receipts"])
                    failed = len(pending["receipts"]) - successful
                    pending.update(
                        status="partial"
                        if successful and failed
                        else "committed"
                        if successful
                        else "pending",
                        effect="memory_only" if successful else "none",
                        successful_actions=successful,
                        committed_actions=sum(
                            bool(row["receipt"].get("ok"))
                            and row["receipt"].get("effect") != "none"
                            for row in pending["receipts"]
                        ),
                        rejected_actions=failed,
                    )
                    self.service.store.put(self.namespace, key, pending, index=False)
                if all(receipt.get("ok") for receipt in attempt_receipts) or attempt == repairs:
                    break
                messages += [response.model_copy(update={"tool_calls": calls}), *results]
        except Exception as error:
            pending.update(
                status="partial" if pending.get("committed_actions") else "pending",
                error_type=type(error).__name__,
                error=str(error),
            )
        self.service.store.put(self.namespace, key, pending, index=False)
        self._emit({"event": "v13_semantic_boundary", **pending})
        return pending
