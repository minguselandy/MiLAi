"""Selected D11 string-rule deferral over the unchanged public acceptance contract.

The current HTTP contrast selected this one opt-in candidate. This module does not
authorize a request, identify an internal decoder backend, or repair any value.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from v0220_wire_contract import (
    LISTS,
    MAPS,
    SINGLES,
    WireContract,
    WireContractError,
    encoded,
    fingerprint,
    pointer,
)
from v0220_wire_contract import REVISION as BASE_REVISION
from v0220_wire_contract import compile_contract as compile_unique_contract

REVISION = "STRING_RULES_RUNTIME_V1"
SELECTED_CONDITION = "D11"


@dataclass(frozen=True)
class StringWireContract(WireContract):
    selected_condition: str = SELECTED_CONDITION

    @property
    def notice(self) -> str:
        return (
            "Transport compatibility contract (not business facts or action authorization): "
            "this opt-in grammar defers uniqueItems and, only at reviewed explicit string "
            "schema nodes, the exact pattern \\S and integer minLength 1 to full validation. "
            "Its permitted generation set can be wider than the unchanged authoritative "
            "contract; decoder language equivalence and a particular backend cause are not "
            "claimed. Every raw response is checked against the complete public schema "
            "before any action. Preserve exact authorized string characters, including "
            "whitespace and escapes after JSON decoding. No value is filled, trimmed, "
            "normalized, sorted, deduplicated or repaired. All other constraints, complete "
            "sources, goals, identity, permissions and version rules remain in force. "
            "Authoritative public response schema:\n" + self.canonical_json
        )

    def manifest(self) -> dict:
        return {
            "revision": REVISION,
            "base_revision": BASE_REVISION,
            "selected_condition": self.selected_condition,
            "canonical_sha256": fingerprint(self.canonical),
            "wire_sha256": fingerprint(self.wire),
            "deferred_checks": json.loads(self.deferred_json),
            "decoder_is_superset_not_equivalent": True,
            "full_validation_required_before_dispatch": True,
            "automatic_value_repair": False,
            "backend_root_cause": "NOT_IDENTIFIED_BY_THIS_COMPILER",
            "compatibility_notice_sha256": fingerprint(self.notice),
            "compatibility_notice_utf8_bytes": len(self.notice.encode("utf-8")),
            "prompt_change_scope": "ONE_COMMON_NOTICE_APPEND_WITH_COMPLETE_AUTHORITATIVE_SCHEMA",
        }

    def prepare(self, body: dict) -> dict:
        if fingerprint(body["response_format"]["json_schema"]["schema"]) != fingerprint(
            self.canonical
        ):
            raise WireContractError("CANONICAL_REQUEST_DRIFT")
        wire = copy.deepcopy(body)
        wire["response_format"]["json_schema"]["schema"] = self.wire
        if wire["messages"] and wire["messages"][0]["role"] == "system":
            content = wire["messages"][0].get("content")
            if not isinstance(content, str):
                raise WireContractError("TEXT_SYSTEM_CONTRACT_REQUIRED")
            wire["messages"][0]["content"] = content + "\n\n" + self.notice
        else:
            wire["messages"].insert(0, {"role": "system", "content": self.notice})
        return wire

    def prompt_diff(self, body: dict) -> dict:
        """Exact deterministic prompt accounting; online token counts remain mandatory."""
        prepared = self.prepare(body)
        previous = compile_unique_contract(self.canonical).prepare(body)
        original_system = (
            body["messages"][0]["content"]
            if body["messages"] and body["messages"][0]["role"] == "system"
            else ""
        )
        actual_system = prepared["messages"][0]["content"]
        old_system = previous["messages"][0]["content"]
        return {
            "original_messages_sha256": fingerprint(body["messages"]),
            "prepared_messages_sha256": fingerprint(prepared["messages"]),
            "previous_unique_only_messages_sha256": fingerprint(previous["messages"]),
            "append_text": (
                "\n\n"
                if original_system or (body["messages"] and body["messages"][0]["role"] == "system")
                else ""
            )
            + self.notice,
            "new_instruction_utf8_bytes": len(actual_system.encode())
            - len(original_system.encode()),
            "delta_vs_unique_only_utf8_bytes": len(actual_system.encode())
            - len(old_system.encode()),
            "source_messages_unchanged": True,
            "complete_public_schema_still_visible": True,
            "online_token_count": "NOT_MEASURED_BY_COMPILER",
            "single_variable_decoder_causal_claim": False,
        }


def compile_contract(
    schema: dict, selected_condition: str = SELECTED_CONDITION
) -> StringWireContract:
    """Only D11 is selected; no blanket regex/length deletion or inferred type walk."""
    if selected_condition != SELECTED_CONDITION:
        raise WireContractError("UNSELECTED_STRING_COMPATIBILITY_CONDITION")
    # The existing checked positive vocabulary and uniqueItems transformation are
    # retained. References, negative operators and unknown extensions fail here.
    original = compile_unique_contract(schema)
    deferred = [
        {**row, "original_value": copy.deepcopy(row["value"]), "rule_kind": "uniqueItems"}
        for row in original.manifest()["deferred_checks"]
    ]

    def visit(node: object, path: list) -> object:
        if isinstance(node, bool):
            return node
        result = {}
        for key, value in node.items():
            selected = node.get("type") == "string" and (
                (key == "pattern" and value == r"\S")
                or (key == "minLength" and type(value) is int and value == 1)
            )
            if selected:
                deferred.append(
                    {
                        "path": pointer([*path, key]),
                        "value": value,
                        "original_value": value,
                        "rule_kind": key,
                        "enforced_by": "full_schema_before_dispatch",
                    }
                )
            elif key in MAPS:
                result[key] = {
                    name: visit(child, [*path, key, name]) for name, child in value.items()
                }
            elif key in LISTS:
                result[key] = [visit(child, [*path, key, i]) for i, child in enumerate(value)]
            elif key in SINGLES:
                result[key] = visit(value, [*path, key])
            else:
                result[key] = copy.deepcopy(value)
        return result

    wire = visit(original.wire, [])
    Draft202012Validator.check_schema(wire)
    return StringWireContract(original.canonical_json, encoded(wire), encoded(deferred))
