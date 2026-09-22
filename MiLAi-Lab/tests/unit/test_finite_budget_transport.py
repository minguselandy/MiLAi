import json
import sys
import time
from pathlib import Path

import httpx
import pytest

from milai_lab.methods.finite_research_budget import BudgetStop, FiniteResearchBudget

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from finite_budget_transport import FiniteBudgetTransport
from reasoningbank_provider import EmbeddingProvider, NativeProvider

SHA = "a" * 64


def budget_at(path):
    return FiniteResearchBudget(path, manifest_sha256=SHA)


def native(root, budget, handler):
    provider = NativeProvider(
        root,
        max_tokens=3_000_000,
        max_requests=400,
        deadline=time.monotonic() + 14400,
        batch_budget=budget,
        transport=httpx.MockTransport(handler),
    )
    provider.context = 65536
    return provider


def respond(request):
    if request.url.path == "/tokenize":
        return httpx.Response(200, json={"count": 12})
    if request.url.path == "/v1/models":
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "Qwen3.6-35B-A3B-FP8",
                        "max_model_len": 65536,
                    }
                ]
            },
        )
    if request.url.path == "/v1/embeddings":
        return httpx.Response(
            200,
            json={
                "model": "bge-m3",
                "data": [{"index": 0, "embedding": [0.1] * 1024}],
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            },
        )
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        },
    )


def test_actual_provider_paths_share_global_accounting_and_preserve_m1(tmp_path):
    budget = budget_at(tmp_path / "budget.sqlite")
    seen = []

    def handler(request):
        assert budget.status()["total_requests"] == len(seen) + 1  # durable before send
        seen.append(request)
        return respond(request)

    provider = native(tmp_path / "text", budget, handler)
    provider.verify()
    provider.generate_message("task", [{"role": "user", "content": "x"}])
    provider.generate_message(
        "task",
        [{"role": "user", "content": "x"}],
        role="extract",
        output_tokens=2048,
        temperature=1.0,
    )
    embedding = EmbeddingProvider(
        tmp_path / "embedding",
        batch_budget=budget,
        token_upper_bound=lambda texts: 100,
        transport=httpx.MockTransport(handler),
    )
    assert len(embedding.embed("task", ["x"])[0]) == 1024
    state = budget.status()
    assert state["total_requests"] == 6  # model-info + two tokenize/generate pairs + embedding
    assert state["requests_by_purpose"] == {
        "model_info": 1,
        "tokenize": 2,
        "generation": 2,
        "embedding": 1,
    }
    assert state["kinds"]["text"]["reported_tokens"] == 40
    assert state["kinds"]["embedding"]["reported_tokens"] == 5
    body = json.loads(seen[2].content)
    assert (body["temperature"], body["top_p"], body["seed"], body["max_tokens"]) == (
        0,
        1,
        213,
        4096,
    )
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    provider.close()
    embedding.close()
    budget.close()


@pytest.mark.parametrize("failure", ["http", "timeout", "missing_usage", "negative_usage"])
def test_failed_generation_retains_bound_after_provider_and_ledger_restart(tmp_path, failure):
    path = tmp_path / "budget.sqlite"
    budget = budget_at(path)
    dispatched = []

    def handler(request):
        dispatched.append(request)
        if request.url.path == "/tokenize":
            return respond(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("controlled fixture", request=request)
        if failure == "negative_usage":
            return httpx.Response(
                200,
                json={
                    "usage": {
                        "prompt_tokens": -1,
                        "completion_tokens": 0,
                        "total_tokens": -1,
                    }
                },
            )
        return httpx.Response(503 if failure == "http" else 200, json={})

    provider = native(tmp_path / "first", budget, handler)
    with pytest.raises((BudgetStop, httpx.ReadTimeout)):
        provider.generate_message("task", [])
    assert len(dispatched) == 2
    if failure != "timeout":
        failure_receipt = json.loads((tmp_path / "first/batch-000002-http.json").read_text())
        assert failure_receipt["batch_request_id"] == 2
        assert failure_receipt["status_code"] == (503 if failure == "http" else 200)
    assert budget.status()["kinds"]["text"]["unknown_token_upper_bound"] == 4108
    provider.close()
    started = budget.status()["started_at_unix"]
    budget.close()
    budget = budget_at(path)
    provider = native(tmp_path / "retry", budget, respond)
    provider.generate_message("task", [])
    assert budget.status()["total_requests"] == 4
    assert budget.status()["started_at_unix"] == started
    assert budget.status()["kinds"]["text"]["charged_tokens"] == 4128
    provider.close()
    budget.close()


def test_deadline_prevents_transport_and_clips_inflight_timeout(tmp_path, monkeypatch):
    budget = budget_at(tmp_path / "budget.sqlite")
    sent = []

    def handler(request):
        sent.append(request)
        assert 0 < request.extensions["timeout"]["read"] <= 2
        return respond(request)

    provider = native(tmp_path / "text", budget, respond)
    provider.verify()
    deadline = budget.status()["deadline_unix"]
    provider.close()
    provider = native(tmp_path / "next", budget, handler)
    monkeypatch.setattr(budget, "_now", lambda: deadline - 2)
    provider.generate_message("task", [])
    monkeypatch.setattr(budget, "_now", lambda: deadline)
    with pytest.raises(BudgetStop, match="WALL_TIME"):
        provider.generate_message("task", [])
    assert len(sent) == 2
    provider.close()
    budget.close()


@pytest.mark.parametrize(
    "url,body",
    [
        ("http://127.0.0.1:9999/v1/chat/completions", {}),
        ("http://127.0.0.1:7860/v1/rerank", {"model": "Qwen3.6-35B-A3B-FP8"}),
        ("http://127.0.0.1:7860/v1/chat/completions", {"model": "other-solver"}),
    ],
)
def test_unapproved_model_endpoint_or_route_cannot_dispatch(tmp_path, url, body):
    budget = budget_at(tmp_path / "budget.sqlite")
    transport = FiniteBudgetTransport(
        budget,
        kind="text",
        inner=httpx.MockTransport(lambda request: pytest.fail("unapproved dispatch")),
    )
    with httpx.Client(transport=transport) as client, pytest.raises(BudgetStop):
        client.post(url, json=body)
    assert budget.status()["total_requests"] == 0
    budget.close()


def test_unknown_embedding_bound_is_rejected_without_request(tmp_path):
    budget = budget_at(tmp_path / "budget.sqlite")
    with pytest.raises(ValueError, match="VERIFIED_EMBEDDING_TOKEN_BOUND_REQUIRED"):
        EmbeddingProvider(tmp_path / "embedding", batch_budget=budget)
    assert budget.status()["total_requests"] == 0
    budget.close()


def test_changed_m1_temperature_never_reaches_generation(tmp_path):
    budget = budget_at(tmp_path / "budget.sqlite")
    sent = []

    def handler(request):
        sent.append(request.url.path)
        return respond(request)

    provider = native(tmp_path / "text", budget, handler)
    with pytest.raises(BudgetStop, match="M1_PROFILE_CHANGED"):
        provider.generate_message("task", [], temperature=0.2)
    assert sent == ["/tokenize"]
    assert budget.status()["total_requests"] == 1
    provider.close()
    budget.close()
