"""Four memory-maintenance arms over one existing MemoryService.

The caller owns model execution and chronological source ingestion. No benchmark,
scorer, future question, model client, or second database belongs in this module.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from milai_lab.memory.edit_units import (
    EditProposal,
    apply_local,
    form_state,
    issue_evidence,
    render_state,
    source_evidence,
)
from milai_lab.memory.functional_state import FunctionalRejection, body_text
from milai_lab.memory.service import MemoryService

Arm = Literal["B0", "B1", "B2", "M"]
METHOD_VERSION = "milai_edit_v1"


class EditMemory:
    """Ordinary full rewrite, plain local edit, and a controlled representation pair."""

    def __init__(self, service: MemoryService, arm: Arm) -> None:
        if arm not in {"B0", "B1", "B2", "M"}:
            raise ValueError("EDIT_ARM_INVALID")
        self.service, self.arm = service, arm
        self.conditioned = arm in {"B2", "M"}

    def proposal_schema(self) -> dict[str, Any]:
        return EditProposal.model_json_schema()

    def instructions(self) -> str:
        common = (
            "Maintain persistent memory using only supplied actual events "
            "and your own prior records. "
            "Do not infer that a request proves a business result. Preserve uncertainty, subjects, "
            "times, exceptions and provenance. Select evidence_id values from supplied material. "
            "Use target_record/base_revision and existing unit IDs exactly as supplied. "
            "Use no_change when no maintenance is justified. For initial formation return units; "
            "relations use zero-based indexes into those new units. Do not invent evidence IDs or "
            "unit IDs. A source reference identifies evidence, not semantic proof. "
            "Historical evidence metadata identifies your prior state; its original body is not "
            "delivered again and does not provide a new semantic support check. "
        )
        if self.arm in {"B0", "B2"}:
            operation = (
                "For an existing record use rewrite and generate its entire new representation. "
            )
        elif self.arm == "B1":
            operation = (
                "For an existing record use edit with replace/insert/delete "
                "on selected text units. "
                "Generate only changed text; unselected units remain verbatim. "
                "insert appends after target_unit, or at the end when target_unit is null. "
            )
        else:
            operation = (
                "For an existing record use edit with replace/append/override/retract. "
                "override needs explicit condition text and preserves the general arrangement "
                "outside that scope. Only one override layer is supported. shared_conditions "
                "explicitly attaches existing conditions to a new override; choose applicability "
                "from evidence, never merely from wording length. append may add a condition "
                "with attach_to listing actual content unit IDs. retract removes only the chosen "
                "unit and its incident relations; cancellation does not affirm the opposite. "
                "A correction for all scopes must explicitly edit all affected units "
                "in one proposal. "
                "For ambiguous or nested scopes preserve original text/uncertainty rather than "
                "silently treating the change as global. "
            )
        representation = (
            "Use content and condition units, modifies(condition→content) and "
            "overrides(scoped content→general content) relations. "
            if self.conditioned
            else "Use only content units with no relations. Keep conditions in the text. "
        )
        return common + operation + representation

    def prepare(
        self,
        actual_source_refs: list[str],
        query: str,
        *,
        limit: int = 6,
        source_ranges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Shared retrieval from already occurred events; the caller bounds delivery equally."""
        selected = self.service.search(query, limit=limit, include_raw=False)["records"]
        actual_refs = list(dict.fromkeys(actual_source_refs))
        ranges = source_ranges
        if ranges is None:
            ranges = []
            for ref in actual_refs:
                source = self.service.source(ref)
                if source is None:
                    raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")
                ranges.append({"source_ref": ref, "start": 0, "end": len(body_text(source))})
        if {part.get("source_ref") for part in ranges} != set(actual_refs):
            raise FunctionalRejection("EDIT_DELIVERED_SOURCE_RANGES_MISMATCH")
        sources = []
        for part in ranges:
            ref = part["source_ref"]
            source = self.service.source(ref)
            if source is None:
                raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")
            evidence = issue_evidence(self.service, ref, part["start"], part["end"])
            sources.append(
                {
                    **evidence,
                    "role": source["role"],
                    "observed_at": source["observed_at"],
                    "text": body_text(source)[part["start"] : part["end"]],
                    "body_delivered": True,
                    "semantic_support": "unchecked",
                }
            )
        records = []
        historical_evidence: dict[str, dict[str, Any]] = {}
        delivered_ids = {source["evidence_id"] for source in sources}
        for row in selected:
            version = row["value"]
            state = copy.deepcopy(version.get("edit_state"))
            refs = []
            if state:
                for item in [*state["units"], *state["relations"]]:
                    for ref in item["evidence_refs"]:
                        if "evidence_id" not in ref:
                            ref.update(
                                issue_evidence(
                                    self.service, ref["source_ref"], ref["start"], ref["end"]
                                )
                            )
                        refs.append(ref)
            else:
                for ref in version.get("source_refs", [version["source_ref"]]):
                    source = self.service.source(ref)
                    if source is not None:
                        refs.append(issue_evidence(self.service, ref, 0, len(body_text(source))))
            for ref in refs:
                if ref["evidence_id"] not in delivered_ids:
                    historical_evidence[ref["evidence_id"]] = {
                        **ref,
                        "body_delivered": False,
                        "semantic_support": "unchecked",
                    }
            records.append(
                {
                    "record_id": row["id"],
                    "revision": version["revision"],
                    "content": version["content"],
                    "edit_state": state,
                }
            )
        return {
            "method_version": METHOD_VERSION,
            "sources": sources,
            "records": records,
            "historical_evidence": list(historical_evidence.values()),
        }

    def apply(
        self,
        session: str,
        proposal_id: str,
        proposal: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply one parsed proposal through the existing service revision transaction."""
        parsed = EditProposal.model_validate(proposal)
        requested = {"method": METHOD_VERSION, "arm": self.arm, "proposal": proposal}
        replay = self.service.replay_requested(session, proposal_id, requested)
        if replay is not None:
            return replay
        if parsed.action == "no_change" and parsed.target_record is None:
            if parsed.base_revision is not None or parsed.units or parsed.relations or parsed.edits:
                raise FunctionalRejection("EDIT_NO_CHANGE_HAS_MUTATIONS")
            return self.service.record_no_change(session, proposal_id, requested)
        old: dict[str, Any] | None = None
        row: dict[str, Any] | None = None
        if parsed.action == "create":
            if parsed.target_record is not None or parsed.base_revision is not None or parsed.edits:
                raise FunctionalRejection("EDIT_CREATE_TARGET_INVALID")
        else:
            if parsed.target_record is None or parsed.base_revision is None:
                raise FunctionalRejection("EDIT_ACTUAL_BASE_REVISION_REQUIRED")
            row = self.service.read(parsed.target_record, parsed.base_revision)
            if not row["ok"]:
                raise FunctionalRejection("EDIT_RECORD_UNAVAILABLE")
            old = row["value"]
        state: dict[str, Any] | None
        if parsed.action in {"create", "rewrite"}:
            if parsed.action == "rewrite" and self.arm not in {"B0", "B2"}:
                raise FunctionalRejection("EDIT_FULL_REWRITE_NOT_AVAILABLE_IN_LOCAL_ARM")
            if parsed.edits:
                raise FunctionalRejection("EDIT_REWRITE_MUST_OMIT_EDITS")
            state = form_state(parsed, self.service, conditioned=self.conditioned)
        elif parsed.action == "no_change":
            if parsed.units or parsed.relations or parsed.edits:
                raise FunctionalRejection("EDIT_NO_CHANGE_HAS_MUTATIONS")
            assert old is not None
            state = old.get("edit_state")
        else:
            if self.arm not in {"B1", "M"} or parsed.units or parsed.relations or not parsed.edits:
                raise FunctionalRejection("EDIT_LOCAL_OPERATIONS_REQUIRED")
            assert old is not None
            if "edit_state" not in old:
                raise FunctionalRejection("EDIT_OLD_RECORD_REQUIRES_EXPLICIT_FORMATION")
            if old["edit_state"]["representation"] != (
                "conditioned_v1" if self.conditioned else "plain_v1"
            ):
                raise FunctionalRejection("EDIT_REPRESENTATION_MISMATCH")
            state = apply_local(
                old["edit_state"], parsed.edits, self.service, conditioned=self.conditioned
            )
        if parsed.action == "no_change":
            assert old is not None
            refs = old.get("source_refs", [old["source_ref"]])
            content = old["content"]
        else:
            assert state is not None
            refs = list(
                dict.fromkeys(
                    ref["source_ref"]
                    for item in [*state["units"], *state["relations"]]
                    for ref in item["evidence_refs"]
                )
            )
            # Retractions retain the cancellation witness even though removed units exit state.
            cancellation_refs = [
                ref["source_ref"]
                for edit in parsed.edits
                for ref in source_evidence(self.service, edit.evidence)
            ]
            refs = list(dict.fromkeys([*cancellation_refs, *refs]))
            content = render_state(state)
        refs = list(dict.fromkeys([*refs, *((old or {}).get("source_refs", []))]))
        raw = {
            "action": "create" if old is None else "update",
            "id": None if row is None else row["id"],
            "expected_revision": 0 if old is None else old["revision"],
            "candidate_handle": None if row is None else row.get("candidate_handle"),
            "content": content,
            "kind": (old or {}).get("kind", "semantic"),
            "scope": (old or {}).get("scope", {}),
            "basis": "inference",
            "fields": (old or {}).get("fields", {}),
            "object_ref": (old or {}).get("object_ref"),
            "source_ref": refs[0],
            "source_refs": refs,
            "requested": requested,
            "edit_state": state,
            "edit_operations": [edit.model_dump() for edit in parsed.edits],
            "method_version": METHOD_VERSION,
            "method_arm": self.arm,
            "patch_operation": "no_change"
            if parsed.action == "no_change"
            else "retract"
            if state is not None and not any(u["role"] == "content" for u in state["units"])
            else "revise",
        }
        if self.service.support_contract == "direct_support_v1":
            raw["field_support"] = {
                field: {"source_refs": refs} for field in ("content", "scope", "basis", "kind")
            }
            raw["trigger_binding"] = self.service.public_turn(session)
        return self.service.commit(session, proposal_id, raw)

    @staticmethod
    def render(version: dict[str, Any]) -> str:
        return (
            render_state(version["edit_state"]) if version.get("edit_state") else version["content"]
        )
