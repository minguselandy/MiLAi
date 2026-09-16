"""P1 isolates only two transport keywords; all outputs remain diagnostic."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0220_wire_contract import encoded
from v0222_diagnostic import CONDITIONS, FIXTURES, SCHEMA, differences, observe, request, specs


def test_frozen_complete_order_and_reverse_pass():
    rows = specs()
    assert len(rows) == 24 and len({r["id"] for r in rows}) == 24
    for start in (0, 4, 8):
        assert [r["condition"] for r in rows[start : start + 4]] == list(CONDITIONS)
        assert [r["condition"] for r in rows[12 + start : 16 + start]] == list(reversed(CONDITIONS))


def test_control_characters_are_actual_values_not_only_literal_escape_sequences():
    assert "\n" in FIXTURES["T2"] and "\t" in FIXTURES["T2"]
    assert "\\" in FIXTURES["T2"] and '"' in FIXTURES["T2"]
    assert "\n" in FIXTURES["T3"] and "\t" in FIXTURES["T3"]
    assert FIXTURES["T3"] != FIXTURES["T3"].strip()


@pytest.mark.parametrize("fixture", FIXTURES)
def test_only_two_wire_keywords_vary_and_all_targets_are_legal(fixture):
    pairs = [request(fixture, condition) for condition in CONDITIONS]
    canonical = pairs[0][0]
    assert all(a == canonical and b["messages"] == canonical["messages"] for a, b in pairs)
    for condition, (_, wire) in zip(CONDITIONS, pairs, strict=True):
        restored = copy.deepcopy(wire)
        node = restored["response_format"]["json_schema"]["schema"]["properties"]["text"]
        assert ("pattern" in node) == (condition in ("D00", "D01"))
        assert ("minLength" in node) == (condition in ("D00", "D10"))
        node.update(SCHEMA["properties"]["text"])
        assert restored == canonical
    assert observe(encoded({"text": FIXTURES[fixture]}), fixture)["exact_fidelity"]


@pytest.mark.parametrize("raw", ['{"text":"a","text":"b"}', "NaN", "{} trailing"])
def test_invalid_json_is_diagnostic_not_an_exception_or_action(raw):
    row = observe(raw, "T1")
    assert row["content_class"] == "INVALID_STRICT_JSON"
    assert not row["exact_fidelity"] and row["business_dispatches"] == 0


@pytest.mark.parametrize(
    "value", [{"text": ""}, {"text": " \t\n"}, {"text": 4}, {}, {"text": "valid", "extra": True}]
)
def test_full_schema_failures_recorded_not_relaxed(value):
    row = observe(encoded(value), "T1")
    assert row["strict_json"] and not row["full_schema"]
    assert row["content_class"] == "FULL_SCHEMA_REJECTED"


def test_legal_short_output_is_not_fidelity_pass():
    row = observe('{"text":"f"}', "T1")
    assert row["full_schema"] and not row["exact_fidelity"]


def test_comparator_preserves_string_bytes_types_and_array_order():
    assert differences({"a": "é", "b": 1}, {"b": 1.0, "a": "é"}) == []
    assert differences({"a": True}, {"a": 1})[0]["kind"] == "TYPE"
    assert differences(" x ", "x")
    assert differences(["a", "b"], ["b", "a"])
    assert differences({"a": 1}, {})[0]["kind"] == "MISSING_OR_EXTRA"
    assert observe('{"text":"  \\t[alpha, beta!]  \\n"}', "T3")["exact_fidelity"]


def test_unplanned_fixture_or_condition_fails_before_transport():
    with pytest.raises(ValueError):
        request("business_answer", "D00")
    with pytest.raises(ValueError):
        request("T1", "D20")


@pytest.mark.parametrize("raw", ['{"text":"\\ud800"}', '{"text":"\\udfff"}'])
def test_malformed_unicode_is_a_content_observation_not_a_runner_crash(raw):
    row = observe(raw, "T2")
    assert row["content_class"] == "INVALID_UNICODE_CONTENT"
    assert row["strict_json"] and not row["exact_fidelity"]
    assert row["business_dispatches"] == 0
