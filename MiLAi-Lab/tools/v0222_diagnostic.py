"""Frozen P1 string contrasts; diagnostic outputs never become business actions."""

from __future__ import annotations

import copy
import json

from v0213_provider import payload
from v0220_action_contract import unique_object
from v0220_wire_contract import WireContractError, compile_contract, encoded, fingerprint, pointer

CONDITIONS = ("D00", "D10", "D01", "D11")
FIXTURES = {
    "T1": "Contact synthetic.user@example.invalid; copy this complete multiword text.",
    "T2": '中文 café Ω — say "hello"; path C:\\lab\\probe\nline two\tfin',
    "T3": "  \t[alpha, beta!]  \n",
}
SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string", "minLength": 1, "pattern": r"\S"}},
    "required": ["text"],
    "additionalProperties": False,
}
SYSTEM = (
    "This is a synthetic exact-copy diagnostic, not a business task. Return exactly one JSON "
    "object whose text field equals the provided target string after JSON decoding. Preserve "
    "every character, including Unicode, whitespace, punctuation and escape-decoded characters. "
    "The transport schema may express only a subset of the authoritative contract below. "
    "All outputs are evaluated unchanged against that complete contract and the target; "
    "no actions are executed and no output is repaired. Authoritative response schema:\n"
    + encoded(SCHEMA)
)


def specs() -> list[dict]:
    rows = []
    for repeat in (1, 2):
        for fixture in FIXTURES:
            for condition in CONDITIONS if repeat == 1 else reversed(CONDITIONS):
                rows.append(
                    {
                        "id": f"p1-{len(rows) + 1:02d}",
                        "stage": "P1",
                        "pass": repeat,
                        "fixture": fixture,
                        "condition": condition,
                    }
                )
    return rows


def request(fixture: str, condition: str) -> tuple[dict, dict]:
    if fixture not in FIXTURES or condition not in CONDITIONS:
        raise ValueError("UNPLANNED_DIAGNOSTIC_CONDITION")
    canonical = payload(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": encoded({"target": FIXTURES[fixture]})},
        ],
        copy.deepcopy(SCHEMA),
    )
    wire = copy.deepcopy(canonical)
    rules = wire["response_format"]["json_schema"]["schema"]["properties"]["text"]
    if condition in ("D10", "D11"):
        rules.pop("pattern")
    if condition in ("D01", "D11"):
        rules.pop("minLength")
    return canonical, wire


def differences(expected: object, actual: object, path: tuple = ()) -> list[dict]:
    """JSON value comparison: no string normalization or order-sensitive object comparison."""
    if isinstance(expected, bool) != isinstance(actual, bool) or (
        type(expected) is not type(actual)
        and not (type(expected) in (int, float) and type(actual) in (int, float))
    ):
        return [
            {
                "path": pointer(list(path)),
                "kind": "TYPE",
                "expected_type": type(expected).__name__,
                "actual_type": type(actual).__name__,
            }
        ]
    if isinstance(expected, dict):
        rows = []
        for name in sorted(set(expected) | set(actual)):
            if name not in expected or name not in actual:
                rows.append({"path": pointer([*path, name]), "kind": "MISSING_OR_EXTRA"})
            else:
                rows.extend(differences(expected[name], actual[name], (*path, name)))
        return rows
    if isinstance(expected, list):
        rows = (
            []
            if len(expected) == len(actual)
            else [{"path": pointer(list(path)), "kind": "LENGTH"}]
        )
        for i, (left, right) in enumerate(zip(expected, actual, strict=False)):
            rows.extend(differences(left, right, (*path, i)))
        return rows
    if expected != actual:
        row = {
            "path": pointer(list(path)),
            "kind": "VALUE",
            "expected_sha256": fingerprint(expected),
            "actual_sha256": fingerprint(actual),
        }
        if isinstance(expected, str):
            row.update(expected_characters=len(expected), actual_characters=len(actual))
        return [row]
    return []


def observe(raw: str, fixture: str) -> dict:
    result = {
        "status": "OBSERVED",
        "strict_json": False,
        "full_schema": False,
        "exact_fidelity": False,
        "business_dispatches": 0,
        "automatic_value_repair": False,
    }
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
        encoded(value)
    except (ValueError, TypeError, RecursionError):
        result["content_class"] = "INVALID_STRICT_JSON"
        return result
    result["strict_json"] = True
    try:
        encoded(value).encode("utf-8")
    except UnicodeEncodeError:
        result["content_class"] = "INVALID_UNICODE_CONTENT"
        result["schema_evaluation"] = "NOT_EVALUATED_INVALID_UNICODE"
        return result
    try:
        compile_contract(SCHEMA).validate_output(raw)
    except WireContractError as exc:
        result.update(content_class="FULL_SCHEMA_REJECTED", issues=exc.issues)
        return result
    result["full_schema"] = True
    result["differences"] = differences({"text": FIXTURES[fixture]}, value)
    result["exact_fidelity"] = not result["differences"]
    result["content_class"] = "EXACT_COPY" if result["exact_fidelity"] else "CONTENT_DIFFERENCE"
    return result
