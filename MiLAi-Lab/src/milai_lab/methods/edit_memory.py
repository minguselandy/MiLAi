"""Four memory-maintenance arms over one existing MemoryService.

The caller owns model execution and chronological source ingestion. No benchmark,
scorer, future question, model client, or second database belongs in this module.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.contracts.memory import ObservationProfile
from milai_lab.memory.edit_units import (
    ARM_OPERATIONS,
    OPERATION_INSTRUCTIONS,
    EditProposal,
    apply_local,
    clause_proposal,
    form_state,
    issue_evidence,
    new_id,
    render_revision_view,
    render_state,
    source_evidence,
    tool_source_origin,
    validate_applicability,
    writer_projection,
    writer_proposal_schema,
)
from milai_lab.memory.functional_state import FunctionalRejection, body_text, resolve_fragment
from milai_lab.memory.observation import maintenance_projection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import (
    EditFeatures,
    compact_prompt_schema,
    compile_semantic_operations,
    decorate_state,
    feature_envelope_schema,
    feature_proposal_schema,
)

Arm = Literal["B0", "B1", "B2", "M"]
METHOD_VERSION = "milai_edit_v1"
V2_METHOD_VERSION = "milai_edit_v2"
InterfaceVersion = Literal["v1", "I1", "I2"]

REVISION_MEANING_INSTRUCTIONS = (
    "Use the whole delivered matter to check linked conditions, exceptions and old overview "
    "statements, including those without explicit edges. A local revision covers all supported "
    "changes in their meaning; preserve unaffected scopes within mixed claims rather than "
    "keeping obsolete wording. Changed wording needs current correction evidence and any "
    "necessary redelivered old Source bodies, never h alone. Combine dependent changes in "
    "that target's single proposal. "
)


class EditMemory:
    """Ordinary full rewrite, plain local edit, and a controlled representation pair."""

    def __init__(
        self,
        service: MemoryService,
        arm: Arm,
        *,
        interface_version: InterfaceVersion = "v1",
        features: EditFeatures | None = None,
    ) -> None:
        if arm not in {"B0", "B1", "B2", "M"}:
            raise ValueError("EDIT_ARM_INVALID")
        self.service, self.arm = service, arm
        self.conditioned = arm in {"B2", "M"}
        if interface_version not in {"v1", "I1", "I2"}:
            raise ValueError("EDIT_INTERFACE_INVALID")
        self.interface_version = interface_version
        self.features = features or EditFeatures()
        if self.features.enabled and interface_version == "v1":
            raise ValueError("EDIT_FEATURES_REQUIRE_V2_INTERFACE")
        self.method_version = METHOD_VERSION if interface_version == "v1" else V2_METHOD_VERSION

    @property
    def method_name(self) -> str:
        return self.arm

    def proposal_schema(
        self, *, allow_create: bool = True, mapping: dict[str, Any] | None = None,
        for_generation: bool = True,
    ) -> dict[str, Any]:
        if self.interface_version == "v1":
            return EditProposal.model_json_schema()
        if self.features.enabled:
            schema = feature_proposal_schema(
                self.arm, self.features, mapping or {}, allow_create=allow_create,
                for_generation=for_generation,
            )
            if self.features.bound_references and mapping and mapping.get("records"):
                variants = [
                    v
                    for v in schema.get("oneOf", [])
                    if v["properties"]["action"]["const"] == "create"
                ]
                for target in mapping["records"]:
                    scoped = feature_proposal_schema(
                        self.arm, self.features, mapping, allow_create=False, target=target,
                        for_generation=for_generation,
                    )
                    for variant in scoped.get("oneOf", []):
                        variant["properties"]["target"] = {"type": "string", "const": target}
                        if "target" not in variant["required"]:
                            variant["required"].append("target")
                        variants.append(variant)
                return {"oneOf": variants}
            return schema
        return writer_proposal_schema(
            self.arm, allow_create=allow_create, for_generation=for_generation
        )

    def envelope_schema(
        self, *, allow_create: bool = True, mapping: dict[str, Any] | None = None,
        for_generation: bool = True,
    ) -> dict[str, Any]:
        if self.features.enabled:
            return feature_envelope_schema(
                self.arm, self.features, mapping or {}, allow_create=allow_create,
                for_generation=for_generation,
            )
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["proposals"],
            "properties": {
                "proposals": {
                    "type": "array",
                    "minItems": 0,
                    "items": self.proposal_schema(
                        allow_create=allow_create, for_generation=for_generation
                    ),
                }
            },
        }

    def instructions(self, *, allow_create: bool = True) -> str:
        if self.features.enabled:
            return self._feature_instructions(allow_create=allow_create)
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

    def _feature_instructions(self, *, allow_create: bool) -> str:
        empty = (
            '{"creates":[],"records":{}}'
            if self.features.single_record_changes
            else '{"proposals":[]}'
        )
        instruction = (
            "Maintain the supported changes in the current dialogue. Read current evidence first "
            "and use the delivered old matters to locate what needs revision. One event can revise "
            "related old matters and create distinct new matters. Preserve still-valid history "
            "and qualifications. Preferences, intentions and plans remain attributed reports "
            "with their time and status. Redelivered support supplies old context. "
            "Return the supplied JSON envelope. When the current dialogue adds no supported "
            "information or revision, return "
            + empty
            + ". "
            "Every r/u/e/h must be a candidate in THIS request. "
            "Only e has actually delivered body; "
            "h is EXISTING_SUPPORT_ONLY and cannot prove a changed claim or synonymous rewrite. "
            + ("" if self.arm == "B0" and self.features.source_metadata else
               "Copy retained text and role exactly when using only its own h. ")
            + "Changed claims and "
            "new relations require new e. Applicability and entailment are your decision, not "
            "certified by a source ID. Preserve subject, time, negation, "
            "qualification and uncertainty. Use one independently revisable assertion per "
            "clause. Separate the value from independently changeable qualifications; a "
            "single sentence in the source need not become a single memory unit. "
            "Delivered unit roles are read-only. Do not echo them into output clauses or "
            "conditions; their position declares the role. A new append or insert may select "
            "its role as allowed by the schema. "
        )
        if self.features.matter_organization:
            instruction += (
                "Each create is ONE independently maintainable matter with a separate matter "
                "description identifying its subject and issue, and its own complete units. "
                "Put unrelated matters in separate creates; the matter description is not a "
                "replacement for their supported bodies. Existing record.matter identifies the "
                "matter being maintained; never combine unrelated records or change their matter. "
            )
        if self.features.source_metadata:
            instruction += (
                "Every generated unit or text edit selects "
                "assertion={source_evidence:e#,kind:reported|"
                "inferred|observed|uncertain} from that item's new evidence. The service records "
                "the ACTUAL speaker role and occurrence time; this does not certify truth. "
                "Preserve assertion ownership in wording too: a user's report is a user report; "
                "an assistant's inference about them is an assistant inference, not an unowned "
                "replacement fact. Assistant material may still contain useful reports or "
                "inferences; neither ignore it all nor promote the last message automatically. "
                "To retain an exact old unit's attribution use assertion={keep:h#} selecting its "
                "own kept support; this cannot change text, role or attribution. "
                "Historical speaker "
                "and occurred_at remain actual metadata even when body_delivered=false. Unknown "
                "legacy attribution or time stays unknown; observed_at is the capture clock. "
            )
        if self.features.temporal_scope:
            instruction += (
                "Optional assertion.applicability selects explicit event_at/effective_from/"
                "effective_until/scope/quantity_scope from its new e; omit unknown fields. "
                "Put applicability inside the owning content/condition's assertion, never "
                "at its top level or in binding; binding carries only relation support. "
                "The selected Source supplies actual speaker role, report time and declared "
                "calendar; these are not effective_from/effective_until. "
                "Intervals are [from,until); ISO or English-month datetimes retain their "
                "stated precision and offset. A date denotes a day, without an inferred "
                "timezone. Date limits bound that calendar day. Only a framework-declared "
                "shared calendar_context permits nominal ordering of timezone-unknown values; "
                "it does not supply a physical timezone. Do not generate calendar_context. "
                "Report/capture/version clocks are service metadata, "
                "never inferred onset. Preserve relative time wording unless the Source supplies "
                "anchored applicability boundaries; omit unknown effective_from/effective_until "
                "instead of copying observed_date or observed_at. "
                "Explicit retrospective reports may explain the past; "
                "unspecified dates stay unknown and a plan's date does not prove completion. "
                "Keep independently changeable limits/scopes as separate conditions with "
                "their own support; exact kept units retain prior applicability. "
                "overall totals imply no per-member quantities or computed shares; per_member "
                "requires explicit source support. Different scopes do not use last-report-wins. "
                "Canceling an exception needs cancellation e, not reproof of the original "
                "value, and never revives an expired general rule. Optional assertion."
                "evidence_links={supports:[e#],opposes:[e#]} selects only this item's evidence "
                "and preserves actual source roles. Explicit links yield supported/opposed/"
                "both/insufficient evidence states, never certified truth; absent links stay "
                "insufficient. Generate semantic content/selections, not actual IDs or clocks. "
            )
        if self.arm in {"B0", "B2"}:
            instruction += (
                "Rewrite the WHOLE selected matter, generating its complete nonempty target "
                "clauses and bindings, including retained exact text/support/attribution. "
                "revision_evidence selects actual e for the whole revision, including "
                "removing an old clause or binding; retained clauses keep their own h support "
                "and attribution. Revision evidence does not support changed clause text. "
                "No hidden body is filled in. retract_record is a separate entire-record "
                "withdrawal with new actual e evidence and no replacement body. "
                "No local edits are available. "
            )
            if self.arm != "B0" or not self.features.source_metadata:
                instruction += (
                    "In a rewrite, from_unit=u# identifies which delivered unit the generated "
                    "clause or condition continues, independently of evidence. Each prior unit "
                    "has at most one such continuation, with the same role. It permits retaining "
                    "the existing binding after a supported value change; it retains no old text "
                    "or support by itself. "
                )
            if self.features.source_metadata:
                instruction += (
                    "For an unchanged old content clause, assertion={keep:h#} selects its "
                    "actual text, support and attribution. Return this keep reference without "
                    "text; keep_support need not be repeated. New or changed text selects "
                    "assertion={source_evidence:e#,kind:reported/inferred/observed/uncertain}. "
                    if self.arm == "B0" else
                    "With from_unit=u# and assertion={keep:h#} for that same old unit, "
                    "omit text to reuse its actual text, or repeat it exactly. This also reuses "
                    "its own support without repeating keep_support. Exact old text with "
                    "assertion={keep:h#} also reuses its support without from_unit. "
                    "Bindings still select their separate relation support. "
                )
            instruction += "Changed text still selects actual e evidence. "
        elif self.arm == "M" and self.features.semantic_operations:
            instruction += (
                "Within one record container use replace for same-scope changes to a delivered "
                "content or condition unit; its actual role and linked units/edges remain. "
                "Use add_exception for a local scoped alternative and remove_exception for an "
                "existing local alternative. "
                "add_exception retains its general rule and only attaches explicitly selected "
                "shared_conditions. remove_exception "
                "removes that alternative and its exclusive condition nodes, preserving general "
                "rules/shared conditions; it cannot reconstruct an already lost general rule. "
                "append/retract remain available for other local formation/removal. "
                "Dependent changes to delivered units "
                "belong in the same ordered edits list; the record commits once. "
                "shared_conditions selects only existing condition units. "
                "A content clause mentioning a prerequisite has no condition binding. Do not "
                "select it as a shared condition. With supporting new e, append a condition "
                "with explicit attach_to targets and retract the obsolete clause when justified; "
                "the service never infers this change from its wording. "
            )
        else:
            instruction += (
                "Local legal operations: "
                + ", ".join(ARM_OPERATIONS[self.arm])
                + ". Untouched units/support stay verbatim. "
            )
        if self.conditioned:
            instruction += (
                "Keep the value in content and express explicit applicability, limits and "
                "unresolved qualifications as conditions. Each content clause explicitly lists "
                "its conditions with their own support and a "
                "binding with its separate relation support. A reuse integer references an earlier "
                "condition declaration in this response; an override target indexes generated "
                "clauses. Existing views use actual u aliases for shared-condition reuse and "
                "override targets. Unresolved old conditions remain unresolved. "
                "When a source states a common prerequisite, declare it in the affected "
                "clause's conditions with a binding; do not save a separate content clause "
                "merely saying that a common prerequisite exists. The delivered role is actual "
                "stored structure; its wording cannot change it. "
            )
        else:
            instruction += "Use content clauses without relations. "
        if self.features.single_record_changes:
            instruction += (
                "creates is a list; records has at most one unique container per delivered r key. "
                "Never repeat a record or split its dependent changes across containers. "
                "Return both creates and records; use [] and {} respectively when empty. "
                "An existing change always names its r key "
                "in records, even when only one record was delivered; never return a bare edit. "
            )
        instruction += (
            "create is allowed in this request. "
            if allow_create
            else "create is unavailable in this request; with records=[] "
            "there is no permitted target, so return " + empty + ". "
        )
        # Complete examples, explicitly hypothetical. They supply no real aliases/facts.
        formation_units: list[dict[str, Any]] = (
            [
                {"text": "User reports reminders use a soft tone.", "role": "content"},
                {"text": "Only on weekdays.", "role": "condition"},
                {"text": "Only before 18:00.", "role": "condition"},
            ]
            if self.conditioned
            else [
                {
                    "text": "User reports reminders normally use a soft tone.",
                    "role": "content",
                },
                {"text": "User reports reminders occur only on weekdays.", "role": "content"},
                {"text": "User reports reminders occur only before 18:00.", "role": "content"},
            ]
        )
        for formed_unit in formation_units:
            formed_unit["evidence"] = ["e1"]
            if self.features.source_metadata:
                formed_unit["assertion"] = {"source_evidence": "e1", "kind": "reported"}
        create: dict[str, Any] = {"action": "create", "units": formation_units}
        if self.conditioned:
            create["relations"] = [
                {"source": source, "target": 0, "relation_type": "modifies", "evidence": ["e1"]}
                for source in (1, 2)
            ]
        if self.features.matter_organization:
            create["matter"] = "User's reminder sound"
        change: dict[str, Any] = {
            "text": "User reports reminders use a bright tone."
            if self.conditioned
            else "User reports reminders normally use a bright tone.",
            "evidence": ["e1"],
            "keep_support": ["h1"],
        }
        if self.features.source_metadata:
            change["assertion"] = {"source_evidence": "e1", "kind": "reported"}
        if self.arm in {"B0", "B2"}:
            correction: dict[str, Any] = {
                "action": "rewrite",
                "units": [{**change, "role": "content"}],
            }
            if self.conditioned:
                correction["units"][0].pop("keep_support")
                correction["units"][0]["from_unit"] = "u1"
            for index, condition in enumerate(formation_units[1:], start=2):
                retained: dict[str, Any] = {
                    "text": condition["text"],
                    "role": condition["role"],
                    "evidence": [],
                    "keep_support": [f"h{index}"],
                }
                if self.features.source_metadata:
                    retained["assertion"] = {"keep": f"h{index}"}
                    if self.arm == "B0":
                        retained.pop("text")
                        retained.pop("evidence")
                        retained.pop("keep_support")
                correction["units"].append(retained)
            if self.conditioned:
                correction["relations"] = [
                    {
                        "source": source,
                        "target": 0,
                        "relation_type": "modifies",
                        "evidence": [],
                        "keep_support": [f"h{source + 3}"],
                    }
                    for source in (1, 2)
                ]
        else:
            correction = {
                "action": "edit",
                "edits": [
                    {
                        **change,
                        "operation": "replace",
                        "target_unit": "u1",
                    }
                ],
            }

        def envelope(proposal: dict[str, Any], *, created: bool) -> dict[str, Any]:
            proposal = clause_proposal(proposal, conditioned=self.conditioned)
            if self.features.single_record_changes:
                return {"creates": [proposal] if created else [],
                        "records": {} if created else {"r1": proposal}}
            return {"proposals": [proposal if created else {**proposal, "target": "r1"}]}

        instruction += (
            "Examples below assume explicitly hypothetical CURRENT inputs; "
            "do not copy their facts or aliases into real memory. "
        )
        if self.features.temporal_scope and self.conditioned:
            instruction += (
                "Date input: user e1 explicitly reports a rule applying from April 1, 2025 "
                "inclusive to April 8 exclusive, with a framework-declared Source calendar. "
                "Date condition fragment in that content's conditions[]: "
                '{"text":"Only from April 1 inclusive to April 8 exclusive.",'
                '"evidence":["e1"],"assertion":{"source_evidence":"e1","kind":"reported",'
                '"applicability":{"effective_from":"2025-04-01",'
                '"effective_until":"2025-04-08"}},"binding":{"evidence":["e1"]}}. '
            )
        if allow_create:
            instruction += (
                "Formation input: records=[]; user e1 reports reminders use a soft tone "
                "only on weekdays and before 18:00. "
                "Complete formation envelope: "
                + json.dumps(envelope(create, created=True), separators=(",", ":"))
                + ". "
            )
        instruction += (
            "Empty input: e body only thanks or asks a question, "
            "no new durable fact and no justified change. Complete empty envelope: " + empty + ". "
        )
        correction_input = (
            "Correction input: CURRENT r1 contains u1='User reports reminders use a soft tone.', "
            "u2='Only on weekdays.', u3='Only before 18:00.'; h1/h2/h3 are their respective "
            "unit supports and old attributions; h4/h5 support modifies(u2->u1)/modifies(u3->u1). "
            if self.conditioned
            else "Correction input: CURRENT r1 contains u1='User reports reminders normally "
            "use a soft tone.', u2='User reports reminders occur only on weekdays.', "
            "u3='User reports reminders occur only before 18:00.'; h1/h2/h3 are their "
            "respective unit supports and old attributions. "
        )
        instruction += (
            correction_input
            + "CURRENT user e1 changes only the tone to bright. This example is unavailable "
            "when those aliases are absent. Complete correction envelope: "
            + json.dumps(envelope(correction, created=False), separators=(",", ":"))
            + "."
        )

        def example_unit(
            text: str,
            role: str = "content",
            support: str | None = None,
            *,
            new_evidence: bool = True,
            keep_attribution: bool = False,
        ) -> dict[str, Any]:
            result: dict[str, Any] = {
                "text": text,
                "role": role,
                "evidence": ["e1"] if new_evidence else [],
            }
            if support:
                result["keep_support"] = [support]
            if self.features.source_metadata:
                result["assertion"] = (
                    {"keep": support} if keep_attribution
                    else {"source_evidence": "e1", "kind": "reported"}
                )
                if self.arm == "B0" and keep_attribution:
                    result.pop("text")
                    result.pop("evidence")
                    result.pop("keep_support", None)
            return result

        def example_relation(
            source: int, target: int, kind: str = "modifies", support: str | None = None
        ) -> dict[str, Any]:
            result: dict[str, Any] = {
                "source": source,
                "target": target,
                "relation_type": kind,
                "evidence": [] if support else ["e1"],
            }
            if support:
                result["keep_support"] = [support]
            return result

        def example_edit(unit: dict[str, Any], operation: str, target: str) -> dict[str, Any]:
            return {
                **{key: value for key, value in unit.items() if key != "role"},
                "operation": operation,
                "target_unit": target,
            }

        add: dict[str, Any]
        shared: dict[str, Any]
        cancel: dict[str, Any]
        if self.arm in {"B0", "B1"}:
            retained_plain = [
                example_unit(
                    unit["text"], support=f"h{index}",
                    new_evidence=False, keep_attribution=True,
                )
                for index, unit in enumerate(formation_units, start=1)
            ]
            alternative = example_unit(
                "User reports Tuesday reminders use a bright tone instead of the general "
                "soft tone, under the same reminder schedule."
            )
            changed_cutoff = example_unit(
                "User reports reminders occur only before 17:00.", support="h3"
            )
            if self.arm == "B0":
                add = {"action": "rewrite", "units": [*retained_plain, alternative]}
                shared = {
                    "action": "rewrite",
                    "units": [
                        *retained_plain[:2], changed_cutoff,
                        example_unit(
                            alternative["text"], support="h4", new_evidence=False,
                            keep_attribution=True,
                        ),
                    ],
                }
                cancel = {
                    "action": "rewrite",
                    "units": [
                        example_unit(
                            formation_units[0]["text"], support="h1", keep_attribution=True
                        ),
                        retained_plain[1],
                        example_unit(
                            changed_cutoff["text"], support="h3", new_evidence=False,
                            keep_attribution=True,
                        ),
                    ],
                }
            else:
                add = {"action": "edit", "edits": [example_edit(alternative, "insert", "u3")]}
                shared = {
                    "action": "edit",
                    "edits": [example_edit(changed_cutoff, "replace", "u3")],
                }
                cancel = {
                    "action": "edit",
                    "edits": [{"operation": "delete", "target_unit": "u4", "evidence": ["e1"]}],
                }
            shared_state = (
                "CURRENT r1 has u1 as the general soft-tone rule, u2 as the reminder weekday "
                "limit, u3 as the reminder before-18:00 limit and u4 as the Tuesday bright-tone "
                "exception under that same schedule; h1/h2/h3/h4 are their respective supports. "
            )
        else:
            bright = example_unit("User reports reminders use a bright tone.")
            cutoff = example_unit("Only before 17:00.", "condition", "h3")
            if self.arm == "B2":
                retained_units = [
                    example_unit(
                        item["text"],
                        item["role"],
                        f"h{index}",
                        new_evidence=False,
                        keep_attribution=True,
                    )
                    for index, item in enumerate(formation_units, start=1)
                ]
                edges = [
                    (1, 0, "modifies"),
                    (2, 0, "modifies"),
                    (4, 3, "modifies"),
                    (3, 0, "overrides"),
                    (1, 3, "modifies"),
                    (2, 3, "modifies"),
                ]
                add = {
                    "action": "rewrite",
                    "units": [
                        *retained_units,
                        bright,
                        example_unit("Only on Tuesdays.", "condition"),
                    ],
                    "relations": [
                        example_relation(
                            source, target, kind, f"h{index + 4}" if index < 2 else None
                        )
                        for index, (source, target, kind) in enumerate(edges)
                    ],
                }
                full_units = [
                    *formation_units,
                    {"text": bright["text"], "role": "content"},
                    {"text": "Only on Tuesdays.", "role": "condition"},
                ]
                shared = {
                    "action": "rewrite",
                    "units": [
                        cutoff
                        if index == 3
                        else example_unit(
                            item["text"],
                            item["role"],
                            f"h{index}",
                            new_evidence=False,
                            keep_attribution=True,
                        )
                        for index, item in enumerate(full_units, start=1)
                    ],
                    "relations": [
                        example_relation(source, target, kind, f"h{index + 6}")
                        for index, (source, target, kind) in enumerate(edges)
                    ],
                }
                cancel = {
                    "action": "rewrite",
                    "units": [
                        example_unit(
                            formation_units[0]["text"], support="h1", keep_attribution=True
                        ),
                        retained_units[1],
                        example_unit(
                            "Only before 17:00.",
                            "condition",
                            "h3",
                            new_evidence=False,
                            keep_attribution=True,
                        ),
                    ],
                    "relations": [
                        example_relation(1, 0, support="h6"),
                        example_relation(2, 0, support="h7"),
                    ],
                }
            else:
                add_edit = example_edit(
                    bright,
                    "add_exception" if self.features.semantic_operations else "override",
                    "u1",
                )
                add_edit.update(condition="Only on Tuesdays.", shared_conditions=["u2", "u3"])
                add = {"action": "edit", "edits": [add_edit]}
                shared = {
                    "action": "edit",
                    "edits": [
                        example_edit(
                            cutoff,
                            "replace",
                            "u3",
                        )
                    ],
                }
                cancel = {
                    "action": "edit",
                    "edits": [
                        {
                            "operation": "remove_exception"
                            if self.features.semantic_operations
                            else "retract",
                            "target_unit": "u4",
                            "evidence": ["e1"],
                        }
                    ],
                }
                if not self.features.semantic_operations:
                    cancel["edits"].append(
                        {"operation": "retract", "target_unit": "u5", "evidence": ["e1"]}
                    )
            shared_state = (
                "CURRENT r1 has u1 general soft-tone content, u2 weekdays, u3 before 18:00, "
                "u4 Tuesday bright-tone content and u5 Tuesdays, with respective supports "
                "h1/h2/h3/h4/h5. Its relations are modifies(u2->u1), modifies(u3->u1), "
                "modifies(u5->u4), overrides(u4->u1), modifies(u2->u4), modifies(u3->u4), "
                "with respective supports h6/h7/h8/h9/h10/h11. "
            )
        instruction += (
            " Independent lifecycle examples start from the original soft-tone state in "
            "Correction input, independently of its bright-tone correction. "
            "Exception input: CURRENT r1 has that original state and supports; CURRENT user e1 "
            "reports Tuesday reminders use a bright tone instead, under the same weekday and "
            "before-18:00 limits. Complete exception envelope: "
            + json.dumps(envelope(add, created=False), separators=(",", ":"))
            + ". Shared-condition input: "
            + shared_state
            + "CURRENT user e1 changes only the common cutoff to 17:00 for both general and "
            "Tuesday reminders. Complete shared-condition envelope: "
            + json.dumps(envelope(shared, created=False), separators=(",", ":"))
            + ". Exception-withdrawal input: CURRENT r1 is the preceding shared-condition "
            "state with its 17:00 cutoff and the same alias/support layout; CURRENT user e1 "
            "withdraws only the Tuesday bright-tone exception. "
            "Complete exception-withdrawal envelope: "
            + json.dumps(envelope(cancel, created=False), separators=(",", ":"))
            + "."
        )
        return instruction

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

    @staticmethod
    def target_support_ranges(selected_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pure, ordered range inventory from only the supplied record versions.

        No body is read or delivered here. The caller chooses the exact ranges
        it can send; a legacy record without structured supports adds no range.
        """
        ranges: dict[tuple[str, int, int, int], dict[str, Any]] = {}
        for row in selected_records:
            if not row.get("ok") or not isinstance(row.get("value"), dict):
                raise FunctionalRejection("EDIT_RECORD_UNAVAILABLE")
            state = row["value"].get("edit_state") or {}
            for item in [*state.get("units", []), *state.get("relations", [])]:
                for ref in item["evidence_refs"]:
                    part = {
                        key: ref[key] for key in ("source_ref", "source_revision", "start", "end")
                    }
                    key = (part["source_ref"], part["source_revision"], part["start"], part["end"])
                    ranges.setdefault(key, part)
        return list(ranges.values())

    def prepare(
        self,
        actual_source_refs: list[str],
        query: str,
        *,
        limit: int = 6,
        source_ranges: list[dict[str, Any]] | None = None,
        selected_records: list[dict[str, Any]] | None = None,
        redelivered_ranges: list[dict[str, Any]] | None = None,
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
            if self.features.source_metadata or redelivered_ranges is not None:
                sources[-1]["occurred_at"] = source.get("occurred_at")
                if "calendar_context" in source:
                    sources[-1]["calendar_context"] = source["calendar_context"]
        redelivered = []
        if redelivered_ranges is not None:
            available = self.target_support_ranges(selected)
            for part in redelivered_ranges:
                if part not in available:
                    raise FunctionalRejection("EDIT_SUPPORT_RANGE_UNAVAILABLE")
                source = self.service.source(part["source_ref"])
                if source is None or source["source_revision"] != part["source_revision"]:
                    raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")
                evidence = issue_evidence(
                    self.service, part["source_ref"], part["start"], part["end"]
                )
                redelivered.append(
                    {
                        **evidence,
                        "role": source["role"],
                        "observed_at": source["observed_at"],
                        "occurred_at": source.get("occurred_at"),
                        **({"calendar_context": source["calendar_context"]}
                           if "calendar_context" in source else {}),
                        "text": body_text(source)[part["start"] : part["end"]],
                        "body_delivered": True,
                        "semantic_support": "unchecked",
                    }
                )
        records = []
        historical_evidence: dict[str, dict[str, Any]] = {}
        delivered_ids = {source["evidence_id"] for source in [*sources, *redelivered]}
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
            if self.features.temporal_scope:
                record["version_time"] = version.get("committed_at")
            records.append(record)
        delivery = {
            "method_version": self.method_version,
            "sources": sources,
            "records": records,
            "historical_evidence": list(historical_evidence.values()),
        }
        if redelivered_ranges is not None:
            delivery["redelivered_sources"] = redelivered
        if self.features.source_metadata:
            self._source_attributes(delivery)
        return delivery

    def observation_delivery(
        self, delivery: dict[str, Any], profiles: list[ObservationProfile]
    ) -> dict[str, Any]:
        """Opt-in public field candidates over exact original JSON member ranges.

        The original Tool Source remains readable. Deterministic candidates are
        neither semantic records nor independent evidence; the editor still
        decides which assertions to form. Unmatched sources retain extraction.
        """
        self._require_v2()
        projected = copy.deepcopy(delivery)
        sources, changes, extraction_ranges = [], [], []
        for row in delivery["sources"]:
            actual = self.service.source(row["source_ref"])
            if actual is None:
                raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")
            profile = next((p for p in profiles if actual["role"] == "tool"
                            and actual["origin"] in p.origins), None)
            text = body_text(actual)
            projection = (maintenance_projection(actual, profile, text)
                          if profile is not None and row["start"] == 0 and row["end"] == len(text)
                          else {"observations": []})
            observations = projection["observations"]
            if not observations:
                sources.append(copy.deepcopy(row))
                extraction_ranges.append({k: row[k] for k in ("source_ref", "start", "end")})
                continue
            spans = list(dict.fromkeys(
                [span for observation in observations for span in observation["ranges"]]
                + projection["unstructured_ranges"]
            ))
            fragments = self.prepare(
                [row["source_ref"]], "", selected_records=[],
                source_ranges=[{"source_ref": row["source_ref"], "start": start, "end": end}
                               for start, end in spans],
            )["sources"]
            sources.extend(fragments)
            by_span = {(fragment["start"], fragment["end"]): fragment for fragment in fragments}
            extraction_ranges.extend(
                {k: by_span[span][k] for k in ("source_ref", "start", "end")}
                for span in projection["unstructured_ranges"]
            )
            for observation in observations:
                changes.append({
                    "basis": "actual_source_literal",
                    "subject": (observation["object_ref"]["application"] + " "
                                + observation["object_ref"]["external_id"]),
                    "statement": observation["field"] + "=" + json.dumps(
                        observation["literal_value"], ensure_ascii=False, separators=(",", ":")
                    ),
                    "field": observation["field"],
                    "field_paths": observation["field_paths"],
                    "literal_value": observation["literal_value"],
                    "observed_at": observation["observed_at"],
                    "resource_version": observation["resource_version"],
                    "version_domain": observation["version_domain"],
                    "current_verified": False,
                    "evidence": [by_span[span]["evidence_id"] for span in observation["ranges"]],
                    "time": None, "scope": None,
                })
        projected.update(sources=sources, result_maintenance={
            "mode": "literal_observations_v1", "literal_changes": changes,
            "extraction_source_ranges": extraction_ranges,
        })
        return projected

    def _source_attributes(self, delivery: dict[str, Any]) -> None:
        refs = [
            source["source_ref"]
            for source in [*delivery.get("sources", []), *delivery.get("redelivered_sources", [])]
        ]
        for record in delivery.get("records", []):
            state = record.get("edit_state") or {}
            for item in [*state.get("units", []), *state.get("relations", [])]:
                refs.extend(ref["source_ref"] for ref in item["evidence_refs"])
                assertion = item.get("assertion")
                if assertion and "source_ref" in assertion:
                    refs.append(assertion["source_ref"])
        attributes = []
        for ref in dict.fromkeys(refs):
            actual = self.service.source(ref)
            if actual is None:
                raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")
            attributes.append(
                {
                    "source_ref": ref,
                    "source_revision": actual["source_revision"],
                    "role": actual["role"],
                    "observed_at": actual["observed_at"],
                    "occurred_at": actual.get("occurred_at"),
                    **({"origin": origin} if (origin := tool_source_origin(actual)) else {}),
                    **({"calendar_context": actual["calendar_context"]}
                       if "calendar_context" in actual else {}),
                }
            )
        delivery["source_attributes"] = attributes

    def preview_writer_view(
        self, delivery: dict[str, Any], *, allow_create: bool = True
    ) -> dict[str, Any]:
        """Pure budget projection; this result grants no read or mutation authority."""
        self._require_v2()
        packet, _ = writer_projection(
            delivery,
            self.interface_version,
            self.arm,
            allow_create=allow_create,
            features=self.features.settings(),
        )
        return {"packet": packet}

    def edit_messages(
        self, packet: dict[str, Any], date: str, *, allow_create: bool,
        schema: dict[str, Any] | None = None,
        change_candidates: list[dict[str, Any]] | None = None,
        prior_context: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        response_schema = (
            schema if schema is not None else self.envelope_schema(allow_create=allow_create)
        )
        if self.features.bound_references:
            response_schema = compact_prompt_schema(response_schema)
        empty_instruction = (
            "An empty maintenance envelope means no maintenance, not a successful update."
            if "records" in response_schema.get("properties", {})
            else "An empty proposals list means no maintenance, not a successful update."
        )
        payload: dict[str, Any] = {
            "observed_date": date,
            "delivery": packet,
            "response_schema": response_schema,
        }
        if prior_context:
            payload["prior_context"] = self.context_projection(prior_context)
            empty_instruction += (
                " prior_context is earlier speech for resolving references, not a new event "
                "or an instruction to save those old statements again."
            )
        if change_candidates is not None:
            payload["change_candidates"] = change_candidates
            empty_instruction += (
                " change_candidates are temporary locating hints; decide what to persist "
                "from the original delivered sources and actual old state. A candidate can "
                "misstate its source even when its source ID matches; it supplies no extra "
                "evidence. Preserve the source's actual subject, attribution and modal strength."
            )
        return [
            {
                "role": "system",
                "content": self.instructions(allow_create=allow_create)
                + " Group distinct topics into separate records. Preserve dates and roles. "
                "In every arm, form one independently stated clause per unit. In plain memory "
                "keep its qualifications in that clause; in conditioned memory explicitly link "
                "actual applicability limits, not ordinary quantities, attributes or observed "
                "states. Keep each independently mutable value self-contained with its subject "
                "and still-applicable qualifications. Do not pack independent matters into a "
                "single long unit or create duplicate records for the same matter. "
                "Return the supplied envelope. At most one proposal per existing target in "
                "this request. "
                + REVISION_MEANING_INSTRUCTIONS
                + "A removal needs evidence of that cancellation. Redelivering a source that "
                "affirmed an old rule does not support a new retraction of that rule. "
                "Compare every explicit current Source value with actual delivered state, "
                "including values the Source says to retain. If they differ, use a supported "
                "same-scope change. An uncommitted prior request does not establish stored state. "
                + empty_instruction
                + (" Candidates marked actual_source_literal are program-projected fields of "
                   "the actual Tool source, not LLM semantic formation. Their observation time "
                   "is not a guarantee of live state. Preserve separate component outcomes."
                   if any(change.get("basis") == "actual_source_literal"
                          for change in change_candidates or []) else ""),
            },
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ]

    @staticmethod
    def context_projection(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"kind": "prior_context", **{key: source.get(key) for key in (
                "text", "role", "observed_at", "occurred_at")},
             **({"calendar_context": source["calendar_context"]}
                if "calendar_context" in source else {})}
            for source in sources
        ]

    def change_request(self, delivery: dict[str, Any], date: str) -> dict[str, Any]:
        """One temporary extraction task over current source bodies, with no Store writes.

        The caller owns transport, capacity, first-attempt accounting and target
        retrieval. Candidates are hints for the same editor, never saved facts.
        Explicit prior context can resolve references; only current fragments
        are selectable evidence for a candidate change.
        """
        self._require_v2()
        projection = delivery.get("result_maintenance")
        if projection is not None:
            extraction = {(row["source_ref"], row["start"], row["end"])
                          for row in projection["extraction_source_ranges"]}
            delivery = {**delivery, "sources": [row for row in delivery["sources"]
                        if (row["source_ref"], row["start"], row["end"]) in extraction]}
        packet, mapping = writer_projection(
            {**delivery, "records": [], "redelivered_sources": []},
            self.interface_version,
            self.arm,
            allow_create=True,
            features=self.features.settings(),
        )
        references = list(mapping["evidence"])
        evidence: dict[str, Any] = {"type": "string"}
        if references:
            evidence["enum"] = references
        changes: dict[str, Any] = {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subject": {"type": "string", "minLength": 1},
                    "statement": {"type": "string", "minLength": 1},
                    "evidence": {"type": "array", "items": evidence, "minItems": 1},
                    "time": {"type": ["string", "null"]},
                    "scope": {"type": ["string", "null"]},
                },
                "required": ["subject", "statement", "evidence", "time", "scope"],
            },
        }
        if not references:
            changes["maxItems"] = 0
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"changes": changes},
            "required": ["changes"],
        }
        return {
            "schema": schema,
            "mapping": mapping,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract brief candidate propositions and change cues from current sources "
                        "for memory maintenance. Preserve the subject, who asserts it, report or "
                        "inference status, modal strength, qualifications and explicit time/scope. "
                        "Considering a course remains considering; wishing to reduce work hours "
                        "remains a wish; a plan does not imply a completed change. An assistant's "
                        "suggested income remains an assistant suggestion, not a user's report. "
                        "Stay close to the source wording when summarizing would strengthen it. "
                        "Select the actual supporting e fragments. Use "
                        "null when time/scope is unspecified. Include independently stated "
                        "new facts and changes; omit social acknowledgments and bare queries. "
                        "Keep each candidate self-contained with its explicit values and "
                        "qualifications, including statements of what to retain. Such statements "
                        "do not establish that stored state already matches them. "
                        "These candidates locate affected old matters for the existing editor; "
                        "they are not memory, verified facts or instructions to execute. The "
                        "editor can reject them or recognize a restatement. Return changes=[] "
                        "when no candidate is warranted."
                        + (" prior_context is earlier speech for resolving references only. "
                           "It is not a current event; do not extract its facts again."
                           if delivery.get("prior_context") else "")
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"observed_date": date, "delivery": packet, "response_schema": schema,
                         **({"prior_context": self.context_projection(delivery["prior_context"])}
                            if delivery.get("prior_context") else {})},
                        ensure_ascii=False,
                    ),
                },
            ],
        }

    @staticmethod
    def decode_changes(envelope: dict[str, Any], request: dict[str, Any]) -> list[dict[str, Any]]:
        """Resolve candidate source selections without granting mutation authority."""
        Draft202012Validator(request["schema"]).validate(envelope)
        return [
            {
                **copy.deepcopy(change),
                "evidence": [
                    request["mapping"]["evidence"][alias]["evidence_id"]
                    for alias in change["evidence"]
                ],
            }
            for change in envelope["changes"]
        ]

    @staticmethod
    def changes_query(changes: list[dict[str, Any]], original_query: str) -> str:
        """One ordinary locating query for the batch; empty extraction does not gate editing."""
        return "\n".join(
            " ".join(str(change[key]) for key in ("subject", "statement", "time", "scope")
                     if change[key] is not None)
            for change in changes
        ) or original_query

    @staticmethod
    def writer_changes(
        changes: list[dict[str, Any]], mapping: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Use the editor's actual e aliases, even when its delivery order differs."""
        aliases = {
            row["evidence_id"]: alias for alias, row in mapping["evidence"].items()
            if row.get("delivery_kind", "current") == "current"
        }
        return [
            {**copy.deepcopy(change), "evidence": [aliases[ref] for ref in change["evidence"]]}
            for change in changes
        ]

    def preview_writer_request(
        self, delivery: dict[str, Any], *, allow_create: bool = True,
        changes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._require_v2()
        packet, draft = writer_projection(
            delivery,
            self.interface_version,
            self.arm,
            allow_create=allow_create,
            features=self.features.settings(),
        )
        return {
            "packet": packet,
            "schema": self.envelope_schema(allow_create=allow_create, mapping=draft),
            "mapping": None,
            **({"change_candidates": self.writer_changes(changes, draft)}
               if changes is not None else {}),
        }

    def writer_request(
        self,
        delivery: dict[str, Any],
        *,
        request_id: str | None = None,
        allow_create: bool = True,
    ) -> dict[str, Any]:
        view = self.writer_view(delivery, request_id=request_id, allow_create=allow_create)
        return {
            **view,
            "schema": self.envelope_schema(allow_create=allow_create, mapping=view["mapping"]),
        }

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
        if self.features.source_metadata:
            self._source_attributes(checked)
        for source in [*checked.get("sources", []), *checked.get("redelivered_sources", [])]:
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
            if self.features.source_metadata or "redelivered_sources" in checked:
                actual_source = self.service.source(source["source_ref"])
                if actual_source is None or source.get("role") != actual_source["role"]:
                    raise FunctionalRejection("EDIT_ACTUAL_SOURCE_ROLE_REQUIRED")
                if "redelivered_sources" in checked:
                    source["observed_at"] = actual_source["observed_at"]
                source["occurred_at"] = actual_source.get("occurred_at")
                if "calendar_context" in actual_source:
                    source["calendar_context"] = actual_source["calendar_context"]
                else:
                    source.pop("calendar_context", None)
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
            checked,
            self.interface_version,
            self.arm,
            allow_create=allow_create,
            features=self.features.settings(),
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
            or mapping.get("edit_features", {})
            != (self.features.settings() if self.features.enabled else {})
        ):
            raise FunctionalRejection("EDIT_MAPPING_OWNERSHIP_MISMATCH")
        return mapping

    def envelope_proposals(
        self, envelope: dict[str, Any], mapping: dict[str, Any] | str
    ) -> list[dict[str, Any]]:
        bound = self.load_mapping(mapping if isinstance(mapping, str) else mapping["mapping_id"])
        if not isinstance(mapping, str) and mapping != bound:
            raise FunctionalRejection("EDIT_MAPPING_CHANGED")
        if not self.features.enabled:
            if (
                not isinstance(envelope, dict)
                or set(envelope) != {"proposals"}
                or not isinstance(envelope.get("proposals"), list)
            ):
                raise ValueError("Writer did not return a proposals list")
            return [copy.deepcopy(proposal) for proposal in envelope["proposals"]]
        errors = list(
            Draft202012Validator(
                self.envelope_schema(
                    allow_create=bound["allow_create"], mapping=bound, for_generation=False
                )
            ).iter_errors(envelope)
        )
        if errors:
            raise FunctionalRejection("EDIT_PUBLIC_ENVELOPE_INVALID: " + errors[0].message)
        if not self.features.single_record_changes:
            proposals = copy.deepcopy(envelope["proposals"])
            if self.features.enabled:
                targets = [p["target"] for p in proposals if p.get("target")]
                if len(targets) != len(set(targets)):
                    raise FunctionalRejection("EDIT_DUPLICATE_RECORD_CONTAINER")
            return proposals  # type: ignore[no-any-return]
        selected_records = envelope.get("records", {})
        return [
            *copy.deepcopy(envelope.get("creates", [])),
            *(
                {**copy.deepcopy(selected_records[target]), "target": target}
                for target in bound["records"]
                if target in selected_records
            ),
        ]

    def decode_envelope(
        self, envelope: dict[str, Any], mapping: dict[str, Any] | str
    ) -> list[dict[str, Any]]:
        return [
            self.decode_proposal(proposal, mapping)
            for proposal in self.envelope_proposals(envelope, mapping)
        ]

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
        schema = self.proposal_schema(
            allow_create=bound["allow_create"], mapping=bound, for_generation=False
        )
        if self.features.enabled and "oneOf" not in schema:
            raise FunctionalRejection("EDIT_PUBLIC_ACTION_UNAVAILABLE")
        errors = list(Draft202012Validator(schema).iter_errors(proposal))
        if errors:
            raise FunctionalRejection("EDIT_PUBLIC_PROPOSAL_INVALID: " + errors[0].message)
        proposal = (
            compile_semantic_operations(proposal, bound) if self.features.enabled else proposal
        )
        target = proposal.get("target")
        record = bound["records"].get(target) if target else None
        if target and record is None:
            raise FunctionalRejection("EDIT_SHORT_REFERENCE_UNAVAILABLE")
        decoded: dict[str, Any] = {"action": proposal["action"]}
        metadata: dict[str, Any] = {}
        if self.features.matter_organization and proposal["action"] == "create":
            if not proposal["matter"].strip():
                raise FunctionalRejection("EDIT_MATTER_DESCRIPTION_REQUIRED")
            metadata["matter_description"] = proposal["matter"]
        if self.features.source_metadata:
            metadata["unit_assertions"] = []
        if self.conditioned and self.features.enabled:
            metadata["unit_exception_flags"] = []
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
            retained_unit = (
                item.get("from_unit") if proposal["action"] == "rewrite"
                else item.get("target_unit") if item.get("operation") == "replace" else None
            )
            if (
                self.features.source_metadata
                and "keep_support" not in item
                and (kept_alias := item.get("assertion", {}).get("keep"))
            ):
                support = bound["support"].get(kept_alias)
                if support is not None and support.get("unit") and (
                    support["unit"] == retained_unit
                    or (proposal["action"] == "rewrite" and not retained_unit
                        and support["record"] == target)
                ):
                    item["keep_support"] = [kept_alias]
            handles, kept = [], []
            for alias in item.get("evidence", []):
                evidence = bound["evidence"].get(alias)
                if evidence is None:
                    raise FunctionalRejection("EDIT_SHORT_EVIDENCE_UNAVAILABLE")
                # Visibility can be revoked since the delivery; never bypass forget.
                resolve_fragment(self.service, evidence["evidence_id"])
                handles.append(evidence["evidence_id"])
                if self.features.enabled:
                    metadata.setdefault("revision_evidence", []).append(evidence["evidence_id"])
            for alias in dict.fromkeys(item.get("keep_support", [])):
                support = bound["support"].get(alias)
                if support is None or support["record"] != target:
                    raise FunctionalRejection("EDIT_SHORT_SUPPORT_UNAVAILABLE")
                kept.append(support)
                handles.extend(ref["evidence_id"] for ref in support["evidence_refs"])
            if not handles:
                raise FunctionalRejection("EDIT_EVIDENCE_REQUIRED")
            return list(dict.fromkeys(handles)), kept

        def assertion(item: dict[str, Any]) -> dict[str, Any]:
            selected = item["assertion"]
            if "source" in selected:
                alias = selected["source"]
                if alias not in item.get("evidence", []):
                    raise FunctionalRejection("EDIT_ASSERTION_SOURCE_NOT_SELECTED")
                evidence = bound["evidence"][alias]
                actual = self.service.source(evidence["source_ref"])
                if actual is None:
                    raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE")
                result = {
                    "kind": selected["kind"],
                    "source_ref": evidence["source_ref"],
                    "source_revision": evidence["source_revision"],
                    "role": actual["role"],
                    "occurred_at": actual.get("occurred_at"),
                    "observed_at": actual["observed_at"],
                    **({"calendar_context": actual["calendar_context"]}
                       if "calendar_context" in actual else {}),
                }
                if self.features.temporal_scope and "applicability" in selected:
                    validate_applicability(selected["applicability"],
                                           calendar_context=actual.get("calendar_context"))
                    result["applicability"] = copy.deepcopy(selected["applicability"])
                if self.features.temporal_scope and "evidence_links" in selected:
                    links = {}
                    for stance, aliases in selected["evidence_links"].items():
                        linked = []
                        for evidence_alias in dict.fromkeys(aliases):
                            if evidence_alias not in item.get("evidence", []):
                                raise FunctionalRejection("EDIT_EVIDENCE_LINK_NOT_SELECTED")
                            original = bound["evidence"][evidence_alias]
                            linked.append({key: original.get(key) for key in (
                                "evidence_id", "source_ref", "source_revision", "start", "end",
                                "role", "occurred_at", "observed_at",
                            )})
                            if "calendar_context" in original:
                                linked[-1]["calendar_context"] = original["calendar_context"]
                        links[stance] = linked
                    result["evidence_links"] = links
                return result
            alias = selected["keep"]
            if alias not in item.get("keep_support", []):
                raise FunctionalRejection("EDIT_ASSERTION_SUPPORT_NOT_KEPT")
            support = bound["support"][alias]
            if "unit" not in support:
                raise FunctionalRejection("EDIT_ASSERTION_REQUIRES_UNIT_SUPPORT")
            unit = alias_unit(support["unit"])
            if unit["text"] != item["text"] or ("role" in item and unit["role"] != item["role"]):
                raise FunctionalRejection("EDIT_CHANGED_ASSERTION_REQUIRES_NEW_EVIDENCE")
            if item.get("target_unit") and item["target_unit"] != support["unit"]:
                raise FunctionalRejection("EDIT_ASSERTION_UNIT_BINDING_INVALID")
            return copy.deepcopy(
                unit.get(
                    "assertion",
                    {"kind": "legacy_unspecified", "role": "unknown", "occurred_at": None},
                )
            )

        origins: list[set[str]] = []
        explicit_origins: set[str] = set()
        for item in proposal.get("units", []):
            if proposal["action"] == "rewrite" and "text" not in item:
                support = bound["support"].get(item["assertion"]["keep"])
                retained_unit = item.get("from_unit")
                if self.arm == "B0" and retained_unit is None and support is not None:
                    retained_unit = support.get("unit")
                if (support is None or support["record"] != target
                        or not retained_unit or support.get("unit") != retained_unit):
                    raise FunctionalRejection("EDIT_ASSERTION_UNIT_BINDING_INVALID")
                prior_unit = alias_unit(retained_unit)
                if self.arm == "B0" and prior_unit["role"] != "content":
                    raise FunctionalRejection("EDIT_ASSERTION_UNIT_BINDING_INVALID")
                item["text"] = prior_unit["text"]
            handles, kept = supports(item)
            origin = {support["unit"] for support in kept if "unit" in support}
            if len(origin) != len(kept) or len(origin) > 1:
                raise FunctionalRejection("EDIT_UNIT_SUPPORT_BINDING_INVALID")
            if "from_unit" in item:
                alias = item["from_unit"]
                prior_unit = alias_unit(alias)
                if (
                    proposal["action"] != "rewrite"
                    or prior_unit["role"] != item.get("role", "content")
                    or (origin and origin != {alias})
                    or alias in explicit_origins
                ):
                    raise FunctionalRejection("EDIT_UNIT_SUPPORT_BINDING_INVALID")
                explicit_origins.add(alias)
                origin.add(alias)
            if not item.get("evidence") and not any(
                alias_unit(alias)["text"] == item["text"]
                and alias_unit(alias)["role"] == item.get("role", "content")
                for alias in origin
            ):
                raise FunctionalRejection("EDIT_CHANGED_CLAIM_REQUIRES_NEW_EVIDENCE")
            origins.append(origin)
            if self.conditioned and self.features.enabled:
                metadata["unit_exception_flags"].append(
                    any(alias_unit(alias).get("local_exception") for alias in origin)
                )
            decoded.setdefault("units", []).append(
                {"text": item["text"], "role": item.get("role", "content"), "evidence": handles}
            )
            if self.features.source_metadata:
                metadata["unit_assertions"].append(assertion(item))
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
                key: value
                for key, value in item.items()
                if key not in {"evidence", "keep_support", "assertion"}
            }
            edit["evidence"] = handles
            if unit:
                edit["target_unit"] = unit["unit_id"]
            for field in ("shared_conditions", "attach_to"):
                if field in edit:
                    edit[field] = [alias_unit(alias)["unit_id"] for alias in edit[field]]
            decoded.setdefault("edits", []).append(edit)
            if self.features.source_metadata:
                metadata["unit_assertions"].append(assertion(item) if "text" in item else None)
        if proposal["action"] == "rewrite" and not proposal["units"]:
            witnesses = proposal.get("withdrawal_evidence", [])
            if not witnesses or proposal.get("relations"):
                raise FunctionalRejection("EDIT_WITHDRAWAL_EVIDENCE_REQUIRED")
            decoded["units"] = []
            decoded["withdrawal_evidence"] = supports({"evidence": witnesses})[0]
        elif proposal.get("withdrawal_evidence"):
            raise FunctionalRejection("EDIT_REWRITE_HAS_WITHDRAWAL_EVIDENCE")
        if proposal.get("revision_evidence"):
            supports({"evidence": proposal["revision_evidence"]})
        if self.features.enabled:
            metadata["revision_evidence"] = list(
                dict.fromkeys(metadata.get("revision_evidence", []))
            )
            decoded["_edit_metadata"] = metadata
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
        metadata = proposal.get("_edit_metadata")
        internal = {
            k: v for k, v in proposal.items() if k not in {"withdrawal_evidence", "_edit_metadata"}
        }
        parsed = EditProposal.model_validate(internal)
        requested = {"method": self.method_version, "arm": self.method_name, "proposal": proposal}
        if self.features.enabled:
            requested["edit_features"] = self.features.settings()
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
                old["edit_state"],
                parsed.edits,
                self.service,
                conditioned=self.conditioned,
                assertions=metadata.get("unit_assertions") if isinstance(metadata, dict) else None,
                mark_exceptions=self.conditioned and self.features.enabled,
            )
        if parsed.action != "no_change" and state is not None and self.features.enabled:
            if not isinstance(metadata, dict):
                raise FunctionalRejection("EDIT_FEATURE_METADATA_REQUIRED")
            if (
                parsed.action == "create"
                and self.features.matter_organization
                and not metadata.get("matter_description")
            ):
                raise FunctionalRejection("EDIT_MATTER_DESCRIPTION_REQUIRED")
            decorate_state(
                state,
                metadata,
                old=(old or {}).get("edit_state"),
                edits=parsed.edits if parsed.action == "edit" else None,
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
            if self.features.enabled and metadata is not None and metadata.get("revision_evidence"):
                cancellation_refs.extend(
                    ref["source_ref"]
                    for ref in source_evidence(self.service, metadata.get("revision_evidence", []))
                )
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
            "method_arm": self.method_name,
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
        if self.features.enabled and metadata is not None and "revision_evidence" in metadata:
            raw["revision_evidence"] = metadata["revision_evidence"]
        return self.service.commit(session, proposal_id, raw)

    @staticmethod
    def render(
        version: dict[str, Any], *, query_time: str | None = None,
        query_calendar_context: str | None = None,
    ) -> str:
        return (
            render_state(
                version["edit_state"], query_time=query_time,
                version_time=version.get("committed_at") if query_time is not None else None,
                query_calendar_context=query_calendar_context,
            ) if version.get("edit_state") else version["content"]
        )

    @staticmethod
    def revision_view(
        version: dict[str, Any], *, query_time: str | None = None,
        query_calendar_context: str | None = None,
    ) -> dict[str, Any]:
        """Read actual current/history state; calendar context is explicitly caller-declared.

        The declaration permits nominal ordering only; it neither supplies a
        timezone nor changes missing coordinates in already stored assertions.
        """
        if not version.get("edit_state"):
            return {"content": version["content"], "semantic_support": "unchecked",
                    "query_time": query_time, "query_calendar_context": query_calendar_context,
                    "version_time": version.get("committed_at")}
        return render_revision_view(
            version["edit_state"], query_time=query_time, version_time=version.get("committed_at"),
            query_calendar_context=query_calendar_context,
        )
