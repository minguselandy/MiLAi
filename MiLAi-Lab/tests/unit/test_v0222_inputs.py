"""P0 schema traversal, strict acceptance and non-normalizing fidelity tests."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from audit_v0222_inputs import (
    field_diff,
    metrics,
    positions,
    reconstruct_old_wire,
    string_constraints,
    validate_raw,
    validator_boundaries,
)


def test_schema_walk_separates_property_names_and_literal_payloads():
    schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "pattern": r"\S", "default": {"pattern": "fake"}},
            "minLength": {"const": "not a keyword"},
            "enum": {"enum": [{"type": "string", "pattern": "fake"}]},
            "a/b~c": {"anyOf": [{"type": "null"}, {"type": "string", "minLength": 1}]},
        },
        "examples": [{"type": "string", "pattern": "fake"}],
        "default": {"properties": {"fake": {"type": "string"}}},
    }
    before = copy.deepcopy(schema)
    rows = string_constraints(schema)
    assert schema == before
    assert [r["pointer"] for r in rows] == [
        "/properties/pattern",
        "/properties/minLength",
        "/properties/a~1b~0c/anyOf/1",
    ]
    assert rows[-1]["operators"] == [{"keyword": "anyOf", "pointer": "/properties/a~1b~0c/anyOf"}]


def test_schema_walk_records_negative_and_conditional_context_without_transforming():
    rows = string_constraints(
        {
            "not": {"type": "string", "pattern": "x"},
            "if": {"type": "string"},
            "then": {"minLength": 1},
            "$defs": {"literal": {"enum": ["x"]}},
        }
    )
    assert len(rows) == 4
    assert rows[0]["operators"][0]["keyword"] == "not"
    assert rows[-1]["pointer"] == "/$defs/literal"


def test_schema_walk_does_not_misclassify_literals_or_booleans():
    assert (
        string_constraints(
            {
                "additionalProperties": False,
                "const": {"pattern": r"\S"},
                "enum": [{"minLength": 1}],
                "type": "object",
            }
        )
        == []
    )


@pytest.mark.parametrize("row", validator_boundaries(), ids=lambda r: r["name"])
def test_full_validator_boundary(row):
    assert row["pass"]
    assert row["decoder_membership"] == "UNOBSERVED"


def test_exact_values_not_lexical_json_or_object_key_order():
    a = json.loads('{"text":"\\u4e2d\\n", "n":1}')
    b = json.loads('{"n":1,"text":"中\\n"}')
    assert field_diff(a, b) == []
    assert field_diff({"s": " a "}, {"s": "a"})[0]["path"] == "/s"
    assert field_diff({"s": [1, 2]}, {"s": [2, 1]})
    assert field_diff({"n": 1}, {"n": True})[0]["kind"] == "TYPE"
    assert field_diff({"n": 1}, {})[0]["kind"] == "MISSING"


def test_character_bytes_and_escaping_are_separate():
    assert metrics("中a")["characters"] == 2
    assert metrics("中a")["utf8_bytes"] == 4
    assert positions("中a中a", "a") == {
        "count": 2,
        "character_offsets": [1, 3],
        "utf8_byte_offsets": [3, 7],
    }


def test_strict_json_rejects_duplicates_before_schema_acceptance():
    result = validate_raw({"type": "object"}, '{"a":1,"a":2}')
    assert result == {"accepted": False, "layer": "JSON", "code": "DUPLICATE_JSON_KEY"}


def test_independent_old_wire_replay_removes_only_schema_unique_items():
    schema = {
        "type": "object",
        "properties": {
            "uniqueItems": {"const": {"uniqueItems": True}},
            "a": {
                "type": "array",
                "items": {"type": "string", "pattern": r"\S"},
                "uniqueItems": True,
                "default": [{"uniqueItems": True}],
            },
        },
    }
    original = {
        "messages": [{"role": "system", "content": "original"}],
        "response_format": {"json_schema": {"schema": schema}},
    }
    before = copy.deepcopy(original)
    wire = reconstruct_old_wire(original)
    assert original == before
    mapped = wire["response_format"]["json_schema"]["schema"]
    assert mapped["properties"]["uniqueItems"] == schema["properties"]["uniqueItems"]
    assert mapped["properties"]["a"]["default"] == [{"uniqueItems": True}]
    assert mapped["properties"]["a"]["items"]["pattern"] == r"\S"
    assert "uniqueItems" not in mapped["properties"]["a"]
    assert wire["messages"][0]["content"].startswith("original\n\nTransport")


def test_audit_import_does_not_load_model_or_provider_runtime():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0,'tools'); "
            "import audit_v0222_inputs; "
            "forbidden={'transformers','torch','vllm','v0220_provider_hardened'}; "
            "assert not forbidden & set(sys.modules)",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
