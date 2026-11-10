"""Learner states follow actual full-menu decisions without exposing supervision."""

import json
from types import SimpleNamespace

from collect_qasper_operation_states import collect_paper
from collected_handoff import replay_collected_prefix
from milai_lab.methods.laya_memory_policy import payload_actions
from prepare_collected_operation_feedback import execute_branch, select_events


def test_learner_choice_budget_handoff_and_mid_prefix_replay(tmp_path):
    history = {
        "id": "paper",
        "source_group": "paper",
        "split": "train",
        "sources": [
            {
                "session_id": "paper",
                "event_key": "body",
                "origin": "reference_document",
                "occurred_at": None,
                "original_event_id": "OFFLINE_PROOF_ID",
                "content": "Alpha beta evidence and a real source body.",
            }
        ],
        "requests": [{"id": "q", "content": "What is alpha beta evidence?"}],
    }
    controls = {
        "q": {"schema": "source_reference_witness_v1", "reference_proofs": [[["OFFLINE_PROOF_ID"]]]}
    }
    capacity = SimpleNamespace(
        text_tokens=len,
        tokenizer=lambda text, **_: {"offset_mapping": [(i, i + 1) for i in range(len(text))]},
    )
    settings = {"ordinary_material_tokens": 8192}
    inputs, rows = [], []

    def predict(payload):
        inputs.append(payload)
        actions = payload_actions(payload)
        selected = next((a for a in actions if a.kind in {"SEARCH", "READ"}), actions[-1])
        return {
            "choice": selected.id,
            "logits": {a.id: float(a.id == selected.id) for a in actions},
        }

    root = tmp_path / "banks" / "paper"
    collect_paper(
        history,
        controls,
        root,
        capacity,
        settings,
        max_steps=3,
        branches=False,
        seed=0,
        append=lambda kind, row: rows.append(row),
        predict=predict,
    )
    events = [json.loads(line) for line in (root / "q-operations.jsonl").read_text().splitlines()]
    assert len(inputs) == len(rows) == 3
    assert "OFFLINE_PROOF_ID" not in json.dumps(inputs)
    assert all(set(p) == {"state", "questions"} for p in inputs)
    assert all(e["selected"] == e["prediction"]["choice"] for e in events[:-1])
    assert events[-1]["forced_budget_handoff"]
    assert all(r["metadata"]["collector"] == "frozen_learner" for r in rows)
    target = {**events[1], "event_id": "paper/q/step-1"}
    with replay_collected_prefix(tmp_path, history, target, settings, capacity, target_step=1) as (
        operations,
        state,
    ):
        assert state.project() == target["before"]
        assert [a.id for a in operations.actions(state)] == [a["id"] for a in target["actions"]]
        saved = operations.checkpoint()
        observation = operations.source_pages.budget
        read = next(a for a in operations.actions(state) if a.kind == "READ")
        result = execute_branch(operations, target["before"], read, 1, 2)
        assert result["trace"][0]["selected"] == read.id
        assert operations.opened
        operations.restore_checkpoint(saved, observation)
        stop = next(
            a for a in operations.actions(state) if a.kind == "HANDOFF" and not a.parameters
        )
        stopped = execute_branch(operations, target["before"], stop, 1, 2)
        assert len(stopped["trace"]) == 1 and not operations.opened
        assert saved == operations.checkpoint()
    selected = select_events(events, 0)
    assert [e["step"] for e in selected] == [0, 1]
    # Changing downstream success cannot change nomination; forced last states remain excluded.
    for event in events:
        event["result"] = {"ok": False, "status": "unrelated_outcome"}
    assert [e["step"] for e in select_events(events, 0)] == [0, 1]

    initial = {**events[0], "event_id": "paper/q/step-0"}
    with replay_collected_prefix(tmp_path, history, initial, settings, capacity, target_step=0) as (
        operations,
        state,
    ):
        saved = operations.checkpoint()
        search = next(a for a in operations.actions(state) if a.kind == "SEARCH")
        legacy = execute_branch(operations, initial["before"], search, 0, 1, "current")
        assert operations.observed and not operations.opened
        operations.restore_checkpoint(saved, operations.source_pages.budget)
        selected = execute_branch(operations, initial["before"], search, 0, 1, "rules")
        assert operations.opened
        assert [e["selected"] for e in legacy["trace"][:-1]] == [
            e["selected"] for e in selected["trace"][:-1]
        ]
        assert len(selected["trace"]) == 3
        assert selected["trace"][-1]["selected"] != "handoff"
