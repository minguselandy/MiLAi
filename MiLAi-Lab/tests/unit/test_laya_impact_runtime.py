"""Actual HTTP boundary, shared accounting and durable failure evidence."""
import json

import httpx
import pytest

from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.runners.laya_impact import impact_model_call

SCHEMA = {"properties": {"roots": {"items": {"enum": ["u1", "u2"]}}}}
MESSAGES = [{"role": "user", "content": json.dumps({"observed_date": "2026-10-16",
             "delivery": {"current_event": "A changed; B unaffected"}})}]


def setup_call(tmp_path, *, label="direct_root", truncated=False):
    requests, generated, admitted = [], [], []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "milai-impact-ce-v1", "answers": {
            "unit_0": {"choice": label}, "unit_1": {"choice": "other"}},
            "usage": {"input_tokens": 190, "output_tokens": 0, "truncated": truncated}})

    def original(stage, *_):
        generated.append(stage)
        return {"writer": True}

    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    wrapped = impact_model_call(original, {"laya_impact": {
        "model": "milai-impact-ce-v1",
        "http_client": httpx.Client(transport=httpx.MockTransport(handler))}},
        budget=budget, root=tmp_path / "http", admit=lambda: admitted.append(True))
    return wrapped, budget, requests, generated, admitted


def test_served_checkpoint_and_replay_share_original_budget(tmp_path):
    call, budget, requests, generated, admitted = setup_call(tmp_path)
    selection = call("impact:work-1", MESSAGES, SCHEMA)
    assert selection == {"roots": ["u1"], "preserve": []}
    assert call("impact:work-1", MESSAGES, SCHEMA) == selection
    assert call("edit", MESSAGES, {}) == {"writer": True}
    assert len(requests) == len(admitted) == 1
    assert requests[0]["model"] == "milai-impact-ce-v1"
    assert generated == ["edit"]
    assert budget.state["generation_requests"] == 1
    assert budget.state["generation"]["known_tokens"] == 190
    assert budget.state["generation"]["unknown_usage"] == 0
    assert budget.state["compute"]["laya_impact"]["questions"] == 2
    assert list((tmp_path / "http").rglob("selection.json"))


@pytest.mark.parametrize("label,truncated", [("invalid", False), ("direct_root", True)])
def test_semantic_failure_keeps_actual_response_and_cost(tmp_path, label, truncated):
    call, budget, requests, generated, _ = setup_call(tmp_path, label=label, truncated=truncated)
    for _ in range(2):
        with pytest.raises(ValueError):
            call("impact", MESSAGES, SCHEMA)
    assert len(requests) == 1
    assert not generated
    assert budget.state["generation"]["known_tokens"] == 190
    assert list((tmp_path / "http").rglob("response.json"))
    assert not list((tmp_path / "http").rglob("selection.json"))


def test_timeout_remains_unknown_and_does_not_repeat(tmp_path):
    requests = []

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("unknown", request=request)

    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    call = impact_model_call(lambda *_: {}, {"laya_impact": {
        "http_client": httpx.Client(transport=httpx.MockTransport(timeout))}},
        budget=budget, root=tmp_path / "http")
    with pytest.raises(httpx.ReadTimeout):
        call("impact", MESSAGES, SCHEMA)
    with pytest.raises(RuntimeError, match="Unconfirmed"):
        call("impact", MESSAGES, SCHEMA)
    assert len(requests) == 1
    assert budget.state["generation"]["unknown_usage"] == 1


def test_reusing_stage_with_different_input_is_not_stale_success(tmp_path):
    call, _, requests, _, _ = setup_call(tmp_path)
    call("impact", MESSAGES, SCHEMA)
    messages = [{"role": "user", "content": json.dumps({"observed_date": "2026-10-17",
                 "delivery": {"current_event": "B changed"}})}]
    with pytest.raises(ValueError, match="input changed"):
        call("impact", messages, SCHEMA)
    assert len(requests) == 1


def test_typed_provider_uses_serial_owner_and_explicit_domain(tmp_path):
    from milai_lab.harness.artifact_io import write_json
    from milai_lab.harness.contextual_artifacts import http_budget_scope
    from milai_lab.harness.http_ownership import HttpOwnershipError

    budget_path = tmp_path / "budget.json"
    initial = RunBudget(RunLimits(), budget_path)
    write_json(budget_path, initial.state)
    config = {"base_url": "http://laya.invalid", "model": "milai-impact-ce-v1",
              "max_len": 2048, "head_max_len": 256, "timeout_seconds": 120.0}
    settings = {"budget_path": str(budget_path),
        "http_ownership_profile": "serialized_ledger_owner_v1",
        "http_ownership_domain": {"deployment_id": "local-test", "clients": [config]}}
    seen = []

    def response(request):
        seen.append(request)
        return httpx.Response(200, json={"answers": {
            "unit_0": {"choice": "direct_root"}, "unit_1": {"choice": "other"}},
            "usage": {"input_tokens": 190, "output_tokens": 0}})

    with http_budget_scope(settings) as budget:
        assert budget is not None
        client = httpx.Client(transport=httpx.MockTransport(response))
        call = impact_model_call(lambda *_: {}, {"laya_impact": {
            **config, "http_client": client}}, budget=budget, root=tmp_path / "http")
        assert call("impact", MESSAGES, SCHEMA)["roots"] == ["u1"]
        assert budget.state["generation"]["known_tokens"] == 190
        assert budget.state["compute"]["laya_impact"]["questions"] == 2
        with pytest.raises(HttpOwnershipError, match="CLIENT_NOT_ALLOWED"):
            denied = impact_model_call(lambda *_: {}, {"laya_impact": {
                **config, "model": "another-checkpoint"}}, budget=budget, root=tmp_path / "bad")
            denied("impact", MESSAGES, SCHEMA)
    assert len(seen) == 1
