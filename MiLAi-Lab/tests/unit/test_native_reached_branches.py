"""Replay actual stopped states under the recorded material/observation protocol."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.store.sqlite import SqliteStore

import native_qa_branches
from milai_lab.datasets.hotpot_memory import export_question
from milai_lab.memory.service import MemoryService
from milai_lab.methods.memory_control import (
    FixedMemoryPolicy,
    MemoryControlState,
    run_memory_control,
)
from milai_lab.methods.small_memory_policy import PolicyScores
from native_qa_control import capture_sources, environment


class Capacity:
    def __init__(self, config=None):
        self.tokenizer = lambda text, **kwargs: {"offset_mapping": [
            (m.start(), m.end()) for m in re.finditer(r"\S+", text)]}

    def text_tokens(self, text):
        return len(text.split())

    def check(self, messages):
        return {}


def test_same_before_material_protocol_and_independent_actual_read_branches(tmp_path, monkeypatch):
    native = {"id": "q", "question": "Which two facts?", "answer": "both",
        "type": "bridge", "level": "hard", "context": {"title": ["One", "Two"],
            "sentences": [["First actual fact."], ["Second actual fact."]]},
        "supporting_facts": {"title": ["One", "Two"], "sent_id": [0, 0]}}
    history, _ = export_question(native, "train", ordinal=0)
    collection, sources = tmp_path / "collection", tmp_path / "sources"
    bank = collection / "banks" / history["id"]
    bank.mkdir(parents=True)
    sources.mkdir()
    (sources / "sources.json").write_text(json.dumps({"histories": [history]}))
    settings = {"host": {"base_url": "http://localhost:7860/v1", "model": "test",
                         "max_tokens": 100}, "system_prompt": "Answer the supplied question.",
                "capacity": {"enable_thinking": False}}
    config = tmp_path / "reader.json"
    config.write_text(json.dumps({"entrypoints": {"functional": settings}}))
    (collection / "run.json").write_text(json.dumps({"status": "COMPLETED",
        "material_formation": "whole_paragraph_v1_R2_whole_turn_R3",
        "source_directory_only": True}))
    captured = []
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store, ("small-control-native", history["id"], "author"),
                                "author", bank / "lock", functional_contract="functional_v1")
        mapping = capture_sources(service, history)
        (bank / "source-map.json").write_text(json.dumps(mapping))
        request = history["requests"][0]
        state, ops = environment(service, request, Capacity(), 2048,
                                 evidence_units=True, source_directory_only=True)

        def record(event):
            if event.get("phase") == "decision_input":
                captured.append({"event_id": "original-task", "decision": event,
                                 "executor_checkpoint": ops.checkpoint()})

        result = run_memory_control(state, FixedMemoryPolicy(1), ops, max_steps=5, record=record)
        assert result["reason"] == "policy_handoff"
    path = bank / f"{request['id']}-learned-checkpoints.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in captured))

    class Scorer:
        def __init__(self):
            self.counters = {}

        def score(self, online):
            ids = [a["id"] for a in online["actions"]]
            return PolicyScores(ids, [float(key == "handoff") for key in ids])

    monkeypatch.setattr(native_qa_branches, "HostCapacity", Capacity)
    monkeypatch.setattr(native_qa_branches.SmallControlModel, "load", lambda *a, **kw: Scorer())
    for sampling, requested, expected, learned in [("last_observed", None, [2], False),
            ("declared_steps", [1, 2], [1, 2], False), ("declared_steps", [1], [1], True)]:
        output = tmp_path / (sampling + ("-checkpoint" if learned else ""))
        native_qa_branches.collect(SimpleNamespace(collection=collection, sources=sources,
            reader_config=config, output=output, checkpoint=Path("unused-test-checkpoint"),
            continuation_checkpoint=Path("unused-test-checkpoint") if learned else None,
            device="cpu", roots=1, seed=17, horizons=[0, 2], material_tokens=2048,
            collection_policy="learned", state_sampling=sampling, state_steps=requested))
        cases = json.loads((output / "cases.json").read_text())
        assert len(cases) == len(expected) * 2 and {c["horizon"] for c in cases} == {0, 2}
        by_step = {row["decision"]["step"]: row["decision"] for row in captured}
        for case in cases:
            step = case["branches"][0]["condition_provenance"]["before_step"]
            actual = by_step[step]
            assert step in expected
            assert case["before"] == actual["before"] and case["actions"] == actual["actions"]
            assert case["response_event_id"] == "original-task"
            stop = next(b for b in case["branches"] if b["action"]["kind"] == "HANDOFF")
            read = next(b for b in case["branches"] if b["action"]["kind"] == "READ")
            assert len(stop["actual_delivered_source_ranges"]) == step - 1
            assert len(read["actual_delivered_source_ranges"]) == (
                step if case["horizon"] == 0 or learned else 2)
            assert stop["continuation"]["trace"][0]["before"] == read["continuation"]["trace"][0][
                "before"]
            assert read["measured_costs"]["local_action_to_request_wall_seconds"] > 0
        shards = [json.loads(line) for line in (output / "completed-cases.jsonl").read_text(
            ).splitlines()]
        assert shards == cases
        assert len(list(output.glob("state-*/memory.sqlite"))) == sum(
            len(c["branches"]) for c in cases)
        run = json.loads((output / "run.json").read_text())
        assert run["Reader_calls"] == 0
        assert run["continuation_model_shared_with_nomination"] == learned
        if learned:
            assert run["continuation_policy_calls"] > 0
            assert run["continuation_policy"] == "saved_checkpoint_policy"


def test_context_protocol_cannot_change_when_restoring_before_the_first_search(tmp_path):
    request = {"query": "quota", "retrieval_request": {"query": "quota",
               "read_goal": {"evidence": ["original_source"]}}}
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("protocol", "author"), "author", tmp_path / "lock",
                                functional_contract="functional_v1")
        service.capture_user("s", "one", "Quota fourteen.")
        state, ops = environment(service, request, Capacity(), 2048, evidence_units=True,
                                 source_directory_only=True, evidence_context_turn_radius=1)
        saved = ops.checkpoint()
        assert not ops.searched
        with pytest.raises(ValueError, match="CHECKPOINT_CONFIGURATION_CHANGED"):
            environment(service, request, Capacity(), 2048,
                state=MemoryControlState(**state.project()), checkpoint=saved,
                evidence_units=True, source_directory_only=True, evidence_context_turn_radius=0)
        restored_state, restored = environment(service, request, Capacity(), 2048,
            state=MemoryControlState(**state.project()), checkpoint=saved,
            evidence_units=True, source_directory_only=True, evidence_context_turn_radius=1)
        assert restored_state.project() == state.project()
        assert restored.checkpoint() == saved
