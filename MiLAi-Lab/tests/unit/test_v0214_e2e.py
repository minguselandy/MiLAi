"""Runner transport receipts are independent of successful usage settlement."""

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from milai_lab.methods.host_acquisition import AcquisitionHelper, Binding

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from run_v0213_decomposition import SCHEMA
from run_v0214_e2e import cold, reconcile_presentation
from v0214_delivery import Readiness, check_host_delivery, readiness_schema
from v0214_source_binding import FileSources


@pytest.mark.parametrize("response_observed", [False, True])
def test_unknown_usage_does_not_invent_a_send(tmp_path, response_observed):
    (tmp_path / "source-01.txt").write_text("Current authorized source.")
    scope = Binding("p", "j", "t")
    helper = AcquisitionHelper(FileSources({scope: tmp_path}))

    async def acquire():
        ref = (await helper.resolve_sources(scope))[0]
        return await helper.read_source(scope, ref)

    page = asyncio.run(acquire())
    (tmp_path / "provider-ledger.jsonl").write_text(json.dumps({
        "event": "RESERVED", "request_id": "unknown-usage"}) + "\n")
    (tmp_path / "unknown-usage-request.json").write_text(json.dumps({"messages": [{
        "role": "user", "content": json.dumps({"source_pages": [asdict(page)]})}]}))
    if response_observed:
        (tmp_path / "unknown-usage-http.json").write_text(json.dumps({
            "status_code": 200, "body": '{"usage": null}'}))
    receipts = reconcile_presentation(tmp_path, helper)
    assert receipts[0]["transmission"] == (
        "HTTP_RESPONSE_OBSERVED" if response_observed else "UNKNOWN_AFTER_RESERVATION")
    assert helper.presented == ([('unknown-usage', page.request_id)] if response_observed else [])
    assert reconcile_presentation(tmp_path, helper) == receipts


def test_disabled_model_transport_stops_before_runtime_and_provider(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "config": {"model_transport_enabled": False}}))
    with pytest.raises(ValueError, match="MODEL_TRANSPORT_DISABLED"):
        cold(tmp_path, tmp_path / "absent-runtime", "neutral", "H", 0)
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("status", ["NEEDS_CLARIFICATION", "BLOCKED"])
def test_public_assessment_and_no_call_delivery_agree(status):
    tools = [{"name": "Draft", "parameters": {"type": "object", "properties": {
        "value": {"type": "string"}}, "required": ["value"]}}]
    candidate = {"assessment": {"basis": "An input is unresolved.", "readiness": status,
        "requested_business_operations": 1}, "delivery": {
        "action": "abstain", "answer": "Which value should I use?", "calls": []}}
    assert Draft202012Validator(readiness_schema(tools, SCHEMA)).is_valid(candidate)
    check = check_host_delivery(candidate, tools)
    assert check.structurally_valid and check.readiness == Readiness(status)


def test_assessment_cannot_silently_repair_conflicting_or_duplicate_plan():
    tools = [{"name": "Draft", "parameters": {"type": "object", "properties": {
        "value": {"type": "string"}}, "required": ["value"]}}]
    call = {"name": "Draft", "arguments": {"value": "x"}}
    candidate = {"assessment": {"basis": "One requested operation.", "readiness": "READY",
        "requested_business_operations": 1}, "delivery": {
        "action": "business", "answer": "Pending draft.", "calls": [call, call]}}
    check = check_host_delivery(candidate, tools)
    assert not check.structurally_valid
    assert check.complete_plan == [call, call]
    assert "REQUESTED_OPERATION_COUNT_CONFLICT" in check.errors
    candidate["assessment"]["readiness"] = "NEEDS_CLARIFICATION"
    assert "ASSESSMENT_ACTION_CONFLICT" in check_host_delivery(candidate, tools).errors
    candidate["assessment"]["readiness"] = "READY"
    candidate["assessment"]["requested_business_operations"] = True
    candidate["delivery"]["calls"] = [call]
    assert "REQUESTED_OPERATION_COUNT_TYPE" in check_host_delivery(candidate, tools).errors
