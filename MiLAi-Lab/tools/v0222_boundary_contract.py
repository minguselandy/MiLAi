"""One exact intent-boundary contrast and its diagnostic-only acceptance contract."""

from __future__ import annotations

import copy
import hashlib
import json
import re

from jsonschema import Draft202012Validator, FormatChecker

from v0220_action_contract import unique_object
from v0220_wire_contract import encoded, fingerprint, pointer
from v0222_diagnostic import differences

CONDITIONS = ("B0", "B1")
SOURCE_EPISODES = ("p3-01", "p3-03", "p3-05", "p3-07")
ROOT_ORDER = (
    "A-1db36ca3de1602c36e98",
    "A-1816ef11f35c3921798c",
    "A-e5324eaf97ba5a9b16dd",
    "A-4d36e6825968f3ce3862",
)
PRESENTATION_KEYS = {
    "profile",
    "contract",
    "origin",
    "observations",
    "inherited_note",
    "authorized_intent",
}
RESOURCES = {"task", "policy", "current", "records", "history", "pending"}
REVISION = "RESIDUAL_INTENT_BOUNDARY_V1"


class BoundaryContractError(ValueError):
    pass


def serialize(value) -> str:
    """Original presentation serialization: insertion order, default spacing, UTF-8 text."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def strict_json(raw: str):
    value = json.loads(raw, object_pairs_hook=unique_object)
    encoded(value)
    return value


def _presentation(canonical: dict) -> dict:
    try:
        serialize(canonical).encode("utf-8")
        messages = canonical["messages"]
        if not isinstance(messages, list) or len(messages) < 2:
            raise BoundaryContractError("ORIGINAL_SYSTEM_AND_USER_REQUIRED")
        if messages[0]["role"] != "system" or messages[-1]["role"] != "user":
            raise BoundaryContractError("ORIGINAL_MESSAGE_ROLES_REQUIRED")
        actual_intents = []
        for index, message in enumerate(messages):
            if set(message) != {"role", "content"} or not isinstance(message["content"], str):
                raise BoundaryContractError("EXACT_TEXT_MESSAGE_ENVELOPE_REQUIRED")
            if index and message["role"] != "user":
                raise BoundaryContractError("NO_PRIOR_RESPONSE_OR_EXTRA_SYSTEM_ALLOWED")
            if message["role"] == "user":
                # Only protocol-level keys identify intent; nested source data and words do not.
                value = strict_json(message["content"])
                if isinstance(value, dict) and "authorized_intent" in value:
                    actual_intents.append(index)
        if actual_intents != [len(messages) - 1]:
            raise BoundaryContractError("EXACTLY_ONE_TOP_LEVEL_INTENT_REQUIRED")
        value = strict_json(messages[-1]["content"])
        if set(value) != PRESENTATION_KEYS or list(value)[-1] != "authorized_intent":
            raise BoundaryContractError("ORIGINAL_LAST_FIELD_PRESENTATION_REQUIRED")
        if (
            value["profile"] != "INTENT_ORACLE"
            or value["origin"] != "HARNESS_PUBLIC_PREFETCH"
            or value["inherited_note"] is not None
            or not isinstance(value["contract"], dict)
        ):
            raise BoundaryContractError("ORIGINAL_ORACLE_PUBLIC_PRESENTATION_REQUIRED")
        observations = value["observations"]
        if (
            not isinstance(observations, list)
            or len(observations) != 6
            or {o["resource"] for o in observations} != RESOURCES
            or any("content" not in o for o in observations)
        ):
            raise BoundaryContractError("COMPLETE_SIX_PUBLIC_RESOURCES_REQUIRED")
        intent = value["authorized_intent"]
        if not isinstance(intent, dict) or set(intent) != {"authorized_action"}:
            raise BoundaryContractError("SINGLE_COMPLETE_AUTHORIZED_ACTION_REQUIRED")
        action = intent["authorized_action"]
        if (
            not isinstance(action, dict)
            or set(action) != {"action", "arguments"}
            or action["action"] != "put_record"
            or not isinstance(action["arguments"], dict)
            or set(action["arguments"]) != {"object_id", "expected_version", "data"}
            or not isinstance(action["arguments"]["object_id"], str)
            or type(action["arguments"]["expected_version"]) is not int
            or action["arguments"]["expected_version"] < 0
            or not isinstance(action["arguments"]["data"], dict)
        ):
            raise BoundaryContractError("COMPLETE_PUT_RECORD_INTENT_REQUIRED")
        schema = canonical["response_format"]["json_schema"]["schema"]
        Draft202012Validator.check_schema(schema)
        if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(action):
            raise BoundaryContractError("ORIGINAL_INTENT_NOT_IN_COMPLETE_SCHEMA")
        return value
    except BoundaryContractError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError):
        raise BoundaryContractError("INVALID_FINITE_ORIGINAL_ENVELOPE") from None


def transform(canonical: dict, condition: str) -> dict:
    if condition not in CONDITIONS:
        raise BoundaryContractError("UNPLANNED_BOUNDARY_CONDITION")
    presentation = _presentation(canonical)
    result = copy.deepcopy(canonical)
    if condition == "B0":
        return result
    if serialize(presentation) != canonical["messages"][-1]["content"]:
        raise BoundaryContractError("ORIGINAL_PRESENTATION_SERIALIZATION_DRIFT")
    intent = presentation.pop("authorized_intent")
    result["messages"][-1]["content"] = serialize(presentation)
    # Keep the existing envelope order, including content-before-role in saved
    # encoded(sort_keys=True) references, without weakening schema order checks.
    moved_message = copy.deepcopy(result["messages"][-1])
    moved_message["content"] = serialize({"authorized_intent": intent})
    result["messages"].append(moved_message)
    return result


def _metrics(text: str) -> dict:
    return {
        "characters": len(text),
        "utf8_bytes": len(text.encode()),
        "sha256_utf8": hashlib.sha256(text.encode()).hexdigest(),
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
    end_before, end_after = len(before) - suffix, len(after) - suffix
    return {
        "start_character": start,
        "removed": before[start:end_before],
        "added": after[start:end_after],
        "unchanged_suffix_characters": suffix,
        "start_utf8_byte": len(before[:start].encode()),
    }


def audit_transform(original: dict, candidate: dict, condition: str) -> dict:
    wanted = transform(original, condition)
    # Preserve order too: object equality or sort-key hashes alone miss schema-property reorder.
    if serialize(candidate) != serialize(wanted):
        raise BoundaryContractError("EXACT_FROZEN_BOUNDARY_TRANSFORM_REQUIRED")
    original_presentation = _presentation(original)
    restored = copy.deepcopy(candidate)
    if condition == "B1":
        remainder = strict_json(restored["messages"][-2]["content"])
        new_intent = strict_json(restored["messages"][-1]["content"])
        if "authorized_intent" in remainder or set(new_intent) != {"authorized_intent"}:
            raise BoundaryContractError("SINGLE_MOVED_INTENT_REQUIRED")
        remainder["authorized_intent"] = new_intent["authorized_intent"]
        restored["messages"].pop()
        restored["messages"][-1]["content"] = serialize(remainder)
    if serialize(restored) != serialize(original):
        raise BoundaryContractError("EXACT_INVERSE_RECONSTRUCTION_REQUIRED")
    last_index = len(original["messages"]) - 1
    return {
        "status": "BOUNDARY_TRANSFORM_PASS",
        "revision": REVISION,
        "condition": condition,
        "original_request_sha256": fingerprint(original),
        "candidate_request_sha256": fingerprint(candidate),
        "original_messages": _metrics(serialize(original["messages"])),
        "candidate_messages": _metrics(serialize(candidate["messages"])),
        "intent_sha256": fingerprint(original_presentation["authorized_intent"]),
        "source_presentation_sha256": fingerprint(
            {k: v for k, v in original_presentation.items() if k != "authorized_intent"}
        ),
        "checks": {
            "exact_inverse_bytes": True,
            "source_values_and_order_unchanged": True,
            "schema_and_parameters_unchanged": True,
            "one_intent_not_duplicated": True,
            "no_added_instruction_text": True,
            "no_value_repair": True,
        },
        "reversible_diff": {
            "replaced_user_index": last_index,
            "content_splice": _splice(
                original["messages"][-1]["content"], candidate["messages"][last_index]["content"]
            ),
            "appended_message": candidate["messages"][-1] if condition == "B1" else None,
        },
        "causal_scope": "Boundary/template markers, distances and JSON envelope change together; "
        "not a decomposition of those subfactors or an external-task estimate",
        "online_token_count": "UNMEASURED_REQUIRES_ACTUAL_HTTP_PREFLIGHT",
    }


def observe(expected: dict, schema: dict, raw: str) -> dict:
    Draft202012Validator.check_schema(schema)
    serialize(expected).encode("utf-8")
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(expected):
        raise BoundaryContractError("EXPECTED_REFERENCE_NOT_IN_FULL_SCHEMA")
    result = {
        "status": "OBSERVED",
        "strict_json": False,
        "full_schema": False,
        "exact_fidelity": False,
        "differences": [],
        "business_dispatches": 0,
        "automatic_value_repair": False,
    }
    try:
        value = strict_json(raw)
    except (ValueError, TypeError, RecursionError):
        result["classification"] = "INVALID_STRICT_JSON"
        return result
    result["strict_json"] = True
    try:
        serialize(value).encode("utf-8")
    except UnicodeEncodeError:
        result["classification"] = "INVALID_UNICODE_CONTENT"
        return result
    # Legal JSON still has useful missing/type/value differences when the public
    # schema rejects it. Recording them never promotes it to exact fidelity.
    result["differences"] = differences(expected, value)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    result["full_schema"] = not errors
    if errors:
        result["issues"] = [
            {
                "path": pointer(list(e.absolute_path)),
                "schema_path": pointer(list(e.absolute_schema_path)),
                "rule": e.validator,
            }
            for e in errors
        ]
    if (
        isinstance(value, dict)
        and value.get("action") == "put_record"
        and isinstance(value.get("arguments"), dict)
        and "expected_version" in value["arguments"]
        and type(value["arguments"]["expected_version"]) is not int
    ):
        # JSON Schema integer permits 0.0, but the unchanged ActionAdapter CAS
        # protocol requires a real int. Do not broaden that protocol or coerce it.
        issue = {
            "path": "/arguments/expected_version",
            "kind": "TYPE",
            "expected_type": "int",
            "actual_type": type(value["arguments"]["expected_version"]).__name__,
        }
        result["protocol_issues"] = [{**issue, "rule": "CAS_INTEGER_REPRESENTATION"}]
        if not any(
            d["path"] == issue["path"] and d["kind"] == "TYPE" for d in result["differences"]
        ):
            result["differences"].append(issue)
        result["classification"] = "CAS_TYPE_REJECTED"
        return result
    if errors:
        result["classification"] = "FULL_SCHEMA_REJECTED"
        return result
    result["exact_fidelity"] = not result["differences"]
    result["classification"] = "EXACT_COPY" if result["exact_fidelity"] else "CONTENT_DIFFERENCE"
    return result


def decision(observations: list[dict], final: bool = False) -> dict:
    if (
        type(final) is not bool
        or not isinstance(observations, list)
        or len(observations) != (16 if final else 8)
    ):
        raise BoundaryContractError("COMPLETE_FROZEN_BOUNDARY_MATRIX_REQUIRED")
    expected = [
        (root, cold, condition)
        for cold in ((1, 2) if final else (1,))
        for root in ROOT_ORDER
        for condition in (CONDITIONS if cold == 1 else tuple(reversed(CONDITIONS)))
    ]
    ids, values = set(), {}
    for row, position in zip(observations, expected, strict=True):
        if (
            not isinstance(row, dict)
            or type(row.get("cold")) is not int
            or type(row.get("exact_fidelity")) is not bool
            or not isinstance(row.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", row["id"])
            or row["id"] in ids
            or (row.get("root"), row.get("cold"), row.get("condition")) != position
        ):
            raise BoundaryContractError("BOUNDARY_OBSERVATION_ID_ORDER_OR_TYPE_DRIFT")
        ids.add(row["id"])
        values[position] = row["exact_fidelity"]
    first_signal = any(
        not values[(root, 1, "B0")] and values[(root, 1, "B1")] for root in ROOT_ORDER
    )
    if not final:
        return {
            "status": "REPEAT_REQUIRED" if first_signal else "NO_DIFFERENTIAL_SIGNAL",
            "repeat_required": first_signal,
        }
    all_b1 = all(values[(root, cold, "B1")] for root in ROOT_ORDER for cold in (1, 2))
    all_b0 = all(values[(root, cold, "B0")] for root in ROOT_ORDER for cold in (1, 2))
    repeated_improvement = any(
        all(not values[(root, cold, "B0")] and values[(root, cold, "B1")] for cold in (1, 2))
        for root in ROOT_ORDER
    )
    qualified = first_signal and all_b1 and repeated_improvement and not all_b0
    return {
        "status": "INTENT_BOUNDARY_SIGNAL" if qualified else "NO_QUALIFIED_PRESENTATION_CANDIDATE",
        "selected_condition": "B1" if qualified else None,
    }
