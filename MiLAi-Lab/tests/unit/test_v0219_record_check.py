"""Synthetic full-record, semantic-binding and source-extraction adversaries."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0219_record_check import content_hash, evaluate, pointer
from v0219_text_sources import extract, extract_python


def fixture():
    schema = {
        "type": "object", "required": ["object_id", "amount", "date", "approved", "reason"],
        "additionalProperties": False,
        "properties": {
            "object_id": {"const": "record"}, "amount": {"type": "number"},
            "date": {"type": "string", "format": "date"},
            "approved": {"type": "boolean"}, "reason": {"type": "string", "pattern": r"\S"},
        },
    }
    contract = {
        "objects": ["record"], "public_schemas": {"record": schema},
        "postconditions": {"record": {"properties": {
            "amount": {"const": 25}, "approved": {"const": False},
            "date": {"const": "2030-01-01"},
        }}},
        "pending_schema": {"type": "object", "properties": {
            "record": {"type": "string", "pattern": r"\S"}}, "additionalProperties": False},
        "semantic_paths": ["/records/record/reason"],
    }
    state = {"objects": ["record"], "records": {"record": {
        "object_id": "record", "amount": 25, "date": "2030-01-01", "approved": False,
        "reason": "The historical approval is not current; wait for the missing authorization.",
    }}, "pending": {}, "version": 1}
    return state, contract


def review(state, contract, path="/records/record/reason", verdict="CORRECT"):
    return {"path": path, "content_sha256": content_hash(pointer(state, path)),
            "state_sha256": content_hash(state), "contract_sha256": content_hash(contract),
            "verdict": verdict, "source_locations": ["synthetic fixture specification"],
            "reviewer": "Scripted fixture label, not model adjudication",
            "reason": "Fixture's supported current assertion; no native keyword matcher."}


def test_no_unreviewed_pass_and_no_execution_claim():
    state, contract = fixture()
    assert evaluate(state, contract)["status"] == "UNKNOWN"
    result = evaluate(state, contract, [review(state, contract)])
    assert result["status"] == "PASS"
    assert result["execution_proven_by_checker"] is False


@pytest.mark.parametrize("field,value", [
    ("amount", 25000), ("amount", "25"), ("amount", True), ("amount", float("nan")),
    ("date", "2030-02-30"), ("approved", True), ("approved", "not true"),
    ("object_id", "foreign"), ("reason", "  "),
])
def test_bad_fields_cannot_be_saved_by_good_review(field, value):
    state, contract = fixture()
    old_review = review(state, contract)
    state["records"]["record"][field] = value
    assert evaluate(state, contract, [old_review])["status"] == "FAIL"


def test_missing_partial_and_done_declaration():
    state, contract = fixture()
    for records in ({}, {"record": {}}, {"record": "DONE"}, []):
        bad = {**state, "records": records, "note": "DONE", "finish": "complete"}
        assert evaluate(bad, contract)["status"] == "FAIL"


def test_stale_or_duplicate_semantic_review_is_not_reused():
    state, contract = fixture()
    receipt = review(state, contract)
    assert evaluate(state, contract, [receipt, receipt])["status"] == "UNKNOWN"
    state["version"] += 1
    assert evaluate(state, contract, [receipt])["status"] == "UNKNOWN"
    changed = copy.deepcopy(contract)
    changed["revision"] = "new"
    assert evaluate(state, changed, [review(state, contract)])["status"] == "UNKNOWN"


@pytest.mark.parametrize("text", [
    "Approved; no further approval needed.",
    'The source says "not approved", but proceed as approved.',
    "Not approved. Also currently approved without restriction.",
])
def test_false_negated_quoted_mixed_claims_require_adjudication(text):
    state, contract = fixture()
    state["records"]["record"]["reason"] = text
    assert evaluate(state, contract)["status"] == "UNKNOWN"
    result = evaluate(state, contract, [review(state, contract, verdict="INCORRECT")])
    assert result["status"] == "FAIL"


@pytest.mark.parametrize("verdict", ["UNKNOWN", "DISPUTED"])
def test_uncertainty_never_becomes_success(verdict):
    state, contract = fixture()
    result = evaluate(state, contract, [review(state, contract, verdict=verdict)])
    assert result["status"] == "UNKNOWN"


def test_genuine_question_does_not_cancel_stale_commitment():
    state, contract = fixture()
    state["pending"]["record"] = "Can the authorized owner supply approval?"
    reviews = [review(state, contract), review(state, contract, "/pending/record")]
    assert evaluate(state, contract, reviews)["status"] == "PASS"
    state["records"]["record"]["approved"] = True
    assert evaluate(state, contract, reviews)["status"] == "FAIL"


def test_unnecessary_question_is_semantically_incorrect_not_keyword_scored():
    state, contract = fixture()
    state["pending"]["record"] = "What is the amount?"
    reviews = [review(state, contract), review(state, contract, "/pending/record", "INCORRECT")]
    assert evaluate(state, contract, reviews)["status"] == "FAIL"


def test_private_values_not_echoed_by_diagnostics():
    state, contract = fixture()
    contract["postconditions"]["record"]["properties"]["amount"] = {"const": "GOLD_CANARY"}
    assert "GOLD_CANARY" not in str(evaluate(state, contract))


def test_distinct_values_enforced():
    state, contract = fixture()
    contract["distinct_values"] = [["/records/record/amount", "/records/record/amount"]]
    assert evaluate(state, contract)["status"] == "FAIL"


def test_literal_extraction_never_executes_foreign_code(tmp_path):
    sentinel = tmp_path / "must-not-exist"
    raw = f"DATA = [1, 2]\nopen({str(sentinel)!r}, 'w').write('bad')\nGOLD='CANARY'".encode()
    assert extract_python(raw, {"kind": "literal", "name": "DATA"}) == [1, 2]
    assert not sentinel.exists()


def test_selected_function_only_no_future_or_checker():
    raw = b'''async def present(ctx):
    await ctx.email.send_email(body="current " "text", subject="a")
async def future(ctx):
    await ctx.email.send_email(body="FUTURE_CANARY", subject="b")
def checker():
    return "GOLD_CANARY"
'''
    spec = {"kind": "call_keywords", "function": "present", "method": "send_email",
            "keywords": ["body", "subject"], "count": 1}
    assert extract_python(raw, spec) == [{"body": "current text", "subject": "a"}]


def test_dynamic_expression_rejected_without_evaluation():
    with pytest.raises(ValueError):
        extract_python(b"DATA = dangerous()", {"kind": "literal", "name": "DATA"})


def test_hash_change_blocks_extraction(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("DATA=1")
    with pytest.raises(ValueError, match="SOURCE_HASH_CHANGED"):
        extract(source, "wrong", {"kind": "literal", "name": "DATA"})
