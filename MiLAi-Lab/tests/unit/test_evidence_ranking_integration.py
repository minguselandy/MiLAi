"""Real Reader wiring with fabricated sources and a local provider double."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.edit_benchmarks import BenchmarkRun, ReadDeliveryIncomplete


def original(index: int, body_size: int = 3000) -> dict[str, Any]:
    return {
        "kind": "original_source", "id": f"source-{index}", "date": "2030-01-01",
        "text": json.dumps([{"role": "user", "content": f"VISIBLE_{index}:" + "x" * body_size,
                            "occurred_at": "2030-01-01"}]),
        "source_ranges": [{"source_ref": f"source-{index}", "source_revision": 1,
                           "start": 0, "end": body_size}],
        "visibility": "visible", "body_delivered": True,
    }


def reader(tmp_path: Path, *, max_calls: int = 12) -> BenchmarkRun:
    class LiteralTokenizer:
        def apply_chat_template(self, messages: Any, **kwargs: Any) -> list[int]:
            assert kwargs["enable_thinking"] is True
            return [0] * len(json.dumps(messages, ensure_ascii=False))

    execution = BenchmarkRun.__new__(BenchmarkRun)
    execution.root = tmp_path
    execution.settings = {
        "memory_view_mode": "direct", "reader_projection": "semantic_units_v1",
        "source_access": "independent_v1", "reader_ranking": "llm_probe",
        "context_tokens": 9000,
        "model": {"model": "fixture-model", "max_tokens": 100, "enable_thinking": True},
        "interface_version": "I2",
    }
    execution.tokenizer = LiteralTokenizer()
    execution.client = SimpleNamespace(config=SimpleNamespace(max_calls=max_calls))
    return execution


def response(content: str) -> dict[str, Any]:
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


@pytest.mark.parametrize("count,batch_orders,order", [
    (3, [[1, 0], [2]], [1, 2, 0]),
    (4, [[1, 0], [3, 2]], [1, 3, 0, 2]),
])
def test_batches_map_local_nominations_to_canonical_positions_and_cache(
    tmp_path: Path, count: int, batch_orders: list[list[int]], order: list[int],
) -> None:
    execution = reader(tmp_path)
    materials = [original(index) for index in range(count)]
    before = copy.deepcopy(materials)
    batches = []

    def chat(messages: Any, **kwargs: Any) -> dict[str, Any]:
        assert execution.input_tokens(messages) <= 8388
        payload = json.loads(messages[1]["content"])
        local = payload["materials"]
        assert [row["item_index"] for row in local] == list(range(len(local)))
        batches.append([row["material"]["id"] for row in local])
        return response(json.dumps({"rank_order": list(reversed(range(len(local))))}))

    execution.client.chat = chat
    assert execution._rank_materials("Which?", "2030-01-02", "qa", materials,
                                     "pool.json") == order
    assert batches == [[f"source-{index}" for index in sorted(batch)]
                       for batch in batch_orders if len(batch) > 1]
    saved = read_json(tmp_path / "http/qa/ranking.json")
    assert saved["batch_orders"] == batch_orders
    assert saved["ranking_calls"] == len(batches) and saved["ranking_skipped"] is False
    assert len(saved["request_paths"]) == len(batches)
    assert execution._rank_materials("Which?", "2030-01-02", "qa", materials,
                                     "pool.json") == order
    assert len(batches) == sum(len(batch) > 1 for batch in batch_orders) and materials == before


def test_complete_fitting_pool_skips_ranking_http(tmp_path: Path) -> None:
    execution = reader(tmp_path)

    def chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
        pytest.fail("A complete fitting pool must not invoke the ranking model")

    execution.client.chat = chat
    assert execution._rank_materials("Which?", "", "qa", [original(0, 20)],
                                     "pool.json") == [0]
    saved = read_json(tmp_path / "http/qa/ranking.json")
    assert saved["ranking_skipped"] is True and saved["ranking_calls"] == 0


def test_ranking_and_reader_only_receive_current_visible_sources(tmp_path: Path) -> None:
    execution = reader(tmp_path)
    execution.settings["context_tokens"] = 15000
    materials = [original(index, 6000) for index in range(4)]
    materials[0]["text"] = json.dumps([{"role": "user", "content": "REVOKED_SECRET"}])
    before = copy.deepcopy(materials)
    write_json(tmp_path / "pool.json", {"materials": materials})
    calls = []

    def live(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**item, "text": "[]", "source_ranges": [], "visibility": "unavailable",
                 "body_delivered": False} if item["id"] == "source-0" else copy.deepcopy(item)
                for item in items]

    visible = live(materials)

    def chat(messages: Any, response_format: Any, **kwargs: Any) -> dict[str, Any]:
        assert "REVOKED_SECRET" not in json.dumps(messages)
        assert execution.input_tokens(messages) <= 14388
        payload = json.loads(messages[1]["content"])
        calls.append(payload)
        if "materials" in payload:
            return response(json.dumps({"rank_order": list(reversed(range(
                len(payload["materials"]))))}))
        indices = payload["memory_item_indices"]
        for material, index in zip(payload["memories"], indices, strict=True):
            assert material["id"] == visible[index]["id"]
            assert material["turns"] == json.loads(visible[index]["text"])
            assert material["visibility"] == visible[index]["visibility"]
        if response_format is not None:
            return response('{"item_indices":[2],"done":true}')
        assert indices == [2]
        return response("VISIBLE_2")

    execution.client.chat = chat
    answer, _ = execution.answer_material("Which?", "", "qa", materials,
                                          snapshot_id="pool.json", material_reader=live)
    assert answer == "VISIBLE_2"
    assert any("materials" in call for call in calls)
    assert len(calls) <= execution.client.config.max_calls
    count = len(calls)
    assert execution.answer_material("Which?", "", "qa", materials,
                                     snapshot_id="pool.json", material_reader=live)[0] == answer
    assert len(calls) == count
    assert materials == before and read_json(tmp_path / "pool.json")["materials"] == before


def test_rank_batches_reserve_reader_and_answer_calls_before_dispatch(tmp_path: Path) -> None:
    execution = reader(tmp_path, max_calls=3)
    calls = []

    def chat(messages: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(messages)
        return response('{"rank_order":[1,0]}')

    execution.client.chat = chat
    with pytest.raises(ReadDeliveryIncomplete):
        execution._rank_materials("Which?", "", "qa", [original(index) for index in range(4)],
                                  "pool.json")
    assert calls == []
