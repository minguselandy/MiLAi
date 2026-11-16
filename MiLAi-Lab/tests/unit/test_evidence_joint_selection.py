"""J1 lets the existing Reader select source bodies and state together."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def test_joint_pool_delivers_excluded_semantic_view_with_its_actual_source(tmp_path: Path) -> None:
    class LiteralTokenizer:
        def apply_chat_template(self, messages: Any, **kwargs: Any) -> list[int]:
            return [0] * len(json.dumps(messages, ensure_ascii=False))

    execution = BenchmarkRun.__new__(BenchmarkRun)
    execution.root = tmp_path / "run"
    execution.settings = {
        "memory_view_mode": "direct", "reader_projection": "semantic_units_v1",
        "source_access": "independent_v1", "reader_ranking": "native",
        "context_tokens": 30000, "model": {"max_tokens": 100, "enable_thinking": True},
        "interface_version": "I2",
    }
    execution.tokenizer = LiteralTokenizer()
    execution.client = SimpleNamespace(config=SimpleNamespace(max_calls=6))
    limit = 29388
    question, date = "What reminder applies during the June travel week?", "2030-06-10"
    snapshot_id = "native/joint/retrieval.json"
    source_text = "SOURCE_JUNE: In June remind me twice weekly, once during the travel week."
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("joint", "owner"), "owner", tmp_path / "lock",
                                functional_contract="functional_v1")
        independent = [service.capture_user(f"session-{index}", "turn:0",
                                            f"BACKGROUND_{index}:" + "x" * 15000)
                       for index in range(2)]
        source = service.capture_user("conditions", "turn:0", source_text)
        span = service.source_fragment_range(source["source_ref"], 0, len(source_text))
        native = service.search_sources("BACKGROUND", source_refs=[
            item["source_ref"] for item in independent])
        semantic = [{"record_id": "fixture-state", "revision": 1, "scope": {},
                     "content": "STATE_JUNE: The travel-week exception overrides June's default.",
                     "revision_evidence": [span]}]
        original_native, original_semantic = copy.deepcopy(native), copy.deepcopy(semantic)

        # The unchanged default/explicit S2 path cannot append the interpretation
        # after the whole original pool already exceeds the complete input limit.
        defaults = execution._source_first_materials(
            service, question, date, native, semantic, snapshot_id=snapshot_id,
        )
        execution.settings["evidence_variant"] = "S2"
        s2 = execution._source_first_materials(
            service, question, date, native, semantic, snapshot_id=snapshot_id,
        )
        assert s2 == defaults and native["material_assembly"]["semantic_materials"] == 0

        execution.settings["evidence_variant"] = "J1"
        joint = execution._source_first_materials(
            service, question, date, native, semantic, snapshot_id=snapshot_id,
        )
        assert joint[:len(s2)] == s2
        assert [row["kind"] for row in joint] == [
            "original_source", "original_source", "original_source", "semantic_view"]
        assembly = native["material_assembly"]
        assert assembly["material_origins"] == [
            "independent_original", "independent_original", "linked_source", "semantic_view"]
        assert assembly["semantic_materials"] == 1 and assembly["input_token_limit"] == limit
        assert assembly["policy"] == "joint_original_and_semantic_candidates"
        assert native["source_materials"] == original_native["source_materials"]
        assert semantic == original_semantic
        assert execution.input_tokens(execution._material_messages(
            question, date, joint, snapshot_id=snapshot_id,
            item_indices=list(range(len(joint))),
        )) > limit
        write_json(execution.root / snapshot_id, {"materials": joint})
        requests = []

        def chat(messages: Any, response_format: Any, **kwargs: Any) -> dict[str, Any]:
            # Includes the actual Reader instructions, page schema and metadata,
            # not just the selected material body lengths.
            assert execution.input_tokens(messages) <= limit
            payload = json.loads(messages[1]["content"])
            requests.append(payload)
            if response_format is not None:
                content = '{"item_indices":[2,3],"done":true}'
            else:
                assert payload["memory_item_indices"] == [2, 3]
                assert [row["kind"] for row in payload["memories"]] == [
                    "original_source", "semantic_view"]
                assert "SOURCE_JUNE" in repr(payload) and "STATE_JUNE" in repr(payload)
                assert "BACKGROUND_" not in repr(payload)
                content = "Once during the travel week."
            return {"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}}

        execution.client.chat = chat
        answer, _ = execution.answer_material(question, date, "joint", joint,
                                              snapshot_id=snapshot_id)
        assert answer == "Once during the travel week."
        assert len(requests) <= execution.client.config.max_calls
        view = read_json(execution.root / "http/joint/memory-view.json")
        assert [ref["item_index"] for ref in view["resident_refs"]] == [2, 3]
        assert view["capacity_continuation"]["final_body_delivered"]
        assert {ref["item_index"] for ref in view["capacity_continuation"][
            "delivered_page_refs"]} == {0, 1, 2, 3}
        assert read_json(execution.root / snapshot_id)["materials"] == joint
        assert not service.records()  # This is a Reader mechanism test, not model formation.


@pytest.mark.parametrize("release_capacity", [False, True])
def test_joint_budget_admits_whole_nominations_without_empty_repair_calls(
    tmp_path: Path, release_capacity: bool,
) -> None:
    """Repeated oversized nominations were a real unsent-final failure in J1's pilot."""
    from milai_lab.runners.edit_benchmarks import ReadDeliveryIncomplete

    class LiteralTokenizer:
        def apply_chat_template(self, messages: Any, **kwargs: Any) -> list[int]:
            return [0] * len(json.dumps(messages))

    memories = [{"kind": "original_source", "id": f"source-{index}",
                 "session_id": f"session-{index}", "date": "2030-01-01",
                 "turn_range": [0, 1], "text": json.dumps([
                     {"role": "user", "content": f"ORIGINAL_{index} " + "x" * 18000}])}
                for index in range(2)]
    memories.append({"kind": "semantic_view", "record_id": "state", "revision": 1,
                     "content": "The first report states a decision, not completed retirement.",
                     "scope": {}, "revision_evidence": []})
    snapshot_id = "native/joint/retrieval.json"
    policies = (["budgeted_nominations_v2"] if release_capacity
                else [None, "budgeted_nominations_v2"])
    for policy in policies:
        execution = BenchmarkRun.__new__(BenchmarkRun)
        execution.root = tmp_path / (policy or "original")
        execution.settings = {
            "evidence_variant": "J1", "joint_selection": policy,
            "memory_view_mode": "direct", "context_tokens": 30000,
            "model": {"max_tokens": 100, "enable_thinking": True}, "interface_version": "I2",
        }
        execution.tokenizer = LiteralTokenizer()
        execution.client = SimpleNamespace(config=SimpleNamespace(max_calls=5))
        write_json(execution.root / snapshot_id, {"materials": memories})
        pages: list[list[int]] = []

        def chat(
            messages: Any, response_format: Any, *, execution: BenchmarkRun = execution,
            pages: list[list[int]] = pages, **kwargs: Any,
        ) -> dict[str, Any]:
            payload = json.loads(messages[1]["content"])
            assert execution.input_tokens(messages) <= 29388
            if response_format is not None:
                pages.append(payload["memory_item_indices"])
                content = ('{"item_indices":[],"drop_item_indices":[0],"done":false}'
                           if release_capacity and len(pages) > 1 else
                           '{"item_indices":[0,1,2],"done":false}')
            else:
                expected = [1, 2] if release_capacity else [0, 2]
                assert payload["memory_item_indices"] == expected
                assert payload["memories"] == [memories[index] for index in expected]
                content = "The report states a decision."
            return {"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}}

        execution.client.chat = chat
        if policy is None:
            with pytest.raises(ReadDeliveryIncomplete, match="read_call_limit"):
                execution.answer_material("Which status?", "", "joint", memories,
                                          snapshot_id=snapshot_id)
        else:
            answer, _ = execution.answer_material("Which status?", "", "joint", memories,
                                                  snapshot_id=snapshot_id)
            assert answer == "The report states a decision."
            assert all(pages) and set(index for page in pages for index in page) == {0, 1, 2}
            view = read_json(execution.root / "http/joint/memory-view.json")
            admission = view["capacity_continuation"]["budget_admissions"][-1]
            assert [ref["item_index"] for ref in admission["excluded_refs"]] == (
                [] if release_capacity else [1])
            if release_capacity:
                assert [ref["item_index"] for ref in view["capacity_continuation"][
                    "budget_admissions"][0]["excluded_refs"]] == [1]
            assert view["capacity_continuation"]["final_input_tokens"] <= 29388
        assert read_json(execution.root / snapshot_id)["materials"] == memories
