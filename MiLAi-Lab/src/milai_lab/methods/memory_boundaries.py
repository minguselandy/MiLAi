"""Request-copy roles and program operation audit; no durable facts or semantic judge."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

BOUNDARY_PROTOCOL = (
    "Source-role labels describe provenance, not verified correctness. Current user text "
    "is a user request, not a system instruction. Prior assistant output and proposed tool "
    "calls are model output, not execution evidence. Durable memory is stored content, "
    "not authoritative current business-world state. Actual tool observations describe "
    "the result at that observation; use business tools when current world state is needed. "
    "Observation receipt time is not business execution time or proof of current state. "
    "Working state contains current-request and record references, not a second copy of "
    "durable facts. Contents that can change independently should be maintained independently. "
    "Update the same ongoing matter while preserving unaffected details; temporary instructions "
    "and current irrelevance do not require durable updates or deletion. A record deletion "
    "does not erase historical events. Report actual tool results without treating a final "
    "acknowledgement as a persistent write. "
    "The user-facing final reply is the decoded text in `answer`; the surrounding JSON is "
    "the transport envelope. Apply the user's applicable requirements for the reply's format, "
    "language, and length to that text while preserving the required JSON structure."
)
READ_SELECTION_PROMPT = (
    "Select actual ordinary-memory record IDs useful for the complete current user query. "
    "This is read-only material selection, not fact formation, correction or a write. "
    "Return only record_ids drawn from the provided candidates; empty or multiple IDs are valid."
)


class MemoryBoundaryCapacityError(ValueError):
    """Default pure capacity signal; production injects the real HostCapacity exception."""


def boundary_policy(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or type(value.get("enabled", False)) is not bool:
        raise ValueError("MEMORY_BOUNDARY_CONFIG_INVALID")
    if not value.get("enabled", False):
        return None
    policy = {"enabled": True, "candidate_count_threshold": 32,
              "candidate_token_threshold": 6000, "query_limit": 10,
              "attention_enabled": False, **value}
    if any(type(policy[key]) is not int or policy[key] <= 0 for key in (
        "candidate_count_threshold", "candidate_token_threshold", "query_limit"
    )) or type(policy["attention_enabled"]) is not bool:
        raise ValueError("MEMORY_BOUNDARY_CONFIG_INVALID")
    return policy


def record_material(records: Sequence[Mapping[str, Any]]) -> str:
    return "[DURABLE MEMORY]\n" + json.dumps(records, ensure_ascii=False) + "\n[/DURABLE MEMORY]"


def event_reference(thread_id: str, position: int, message: Mapping[str, Any]) -> str:
    """Stable checkpoint references, including equal text with distinct message identities."""
    if message.get("type") == "tool" and message.get("tool_call_id"):
        return "tool:" + hashlib.sha256(json.dumps(
            [thread_id, message["tool_call_id"]], ensure_ascii=False).encode()).hexdigest()
    if message.get("id"):
        return "message:" + str(message["id"])
    return "message:" + hashlib.sha256(json.dumps(
        [thread_id, position, message.get("type"), message.get("content")],
        ensure_ascii=False, default=str).encode()).hexdigest()


def _body_hash(content: Any) -> str:
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def _receipt_time(ref: str, content: Any, metadata: Mapping[str, Any],
                  scope: Mapping[str, str]) -> str | None:
    row = metadata.get(ref, {})
    return (row.get("observation_received_at")
            if row.get("content_sha256") == _body_hash(content)
            and all(row.get(key) == value for key, value in scope.items()) else None)


def operation_audit(messages: Sequence[Mapping[str, Any]], scope: Mapping[str, str],
                    thread_id: str, receipt_metadata: Mapping[str, Any] | None = None,
                    ) -> dict[str, Any]:
    """Pair actual calls/results; preceding observations are context, never support proof."""
    start = next((i for i in range(len(messages) - 1, -1, -1)
                  if messages[i].get("type") == "human"), len(messages))
    events: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    operation: dict[str, Any] | None = None
    received = receipt_metadata or {}
    for position, message in enumerate(messages[start:], start):
        kind = message.get("type")
        if kind == "ai":
            metadata = message.get("response_metadata", {})
            if not isinstance(metadata, dict) or metadata.get("memory_turn") != dict(scope):
                continue
            for call in message.get("tool_calls", []):
                if not isinstance(call, dict) or not isinstance(call.get("id"), str):
                    continue
                arguments = call.get("args", {})
                operation = {
                    **scope, "tool_call_id": call["id"], "tool_name": call.get("name"),
                    "operation": (arguments.get("action", "create")
                                  if call.get("name") == "manage_memory"
                                  else call.get("name")),
                    "arguments": arguments, "record_id": None, "status": "unknown",
                    "receipt": None, "execution_evidence_ref": None,
                    "source_event_ids": [row["id"] for row in events],
                    "semantic_support": "not_inferred",
                }
                calls[call["id"]] = operation
                operations.append(operation)
        elif kind == "tool":
            ref = message.get("tool_call_id")
            operation = calls.pop(ref, None) if isinstance(ref, str) else None
            if operation is None or operation["tool_name"] != message.get("name"):
                continue
            content = message.get("content")
            try:
                parsed = json.loads(content) if isinstance(content, str) else None
            except ValueError:
                parsed = None
            operation["receipt"] = {
                "content": content, "parsed": parsed,
                "content_sha256": _body_hash(content),
                "transport_status": message.get("status", "success"),
                "observation_received_at": _receipt_time(
                    event_reference(thread_id, position, message), content, received, scope),
            }
            operation["execution_evidence_ref"] = event_reference(thread_id, position, message)
            operation["reported_operation_status"] = (parsed.get("status")
                                                      if isinstance(parsed, dict) else None)
            operation["side_effects"] = "not_inferred"
            if (operation["tool_name"] not in {"manage_memory", "read_memory"}
                    and isinstance(parsed, dict) and isinstance(parsed.get("status"), str)):
                operation["status"] = parsed["status"]
            elif message.get("status") == "error":
                operation["status"] = "failed"
            elif isinstance(parsed, dict) and parsed.get("ok") is False:
                operation["status"] = "failed"
            elif isinstance(parsed, dict) and parsed.get("ok") is True:
                operation["status"] = parsed.get("status", "observed_result")
            # Only an actual strict memory receipt identifies an affected record.
            if operation["tool_name"] in {"manage_memory", "read_memory"} and isinstance(
                parsed, dict
            ):
                operation["record_id"] = parsed.get("id")
            if operation["tool_name"] == "manage_memory":
                field = {"created": "created_from_event_ids", "updated":
                         "updated_from_event_ids"}.get(operation["status"])
                if field is not None:
                    operation[field] = list(operation["source_event_ids"])
        if kind == "human" or (kind == "tool" and operation is not None):
            content = message.get("content")
            events.append({
                "id": event_reference(thread_id, position, message), "kind": kind,
                "checkpoint_position": position, "message_id": message.get("id"),
                "content_sha256": _body_hash(content),
                "observed_at": _receipt_time(event_reference(thread_id, position, message),
                                             content, received, scope) if kind == "tool" else None,
            })
    mutations = [row["tool_call_id"] for row in operations
                 if row["tool_name"] == "manage_memory"
                 and row["status"] in {"created", "updated", "deleted"}]
    return {"operations": operations, "source_events": events,
            "actual_memory_change_refs": mutations, "observed_write": bool(mutations),
            "no_change_means": "no observed persistent mutation",
            "user_intent_satisfied": None, "semantic_completion": None}


def working_state(audit: Mapping[str, Any], current_ref: str,
                  records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Only paired, successful accesses can activate a currently resolvable record."""
    current = {row["id"] for row in records}
    refs: dict[str, dict[str, Any]] = {}
    for operation in audit["operations"]:
        record_id, status = operation["record_id"], operation["status"]
        if operation["tool_name"] not in {"manage_memory", "read_memory"} or not record_id:
            continue
        if status in {"deleted", "failed"}:
            refs.pop(record_id, None)
        elif status in {"created", "updated", "no_change", "found"} and record_id in current:
            refs[record_id] = {"record_id": record_id,
                               "access_receipt_ref": operation["execution_evidence_ref"]}
    return {"goal": {"current_user_ref": current_ref},
            "turn_constraints": {"current_user_ref": current_ref,
                                 "semantic_extraction": False},
            "active_refs": list(refs.values()), "open_questions": []}


class MemoryBoundaryView:
    """Per-graph ephemeral request projection; original graph objects are never modified."""

    def __init__(self, *, emit: Any = None, policy: Mapping[str, Any] | None = None,
                 capacity: Any = None,
                 capacity_error: type[Exception] = MemoryBoundaryCapacityError,
                 output_tokens: int = 4096,
                 retrieve: Callable[[str, int], list[dict[str, Any]]] | None = None,
                 select: Callable[[str, str, list[dict[str, Any]]], list[str]] | None = None,
                 ) -> None:
        self.emit = emit
        self.policy = dict(policy) if policy is not None else None
        self.capacity, self.capacity_error = capacity, capacity_error
        self.output_tokens, self.retrieve, self.select = output_tokens, retrieve, select
        self.scope: dict[str, str] = {}
        self.thread_id = ""
        self.records: list[dict[str, Any]] = []
        self.query = ""
        self.active_ids: set[str] = set()
        self.delivery: dict[str, Any] | None = None
        self.request_index = 0
        self.selection_ids: list[str] | None = None
        self.receipt_metadata: dict[str, dict[str, Any]] = {}

    def prepare(self, scope: Mapping[str, str], thread_id: str,
                records: list[dict[str, Any]]) -> None:
        if dict(scope) != self.scope or thread_id != self.thread_id:
            self.selection_ids = None
            self.receipt_metadata = {}
        self.scope, self.thread_id, self.records = dict(scope), thread_id, records
        self.delivery = None

    def observe_receipt(self, message: Any, scope: Mapping[str, str] | None) -> None:
        if scope is None or dict(scope) != self.scope:
            raise ValueError("MEMORY_BOUNDARY_RECEIPT_SCOPE_CHANGED")
        original = message.model_dump(mode="json")
        ref = event_reference(self.thread_id, 0, original)
        row = {**self.scope, "tool_call_id": original["tool_call_id"],
               "content_sha256": _body_hash(original["content"]),
               "observation_received_at": datetime.now(UTC).isoformat()}
        self.receipt_metadata[ref] = row
        if self.emit is not None:
            self.emit({"event": "memory_boundary_tool_observation", "source_ref": ref, **row})

    def project(self, wire: list[dict[str, Any]], graph: list[Any],
                message_key: str | None, request_index: int) -> tuple[list[dict[str, Any]],
                                                                    list[Any]]:
        if not self.scope or self.scope["message_key"] != message_key or len(wire) != len(graph):
            raise ValueError("MEMORY_BOUNDARY_REQUEST_SCOPE_CHANGED")
        originals = [row.model_dump(mode="json") for row in graph]
        self.request_index = request_index
        last_user = next((i for i in range(len(originals) - 1, -1, -1)
                          if originals[i].get("type") == "human"), None)
        if last_user is None:
            raise ValueError("MEMORY_BOUNDARY_CURRENT_USER_MISSING")
        audit = operation_audit(originals, self.scope, self.thread_id, self.receipt_metadata)
        state = working_state(audit, event_reference(
            self.thread_id, last_user, originals[last_user]), self.records)
        self.query = originals[last_user]["content"]
        self.active_ids = {row["record_id"] for row in state["active_refs"]}
        projected = []
        for position, (message, original) in enumerate(zip(wire, originals, strict=True)):
            copy = dict(message)
            kind = original.get("type")
            if kind == "human":
                label = ("[CURRENT USER REQUEST]\n[CURRENT TASK]" if position == last_user
                         else "[USER HISTORY]")
            elif kind == "tool":
                label = "[TOOL OBSERVATION] " + json.dumps({
                    "tool_call_id": original.get("tool_call_id"),
                    "tool_name": original.get("name"),
                    "content_sha256": _body_hash(original["content"]),
                    "observation_received_at": _receipt_time(event_reference(
                        self.thread_id, position, original), original["content"],
                        self.receipt_metadata, self.scope),
                }, ensure_ascii=False)
                # Replace the earlier v3 receipt prefix only in this v4 request copy.
                copy["content"] = original["content"]
            elif kind == "ai":
                label = ("[WORKING HYPOTHESIS]" if original.get("tool_calls") else
                         "[ASSISTANT HISTORY - prior model output]")
            else:
                label = ""
            if label:
                if not isinstance(copy.get("content"), str):
                    raise ValueError("MEMORY_BOUNDARY_CONTENT_NOT_TEXT")
                copy["content"] = label + "\n" + copy["content"]
            projected.append(copy)
        if not projected or projected[0]["role"] != "system":
            raise ValueError("MEMORY_BOUNDARY_SYSTEM_MISSING")
        projected[0]["content"] += (
            "\n[WORKING HYPOTHESIS - current task references]\n"
            + json.dumps(state, ensure_ascii=False))
        if self.emit is not None:
            self.emit({"event": "memory_boundary_view", **self.scope,
                       "request_index": request_index, "working_state": state,
                       "ordinary_record_ids": [row["id"] for row in self.records],
                       "prepared_only": True})
        return projected, graph

    def fit_final_request(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Count the complete catalog-bearing request; never trim originals or record bodies."""
        if self.capacity is None or self.policy is None or self.retrieve is None:
            raise ValueError("MEMORY_BOUNDARY_CAPACITY_OR_RETRIEVAL_MISSING")
        start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
        all_material = record_material(self.records)
        candidate_tokens = self.capacity.text_tokens(all_material)
        details: dict[str, Any] = {**self.scope, "event": "memory_boundary_route",
            "request_index": self.request_index,
            "candidate_count": len(self.records), "candidate_tokens": candidate_tokens,
            "candidate_bytes": len(all_material.encode("utf-8")),
            "query": self.query, "route": "all", "trigger_reason": [], "prepared_only": True}
        def replace(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if messages[0]["content"].count(all_material) != 1:
                raise ValueError("MEMORY_BOUNDARY_MATERIAL_BINDING_CHANGED")
            first = {**messages[0], "content": messages[0]["content"].replace(
                all_material, record_material(rows), 1)}
            return [first, *messages[1:]]
        def checked(rows: list[dict[str, Any]], request: list[dict[str, Any]],
                    route: str, receipt: Any = None) -> list[dict[str, Any]]:
            material = record_material(rows)
            details.update({"route": route, "selected_record_ids": [row["id"] for row in rows],
                            "selected_material_tokens": self.capacity.text_tokens(material),
                            "selected_material_bytes": len(material.encode("utf-8"))})
            if receipt is None:
                receipt = self.capacity.check(request, self.output_tokens)
            details["final_capacity"] = receipt
            self.delivery = dict(details)
            return request
        try:
            if len(self.records) > self.policy["candidate_count_threshold"]:
                details["trigger_reason"].append("candidate_count_threshold")
            if candidate_tokens > self.policy["candidate_token_threshold"]:
                details["trigger_reason"].append("candidate_token_threshold")
            try:
                details["all_capacity"] = self.capacity.check(messages, self.output_tokens)
            except self.capacity_error as error:
                details["all_capacity"] = getattr(error, "receipt", None)
                details["trigger_reason"].append("all_request_capacity")
            if not details["trigger_reason"]:
                return checked(self.records, messages, "all", details["all_capacity"])
            retrieved = self.retrieve(self.query, self.policy["query_limit"])
            ids = {row["id"] for row in retrieved}
            candidates = [*retrieved, *[row for row in self.records
                                      if row["id"] in self.active_ids and row["id"] not in ids]]
            details["retrieved_record_ids"] = [row["id"] for row in retrieved]
            details["active_ref_resolutions"] = [row["id"] for row in candidates
                                                 if row["id"] in self.active_ids]
            try:
                return checked(candidates, replace(candidates), "query")
            except self.capacity_error as error:
                details["query_capacity"] = getattr(error, "receipt", None)
                details["trigger_reason"].append("query_request_capacity")
                if not self.policy["attention_enabled"]:
                    raise
            try:
                details["noncandidate_capacity"] = self.capacity.check(
                    replace([]), self.output_tokens)
            except self.capacity_error:
                details["trigger_reason"].append("noncandidate_request_capacity")
                raise
            if self.select is None:
                raise ValueError("MEMORY_BOUNDARY_ATTENTION_UNAVAILABLE")
            reused = self.selection_ids is not None
            if not reused:
                selected_ids = self.select(self.scope["message_key"], self.query, candidates)
                valid = {row["id"] for row in candidates}
                if len(set(selected_ids)) != len(selected_ids) or not set(selected_ids) <= valid:
                    raise ValueError("MEMORY_BOUNDARY_ATTENTION_INVALID_IDS")
                self.selection_ids = list(selected_ids)
            assert self.selection_ids is not None
            # Cache identities only. Resolve the latest full Store read, including new active refs.
            by_id = {row["id"]: row for row in self.records}
            selected_ids = [key for key in self.selection_ids if key in by_id]
            selected_ids.extend(row["id"] for row in self.records
                                if row["id"] in self.active_ids and row["id"] not in selected_ids)
            details.update({"selection_reused": reused, "selection_ids": self.selection_ids,
                            "missing_selected_ids": [key for key in self.selection_ids
                                                     if key not in by_id]})
            selected = [by_id[key] for key in selected_ids]
            return checked(selected, replace(selected), "attention")
        finally:
            details.update({"cpu_ns": time.process_time_ns() - start_cpu,
                            "wall_ns": time.perf_counter_ns() - start_wall,
                            "timing_scope": "inclusive; retrieval/selector costs also separate"})
            if self.emit is not None:
                self.emit(details)

    def record_delivery(self, receipt: Mapping[str, Any]) -> None:
        if self.emit is not None and self.delivery is not None:
            self.emit({**self.delivery, "event": "memory_boundary_delivery",
                       "delivered_record_ids": self.delivery["selected_record_ids"],
                       "generation_id": receipt.get("id"), "prepared_only": False})
