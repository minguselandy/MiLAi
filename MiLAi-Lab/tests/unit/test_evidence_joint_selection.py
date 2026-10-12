"""J1 lets the existing Reader select source bodies and state together."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
