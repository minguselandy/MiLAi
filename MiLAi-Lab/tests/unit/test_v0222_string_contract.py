"""Local selected-string compiler acceptance proof; never a decoder/model score."""

import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, SchemaError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put

from v0213_provider import payload
from v0218_world import World
from v0220_action_adapter import ActionAdapter
from v0220_action_contract import ActionContract
from v0220_evidence import read
from v0220_wire_contract import WireContractError, encoded, fingerprint
from v0220_wire_contract import compile_contract as compile_unique_contract
from v0222_string_contract import REVISION, compile_contract

STRING = {"type": "string", "pattern": r"\S", "minLength": 1}


@pytest.mark.parametrize(
    "value",
    [
        "synthetic.user@example.invalid",
        "multi word text",
        "中文 café Ω 😀",
        'quote "hello"; path C:\\lab\\test\nline two\tfin',
        "  \t[alpha, beta!]  \n",
        "x",
        "前面 \n\t 后面",
        " a " * 400,
    ],
)
def test_valid_strings_preserve_every_decoded_character(value):
    plan = compile_contract(STRING)
    for raw in (json.dumps(value, ensure_ascii=False), json.dumps(value, ensure_ascii=True)):
        result = plan.validate_output(raw)
        assert result == value
        assert result.encode("utf-8") == value.encode("utf-8")
    assert Draft202012Validator(plan.wire).is_valid(value)
    assert plan.canonical == STRING and plan.wire == {"type": "string"}


@pytest.mark.parametrize("value", ["", " ", "\t\n", "\u2003", None, False, 1, [], {}])
def test_complete_authority_rejects_empty_whitespace_and_wrong_type(value):
    plan = compile_contract(STRING)
    if isinstance(value, str):
        assert Draft202012Validator(plan.wire).is_valid(value)
    with pytest.raises(WireContractError, match="PUBLIC_CONTRACT_REJECTED"):
        plan.validate_output(encoded(value))


@pytest.mark.parametrize(
    "raw",
    [
        '{"text":"a","text":"b"}',
        "NaN",
        "Infinity",
        "1e999",
        "{broken",
        "[" * 1100 + "0" + "]" * 1100,
    ],
)
def test_strict_finite_json_still_required(raw):
    with pytest.raises(WireContractError):
        compile_contract({"type": "object", "properties": {"text": STRING}}).validate_output(raw)


def test_only_exact_string_keyword_values_are_deferred():
    schemas = [
        {"type": "string", "pattern": "^\\S+$", "minLength": 2, "maxLength": 50},
        {"type": "string", "pattern": r"\\S", "minLength": 0},
        {"type": "string", "format": "email", "enum": ["a@example.invalid"]},
        {"type": "string", "const": "fixed", "pattern": "^fixed$"},
        {"type": ["string", "null"], "pattern": r"\S", "minLength": 1},
        {"pattern": r"\S", "minLength": 1},
        {"type": "string", "minLength": 1.0},
    ]
    for schema in schemas:
        plan = compile_contract(schema)
        assert fingerprint(plan.wire) == fingerprint(schema)
        assert plan.manifest()["deferred_checks"] == []
    plan = compile_contract({"type": "string", "minLength": 1, "pattern": "^fixed$"})
    assert plan.wire == {"type": "string", "pattern": "^fixed$"}
    assert plan.manifest()["deferred_checks"][0]["rule_kind"] == "minLength"


@pytest.mark.parametrize("bad", [True, False, -1, "1"])
def test_invalid_minlength_types_are_not_lowered(bad):
    with pytest.raises(SchemaError):
        compile_contract({"type": "string", "minLength": bad})


@pytest.mark.parametrize("condition", ["D00", "D10", "D01", "D12", "", None, True])
def test_only_the_selected_candidate_is_available(condition):
    with pytest.raises(WireContractError, match="UNSELECTED_STRING"):
        compile_contract(STRING, selected_condition=condition)


def test_literal_keywords_and_business_names_are_not_schema_nodes():
    literal = {"type": "string", "pattern": r"\S", "minLength": 1, "uniqueItems": True}
    schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "const": r"\S"},
            "minLength": {"type": "integer", "enum": [1]},
            "default": {"type": "object", "const": literal},
            "a/~b": copy.deepcopy(STRING),
        },
        "default": literal,
        "examples": [literal],
        "enum": [{"default": literal}],
    }
    before = copy.deepcopy(schema)
    plan = compile_contract(schema)
    assert schema == before and plan.canonical == before
    for key in ("default", "examples", "enum"):
        assert plan.wire[key] == schema[key]
    for key in ("pattern", "minLength", "default"):
        assert plan.wire["properties"][key] == schema["properties"][key]
    assert {r["path"] for r in plan.manifest()["deferred_checks"]} == {
        "/properties/a~1~0b/pattern",
        "/properties/a~1~0b/minLength",
    }


@pytest.mark.parametrize("key", ["anyOf", "allOf", "prefixItems"])
def test_reviewed_positive_list_nodes(key):
    plan = compile_contract({key: [copy.deepcopy(STRING)]})
    assert plan.wire[key] == [{"type": "string"}]
    assert {r["path"] for r in plan.manifest()["deferred_checks"]} == {
        f"/{key}/0/pattern",
        f"/{key}/0/minLength",
    }


@pytest.mark.parametrize("key", ["items", "additionalProperties", "propertyNames"])
def test_reviewed_positive_single_nodes(key):
    plan = compile_contract({key: copy.deepcopy(STRING)})
    assert plan.wire[key] == {"type": "string"}


def test_reviewed_map_nodes_and_boolean_schemas():
    schema = {"properties": {"yes": True, "no": False}, "patternProperties": {"^x": STRING}}
    plan = compile_contract(schema)
    assert plan.wire["properties"] == schema["properties"]
    assert plan.wire["patternProperties"] == {"^x": {"type": "string"}}


@pytest.mark.parametrize(
    "schema",
    [
        {"not": STRING},
        {"oneOf": [STRING, {}]},
        {"if": STRING, "then": {}},
        {"$ref": "https://example.invalid/never-read"},
        {"$defs": {"value": STRING}},
        {"contains": STRING},
        {"unevaluatedProperties": False},
        {"x-unknown": STRING},
    ],
)
def test_unreviewed_negative_or_reference_nodes_stay_rejected(schema):
    with pytest.raises(WireContractError, match="UNREVIEWED_SCHEMA_OPERATOR"):
        compile_contract(schema)


def test_unique_items_remains_in_authoritative_validator():
    schema = {"type": "array", "items": STRING, "uniqueItems": True, "minItems": 1}
    plan = compile_contract(schema)
    assert plan.wire == {"type": "array", "items": {"type": "string"}, "minItems": 1}
    assert plan.validate_output('["a"," b "]') == ["a", " b "]
    for value in (["a", "a"], ["a", "  "], []):
        with pytest.raises(WireContractError, match="PUBLIC_CONTRACT_REJECTED"):
            plan.validate_output(encoded(value))
    deferred = plan.manifest()["deferred_checks"]
    assert {r["rule_kind"] for r in deferred} == {"uniqueItems", "pattern", "minLength"}
    assert all(
        r["value"] == r["original_value"] and r["enforced_by"] == "full_schema_before_dispatch"
        for r in deferred
    )
    assert compile_unique_contract(schema).wire["items"] == STRING


def test_other_business_constraints_and_immutable_values_remain():
    schema = {
        "type": "object",
        "required": ["text", "amount", "when", "fixed", "enabled"],
        "additionalProperties": False,
        "properties": {
            "text": STRING,
            "amount": {"type": "number", "minimum": 0, "maximum": 10},
            "when": {"type": "string", "format": "email"},
            "fixed": {"type": "string", "enum": ["left", "right"]},
            "enabled": {"type": "boolean"},
        },
    }
    plan = compile_contract(schema)
    good = {
        "text": " a ",
        "amount": 5,
        "when": "synthetic@example.invalid",
        "fixed": "left",
        "enabled": False,
    }
    assert plan.validate_output(encoded(good)) == good
    for field, value in (
        ("amount", -1),
        ("when", "not-an-email"),
        ("fixed", "else"),
        ("enabled", 0),
        ("extra", 1),
    ):
        invalid = {**good, field: value}
        with pytest.raises(WireContractError):
            plan.validate_output(encoded(invalid))
    with pytest.raises(WireContractError):
        plan.validate_output(encoded({k: v for k, v in good.items() if k != "text"}))
    canonical, wire = plan.canonical, plan.wire
    canonical.clear()
    wire.clear()
    assert plan.canonical == schema and plan.wire["required"] == schema["required"]


@pytest.mark.parametrize("system", [None, "", "Original complete policy."])
def test_prepare_preserves_sources_and_reports_exact_prompt_change(system):
    messages = ([{"role": "system", "content": system}] if system is not None else []) + [
        {"role": "user", "content": "完整资料, 不截断。"},
    ]
    body = payload(messages, copy.deepcopy(STRING))
    before = copy.deepcopy(body)
    plan = compile_contract(STRING)
    wire, diff = plan.prepare(body), plan.prompt_diff(body)
    assert body == before
    assert wire["messages"][-1] == before["messages"][-1]
    assert wire["messages"][0]["content"] == (system or "") + diff["append_text"]
    assert plan.canonical_json in wire["messages"][0]["content"]
    assert wire["messages"][0]["content"].count("Transport compatibility contract") == 1
    assert diff["new_instruction_utf8_bytes"] == len(diff["append_text"].encode())
    assert diff["prepared_messages_sha256"] == fingerprint(wire["messages"])
    assert diff["single_variable_decoder_causal_claim"] is False
    assert plan.manifest()["revision"] == REVISION
    assert plan.manifest()["selected_condition"] == "D11"


def test_prepare_rejects_typed_canonical_drift_and_nontext_system():
    plan = compile_contract(STRING)
    wrong = copy.deepcopy(STRING)
    wrong["minLength"] = True
    with pytest.raises(WireContractError, match="CANONICAL_REQUEST_DRIFT"):
        plan.prepare(payload([], wrong))
    with pytest.raises(WireContractError, match="TEXT_SYSTEM"):
        plan.prepare(payload([{"role": "system", "content": []}], copy.deepcopy(STRING)))


def test_datetime_rule_is_preserved_with_exact_legacy_format_availability():
    schema = {"type": "string", "format": "date-time"}
    plan = compile_contract(schema)
    assert plan.wire == plan.canonical == schema
    # Optional format plugins are deliberately not installed or silently assumed.
    # This proves unchanged acceptance, not availability of every format checker.
    baseline = Draft202012Validator(schema, format_checker=FormatChecker())
    for value in ("2026-09-11T00:00:00Z", "not-a-date"):
        if baseline.is_valid(value):
            assert plan.validate_output(encoded(value)) == value
        else:
            with pytest.raises(WireContractError):
                plan.validate_output(encoded(value))


def test_validator_blocks_before_original_action_adapter_and_preserves_cas(tmp_path):
    environment = public()
    for record in environment["task"]["record_schemas"].values():
        record["properties"]["text"] = copy.deepcopy(STRING)
    adapter = ActionAdapter(
        World.create(tmp_path / "world.sqlite", "owned", environment),
        ActionContract.from_public(environment),
    )
    plan = compile_contract(adapter.contract.action_schema())
    initial = adapter.world.snapshot()
    for field, value in (("text", "  "), ("scope", "other"), ("object_id", "other")):
        invalid = put()
        invalid["arguments"]["data"][field] = value
        with pytest.raises(WireContractError):
            plan.validate_output(encoded(invalid))
        assert adapter.world.snapshot() == initial and adapter.world.ledger() == []
    for version in (True, -1, "0"):
        invalid = put(version=version)
        with pytest.raises(WireContractError):
            plan.validate_output(encoded(invalid))
    action = plan.validate_output(encoded(put()))
    receipt = adapter.execute(action, operation_id="synthetic:01")
    assert receipt["committed"] is True
    assert adapter.read("records")["content"]["left"]["text"] == put()["arguments"]["data"]["text"]
    assert adapter.execute(action, operation_id="synthetic:01") == receipt
    assert adapter.execute(action, operation_id="stale:01")["committed"] is False
    assert len(adapter.world.ledger()) == 1


def test_eight_original_contracts_and_all_25_exposed_reference_objects():
    evidence = Path("/cra/memory/mx_memory/evidence")
    inventory_path = evidence / "v0220-wire-fix/20260911-v1/inventory.json"
    if not inventory_path.is_file():
        pytest.skip("Already-exposed reference evidence is external to Git")
    inventory = read(inventory_path)
    assert len(inventory) == 8
    object_count, schema_count, string_rule_count = 0, 0, 0
    for row in inventory:
        path = inventory_path.parent / "requests" / (row["id"] + "-canonical.json")
        body = read(path)
        plan = compile_contract(body["response_format"]["json_schema"]["schema"])
        schema_count += 1
        assert plan.canonical == body["response_format"]["json_schema"]["schema"]
        prepared = plan.prepare(body)
        assert prepared["messages"][1:] == (
            body["messages"][1:] if body["messages"][0]["role"] == "system" else body["messages"]
        )
        if row["finish_only"]:
            plan.validate_output(encoded({"action": "finish", "arguments": {"message": "done"}}))
            continue
        case = evidence / "v0219/f2-wave1-v1/cases" / row["root"]
        public_data, reference = (
            read(case / "public-initial.json"),
            read(case / "independent-reference.json"),
        )
        records = reference.get("records", reference.get("initial_records"))
        assert set(records) == set(public_data["objects"])
        for object_id in public_data["objects"]:
            action = {
                "action": "put_record",
                "arguments": {
                    "object_id": object_id,
                    "expected_version": 0,
                    "data": {k: v for k, v in records[object_id].items() if k != "object_id"},
                },
            }
            assert plan.validate_output(encoded(action)) == action
            assert Draft202012Validator(plan.wire).is_valid(action)
            object_count += 1
        string_rule_count += sum(
            r["rule_kind"] in {"pattern", "minLength"} for r in plan.manifest()["deferred_checks"]
        )
    assert object_count == 25 and schema_count == 8 and string_rule_count > 0
