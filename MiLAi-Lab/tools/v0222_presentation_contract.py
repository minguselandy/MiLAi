"""One reversible intent-message presentation; no compiler, actor, or authority.

The full public contract and all original history remain unchanged. This function
does not choose the next action, fill a version, or validate business execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math

from v0220_action_contract import unique_object
from v0220_wire_contract import encoded, fingerprint

REVISION = "INTENT_BOUNDARY_RUNTIME_V1"
PRESENTATION_KEYS = {
    "profile",
    "contract",
    "origin",
    "observations",
    "inherited_note",
    "authorized_intent",
}
RESOURCES = {"task", "policy", "current", "records", "history", "pending"}
BUDGET_KEYS = {
    "remaining_generation_opportunities",
    "final_delivery_reservation",
    "last_completed_public_observation",
}


class PresentationContractError(ValueError):
    pass


def _json_tree(value) -> None:
    """Reject non-JSON Python containers, nonfinite numbers and invalid UTF-8."""
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise PresentationContractError("STRING_JSON_KEYS_REQUIRED")
        for key, item in value.items():
            key.encode("utf-8")
            _json_tree(item)
    elif type(value) is list:
        for item in value:
            _json_tree(item)
    elif type(value) is str:
        value.encode("utf-8")
    elif value is None or type(value) in {bool, int}:
        pass
    elif type(value) is not float or not math.isfinite(value):
        raise PresentationContractError("FINITE_JSON_VALUES_REQUIRED")


def _serialize(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _parse(raw: str):
    value = json.loads(raw, object_pairs_hook=unique_object)
    _json_tree(value)
    return value


def _intent_kind(intent: dict) -> str:
    if type(intent) is not dict:
        raise PresentationContractError("ORIGINAL_INTENT_OBJECT_REQUIRED")
    if set(intent) == {"authorized_action"}:
        action = intent["authorized_action"]
        if type(action) is not dict or set(action) != {"action", "arguments"}:
            raise PresentationContractError("COMPLETE_SINGLE_AUTHORIZED_ACTION_REQUIRED")
        args = action["arguments"]
        if type(args) is not dict:
            raise PresentationContractError("NAMED_ACTION_ARGUMENTS_REQUIRED")
        if action["action"] == "put_record":
            if (
                set(args) != {"object_id", "expected_version", "data"}
                or type(args["object_id"]) is not str
                or type(args["expected_version"]) is not int
                or args["expected_version"] < 0
                or type(args["data"]) is not dict
            ):
                raise PresentationContractError("COMPLETE_UNREPAIRED_PUT_RECORD_REQUIRED")
        elif action["action"] == "finish":
            if set(args) != {"message"} or type(args["message"]) is not str:
                raise PresentationContractError("COMPLETE_ORIGINAL_FINISH_REQUIRED")
        else:
            raise PresentationContractError("UNREVIEWED_SINGLE_ACTION_KIND")
        return "SINGLE_ACTION"
    if set(intent) == {"instruction", "ordered_writes"}:
        writes = intent["ordered_writes"]
        if type(intent["instruction"]) is not str or type(writes) is not list or not writes:
            raise PresentationContractError("COMPLETE_ORIGINAL_CHAIN_REQUIRED")
        for write in writes:
            if (
                type(write) is not dict
                or set(write) != {"object_id", "data"}
                or type(write["object_id"]) is not str
                or type(write["data"]) is not dict
            ):
                raise PresentationContractError(
                    "ORIGINAL_ORDERED_WRITES_WITHOUT_FILLED_CAS_REQUIRED"
                )
        return "ORDERED_CHAIN"
    raise PresentationContractError("UNREVIEWED_INTENT_ENVELOPE")


def _original(canonical: dict) -> tuple[dict, str]:
    try:
        _json_tree(canonical)
        if type(canonical) is not dict:
            raise PresentationContractError("CANONICAL_REQUEST_OBJECT_REQUIRED")
        messages = canonical["messages"]
        schema = canonical["response_format"]["json_schema"]["schema"]
        if type(schema) is not dict:
            raise PresentationContractError("COMPLETE_SCHEMA_OBJECT_REQUIRED")
        if type(messages) is not list or len(messages) < 2:
            raise PresentationContractError("ORIGINAL_SYSTEM_AND_PRESENTATION_REQUIRED")
        parsed = {}
        intent_positions = []
        for index, message in enumerate(messages):
            if (
                type(message) is not dict
                or set(message) != {"role", "content"}
                or type(message["content"]) is not str
                or message["role"] not in {"system", "user", "assistant"}
                or (message["role"] == "system") != (index == 0)
            ):
                raise PresentationContractError("ORIGINAL_TEXT_MESSAGE_ENVELOPE_REQUIRED")
            if index:
                parsed[index] = _parse(message["content"])
                if (
                    message["role"] == "user"
                    and type(parsed[index]) is dict
                    and "authorized_intent" in parsed[index]
                ):
                    intent_positions.append(index)
        if intent_positions != [1] or messages[1]["role"] != "user":
            raise PresentationContractError("UNIQUE_INITIAL_PROTOCOL_INTENT_REQUIRED")
        presentation = parsed[1]
        if (
            set(presentation) != PRESENTATION_KEYS
            or list(presentation)[-1] != "authorized_intent"
            or presentation["profile"] != "INTENT_ORACLE"
            or presentation["origin"] != "HARNESS_PUBLIC_PREFETCH"
            or presentation["inherited_note"] is not None
            or type(presentation["contract"]) is not dict
        ):
            raise PresentationContractError("COMPLETE_ORIGINAL_ORACLE_PRESENTATION_REQUIRED")
        observations = presentation["observations"]
        if (
            type(observations) is not list
            or len(observations) != 6
            or any(type(o) is not dict or "content" not in o for o in observations)
            or {o["resource"] for o in observations} != RESOURCES
        ):
            raise PresentationContractError("ALL_SIX_PUBLIC_RESOURCES_REQUIRED")
        if _serialize(presentation) != messages[1]["content"]:
            raise PresentationContractError("ORIGINAL_PRESENTATION_SERIALIZATION_REQUIRED")
        kind = _intent_kind(presentation["authorized_intent"])
        if kind == "SINGLE_ACTION":
            if len(messages) != 2:
                raise PresentationContractError("SINGLE_ACTION_CALIBRATION_HAS_NO_SESSION_HISTORY")
        else:
            if (
                len(messages) < 3
                or len(messages) % 2 != 1
                or messages[-1]["role"] != "user"
                or type(parsed[len(messages) - 1]) is not dict
                or set(parsed[len(messages) - 1]) != BUDGET_KEYS
            ):
                raise PresentationContractError("ORIGINAL_SESSION_BUDGET_AND_HISTORY_REQUIRED")
            for index in range(2, len(messages) - 1):
                if index % 2 == 0:
                    if messages[index]["role"] != "assistant":
                        raise PresentationContractError("ORIGINAL_ASSISTANT_TOOL_ORDER_REQUIRED")
                elif (
                    messages[index]["role"] != "user"
                    or type(parsed[index]) is not dict
                    or set(parsed[index]) != {"tool_result"}
                ):
                    raise PresentationContractError("ORIGINAL_ASSISTANT_TOOL_ORDER_REQUIRED")
        return presentation, kind
    except PresentationContractError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError):
        raise PresentationContractError("INVALID_FINITE_ORIGINAL_REQUEST") from None


def present(canonical: dict) -> dict:
    """Move the original whole intent once; leave the caller's Session history alone."""
    presentation, _ = _original(canonical)
    result = copy.deepcopy(canonical)
    intent = presentation.pop("authorized_intent")
    result["messages"][1]["content"] = _serialize(presentation)
    moved = copy.deepcopy(result["messages"][1])  # Keep persisted content/role key order.
    moved["content"] = _serialize({"authorized_intent": intent})
    result["messages"].append(moved)
    return result


def _metrics(value: str) -> dict:
    raw = value.encode("utf-8")
    return {
        "characters": len(value),
        "utf8_bytes": len(raw),
        "sha256_utf8": hashlib.sha256(raw).hexdigest(),
    }


def _splice(before: str, after: str) -> dict:
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    suffix = 0
    while (
        suffix < min(len(before) - start, len(after) - start)
        and before[-1 - suffix] == after[-1 - suffix]
    ):
        suffix += 1
    return {
        "start_character": start,
        "start_utf8_byte": len(before[:start].encode()),
        "removed": before[start : len(before) - suffix],
        "added": after[start : len(after) - suffix],
        "unchanged_suffix_characters": suffix,
    }


def audit_presentation(original: dict, presented: dict) -> dict:
    """Check exact ordered bytes and inverse, not merely sorted object fingerprints."""
    wanted = present(original)
    try:
        _json_tree(presented)
        if _serialize(presented) != _serialize(wanted):
            raise PresentationContractError("EXACT_PRESENTATION_TRANSFORM_REQUIRED")
        restored = copy.deepcopy(presented)
        remainder = _parse(restored["messages"][1]["content"])
        moved = _parse(restored["messages"].pop()["content"])
        remainder["authorized_intent"] = moved["authorized_intent"]
        restored["messages"][1]["content"] = _serialize(remainder)
        if _serialize(restored) != _serialize(original):
            raise PresentationContractError("EXACT_INVERSE_REQUEST_BYTES_REQUIRED")
        presentation, kind = _original(original)
        return {
            "status": "PRESENTATION_CONTRACT_PASS",
            "revision": REVISION,
            "intent_kind": kind,
            "original_request_sha256": fingerprint(original),
            "presented_request_sha256": fingerprint(presented),
            # Transport has always used encoded(sort_keys=True). The source
            # message strings retain their own original ordering/serialization;
            # request-envelope metrics must survive that existing save/read policy.
            # Exact transform and inverse checks above remain order-sensitive.
            "request_byte_encoding": "UNCHANGED_TRANSPORT_ENCODED_SORT_KEYS_TRUE",
            "original_request": _metrics(encoded(original)),
            "presented_request": _metrics(encoded(presented)),
            "intent_sha256": fingerprint(presentation["authorized_intent"]),
            "source_presentation_sha256": fingerprint(
                {k: v for k, v in presentation.items() if k != "authorized_intent"}
            ),
            "checks": {
                "exact_inverse_bytes": True,
                "complete_sources_and_order_unchanged": True,
                "schema_order_and_parameters_unchanged": True,
                "original_assistant_tool_and_budget_bytes_unchanged": True,
                "one_whole_original_intent_only": True,
                "no_action_selection_or_cas_fill": True,
                "no_added_instruction_or_value_repair": True,
            },
            "reversible_diff": {
                "replaced_user_index": 1,
                "content_splice": _splice(
                    original["messages"][1]["content"], presented["messages"][1]["content"]
                ),
                "appended_message": copy.deepcopy(presented["messages"][-1]),
            },
            "online_token_count": "UNMEASURED_REQUIRES_ACTUAL_HTTP_PREFLIGHT",
            "business_acceptance": "UNCHANGED_SEPARATE_FULL_SCHEMA_CAS_INTENT_AND_EFFECT_GATES",
        }
    except PresentationContractError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError):
        raise PresentationContractError("INVALID_FINITE_PRESENTED_REQUEST") from None
