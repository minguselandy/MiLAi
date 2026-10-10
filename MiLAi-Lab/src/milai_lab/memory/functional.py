"""Functional opt-in tools over one MemoryService; no model or business dispatch.

Ordinary context is cached per actual public message. Explicit reads consume a
durable per-message allowance, including failed attempts. Every cursor resolves
its issued snapshot. Stored logs remain audit evidence after visibility revocation.
"""

from __future__ import annotations

import copy
import math
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal, cast

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model

from milai_lab.memory.functional_maintenance import bounded_support_review
from milai_lab.memory.functional_state import (
    FunctionalIntegrityError,
    FunctionalMaintenanceRejection,
    FunctionalOperationError,
    FunctionalRejection,
    FunctionalReviewRejection,
    canonical,
    commit_request_targets,
    fragment_support,
    namespace,
    note_exposure,
    project_request_targets,
    reference_key,
    request_target_mapping,
    resolve_request_target,
    scope_leaves,
)
from milai_lab.memory.reader_projection import expand_host_packet
from milai_lab.memory.service import MemoryService, _lexical_tokens
from milai_lab.memory.working_set import (
    admit_refs,
    catalog_candidates,
    empty_view,
    item_ref,
    read_evidence_basis,
)


class SavedAssertion(BaseModel):
    """One supported assertion, with its applicability expressed in the same body."""

    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(
        description=(
            "Complete supported assertion, including who, which occurrence, time, conditions, "
            "exceptions and uncertainty. Preserve restrictive source wording in this body."
        )
    )
    fragment_handles: list[str]
    tool_call_id: Annotated[str, InjectedToolCallId]


class FieldChange(BaseModel):
    """One proposed value and its explicitly selected evidence, not a semantic verdict."""

    model_config = ConfigDict(extra="forbid", strict=True)
    field: str = Field(description="content/kind/basis or scope.KEY[.KEY]")
    op: Literal["set", "remove"]
    value: Any = Field(
        default=None,
        description=(
            "Required for set; omit for remove. Preserve the assertion's exact subject, "
            "occurrence, time limits, negation and uncertainty. Scope values describe only "
            "explicit applicability boundaries, not inferred project labels or summary categories."
        ),
    )
    fragment_handles: list[str] = Field(
        description="Issued fragments supporting this NEW value or removal; not its old value"
    )


class ReplacementChange(FieldChange):
    """Public selection names distinguish replacement evidence from target identity."""

    fragment_handles: list[str] = Field(
        alias="evidence_for_new_value",
        description=(
            "Select original fragments whose unchanged text supports the replacement value "
            "or explicit removal. A fragment supporting the old record does not acquire new "
            "meaning when the user corrects it. Select the actual correction when it supplies "
            "the new fact; older fragments remain eligible when they directly support it. "
            "The read_handle, not this evidence selection, identifies the old target."
        ),
    )


class FragmentCue(BaseModel):
    """A short literal selection cue, not a model-generated full quotation."""

    model_config = ConfigDict(extra="forbid", strict=True)
    fragment_handle: str
    supporting_words: str = Field(
        min_length=1,
        max_length=160,
        description=(
            "Short exact words from THIS original fragment that express the NEW fact, "
            "correction or cancellation, not merely its topic or old value. Copy only this "
            "short selection cue, not a whole quotation. The program checks exact occurrence "
            "inside the selected fragment; a valid cue is not proof of semantic support."
        ),
    )


class AnchoredChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: str = Field(description="content/kind/basis or scope.KEY[.KEY]")
    op: Literal["set", "remove"]
    value: Any = Field(
        default=None,
        description=(
            "Required for set; omit for remove. New value with unchanged limits retained."
        ),
    )
    evidence_for_new_value: list[FragmentCue] = Field(
        description=(
            "Select original fragments and short literal words expressing THIS change. "
            "The old record's read_handle identifies the target; its old affirmation is "
            "not evidence for a different assertion."
        )
    )


class ReadSelector(BaseModel):
    """Concrete read selectors reject unused parameters and implicit coercion."""

    model_config = ConfigDict(extra="forbid", strict=True)
    tool_call_id: Annotated[str, InjectedToolCallId]


class RecordSelector(ReadSelector):
    record_id: str = Field(min_length=1)


class RevisionSelector(RecordSelector):
    revision: int = Field(ge=1)


class SourceSelector(ReadSelector):
    source_ref: str = Field(min_length=1)


class FragmentSelector(ReadSelector):
    fragment_handle: str = Field(min_length=1)


class PageSelector(ReadSelector):
    cursor: str = Field(min_length=1)


class SupportContextSelector(ReadSelector):
    fragment_handles: list[str] = Field(min_length=1)
    read_handle: str | None = None


class ForgetTargetSelector(ReadSelector):
    targets: list[str] = Field(
        min_length=1,
        description="Copy targets from this request's delivered items. Select at most one record "
                    "and any explicitly selected original Sources; do not construct identifiers.",
    )
    scope: Literal["record", "record_and_sources"] = "record_and_sources"


class StructuredReadGoal(BaseModel):
    """Declared reading purpose and evidence needs, never a sufficiency verdict."""

    model_config = ConfigDict(extra="forbid", strict=True)
    purpose: str = Field(min_length=1)
    evidence: list[Literal[
        "current_interpretation", "saved_history", "original_source", "live_business"
    ]]


def normalize_read_goal(
    value: str | dict[str, Any] | StructuredReadGoal | None,
) -> str | dict[str, Any] | None:
    if value is None or isinstance(value, str):
        return value
    goal = value if isinstance(value, StructuredReadGoal) \
        else StructuredReadGoal.model_validate(value)
    return goal.model_dump(mode="json")


class ResidentTargetSelector(ReadSelector):
    target: str = Field(
        min_length=1, description="Copy an actual target from this request's material.",
    )
    keep_resident: bool = False
    read_goal: str | StructuredReadGoal | None = Field(
        default=None, description="Reading purpose and explicit evidence needs; this declaration "
                                  "does not certify coverage, sufficient evidence or permission.",
    )


class ResidentRevisionTargetSelector(ResidentTargetSelector):
    revision: int | None = Field(default=None, ge=1, description="Exact revision when selecting "
                                "from a current record target; omit for an exact revision target.")


class ResidentSupportTargetSelector(ReadSelector):
    targets: list[str] = Field(min_length=1, description="Delivered exact Source targets and "
                             "at most one delivered record target; navigation is insufficient.")
    keep_resident: bool = False
    read_goal: str | StructuredReadGoal | None = None


class ReadSelectorTool(StructuredTool):
    """Preserve the selector model's constraints in the model-visible schema."""

    @property
    def tool_call_schema(self) -> dict[str, Any]:
        # The SDK's subset model drops extra="forbid" when removing injected
        # arguments. Export our actual strict DTO and remove only our injected ID,
        # so provider validation and direct execution accept the same selectors.
        assert isinstance(self.args_schema, type) and issubclass(self.args_schema, ReadSelector)
        schema = self.args_schema.model_json_schema()
        schema["properties"].pop("tool_call_id")
        schema["required"] = [key for key in schema["required"] if key != "tool_call_id"]
        return {**schema, "title": self.name, "description": self.description}


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
        read_interface: str = "combined_selectors_v1",
        recent_context: str = "disabled",
        memory_view_mode: str = "legacy",
        existing_confirmation: bool = False,
        support_context: bool = False,
        semantic_reproposal_policy: str = "message_limit_only",
        revision_support_review: Callable[[dict[str, Any], Callable[[], None]], None] | None = None,
        formation_support_review: (
            Callable[[dict[str, Any], Callable[[], None]], None] | None
        ) = None,
    ) -> None:
        if service.functional_contract != "functional_v1":
            raise FunctionalRejection("V13_5_FUNCTIONAL_CONTRACT_REQUIRED")
        if any(type(v) is not int or v < 1 for v in (read_limit, material_limit, fragment_chars)):
            raise FunctionalRejection("V13_5_FUNCTIONAL_LIMIT_INVALID")
        self.service, self.token_count = service, token_count
        if formation_interface not in {
            "content_and_scope_v1",
            "unified_assertion_v1",
            "unified_assertion_v2",
            "unified_assertion_v3",
            "reviewed_assertion_v1",
            "anchored_assertion_v1",
            "anchored_assertion_v2",
            "anchored_assertion_v3",
        }:
            raise FunctionalRejection("V13_5_FORMATION_INTERFACE_INVALID")
        self.formation_interface = formation_interface
        if read_interface not in {"combined_selectors_v1", "explicit_selectors_v1"}:
            raise FunctionalRejection("V13_5_READ_INTERFACE_INVALID")
        self.read_interface = read_interface
        if type(existing_confirmation) is not bool:
            raise FunctionalRejection("V13_5_EXISTING_CONFIRMATION_INVALID")
        self.existing_confirmation = existing_confirmation
        if type(support_context) is not bool:
            raise FunctionalRejection("V13_5_SUPPORT_CONTEXT_INVALID")
        self.support_context = support_context
        if semantic_reproposal_policy not in {"message_limit_only", "maintenance_two_proposals_v1"}:
            raise FunctionalRejection("FUNCTIONAL_SEMANTIC_REPROPOSAL_POLICY_INVALID")
        if semantic_reproposal_policy != "message_limit_only" and (
            revision_support_review is None or formation_support_review is None
        ):
            raise FunctionalRejection("FUNCTIONAL_BOUNDED_REPROPOSAL_REQUIRES_BOTH_REVIEWS")
        self.semantic_reproposal_policy = semantic_reproposal_policy
        self.revision_support_review = revision_support_review
        self.formation_support_review = formation_support_review
        if recent_context not in {"disabled", "session_events_v1", "bank_recent_v2"}:
            raise FunctionalRejection("V13_5_RECENT_CONTEXT_INVALID")
        self.recent_context = recent_context
        if memory_view_mode not in {"legacy", "staged", "state_driven"}:
            raise FunctionalRejection("FUNCTIONAL_MEMORY_VIEW_MODE_INVALID")
        self.memory_view_mode = memory_view_mode
        self.read_limit, self.material_limit, self.fragment_chars = (
            read_limit,
            material_limit,
            fragment_chars,
        )
        self.policy = {
            "read_limit": read_limit,
            "material_limit": material_limit,
            "fragment_chars": fragment_chars,
            "retrieval_policy": "supplied_ranges"
            if retrieval_candidates is not None
            else "service_search",
        }
        if formation_interface != "content_and_scope_v1":
            self.policy["formation_interface"] = formation_interface
        if read_interface != "combined_selectors_v1":
            self.policy["read_interface"] = read_interface
        if support_context:
            self.policy["support_context"] = "selected_sources_v1"
        if semantic_reproposal_policy != "message_limit_only":
            self.policy["semantic_reproposal_policy"] = semantic_reproposal_policy
        if recent_context != "disabled":
            self.policy["recent_context"] = recent_context
        if memory_view_mode != "legacy":
            self.policy["memory_view_mode"] = memory_view_mode
        if revision_support_review is not None:
            self.policy["revision_support_review"] = "selected_originals_v1"
        if formation_support_review is not None:
            self.policy["formation_support_review"] = "selected_originals_v1"
        self.retrieval_candidates = copy.deepcopy(retrieval_candidates)
        if retrieval_candidates is not None:
            for row in retrieval_candidates:
                required = {"source_ref", "start", "end", "retrieval_score"}
                references = {"source_revision"}
                if (
                    not isinstance(row, dict)
                    or not required <= set(row)
                    or set(row) - required - references
                    or type(row["retrieval_score"]) not in {int, float}
                    or not math.isfinite(row["retrieval_score"])
                ):
                    raise FunctionalRejection("V13_5_RETRIEVAL_CANDIDATE_INVALID")
                fragment = service.source_fragment_range(
                    row["source_ref"], row["start"], row["end"]
                )
                if any(row[key] != fragment[key] for key in references.intersection(row)):
                    raise FunctionalRejection("V13_5_RETRIEVAL_CANDIDATE_VERSION_MISMATCH")

    @property
    def read_tool_names(self) -> frozenset[str]:
        names = {"search_memory", "read_memory", "read_source"}
        if self.read_interface == "explicit_selectors_v1" or self.memory_view_mode != "legacy":
            names.update(
                {"read_memory_history", "read_memory_revision", "read_fragment", "read_page"}
            )
        if self.support_context:
            names.add("read_support_context")
        return frozenset(names)

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
            config_version=cfg.get("v13_config_version"),
        )
        if bound is None:
            raise FunctionalRejection("V13_5_ACTUAL_PUBLIC_TURN_REQUIRED")
        return bound

    def bind_request_targets(
        self, config: RunnableConfig, packet: dict[str, Any]
    ) -> dict[str, Any]:
        """Bind a trusted final delivery, never a model-supplied packet or preview."""
        return self._bind_request_targets(self._binding(config), packet)

    def _bind_request_targets(
        self, binding: dict[str, Any], packet: dict[str, Any]
    ) -> dict[str, Any]:
        if self.memory_view_mode == "legacy" or not packet.get("ok"):
            return packet
        packet = {**packet, "forget_epoch": packet.get("forget_epoch", self.forget_epoch)}
        if packet["forget_epoch"] != self.forget_epoch:
            raise FunctionalRejection("V13_5_REQUEST_TARGET_REVOKED")
        mapping = request_target_mapping(self.service, binding)
        scope = packet.get("target_scope")
        if scope is not None:
            if not isinstance(scope, str) or len(scope) != 13 or scope[0] != "q" or any(
                char not in "0123456789abcdef" for char in scope[1:]
            ):
                raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_SCOPE_INVALID")
            if mapping["targets"] and scope != mapping["scope"]:
                raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_SCOPE_CHANGED")
            mapping["scope"] = scope
        result, planned = project_request_targets(mapping, expand_host_packet(packet))
        result = self._project_read_packet(result)
        if self.token_count(canonical(result)) > self.material_limit:
            raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT")
        for target in set(planned["targets"]) - set(mapping["targets"]):
            row = planned["targets"][target]
            if row["kind"] == "delivered_record":
                bound = self.service.candidate(row["credentials"]["read_handle"])
                if bound is None or any(
                    bound[key] != value for key, value in row["identity"].items()
                ):
                    raise FunctionalRejection("V13_5_REQUEST_TARGET_RECORD_NOT_ISSUED")
            elif row["kind"] == "delivered_source":
                fragment = self.service.source_fragment(row["credentials"]["fragment_handle"])
                if any(fragment[key] != value for key, value in row["identity"].items()):
                    raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_SOURCE_CHANGED")
        if planned["targets"]:
            commit_request_targets(self.service, planned)
        return result

    def _deliver_request_targets(
        self, binding: dict[str, Any], packet: dict[str, Any], *, from_tool: bool = False,
    ) -> dict[str, Any]:
        """Final base delivery hook; adapters may defer it until their own receipt is saved."""
        return self._bind_request_targets(binding, packet)

    def resolve_request_target(
        self, config: RunnableConfig, target: str, *, kind: str | None = None
    ) -> dict[str, Any]:
        """Return only the bound identity/credentials; callers retain their operation checks."""
        return resolve_request_target(self.service, self._binding(config), target, kind=kind)

    def _resolve_read_target(
        self, binding: dict[str, Any], request: dict[str, Any],
    ) -> dict[str, Any]:
        row = resolve_request_target(self.service, binding, request["target"])
        identity, kind, tool = row["identity"], row["kind"], request["tool"]
        if kind == "read_only_navigation" and identity.get("forget_epoch", self.forget_epoch) \
                != self.forget_epoch:
            raise FunctionalRejection("V13_5_REQUEST_TARGET_REVOKED")
        if tool in {"read_memory", "read_memory_history", "read_memory_revision"}:
            if "record_id" not in identity or (
                kind == "read_only_navigation" and identity.get("read", {}).get("tool")
                not in {"read_memory", "read_memory_history", "read_memory_revision"}
            ):
                raise FunctionalRejection("V13_5_REQUEST_TARGET_KIND_INVALID")
            if tool == "read_memory" and identity.get("version_view") \
                    == "historical_exact_revision":
                raise FunctionalRejection("V13_5_REQUEST_TARGET_KIND_INVALID")
            selectors: dict[str, Any] = {"record_id": identity["record_id"]}
            if tool == "read_memory_history":
                selectors["history"] = True
            elif tool == "read_memory_revision":
                revision = request.get("revision")
                exact = kind == "delivered_record" or identity.get("version_view") \
                    == "historical_exact_revision"
                if exact and revision is not None and revision != identity.get("revision"):
                    raise FunctionalRejection("V13_5_REQUEST_TARGET_REVISION_CHANGED")
                revision = identity.get("revision") if revision is None else revision
                if type(revision) is not int or revision < 1:
                    raise FunctionalRejection("V13_5_EXACT_REVISION_REQUIRED")
                selectors["revision"] = revision
            return {**request, **selectors}
        if tool == "read_source" and "source_ref" in identity and (
            kind == "delivered_source" or (kind == "read_only_navigation"
            and identity.get("read", {}).get("tool") == "read_source")
        ):
            return {**request, "source_ref": identity["source_ref"]}
        if tool == "read_fragment" and kind == "delivered_source":
            return {**request, "fragment_handle": row["credentials"]["fragment_handle"]}
        if tool == "read_page" and kind == "read_only_navigation" \
                and identity.get("read", {}).get("tool") == "read_page":
            return {**request, **identity["read"]["arguments"]}
        raise FunctionalRejection("V13_5_REQUEST_TARGET_KIND_INVALID")

    def _history_index_page(
        self, binding: dict[str, Any], record_id: str, cursor: str,
    ) -> dict[str, Any]:
        index = self.service.history_index(record_id, cursor=cursor)
        if not index.get("ok"):
            return index
        packet = {
            "schema": "functional_material_v1", "ok": True,
            "kind": "stored_history_index", "record_id": record_id,
            "stored_history": index, "items": [], "delivered_units": 0,
            "view_refs": [], "reading_basis": {},
            "forget_epoch": self.forget_epoch, **self._read_only_metadata([]),
        }
        packet, _ = project_request_targets(request_target_mapping(self.service, binding), packet)
        packet = self._project_read_packet(packet)
        if self.token_count(canonical(packet)) > self.material_limit:
            raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT")
        return packet

    def forget_targets(
        self, config: RunnableConfig, operation_id: str, targets: list[str], *,
        scope: str = "record_and_sources",
    ) -> dict[str, Any]:
        """Translate explicit request targets into the unchanged exact forget contract."""
        if (
            not isinstance(targets, list) or not targets
            or not all(isinstance(target, str) for target in targets)
            or len(set(targets)) != len(targets)
        ):
            raise FunctionalRejection("V13_5_REQUEST_TARGET_SELECTION_REQUIRED")
        binding = self._binding(config)
        selected = [resolve_request_target(self.service, binding, target) for target in targets]
        records = [row for row in selected if row["kind"] == "delivered_record"]
        sources = [row for row in selected if row["kind"] == "delivered_source"]
        if len(records) > 1 or len(records) + len(sources) != len(selected):
            raise FunctionalRejection("V13_5_FORGET_EXACTLY_ONE_RECORD_OR_SOURCES_REQUIRED")
        fragments = [row["credentials"]["fragment_handle"] for row in sources]
        return self.service.forget(
            binding["session"], operation_id,
            records[0]["credentials"]["read_handle"] if records else None,
            scope=scope,
            fragment_handles=fragments if not records else None,
            additional_fragment_handles=fragments if records and fragments else None,
        )

    def _record_units(
        self,
        row: dict[str, Any],
        view: str = "current_at_snapshot",
    ) -> list[dict[str, Any]]:
        if not row.get("ok") or not row.get("candidate_handle"):
            return []
        version = row["value"]
        body = version["content"]
        units = [
            {
                "type": "record",
                "record_id": row["id"],
                "read_handle": row["candidate_handle"],
                "revision": version["revision"],
                "committed_at": version.get("committed_at"),
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
        if view == "current_at_snapshot":
            index = self.service.history_index(row["id"])
            explicit = self.read_interface == "explicit_selectors_v1" \
                or self.memory_view_mode != "legacy"
            # A bounded index exposes actual saved revision identities, not old
            # bodies or captured requests. The existing read tools fetch those
            # bodies under the same owner, visibility, budget and cursor rules.
            units[0]["stored_history"] = {
                key: index[key]
                for key in ("status", "revision_count", "revisions", "omitted_count")
                if key in index
            }
            if index.get("ok") and index["status"] == "available":
                units[0]["stored_history"].update(
                    current_revision_at_index=index["current_revision_at_snapshot"],
                    index_next_cursor=index["next_cursor"],
                    read={
                        "tool": "read_memory_history" if explicit else "read_memory",
                        "arguments": {
                            "record_id": row["id"],
                            **({} if explicit else {"history": True}),
                        },
                    },
                    revision_tool="read_memory_revision" if explicit else "read_memory",
                    body_page_tool="read_page" if explicit else "read_memory",
                )
        return units

    def _view_key(self, config: RunnableConfig) -> str:
        bound = self._binding(config)
        return "memory-view:" + reference_key([bound["session"], bound["message_id"]])

    def view_state(self, config: RunnableConfig) -> dict[str, Any]:
        """Return reference-only selection; read coverage remains in existing read receipts."""
        stored = self.service.store.get(namespace(self.service), self._view_key(config))
        return copy.deepcopy(stored.value) if stored else empty_view()

    def focus_view(
        self, config: RunnableConfig, *, focus: Any = None,
        read_goal: str | dict[str, Any] | StructuredReadGoal | None = None,
        resident_refs: list[dict[str, Any]] | None = None,
        pending_refs: list[Any] | None = None,
    ) -> dict[str, Any]:
        state = self.view_state(config)
        state["focus"], state["read_goal"] = focus, normalize_read_goal(read_goal)
        if resident_refs is not None:
            state["resident_refs"] = copy.deepcopy(resident_refs)
        if pending_refs is not None:
            state["pending_refs"] = copy.deepcopy(pending_refs)
        self.service.store.put(namespace(self.service), self._view_key(config), state, index=False)
        return copy.deepcopy(state)

    def _note_view_page(
        self, config: RunnableConfig, result: dict[str, Any], *,
        keep_resident: bool = False, refresh_current: bool = False,
        read_goal: str | dict[str, Any] | StructuredReadGoal | None = None,
    ) -> None:
        if self.memory_view_mode == "legacy" or not result.get("ok"):
            return
        refs = result.get("view_refs", [])
        if not refs and read_goal is None:
            return
        state = self.view_state(config)
        if refresh_current:
            affected = {ref["id"] for ref in refs if ref["kind"] == "record"}
            state["resident_refs"] = [
                ref for ref in state["resident_refs"]
                if ref["kind"] != "record" or ref["id"] not in affected
                or ref["view"] != "current_at_snapshot"
            ]
        state = admit_refs(state, refs, keep_resident=keep_resident or refresh_current)
        if read_goal is not None:
            state["read_goal"] = normalize_read_goal(read_goal)
        self.service.store.put(namespace(self.service), self._view_key(config), state, index=False)

    def resident_items(self, config: RunnableConfig) -> list[dict[str, Any]]:
        """Reload delivered units through original Source/record visibility boundaries."""
        items = []
        for ref in self.view_state(config)["resident_refs"]:
            snapshot = self.service.store.get(namespace(self.service), ref["snapshot_id"])
            if snapshot is None:
                continue
            unit = copy.deepcopy(snapshot.value["items"][ref["unit_index"]])
            if unit["type"] == "fragment":
                try:
                    self.service.source_fragment(unit["fragment_handle"])
                except ValueError:
                    continue
            else:
                row = self.service.read(unit["record_id"], unit["revision"])
                if not row.get("ok"):
                    continue
                if unit["version_view"] == "current_at_snapshot":
                    current = self.service.read(unit["record_id"])
                    if current.get("ok") and current["value"]["revision"] != unit["revision"]:
                        unit["version_view"] = "historical_exact_revision"
            items.append(unit)
        return items

    def _deduplicate(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Subtract only already delivered intervals of this exact Source/body version."""
        seen: dict[tuple[str, int], list[tuple[int, int]]] = {}
        result = []
        for unit in units:
            if unit["type"] != "fragment":
                result.append(unit)
                continue
            identity = (unit["source_ref"], unit.get("source_revision", 1))
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
            {
                **unit,
                "input_relation": (
                    "current_request"
                    if unit["source_ref"] == binding["source_ref"]
                    else "archived_source"
                ),
            }
            if unit["type"] == "fragment"
            else unit
            for unit in items
        ]
        payload = {
            "binding": binding,
            "policy": self.policy,
            "kind": kind,
            "forget_epoch": self.forget_epoch,
            "items": items,
        }
        key = "snapshot-" + str(uuid.uuid4())
        prior = self.service.store.get(namespace(self.service), key)
        if prior is not None and prior.value != payload:
            raise FunctionalIntegrityError("V13_5_SNAPSHOT_COLLISION")
        if prior is None:
            self.service.store.put(namespace(self.service), key, payload, index=False)
        return key

    @staticmethod
    def _read_only_metadata(items: list[dict[str, Any]]) -> dict[str, Any]:
        record_ids = list(
            dict.fromkeys(unit["record_id"] for unit in items if unit["type"] == "record")
        )
        return {
            "operation_effect": "read_only",
            "semantic_write_performed": False,
            "delivered_semantic_record_ids": record_ids,
            "delivered_semantic_record_count": len(record_ids),
            "delivered_semantic_record_units": sum(unit["type"] == "record" for unit in items),
            "delivered_raw_fragment_count": sum(unit["type"] == "fragment" for unit in items),
            "delivery_count_scope": "this_packet_items_only_not_owner_total_or_writes",
            "record_unit_scope": "a_unit_may_be_only_part_of_one_original_stored_revision_body",
            "formation_evidence": (
                "Successful save_memory/update_memory receipt; "
                "raw capture/search/read is not formation"
            ),
            "evidence_contract": {
                "fragment_verification": "exact_original_span_only_not_semantic_support",
                "new_values": "must_be_directly_supported_by_selected_fragments",
                "trigger_binding": "execution_attribution_not_field_evidence",
                "input_relation": "timing_only_not_automatic_evidence",
                "stored_history": (
                    "Current absence does not prove never saved. For past saves use "
                    "stored_history.read or an exact revision. Historical reads are not current. "
                    "committed_at is storage time, not reported/effective time. "
                    "Body next_cursor is not index_next_cursor."
                ),
                "missing_material": (
                    "Visible evidence only. A missing match cannot establish never supplied, "
                    "forgotten or erased. Absence reason is unknown without topic-bound evidence."
                ),
            },
        }

    def _project_read_packet(self, packet: dict[str, Any]) -> dict[str, Any]:
        """Project exactly this delivered page before counting its full cost."""
        return packet

    def _page(self, key: str, start: int, binding: dict[str, Any]) -> dict[str, Any]:
        stored = self.service.store.get(namespace(self.service), key)
        if stored is None:
            raise FunctionalRejection("V13_5_SNAPSHOT_NOT_ISSUED_OR_CHANGED")
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
        directory = value["kind"].endswith("_catalog")
        target_mapping = (
            request_target_mapping(self.service, binding)
            if self.memory_view_mode != "legacy" else None
        )

        def packet(end: int) -> dict[str, Any]:
            bodies = [unit for unit in chosen if not unit["type"].endswith("_candidate")]
            candidates = [copy.deepcopy(unit) for unit in chosen
                          if unit["type"].endswith("_candidate")]
            if self.read_interface == "explicit_selectors_v1":
                for candidate in candidates:
                    if candidate["read"]["arguments"].get("revision") is not None:
                        candidate["read"]["tool"] = "read_memory_revision"
            result = {
                "ok": True,
                "schema": "functional_material_v1",
                "snapshot_id": key,
                "kind": value["kind"],
                **(
                    {
                        "support_context": {
                            "selection_status": "read_preview_not_committed_field_support",
                            "target": "record_units_are_the_exact_read_version_not_new_evidence",
                            "unchanged_fields": "inherit_only_their_own_visible_prior_support",
                            "changed_fields": "select_originals_for_each_change_at_write_time",
                            "qualifications": "retain_unmodified_limits_unless_selected_correction_"
                            "changes_or_cancels_them; unknown_time_is_not_current_effect",
                            "context_vs_outcome": "select_both_when_the_assertion_uses_both; "
                            "a_request_is_not_an_executed_result",
                        }
                    }
                    if value["kind"] == "support_context"
                    else {}
                ),
                "items": bodies,
                **({
                    "candidates": candidates,
                    "candidate_count": len(candidates),
                    "candidate_scope": "navigation_only_not_body_read_or_fact_support",
                } if directory else {}),
                **({
                    "view_refs": [item_ref(unit, key, items.index(unit)) for unit in bodies],
                    "reading_basis": read_evidence_basis(bodies),
                } if self.memory_view_mode != "legacy" else {}),
                "start": start,
                "delivered_units": len(bodies),
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
                **self._read_only_metadata(bodies),
                "delivery_status": ("partial_with_omissions" if skipped else "partial")
                if end < len(items)
                else ("snapshot_end_with_omissions" if skipped else "complete_snapshot"),
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
            if target_mapping is not None:
                result, _ = project_request_targets(target_mapping, result)
            return self._project_read_packet(result)

        end = start
        for index, unit in enumerate(items[start:], start):
            if unit["type"] == "source_candidate":
                if self.service.source(unit["source_ref"]) is None:
                    raise FunctionalIntegrityError("V13_5_SNAPSHOT_SOURCE_CHANGED")
            elif unit["type"] == "fragment":
                actual = self.service.source_fragment(unit["fragment_handle"])
                if actual["source_ref"] != unit["source_ref"] or actual.get(
                    "source_revision", 1
                ) != unit.get("source_revision", 1):
                    raise FunctionalIntegrityError("V13_5_SNAPSHOT_SOURCE_CHANGED")
            else:
                row = self.service.read(unit["record_id"], unit["revision"])
                if not row["ok"] or row["value"]["revision"] != unit["revision"]:
                    raise FunctionalIntegrityError("V13_5_SNAPSHOT_RECORD_UNAVAILABLE")
            chosen.append(unit)
            required = self.token_count(canonical(packet(index + 1)))
            if required > self.material_limit:
                chosen.pop()
                if chosen or skipped:
                    break
                # Never return a cursor stuck at the same impossible unit. The
                # original snapshot is unchanged and the omission is explicit.
                alternate = (
                    [unit["source_ref"]]
                    if unit["type"] == "fragment"
                    else unit.get("source_refs", [])
                )
                skipped.append(
                    {
                        "unit_index": index,
                        "type": unit["type"],
                        "reason": "unit_exceeds_material_limit",
                        "required_packet_tokens": required,
                        "snapshot_body_delivered": False,
                        "retry_same_unit_under_same_limit": False,
                        "alternative": {
                            "tool": "read_source",
                            "source_ref": alternate[0],
                            "meaning": "original_support_not_semantic_record_body",
                        }
                        if alternate
                        else None,
                    }
                )
            end = index + 1
        result = packet(end)
        if self.token_count(canonical(result)) > self.material_limit:
            raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT")
        refs = [
            ref
            for unit in chosen if not unit["type"].endswith("_candidate")
            for ref in ([unit["source_ref"]] if unit["type"] == "fragment" else unit["source_refs"])
        ]
        with self.service._locked():
            note_exposure(self.service, binding["source_ref"], refs)
        return result

    def context(
        self,
        session: str,
        turn_id: str,
        config_version: str,
        *,
        query: str | None = None,
    ) -> dict[str, Any]:
        ref = self.service.event_id(session, turn_id, "user")
        event = self.service.source(ref)
        if event is None:
            event = self.service.active_public_input(session, turn_id, config_version)
        if event is None or event["role"] != "user":
            raise FunctionalRejection("V13_5_CAPTURE_REQUIRED")
        actual_query = (
            event["content"] if isinstance(event["content"], str) else canonical(event["content"])
        )
        if query is not None and query != actual_query:
            raise FunctionalRejection("V13_5_PUBLIC_QUERY_CHANGED")
        prior = self.service.store.get(
            self.service.turns_namespace, reference_key([session, turn_id])
        )
        bound = self.service.bind_public_turn(
            session,
            turn_id,
            ref,
            config_version=config_version,
            phase="resume" if prior else "start",
        )
        key = "ordinary:" + reference_key([session, turn_id, self.forget_epoch])
        cached = self.service.store.get(namespace(self.service), key)
        if cached is None:
            units = self._search_units(actual_query, ref)
            if self.recent_context != "disabled" and self.retrieval_candidates is None:
                # Public captured events only, same owner/bank (v1 also session), after visibility
                # filtering. Fixed supplied candidate pools keep their exact order.
                recent_session = session if self.recent_context == "session_events_v1" else None
                recent = sorted(
                    (
                        source
                        for source in self.service.sources(recent_session)
                        if source["event_id"] != ref and source["role"] in {"user", "assistant"}
                    ),
                    key=lambda source: (source["observed_at"], source["event_id"]),
                )[-4:]
                fragments = [
                    {"type": "fragment", **fragment}
                    for source in recent
                    for fragment in self.service.source_fragments(
                        source["event_id"], max_chars=self.fragment_chars
                    )
                ]
                current = [unit for unit in units if unit.get("source_ref") == ref]
                recent_records = []
                if self.recent_context == "bank_recent_v2":
                    rows = sorted(
                        (row for row in self.service.records() if row.get("ok")),
                        key=lambda row: (row["value"].get("committed_at", ""), row["id"]),
                    )[-4:]
                    recent_records = [
                        unit for row in reversed(rows) for unit in self._record_units(row)
                    ]
                recent_ids = {unit["record_id"] for unit in recent_records}
                units = self._deduplicate(
                    current
                    + recent_records
                    + fragments
                    + [unit for unit in units if unit.get("record_id") not in recent_ids]
                )
            snapshot = self._snapshot(bound, units, "ordinary")
            self.service.store.put(
                namespace(self.service), key, {"snapshot": snapshot}, index=False
            )
        else:
            snapshot = cached.value["snapshot"]
        if self.memory_view_mode == "legacy":
            return self._deliver_request_targets(bound, self._page(snapshot, 0, bound))
        cached = self.service.store.get(namespace(self.service), key)
        assert cached is not None
        catalog_snapshot = cached.value.get("catalog_snapshot")
        if catalog_snapshot is None:
            stored = self.service.store.get(namespace(self.service), snapshot)
            assert stored is not None
            current = [unit for unit in stored.value["items"] if unit.get("source_ref") == ref]
            candidates = catalog_candidates([
                unit for unit in stored.value["items"] if unit.get("source_ref") != ref
            ])
            catalog_snapshot = self._snapshot(bound, current + candidates, "ordinary_catalog")
            self.service.store.put(namespace(self.service), key, {
                **cached.value, "catalog_snapshot": catalog_snapshot,
            }, index=False)
        page = self._page(catalog_snapshot, 0, bound)
        config: RunnableConfig = {"configurable": {
            "user_id": self.service.owner, "v13_session": session,
            "v13_turn_id": turn_id, "v13_config_version": config_version,
        }}
        # Refreshing the public-input directory is not a new matter selection.
        # Retain actual pages selected by a preceding read in this request.
        self._note_view_page(config, page, keep_resident=True)
        return self._deliver_request_targets(bound, page)

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
        if self.formation_support_review is not None:
            self.service.prepare_proposal(bound["session"], operation_id, proposal)
            existing = self._run_support_review(
                self.formation_support_review,
                self._formation_evidence(bound, proposal, operation_id),
                bound,
                refs,
                operation_id,
                requested,
            )
            if existing is not None:
                return existing
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
        review_before_commit: bool = False,
        review_token: str | None = None,
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
            matching = [
                selected
                for field, selected in selections.items()
                if path == field or path.startswith(field + ".") or field.startswith(path + ".")
            ]
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
            selected_changes = [
                support[path]
                for path in after
                if path not in before or canonical(before[path]) != canonical(after[path])
            ] + list(removed.values())
            if retract:
                selected_changes.append(fragment_handles or [])
                if self.formation_interface in {"anchored_assertion_v2", "anchored_assertion_v3"}:
                    self._require_distinct_withdrawal_support(old, fragment_handles or [])
            for selected in selected_changes:
                fragment_support(self.service, selected)
            new = fragment_support(
                self.service,
                list(dict.fromkeys(handle for selected in selected_changes for handle in selected)),
            )
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
        if review_before_commit and not equal:
            preview = self._review_revision(bound, proposal, old, review_token)
            if preview is not None:
                return preview
        if self.revision_support_review is not None and not equal:
            self.service.prepare_proposal(bound["session"], operation_id, proposal)
            existing = self._run_support_review(
                self.revision_support_review,
                self._revision_evidence(bound, proposal, old, operation_id),
                bound,
                proposal["source_refs"],
                operation_id,
                requested,
            )
            if existing is not None:
                return existing
        return self._commit(bound["session"], operation_id, proposal)

    def _run_support_review(
        self,
        review: Callable[[dict[str, Any], Callable[[], None]], None],
        evidence: dict[str, Any],
        bound: dict[str, Any],
        source_refs: list[str],
        operation_id: str,
        requested: dict[str, Any],
    ) -> dict[str, Any] | None:
        def note_review_delivery() -> None:
            # A returned review can inform the final answer, including a refusal.
            # Independent input remains the exposure anchor, not derived content.
            with self.service._locked():
                note_exposure(self.service, bound["source_ref"], source_refs)

        if self.semantic_reproposal_policy == "maintenance_two_proposals_v1":
            return bounded_support_review(
                self.service,
                bound,
                evidence,
                operation_id,
                requested,
                lambda: review(evidence, note_review_delivery),
            )
        review(evidence, note_review_delivery)
        return None

    def _formation_evidence(
        self,
        bound: dict[str, Any],
        proposal: dict[str, Any],
        proposal_id: str,
    ) -> dict[str, Any]:
        """Review newly asserted content and scope using only actual selected sources."""
        fields = {"content": proposal["content"], **scope_leaves(proposal["scope"])}
        changes = []
        for field, value in fields.items():
            quotes = fragment_support(self.service, proposal["functional_support"][field])["quotes"]
            for quote in quotes:
                source = self.service.source(quote["source_ref"])
                if source is None:
                    raise FunctionalRejection("V13_5_FORMATION_REVIEW_SOURCE_UNAVAILABLE")
                quote["source_role"] = source["role"]
            changes.append(
                {
                    "field": field,
                    "before": None,
                    "after": value,
                    "before_present": False,
                    "after_present": True,
                    "selected_original_fragments": quotes,
                }
            )
        return {
            "schema": "functional_formation_evidence_v1",
            "binding": bound,
            "proposal_id": proposal_id,
            "forget_epoch": self.forget_epoch,
            "record_id": None,
            "basis": proposal["basis"],
            "changes": changes,
            "semantic_support": "unchecked",
        }

    def _revision_evidence(
        self,
        bound: dict[str, Any],
        proposal: dict[str, Any],
        old: dict[str, Any],
        proposal_id: str,
    ) -> dict[str, Any]:
        """Provide actual deltas and selected originals to an injected precommit review.

        The trigger binds this request but is not silently added as field evidence.
        A review is a model assessment, not a certificate attached to stored support.
        """
        before = {**scope_leaves(old["scope"]), **{k: old[k] for k in ("content", "kind", "basis")}}
        after = {
            **scope_leaves(proposal["scope"]),
            **{k: proposal[k] for k in ("content", "kind", "basis")},
        }
        changes = []
        for field in sorted(before.keys() | after.keys()):
            if (
                field in before
                and field in after
                and canonical(before[field]) == canonical(after[field])
            ):
                continue
            selected = (
                proposal["functional_support"][field]
                if field in after
                else proposal["removed_field_support"][field]
            )
            changes.append(
                {
                    "field": field,
                    "before": before.get(field),
                    "after": after.get(field),
                    "before_present": field in before,
                    "after_present": field in after,
                    "selected_original_fragments": fragment_support(self.service, selected)[
                        "quotes"
                    ],
                }
            )
        if proposal["patch_operation"] == "retract":
            changes.append(
                {
                    "field": "record",
                    "before": "active",
                    "after": "withdrawn",
                    "before_present": True,
                    "after_present": True,
                    "selected_original_fragments": fragment_support(
                        self.service, proposal["removed_field_support"]["record"]
                    )["quotes"],
                }
            )
        for change in changes:
            for quote in change["selected_original_fragments"]:
                source = self.service.source(quote["source_ref"])
                if source is None:
                    raise FunctionalRejection("V13_5_REVISION_REVIEW_SOURCE_UNAVAILABLE")
                quote["source_role"] = source["role"]
        return {
            "schema": "functional_revision_evidence_v1",
            "binding": bound,
            "proposal_id": proposal_id,
            "forget_epoch": self.forget_epoch,
            "record_id": proposal["id"],
            "read_handle": proposal["candidate_handle"],
            "read_revision": old["revision"],
            "old_content": old["content"],
            "old_scope": old["scope"],
            "changes": changes,
            "semantic_support": "unchecked",
        }

    def _review_revision(
        self,
        bound: dict[str, Any],
        proposal: dict[str, Any],
        old: dict[str, Any],
        review_token: str | None,
    ) -> dict[str, Any] | None:
        """Expose the exact proposed diff and selected originals before any fact write.

        The issued token binds a preview, not semantic truth. It never substitutes
        evidence, grants business permission, or turns an old assertion into a correction.
        """
        identity = {
            "binding": bound,
            "proposal": proposal,
            "policy": self.policy,
            "forget_epoch": self.forget_epoch,
        }
        if review_token is not None:
            issued = self.service.store.get(namespace(self.service), review_token)
            # Compare the supplied preview once at its mutation boundary.
            if issued is None or issued.value != identity:
                raise FunctionalRejection("V13_5_REVISION_REVIEW_NOT_ISSUED_OR_CHANGED")
            return None
        token = "revision-review-" + str(uuid.uuid4())
        before = {**scope_leaves(old["scope"]), **{k: old[k] for k in ("content", "kind", "basis")}}
        after = {
            **scope_leaves(proposal["scope"]),
            **{k: proposal[k] for k in ("content", "kind", "basis")},
        }
        old_support = self._source_support(old)
        rows = []
        for field in sorted(before.keys() | after.keys()):
            if (
                field in before
                and field in after
                and canonical(before[field]) == canonical(after[field])
            ):
                continue
            selected = (
                proposal["functional_support"][field]
                if field in after
                else proposal["removed_field_support"][field]
            )
            rows.append(
                {
                    "field": field,
                    "before": before.get(field),
                    "after": after.get(field),
                    "removed": field not in after,
                    "selected_original_fragments": fragment_support(self.service, selected)[
                        "quotes"
                    ],
                    "same_selection_as_prior_field_support": set(selected)
                    == set(old_support.get(field, [])),
                }
            )
        if proposal["patch_operation"] == "retract":
            rows.append(
                {
                    "field": "record",
                    "before": "active",
                    "after": "withdrawn",
                    "selected_original_fragments": fragment_support(
                        self.service, proposal["removed_field_support"]["record"]
                    )["quotes"],
                }
            )
        result = {
            "ok": True,
            "status": "revision_review_required",
            "effect": "none",
            "semantic_write_performed": False,
            "formation_status": "pending",
            "record_id": proposal["id"],
            "read_revision": old["revision"],
            "old_content": old["content"],
            "old_scope": old["scope"],
            "proposed_changes": rows,
            "review_token": token,
            "semantic_support": "unchecked",
            "next_step": (
                "No revision has been committed. Compare EACH new value with its selected "
                "ORIGINAL TEXT below. If it only states the superseded value, select actual "
                "correction evidence and request a new preview without review_token. "
                "Keep unchanged limits, exceptions and uncertainty. A matching prior "
                "selection is a factual warning, not automatic rejection: the same source "
                "can support a legitimate reinterpretation. If all proposed changes are "
                "supported as written, call update_memory with exactly the same arguments "
                "and this review_token to commit. Current input is not automatically evidence."
            ),
        }
        if self.token_count(canonical(result)) > self.material_limit:
            raise FunctionalRejection("V13_5_REVISION_REVIEW_EXCEEDS_MATERIAL_LIMIT")
        with self.service._locked():
            self.service.store.put(namespace(self.service), token, identity, index=False)
            note_exposure(self.service, bound["source_ref"], proposal["source_refs"])
        return result

    def _require_distinct_withdrawal_support(
        self,
        old: dict[str, Any],
        handles: list[str],
    ) -> None:
        """A withdrawal needs a witness beyond the preserved affirmation's spans.

        This is a provenance constraint, not an entailment test. An archived event
        or another span in the same Source can qualify; current input is not added.
        Ordinary revisions and exact no_change do not use this constraint.
        """
        selected = fragment_support(self.service, handles)
        prior = [
            quote
            for support in old.get("functional_support", {}).values()
            for quote in support.get("quotes", [])
        ]
        if not prior:
            raise FunctionalRejection("V13_5_WITHDRAWAL_PRIOR_SUPPORT_UNAVAILABLE")
        identity = ("source_ref", "source_revision")
        for quote in selected["quotes"]:
            covered_until = quote["start"]
            intervals = sorted(
                (p["start"], p["end"])
                for p in prior
                if all(p[key] == quote[key] for key in identity)
            )
            for start, end in intervals:
                if start > covered_until:
                    break
                covered_until = max(covered_until, end)
            if covered_until < quote["end"]:
                return
        raise FunctionalRejection(
            "V13_5_WITHDRAWAL_REUSES_ONLY_PRIOR_SUPPORT: select an actual cancellation "
            "witness beyond the record's existing affirmative support ranges; an archived "
            "event or a different span in the same Source is allowed. No source was added "
            "or substituted and no withdrawal was committed. Distinctness does not verify meaning."
        )

    def _cue_handles(self, cues: list[FragmentCue]) -> list[str]:
        if not cues:
            return []  # Only an exact no_change may omit selected evidence.
        handles = [cue.fragment_handle for cue in cues]
        selected = fragment_support(self.service, handles)
        for cue, quote in zip(cues, selected["quotes"], strict=True):
            if not cue.supporting_words.strip() or cue.supporting_words not in quote["content"]:
                raise FunctionalRejection(
                    "V13_5_EVIDENCE_CUE_NOT_IN_SELECTED_FRAGMENT: "
                    + cue.fragment_handle
                    + "; select the original fragment containing your literal supporting_words; "
                    "no source was substituted and no revision was committed"
                )
        return handles

    def _read(
        self,
        config: RunnableConfig,
        call_id: str,
        arguments: dict[str, Any],
        action: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        bound = self._binding(config)
        if "read_goal" in arguments:
            arguments = {**arguments, "read_goal": normalize_read_goal(arguments["read_goal"])}
        key = "read-admission:" + reference_key([bound["session"], bound["message_id"]])

        def unknown(error: Exception, phase: str) -> dict[str, Any]:
            result = {
                "ok": False, "status": "read_outcome_unknown",
                "error_type": type(error).__name__, "phase": phase,
                "read_state_effect": "unconfirmed", "retryable": False,
                **self._read_only_metadata([]),
            }
            if self.token_count(canonical(result)) > self.material_limit:
                raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT") from error
            return result

        def persist(result: dict[str, Any]) -> None:
            with self.service._locked():
                current = self.service.store.get(namespace(self.service), key)
                assert current is not None
                current.value["calls"][call_id]["result"] = result
                self.service.store.put(namespace(self.service), key, current.value, index=False)

        def deliver(result: dict[str, Any]) -> dict[str, Any]:
            # A cached unknown is never a new delivery or permission to retry.
            if not result.get("ok"):
                return result
            try:
                self._note_view_page(
                    config, result, keep_resident=arguments.get("keep_resident", False),
                    read_goal=arguments.get("read_goal"),
                )
                result = self._deliver_request_targets(bound, result, from_tool=True)
            except Exception as error:
                result = unknown(error, "target_delivery_persistence")
            try:
                persist(result)
            except Exception as error:
                return unknown(error, "read_receipt_persistence")
            return result

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
                    replay = cast(dict[str, Any], previous["result"])
                    return deliver(replay)
                raise FunctionalIntegrityError("V13_5_READ_OUTCOME_UNKNOWN")
            if len(state["calls"]) >= self.read_limit:
                exhausted = {
                    "ok": False,
                    "status": "read_limit_exhausted",
                    "limit": self.read_limit,
                    **self._read_only_metadata([]),
                }
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
            result = {
                "ok": False,
                "status": "read_integrity_error"
                if isinstance(error, FunctionalIntegrityError)
                else "read_outcome_unknown",
                "error_type": type(error).__name__,
                "phase": "read_action",
                "read_state_effect": "unconfirmed",
                "retryable": False,
            }
        if result.get("schema") != "functional_material_v1":
            # Failed reads delivered no items; zero is a delivery count, not a
            # claim that the owner has no records or that the lookup succeeded.
            result = {**result, **self._read_only_metadata([])}
            if self.token_count(canonical(result)) > self.material_limit:
                raise FunctionalRejection("V13_5_MATERIAL_WRAPPER_EXCEEDS_LIMIT")
        # Persist the original result before any adapter remembers evidence or
        # signs targets. An acknowledgement loss cannot certify its delivery.
        try:
            persist(result)
        except Exception as error:
            return unknown(error, "read_receipt_persistence")
        return deliver(result)

    def read_support_context(
        self,
        config: RunnableConfig,
        call_id: str,
        fragment_handles: list[str] | None = None,
        read_handle: str | None = None,
        *, targets: list[str] | None = None, keep_resident: bool = False,
        read_goal: str | dict[str, Any] | StructuredReadGoal | None = None,
    ) -> dict[str, Any]:
        """Present actual selected sources and an optional exact target without writing."""

        def action(bound: dict[str, Any]) -> dict[str, Any]:
            if not self.support_context:
                raise FunctionalRejection("V13_5_SUPPORT_CONTEXT_DISABLED")
            selected_fragments, selected_record = fragment_handles or [], read_handle
            if targets is not None:
                selected = [
                    resolve_request_target(self.service, bound, target) for target in targets
                ]
                records = [row for row in selected if row['kind'] == 'delivered_record']
                sources = [row for row in selected if row['kind'] == 'delivered_source']
                if len(records) > 1 or len(records) + len(sources) != len(selected):
                    raise FunctionalRejection("V13_5_REQUEST_TARGET_KIND_INVALID")
                selected_fragments = [row['credentials']['fragment_handle'] for row in sources]
                selected_record = records[0]['credentials']['read_handle'] if records else None
            # Exact fragment selections remain exact; navigation never expands them.
            fragment_support(self.service, selected_fragments)
            units = []
            if selected_record is not None:
                candidate = self.service.candidate(selected_record)
                if candidate is None:
                    raise FunctionalRejection("V13_5_READ_HANDLE_INVALID")
                row = self.service.read(candidate["record_id"], candidate["revision"])
                if not row.get("ok"):
                    raise FunctionalRejection("V13_5_RECORD_UNAVAILABLE")
                units.extend(self._record_units(row, "read_target_exact_revision"))
                # The old support identities are context only, never selected for a new value.
                prior = {
                    field: [
                        {
                            k: quote[k]
                            for k in (
                                "source_ref",
                                "source_revision",
                                "fragment_handle",
                                "start",
                                "end",
                            )
                            if k in quote
                        }
                        for quote in support["quotes"]
                    ]
                    for field, support in row["value"].get("functional_support", {}).items()
                }
                for unit in units:
                    unit["prior_field_support_identity"] = prior
            units.extend(
                {"type": "fragment", **self.service.source_fragment(handle)}
                for handle in selected_fragments
            )
            return self._page(self._snapshot(bound, units, "support_context"), 0, bound)

        return self._read(
            config,
            call_id,
            ({"tool": "read_support_context", "targets": targets,
              "keep_resident": keep_resident,
              **({"read_goal": normalize_read_goal(read_goal)} if read_goal is not None else {})}
             if targets is not None else {
                "tool": "read_support_context",
                "read_handle": read_handle,
                "fragment_handles": fragment_handles,
            }),
            action,
        )

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
                    **(
                        {
                            "review_status": error.review_status,
                            "review_proposal_id": error.proposal_id,
                            "review_failure_type": error.failure_type,
                            "review_budget_exhausted": error.failure_type == "BudgetExceeded",
                            "phase": "precommit_support_review",
                        }
                        if isinstance(error, FunctionalReviewRejection)
                        else {}
                    ),
                    **(
                        {"maintenance": error.details, "phase": "precommit_maintenance_allowance"}
                        if isinstance(error, FunctionalMaintenanceRejection)
                        else {}
                    ),
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
                    "phase": error.phase
                    if isinstance(error, FunctionalOperationError)
                    else "mutation_preparation",
                    "error_category": "integrity"
                    if isinstance(cause, FunctionalIntegrityError)
                    else "unconfirmed_effect",
                    "recovery": "same_operation_id_only",
                }

        def save_memory(
            content: Annotated[
                str,
                Field(
                    description=(
                        "Faithful assertion with all applicability limits, exceptions, "
                        "negation and uncertainty retained in the text itself. "
                        "Keep source wording for restrictive "
                        "phrases; do not generalize one occurrence into a class or a lasting "
                        "preference."
                    )
                ),
            ],
            fragment_handles: list[str],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            scope: Annotated[
                dict[str, Any] | None,
                Field(
                    description=(
                        "Only explicitly supported applicability boundaries. "
                        "Preserve the particular occurrence rather than merely its category. "
                        "Do not invent project names or use scope for summary labels. "
                        "Omit absent boundaries; keep unknown dates unknown. "
                        "These fields must agree with the restrictions retained in content."
                    )
                ),
            ] = None,
        ) -> ToolMessage:
            """Save semantic memory using issued fragments and their original source/version/span.

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
            content: str,
            fragment_handles: list[str],
            config: RunnableConfig,
            *,
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
                    config,
                    tool_call_id,
                    read_handle,
                    [change.model_dump(exclude_unset=True) for change in changes],
                    fragment_handles,
                    retract=retract,
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
            In a staged/state-driven view, candidates only navigate: open selected
            record_id/source_ref with the existing read tools for its actual body.
            """
            return message(
                "search_memory",
                tool_call_id,
                self._read(
                    config,
                    tool_call_id,
                    {"tool": "search_memory", "query": query},
                    lambda bound: self._page(
                        self._snapshot(
                            bound,
                            self._search_units(query) if self.memory_view_mode == "legacy"
                            else catalog_candidates(self._search_units(query)),
                            "explicit_search" if self.memory_view_mode == "legacy"
                            else "explicit_search_catalog",
                        ),
                        0,
                        bound,
                    ),
                ),
            )

        def record_read(
            config: RunnableConfig,
            tool_call_id: str,
            request: dict[str, Any],
        ) -> ToolMessage:
            def action(bound: dict[str, Any]) -> dict[str, Any]:
                selected = self._resolve_read_target(bound, request) \
                    if "target" in request else request
                record_id, revision, cursor = (
                    selected.get(k) for k in ("record_id", "revision", "cursor")
                )
                history = selected.get("history", False)
                history_cursor = selected.get("history_cursor")
                if "index_cursor" in selected:
                    return self._history_index_page(bound, str(record_id), selected["index_cursor"])
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
                request["tool"], tool_call_id, self._read(config, tool_call_id, request, action)
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
            keep_resident: bool = False,
            read_goal: str | None = None,
        ) -> ToolMessage:
            """Read current/exact historical revision, or a previously issued cursor.

            history=true reads original stored revision bodies with snapshot pagination.
            A current snapshot omitting content does not establish it was never
            saved. Read the stored history when answering what was saved before.
            History is read-only: do not save an old value as a new or current fact.
            Reading a record or raw fragment performs no semantic write. Only an
            actual successful save_memory/update_memory receipt confirms that effect.
            A cursor always continues its original
            ordinary/explicit snapshot; it never changes to latest results.
            """

            return record_read(
                config,
                tool_call_id,
                {
                    "tool": "read_memory",
                    "record_id": record_id,
                    "revision": revision,
                    "cursor": cursor,
                    "history": history,
                    "history_cursor": history_cursor,
                    **({"keep_resident": keep_resident,
                       **({"read_goal": read_goal} if read_goal is not None else {})}
                       if self.memory_view_mode != "legacy" else {}),
                },
            )

        def source_read(
            config: RunnableConfig,
            tool_call_id: str,
            request: dict[str, Any],
        ) -> ToolMessage:
            def action(bound: dict[str, Any]) -> dict[str, Any]:
                selected = self._resolve_read_target(bound, request) \
                    if "target" in request else request
                fragment_handle, source_ref, cursor = (
                    selected.get(k) for k in ("fragment_handle", "source_ref", "cursor")
                )
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
                request["tool"], tool_call_id, self._read(config, tool_call_id, request, action)
            )

        def read_source(
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            fragment_handle: str | None = None,
            source_ref: str | None = None,
            cursor: str | None = None,
            keep_resident: bool = False,
            read_goal: str | None = None,
        ) -> ToolMessage:
            """Read an issued exact fragment or a full public source group, continuing its cursor.

            Source groups split only at public original boundaries; each page states omissions.
            Original capture/read is not semantic formation. This read never saves;
            a semantic write needs a successful save_memory/update_memory receipt.
            Every call, including a failed call, uses the explicit per-message read allowance.
            """

            return source_read(
                config,
                tool_call_id,
                {
                    "tool": "read_source",
                    "fragment_handle": fragment_handle,
                    "source_ref": source_ref,
                    "cursor": cursor,
                    **({"keep_resident": keep_resident,
                       **({"read_goal": read_goal} if read_goal is not None else {})}
                       if self.memory_view_mode != "legacy" else {}),
                },
            )

        def read_current_memory(
            record_id: str,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            keep_resident: bool = False,
            read_goal: str | None = None,
        ) -> ToolMessage:
            """Read the current version of an issued record ID, without changing it.

            Supply only record_id. For earlier bodies use read_memory_history or
            read_memory_revision: absence here does not establish never saved.
            Continue any next_cursor with read_page.
            Every read uses the shared explicit read allowance; it is not a save.
            """
            return record_read(
                config, tool_call_id, {"tool": "read_memory", "record_id": record_id,
                    **({"keep_resident": keep_resident,
                       **({"read_goal": read_goal} if read_goal is not None else {})}
                       if self.memory_view_mode != "legacy" else {})}
            )

        def read_memory_history(
            record_id: str,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            keep_resident: bool = False,
            read_goal: str | None = None,
        ) -> ToolMessage:
            """Read original stored revision bodies for one issued record ID.

            Supply only record_id. This freezes the visible history for pagination;
            use read_page for next_cursor. Reading old values never makes them
            current or saves them. Uses the shared explicit read allowance.
            """
            return record_read(
                config,
                tool_call_id,
                {"tool": "read_memory_history", "record_id": record_id, "history": True,
                    **({"keep_resident": keep_resident,
                       **({"read_goal": read_goal} if read_goal is not None else {})}
                       if self.memory_view_mode != "legacy" else {})},
            )

        def read_memory_revision(
            record_id: str,
            revision: int,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            keep_resident: bool = False,
            read_goal: str | None = None,
        ) -> ToolMessage:
            """Read one exact stored historical revision without making it current.

            Supply record_id and the actual positive integer revision. To discover
            earlier revisions use read_memory_history. Continue with read_page.
            Uses the shared explicit read allowance; it never saves or updates.
            """
            return record_read(
                config,
                tool_call_id,
                {"tool": "read_memory_revision", "record_id": record_id, "revision": revision,
                    **({"keep_resident": keep_resident,
                       **({"read_goal": read_goal} if read_goal is not None else {})}
                       if self.memory_view_mode != "legacy" else {})},
            )

        def read_source_group(
            source_ref: str,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            keep_resident: bool = False,
            read_goal: str | None = None,
        ) -> ToolMessage:
            """Read a full original source group using its issued source_ref.

            Supply only source_ref; use read_fragment for a fragment_handle, or
            read_page for next_cursor. Sources split at public original boundaries
            and state omissions. Uses the shared read allowance, never a semantic save.
            """
            return source_read(
                config, tool_call_id, {"tool": "read_source", "source_ref": source_ref,
                    **({"keep_resident": keep_resident,
                       **({"read_goal": read_goal} if read_goal is not None else {})}
                       if self.memory_view_mode != "legacy" else {})}
            )

        def read_fragment(
            fragment_handle: str,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            keep_resident: bool = False,
            read_goal: str | None = None,
        ) -> ToolMessage:
            """Read the exact original fragment identified by an issued fragment_handle.

            Supply only fragment_handle. For the full source use read_source with
            its source_ref; continue any next_cursor with read_page. Reading is not
            semantic formation and uses the shared explicit read allowance.
            """
            return source_read(
                config, tool_call_id, {"tool": "read_fragment", "fragment_handle": fragment_handle,
                    **({"keep_resident": keep_resident,
                       **({"read_goal": read_goal} if read_goal is not None else {})}
                       if self.memory_view_mode != "legacy" else {})}
            )

        def read_page(
            cursor: str,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            keep_resident: bool = False,
            read_goal: str | None = None,
        ) -> ToolMessage:
            """Continue an issued next_cursor from ordinary material or any explicit read.

            Supply only cursor. It continues that exact source/search/record/history
            snapshot, never fresh latest results. Visibility revocation still applies.
            Uses the shared explicit read allowance and never writes semantic records.
            """
            return record_read(config, tool_call_id, {"tool": "read_page", "cursor": cursor,
                **({"keep_resident": keep_resident,
                       **({"read_goal": read_goal} if read_goal is not None else {})}
                   if self.memory_view_mode != "legacy" else {})})

        def read_support_context(
            fragment_handles: list[str],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            read_handle: str | None = None,
        ) -> ToolMessage:
            """Read chosen original bodies beside an optional exact target before proposing.

            Select fragments for the actual assertion, including conditions or context,
            and an issued read_handle when revising. Returns the old content/scope and
            prior field-support identities separately from selected original bodies.
            Preserve necessary limits, unknown effective times and source roles; an
            explicit correction can change or cancel an old limit. The current request
            remains the user's instruction, not automatically supporting evidence.
            This is a read-only working view, not approval, a semantic save, or a claim
            that all necessary evidence was selected. Final save/update must explicitly
            select its sources. Omitted bodies remain missing; continue next_cursor with
            read_page. Uses the existing shared additional-read allowance.
            """
            return message(
                "read_support_context",
                tool_call_id,
                self.read_support_context(config, tool_call_id, fragment_handles, read_handle),
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

        def forget_request_targets(
            targets: list[str], config: RunnableConfig, *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            scope: Literal["record", "record_and_sources"] = "record_and_sources",
        ) -> ToolMessage:
            """Forget explicitly selected targets copied from this request's delivered items.

            Select at most one delivered_record target, and any delivered_source targets
            for other original copies. A source selection revokes that whole Source.
            record_and_sources hides the record, support/history/raw fallbacks and derived
            assistant outputs; record alone retains source visibility. This is visibility
            revocation, not physical erasure. Navigation-only targets cannot be forgotten.
            """
            return message("forget_memory", tool_call_id, mutation(
                lambda: self.forget_targets(config, tool_call_id, targets, scope=scope)
            ))

        def update_assertion(
            read_handle: str,
            changes: list[ReplacementChange],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            retract: bool = False,
            fragment_handles: list[str] | None = None,
        ) -> ToolMessage:
            """Update the OLD read target using separately selected evidence for each NEW value.

            read_handle identifies the exact old record/version, not evidence for a change.
            Each changes item supplies field, op, value and evidence_for_new_value.
            Read the selected fragment's ORIGINAL TEXT before choosing it: it must support
            the proposed replacement as written, without mentally editing the source.
            To apply a correction, select evidence containing that correction; citing only
            the superseded statement does not support a changed assertion. Current input
            is not automatically evidence, and a directly supporting older source is valid.
            Preserve unchanged qualifications and select additional support if needed.
            An omitted field retains its prior value/support; null is a value, not removal.
            Only scope.KEY fields allow remove. Same values/empty changes are no_change.
            retract=true with changes=[] uses top-level fragment_handles for withdrawal.
            Quote verification proves original bytes only; semantic support is unchecked.
            """
            return update_memory(
                read_handle,
                [FieldChange.model_validate(c.model_dump(exclude_unset=True)) for c in changes],
                config,
                tool_call_id=tool_call_id,
                retract=retract,
                fragment_handles=fragment_handles,
            )

        def update_assertion_withdrawal(
            read_handle: str,
            changes: list[ReplacementChange],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            retract: bool = False,
            evidence_for_withdrawal: Annotated[
                list[str] | None,
                Field(
                    description=(
                        "Only for retract=true: original fragments that state the WITHDRAWAL. "
                        "The old keep/save statement identifies what is withdrawn but cannot "
                        "support its withdrawal. The read_handle already identifies the target. "
                        "Select the actual withdrawal text, which may be current or archived; "
                        "the current request/trigger is not automatically evidence."
                    )
                ),
            ] = None,
        ) -> ToolMessage:
            """Revise or withdraw the OLD read target with evidence for the actual CHANGE.

            For a revision, each changes item selects evidence_for_new_value whose
            unchanged original text supports the replacement or explicit field removal.
            Keep unchanged qualifications and support; a trigger alone is not evidence.
            For a withdrawal, use retract=true, changes=[] and evidence_for_withdrawal
            containing the actual cancellation. Old affirmation is not cancellation
            evidence. Old content/support stay in history, separate from withdrawal support.
            A directly supporting archived source remains valid; do not blindly choose
            the current input when it is only a query. No value, source or current trigger
            is substituted by the program. Same values/empty changes are no_change.
            Quote verification proves source bytes only; semantic support is unchecked.
            """
            return update_assertion(
                read_handle,
                changes,
                config,
                tool_call_id=tool_call_id,
                retract=retract,
                fragment_handles=evidence_for_withdrawal,
            )

        def reviewed_assertion(
            read_handle: str,
            changes: list[ReplacementChange],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            retract: bool = False,
            evidence_for_withdrawal: list[str] | None = None,
            review_token: str | None = None,
        ) -> ToolMessage:
            """Preview a revision's old/new values and selected original evidence, then commit.

            First omit review_token. No changed fact is written by that preview. Inspect
            EVERY selected original text against its new value; keep unchanged limitations.
            Correct a wrong selection by sending revised arguments without review_token.
            Only when the preview is supported, repeat exactly those arguments with the
            returned review_token. This explicit confirmation commits the revision.
            Per-field evidence_for_new_value supports the new value, not target identity.
            Full withdrawal uses retract=true, changes=[] and evidence_for_withdrawal
            containing actual cancellation. Archived evidence can be valid; current input
            is not automatically evidence. The program verifies bytes, not entailment.
            Same values/empty changes yield exact no_change without a redundant preview.
            """
            return message(
                "update_memory",
                tool_call_id,
                mutation(
                    lambda: self.update(
                        config,
                        tool_call_id,
                        read_handle,
                        [c.model_dump(exclude_unset=True) for c in changes],
                        evidence_for_withdrawal,
                        retract=retract,
                        review_before_commit=True,
                        review_token=review_token,
                    )
                ),
            )

        def anchored_assertion(
            read_handle: str,
            changes: list[AnchoredChange],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            retract: bool = False,
            evidence_for_withdrawal: list[FragmentCue] | None = None,
        ) -> ToolMessage:
            """Update the old target using short original words expressing each actual CHANGE.

            For each change choose evidence_for_new_value entries with fragment_handle and
            supporting_words. Those short verbatim words must express the new assertion
            and occur in that selected fragment. A subject name or superseded statement
            does not support a new value. Preserve unchanged scope, negation and uncertainty.
            Full withdrawal uses retract=true, changes=[] and evidence_for_withdrawal with
            actual cancellation words. Current input is not automatically evidence; archived
            and same-source reinterpretation remain legal when their text supports the change.
            The program extracts complete quotes and checks cue occurrence, not entailment.
            No preview or confirmation token is needed. Same values/empty changes remain
            exact no_change; no automatic replacement of your selected sources occurs.
            """

            def action() -> dict[str, Any]:
                if evidence_for_withdrawal is not None and not retract:
                    raise FunctionalRejection("V13_5_WITHDRAWAL_EVIDENCE_REQUIRES_RETRACT")
                rows = []
                for change in changes:
                    row = change.model_dump(exclude_unset=True)
                    row.pop("evidence_for_new_value")
                    row["fragment_handles"] = self._cue_handles(change.evidence_for_new_value)
                    rows.append(row)
                withdrawal = (
                    self._cue_handles(evidence_for_withdrawal)
                    if evidence_for_withdrawal is not None
                    else None
                )
                return self.update(
                    config, tool_call_id, read_handle, rows, withdrawal, retract=retract
                )

            return message("update_memory", tool_call_id, mutation(action))

        def optional_withdrawal_patch(
            read_handle: str,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            changes: list[AnchoredChange] | None = None,
            retract: bool = False,
            evidence_for_withdrawal: list[FragmentCue] | None = None,
        ) -> ToolMessage:
            """Full withdrawal permits omitted changes; ordinary updates require explicit changes.

            Omitted/null changes means an empty patch only when retract=true. For an
            ordinary update supply changes, including [] for an explicit no_change check.
            Withdrawal still requires actual selected cancellation evidence.
            """
            if changes is None and not retract:

                def reject() -> dict[str, Any]:
                    raise FunctionalRejection("V13_5_NON_WITHDRAWAL_CHANGES_REQUIRED")

                return message("update_memory", tool_call_id, mutation(reject))
            return anchored_assertion(
                read_handle,
                [] if changes is None else changes,
                config,
                tool_call_id=tool_call_id,
                retract=retract,
                evidence_for_withdrawal=evidence_for_withdrawal,
            )

        def confirm_existing_memory(
            read_handle: str,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> ToolMessage:
            """Confirm an already matching current record WITHOUT changing it.

            Use its actual read_handle when the user asks to keep the same record
            and version. This performs the existing exact no_change check: no new
            record, revision, field, source or history is written. A stale, revoked
            or wrong-owner handle cannot confirm the current record. It cannot
            save a new fact, apply a correction or prove the record satisfies the
            whole request. Describe success as already present/unchanged, never
            as a new save. For changed values use update_memory with real evidence.
            """
            return message(
                "confirm_existing_memory",
                tool_call_id,
                mutation(lambda: self.update(config, tool_call_id, read_handle, [])),
            )

        save_tool = (
            StructuredTool.from_function(
                save_assertion, name="save_memory", args_schema=SavedAssertion
            )
            if self.formation_interface
            in {
                "unified_assertion_v1",
                "unified_assertion_v2",
                "unified_assertion_v3",
                "reviewed_assertion_v1",
                "anchored_assertion_v1",
                "anchored_assertion_v2",
                "anchored_assertion_v3",
            }
            else StructuredTool.from_function(save_memory)
        )
        withdrawal_description = (
            str(anchored_assertion.__doc__) + "\nFull-record withdrawal additionally "
            "requires at least one cancellation witness outside the preserved "
            "record's existing support ranges. Repeating only its old affirmation "
            "is rejected even when supporting_words match it. Archived events or "
            "other spans in the same Source remain eligible; no current input is "
            "automatically evidence. If no such witness is available, do not "
            "claim withdrawal success. This restriction does not apply to ordinary "
            "same-source revisions or exact no_change."
            if self.formation_interface in {"anchored_assertion_v2", "anchored_assertion_v3"}
            else None
        )
        if self.formation_interface == "anchored_assertion_v3":
            withdrawal_description = (
                str(withdrawal_description).replace(
                    "retract=true, changes=[] and evidence_for_withdrawal with",
                    "retract=true (changes may be omitted/null, meaning []) and "
                    "evidence_for_withdrawal with",
                )
                + "\n"
                + str(optional_withdrawal_patch.__doc__)
            )
        update_tool = (
            StructuredTool.from_function(
                optional_withdrawal_patch
                if self.formation_interface == "anchored_assertion_v3"
                else anchored_assertion,
                name="update_memory",
                description=withdrawal_description,
            )
            if self.formation_interface
            in {"anchored_assertion_v1", "anchored_assertion_v2", "anchored_assertion_v3"}
            else StructuredTool.from_function(reviewed_assertion, name="update_memory")
            if self.formation_interface == "reviewed_assertion_v1"
            else StructuredTool.from_function(update_assertion_withdrawal, name="update_memory")
            if self.formation_interface == "unified_assertion_v3"
            else StructuredTool.from_function(update_assertion, name="update_memory")
            if self.formation_interface == "unified_assertion_v2"
            else StructuredTool.from_function(update_memory)
        )
        confirmation_tools = (
            (StructuredTool.from_function(confirm_existing_memory),)
            if self.existing_confirmation
            else ()
        )

        def combined_read_tool(function: Callable[..., Any]) -> StructuredTool:
            tool = StructuredTool.from_function(function)
            if self.memory_view_mode == "legacy":
                schema = cast(type[BaseModel], tool.args_schema)
                fields: Any = {
                    name: (field.annotation, copy.deepcopy(field))
                    for name, field in schema.model_fields.items()
                    if name not in {"keep_resident", "read_goal"}
                }
                tool.args_schema = create_model(schema.__name__, **fields)
            return tool

        resident = self.memory_view_mode != "legacy"

        def target_read_tool(name: str, description: str) -> StructuredTool:
            def read_target(
                target: str, config: RunnableConfig, *,
                tool_call_id: Annotated[str, InjectedToolCallId],
                keep_resident: bool = False,
                read_goal: str | StructuredReadGoal | None = None,
                revision: int | None = None,
            ) -> ToolMessage:
                """Read one exactly bound request target through the original read allowance."""
                request: dict[str, Any] = {
                    "tool": name, "target": target, "keep_resident": keep_resident,
                }
                if read_goal is not None:
                    request["read_goal"] = normalize_read_goal(read_goal)
                if revision is not None:
                    request["revision"] = revision
                reader = source_read if name in {"read_source", "read_fragment"} else record_read
                return reader(config, tool_call_id, request)

            return ReadSelectorTool.from_function(
                read_target, name=name, description=description,
                args_schema=ResidentRevisionTargetSelector if name == "read_memory_revision"
                else ResidentTargetSelector,
            )

        def read_support_targets(
            targets: list[str], config: RunnableConfig, *,
            tool_call_id: Annotated[str, InjectedToolCallId], keep_resident: bool = False,
            read_goal: str | StructuredReadGoal | None = None,
        ) -> ToolMessage:
            """Read exactly delivered Source fragments beside at most one delivered record.

            Navigation targets supply no body credentials. This working view performs no
            semantic write or sufficiency judgement and uses the shared read allowance.
            """
            return message("read_support_context", tool_call_id, self.read_support_context(
                config, tool_call_id, targets=targets, keep_resident=keep_resident,
                read_goal=read_goal,
            ))

        read_tools = (
            tuple(target_read_tool(name, description) for name, description in (
                ("read_memory", "Read the current version using an actual record target."),
                ("read_memory_history", "Read the original stored versions using a record target; "
                 "old bodies remain historical. Continue actual next_target with read_page."),
                ("read_memory_revision", "Read one exact revision using its revision target, "
                 "or a current record navigation target and exact revision integer."),
                ("read_source", "Read a full original Source using its actual Source target."),
                ("read_fragment", "Read an exact original fragment using its Source target."),
                ("read_page", "Continue this request's actual next_target or index_next_target; "
                 "its original snapshot and visibility checks remain in force."),
            )) if resident else
            (
                ReadSelectorTool.from_function(
                    read_current_memory, name="read_memory",
                    args_schema=RecordSelector
                ),
                ReadSelectorTool.from_function(
                    read_memory_history,
                    args_schema=RecordSelector,
                ),
                ReadSelectorTool.from_function(
                    read_memory_revision,
                    args_schema=RevisionSelector,
                ),
                ReadSelectorTool.from_function(
                    read_source_group, name="read_source",
                    args_schema=SourceSelector,
                ),
                ReadSelectorTool.from_function(
                    read_fragment,
                    args_schema=FragmentSelector,
                ),
                ReadSelectorTool.from_function(
                    read_page, args_schema=PageSelector,
                ),
            )
            if self.read_interface == "explicit_selectors_v1"
            else (
                combined_read_tool(read_memory),
                combined_read_tool(read_source),
            )
        )
        if resident:
            for read_tool in read_tools:
                read_tool.description += (
                    " Optional read_goal states why the current question needs this read, "
                    "possibly combining applicability, original wording and saved history. "
                    "Omitting it inherits that purpose; opening a source, version or page "
                    "does not change the purpose, evidence or permissions."
                )
        return (
            save_tool,
            update_tool,
            *confirmation_tools,
            StructuredTool.from_function(search_memory),
            *read_tools,
            *(
                (
                    ReadSelectorTool.from_function(
                        read_support_context, args_schema=SupportContextSelector
                    ) if not resident else ReadSelectorTool.from_function(
                        read_support_targets, name="read_support_context",
                        args_schema=ResidentSupportTargetSelector,
                    ),
                )
                if self.support_context
                else ()
            ),
            StructuredTool.from_function(forget_memory)
            if self.memory_view_mode == "legacy" else ReadSelectorTool.from_function(
                forget_request_targets, name="forget_memory", args_schema=ForgetTargetSelector
            ),
        )
