"""Four memory-maintenance arms over one existing MemoryService.

The caller owns model execution and chronological source ingestion. No benchmark,
scorer, future question, model client, or second database belongs in this module.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.memory.edit_units import (
    ARM_OPERATIONS,
    OPERATION_INSTRUCTIONS,
    EditProposal,
    apply_local,
    form_state,
    issue_evidence,
    new_id,
    render_state,
    source_evidence,
    writer_projection,
    writer_proposal_schema,
)
from milai_lab.memory.functional_state import FunctionalRejection, body_text, resolve_fragment
from milai_lab.memory.service import MemoryService

Arm = Literal["B0", "B1", "B2", "M"]
METHOD_VERSION = "milai_edit_v1"
V2_METHOD_VERSION = "milai_edit_v2"
InterfaceVersion = Literal["v1", "I1", "I2"]


class EditMemory:
    """Ordinary full rewrite, plain local edit, and a controlled representation pair."""

    def __init__(
        self, service: MemoryService, arm: Arm, *, interface_version: InterfaceVersion = "v1"
    ) -> None:
        if arm not in {"B0", "B1", "B2", "M"}:
            raise ValueError("EDIT_ARM_INVALID")
        self.service, self.arm = service, arm
        self.conditioned = arm in {"B2", "M"}
        if interface_version not in {"v1", "I1", "I2"}:
            raise ValueError("EDIT_INTERFACE_INVALID")
        self.interface_version = interface_version
        self.method_version = METHOD_VERSION if interface_version == "v1" else V2_METHOD_VERSION

    def proposal_schema(self, *, allow_create: bool = True) -> dict[str, Any]:
        if self.interface_version == "v1":
            return EditProposal.model_json_schema()
        return writer_proposal_schema(self.arm, allow_create=allow_create)

    def envelope_schema(self, *, allow_create: bool = True) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["proposals"],
            "properties": {
                "proposals": {
                    "type": "array",
                    "minItems": 0,
                    "items": self.proposal_schema(allow_create=allow_create),
                }
            },
        }

    def instructions(self, *, allow_create: bool = True) -> str:
        if self.interface_version != "v1":
            operations = ARM_OPERATIONS[self.arm]
            return (
                "Return the supplied JSON envelope. Use only actual events and your prior state. "
                "Preserve subjects, times, qualifications, uncertainty and source attribution. "
                "A request does not prove a business outcome. target uses r#; u# labels prior "
                "units. evidence uses only e# with its supplied body "
                "in this request. keep_support selects h# EXISTING_SUPPORT_ONLY, never new proof. "
                "New or changed claims and new relations need new e evidence. An unchanged unit "
                "or relation may explicitly retain its own h support with evidence=[]. For a unit "
                "retained only via h, copy its exact delivered text and role. h is not semantic "
                "approval for synonymous wording: changed text, including a paraphrase, needs "
                "supporting new e. Do not move "
                "another unit's support to an unrelated claim. A changed claim may retain "
                "its prior h qualifiers alongside new e. Do not invent aliases or base revisions. "
                "Every r/u/e/h alias must appear in the current delivered writer packet; "
                "numbering never implies availability. Maintain supported durable new facts and "
                "actual corrections: choose create when allowed and no delivered record already "
                "covers the fact, or the applicable existing-record action for a correction. "
                "records=[] means no old record was delivered, not that new e evidence is absent. "
                "Do not return an empty envelope merely because the memory bank is empty. "
                "Capturing a new utterance does not mean it deserves semantic memory. Social "
                "acknowledgments or ordinary queries with no new durable fact or actual correction "
                "need no save; a query that also supplies a durable fact may still justify one. "
                "If there is genuinely no justified creation or record change, return "
                '{"proposals":[]}. Targeted no_change only confirms a delivered existing record. '
                "If records=[], do not invent a target, including for no_change. "
                "Do not infer applicability from old support metadata. "
                + (
                    "create is available. "
                    if allow_create
                    else "create is unavailable in this request. If records=[], no permitted "
                    'target exists: return {"proposals":[]} even if e contains a new fact. '
                )
                + (
                    "For an existing record use edit; legal operations: "
                    + ", ".join(operations)
                    + ". Emit only changed units; untouched text and support remain verbatim. "
                    if operations
                    else "Use rewrite for an existing record; generate the complete replacement, "
                    "including all retained units and relations. Never fill missing text. "
                    "Empty units withdraw the record only with new withdrawal_evidence e#. "
                )
                + (
                    "Use one layer of explicit content/condition units and modifies/overrides "
                    "relations. A generated relation uses zero-based indexes into generated units. "
                    if self.conditioned
                    else "Use plain content units; keep conditions in their text. "
                )
                + "".join(OPERATION_INSTRUCTIONS[operation] for operation in operations)
                + self._instruction_examples(allow_create=allow_create)
            )
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

    def _instruction_examples(self, *, allow_create: bool) -> str:
        """Illustrative valid envelopes, never extra evidence for the real request."""
        units: list[dict[str, Any]] = [
            {"text": "Reminders are quiet.", "role": "content", "evidence": ["e1"]},
            {
                "text": "Only during the exhibition.",
                "role": "condition" if self.conditioned else "content",
                "evidence": ["e1"],
            },
        ]
        create: dict[str, Any] = {"action": "create", "units": units}
        if self.conditioned:
            create["relations"] = [
                {"source": 1, "target": 0, "relation_type": "modifies", "evidence": ["e1"]}
            ]
        if ARM_OPERATIONS[self.arm]:
            correction: dict[str, Any] = {
                "action": "edit",
                "target": "r1",
                "edits": [
                    {
                        "operation": "replace",
                        "target_unit": "u1",
                        "text": "Reminders use a soft tone.",
                        "evidence": ["e1"],
                        "keep_support": ["h1"],
                    }
                ],
            }
        else:
            retained = copy.deepcopy(units)
            retained[0].update(text="Reminders use a soft tone.", keep_support=["h1"])
            retained[1].update(evidence=[], keep_support=["h2"])
            correction = {"action": "rewrite", "target": "r1", "units": retained}
            if self.conditioned:
                correction["relations"] = [
                    {
                        "source": 1,
                        "target": 0,
                        "relation_type": "modifies",
                        "evidence": [],
                        "keep_support": ["h3"],
                    }
                ]
        examples = (
            " Examples use hypothetical CURRENT deliveries and illustrate legal action shapes, "
            "not facts, available aliases or required topics for your real request. Do not copy "
            "example text as facts: generate actual memory from current e bodies and your own "
            "delivered prior state, using only references that occur in your actual packet. "
        )
        if allow_create:
            examples += (
                "For formation, assume current records=[] and actual e1 says 'Reminders are "
                "quiet, only during the exhibition.' That is supported new information even "
                "with no old record. Formation response: "
                + json.dumps({"proposals": [create]}, ensure_ascii=False, separators=(",", ":"))
                + ". "
            )
        examples += (
            "For an empty example, assume current e contains only social acknowledgment such as "
            "'Thank you' or an ordinary query such as 'Could you look that up?', with no new "
            "durable fact and no justified record change. Do not turn the occurrence of that "
            'utterance into a semantic fact. empty response: {"proposals":[]}. '
        )
        examples += (
            "For correction, assume the CURRENT packet actually delivers r1 with u1='Reminders "
            "are quiet.' and u2='Only during the exhibition.', h1/h2 retaining those units' own "
            "support, "
            + ("and h3 retaining their modifies relation, " if self.conditioned else "")
            + "and actual e1 says 'Reminders use a soft tone.' The old exhibition limit was not "
            "restated or canceled: copy its delivered text and role exactly with h2, without "
            "paraphrasing it; change the supported tone using e1. If target references "
            "are absent, this correction example does not apply. Correction response: "
            + json.dumps({"proposals": [correction]}, ensure_ascii=False, separators=(",", ":"))
            + ". Choose supported maintenance when justified; empty is only for no justified "
            "permitted action."
        )
        return examples

    def prepare(
        self,
        actual_source_refs: list[str],
        query: str,
        *,
        limit: int = 6,
        source_ranges: list[dict[str, Any]] | None = None,
        selected_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Shared retrieval from already occurred events; the caller bounds delivery equally."""
        selected = (
            self.service.search(query, limit=limit, include_raw=False)["records"]
            if selected_records is None
            else selected_records
        )
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
            if not row.get("ok") or not isinstance(row.get("value"), dict):
                raise FunctionalRejection("EDIT_RECORD_UNAVAILABLE")
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
            record = {
                "record_id": row["id"],
                "revision": version["revision"],
                "content": version["content"],
                "edit_state": state,
            }
            if self.interface_version != "v1":
                record["scope"] = copy.deepcopy(version.get("scope", {}))
            records.append(record)
        return {
            "method_version": self.method_version,
            "sources": sources,
            "records": records,
            "historical_evidence": list(historical_evidence.values()),
        }

    def preview_writer_view(
        self, delivery: dict[str, Any], *, allow_create: bool = True
    ) -> dict[str, Any]:
        """Pure budget projection; this result grants no read or mutation authority."""
        self._require_v2()
        packet, _ = writer_projection(
            delivery, self.interface_version, self.arm, allow_create=allow_create
        )
        return {"packet": packet}

    def _require_v2(self) -> None:
        if self.interface_version == "v1":
            raise FunctionalRejection("EDIT_V2_INTERFACE_REQUIRED")

    @property
    def mapping_namespace(self) -> tuple[str, ...]:
        return (*self.service.namespace, "edit_writer_views")

    def writer_view(
        self,
        delivery: dict[str, Any],
        *,
        request_id: str | None = None,
        allow_create: bool = True,
    ) -> dict[str, Any]:
        """Bind only the supplied whole records and actual delivered source ranges.

        No retrieval is performed. The trusted caller invokes this only for the
        packet it will send, after pure previews and complete-request budgeting.
        """
        self._require_v2()
        checked = copy.deepcopy(delivery)
        for source in checked.get("sources", []):
            fragment = resolve_fragment(self.service, source["evidence_id"])
            if (
                not source.get("body_delivered")
                or source.get("text") != fragment["content"]
                or any(
                    source[key] != fragment[key]
                    for key in ("source_ref", "source_revision", "start", "end")
                )
            ):
                raise FunctionalRejection("EDIT_ACTUAL_DELIVERY_REQUIRED")
        for record in checked.get("records", []):
            actual = self.service.read(record["record_id"], record["revision"])
            if not actual.get("ok") or any(
                record.get(key) != actual["value"].get(key) for key in ("content", "edit_state")
            ):
                raise FunctionalRejection("EDIT_COMPLETE_ACTUAL_RECORD_REQUIRED")
            if "scope" in record and record["scope"] != actual["value"].get("scope", {}):
                raise FunctionalRejection("EDIT_ACTUAL_SCOPE_REQUIRED")
            record["candidate_handle"] = actual.get("candidate_handle")
        packet, mapping = writer_projection(
            checked, self.interface_version, self.arm, allow_create=allow_create
        )
        mapping.update(
            mapping_id="edit-map:" + request_id if request_id is not None else new_id("edit-map"),
            owner=self.service.owner,
            bank=list(self.service.namespace),
            packet=packet,
        )
        with self.service._locked():
            prior = self.service.store.get(self.mapping_namespace, mapping["mapping_id"])
            if prior is not None and prior.value != mapping:
                raise FunctionalRejection("EDIT_MAPPING_REQUEST_CHANGED")
            if prior is None:
                self.service.store.put(
                    self.mapping_namespace, mapping["mapping_id"], mapping, index=False
                )
            persisted = self.service.store.get(self.mapping_namespace, mapping["mapping_id"])
            if persisted is None or persisted.value != mapping:
                raise FunctionalRejection("EDIT_MAPPING_PERSISTENCE_UNCONFIRMED")
        return {"packet": packet, "mapping": mapping}

    def load_mapping(self, mapping_id: str) -> dict[str, Any]:
        item = self.service.store.get(self.mapping_namespace, mapping_id)
        if item is None:
            raise FunctionalRejection("EDIT_MAPPING_UNAVAILABLE")
        mapping: dict[str, Any] = copy.deepcopy(item.value)
        if (
            mapping.get("owner") != self.service.owner
            or mapping.get("bank") != list(self.service.namespace)
            or mapping.get("arm") != self.arm
            or mapping.get("interface_version") != self.interface_version
        ):
            raise FunctionalRejection("EDIT_MAPPING_OWNERSHIP_MISMATCH")
        return mapping

    def decode_proposal(
        self, proposal: dict[str, Any], mapping: dict[str, Any] | str
    ) -> dict[str, Any]:
        """Exact short references to legacy DTOs, bound to the actual read revision.

        This verifies structural support selection, not entailment or applicability.
        Changed statements still require an explicit new delivered evidence choice.
        """
        self._require_v2()
        bound = self.load_mapping(mapping if isinstance(mapping, str) else mapping["mapping_id"])
        if not isinstance(mapping, str) and mapping != bound:
            raise FunctionalRejection("EDIT_MAPPING_CHANGED")
        errors = list(
            Draft202012Validator(
                self.proposal_schema(allow_create=bound["allow_create"])
            ).iter_errors(proposal)
        )
        if errors:
            raise FunctionalRejection("EDIT_PUBLIC_PROPOSAL_INVALID: " + errors[0].message)
        target = proposal.get("target")
        record = bound["records"].get(target) if target else None
        if target and record is None:
            raise FunctionalRejection("EDIT_SHORT_REFERENCE_UNAVAILABLE")
        decoded: dict[str, Any] = {"action": proposal["action"]}
        if record:
            if not self.service.read(record["record_id"], record["revision"])["ok"]:
                raise FunctionalRejection("EDIT_RECORD_UNAVAILABLE")
            decoded.update(target_record=record["record_id"], base_revision=record["revision"])

        def alias_unit(alias: str) -> dict[str, Any]:
            unit = bound["units"].get(alias)
            if unit is None or unit["record"] != target:
                raise FunctionalRejection("EDIT_SHORT_UNIT_UNAVAILABLE")
            return unit  # type: ignore[no-any-return]

        def supports(item: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
            handles, kept = [], []
            for alias in item.get("evidence", []):
                evidence = bound["evidence"].get(alias)
                if evidence is None:
                    raise FunctionalRejection("EDIT_SHORT_EVIDENCE_UNAVAILABLE")
                # Visibility can be revoked since the delivery; never bypass forget.
                resolve_fragment(self.service, evidence["evidence_id"])
                handles.append(evidence["evidence_id"])
            for alias in dict.fromkeys(item.get("keep_support", [])):
                support = bound["support"].get(alias)
                if support is None or support["record"] != target:
                    raise FunctionalRejection("EDIT_SHORT_SUPPORT_UNAVAILABLE")
                kept.append(support)
                handles.extend(ref["evidence_id"] for ref in support["evidence_refs"])
            if not handles:
                raise FunctionalRejection("EDIT_EVIDENCE_REQUIRED")
            return list(dict.fromkeys(handles)), kept

        origins: list[set[str]] = []
        for item in proposal.get("units", []):
            handles, kept = supports(item)
            origin = {support["unit"] for support in kept if "unit" in support}
            if len(origin) != len(kept) or len(origin) > 1:
                raise FunctionalRejection("EDIT_UNIT_SUPPORT_BINDING_INVALID")
            if not item.get("evidence") and not any(
                alias_unit(alias)["text"] == item["text"]
                and alias_unit(alias)["role"] == item.get("role", "content")
                for alias in origin
            ):
                raise FunctionalRejection("EDIT_CHANGED_CLAIM_REQUIRES_NEW_EVIDENCE")
            origins.append(origin)
            decoded.setdefault("units", []).append(
                {"text": item["text"], "role": item.get("role", "content"), "evidence": handles}
            )
        for item in proposal.get("relations", []):
            handles, kept = supports(item)
            if max(item["source"], item["target"]) >= len(origins):
                raise FunctionalRejection("EDIT_FORMATION_RELATION_INDEX_INVALID")
            for support in kept:
                if (
                    support.get("relation_type") != item["relation_type"]
                    or support.get("source") not in origins[item["source"]]
                    or support.get("target") not in origins[item["target"]]
                ):
                    raise FunctionalRejection("EDIT_RELATION_SUPPORT_BINDING_INVALID")
            if not item.get("evidence") and not kept:
                raise FunctionalRejection("EDIT_NEW_RELATION_REQUIRES_NEW_EVIDENCE")
            decoded.setdefault("relations", []).append(
                {
                    **{key: item[key] for key in ("source", "target", "relation_type")},
                    "evidence": handles,
                }
            )
        for item in proposal.get("edits", []):
            handles, kept = supports(item)
            unit = alias_unit(item["target_unit"]) if item.get("target_unit") else None
            if any(support.get("unit") != item.get("target_unit") for support in kept):
                raise FunctionalRejection("EDIT_UNIT_SUPPORT_BINDING_INVALID")
            if not item.get("evidence") and (
                item["operation"] != "replace" or unit is None or item["text"] != unit["text"]
            ):
                raise FunctionalRejection("EDIT_CHANGED_CLAIM_REQUIRES_NEW_EVIDENCE")
            edit = {
                key: value for key, value in item.items() if key not in {"evidence", "keep_support"}
            }
            edit["evidence"] = handles
            if unit:
                edit["target_unit"] = unit["unit_id"]
            for field in ("shared_conditions", "attach_to"):
                if field in edit:
                    edit[field] = [alias_unit(alias)["unit_id"] for alias in edit[field]]
            decoded.setdefault("edits", []).append(edit)
        if proposal["action"] == "rewrite" and not proposal["units"]:
            witnesses = proposal.get("withdrawal_evidence", [])
            if not witnesses or proposal.get("relations"):
                raise FunctionalRejection("EDIT_WITHDRAWAL_EVIDENCE_REQUIRED")
            decoded["units"] = []
            decoded["withdrawal_evidence"] = supports({"evidence": witnesses})[0]
        elif proposal.get("withdrawal_evidence"):
            raise FunctionalRejection("EDIT_REWRITE_HAS_WITHDRAWAL_EVIDENCE")
        return decoded

    def apply(
        self,
        session: str,
        proposal_id: str,
        proposal: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply one parsed proposal through the existing service revision transaction."""
        withdrawal = (
            proposal.get("withdrawal_evidence", []) if self.interface_version != "v1" else []
        )
        internal = (
            {k: v for k, v in proposal.items() if k != "withdrawal_evidence"}
            if withdrawal
            else proposal
        )
        parsed = EditProposal.model_validate(internal)
        requested = {"method": self.method_version, "arm": self.arm, "proposal": proposal}
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
            if withdrawal:
                if parsed.action != "rewrite" or parsed.units or parsed.relations or old is None:
                    raise FunctionalRejection("EDIT_WITHDRAWAL_MUST_OMIT_NEW_BODY")
                witnesses = source_evidence(self.service, withdrawal)
                old_refs = [
                    ref
                    for item in [*old["edit_state"]["units"], *old["edit_state"]["relations"]]
                    for ref in item["evidence_refs"]
                ]
                if all(
                    any(
                        ref["source_ref"] == previous["source_ref"]
                        and ref["source_revision"] == previous["source_revision"]
                        and previous["start"] <= ref["start"] <= ref["end"] <= previous["end"]
                        for previous in old_refs
                    )
                    for ref in witnesses
                ):
                    raise FunctionalRejection("EDIT_NEW_WITHDRAWAL_WITNESS_REQUIRED")
                state = {
                    "representation": "conditioned_v1" if self.conditioned else "plain_v1",
                    "units": [],
                    "relations": [],
                }
            else:
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
            cancellation_refs.extend(
                ref["source_ref"] for ref in source_evidence(self.service, withdrawal)
            ) if withdrawal else None
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
            "method_version": self.method_version,
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
