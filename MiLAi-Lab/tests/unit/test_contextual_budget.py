from pathlib import Path

import httpx
import pytest

from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget, RunLimits, Trace
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


def test_uncapped_usage_keeps_known_and_pending_charges_on_resume(tmp_path: Path) -> None:
    limits = RunLimits(generation_requests=None, generation_tokens=None, embedding_tokens=None)
    path = tmp_path / "budget.json"
    budget = RunBudget(limits, path)
    first = budget.reserve(
        "chat/completions", {"messages": [], "max_tokens": 1000},
        generation_input_tokens=2_000_000,
    )
    budget.finish(first, {"total_tokens": 37})
    budget.reserve("chat/completions", {"messages": [], "max_tokens": 1000})
    embedded = budget.reserve("embeddings", {"input": ["source"]})
    budget.finish(embedded, {"total_tokens": 3})

    restored = RunBudget(limits, path)
    assert restored.state["generation_requests"] == 2
    assert restored.state["generation"]["known_tokens"] == 37
    assert restored.state["generation"]["unknown_usage"] == 1
    assert restored.state["generation"]["charged_tokens"] > 1037
    assert restored.state["embedding"] == {
        "known_tokens": 3, "charged_tokens": 3, "unknown_usage": 0,
    }


def test_failed_requests_and_unknown_usage_survive_budget_resume(tmp_path: Path) -> None:
    limits = RunLimits(generation_requests=2, generation_tokens=2000)
    path = tmp_path / "budget.json"
    budget = RunBudget(limits, path)

    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with VLLMClient(
        VLLMConfig("http://fixture/v1", "fixture", max_tokens=10),
        transport=httpx.MockTransport(fail),
        budget=budget,
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            client.chat([{"role": "user", "content": "hello"}])
    restored = RunBudget(limits, path)
    assert restored.state["generation_requests"] == 1
    assert restored.state["generation"]["unknown_usage"] == 1
    assert restored.state["generation"]["charged_tokens"] > 10
    reservation = restored.reserve("chat/completions", {"messages": [], "max_tokens": 10})
    restored.finish(reservation, {"total_tokens": 4})
    with pytest.raises(BudgetExceeded):
        restored.reserve("chat/completions", {"messages": [], "max_tokens": 10})
    assert restored.state["generation"]["known_tokens"] == 4


def test_generation_holdback_prevents_ingestion_spending_judge_capacity(
    tmp_path: Path,
) -> None:
    limits = RunLimits(generation_requests=2, generation_tokens=1000)
    budget = RunBudget(limits, tmp_path / "budget.json")

    def complete(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [], "usage": {
                "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
            },
        })

    with VLLMClient(
        VLLMConfig("http://fixture/v1", "fixture", max_tokens=10),
        transport=httpx.MockTransport(complete), budget=budget,
    ) as client:
        client.generation_holdback_requests = 1
        client.generation_holdback_tokens = 100
        client.chat([{"role": "user", "content": "history"}])
        assert budget.state["generation_requests"] == 1
        assert budget.state["generation"]["charged_tokens"] == 15
        with pytest.raises(BudgetExceeded, match="holdback"):
            client.chat([{"role": "user", "content": "more history"}])
        assert budget.state["generation_requests"] == 1
        client.generation_holdback_requests = 0
        client.generation_holdback_tokens = 0
        client.chat([{"role": "user", "content": "judge"}])
    assert budget.state["generation_requests"] == 2
    assert budget.state["generation"]["known_tokens"] == 30


def test_generation_capacity_estimate_and_actual_usage_are_traced(tmp_path: Path) -> None:
    class Capacity:
        enable_thinking = False

        def check(self, messages, output_tokens, tools):
            assert messages == [{"role": "user", "content": "question"}]
            assert output_tokens == 10 and tools is None
            return {
                "prompt_tokens": 15, "output_reserve_tokens": 10,
                "identity": {"model": "local-host", "capacity_policy_sha256": "fixed"},
            }

    trace = Trace(tmp_path / "trace.jsonl", "answer")
    budget = RunBudget(
        RunLimits(generation_requests=1, generation_tokens=50), tmp_path / "budget.json",
    )
    with VLLMClient(
        VLLMConfig("http://fixture/v1", "fixture", max_tokens=10), emit=trace,
        budget=budget,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "choices": [], "usage": {
                "prompt_tokens": 17, "completion_tokens": 3, "total_tokens": 20,
            },
        })),
    ) as client:
        client.capacity = Capacity()  # type: ignore[assignment]
        client.chat([{"role": "user", "content": "question"}])
    usage = trace.usage[0]
    assert usage["capacity"]["prompt_tokens"] == 15
    assert usage["capacity_comparison"] == {
        "actual_prompt_tokens": 17,
        "actual_completion_tokens": 3,
        "prompt_estimate_error_tokens": 2,
        "output_reserve_minus_actual_tokens": 7,
    }
    assert usage["usage"]["prompt_tokens"] == 17
    assert budget.state["generation"]["known_tokens"] == 20
