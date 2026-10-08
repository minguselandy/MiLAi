"""Opt-in edit arms on the existing functional Host, Reader and MemoryService.

The plain and conditioned operators are the frozen MiLAi-Edit methods.
This adapter binds them to functional request/receipt contracts. It has no model,
application object, business authorization, reviewer or independent database.
Record scope is retained on updates; scope-only patches are not exposed.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from pydantic import Field, ValidationError

from milai_lab.memory.edit_units import (
    EditDTO,
    EditProposal,
    NewRelation,
    NewUnit,
    UnitEdit,
    apply_local,
    form_state,
    read_applicability,
    read_revision_evidence,
    read_revision_scope,
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
    reference_key,
    scope_leaves,
)
from milai_lab.methods.append_memory import AppendMemory
from milai_lab.methods.edit_features import EditFeatures, decorate_state
from milai_lab.methods.edit_maintenance import (
    MaintenanceRecipe,
    ModelCall,
    maintain_event,
    resume_maintenance,
)
from milai_lab.methods.edit_memory import Arm, EditMemory, InterfaceVersion

FUNCTIONAL_METHOD = "milai_edit_m_v1"
FUNCTIONAL_B0_METHOD = "milai_edit_b0_v1"
FUNCTIONAL_B1_METHOD = "milai_edit_b1_v1"
FUNCTIONAL_B2_METHOD = "milai_edit_b2_v1"
FUNCTIONAL_APPEND_METHOD = "milai_fact_append_v1"
FunctionalArm = Arm | Literal["Append-only"]
FUNCTIONAL_ARMS: dict[str, FunctionalArm] = {
    FUNCTIONAL_B0_METHOD: "B0",
    FUNCTIONAL_B1_METHOD: "B1",
    FUNCTIONAL_B2_METHOD: "B2",
    FUNCTIONAL_METHOD: "M",
    FUNCTIONAL_APPEND_METHOD: "Append-only",
}
INTEGRATION_VERSION = "functional_m_v1"


class _WholeRewriteInput(EditDTO):
    """A full rewrite cannot silently discard a model's local-edit arguments."""

    read_handle: str
    units: list[NewUnit] | None = None
    relations: list[NewRelation] | None = None
    withdrawal_evidence: list[str] | None = None
    tool_call_id: Annotated[str, InjectedToolCallId]


class _WriterInput(EditDTO):
    proposal: dict[str, Any]
    tool_call_id: Annotated[str, InjectedToolCallId]


class _WriterSaveInput(_WriterInput):
    scope: dict[str, Any] | None = None


class _ExplicitWriterTool(StructuredTool):
    @property
    def tool_call_schema(self) -> dict[str, Any]:
        """Keep per-request nested JSON constraints across LangChain's subset view."""
        if self.args_schema is None or isinstance(self.args_schema, dict):
            raise FunctionalRejection("FUNCTIONAL_EDIT_WRITER_SCHEMA_UNAVAILABLE")
        if not issubclass(self.args_schema, EditDTO):
            raise FunctionalRejection("FUNCTIONAL_EDIT_WRITER_SCHEMA_UNAVAILABLE")
        schema = copy.deepcopy(self.args_schema.model_json_schema())
        schema["properties"].pop("tool_call_id", None)
        schema["required"] = [field for field in schema["required"] if field != "tool_call_id"]
        schema["description"] = self.description
        return schema


class FunctionalEditMemory(FunctionalMemory):
    """Use an edit arm in the current flow; default FunctionalMemory is unchanged."""

    def __init__(
        self,
        *args: Any,
        arm: FunctionalArm = "M",
        interface_version: InterfaceVersion = "v1",
        features: EditFeatures | None = None,
        maintenance_recipe: MaintenanceRecipe | None = None,
        query_time: str | None = None,
        query_calendar_context: str | None = None,
        **kwargs: Any,
    ) -> None:
        if arm not in FUNCTIONAL_ARMS.values():
            raise ValueError("FUNCTIONAL_EDIT_ARM_INVALID")
        super().__init__(*args, **kwargs)
        self.arm = arm
        self.writer: EditMemory
        if arm == "Append-only":
            if interface_version != "I2" or maintenance_recipe is None:
                raise ValueError("FUNCTIONAL_APPEND_REQUIRES_I2_MAINTENANCE_RECIPE")
            self.writer = AppendMemory(self.service, features=features or EditFeatures())
        else:
            self.writer = EditMemory(
                self.service, arm, interface_version=interface_version, features=features
            )
        self.features = self.writer.features
        self.interface_version = interface_version
        self.maintenance_recipe = maintenance_recipe
        self.query_time = query_time
        self.query_calendar_context = query_calendar_context
        if maintenance_recipe is not None:
            self.policy["maintenance_recipe"] = maintenance_recipe
        self.conditioned = arm in {"B2", "M"}
        self.local = arm in {"B1", "M"}
        self.memory_method = next(name for name, value in FUNCTIONAL_ARMS.items() if value == arm)
        self.policy["memory_method"] = self.memory_method
        self.policy["integration_version"] = (
            INTEGRATION_VERSION if arm == "M" else "functional_" + arm.lower() + "_v1"
        )
        if interface_version != "v1":
            self.policy["interface_version"] = interface_version
            self.policy["integration_version"] = "functional_edit_v2"
        if self.features.enabled:
            self.policy["edit_features"] = canonical(self.features.settings())

    def instructions(self) -> str:
        if self.interface_version != "v1":
            return self.writer.instructions() + (
                "Functional tool arguments replace the proposals envelope. For a supported "
                "durable new fact use save_memory when formation is warranted; for an actual "
                "correction use update_memory with the applicable delivered target and evidence. "
                "An empty records list is not absence of new evidence. Raw utterance capture "
                "alone is not a reason to save social acknowledgment or a query without durable "
                "facts. With only h, retain exact delivered unit text/role; use supporting new e "
                "for changed wording. If no maintenance "
                "is justified, make no save_memory/update_memory tool call. "
                "Functional save_memory takes proposal=create and optional scope. "
                "update_memory takes proposal with target=r# from the latest writer packet. "
                "Do not pass read_handle, persistent IDs, mapping IDs, or base_revision to these "
                "writer tools. Read/confirmation/history/forget still use the existing Reader "
                "contracts. Record scope stays unchanged on updates. A partial record is "
                "unprocessed until all its text units have actually been read; the Host never "
                "completes a replacement using unseen text. Memory receipts prove no business "
                "outcome. Support review remains an optional caller callback. "
            )
        if not self.local:
            return self.writer.instructions() + (
                "The functional tool signatures replace the proposal envelope: save_memory "
                "takes units/relations/scope; update_memory takes an actual read_handle and the "
                "entire replacement units/relations. Include all retained text, qualifications "
                "and relations. These tools do not accept local edits or model-issued unit IDs. "
                "Do not send action/target_record/base_revision. Every evidence[] string must "
                "be an actually delivered source fragment_handle, the same issued range identity "
                "as evidence_id. source_ref is provenance only. A record's evidence_refs "
                "metadata does not deliver original bodies; read missing originals explicitly. "
                "Record scope stays unchanged during rewrite. For exact no_change omit units "
                "or set them to null, with no relations or withdrawal_evidence. To withdraw the "
                "whole record set units=[] and select actually delivered withdrawal_evidence "
                "containing a new cancellation witness beyond its prior affirmative support. "
                "No new content can be mixed with whole withdrawal. confirm_existing_memory "
                "also confirms an unchanged current record without a new revision. "
            )
        targets = "target_unit/shared_conditions/attach_to" if self.conditioned else "target_unit"
        applicability = (
            "condition/override units express applicability within that scope. "
            if self.conditioned
            else "keep conditions and qualifications in the selected plain text units. "
        )
        return self.writer.instructions() + (
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
        self,
        config: RunnableConfig,
        fragment_handles: list[str],
        *,
        redelivered: bool = False,
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
            if self.interface_version != "v1":
                self._cache_writer_items(
                    config,
                    [
                        {"type": "fragment", **self.service.source_fragment(handle)}
                        for handle in dict.fromkeys(fragment_handles)
                    ],
                    redelivered=redelivered,
                )

    def _writer_key(self, config: RunnableConfig, prefix: str) -> str:
        bound = self._binding(config)
        return prefix + reference_key([bound, self.interface_version, self.arm, self.forget_epoch])

    def _cache_writer_items(
        self,
        config: RunnableConfig,
        items: list[dict[str, Any]],
        *,
        redelivered: bool = False,
    ) -> None:
        """Accumulate only actual Reader pages and trusted visible ToolMessage spans."""
        key = self._writer_key(config, "edit-writer-delivery:")
        prior = self.service.store.get(namespace(self.service), key)
        merged = copy.deepcopy(prior.value["items"]) if prior else []
        current_ref = self._binding(config)["source_ref"]
        for item in items:
            delivered = copy.deepcopy(item)
            if redelivered and item.get("type") == "fragment" and item["source_ref"] != current_ref:
                delivered["delivery_kind"] = "redelivered_support"
            if delivered not in merged:
                merged.append(delivered)
        self.service.store.put(namespace(self.service), key, {"items": merged}, index=False)

    def _model_items(self, config: RunnableConfig) -> list[dict[str, Any]]:
        """Current material, separately from the durable archive of actual reads."""
        stored = self.service.store.get(
            namespace(self.service), self._writer_key(config, "edit-writer-delivery:")
        )
        archive = stored.value["items"] if stored else []
        if self.memory_view_mode == "legacy":
            return copy.deepcopy(archive)
        current_ref = self._binding(config)["source_ref"]
        # Current public input and actual business results remain available when
        # switching a semantic matter. Earlier support only returns when selected.
        current = [item for item in archive if item["type"] == "fragment" and (
            item["source_ref"] == current_ref or (item.get("role") == "tool"
            and item.get("delivery_kind") != "redelivered_support")
        )]
        resident = self.resident_items(config)
        current_handles = {item["fragment_handle"] for item in current}
        for item in resident:
            if item["type"] == "fragment" and item["source_ref"] != current_ref \
                    and item["fragment_handle"] not in current_handles:
                item["delivery_kind"] = "redelivered_support"
        items: dict[str, dict[str, Any]] = {}
        for item in [*copy.deepcopy(current), *resident]:
            identity = canonical([self._progress_identity(item), item.get("version_view")])
            items.setdefault(identity, item)
        return list(items.values())

    def model_material(
        self, config: RunnableConfig, *, for_write: bool = False
    ) -> dict[str, Any]:
        """Project actual resident material immediately before a model call.

        Answering through the shared maintenance recipe does not issue another
        editor map. Direct I2 writing explicitly requests the current target map.
        Full conversation and read receipts remain in their original checkpoints.
        """
        if self.memory_view_mode == "legacy":
            bound = self._binding(config)
            if for_write:
                return self.writer_context(
                    bound["session"], bound["message_id"], bound["config_version"]
                )
            return self.context(bound["session"], bound["message_id"], bound["config_version"])
        items = self._model_items(config)
        material = {
            "ok": True, "schema": "functional_material_v1", "kind": "resident",
            "items": items, **self._read_only_metadata(items),
            "memory_view": self.view_state(config), "read_progress": self.read_progress(config),
        }
        page_ends: dict[str, int] = {}
        for ref in material["memory_view"]["resident_refs"]:
            page_ends[ref["snapshot_id"]] = max(
                page_ends.get(ref["snapshot_id"], 0), ref["unit_index"] + 1
            )
        continuations = []
        for snapshot_id, end in page_ends.items():
            snapshot = self.service.store.get(namespace(self.service), snapshot_id)
            if snapshot is not None and not snapshot.value["kind"].endswith("_catalog") \
                    and end < len(snapshot.value["items"]):
                continuations.append({
                    "tool": "read_page" if self.read_interface == "explicit_selectors_v1"
                    else "read_memory",
                    "arguments": {"cursor": snapshot_id + ":" + str(end)},
                })
        if continuations:
            material["continuations"] = continuations
        bound = self._binding(config)
        ordinary = self.service.store.get(namespace(self.service), "ordinary:" + reference_key(
            [bound["session"], bound["message_id"], self.forget_epoch]
        ))
        if ordinary is not None and ordinary.value.get("catalog_snapshot"):
            directory = self._page(ordinary.value["catalog_snapshot"], 0, bound)
            material["candidates"] = directory.get("candidates", [])
            material["candidate_scope"] = "navigation_only_not_body_read_or_fact_support"
            material["next_cursor"] = directory.get("next_cursor")
        if for_write and self.interface_version != "v1":
            packet = self._writer_packet(config, material)
            packet["memory_view"] = material["memory_view"]
            if "candidates" in material:
                packet["candidates"] = material["candidates"]
                packet["candidate_scope"] = material["candidate_scope"]
            if continuations:
                packet["continuations"] = continuations
            return packet
        return material

    def project_model_messages(
        self, config: RunnableConfig, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        """Evict old read bodies from temporary input, retaining every tool pair.

        The caller adds model_material to the current system input. Tool results
        keep their actual identities, cursors and progress, while business and
        mutation receipts pass through unchanged. This never alters the journal.
        """
        if self.memory_view_mode == "legacy":
            return list(messages)
        self._binding(config)
        projected: list[BaseMessage] = []
        for message in messages:
            if not isinstance(message, ToolMessage) or message.name not in self.read_tool_names:
                projected.append(message)
                continue
            try:
                result = json.loads(str(message.content))
            except (TypeError, ValueError):
                projected.append(message)
                continue
            if not isinstance(result, dict) or not result.get("items"):
                projected.append(message)
                continue
            result = copy.deepcopy(result)
            result["read_identities"] = [self._progress_identity(item) for item in result["items"]]
            result["items"] = []
            result["material_location"] = "current_resident_view_or_original_read_reference"
            projected.append(message.model_copy(update={"content": canonical(result)}))
        return projected

    def pending_maintenance(self, config: RunnableConfig) -> list[dict[str, Any]]:
        """Visible explicit save checkpoints, referenced rather than duplicated."""
        self._binding(config)
        result = []
        ns = (*self.service.namespace, "edit_maintenance")
        for stored in self.service.store.search(ns, limit=10000):
            state = stored.value
            if not state.get("memory_save_requested"):
                continue
            session, request_id = json.loads(stored.key)
            sources = state["binding"]["sources"]
            if not sources or any(self.service.source(row["source_ref"]) is None
                                  for row in sources):
                continue
            receipts = state.get("receipts", [])
            confirmed = any(row.get("ok") and row.get("effect") == "memory_only"
                            and row.get("status") in {"committed", "no_change", "replayed"}
                            for row in receipts)
            if state["phase"] == "complete" and confirmed and not state.get("unprocessed"):
                continue
            result.append({
                "request_id": request_id, "session": session,
                "source_refs": list(dict.fromkeys(row["source_ref"] for row in sources)),
                "maintenance_phase": state["phase"],
                "confirmed_receipt_count": sum(bool(row.get("ok")) for row in receipts),
                "checkpoint": {"namespace": list(ns), "key": stored.key},
                "recovery": "inspect_original_receipts_before_explicit_new_attempt",
            })
        return result

    def _commit(
        self, session: str, operation_id: str, proposal: dict[str, Any]
    ) -> dict[str, Any]:
        receipt = super()._commit(session, operation_id, proposal)
        if self.memory_view_mode == "legacy" or not receipt.get("ok") \
                or receipt.get("status") != "committed":
            return receipt
        bound = proposal["trigger_binding"]
        config: RunnableConfig = {"configurable": {
            "user_id": self.service.owner, "v13_session": bound["session"],
            "v13_turn_id": bound["message_id"], "v13_config_version": bound["config_version"],
        }}
        selected = proposal["action"] == "create" or any(
            ref.get("kind") == "record" and ref.get("id") == receipt["id"]
            and ref.get("view") == "current_at_snapshot"
            for ref in self.view_state(config)["resident_refs"]
        )
        if selected:
            self._refresh_current(config, receipt["id"])
        return receipt

    def _refresh_current(self, config: RunnableConfig, record_id: str) -> None:
        """Refresh only a target actually selected by a read or committed operation."""
        row = self.service.read(record_id)
        if not row.get("ok"):
            return
        current_refs = [ref for ref in self.view_state(config)["resident_refs"]
                        if ref.get("kind") == "record" and ref.get("id") == record_id
                        and ref.get("view") == "current_at_snapshot"]
        if current_refs and all(ref["revision"] == row["value"]["revision"]
                                for ref in current_refs):
            return
        bound = self._binding(config)
        snapshot = self._snapshot(bound, self._record_units(row), "committed_current")
        page = self._page(snapshot, 0, bound)
        self._cache_writer_items(config, page.get("items", []))
        self._note_view_page(config, page, keep_resident=True, refresh_current=True)

    def _remember_page(self, config: RunnableConfig, result: dict[str, Any]) -> None:
        if result.get("ok"):
            self.note_delivered_fragment_handles(
                config,
                [
                    unit["fragment_handle"]
                    for unit in result.get("items", [])
                    if unit.get("type") == "fragment"
                ],
                redelivered=True,
            )
            if self.interface_version != "v1":
                self._cache_writer_items(config, result.get("items", []), redelivered=True)

    @staticmethod
    def _progress_identity(item: dict[str, Any]) -> list[Any]:
        if item["type"] == "fragment":
            return ["source", item["source_ref"], item.get("source_revision", 1),
                    None, [item["start"], item["end"]]]
        return [item["type"], item.get("record_id"), item.get("revision"),
                item.get("edit_unit", {}).get("unit_id"), item.get("content_range")]

    @staticmethod
    def _new_range(identity: list[Any], previous: list[list[Any]]) -> bool:
        if identity[-1] is None or identity[-1][0] == identity[-1][1]:
            return identity not in previous
        remaining = [identity[-1]]
        for old in previous:
            if old[:-1] == identity[:-1] and old[-1] is not None:
                left, right = old[-1]
                remaining = [
                    [a, b] for start, end in remaining
                    for a, b in ((start, min(end, left)), (max(start, right), end)) if a < b
                ]
        return bool(remaining)

    def _note_read_progress(
        self, config: RunnableConfig, result: dict[str, Any], *, from_tool: bool
    ) -> None:
        if self.service.memory_profile != "unified_v1":
            return
        key = self._writer_key(config, "edit-read-progress:")
        prior = self.service.store.get(namespace(self.service), key)
        state = copy.deepcopy(prior.value) if prior else {"units": [], "pages": []}
        identities = [self._progress_identity(item) for item in result.get("items", [])]
        fresh = []
        for identity in identities:
            if self._new_range(identity, state["units"]):
                fresh.append(identity)
                state["units"].append(identity)
        page = [result.get("snapshot_id"), result.get("start")]
        new_page = page not in state["pages"] and result.get("snapshot_id") is not None
        if new_page:
            state["pages"].append(page)
        progress = {
            "new_units": len(fresh), "delivered_units_total": len(state["units"]),
            "new_snapshot_page": new_page, "next_cursor": result.get("next_cursor"),
            "status": "new_evidence" if fresh else "no_new_evidence",
            "continuation": "read_missing_object_revision_or_next_cursor" if fresh else
            "use_delivered_material_or_report_insufficient",
            "history_absence_not_established": True,
        }
        if from_tool:
            state["last_tool"] = progress
        self.service.store.put(namespace(self.service), key, state, index=False)
        # The page planner already enforces the public material allowance. Avoid
        # overflowing it merely to repeat auxiliary progress metadata; callers
        # can always inspect read_progress after the actual read.
        annotated = {**result, "read_progress": progress}
        if self.token_count(canonical(annotated)) <= self.material_limit:
            result["read_progress"] = progress

    def read_progress(self, config: RunnableConfig) -> dict[str, Any]:
        """Inspect this turn's delivered object/version/range and page progress."""
        prior = self.service.store.get(
            namespace(self.service), self._writer_key(config, "edit-read-progress:")
        )
        if prior is None:
            return {"delivered_units_total": 0, "last_tool": None}
        return {
            "delivered_units_total": len(prior.value["units"]),
            "delivered_snapshot_pages": len(prior.value["pages"]),
            "delivered_identities": copy.deepcopy(prior.value["units"]),
            "snapshot_pages": copy.deepcopy(prior.value["pages"]),
            "last_tool": copy.deepcopy(prior.value.get("last_tool")),
        }

    def maintain_delivery(
        self,
        config: RunnableConfig,
        delivery: dict[str, Any],
        *,
        request_id: str,
        date: str,
        recipe: MaintenanceRecipe,
        model_call: ModelCall,
        allowed: bool,
        execute: bool = True,
        selected_record_ids: list[str] | None = None,
        fit: Callable[[list[dict[str, str]]], bool] | None = None,
        prepare_delivery: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        prior_request_id: str | None = None,
        new_attempt_id: str | None = None,
        memory_save_requested: bool = False,
    ) -> dict[str, Any]:
        """Bind a current event or explicit consolidation to the ordinary Host commits."""
        if not allowed:
            return {"status": "not_permitted", "phase": "permission", "receipts": [],
                    "unprocessed": [], "semantic_write_performed": False}
        bound = self._binding(config)
        if self.memory_view_mode != "legacy" and selected_record_ids is None \
                and prior_request_id is None:
            selected = list(dict.fromkeys(
                item["record_id"] for item in self.resident_items(config)
                if item["type"] == "record" and item["version_view"] == "current_at_snapshot"
            ))
            if selected:
                selected_record_ids = selected

        def commit(
            operation_id: str, proposal: dict[str, Any], mapping: dict[str, Any]
        ) -> dict[str, Any]:
            self.service.store.put(
                namespace(self.service), self._writer_key(config, "edit-writer-active:"),
                {"mapping_id": mapping["mapping_id"]}, index=False,
            )
            self.note_delivered_fragment_handles(
                config, [row["evidence_id"] for row in mapping["evidence"].values()],
                redelivered=delivery.get("replay", False),
            )
            receipt = self.apply_writer_proposal(config, operation_id, proposal)
            if receipt.get("ok") and (receipt.get("status") == "committed"
                                     or receipt.get("original_status") == "committed"):
                if self.memory_view_mode != "legacy":
                    self._refresh_current(config, receipt["id"])
                self.service.store.delete(
                    namespace(self.service), "ordinary:" + reference_key(
                        [bound["session"], bound["message_id"], self.forget_epoch]
                    ),
                )
            return receipt

        def selected_delivery(located: dict[str, Any]) -> dict[str, Any]:
            prepared = prepare_delivery(located) if prepare_delivery is not None else located
            if self.memory_view_mode != "legacy":
                units = [unit for record in prepared["records"]
                         for unit in self._record_units(self.service.read(
                             record["record_id"], record["revision"]
                         ))]
                if units:
                    snapshot = self._snapshot(bound, units, "maintenance_selected")
                    page = self._page(snapshot, 0, bound)
                    self._cache_writer_items(config, page.get("items", []))
                    self._note_view_page(config, page)
                else:
                    state = self.view_state(config)
                    self.focus_view(config, focus=state["focus"], read_goal=state["read_goal"],
                                    resident_refs=[], pending_refs=state["pending_refs"])
            return prepared

        options: dict[str, Any] = {
            "session": bound["session"], "date": date, "recipe": recipe,
            "model_call": model_call, "commit": commit, "selected_record_ids": selected_record_ids,
            "fit": fit, "prepare_delivery": selected_delivery,
            "memory_view_mode": self.memory_view_mode,
            "memory_save_requested": memory_save_requested,
        }
        if prior_request_id is not None:
            result = resume_maintenance(
                self.writer, delivery, prior_request_id=prior_request_id,
                new_attempt_id=new_attempt_id if execute else None, **options,
            )
        else:
            if new_attempt_id is not None:
                raise FunctionalRejection("EDIT_MAINTENANCE_PRIOR_REQUEST_REQUIRED")
            result = maintain_event(
                self.writer, delivery, request_id=request_id, execute=execute, **options
            )
        return result

    def maintain_sources(
        self,
        config: RunnableConfig,
        *,
        recipe: MaintenanceRecipe,
        model_call: ModelCall,
        allowed: bool,
        execute: bool = True,
        fit: Callable[[list[dict[str, str]]], bool] | None = None,
        prior_request_fragments: list[dict[str, Any]] | None = None,
        memory_save_requested: bool = False,
    ) -> list[dict[str, Any]]:
        """Maintain current user input and actually delivered tool sources once each.

        Current Host permission is authoritative. Old context and assistant prose
        never become a fresh event just because they occur in the Reader cache.
        Explicitly selected old request ranges join prior context without the
        recent-source limit; they do not enter the current evidence table.
        """
        if not allowed:
            return []
        bound = self._binding(config)
        stored = self.service.store.get(
            namespace(self.service), self._writer_key(config, "edit-writer-delivery:")
        )
        refs = [bound["source_ref"]]
        refs.extend(
            item["source_ref"] for item in (stored.value["items"] if stored else [])
            if item["type"] == "fragment" and item.get("role") == "tool"
            and item.get("delivery_kind") != "redelivered_support"
        )
        results = []
        for ref in dict.fromkeys(refs):
            source = self.service.source(ref)
            if source is None:
                continue
            delivery = self.writer.prepare([ref], "", selected_records=[], redelivered_ranges=[])
            old = {}
            for item in (stored.value["items"] if stored else []):
                if item["type"] != "fragment" or item["source_ref"] == ref:
                    continue
                previous = self.service.source(item["source_ref"])
                if previous is not None and previous["observed_at"] < source["observed_at"]:
                    old[(item["source_ref"], item["start"], item["end"])] = previous
            recent_refs = sorted(
                {key[0] for key in old},
                key=lambda key: next(s["observed_at"] for k, s in old.items() if k[0] == key),
            )[-4:]
            ranges = [{"source_ref": key[0], "start": key[1], "end": key[2]}
                      for key in old if key[0] in recent_refs]
            for fragment in prior_request_fragments or []:
                part = {key: fragment[key] for key in ("source_ref", "start", "end")}
                if part not in ranges:
                    ranges.append(part)
            if ranges:
                delivery["prior_context"] = self.writer.prepare(
                    list(dict.fromkeys(part["source_ref"] for part in ranges)), "",
                    selected_records=[], source_ranges=ranges,
                    redelivered_ranges=[],
                )["sources"]
            request_id = "maintenance:" + canonical(
                [bound["session"], bound["message_id"], bound["config_version"], ref]
            )

            results.append(self.maintain_delivery(
                config, delivery, request_id=request_id,
                date=source.get("occurred_at") or source["observed_at"], recipe=recipe,
                model_call=model_call, allowed=allowed, execute=execute, fit=fit,
                memory_save_requested=memory_save_requested,
            ))
        return results

    def writer_context(
        self, session: str, turn_id: str, config_version: str, *, query: str | None = None
    ) -> dict[str, Any]:
        """Public v2 packet from actually delivered Reader pages; original context is retained.

        Incomplete record fragments are reported, never reconstructed by fetching
        unseen body text. The caller invokes this before handing the packet to the
        Agent. Its immutable map is server-side and operation-bound on first use.
        """
        if self.interface_version == "v1":
            return self.context(session, turn_id, config_version, query=query)
        page = self.context(session, turn_id, config_version, query=query)
        config: RunnableConfig = {
            "configurable": {
                "user_id": self.service.owner,
                "v13_session": session,
                "v13_turn_id": turn_id,
                "v13_config_version": config_version,
            }
        }
        return self._writer_packet(config, page)

    def _writer_packet(self, config: RunnableConfig, page: dict[str, Any]) -> dict[str, Any]:
        items = self._model_items(config)
        sources: list[dict[str, Any]] = []
        redelivered: list[dict[str, Any]] = []
        redelivered_handles = {
            item["fragment_handle"]
            for item in items
            if item.get("delivery_kind") == "redelivered_support"
        }
        groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for item in items:
            if item["type"] == "fragment":
                try:
                    fragment = self.service.source_fragment(item["fragment_handle"])
                except FunctionalRejection:
                    continue
                destination = (
                    redelivered if fragment["fragment_handle"] in redelivered_handles else sources
                )
                destination.append(
                    {
                        **{
                            key: fragment[key]
                            for key in (
                                "source_ref",
                                "source_revision",
                                "start",
                                "end",
                                "role",
                                "observed_at",
                            )
                        },
                        "evidence_id": fragment["fragment_handle"],
                        "text": fragment["content"],
                        "body_delivered": True,
                    }
                )
            elif item["type"] == "record":
                if self.memory_view_mode != "legacy" \
                        and item.get("version_view") != "current_at_snapshot":
                    continue
                groups.setdefault((item["record_id"], item["revision"]), []).append(item)
        records: list[dict[str, Any]] = []
        unprocessed: list[dict[str, Any]] = []
        for (record_id, revision), fragments in groups.items():
            current = self.service.read(record_id)
            if not current.get("ok") or current["value"]["revision"] != revision:
                unprocessed.append({"reason": "read_revision_no_longer_current"})
                continue
            if "edit_representation" not in fragments[0]:
                end, text = 0, ""
                for chunk in sorted(fragments, key=lambda item: item["content_range"][0]):
                    start, stop = chunk["content_range"]
                    if stop <= end:
                        continue
                    if start != end:
                        break
                    text += chunk["content"]
                    end = stop
                if end == fragments[0]["content_total_codepoints"]:
                    records.append(
                        {
                            "record_id": record_id,
                            "revision": revision,
                            "content": text,
                            "edit_state": None,
                            "scope": copy.deepcopy(fragments[0]["scope"]),
                        }
                    )
                else:
                    unprocessed.append({"reason": "complete_record_body_not_delivered"})
                continue
            by_unit: dict[str, list[dict[str, Any]]] = {}
            for fragment in fragments:
                if "edit_unit" in fragment:
                    by_unit.setdefault(fragment["edit_unit"]["unit_id"], []).append(fragment)
            state: dict[str, Any] = {
                "representation": fragments[0].get("edit_representation"),
                "units": [],
                "relations": [],
            }
            if "edit_matter_description" in fragments[0]:
                state["matter_description"] = copy.deepcopy(fragments[0]["edit_matter_description"])
            complete = len(by_unit) == fragments[0].get("edit_unit_count")
            for unit_id, chunks in by_unit.items():
                chunks = sorted(chunks, key=lambda chunk: chunk["content_range"][0])
                end, text = 0, ""
                for chunk in chunks:
                    start, stop = chunk["content_range"]
                    if start < end and stop <= end:
                        continue
                    if start != end:
                        complete = False
                        break
                    text += chunk["content"]
                    end = stop
                    for relation in chunk["edit_relations"]:
                        if relation not in state["relations"]:
                            state["relations"].append(copy.deepcopy(relation))
                if end != chunks[0]["content_total_codepoints"]:
                    complete = False
                state["units"].append(
                    {"unit_id": unit_id, "text": text, **copy.deepcopy(chunks[0]["edit_unit"])}
                )
            complete = complete and len(state["relations"]) == fragments[0].get(
                "edit_relation_count", 0
            )
            if not complete:
                unprocessed.append(
                    {
                        "reason": "complete_record_body_not_delivered",
                        "delivered_units": len(by_unit),
                    }
                )
                continue
            # Ordering is metadata, not missing text. Every member above was delivered.
            actual_state = current["value"]["edit_state"]
            unit_order = {u["unit_id"]: index for index, u in enumerate(actual_state["units"])}
            relation_order = {
                r["relation_id"]: index for index, r in enumerate(actual_state["relations"])
            }
            state["units"].sort(key=lambda unit: unit_order[unit["unit_id"]])
            state["relations"].sort(key=lambda relation: relation_order[relation["relation_id"]])
            records.append(
                {
                    "record_id": record_id,
                    "revision": revision,
                    "content": render_state(state),
                    "edit_state": state,
                    "scope": copy.deepcopy(fragments[0]["scope"]),
                }
            )
        delivery = {"sources": sources, "records": records}
        if redelivered:
            delivery["redelivered_sources"] = redelivered
            for source in [*sources, *redelivered]:
                actual = self.service.source(source["source_ref"])
                if actual is None:
                    raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")
                source["occurred_at"] = actual.get("occurred_at")
        if self.features.source_metadata:
            self.writer._source_attributes(delivery)
        preview = self.writer.preview_writer_view(delivery)["packet"]
        result = {
            "ok": True,
            "schema": "functional_edit_writer_v2",
            "writer_packet": preview,
            "unprocessed_records": unprocessed,
            "reader": {
                key: copy.deepcopy(page[key])
                for key in (
                    "next_cursor",
                    "delivery_status",
                    "omitted_units",
                    "skipped_units",
                    "delivered_raw_fragment_count",
                    "delivered_semantic_record_count",
                )
                if key in page
            },
        }
        result["required_packet_tokens"] = self.token_count(canonical(result))
        required = self.token_count(canonical(result))
        if required > self.material_limit:
            raise FunctionalRejection("FUNCTIONAL_EDIT_COMPLETE_WRITER_PACKET_EXCEEDS_LIMIT")
        view = self.writer.writer_view(delivery)
        self.service.store.put(
            namespace(self.service),
            self._writer_key(config, "edit-writer-active:"),
            {"mapping_id": view["mapping"]["mapping_id"]},
            index=False,
        )
        active = self.service.store.get(
            namespace(self.service), self._writer_key(config, "edit-writer-active:")
        )
        if active is None or active.value != {"mapping_id": view["mapping"]["mapping_id"]}:
            raise FunctionalIntegrityError("FUNCTIONAL_EDIT_ACTIVE_MAP_UNCONFIRMED")
        result["writer_packet"] = view["packet"]
        result["required_packet_tokens"] = required
        return result

    def context(
        self, session: str, turn_id: str, config_version: str, *, query: str | None = None
    ) -> dict[str, Any]:
        result = super().context(session, turn_id, config_version, query=query)
        config: RunnableConfig = {
                "configurable": {
                    "user_id": self.service.owner,
                    "v13_session": session,
                    "v13_turn_id": turn_id,
                    "v13_config_version": config_version,
                }
            }
        self._remember_page(config, result)
        self._note_read_progress(config, result, from_tool=False)
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
            self._note_read_progress(config, result, from_tool=True)
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

    def _require_update_delivery(
        self, handles: list[str], old: dict[str, Any], kept_support: list[str] | None
    ) -> dict[str, Any]:
        if not kept_support:
            return self._require_delivered(handles)
        if self.interface_version == "v1":
            raise FunctionalRejection("FUNCTIONAL_EDIT_V2_SUPPORT_REQUIRED")
        prior = {
            ref["evidence_id"]
            for item in [*old["edit_state"]["units"], *old["edit_state"]["relations"]]
            for ref in item["evidence_refs"]
        }
        if not set(kept_support) <= prior or not set(kept_support) <= set(handles):
            raise FunctionalRejection("FUNCTIONAL_EDIT_EXISTING_SUPPORT_BINDING_INVALID")
        fresh = [handle for handle in handles if handle not in kept_support]
        if fresh:
            self._require_delivered(fresh)
        return fragment_support(self.service, handles)

    def apply_writer_proposal(
        self,
        config: RunnableConfig,
        operation_id: str,
        proposal: dict[str, Any],
        *,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Operation-bound decoding before existing save/update/review/commit gates."""
        if self.interface_version == "v1":
            raise FunctionalRejection("FUNCTIONAL_EDIT_V2_INTERFACE_REQUIRED")
        if self.arm == "Append-only" and proposal.get("action") != "create":
            raise FunctionalRejection("APPEND_ONLY_CREATE_REQUIRED")
        bound = self._binding(config)
        key = "edit-writer-operation:" + reference_key([bound, operation_id])
        requested: dict[str, Any] = {
            "proposal": proposal,
            "scope": scope,
            "arm": self.arm,
            "interface_version": self.interface_version,
        }
        if self.features.enabled:
            requested["edit_features"] = self.features.settings()
        with self.service._locked():
            prior = self.service.store.get(namespace(self.service), key)
            if prior is not None:
                if prior.value["requested"] != requested:
                    raise FunctionalRejection("FUNCTIONAL_EDIT_OPERATION_INPUT_CHANGED")
                decoded, read_handle, kept = (
                    copy.deepcopy(prior.value[field])
                    for field in ("decoded", "read_handle", "kept_support")
                )
            else:
                active = self.service.store.get(
                    namespace(self.service), self._writer_key(config, "edit-writer-active:")
                )
                if active is None:
                    raise FunctionalRejection("FUNCTIONAL_EDIT_ACTUAL_WRITER_DELIVERY_REQUIRED")
                mapping = self.writer.load_mapping(active.value["mapping_id"])
                decoded = self.writer.decode_proposal(proposal, mapping)
                target = proposal.get("target")
                read_handle = mapping["records"][target]["candidate_handle"] if target else None
                support_items = [
                    *proposal.get("units", []),
                    *proposal.get("relations", []),
                    *proposal.get("edits", []),
                    *proposal.get("unresolved_conditions", []),
                ]
                for clause in proposal.get("clauses", []):
                    support_items.append(clause)
                    for condition in clause.get("conditions", []):
                        support_items.extend((condition, condition["binding"]))
                    support_items.extend(clause.get("overrides", []))
                kept = list(
                    dict.fromkeys(
                        ref["evidence_id"]
                        for item in support_items
                        for alias in item.get("keep_support", [])
                        for ref in mapping["support"][alias]["evidence_refs"]
                    )
                )
                operation_map = {
                    "requested": requested,
                    "mapping_id": mapping["mapping_id"],
                    "decoded": decoded,
                    "read_handle": read_handle,
                    "kept_support": kept,
                }
                self.service.store.put(
                    namespace(self.service),
                    key,
                    operation_map,
                    index=False,
                )
                visible = self.service.store.get(namespace(self.service), key)
                if visible is None or visible.value != operation_map:
                    raise FunctionalIntegrityError("FUNCTIONAL_EDIT_OPERATION_MAP_UNCONFIRMED")
            if self.features.single_record_changes and proposal.get("target"):
                operation = self.service.store.get(namespace(self.service), key)
                if operation is None:
                    raise FunctionalIntegrityError("FUNCTIONAL_EDIT_OPERATION_MAP_UNCONFIRMED")
                use_key = "edit-writer-record-use:" + reference_key(
                    [operation.value["mapping_id"], proposal["target"]]
                )
                use = self.service.store.get(namespace(self.service), use_key)
                if use is not None and use.value != {"operation_id": operation_id}:
                    raise FunctionalRejection("EDIT_DUPLICATE_RECORD_CONTAINER")
                if use is None:
                    self.service.store.put(
                        namespace(self.service),
                        use_key,
                        {"operation_id": operation_id},
                        index=False,
                    )
                checked_use = self.service.store.get(namespace(self.service), use_key)
                if checked_use is None or checked_use.value != {"operation_id": operation_id}:
                    raise FunctionalIntegrityError("FUNCTIONAL_EDIT_RECORD_USE_UNCONFIRMED")
        if decoded["action"] == "create":
            return self.save_edit(
                config,
                operation_id,
                decoded["units"],
                decoded.get("relations"),
                scope,
                _edit_metadata=decoded.get("_edit_metadata"),
            )
        if scope is not None:
            raise FunctionalRejection("FUNCTIONAL_EDIT_SCOPE_UPDATE_NOT_EXPOSED")
        if decoded["action"] == "no_change" and read_handle is None:
            return self.service.record_no_change(bound["session"], operation_id, requested)
        if decoded["action"] == "edit" or self.local:
            return self.update_edit(
                config,
                operation_id,
                read_handle,
                decoded.get("edits", []),
                _kept_support=kept,
                _edit_metadata=decoded.get("_edit_metadata"),
            )
        return self.rewrite_edit(
            config,
            operation_id,
            read_handle,
            decoded.get("units") if decoded["action"] == "rewrite" else None,
            decoded.get("relations"),
            decoded.get("withdrawal_evidence"),
            _kept_support=kept,
            _edit_metadata=decoded.get("_edit_metadata"),
        )

    def _record_units(
        self, row: dict[str, Any], view: str = "current_at_snapshot"
    ) -> list[dict[str, Any]]:
        ordinary = super()._record_units(row, view)
        state = row.get("value", {}).get("edit_state")
        if not ordinary or not state:
            return ordinary
        record = {key: value for key, value in ordinary[0].items() if key != "stored_history"}
        revision_scope = {
            item["current_unit_id"]: item
            for item in read_revision_scope(self.service, row["id"], row["value"])
        } if self.features.enabled else {}
        query_time = (
            self.query_time if self.query_time is not None else self.service.clock().isoformat()
        ) if self.features.temporal_scope else None
        applicability = read_applicability(
            state,
            query_time=query_time,
            query_calendar_context=self.query_calendar_context,
            version_time=row["value"].get("committed_at") if self.features.temporal_scope else None,
            include_temporal=self.features.temporal_scope,
        ) if self.maintenance_recipe else {}
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
                        **record,
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
                if self.features.enabled:
                    if "matter_description" in state:
                        result[-1]["edit_matter_description"] = state["matter_description"]
                    if "assertion" in unit:
                        result[-1]["edit_unit"]["assertion"] = copy.deepcopy(unit["assertion"])
                    if unit.get("local_exception"):
                        result[-1]["edit_unit"]["local_exception"] = True
                    if start == 0 and unit["unit_id"] in revision_scope:
                        result[-1]["revision_scope"] = revision_scope[unit["unit_id"]]
                if start == 0 and unit["unit_id"] in applicability:
                    result[-1]["applicability"] = {
                        "view": view, "basis": "stored_direct_relations_only",
                        **applicability[unit["unit_id"]],
                    }
        result = result or [
            {
                **record,
                "edit_representation": state["representation"],
                "edit_unit_count": 0,
                "edit_relation_count": 0,
            }
        ]
        if "stored_history" in ordinary[0]:
            result[0]["stored_history"] = ordinary[0]["stored_history"]
        if self.features.enabled:
            result[0]["revision_evidence"] = read_revision_evidence(self.service, row["value"])
        if self.features.temporal_scope:
            result[0]["revision_view"] = self.writer.revision_view(
                row["value"], query_time=query_time,
                query_calendar_context=self.query_calendar_context,
            )
        return result

    def _record_basis(self, source_refs: list[str]) -> str:
        """Aggregate actual record provenance; unit assertions retain their own roles."""
        roles = {self.service.source(ref)["role"] for ref in source_refs}  # type: ignore[index]
        return (
            "user_statement" if roles == {"user"} else
            "tool_observation" if roles == {"tool"} else "inference"
        )

    def save_edit(
        self,
        config: RunnableConfig,
        operation_id: str,
        units: list[dict[str, Any]],
        relations: list[dict[str, Any]] | None = None,
        scope: dict[str, Any] | None = None,
        *,
        _edit_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bound = self._binding(config)
        parsed = EditProposal.model_validate(
            {"action": "create", "units": units, "relations": relations or []}
        )
        requested: dict[str, Any] = {
            "operation": "save",
            "memory_method": self.memory_method,
            "units": [unit.model_dump() for unit in parsed.units],
            "relations": [relation.model_dump() for relation in parsed.relations],
            "scope": scope,
        }
        if self.features.enabled:
            requested["edit_features"] = self.features.settings()
            requested["edit_metadata"] = _edit_metadata
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
        if self.features.enabled:
            if _edit_metadata is None or (
                self.features.matter_organization and not _edit_metadata.get("matter_description")
            ):
                raise FunctionalRejection("EDIT_FEATURE_METADATA_REQUIRED")
            decorate_state(state, _edit_metadata)
        saved_scope = self._scope(scope or {})
        refs = support["source_refs"]
        proposal = {
            "action": "create",
            "id": None,
            "expected_revision": 0,
            "content": render_state(state),
            "scope": saved_scope,
            "kind": "semantic",
            "basis": self._record_basis(refs),
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
            "method_version": self.writer.method_version,
            "method_arm": self.arm,
            "patch_operation": "revise",
        }
        if _edit_metadata is not None and "revision_evidence" in _edit_metadata:
            proposal["revision_evidence"] = _edit_metadata["revision_evidence"]
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

    def update_edit(
        self,
        config: RunnableConfig,
        operation_id: str,
        read_handle: str,
        edits: list[dict[str, Any]],
        *,
        _kept_support: list[str] | None = None,
        _edit_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.local:
            raise FunctionalRejection("FUNCTIONAL_EDIT_FULL_REWRITE_REQUIRED")
        bound = self._binding(config)
        parsed = EditProposal.model_validate({"action": "edit", "edits": edits})
        requested: dict[str, Any] = {
            "operation": "update",
            "memory_method": self.memory_method,
            "read_handle": read_handle,
            "edits": [edit.model_dump() for edit in parsed.edits],
        }
        if self.features.enabled:
            requested["edit_features"] = self.features.settings()
            requested["edit_metadata"] = _edit_metadata
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
        operations = (
            {"replace", "append", "override", "retract"}
            if self.conditioned
            else {"replace", "insert", "delete"}
        )
        if any(edit.operation not in operations for edit in parsed.edits):
            raise FunctionalRejection(f"FUNCTIONAL_EDIT_{self.arm}_OPERATION_REQUIRED")
        changed_handles = list(dict.fromkeys(h for edit in parsed.edits for h in edit.evidence))
        if parsed.edits:
            self._require_update_delivery(changed_handles, old, _kept_support)
            state = apply_local(
                state,
                parsed.edits,
                self.service,
                conditioned=self.conditioned,
                assertions=_edit_metadata.get("unit_assertions") if _edit_metadata else None,
                mark_exceptions=self.conditioned and self.features.enabled,
            )
            if self.features.enabled:
                if _edit_metadata is None:
                    raise FunctionalRejection("EDIT_FEATURE_METADATA_REQUIRED")
                decorate_state(state, _edit_metadata, old=old["edit_state"], edits=parsed.edits)
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
        basis = old["basis"] if equal else self._record_basis(refs)
        if basis != old["basis"]:
            support["basis"] = list(dict.fromkeys([*support.get("basis", []), *handles]))
        updated = {"content": content, "basis": basis}
        proposal = {
            "action": "update",
            "id": row["id"],
            "expected_revision": old["revision"],
            "candidate_handle": read_handle,
            "content": content,
            **{key: copy.deepcopy(old[key]) for key in ("kind", "scope", "fields")},
            "basis": basis,
            "object_ref": old.get("object_ref"),
            "source_ref": refs[0],
            "source_refs": refs,
            "field_support": {
                field: {"reuse_support_from": read_handle}
                if canonical(old[field]) == canonical(updated.get(field, old[field]))
                else {"source_refs": refs}
                for field in ("content", "scope", "basis", "kind")
            },
            "trigger_binding": bound,
            "requested": requested,
            "edit_state": state,
            "edit_operations": [e.model_dump() for e in parsed.edits],
            "method_version": self.writer.method_version,
            "method_arm": self.arm,
            "patch_operation": "no_change" if equal else "retract" if retract else "revise",
        }
        if _edit_metadata is not None and "revision_evidence" in _edit_metadata:
            proposal["revision_evidence"] = _edit_metadata["revision_evidence"]
        if not equal:
            proposal["functional_support"] = support
            proposal["removed_field_support"] = {"record": changed_handles} if retract else {}
        if self.revision_support_review is not None and not equal:
            self.service.prepare_proposal(bound["session"], operation_id, proposal)
            existing = self._run_support_review(
                self.revision_support_review,
                self._revision_evidence(bound, proposal, old, operation_id),
                bound,
                refs,
                operation_id,
                requested,
            )
            if existing is not None:
                return existing
        return self._commit(bound["session"], operation_id, proposal)

    def rewrite_edit(
        self,
        config: RunnableConfig,
        operation_id: str,
        read_handle: str,
        units: list[dict[str, Any]] | None = None,
        relations: list[dict[str, Any]] | None = None,
        withdrawal_evidence: list[str] | None = None,
        *,
        _kept_support: list[str] | None = None,
        _edit_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Replace the whole B0/B2 representation, confirm it, or withdraw with evidence.

        None units confirms without new support. Explicit empty units withdraws
        using the existing distinct-witness gate; it is not an empty formation.
        Nonempty units always pass through the frozen whole-state constructor.
        """
        if self.local:
            raise FunctionalRejection("FUNCTIONAL_EDIT_LOCAL_OPERATIONS_REQUIRED")
        bound = self._binding(config)
        parsed = EditProposal.model_validate(
            {"action": "rewrite", "units": units or [], "relations": relations or []}
        )
        requested: dict[str, Any] = {
            "operation": "rewrite",
            "memory_method": self.memory_method,
            "read_handle": read_handle,
            "units": None if units is None else [unit.model_dump() for unit in parsed.units],
            "relations": [relation.model_dump() for relation in parsed.relations],
            "withdrawal_evidence": withdrawal_evidence or [],
        }
        if self.features.enabled:
            requested["edit_features"] = self.features.settings()
            requested["edit_metadata"] = _edit_metadata
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
        representation = "conditioned_v1" if self.conditioned else "plain_v1"
        old_state = old.get("edit_state")
        if not old_state or old_state["representation"] != representation:
            raise FunctionalRejection(f"FUNCTIONAL_EDIT_EXPLICIT_{self.arm}_FORMATION_REQUIRED")
        no_change = units is None
        retract = units == []
        handles: list[str] = []
        if no_change:
            if parsed.relations or withdrawal_evidence:
                raise FunctionalRejection("FUNCTIONAL_EDIT_NO_CHANGE_HAS_MUTATIONS")
            state = copy.deepcopy(old_state)
        elif retract:
            if parsed.relations or not withdrawal_evidence:
                raise FunctionalRejection("FUNCTIONAL_EDIT_WITHDRAWAL_EVIDENCE_REQUIRED")
            handles = list(dict.fromkeys(withdrawal_evidence))
            self._require_delivered(handles)
            self._require_distinct_withdrawal_support(old, handles)
            state = {"representation": representation, "units": [], "relations": []}
        else:
            if withdrawal_evidence:
                raise FunctionalRejection("FUNCTIONAL_EDIT_REWRITE_HAS_WITHDRAWAL_EVIDENCE")
            handles = list(
                dict.fromkeys(
                    [h for unit in parsed.units for h in unit.evidence]
                    + [h for relation in parsed.relations for h in relation.evidence]
                    + (_edit_metadata.get("revision_evidence", []) if _edit_metadata else [])
                )
            )
            self._require_update_delivery(handles, old, _kept_support)
            state = form_state(parsed, self.service, conditioned=self.conditioned)
            if not any(unit["role"] == "content" for unit in state["units"]):
                raise FunctionalRejection("FUNCTIONAL_EDIT_WITHDRAWAL_REQUIRES_EMPTY_UNITS")
        if self.features.enabled and not no_change:
            if _edit_metadata is None:
                raise FunctionalRejection("EDIT_FEATURE_METADATA_REQUIRED")
            decorate_state(state, _edit_metadata, old=old_state)
        content = old["content"] if no_change else render_state(state)
        support = self._source_support(old)
        refs = list(
            dict.fromkeys(
                [
                    *(fragment_support(self.service, handles)["source_refs"] if handles else []),
                    *old.get("source_refs", [old["source_ref"]]),
                ]
            )
        )
        basis = old["basis"] if no_change else self._record_basis(refs)
        if basis != old["basis"]:
            support["basis"] = list(dict.fromkeys([*support.get("basis", []), *handles]))
        updated = {"content": content, "basis": basis}
        proposal = {
            "action": "update",
            "id": row["id"],
            "expected_revision": old["revision"],
            "candidate_handle": read_handle,
            "content": content,
            **{key: copy.deepcopy(old[key]) for key in ("kind", "scope", "fields")},
            "basis": basis,
            "object_ref": old.get("object_ref"),
            "source_ref": refs[0],
            "source_refs": refs,
            "field_support": {
                field: {"reuse_support_from": read_handle}
                if canonical(old[field]) == canonical(updated.get(field, old[field]))
                else {"source_refs": refs}
                for field in ("content", "scope", "basis", "kind")
            },
            "trigger_binding": bound,
            "requested": requested,
            "edit_state": state,
            "edit_operations": [],
            "method_version": self.writer.method_version,
            "method_arm": self.arm,
            "patch_operation": "no_change" if no_change else "retract" if retract else "revise",
        }
        if _edit_metadata is not None and "revision_evidence" in _edit_metadata:
            proposal["revision_evidence"] = _edit_metadata["revision_evidence"]
        if not no_change:
            support["content"] = handles
            proposal["functional_support"] = support
            proposal["removed_field_support"] = {"record": handles} if retract else {}
        if self.revision_support_review is not None and not no_change:
            self.service.prepare_proposal(bound["session"], operation_id, proposal)
            existing = self._run_support_review(
                self.revision_support_review,
                self._revision_evidence(bound, proposal, old, operation_id),
                bound,
                refs,
                operation_id,
                requested,
            )
            if existing is not None:
                return existing
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
        if self.interface_version != "v1":
            return self._writer_tools()

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

        def rewrite_memory(
            read_handle: str,
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            units: list[NewUnit] | None = None,
            relations: list[NewRelation] | None = None,
            withdrawal_evidence: list[str] | None = None,
        ) -> ToolMessage:
            """Rewrite the WHOLE actual read record with complete units and relations.

            Include all retained text, conditions and relations. Use actually delivered
            fragment_handles for every evidence[], never source_ref. Local edits and
            old unit IDs are not accepted. Record scope stays unchanged. Omit units
            or set units=null for exact no_change, with no relations or withdrawal
            evidence. Explicit units=[] withdraws the whole record and REQUIRES actual
            delivered withdrawal_evidence beyond its prior affirmative support ranges.
            Whole withdrawal cannot include replacement text or relations. It retains
            exact readable history and does not physically forget sources or records.
            """
            return message(
                "update_memory",
                tool_call_id,
                self._mutation(
                    lambda: self.rewrite_edit(
                        config,
                        tool_call_id,
                        read_handle,
                        [unit.model_dump() for unit in units] if units is not None else None,
                        [relation.model_dump() for relation in relations] if relations else [],
                        withdrawal_evidence,
                    )
                ),
            )

        replacements = {
            "save_memory": StructuredTool.from_function(save_memory),
            "update_memory": StructuredTool.from_function(update_memory)
            if self.local
            else StructuredTool.from_function(
                rewrite_memory, name="update_memory", args_schema=_WholeRewriteInput
            ),
        }
        if not self.conditioned:
            replacements["save_memory"].description = (
                f"Save {self.arm} plain content units, with no relations. "
                "Keep conditions and uncertainty "
                "in their text. Each evidence list copies actually delivered source "
                "fragment_handles, never source_ref. Unit IDs are issued by the Host. "
                "scope is explicit record "
                "metadata. Saving is a memory-only effect and proves no business outcome."
            )
        elif self.arm == "B2":
            replacements["save_memory"].description = replacements[
                "save_memory"
            ].description.replace("Save M", "Save B2", 1)
        if self.arm == "B1":
            replacements["update_memory"].description = (
                "Edit the actual read B1 record using replace/insert/delete. Copy target_unit "
                "from delivered edit_unit IDs and evidence from actual delivered source "
                "fragment_handles, never source_ref. insert follows target_unit, or appends "
                "when it is null. Unselected units and record scope remain unchanged. Keep "
                "conditions in plain text. Full withdrawal needs a new cancellation witness. "
                "An empty edits list confirms exact no_change."
            )
        return tuple(replacements.get(tool.name, tool) for tool in super().tools())

    def writer_tools(self, config: RunnableConfig) -> tuple[BaseTool, ...]:
        """Actual per-request SDK tools after writer_context has delivered its map."""
        if not self.features.enabled:
            return self.tools()
        active = self.service.store.get(
            namespace(self.service), self._writer_key(config, "edit-writer-active:")
        )
        mapping = self.writer.load_mapping(active.value["mapping_id"]) if active else {}
        return self._writer_tools(mapping)

    def _writer_tools(self, mapping: dict[str, Any] | None = None) -> tuple[BaseTool, ...]:
        """The same arm catalogue drives real SDK schemas and decoding."""
        if self.features.enabled and mapping is None:
            # Static ToolNode functions parse dictionaries and execute the same
            # operation-bound decoder. Only writer_tools(config) advertises the
            # actual per-request schemas to the model.
            create_schema: dict[str, Any] | None = {"type": "object"}
            update_schema: dict[str, Any] = {"type": "object"}
        else:
            schema = self.writer.proposal_schema(mapping=mapping)
            create_schema = next(
                (
                    item
                    for item in schema.get("oneOf", [])
                    if item["properties"]["action"]["const"] == "create"
                ),
                None,
            )
            update_schema = self.writer.proposal_schema(allow_create=False, mapping=mapping)

        class SaveInput(_WriterSaveInput):
            proposal: dict[str, Any] = Field(json_schema_extra=create_schema or {})

        class UpdateInput(_WriterInput):
            proposal: dict[str, Any] = Field(json_schema_extra=update_schema)

        def save_memory(
            proposal: dict[str, Any],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
            scope: dict[str, Any] | None = None,
        ) -> ToolMessage:
            """Create using the current writer packet's e evidence. IDs are issued by the Host."""
            return result_message("save_memory", config, tool_call_id, proposal, scope)

        def update_memory(
            proposal: dict[str, Any],
            config: RunnableConfig,
            *,
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> ToolMessage:
            """Maintain a current writer target r with its legal arm operation, or no_change."""
            return result_message("update_memory", config, tool_call_id, proposal)

        def result_message(
            name: str,
            config: RunnableConfig,
            call_id: str,
            proposal: dict[str, Any],
            scope: dict[str, Any] | None = None,
        ) -> ToolMessage:
            def apply() -> dict[str, Any]:
                if (name == "save_memory") != (proposal.get("action") == "create"):
                    raise FunctionalRejection("FUNCTIONAL_EDIT_WRITER_TOOL_ACTION_INVALID")
                return self.apply_writer_proposal(config, call_id, proposal, scope=scope)

            result = self._mutation(apply)
            return ToolMessage(
                name=name,
                tool_call_id=call_id,
                content=canonical(result),
                status="success" if result.get("ok") else "error",
            )

        replacements = {
            "save_memory": (
                _ExplicitWriterTool if self.features.enabled else StructuredTool
            ).from_function(save_memory, args_schema=SaveInput),
            "update_memory": (
                _ExplicitWriterTool if self.features.enabled else StructuredTool
            ).from_function(update_memory, args_schema=UpdateInput),
        }
        replacements["update_memory"].description = self.writer.instructions(allow_create=False) + (
            "Here the tool arguments replace the proposals envelope: proposal is one legal "
            "maintenance action. Apply a supported correction to an actual delivered target. "
            "With no justified maintenance, do not call this tool. "
            "A targeted no_change needs an actual delivered r alias."
        )
        return tuple(
            replacements.get(tool.name, tool)
            for tool in super().tools()
            if not (tool.name == "save_memory" and create_schema is None)
            and not (tool.name == "update_memory" and self.arm == "Append-only")
            and not (
                tool.name == "update_memory"
                and self.features.enabled
                and mapping is not None
                and "oneOf" not in update_schema
            )
        )
