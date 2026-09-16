"""Pure JSON boundary contrast and finite selection tests; no HTTP or business execution."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from v0220_wire_contract import encoded
from v0222_boundary_contract import (
    CONDITIONS,
    RESOURCES,
    ROOT_ORDER,
    BoundaryContractError,
    audit_transform,
    decision,
    observe,
    serialize,
    strict_json,
    transform,
)


def fixture(value='  中文 café "quoted" \\ path\nnew\ttab  '):
    expected = {
        "action": "put_record",
        "arguments": {
            "object_id": "target",
            "expected_version": 0,
            "data": {"text": value},
        },
    }
    schema = {
        "type": "object",
        "required": ["action", "arguments"],
        "additionalProperties": False,
        "properties": {
            "action": {"const": "put_record"},
            "arguments": {
                "type": "object",
                "required": ["object_id", "expected_version", "data"],
                "additionalProperties": False,
                "properties": {
                    "object_id": {"type": "string"},
                    "expected_version": {"type": "integer", "minimum": 0},
                    "data": {
                        "type": "object",
                        "required": ["text"],
                        "additionalProperties": False,
                        "properties": {
                            "text": {"type": "string", "minLength": 1, "pattern": r"\S"},
                        },
                    },
                },
            },
        },
    }
    presentation = {
        "profile": "INTENT_ORACLE",
        "contract": {"authorized_intent": "ordinary schema property"},
        "origin": "HARNESS_PUBLIC_PREFETCH",
        "observations": [
            {
                "resource": name,
                "content": {
                    "authorized_intent": "source data with same field name, not protocol intent",
                    "text": 'Text says "authorized_intent" and preserves \t \n and café.',
                },
            }
            for name in sorted(RESOURCES)
        ],
        "inherited_note": None,
        "authorized_intent": {"authorized_action": expected},
    }
    body = {
        "model": "synthetic-model",
        "temperature": 0,
        "seed": 213,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": "unchanged calibration"},
            {"role": "user", "content": serialize(presentation)},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"schema": schema}},
    }
    return body, expected, schema


@pytest.mark.parametrize("condition", CONDITIONS)
def test_exact_movement_and_inverse_without_repair_or_compiler(condition):
    original, expected, _ = fixture()
    before = copy.deepcopy(original)
    candidate = transform(original, condition)
    assert original == before and candidate is not original
    audit = audit_transform(original, candidate, condition)
    assert all(audit["checks"].values())
    if condition == "B0":
        assert serialize(candidate) == serialize(original)
    else:
        remainder = json.loads(candidate["messages"][-2]["content"])
        moved = json.loads(candidate["messages"][-1]["content"])
        assert "authorized_intent" not in remainder
        assert moved == {"authorized_intent": {"authorized_action": expected}}
        assert moved["authorized_intent"]["authorized_action"]["arguments"]["data"][
            "text"
        ].startswith("  ")
        assert candidate["messages"][:-2] == original["messages"][:-1]
        splice = audit["reversible_diff"]["content_splice"]
        old = original["messages"][-1]["content"]
        start = splice["start_character"]
        assert old[start : start + len(splice["removed"])] == splice["removed"]
        assert (
            old[:start] + splice["added"] + old[start + len(splice["removed"]) :]
            == candidate["messages"][-2]["content"]
        )
    assert candidate["response_format"] == original["response_format"]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "nan",
        "missing",
        "not_last",
        "two_intents",
        "note",
        "source_missing",
        "bad_role",
        "bad_intent",
        "retransform",
    ],
)
def test_invalid_or_already_transformed_original_rejected(mutation):
    body, _, _ = fixture()
    presentation = json.loads(body["messages"][-1]["content"])
    if mutation == "duplicate":
        body["messages"][-1]["content"] = body["messages"][-1]["content"].replace(
            '"profile": "INTENT_ORACLE"', '"profile":"INTENT_ORACLE","profile":"INTENT_ORACLE"'
        )
    elif mutation == "nan":
        body["messages"][-1]["content"] = body["messages"][-1]["content"].replace(
            '"inherited_note": null', '"inherited_note": NaN'
        )
    elif mutation == "two_intents":
        body["messages"].insert(
            1,
            {
                "role": "user",
                "content": serialize({"authorized_intent": presentation["authorized_intent"]}),
            },
        )
    elif mutation == "bad_role":
        body["messages"][-1]["role"] = "assistant"
    elif mutation == "retransform":
        body = transform(body, "B1")
    else:
        if mutation == "missing":
            presentation.pop("authorized_intent")
        elif mutation == "not_last":
            presentation["inherited_note"] = presentation.pop("inherited_note")
        elif mutation == "note":
            presentation["inherited_note"] = "old note"
        elif mutation == "source_missing":
            presentation["observations"].pop()
        elif mutation == "bad_intent":
            presentation["authorized_intent"] = {"authorized_action": {"action": "finish"}}
        body["messages"][-1]["content"] = serialize(presentation)
    with pytest.raises(BoundaryContractError):
        transform(body, "B1")


def test_b1_will_not_silently_reserialize_nonoriginal_source_format():
    body, _, _ = fixture()
    body["messages"][-1]["content"] = json.dumps(
        json.loads(body["messages"][-1]["content"]), indent=2
    )
    assert transform(body, "B0")["messages"] == body["messages"]
    with pytest.raises(BoundaryContractError, match="SERIALIZATION_DRIFT"):
        transform(body, "B1")


@pytest.mark.parametrize("condition", CONDITIONS)
def test_encoded_frozen_request_roundtrip_retains_exact_schema_order_audit(condition):
    body, _, _ = fixture()
    # Actual frozen requests are read from encoded(sort_keys=True) bytes.
    original = strict_json(encoded(body))
    candidate = strict_json(encoded(transform(original, condition)))
    assert audit_transform(original, candidate, condition)["status"] == "BOUNDARY_TRANSFORM_PASS"
    assert list(candidate["messages"][-1]) == list(original["messages"][-1])
    props = candidate["response_format"]["json_schema"]["schema"]["properties"]
    candidate["response_format"]["json_schema"]["schema"]["properties"] = dict(
        reversed(list(props.items()))
    )
    with pytest.raises(BoundaryContractError, match="EXACT_FROZEN"):
        audit_transform(original, candidate, condition)


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "duplicate_intent",
        "target",
        "parameter",
        "numeric_type",
        "schema",
        "schema_order",
        "system",
        "extra_message",
        "escape_spelling",
    ],
)
def test_audit_rejects_any_unplanned_candidate_change(mutation):
    body, _, _ = fixture()
    changed = transform(body, "B1")
    if mutation in {"source", "duplicate_intent"}:
        value = json.loads(changed["messages"][-2]["content"])
        if mutation == "source":
            value["observations"][0]["content"] = "cropped"
        else:
            value["authorized_intent"] = json.loads(changed["messages"][-1]["content"])[
                "authorized_intent"
            ]
        changed["messages"][-2]["content"] = serialize(value)
    elif mutation == "target":
        value = json.loads(changed["messages"][-1]["content"])
        value["authorized_intent"]["authorized_action"]["arguments"]["object_id"] = "another"
        changed["messages"][-1]["content"] = serialize(value)
    elif mutation == "parameter":
        changed["seed"] = 214
    elif mutation == "numeric_type":
        changed["temperature"] = 0.0
    elif mutation == "schema":
        changed["response_format"]["json_schema"]["schema"]["required"] = []
    elif mutation == "schema_order":
        props = changed["response_format"]["json_schema"]["schema"]["properties"]
        changed["response_format"]["json_schema"]["schema"]["properties"] = dict(
            reversed(list(props.items()))
        )
    elif mutation == "system":
        changed["messages"][0]["content"] += " copy carefully"
    elif mutation == "extra_message":
        changed["messages"].append(copy.deepcopy(changed["messages"][-1]))
    else:
        changed["messages"][-1]["content"] = json.dumps(
            json.loads(changed["messages"][-1]["content"]), ensure_ascii=True
        )
    with pytest.raises(BoundaryContractError, match="EXACT_FROZEN"):
        audit_transform(body, changed, "B1")


@pytest.mark.parametrize("raw", ["not json", "NaN", "Infinity", "1e999", '{"a":1,"a":2}'])
def test_invalid_json_is_only_observation(raw):
    _, expected, schema = fixture()
    result = observe(expected, schema, raw)
    assert result["classification"] == "INVALID_STRICT_JSON"
    assert not result["exact_fidelity"] and result["business_dispatches"] == 0


def test_invalid_unicode_never_normalized_or_repaired():
    _, expected, schema = fixture()
    raw = serialize(expected).replace("café", r"caf\ud800")
    row = observe(expected, schema, raw)
    assert row["strict_json"] and not row["full_schema"]
    assert row["classification"] == "INVALID_UNICODE_CONTENT"


def test_unicode_whitespace_escape_spelling_and_full_value_fidelity():
    _, expected, schema = fixture()
    assert observe(expected, schema, json.dumps(expected, ensure_ascii=True))["exact_fidelity"]
    altered = copy.deepcopy(expected)
    altered["arguments"]["data"]["text"] = altered["arguments"]["data"]["text"].strip()
    row = observe(expected, schema, serialize(altered))
    assert row["full_schema"] and not row["exact_fidelity"]
    assert row["differences"][0]["path"] == "/arguments/data/text"
    altered["arguments"]["data"]["text"] = " \t\n"
    assert observe(expected, schema, serialize(altered))["classification"] == "FULL_SCHEMA_REJECTED"


@pytest.mark.parametrize("mutation,kind", [("missing", "MISSING_OR_EXTRA"), ("type", "TYPE")])
def test_full_schema_rejections_still_locate_complete_field_difference(mutation, kind):
    _, expected, schema = fixture()
    altered = copy.deepcopy(expected)
    if mutation == "missing":
        altered["arguments"]["data"].pop("text")
    else:
        altered["arguments"]["data"]["text"] = 17
    raw = serialize(altered)
    row = observe(expected, schema, raw)
    assert row["classification"] == "FULL_SCHEMA_REJECTED"
    assert row["strict_json"] and not row["full_schema"] and not row["exact_fidelity"]
    assert row["differences"][0]["path"] == "/arguments/data/text"
    assert row["differences"][0]["kind"] == kind
    assert raw == serialize(altered) and row["automatic_value_repair"] is False
    assert row["business_dispatches"] == 0


@pytest.mark.parametrize(
    "version,schema_pass,exact,classification",
    [
        (0, True, True, "EXACT_COPY"),
        (0.0, True, False, "CAS_TYPE_REJECTED"),
        (False, False, False, "CAS_TYPE_REJECTED"),
        (True, False, False, "CAS_TYPE_REJECTED"),
        ("0", False, False, "CAS_TYPE_REJECTED"),
    ],
)
def test_cas_requires_real_integer_without_changing_json_schema_truth(
    version,
    schema_pass,
    exact,
    classification,
):
    _, expected, schema = fixture()
    actual = copy.deepcopy(expected)
    actual["arguments"]["expected_version"] = version
    raw = serialize(actual)
    row = observe(expected, schema, raw)
    assert row["strict_json"] and row["full_schema"] is schema_pass
    assert row["exact_fidelity"] is exact and row["classification"] == classification
    assert row["automatic_value_repair"] is False and row["business_dispatches"] == 0
    assert raw == serialize(actual)
    if not exact:
        assert any(
            d["path"] == "/arguments/expected_version" and d["kind"] == "TYPE"
            for d in row["differences"]
        )
        assert row["protocol_issues"][0]["rule"] == "CAS_INTEGER_REPRESENTATION"


def test_ordinary_business_numbers_keep_existing_numeric_equality():
    _, expected, schema = fixture()
    expected["arguments"]["data"]["amount"] = 1
    data_schema = schema["properties"]["arguments"]["properties"]["data"]
    data_schema["properties"]["amount"] = {"type": "number"}
    data_schema["required"].append("amount")
    actual = copy.deepcopy(expected)
    actual["arguments"]["data"]["amount"] = 1.0
    row = observe(expected, schema, serialize(actual))
    assert row["full_schema"] and row["exact_fidelity"]
    assert row["differences"] == [] and row["classification"] == "EXACT_COPY"


def test_missing_cas_remains_required_field_failure_not_a_fabricated_type_value():
    _, expected, schema = fixture()
    actual = copy.deepcopy(expected)
    actual["arguments"].pop("expected_version")
    row = observe(expected, schema, serialize(actual))
    assert row["classification"] == "FULL_SCHEMA_REJECTED"
    assert row["differences"][0] == {
        "path": "/arguments/expected_version",
        "kind": "MISSING_OR_EXTRA",
    }


def observations(rule, *, final=False):
    return [
        {
            "id": f"boundary-{i:02d}",
            "root": root,
            "cold": cold,
            "condition": condition,
            "exact_fidelity": rule(root, cold, condition),
        }
        for i, (root, cold, condition) in enumerate(
            [
                (root, cold, condition)
                for cold in ((1, 2) if final else (1,))
                for root in ROOT_ORDER
                for condition in (CONDITIONS if cold == 1 else tuple(reversed(CONDITIONS)))
            ],
            1,
        )
    ]


def test_first_pass_only_same_root_improvement_triggers_full_repeat():
    assert decision(observations(lambda r, c, b: True)) == {
        "status": "NO_DIFFERENTIAL_SIGNAL",
        "repeat_required": False,
    }
    assert decision(observations(lambda r, c, b: b == "B1")) == {
        "status": "REPEAT_REQUIRED",
        "repeat_required": True,
    }
    assert decision(observations(lambda r, c, b: r == ROOT_ORDER[0]))["repeat_required"] is False


def test_final_requires_all_eight_and_consistent_root_improvement():
    assert decision(observations(lambda r, c, b: b == "B1", final=True), final=True) == {
        "status": "INTENT_BOUNDARY_SIGNAL",
        "selected_condition": "B1",
    }
    rules = [
        lambda r, c, b: True,
        lambda r, c, b: b == "B1" and not (r == ROOT_ORDER[3] and c == 2),
        lambda r, c, b: b == "B1" or r != ROOT_ORDER[c - 1],
    ]
    for rule in rules:
        assert decision(observations(rule, final=True), final=True) == {
            "status": "NO_QUALIFIED_PRESENTATION_CANDIDATE",
            "selected_condition": None,
        }


@pytest.mark.parametrize(
    "mutation", ["short", "extra", "order", "id", "bool_cold", "int_fidelity", "wrong_root"]
)
def test_selector_rejects_partial_cherry_picked_or_badly_typed_matrix(mutation):
    rows = observations(lambda r, c, b: b == "B1")
    if mutation == "short":
        rows.pop()
    elif mutation == "extra":
        rows.append(copy.deepcopy(rows[-1]))
    elif mutation == "order":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "id":
        rows[1]["id"] = rows[0]["id"]
    elif mutation == "bool_cold":
        rows[0]["cold"] = True
    elif mutation == "int_fidelity":
        rows[0]["exact_fidelity"] = 1
    else:
        rows[0]["root"] = "unopened-root"
    with pytest.raises(BoundaryContractError):
        decision(rows)
