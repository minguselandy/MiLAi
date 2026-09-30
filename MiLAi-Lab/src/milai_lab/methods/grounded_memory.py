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
    "empty": "empty material",
    "trimming": "whole fields then explicit text/candidate truncation; retain conflicts",
    "unit_order": "selected records, selected object fields, selected source ranges",
    "candidate_limit": "six distinct record/object identities; source ranges are supporting leaves",
    "extra_query": "search_memory executes each explicit query and charges independently",
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
        observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if representation not in {"raw", "receipt", "milai"}:
            raise ValueError("V13_PACKET_POLICY_INVALID")
        self.service, self.token_count, self.embeddings = service, token_count, embeddings
        self.representation, self.observer = representation, observer
        self.namespace = (*service.namespace, "v13_2_recipe")
        self.policy = {
            **POLICY,
            "representation": representation,
            "candidate_contract": service.candidate_contract,
            "source_backlinks": service.source_backlinks,
        }

    def _emit(self, value: dict[str, Any]) -> None:
        if self.observer is not None:
            self.observer(value)

    def _record(self, row: dict[str, Any]) -> dict[str, Any]:
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
        previous = self.service.store.get(self.namespace, "raw_index")
        chunks = [vars(row) for row in raw_chunks(documents)]
        if not chunks:
            return [], "empty"
        entries = [IndexEntry(row["id"], row["source_id"], row["content"]) for row in chunks]
        lexical = _bm25_scores(entries, query)
        degradation = "dense_unavailable"
        if self.embeddings is not None:
            try:
                index = raw_index(
                    documents,
                    self.embeddings.embed_documents,
                    previous.value if previous is not None else None,
                )
                self.service.store.put(self.namespace, "raw_index", index, index=False)
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
        self, ranked: list[dict[str, Any]], observations: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Freeze identities at first query; dirty refresh cannot introduce unrelated records."""
        selected = []
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
            for record in records:
                version = record.get("value") or {}
                refs.update(version.get("source_refs", [version.get("source_ref")]))
            fields = [
                [obj["object_ref"]["id"], name]
                for obj in observations["objects"]
                for name, field in obj["fields"].items()
                if any(event["source_event_id"] in refs for event in field["history"])
            ]
            selected.append(
                {
                    **row,
                    "record_ids": [record["id"] for record in records if record["ok"]],
                    "object_fields": fields,
                }
            )
        return selected

    def _units(
        self, selected: list[dict[str, Any]], observations: dict[str, Any]
    ) -> list[dict[str, Any]]:
        units = []
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
                row = self.service.read(memory_id)
                if row["ok"]:
                    units.append(
                        {
                            "unit_id": "record:" + memory_id,
                            "type": "record",
                            "record": self._record(row),
                        }
                    )
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
        priority = {"record": 0, "observation_field": 1, "source": 2}
        return sorted(units, key=lambda row: priority[row["type"]])

    def _packet(self, units: list[dict[str, Any]], revision: str) -> tuple[dict[str, Any], str]:
        packet = {
            "ok": True,
            "schema": "bounded_evidence_v1",
            "owner": self.service.owner,
            "bank_revision": revision,
            "items": units,
            "current_verified": False,
        }
        identities = {
            "record:" + unit["record"]["id"] for unit in units if unit["type"] == "record"
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
        self, units: list[dict[str, Any]], revision: str
    ) -> tuple[list[dict[str, Any]], list[str]]:
        chosen: list[dict[str, Any]] = []
        omitted, delivered = [], set()
        candidates: set[str] = set()
        for unit in units:
            key = unit["unit_id"]
            if key in delivered:
                continue
            identity = (
                "record:" + unit["record"]["id"]
                if unit["type"] == "record"
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
            if self.token_count(self._packet([*chosen, value], revision)[1]) > POLICY["budget"]:
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
                            self.token_count(self._packet([*chosen, value], revision)[1])
                            <= POLICY["budget"]
                        ):
                            low = middle
                        else:
                            high = middle - 1
                    target[field] = body[:low]
                    if field == "excerpt":
                        value["range"][1] = value["range"][0] + low
            if self.token_count(self._packet([*chosen, value], revision)[1]) > POLICY["budget"]:
                omitted.append(key)
                continue
            chosen.append(value)
            delivered.add(key)  # only actually delivered cards are deduplicated
            if identity is not None:
                candidates.add(identity)
        return chosen, omitted

    def prepare_context(
        self,
        public_request: str,
        *,
        owner: str,
        session: str,
        turn_id: str,
        explicit_query: str | None = None,
    ) -> dict[str, Any]:
        if owner != self.service.owner:
            raise ValueError("V13_PACKET_OWNER_MISMATCH")
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
        cached = self.service.store.get(self.namespace, key)
        documents, observations, revision = self._snapshot(current_source)
        if cached is not None and explicit_query is None:
            state = cached.value
            if state["query_hash"] != _hash(public_request) or state["policy"] != self.policy:
                raise ValueError("V13_PACKET_TURN_CHANGED")
            if state["bank_revision"] == revision:
                result = {**state, "reused": True, "retrieval_calls": 0}
                self._emit(
                    {"event": "v13_evidence_packet_reused", "packet_hash": state["packet_hash"]}
                )
                return result
            selected, retrieval, calls = state["selected"], state["retrieval"], 0
        else:
            ranked, retrieval = self._retrieve(documents, query)
            selected, calls = self._select(ranked, observations), 1
        chosen, omitted = self._fit(self._units(selected, observations), revision)
        packet, material = self._packet(chosen, revision)
        if not chosen:
            material = ""
        state = {
            "policy": self.policy,
            "query_hash": _hash(query),
            "query_kind": "ordinary_public" if explicit_query is None else "explicit_additional",
            "actual_public_request_hash": _hash(public_request),
            "bank_revision": revision,
            "packet": packet,
            "packet_hash": packet["packet_hash"],
            "material": material,
            "material_tokens": self.token_count(material),
            "selected": selected,
            "omitted_ids": omitted,
            "retrieval": retrieval,
            "retrieval_calls": calls,
            "reused": False,
            "wall_ns": time.perf_counter_ns() - wall,
            "cpu_ns": time.process_time_ns() - cpu,
            "measurement": "whole source/record/fact snapshot scans; Store IO not fully counted",
        }
        self.service.store.put(self.namespace, key, state, index=False)
        self.service.store.put(
            self.namespace, "last_packet:" + _hash([session, turn_id]), {"key": key}, index=False
        )
        self._emit({"event": "v13_evidence_packet", **state})
        return state

    def _public_source(self, config: RunnableConfig) -> tuple[dict[str, Any], dict[str, Any]]:
        cfg = config["configurable"]
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

    def hook(self, base_system: str) -> Callable[..., dict[str, Any]]:
        def prepare(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
            cfg = config["configurable"]
            human = next(
                row for row in reversed(state["messages"]) if isinstance(row, HumanMessage)
            )
            packet = self.prepare_context(
                str(human.content),
                owner=cfg["user_id"],
                session=cfg["v13_session"],
                turn_id=str(human.id),
            )
            return {
                "llm_input_messages": [
                    SystemMessage(
                        content=base_system
                        + ("\n" + packet["material"] if packet["material"] else "")
                    ),
                    *state["messages"],
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
