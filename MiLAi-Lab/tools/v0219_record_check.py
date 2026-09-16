"""Offline full-record checking with explicit, content-bound semantic adjudication.

No task IDs, gold vocabulary or model-policy routing live here. Public schemas
describe business deliverables; private schemas contain independently reviewed
postconditions. Neither private schemas nor these diagnostics are Host tools.
"""

from __future__ import annotations

import hashlib
import json
import math

from jsonschema import Draft202012Validator, FormatChecker


def content_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode()
    ).hexdigest()


def finite(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(finite(v) for v in value.values())
    if isinstance(value, list):
        return all(finite(v) for v in value)
    return True


def pointer(value: object, path: str) -> object:
    if path == "":
        return value
    if not path.startswith("/"):
        raise ValueError("JSON_POINTER_REQUIRED")
    for part in path[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def schema_errors(value: object, schema: dict, layer: str) -> list[dict]:
    Draft202012Validator.check_schema(schema)
    errors = Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)
    # Do not echo private expected values or untrusted instance text into error logs.
    return [
        {"layer": layer, "path": list(error.absolute_path), "check": error.validator}
        for error in errors
    ]


def evaluate(state: dict, contract: dict, reviews: list[dict] | None = None) -> dict:
    """Never turn an unreviewed free-text claim into a full PASS.

    Caller must independently verify the frozen contract and the actual SQLite
    snapshot provenance. A supplied dict alone cannot prove execution.
    """
    if not finite(state):
        return {"status": "FAIL", "errors": [{"layer": "WIRE", "check": "NONFINITE"}],
                "semantic_pending": [], "execution_proven_by_checker": False}
    errors = []
    expected_objects = contract["objects"]
    if set(state.get("objects", [])) != set(expected_objects):
        errors.append({"layer": "IDENTITY", "check": "OBJECT_UNIVERSE"})
    records = state.get("records", {})
    if not isinstance(records, dict) or set(records) != set(expected_objects):
        errors.append({"layer": "EXECUTED_RECORDS", "check": "COMPLETE_OBJECT_SET"})
    if not isinstance(records, dict):
        records = {}
    for target in expected_objects:
        row = records.get(target)
        for layer, schema in (
            ("PUBLIC_CONTRACT", contract["public_schemas"][target]),
            ("POSTCONDITION", contract["postconditions"][target]),
        ):
            errors.extend(
                {"object": target, **error} for error in schema_errors(row, schema, layer)
            )
        if isinstance(row, dict) and row.get("object_id") != target:
            errors.append({"object": target, "layer": "IDENTITY", "check": "RECORD_OBJECT"})
    for group in contract.get("distinct_values", []):
        try:
            values = [content_hash(pointer(state, path)) for path in group]
            if len(set(values)) != len(values):
                errors.append({"layer": "CROSS_RECORD", "check": "DISTINCT_VALUES"})
        except (KeyError, IndexError, TypeError, ValueError):
            errors.append({"layer": "CROSS_RECORD", "check": "MISSING_VALUE"})
    errors.extend(schema_errors(state.get("pending"), contract["pending_schema"], "PENDING"))
    pending = []
    reviews = reviews or []
    paths = list(contract.get("semantic_paths", []))
    # Pending questions are real work, but never automatically deemed appropriate.
    if isinstance(state.get("pending"), dict):
        paths += ["/pending/" + key.replace("~", "~0").replace("/", "~1")
                  for key in state["pending"]]
    for path in paths:
        try:
            value = pointer(state, path)
            sha = content_hash(value)
        except (KeyError, IndexError, TypeError, ValueError):
            continue  # missing required values already fail the complete schema
        matching = [r for r in reviews if r.get("path") == path and r.get("content_sha256") == sha
                    and r.get("contract_sha256") == content_hash(contract)
                    and r.get("state_sha256") == content_hash(state)]
        if len(matching) != 1:
            pending.append({"path": path, "content_sha256": sha, "reason": "REVIEW_REQUIRED"})
            continue
        review = matching[0]
        if (review.get("verdict") not in {"CORRECT", "INCORRECT", "UNKNOWN", "DISPUTED"}
                or not review.get("source_locations") or not review.get("reviewer")
                or not isinstance(review.get("reason"), str) or not review["reason"].strip()):
            pending.append({"path": path, "content_sha256": sha, "reason": "INVALID_REVIEW"})
        elif review["verdict"] == "INCORRECT":
            errors.append({"layer": "SEMANTIC_REVIEW", "path": path, "check": "INCORRECT"})
        elif review["verdict"] != "CORRECT":
            pending.append({"path": path, "content_sha256": sha, "reason": review["verdict"]})
    return {
        "status": "FAIL" if errors else "UNKNOWN" if pending else "PASS",
        "errors": errors, "semantic_pending": pending,
        "contract_sha256": content_hash(contract), "state_sha256": content_hash(state),
        "execution_proven_by_checker": False,
        "review_independence": "Caller must disclose adjudicator and arm blinding; not inferred.",
    }
