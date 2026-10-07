"""Source-grounded factual append control on the common maintenance pipeline."""

from __future__ import annotations

from typing import Any

from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_memory import EditMemory


class AppendMemory(EditMemory):
    """Plain factual records; corrections are new reports, never silent rewrites."""

    def __init__(self, service: MemoryService, *, features: EditFeatures) -> None:
        super().__init__(service, "B0", interface_version="I2", features=features)
        self.method_version = "milai_fact_append_v1"

    @property
    def method_name(self) -> str:
        return "Append-only"

    def envelope_schema(
        self, *, allow_create: bool = True, mapping: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        schema = super().envelope_schema(allow_create=allow_create, mapping=mapping)
        fields = schema["properties"]
        if "creates" in fields:
            fields["records"] = {
                "type": "object", "properties": {}, "additionalProperties": False,
            }
        else:
            items = fields["proposals"]["items"]
            choices = items.get("oneOf", []) if isinstance(items, dict) else []
            creates = [v for v in choices if v["properties"]["action"]["const"] == "create"]
            fields["proposals"]["items"] = {"oneOf": creates} if creates else False
        return schema

    def edit_messages(
        self, packet: dict[str, Any], date: str, *, allow_create: bool,
        schema: dict[str, Any] | None = None,
        change_candidates: list[dict[str, Any]] | None = None,
        prior_context: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        messages = super().edit_messages(
            packet, date, allow_create=allow_create, schema=schema,
            change_candidates=change_candidates, prior_context=prior_context,
        )
        messages[0]["content"] = (
            "Maintain factual append-only memory using the supplied plain-record schema. "
            "Append useful independently stated facts from the current original sources. "
            "Existing records are earlier reports for detecting redundant restatements and "
            "understanding corrections; never rewrite, retract or delete them. A correction, "
            "cancellation or changed plan is a new dated assertion even for an existing matter. "
            "State what changed and its explicit applicable time/scope, so the common Reader "
            "can reconcile earlier and later reports. Do not imply that a plan was completed. "
            "Preserve the speaker, subject, qualifications, uncertainty and exceptions in each "
            "plain clause. Bind assertions to actual delivered sources; report time is not an "
            "invented effective time. A user request does not prove a business effect. "
            "Group related facts in a matter, one independently stated clause per unit. "
            "Do not append duplicate restatements or copy the raw dialogue as a substitute "
            "for useful factual memory. change_candidates are temporary hints, not evidence; "
            "empty candidates still allow original-source facts. prior_context is earlier "
            "speech for resolving references, not a new event to append again. Return the "
            "supplied JSON envelope with only creates (or create proposals); records stays {}. "
            "An empty envelope means no new factual record, not proof of successful maintenance."
        )
        return messages

    def apply(
        self, session: str, proposal_id: str, proposal: dict[str, Any]
    ) -> dict[str, Any]:
        if proposal.get("action") != "create":
            raise FunctionalRejection("APPEND_ONLY_CREATE_REQUIRED")
        return super().apply(session, proposal_id, proposal)
