"""Functional opt-in tools over one MemoryService; no model or business dispatch.

Ordinary context is cached per actual public message. Explicit reads consume a
durable per-message allowance, including failed attempts. Every cursor resolves
its issued snapshot. Stored logs remain audit evidence after visibility revocation.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from typing import Annotated, Any, Literal, cast

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from milai_lab.memory.functional_state import (
    FunctionalIntegrityError,
    FunctionalOperationError,
    FunctionalRejection,
    canonical,
    digest,
    fragment_support,
    namespace,
    note_exposure,
    scope_leaves,
)
from milai_lab.memory.service import MemoryService, _lexical_tokens


class SavedAssertion(BaseModel):
    """One supported assertion, with its applicability expressed in the same body."""

    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(description=(
        "Complete supported assertion, including who, which occurrence, time, conditions, "
        "exceptions and uncertainty. Preserve restrictive source wording in this body."))
    fragment_handles: list[str]
    tool_call_id: Annotated[str, InjectedToolCallId]


class FieldChange(BaseModel):
    """One proposed value and its explicitly selected evidence, not a semantic verdict."""

    model_config = ConfigDict(extra="forbid", strict=True)
    field: str = Field(description="content/kind/basis or scope.KEY[.KEY]")
    op: Literal["set", "remove"]
    value: Any = Field(default=None, description=(
        "Required for set; omit for remove. Preserve the assertion's exact subject, "
        "occurrence, time limits, negation and uncertainty. Scope values describe only "
        "explicit applicability boundaries, not inferred project labels or summary categories."))
    fragment_handles: list[str] = Field(
        description="Issued fragments supporting this NEW value or removal; not its old value")


class FunctionalMemory:
    def __init__(
        self,
        service: MemoryService,
        token_count: Callable[[str], int],
        *,
        read_limit: int = 3,
        material_limit: int = 8192,
        fragment_chars: int = 1200,
        retrieval_candidates: list[dict[str, Any]] | None = None,
        formation_interface: str = "content_and_scope_v1",
    ) -> None:
        if service.functional_contract != "functional_v1":
            raise FunctionalRejection("V13_5_FUNCTIONAL_CONTRACT_REQUIRED")
        if any(type(v) is not int or v < 1 for v in (read_limit, material_limit, fragment_chars)):
            raise FunctionalRejection("V13_5_FUNCTIONAL_LIMIT_INVALID")
        self.service, self.token_count = service, token_count
        if formation_interface not in {"content_and_scope_v1", "unified_assertion_v1"}:
            raise FunctionalRejection("V13_5_FORMATION_INTERFACE_INVALID")
        self.formation_interface = formation_interface
        self.read_limit, self.material_limit, self.fragment_chars = (
            read_limit,
            material_limit,
            fragment_chars,
        )
        self.policy = {
            "read_limit": read_limit,
            "material_limit": material_limit,
            "fragment_chars": fragment_chars,
            "retrieval_candidates_sha256": digest(retrieval_candidates),
        }
        if formation_interface != "content_and_scope_v1":
            self.policy["formation_interface"] = formation_interface
        self.retrieval_candidates = copy.deepcopy(retrieval_candidates)
        if retrieval_candidates is not None:
            for row in retrieval_candidates:
                required = {"source_ref", "start", "end", "retrieval_score"}
                hashes = {"source_sha256", "body_text_sha256", "span_sha256"}
                if (
                    not isinstance(row, dict)
                    or not required <= set(row)
                    or set(row) - required - hashes
                    or type(row["retrieval_score"]) not in {int, float}
                    or not math.isfinite(row["retrieval_score"])
                ):
                    raise FunctionalRejection("V13_5_RETRIEVAL_CANDIDATE_INVALID")
                fragment = service.source_fragment_range(
                    row["source_ref"], row["start"], row["end"])
                if any(row[key] != fragment[key] for key in hashes.intersection(row)):
                    raise FunctionalRejection("V13_5_RETRIEVAL_CANDIDATE_HASH_MISMATCH")

    @property
    def forget_epoch(self) -> int:
        return self.service.forget_epoch

    def forgotten_source_refs(self) -> list[str]:
        return self.service.forgotten_source_refs()

    def _binding(self, config: RunnableConfig) -> dict[str, Any]:
        cfg = config.get("configurable", {})
        if cfg.get("user_id") != self.service.owner:
            raise FunctionalRejection("V13_5_OWNER_MISMATCH")
        bound = self.service.public_turn(
            str(cfg.get("v13_session", "")),
            message_id=cfg.get("v13_turn_id"),
            config_sha256=cfg.get("v13_support_config_sha256"),
        )
        if bound is None:
            raise FunctionalRejection("V13_5_ACTUAL_PUBLIC_TURN_REQUIRED")
        return bound

    def _record_units(
        self,
        row: dict[str, Any],
        view: str = "current_at_snapshot",
    ) -> list[dict[str, Any]]:
        if not row.get("ok") or not row.get("candidate_handle"):
            return []
        version = row["value"]
        body = version["content"]
        return [
            {
                "type": "record",
                "record_id": row["id"],
                "read_handle": row["candidate_handle"],
                "revision": version["revision"],
                "version_sha256": digest(version),
                "kind": version["kind"],
                "scope": version["scope"],
                "basis": version["basis"],
                "source_refs": version.get("source_refs", [version["source_ref"]]),
                "content": body[start : start + self.fragment_chars],
                "content_range": [start, min(start + self.fragment_chars, len(body))],
                "content_total_codepoints": len(body),
                "semantic_support": "unchecked",
                "version_view": view,
                "retracted": version.get("retracted", False),
            }
            for start in range(0, max(1, len(body)), self.fragment_chars)
        ]

    def _deduplicate(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Subtract only already delivered intervals of this exact Source/body version."""
        seen: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
        result = []
        for unit in units:
            if unit["type"] != "fragment":
                result.append(unit)
                continue
            identity = tuple(
                unit[key] for key in ("source_ref", "source_sha256", "body_text_sha256")
            )
            previous = seen.setdefault(identity, [])
            residual = [(unit["start"], unit["end"])]
            for left, right in previous:
                residual = [
                    (a, b)
                    for start, end in residual
                    for a, b in ((start, min(end, left)), (max(start, right), end))
                    if a < b
                ]
            for start, end in residual:
                for offset in range(start, end, self.fragment_chars):
                    result.append(
                        {
                            "type": "fragment",
                            **self.service.source_fragment_range(
                                unit["source_ref"], offset, min(end, offset + self.fragment_chars)
                            ),
                        }
                    )
            previous.append((unit["start"], unit["end"]))
        return result

    def _search_units(self, query: str, current_ref: str | None = None) -> list[dict[str, Any]]:
        if digest(self.retrieval_candidates) != self.policy["retrieval_candidates_sha256"]:
            raise FunctionalIntegrityError("V13_5_RETRIEVAL_CANDIDATES_CHANGED")
        current = (
            [
                {"type": "fragment", **fragment}
                for fragment in self.service.source_fragments(
                    current_ref, max_chars=self.fragment_chars
                )
            ]
            if current_ref and self.service.source(current_ref) is not None
            else []
        )
        if self.retrieval_candidates is not None:
            # Trusted supplied retrieval ranges are the entire controlled candidate pool.
            candidates = sorted(
                enumerate(self.retrieval_candidates),
                key=lambda pair: (-pair[1]["retrieval_score"], pair[0]),
            )
            fragments = [
                {
                    "type": "fragment",
                    **self.service.source_fragment_range(
                        row["source_ref"], row["start"], row["end"]
                    ),
                }
                for _, row in candidates
                if self.service.source(row["source_ref"]) is not None
            ]
            return self._deduplicate(current + fragments)
        result = self.service.search(query, limit=100, include_raw=True)
        units: list[dict[str, Any]] = []
        refs = []
        for notice in result.get("withdrawals", []):
            units.append({"type": "withdrawal", "content": "", **notice})
            refs.extend(notice["source_refs"])
        for row in result["records"]:
            units.extend(self._record_units(row))
            if row.get("ok"):
                refs.extend(row["value"].get("source_refs", [row["value"]["source_ref"]]))
        refs.extend(event["event_id"] for event in result["raw_events"])
        for ref in dict.fromkeys(refs):
            if ref != current_ref and self.service.source(ref) is not None:
                units.extend(
                    {"type": "fragment", **fragment}
                    for fragment in self.service.source_fragments(
                        ref, max_chars=self.fragment_chars
                    )
                )
        terms = set(_lexical_tokens(query))
        # Score actual body paragraphs, never opaque IDs, dates or metadata headers.
        # Stable ties retain public source/paragraph order. Full groups remain reachable.
        units.sort(
            key=lambda unit: (
                unit["type"] != "withdrawal",
                -len(
                    terms.intersection(_lexical_tokens(unit["content"], include_cjk_unigrams=True))
                ),
            )
        )
        return self._deduplicate(current + units)

    def _snapshot(self, binding: dict[str, Any], items: list[dict[str, Any]], kind: str) -> str:
        items = [
            {**unit, "input_relation": ("current_request" if unit["source_ref"] ==
                                       binding["source_ref"] else "archived_source")}
            if unit["type"] == "fragment" else unit
            for unit in items
        ]
        payload = {
            "binding": binding,
            "policy": self.policy,
            "kind": kind,
            "forget_epoch": self.forget_epoch,
            "items": items,
        }
        key = "snapshot-" + digest(payload)
        prior = self.service.store.get(namespace(self.service), key)
        if prior is not None and prior.value != payload:
            raise FunctionalIntegrityError("V13_5_SNAPSHOT_COLLISION")
        if prior is None:
            self.service.store.put(namespace(self.service), key, payload, index=False)
        return key

    @staticmethod
    def _read_only_metadata(items: list[dict[str, Any]]) -> dict[str, Any]:
        record_ids = list(dict.fromkeys(
            unit["record_id"] for unit in items if unit["type"] == "record"
        ))
        return {
            "operation_effect": "read_only",
            "semantic_write_performed": False,
            "delivered_semantic_record_ids": record_ids,
            "delivered_semantic_record_count": len(record_ids),
            "delivered_semantic_record_units": sum(unit["type"] == "record" for unit in items),
            "delivered_raw_fragment_count": sum(unit["type"] == "fragment" for unit in items),
            "delivery_count_scope": "this_packet_items_only_not_owner_total_or_writes",
            "record_unit_scope": "a_unit_may_be_only_part_of_a_record_body",
            "formation_evidence": (
                "Successful save_memory/update_memory receipt; "
                "raw capture/search/read is not formation"
            ),
            "evidence_contract": {
                "fragment_verification": "exact_original_span_only_not_semantic_support",
                "new_values": "must_be_directly_supported_by_selected_fragments",
                "trigger_binding": "execution_attribution_not_field_evidence",
                "input_relation": "timing_only_not_automatic_evidence",
            },
        }

    def _page(self, key: str, start: int, binding: dict[str, Any]) -> dict[str, Any]:
        stored = self.service.store.get(namespace(self.service), key)
        if stored is None:
            raise FunctionalRejection("V13_5_SNAPSHOT_NOT_ISSUED_OR_CHANGED")
        if key != "snapshot-" + digest(stored.value):
            raise FunctionalIntegrityError("V13_5_SNAPSHOT_NOT_ISSUED_OR_CHANGED")
        value = stored.value
        if (
            value["binding"] != binding
            or value["policy"] != self.policy
            or value["forget_epoch"] != self.forget_epoch
        ):
            raise FunctionalIntegrityError("V13_5_SNAPSHOT_BINDING_CHANGED_OR_REVOKED")
        items = value["items"]
        if type(start) is not int or start < 0 or start > len(items):
            raise FunctionalRejection("V13_5_CURSOR_RANGE_INVALID")
        chosen: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        def packet(end: int) -> dict[str, Any]:
            return {
                "ok": True,
                "schema": "functional_material_v1",
                "snapshot_id": key,
                "kind": value["kind"],
                "items": chosen,
                "start": start,
                "delivered_units": len(chosen),
                "total_units": len(items),
                "omitted_units": len(items) - end + len(skipped),
                "skipped_units": skipped,
                "examined_units": end - start,
                "coverage_scope": "this_page_only_prior_page_omissions_remain",
                "next_cursor": key + ":" + str(end) if end < len(items) else None,
                "forget_epoch": self.forget_epoch,
                "material_limit": self.material_limit,
                "semantic_support": "unchecked",
                "business_authority": False,
                **self._read_only_metadata(chosen),
                "delivery_status": ("partial_with_omissions" if skipped else "partial")
                if end < len(items) else ("snapshot_end_with_omissions"
                                        if skipped else "complete_snapshot"),
                **({"status": "advanced_with_explicit_omission"} if skipped else {}),
                "source_groups": list(
                    {
                        u["source_ref"]: {
                            "source_ref": u["source_ref"],
                            "source_total_codepoints": u["source_total_codepoints"],
                            "read_source_available": True,
                            "dependency_scope": "same_public_source_only_no_inferred_relations",
                        }
                        for u in chosen
                        if u["type"] == "fragment"
                    }.values()
                ),
            }

        end = start
        for index, unit in enumerate(items[start:], start):
            if unit["type"] == "fragment":
                actual = self.service.source_fragment(unit["fragment_handle"])
                expected = {"type": "fragment", **actual, "input_relation": (
                    "current_request" if actual["source_ref"] == binding["source_ref"]
                    else "archived_source")}
                if expected != unit:
                    raise FunctionalIntegrityError("V13_5_SNAPSHOT_SOURCE_CHANGED")
            else:
                row = self.service.read(unit["record_id"], unit["revision"])
                if not row["ok"] or digest(row["value"]) != unit["version_sha256"]:
                    raise FunctionalIntegrityError("V13_5_SNAPSHOT_RECORD_UNAVAILABLE")
            chosen.append(unit)
            required = self.token_count(canonical(packet(index + 1)))
            if required > self.material_limit:
                chosen.pop()
                if chosen or skipped:
                    break
                # Never return a cursor stuck at the same impossible unit. The
                # original snapshot is unchanged and the omission is explicit.
                alternate = ([unit["source_ref"]] if unit["type"] == "fragment"
                             else unit.get("source_refs", []))
                skipped.append({
                    "unit_index": index, "type": unit["type"],
                    "reason": "unit_exceeds_material_limit",
                    "required_packet_tokens": required,
                    "snapshot_body_delivered": False,
                    "retry_same_unit_under_same_limit": False,
                    "alternative": {"tool": "read_source", "source_ref": alternate[0],
                                    "meaning": "original_support_not_semantic_record_body"}
                    if alternate else None,
                })
            end = index + 1
        result = packet(end)
        if self.token_count(canonical(result)) > self.material_limit:
            raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT")
        refs = [
            ref
            for unit in chosen
            for ref in ([unit["source_ref"]] if unit["type"] == "fragment" else unit["source_refs"])
        ]
        with self.service._locked():
            note_exposure(self.service, binding["source_ref"], refs)
        return result

    def context(
        self,
        session: str,
        turn_id: str,
        config_sha256: str,
        *,
        query: str | None = None,
    ) -> dict[str, Any]:
        ref = self.service.event_id(session, turn_id, "user")
        event = self.service.source(ref)
        if event is None:
            event = self.service.active_public_input(session, turn_id, config_sha256)
        if event is None or event["role"] != "user":
            raise FunctionalRejection("V13_5_CAPTURE_REQUIRED")
        actual_query = (
            event["content"] if isinstance(event["content"], str) else canonical(event["content"])
        )
        if query is not None and query != actual_query:
            raise FunctionalRejection("V13_5_PUBLIC_QUERY_CHANGED")
        prior = self.service.store.get(self.service.turns_namespace, digest([session, turn_id]))
        bound = self.service.bind_public_turn(
            session, turn_id, ref, config_sha256=config_sha256, phase="resume" if prior else "start"
        )
        key = "ordinary-" + digest([bound, self.policy, self.forget_epoch])
        cached = self.service.store.get(namespace(self.service), key)
        if cached is None:
            snapshot = self._snapshot(bound, self._search_units(actual_query, ref), "ordinary")
            self.service.store.put(
                namespace(self.service), key, {"snapshot": snapshot}, index=False
            )
        else:
            snapshot = cached.value["snapshot"]
        return self._page(snapshot, 0, bound)

    def _source_support(self, version: dict[str, Any]) -> dict[str, list[str]]:
        if "functional_support" in version:
            return {
                key: value["fragment_handles"]
                for key, value in version["functional_support"].items()
            }
        handles = [
            f["fragment_handle"]
            for ref in version.get("source_refs", [version["source_ref"]])
            for f in self.service.source_fragments(ref, max_chars=self.fragment_chars)
        ]
        return {
            key: handles for key in ("content", "kind", "basis", *scope_leaves(version["scope"]))
        }

    def _commit(self, session: str, operation_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.service.commit(session, operation_id, proposal)
        except Exception as error:
            raise FunctionalOperationError("semantic_commit", error) from error

    def save(
        self,
        config: RunnableConfig,
        operation_id: str,
        content: str,
        fragment_handles: list[str],
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bound = self._binding(config)
        requested = {
            "operation": "save",
            "content": content,
            "fragment_handles": fragment_handles,
            "scope": scope,
        }
        replay = self.service.replay_requested(bound["session"], operation_id, requested)
        if replay is not None:
            return replay
        if not isinstance(content, str) or not content.strip():
            raise FunctionalRejection("V13_5_NONEMPTY_CONTENT_REQUIRED")
        scope = self._scope(scope or {})
        support = fragment_support(self.service, fragment_handles)
        refs = support["source_refs"]
        roles = {self.service.source(ref)["role"] for ref in refs}  # type: ignore[index]
        basis = (
            "user_statement"
            if roles == {"user"}
            else "tool_observation"
            if roles == {"tool"}
            else "inference"
        )
        proposal = {
            "action": "create",
            "id": None,
            "expected_revision": 0,
            "content": content,
            "scope": scope,
            "kind": "semantic",
            "basis": basis,
            "fields": {},
            "object_ref": None,
            "source_ref": refs[0],
            "source_refs": refs,
            "field_support": {
                field: {"source_refs": refs} for field in ("content", "scope", "basis", "kind")
            },
            "functional_support": {
                field: fragment_handles
                for field in ("content", "kind", "basis", *scope_leaves(scope))
            },
            "trigger_binding": bound,
            "requested": requested,
        }
        return self._commit(bound["session"], operation_id, proposal)

    @staticmethod
    def _scope(scope: dict[str, Any]) -> dict[str, Any]:
        scope_leaves(scope)
        canonical(scope)
        return scope

    def update(
        self,
        config: RunnableConfig,
        operation_id: str,
        read_handle: str,
        changes: list[dict[str, Any]],
        fragment_handles: list[str] | None = None,
        *,
        retract: bool = False,
    ) -> dict[str, Any]:
        bound = self._binding(config)
        requested = {
            "operation": "update",
            "read_handle": read_handle,
            "changes": changes,
            "fragment_handles": fragment_handles,
            "retract": retract,
        }
        replay = self.service.replay_requested(bound["session"], operation_id, requested)
        if replay is not None:
            return replay
        candidate = self.service.candidate(read_handle)
        if candidate is None:
            raise FunctionalRejection("V13_5_READ_HANDLE_INVALID")
        row = self.service.read(candidate["record_id"], candidate["revision"])
        if not row["ok"]:
            raise FunctionalRejection("V13_5_RECORD_UNAVAILABLE")
        old = row["value"]
        value = copy.deepcopy({key: old[key] for key in ("content", "kind", "basis", "scope")})
        support = self._source_support(old)
        if not isinstance(changes, list) or type(retract) is not bool or (retract and changes):
            raise FunctionalRejection("V13_5_CHANGES_LIST_REQUIRED_OR_RETRACT_CONFLICT")
        changed: set[str] = set()
        selections: dict[str, list[str]] = {}
        for change in changes:
            if (
                not isinstance(change, dict)
                or set(change) - {"field", "op", "value", "fragment_handles"}
                or change.get("op") not in {"set", "remove"}
                or not isinstance(change.get("field"), str)
            ):
                raise FunctionalRejection("V13_5_CHANGE_SCHEMA_INVALID")
            field = change["field"]
            if any(
                field == other or field.startswith(other + ".") or other.startswith(field + ".")
                for other in changed
            ):
                raise FunctionalRejection("V13_5_OVERLAPPING_CHANGE_FIELD")
            changed.add(field)
            # Legacy direct Python callers can explicitly share a selection.
            # The exposed Agent tool requires a separate selection per change.
            selected = change.get("fragment_handles", fragment_handles)
            if not isinstance(selected, list) or not all(isinstance(h, str) for h in selected):
                raise FunctionalRejection("V13_5_FIELD_FRAGMENT_SELECTION_REQUIRED:" + field)
            selections[field] = selected
            if change["op"] == "set" and "value" not in change:
                raise FunctionalRejection("V13_5_SET_VALUE_REQUIRED")
            if change["op"] == "remove" and "value" in change:
                raise FunctionalRejection("V13_5_REMOVE_MUST_OMIT_VALUE")
            if field.startswith("scope.") and all(field.split(".")):
                parts = field.split(".")[1:]
                parent = value["scope"]
                for part in parts[:-1]:
                    if part not in parent:
                        if change["op"] == "remove":
                            parent = {}
                            break
                        parent[part] = {}
                    if not isinstance(parent[part], dict):
                        raise FunctionalRejection("V13_5_SCOPE_PARENT_NOT_OBJECT")
                    parent = parent[part]
                if change["op"] == "remove":
                    parent.pop(parts[-1], None)
                else:
                    parent[parts[-1]] = copy.deepcopy(change["value"])
            elif field in {"content", "kind", "basis"} and change["op"] == "set":
                value[field] = change["value"]
            else:
                raise FunctionalRejection("V13_5_CHANGE_FIELD_OR_OPERATION_INVALID")
        self._scope(value["scope"])
        equal = (not retract or old.get("retracted", False)) and all(
            canonical(value[field]) == canonical(old[field]) for field in value
        )
        before = {**scope_leaves(old["scope"]), **{k: old[k] for k in ("content", "kind", "basis")}}
        after = {
            **scope_leaves(value["scope"]),
            **{k: value[k] for k in ("content", "kind", "basis")},
        }

        def selected_for(path: str) -> list[str]:
            matching = [selected for field, selected in selections.items()
                        if path == field or path.startswith(field + ".")
                        or field.startswith(path + ".")]
            if not matching:
                raise FunctionalIntegrityError("V13_5_CHANGED_FIELD_SELECTION_MISSING:" + path)
            return list(dict.fromkeys(handle for selected in matching for handle in selected))

        removed = {path: selected_for(path) for path in before.keys() - after.keys()}
        support = {
            path: (
                support[path]
                if path in before and canonical(before[path]) == canonical(item)
                else selected_for(path)
            )
            for path, item in after.items()
        }
        if equal:
            refs = old.get("source_refs", [old["source_ref"]])
            lineage = None
        else:
            # Validate each changed leaf independently, then form the source union.
            # Shared provenance does not assert that all new values are supported.
            selected_changes = [support[path] for path in after
                                if path not in before or canonical(before[path]) !=
                                canonical(after[path])] + list(removed.values())
            if retract:
                selected_changes.append(fragment_handles or [])
            for selected in selected_changes:
                fragment_support(self.service, selected)
            new = fragment_support(self.service, list(dict.fromkeys(
                handle for selected in selected_changes for handle in selected)))
            refs = list(
                dict.fromkeys([*new["source_refs"], *old.get("source_refs", [old["source_ref"]])])
            )
            lineage = {
                field: (
                    {"reuse_support_from": read_handle}
                    if canonical(value[field]) == canonical(old[field])
                    else {"source_refs": refs}
                )
                for field in ("content", "scope", "basis", "kind")
            }
        proposal = {
            "action": "update",
            "id": row["id"],
            "expected_revision": old["revision"],
            "candidate_handle": read_handle,
            **value,
            "fields": old["fields"],
            "object_ref": old.get("object_ref"),
            "source_ref": refs[0],
            "source_refs": refs,
            "field_support": lineage,
            "trigger_binding": bound,
            "requested": requested,
            "patch_operation": "no_change" if equal else "retract" if retract else "revise",
        }
        if not equal:
            proposal["functional_support"] = support
            proposal["removed_field_support"] = {
                **removed,
                **({"record": fragment_handles} if retract else {}),
            }
        return self._commit(bound["session"], operation_id, proposal)

    def _read(
        self,
        config: RunnableConfig,
        call_id: str,
        arguments: dict[str, Any],
        action: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        bound = self._binding(config)
        key = "read-admission-" + digest(bound)
        with self.service._locked():
            old = self.service.store.get(namespace(self.service), key)
            state = old.value if old else {"binding": bound, "policy": self.policy, "calls": {}}
            if state["binding"] != bound or state["policy"] != self.policy:
                raise FunctionalIntegrityError("V13_5_READ_ADMISSION_CHANGED")
            previous = state["calls"].get(call_id)
            if previous is not None:
                if previous["arguments"] != arguments:
                    raise FunctionalRejection("V13_5_READ_CALL_CHANGED")
                if previous["forget_epoch"] != self.forget_epoch:
                    raise FunctionalRejection("V13_5_READ_REPLAY_REVOKED")
                if "result" in previous:
                    return cast(dict[str, Any], previous["result"])
                raise FunctionalIntegrityError("V13_5_READ_OUTCOME_UNKNOWN")
            if len(state["calls"]) >= self.read_limit:
                exhausted = {"ok": False, "status": "read_limit_exhausted",
                             "limit": self.read_limit, **self._read_only_metadata([])}
                if self.token_count(canonical(exhausted)) > self.material_limit:
                    raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT")
                return exhausted
            state["calls"][call_id] = {"arguments": arguments, "forget_epoch": self.forget_epoch}
            self.service.store.put(namespace(self.service), key, state, index=False)
        try:
            result = action(bound)
        except FunctionalRejection as error:
            result = {
                "ok": False,
                "status": "read_rejected",
                "reason": str(error),
                "retryable": False,
                "error_type": type(error).__name__,
                "phase": "read_contract",
            }
        except Exception as error:
            result = {"ok": False, "status": "read_integrity_error"
                      if isinstance(error, FunctionalIntegrityError) else "read_outcome_unknown",
                      "error_type": type(error).__name__, "phase": "read_action",
                      "read_state_effect": "unconfirmed", "retryable": False}
        if result.get("schema") != "functional_material_v1":
            # Failed reads delivered no items; zero is a delivery count, not a
            # claim that the owner has no records or that the lookup succeeded.
            result = {**result, **self._read_only_metadata([])}
            if self.token_count(canonical(result)) > self.material_limit:
                raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT")
        try:
            with self.service._locked():
                current = self.service.store.get(namespace(self.service), key)
                assert current is not None
                current.value["calls"][call_id]["result"] = result
                self.service.store.put(namespace(self.service), key, current.value, index=False)
        except Exception as error:
            result = {"ok": False, "status": "read_outcome_unknown",
                      "error_type": type(error).__name__, "phase": "read_receipt_persistence",
                      "read_state_effect": "unconfirmed", "retryable": False,
                      **self._read_only_metadata([])}
            if self.token_count(canonical(result)) > self.material_limit:
                raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT") from error
        return result

    def tools(self) -> tuple[BaseTool, ...]:
        def message(name: str, call_id: str, result: dict[str, Any]) -> ToolMessage:
            return ToolMessage(
                name=name,
                tool_call_id=call_id,
                content=canonical(result),
                status="success" if result.get("ok") else "error",
            )

        def mutation(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
            try:
                return action()
            except FunctionalRejection as error:
                return {
                    "ok": False,
                    "status": "rejected",
                    "reason": str(error),
                    "effect": "none",
                    "formation_status": "pending",
                    "error_type": type(error).__name__,
                    "phase": "pre_mutation_contract",
                }
            except Exception as error:
                # A Store put can commit and then raise. Only the same durable
                # operation identity may recover its actual receipt on replay.
                cause = error.cause if isinstance(error, FunctionalOperationError) else error
                return {
                    "ok": False,
                    "status": "outcome_unknown",
                    "effect": "unconfirmed",
                    "formation_status": "unknown",
                    "error_type": type(cause).__name__,
                    "phase": error.phase if isinstance(error, FunctionalOperationError)
                    else "mutation_preparation",
                    "error_category": "integrity" if isinstance(cause, FunctionalIntegrityError)
                    else "unconfirmed_effect",
                    "recovery": "same_operation_id_only",
                }

        def save_memory(
            content: Annotated[str, Field(description=(
                "Faithful assertion with all applicability limits, exceptions, negation and "
                "uncertainty retained in the text itself. Keep source wording for restrictive "
                "phrases; do not generalize one occurrence into a class or a lasting "
                "preference."))],
            fragment_handles: list[str],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            scope: Annotated[dict[str, Any] | None, Field(description=(
                "Only explicitly supported applicability boundaries. Preserve the particular "
                "occurrence rather than merely its category. Do not invent project names or "
                "use scope for summary labels. Omit absent boundaries; keep unknown dates unknown. "
                "These fields must agree with the restrictions retained in content."))] = None,
        ) -> ToolMessage:
            """Save semantic memory using issued fragments; program extracts original quote/hash.

            Create a new matter. For an existing continuing matter, read its record
            and use update_memory; do not create a duplicate with save_memory.
            An identical save in the same current message returns existing_record,
            no_change and effect=none. It never creates a second record.
            Selected fragments must directly support the new content and scope.
            A verified fragment proves original bytes, not semantic support.
            The current request binding attributes execution; it is not field evidence.
            Scope is a JSON map of explicit personal/project/time limits, not Source objects.
            Confirm semantic saving only after an ok committed/no_change receipt.
            """
            return message(
                "save_memory",
                tool_call_id,
                mutation(lambda: self.save(config, tool_call_id, content, fragment_handles, scope)),
            )

        def save_assertion(
            content: str, fragment_handles: list[str], config: RunnableConfig, *,
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> ToolMessage:
            """Save one new supported assertion with all limits in its content.

            Content is the complete memory: state the fact AND its explicit subject,
            particular occurrence, time, conditions, exceptions and uncertainty together.
            There is no separate scope map to carry omitted meaning. Prefer the source's
            restrictive phrases to inferred category or project labels. Select actual
            fragments supporting the assertion. The program extracts quotes; valid
            quotes alone do not prove semantic support. For an existing matter use
            update_memory on the actual read version instead of creating a duplicate.
            Confirm saving only after an actual committed or no_change receipt.
            """
            return save_memory(content, fragment_handles, config, tool_call_id=tool_call_id)

        def update_memory(
            read_handle: str,
            changes: list[FieldChange],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            retract: bool = False,
            fragment_handles: list[str] | None = None,
        ) -> ToolMessage:
            """Patch the exact read version using field, op=set/remove, and value for set.

            Fields are content/kind/basis or scope.KEY[.KEY]. Only scope paths support remove.
            If the corrected claim is in content, patch content itself. Scope holds
            applicability boundaries; it does not replace contradictory content.
            Each changes item requires its own fragment_handles. Select fragments
            that directly support each NEW changed value, not
            merely the old value. The current correction is not automatically
            added as evidence: supply its issued fragment handles when it supports
            the change. A trigger binding only attributes the current execution.
            retract=true with changes=[] withdraws the fact and retains its history.
            Only a retraction uses top-level fragment_handles; ordinary changes
            select support inside each item. Empty per-item selections are allowed
            only for exact no_change fields, never for a changed value.
            Omitted fields retain original support; null is a value, never removal.
            Empty changes or exact same values return no_change without a new version.
            """
            def patch() -> dict[str, Any]:
                if changes and fragment_handles is not None:
                    raise FunctionalRejection("V13_5_SELECT_FRAGMENTS_INSIDE_EACH_CHANGE")
                return self.update(
                    config, tool_call_id, read_handle,
                    [change.model_dump(exclude_unset=True) for change in changes],
                    fragment_handles, retract=retract,
                )

            return message("update_memory", tool_call_id, mutation(patch))

        def search_memory(
            query: str, config: RunnableConfig, *, tool_call_id: Annotated[str, InjectedToolCallId]
        ) -> ToolMessage:
            """Search owner material read-only; units paginate a fixed snapshot.

            Raw fragments are captured original Sources, not saved semantic records.
            Record units are existing versions, possibly partial bodies. Counts refer
            only to delivered items. Search never saves or updates: confirm a semantic
            write only from a successful save_memory/update_memory receipt.
            """
            return message(
                "search_memory",
                tool_call_id,
                self._read(
                    config,
                    tool_call_id,
                    {"tool": "search_memory", "query": query},
                    lambda bound: self._page(
                        self._snapshot(bound, self._search_units(query), "explicit_search"),
                        0,
                        bound,
                    ),
                ),
            )

        def read_memory(
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            record_id: str | None = None,
            revision: int | None = None,
            cursor: str | None = None,
            history: bool = False,
            history_cursor: str | None = None,
        ) -> ToolMessage:
            """Read current/exact historical revision, or a previously issued cursor.

            history=true reads original stored revision bodies with snapshot pagination.
            History is read-only: do not save an old value as a new or current fact.
            Reading a record or raw fragment performs no semantic write. Only an
            actual successful save_memory/update_memory receipt confirms that effect.
            A cursor always continues its original
            ordinary/explicit snapshot; it never changes to latest results.
            """

            def action(bound: dict[str, Any]) -> dict[str, Any]:
                if cursor is not None:
                    if (
                        record_id is not None
                        or revision is not None
                        or history
                        or history_cursor is not None
                    ):
                        raise FunctionalRejection("V13_5_CURSOR_ARGUMENTS_CONFLICT")
                    key, sep, offset = cursor.rpartition(":")
                    if sep != ":" or not offset.isdecimal():
                        raise FunctionalRejection("V13_5_CURSOR_INVALID")
                    return self._page(key, int(offset), bound)
                if record_id is None:
                    raise FunctionalRejection("V13_5_RECORD_ID_REQUIRED")
                if history:
                    if revision is not None:
                        raise FunctionalRejection("V13_5_HISTORY_REVISION_CONFLICT")
                    if history_cursor is not None:
                        key, sep, offset = history_cursor.rpartition(":")
                        if sep != ":" or not offset.isdecimal():
                            raise FunctionalRejection("V13_5_CURSOR_INVALID")
                        return self._page(key, int(offset), bound)
                    index = self.service.history_index(record_id)
                    if not index["ok"]:
                        return index
                    revisions = list(index["revisions"])
                    while index["next_cursor"]:
                        index = self.service.history_index(record_id, cursor=index["next_cursor"])
                        revisions.extend(index["revisions"])
                    units = [
                        unit
                        for rev in revisions
                        for unit in self._record_units(
                            self.service.read(record_id, rev), "historical_exact_revision"
                        )
                    ]
                    return self._page(self._snapshot(bound, units, "record_history"), 0, bound)
                if history_cursor is not None:
                    raise FunctionalRejection("V13_5_HISTORY_CURSOR_REQUIRES_HISTORY")
                row = self.service.read(record_id, revision)
                if not row["ok"]:
                    return row
                return self._page(
                    self._snapshot(
                        bound,
                        self._record_units(
                            row,
                            "historical_exact_revision"
                            if revision is not None
                            else "current_at_snapshot",
                        ),
                        "record_read",
                    ),
                    0,
                    bound,
                )

            return message(
                "read_memory",
                tool_call_id,
                self._read(
                    config,
                    tool_call_id,
                    {
                        "tool": "read_memory",
                        "record_id": record_id,
                        "revision": revision,
                        "cursor": cursor,
                        "history": history,
                        "history_cursor": history_cursor,
                    },
                    action,
                ),
            )

        def read_source(
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            fragment_handle: str | None = None,
            source_ref: str | None = None,
            cursor: str | None = None,
        ) -> ToolMessage:
            """Read an issued exact fragment or a full public source group, continuing its cursor.

            Source groups split only at public original boundaries; each page states omissions.
            Original capture/read is not semantic formation. This read never saves;
            a semantic write needs a successful save_memory/update_memory receipt.
            Every call, including a failed call, uses the explicit per-message read allowance.
            """

            def action(bound: dict[str, Any]) -> dict[str, Any]:
                if sum(x is not None for x in (fragment_handle, source_ref, cursor)) != 1:
                    raise FunctionalRejection("V13_5_EXACTLY_ONE_SOURCE_SELECTOR_REQUIRED")
                if cursor is not None:
                    key, sep, offset = cursor.rpartition(":")
                    if sep != ":" or not offset.isdecimal():
                        raise FunctionalRejection("V13_5_CURSOR_INVALID")
                    return self._page(key, int(offset), bound)
                fragments = (
                    [self.service.source_fragment(fragment_handle)]
                    if fragment_handle is not None
                    else self.service.source_fragments(
                        str(source_ref), max_chars=self.fragment_chars
                    )
                )
                return self._page(
                    self._snapshot(
                        bound, [{"type": "fragment", **f} for f in fragments], "source_read"
                    ),
                    0,
                    bound,
                )

            return message(
                "read_source",
                tool_call_id,
                self._read(
                    config,
                    tool_call_id,
                    {
                        "tool": "read_source",
                        "fragment_handle": fragment_handle,
                        "source_ref": source_ref,
                        "cursor": cursor,
                    },
                    action,
                ),
            )

        def forget_memory(
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            read_handle: str | None = None,
            fragment_handles: list[str] | None = None,
            additional_fragment_handles: list[str] | None = None,
            scope: Literal["record", "record_and_sources"] = "record_and_sources",
        ) -> ToolMessage:
            """Revoke visibility of one exact record OR issued original fragment sources.

            record_and_sources also blocks associated source/history/raw fallback.
            record alone keeps source visibility. Audit/checkpoint bytes are retained.
            fragment_handles revokes whole selected Sources, including unformed raw input.
            With read_handle, additional_fragment_handles explicitly selects other known copies.
            User input is never revoked just because prefetch exposed another memory to the Host.
            This is runtime visibility revocation, not physical erasure.
            """
            bound = self._binding(config)
            return message(
                "forget_memory",
                tool_call_id,
                mutation(
                    lambda: self.service.forget(
                        bound["session"],
                        tool_call_id,
                        read_handle,
                        scope=scope,
                        fragment_handles=fragment_handles,
                        additional_fragment_handles=additional_fragment_handles,
                    )
                ),
            )

        save_tool = (StructuredTool.from_function(
            save_assertion, name="save_memory", args_schema=SavedAssertion)
            if self.formation_interface == "unified_assertion_v1"
            else StructuredTool.from_function(save_memory))
        return (save_tool, *tuple(
            StructuredTool.from_function(function)
            for function in (
                update_memory,
                search_memory,
                read_memory,
                read_source,
                forget_memory,
            )
        ))
