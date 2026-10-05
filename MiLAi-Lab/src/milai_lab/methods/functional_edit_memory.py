"""Opt-in local edit tools on the existing functional Host, Reader and MemoryService.

The plain and conditioned operators are the frozen MiLAi-Edit methods.
This adapter binds them to functional request/receipt contracts. It has no model,
application object, business authorization, reviewer or independent database.
Record scope is retained on updates; scope-only patches are not exposed.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Annotated, Any, Literal

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from pydantic import ValidationError

from milai_lab.memory.edit_units import (
    EditProposal,
    NewRelation,
    NewUnit,
    UnitEdit,
    apply_local,
    form_state,
    render_state,
)
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import (
    FunctionalIntegrityError,
    FunctionalOperationError,
    FunctionalRejection,
    canonical,
    fragment_support,
    namespace,
    scope_leaves,
)
from milai_lab.methods.edit_memory import METHOD_VERSION, EditMemory

FUNCTIONAL_METHOD = "milai_edit_m_v1"
FUNCTIONAL_B1_METHOD = "milai_edit_b1_v1"
INTEGRATION_VERSION = "functional_m_v1"


class FunctionalEditMemory(FunctionalMemory):
    """Use M or B1 in the current flow; default FunctionalMemory is unchanged."""

    def __init__(self, *args: Any, arm: Literal["B1", "M"] = "M", **kwargs: Any) -> None:
        if arm not in {"B1", "M"}:
            raise ValueError("FUNCTIONAL_EDIT_ARM_INVALID")
        super().__init__(*args, **kwargs)
        self.arm = arm
        self.conditioned = arm == "M"
        self.memory_method = FUNCTIONAL_METHOD if self.conditioned else FUNCTIONAL_B1_METHOD
        self.policy["memory_method"] = self.memory_method
        self.policy["integration_version"] = (
            INTEGRATION_VERSION if self.conditioned else "functional_b1_v1"
        )

    def instructions(self) -> str:
        targets = "target_unit/shared_conditions/attach_to" if self.conditioned else "target_unit"
        applicability = (
            "condition/override units express applicability within that scope. "
            if self.conditioned else
            "keep conditions and qualifications in the selected plain text units. "
        )
        return EditMemory(self.service, self.arm).instructions() + (
            "The functional tool signatures replace the proposal envelope: use save_memory "
            "with units/relations/scope, or update_memory with an actual read_handle and edits. "
            "Do not send action/target_record/base_revision to these tools. Copy edit_unit.unit_id "
            f"from Reader records for {targets}. Every evidence[] "
            "string must be an actually delivered source fragment_handle; it is the same issued "
            "range identity as evidence_id. source_ref identifies provenance only and cannot be "
            "used as a fragment handle. A record's evidence_refs metadata does not deliver the "
            "original body again. Read missing originals explicitly. Record scope stays unchanged "
            f"on local edits; {applicability}"
            "confirm_existing_memory confirms an unchanged record, without creating a revision. "
        )

    def note_delivered_fragment_handles(
        self, config: RunnableConfig, fragment_handles: list[str]
    ) -> None:
        """Trusted delivery callback, never an Agent tool or semantic authorization.

        For business ToolMessages the caller supplies only handles from the actual
        delivered source_fragment_index. Merely capturing or indexing a source
        does not call this function. Reader calls register their returned page.
        """
        bound = self._binding(config)
        with self.service._locked():
            for handle in dict.fromkeys(fragment_handles):
                fragment = self.service.source_fragment(handle)
                key = "edit-delivered:" + handle
                reference = {
                    "owner": self.service.owner,
                    "bank": list(self.service.namespace),
                    **{
                        field: fragment[field]
                        for field in ("source_ref", "source_revision", "start", "end")
                    },
                }
                old = self.service.store.get(namespace(self.service), key)
                if old is not None:
                    if old.value["reference"] != reference:
                        raise FunctionalIntegrityError("FUNCTIONAL_EDIT_DELIVERY_REFERENCE_CHANGED")
                    continue
                self.service.store.put(
                    namespace(self.service),
                    key,
                    {"reference": reference, "delivery_binding": bound},
                    index=False,
                )

    def _remember_page(self, config: RunnableConfig, result: dict[str, Any]) -> None:
        if result.get("ok"):
            self.note_delivered_fragment_handles(
                config,
                [
                    unit["fragment_handle"]
                    for unit in result.get("items", [])
                    if unit.get("type") == "fragment"
                ],
            )

    def context(
        self, session: str, turn_id: str, config_version: str, *, query: str | None = None
    ) -> dict[str, Any]:
        result = super().context(session, turn_id, config_version, query=query)
        self._remember_page(
            {
                "configurable": {
                    "user_id": self.service.owner,
                    "v13_session": session,
                    "v13_turn_id": turn_id,
                    "v13_config_version": config_version,
                }
            },
            result,
        )
        return result

    def _read(
        self,
        config: RunnableConfig,
        call_id: str,
        arguments: dict[str, Any],
        action: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        result = super()._read(config, call_id, arguments, action)
        try:
            self._remember_page(config, result)
        except Exception as error:
            return {
                "ok": False,
                "status": "read_outcome_unknown",
                "effect": "unconfirmed",
                "phase": "fragment_delivery_persistence",
                "error_type": type(error).__name__,
                "delivered_raw_fragment_count": 0,
                "recovery": "same_operation_id_only",
            }
        return result

    def _require_delivered(self, handles: list[str]) -> dict[str, Any]:
        support = fragment_support(self.service, handles)
        for handle in dict.fromkeys(handles):
            fragment = self.service.source_fragment(handle)
            issued = self.service.store.get(namespace(self.service), "edit-delivered:" + handle)
            expected = {
                "owner": self.service.owner,
                "bank": list(self.service.namespace),
                **{k: fragment[k] for k in ("source_ref", "source_revision", "start", "end")},
            }
            if issued is None or issued.value.get("reference") != expected:
                raise FunctionalRejection("FUNCTIONAL_EDIT_ACTUALLY_DELIVERED_FRAGMENT_REQUIRED")
        return support

    def _record_units(
        self, row: dict[str, Any], view: str = "current_at_snapshot"
    ) -> list[dict[str, Any]]:
        ordinary = super()._record_units(row, view)
        state = row.get("value", {}).get("edit_state")
        if not ordinary or not state:
            return ordinary
        result = []
        for unit in state["units"]:
            text = unit["text"]
            edges = [
                r
                for r in state["relations"]
                if unit["unit_id"] in (r["source_unit"], r["target_unit"])
            ]
            for start in range(0, max(1, len(text)), self.fragment_chars):
                result.append(
                    {
                        **ordinary[0],
                        "content": text[start : start + self.fragment_chars],
                        "content_range": [start, min(start + self.fragment_chars, len(text))],
                        "content_total_codepoints": len(text),
                        "edit_representation": state["representation"],
                        "edit_unit_count": len(state["units"]),
                        "edit_relation_count": len(state["relations"]),
                        "edit_unit": {
                            k: copy.deepcopy(unit[k]) for k in ("unit_id", "role", "evidence_refs")
                        },
                        "edit_relations": copy.deepcopy(edges),
                        "method_version": row["value"]["method_version"],
                        "method_arm": row["value"].get("method_arm", self.arm),
                    }
                )
        return result or [
            {
                **ordinary[0],
                "edit_representation": state["representation"],
                "edit_unit_count": 0,
                "edit_relation_count": 0,
            }
        ]

    def save_edit(
        self,
        config: RunnableConfig,
        operation_id: str,
        units: list[dict[str, Any]],
        relations: list[dict[str, Any]] | None = None,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bound = self._binding(config)
        parsed = EditProposal.model_validate(
            {"action": "create", "units": units, "relations": relations or []}
        )
        requested = {
            "operation": "save",
            "memory_method": self.memory_method,
            "units": [unit.model_dump() for unit in parsed.units],
            "relations": [relation.model_dump() for relation in parsed.relations],
            "scope": scope,
        }
        replay = self.service.replay_requested(bound["session"], operation_id, requested)
        if replay is not None:
            return replay
        handles = list(
            dict.fromkeys(
                [h for unit in parsed.units for h in unit.evidence]
                + [h for relation in parsed.relations for h in relation.evidence]
            )
        )
        support = self._require_delivered(handles)
        state = form_state(parsed, self.service, conditioned=self.conditioned)
        saved_scope = self._scope(scope or {})
        refs = support["source_refs"]
        roles = {self.service.source(ref)["role"] for ref in refs}  # type: ignore[index]
        proposal = {
            "action": "create",
            "id": None,
            "expected_revision": 0,
            "content": render_state(state),
            "scope": saved_scope,
            "kind": "semantic",
            "basis": "user_statement"
            if roles == {"user"}
            else "tool_observation"
            if roles == {"tool"}
            else "inference",
            "fields": {},
            "object_ref": None,
            "source_ref": refs[0],
            "source_refs": refs,
            "field_support": {
                field: {"source_refs": refs} for field in ("content", "scope", "basis", "kind")
            },
            "functional_support": {
                field: handles for field in ("content", "kind", "basis", *scope_leaves(saved_scope))
            },
            "trigger_binding": bound,
            "requested": requested,
            "edit_state": state,
            "edit_operations": [],
            "method_version": METHOD_VERSION,
            "method_arm": self.arm,
            "patch_operation": "revise",
        }
        if self.formation_support_review is not None:
            self.service.prepare_proposal(bound["session"], operation_id, proposal)
            self._run_support_review(
                self.formation_support_review,
                self._formation_evidence(bound, proposal, operation_id),
                bound,
                refs,
            )
        return self._commit(bound["session"], operation_id, proposal)

    def update_edit(
        self,
        config: RunnableConfig,
        operation_id: str,
        read_handle: str,
        edits: list[dict[str, Any]],
    ) -> dict[str, Any]:
        bound = self._binding(config)
        parsed = EditProposal.model_validate({"action": "edit", "edits": edits})
        requested = {
            "operation": "update",
            "memory_method": self.memory_method,
            "read_handle": read_handle,
            "edits": [edit.model_dump() for edit in parsed.edits],
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
        state = old.get("edit_state")
        representation = "conditioned_v1" if self.conditioned else "plain_v1"
        if not state or state["representation"] != representation:
            raise FunctionalRejection(f"FUNCTIONAL_EDIT_EXPLICIT_{self.arm}_FORMATION_REQUIRED")
        operations = {"replace", "append", "override", "retract"} if self.conditioned else {
            "replace", "insert", "delete"
        }
        if any(edit.operation not in operations for edit in parsed.edits):
            raise FunctionalRejection(f"FUNCTIONAL_EDIT_{self.arm}_OPERATION_REQUIRED")
        changed_handles = list(dict.fromkeys(h for edit in parsed.edits for h in edit.evidence))
        if parsed.edits:
            self._require_delivered(changed_handles)
            state = apply_local(state, parsed.edits, self.service, conditioned=self.conditioned)
        content = render_state(state)
        equal = state == old["edit_state"] and content == old["content"]
        retract = not equal and not any(unit["role"] == "content" for unit in state["units"])
        if retract:
            self._require_distinct_withdrawal_support(old, changed_handles)
        handles = list(
            dict.fromkeys(
                [
                    *changed_handles,
                    *(
                        ref["evidence_id"]
                        for item in [*state["units"], *state["relations"]]
                        for ref in item["evidence_refs"]
                    ),
                ]
            )
        )
        support = self._source_support(old)
        if not equal:
            support["content"] = handles
        refs = list(
            dict.fromkeys(
                [
                    *(fragment_support(self.service, handles)["source_refs"] if handles else []),
                    *old.get("source_refs", [old["source_ref"]]),
                ]
            )
        )
        proposal = {
            "action": "update",
            "id": row["id"],
            "expected_revision": old["revision"],
            "candidate_handle": read_handle,
            "content": content,
            **{key: copy.deepcopy(old[key]) for key in ("kind", "basis", "scope", "fields")},
            "object_ref": old.get("object_ref"),
            "source_ref": refs[0],
            "source_refs": refs,
            "field_support": {
                field: {"reuse_support_from": read_handle}
                if canonical(old[field]) == canonical(content if field == "content" else old[field])
                else {"source_refs": refs}
                for field in ("content", "scope", "basis", "kind")
            },
            "trigger_binding": bound,
            "requested": requested,
            "edit_state": state,
            "edit_operations": [e.model_dump() for e in parsed.edits],
            "method_version": METHOD_VERSION,
            "method_arm": self.arm,
            "patch_operation": "no_change" if equal else "retract" if retract else "revise",
        }
        if not equal:
            proposal["functional_support"] = support
            proposal["removed_field_support"] = {"record": changed_handles} if retract else {}
        if self.revision_support_review is not None and not equal:
            self.service.prepare_proposal(bound["session"], operation_id, proposal)
            self._run_support_review(
                self.revision_support_review,
                self._revision_evidence(bound, proposal, old, operation_id),
                bound,
                refs,
            )
        return self._commit(bound["session"], operation_id, proposal)

    @staticmethod
    def _mutation(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return action()
        except (FunctionalRejection, ValidationError) as error:
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
                "recovery": "same_operation_id_only",
                "error_category": "integrity"
                if isinstance(cause, FunctionalIntegrityError)
                else "unconfirmed_effect",
            }

    def tools(self) -> tuple[BaseTool, ...]:
        def message(name: str, call_id: str, result: dict[str, Any]) -> ToolMessage:
            return ToolMessage(
                name=name,
                tool_call_id=call_id,
                content=canonical(result),
                status="success" if result.get("ok") else "error",
            )

        def save_memory(
            units: list[NewUnit],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            relations: list[NewRelation] | None = None,
            scope: dict[str, Any] | None = None,
        ) -> ToolMessage:
            """Save M content/condition units and zero-based modifies/overrides relations.

            Each evidence list copies actual delivered source fragment_handles, never
            source_ref. Preserve subjects, times, negation and uncertainty. Unit IDs
            are issued by the Host. scope is explicit record metadata, not a summary
            label. Saving is a memory-only effect and proves no business outcome.
            """
            return message(
                "save_memory",
                tool_call_id,
                self._mutation(
                    lambda: self.save_edit(
                        config,
                        tool_call_id,
                        [unit.model_dump() for unit in units],
                        [relation.model_dump() for relation in relations] if relations else [],
                        scope,
                    )
                ),
            )

        def update_memory(
            read_handle: str,
            edits: list[UnitEdit],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> ToolMessage:
            """Edit the actual read record using M replace/append/override/retract.

            Copy target_unit/shared_conditions/attach_to from delivered edit_unit IDs.
            Copy evidence from actual delivered source fragment_handles, never source_ref.
            override needs explicit condition text; it preserves the general arrangement.
            Unselected units and record scope remain unchanged. Only one override layer
            is supported. retract removes a selected unit and its incident relations;
            cancellation does not assert an opposite. Full withdrawal needs a new
            cancellation witness. An empty edits list confirms exact no_change.
            """
            return message(
                "update_memory",
                tool_call_id,
                self._mutation(
                    lambda: self.update_edit(
                        config,
                        tool_call_id,
                        read_handle,
                        [edit.model_dump() for edit in edits],
                    )
                ),
            )

        replacements = {
            "save_memory": StructuredTool.from_function(save_memory),
            "update_memory": StructuredTool.from_function(update_memory),
        }
        if not self.conditioned:
            replacements["save_memory"].description = (
                "Save B1 plain content units, with no relations. Keep conditions and uncertainty "
                "in their text. Each evidence list copies actually delivered source "
                "fragment_handles, never source_ref. Unit IDs are issued by the Host. "
                "scope is explicit record "
                "metadata. Saving is a memory-only effect and proves no business outcome."
            )
            replacements["update_memory"].description = (
                "Edit the actual read B1 record using replace/insert/delete. Copy target_unit "
                "from delivered edit_unit IDs and evidence from actual delivered source "
                "fragment_handles, never source_ref. insert follows target_unit, or appends "
                "when it is null. Unselected units and record scope remain unchanged. Keep "
                "conditions in plain text. Full withdrawal needs a new cancellation witness. "
                "An empty edits list confirms exact no_change."
            )
        return tuple(replacements.get(tool.name, tool) for tool in super().tools())
