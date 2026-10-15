"""An optional ranking endpoint shares accounting without replacing the Reader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import edit_benchmarks
from milai_lab.runners.edit_benchmarks import BenchmarkRun, ReadDeliveryIncomplete
from milai_lab.runners.evidence_replay import _cost


def source(index: int, size: int) -> dict[str, Any]:
    return {"kind": "original_source", "id": f"source-{index}", "date": "2030-01-01",
            "text": json.dumps([{"role": "user", "content": f"SOURCE_{index}:" + "x" * size}]),
            "source_ranges": []}


def execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str = "memsifter",
) -> tuple[BenchmarkRun, list[dict[str, Any]], list[str], list[VLLMClient]]:
    loaded, sent, clients = [], [], []

    class Tokenizer:
        def __init__(self, divisor: int) -> None:
            self.divisor = divisor

        def apply_chat_template(self, messages: Any, **kwargs: Any) -> list[int]:
            assert kwargs["enable_thinking"] is (self.divisor == 1)
            return [0] * (len(json.dumps(messages, ensure_ascii=False)) // self.divisor)

    def load_tokenizer(path: str, **kwargs: Any) -> Tokenizer:
        assert kwargs == {"local_files_only": True}
        loaded.append(path)
        return Tokenizer(4 if path == "rank-tokenizer" else 1)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent.append(payload)
        ranker = request.url.host == "rank.test"
        assert payload["model"] == ("MemSifter-fixture" if ranker else "main-fixture")
        if ranker:
            assert payload["max_tokens"] == 2048 and payload["temperature"] == 0.6
            assert payload["chat_template_kwargs"] == {"enable_thinking": False}
            if mode == "memsifter":
                assert "response_format" not in payload
                content = "<think>Order sources.</think><ranking>1,0</ranking>"
            else:
                assert payload["response_format"] == {"type": "json_object"}
                content = '{"rank_order":[1,0]}'
            usage = {"prompt_tokens": 333, "completion_tokens": 44, "total_tokens": 377}
        else:
            assert payload["max_tokens"] == 100
            assert payload["chat_template_kwargs"] == {"enable_thinking": True}
            content = ('{"item_indices":[1],"done":true}'
                       if payload.get("response_format") else "Actual source answer.")
            usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        return httpx.Response(200, json={
            "model": payload["model"], "usage": usage,
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        })

    def make_client(config: VLLMConfig, *, budget: RunBudget) -> VLLMClient:
        client = VLLMClient(config, budget=budget, transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    monkeypatch.setattr(edit_benchmarks.AutoTokenizer, "from_pretrained", load_tokenizer)
    monkeypatch.setattr(edit_benchmarks, "VLLMClient", make_client)
    budget_path = tmp_path / "budget.json"
    write_json(budget_path, RunBudget(RunLimits(), budget_path).state)
    settings = {
        "experiment_name": "separate-ranker", "interface_version": "I2",
        "budget_path": str(budget_path), "tokenizer_path": "main-tokenizer",
        "context_tokens": 30612, "memory_view_mode": "direct",
        "reader_projection": "semantic_units_v1", "source_access": "independent_v1",
        "source_top_k": 20, "semantic_top_k": 10, "reader_ranking": mode,
        "model": {"base_url": "http://main.test/v1/", "model": "main-fixture",
                  "max_tokens": 100, "enable_thinking": True, "max_calls": 6},
        "ranker": {"tokenizer_path": "rank-tokenizer", "context_tokens": 20000,
                   "model": {"base_url": "http://rank.test/v1/", "model": "MemSifter-fixture",
                             "temperature": 0.6, "enable_thinking": False}},
    }
    return BenchmarkRun(settings, tmp_path / "run", phase="predict"), sent, loaded, clients


@pytest.mark.parametrize("mode", ["memsifter", "llm_probe"])
def test_explicit_ranker_uses_own_transport_capacity_and_shared_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    run, sent, loaded, clients = execution(tmp_path, monkeypatch, mode=mode)
    pool = [source(index, 18000) for index in range(2)]
    write_json(run.root / "pool.json", {"materials": pool})
    try:
        assert loaded == ["main-tokenizer"] and len(clients) == 1
        assert run.answer_material("Which?", "", "qa", pool, snapshot_id="pool.json")[0] == (
            "Actual source answer.")
        assert loaded == ["main-tokenizer", "rank-tokenizer"] and len(clients) == 2
        assert clients[0].budget is clients[1].budget is run.budget
        assert [row["model"] for row in sent] == ["MemSifter-fixture", *["main-fixture"] * 3]
        main_payloads = [json.loads(row["messages"][1]["content"]) for row in sent[1:]]
        assert [row["memory_item_indices"] for row in main_payloads] == [[1], [0], [1]]
        rank = read_json(run.root / "http/qa/ranking.json")
        assert rank["model"] == "MemSifter-fixture" and rank["ranking_calls"] == 1
        assert rank["rank_order"] == [1, 0] and rank["ranking_input_token_limit"] == 17440
        request = read_json(run.root / "http/qa/ranking/batch-0/request.json")
        assert request["provider"] == "ranker" and request["model"] == "MemSifter-fixture"
        assert request["context_tokens"] == 20000 and request["max_tokens"] == 2048
        assert request["prompt_tokens"] == len(json.dumps(request["messages"],
                                                          ensure_ascii=False)) // 4
        assert request["prompt_tokens"] < 17440
        assert run.budget.state["generation_requests"] == 4
        assert run.budget.state["generation"]["known_tokens"] == 737
        cost = _cost(run.root / "http/qa", 0.0)
        assert cost["models"]["MemSifter-fixture"] == {
            "calls": 1, "input_tokens": 333, "output_tokens": 44}
        assert cost["models"]["main-fixture"]["calls"] == 3
        assert cost["stages"]["ranking"]["MemSifter-fixture"]["calls"] == 1
        run.answer_material("Which?", "", "qa", pool, snapshot_id="pool.json")
        assert len(sent) == 4 and run.budget.state["generation_requests"] == 4
        assert read_json(run.root / "pool.json")["materials"] == pool
    finally:
        run.close()
    assert all(client._client.is_closed for client in clients)


def test_complete_pool_skip_does_not_load_or_connect_unused_ranker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, sent, loaded, clients = execution(tmp_path, monkeypatch)
    pool = [source(0, 20)]
    write_json(run.root / "pool.json", {"materials": pool})
    try:
        run.answer_material("Which?", "", "qa", pool, snapshot_id="pool.json")
        assert loaded == ["main-tokenizer"] and len(clients) == 1
        assert run.ranker_client is None and run.ranker_tokenizer is None
        assert [row["model"] for row in sent] == ["main-fixture"]
        assert read_json(run.root / "http/qa/ranking.json")["ranking_skipped"] is True
        assert run.budget.state["generation_requests"] == 1
    finally:
        run.close()


def test_unavailable_whole_rank_material_does_not_open_rank_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, sent, loaded, clients = execution(tmp_path, monkeypatch)
    run.settings["ranker"]["context_tokens"] = 3500
    try:
        with pytest.raises(ReadDeliveryIncomplete, match="whole_ranking_material_unavailable"):
            run._rank_materials("Which?", "", "qa", [source(index, 18000)
                                                     for index in range(2)], "pool.json")
        assert loaded == ["main-tokenizer", "rank-tokenizer"]
        assert run.ranker_client is None and len(clients) == 1 and sent == []
        assert run.budget.state["generation_requests"] == 0
    finally:
        run.close()


def test_memsifter_cannot_silently_use_the_main_reader_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, sent, loaded, clients = execution(tmp_path, monkeypatch)
    run.settings.pop("ranker")
    try:
        with pytest.raises(ValueError, match="checkpoint is not configured"):
            run._rank_materials("Which?", "", "qa", [source(0, 20)], "pool.json")
        assert sent == [] and loaded == ["main-tokenizer"] and len(clients) == 1
    finally:
        run.close()
