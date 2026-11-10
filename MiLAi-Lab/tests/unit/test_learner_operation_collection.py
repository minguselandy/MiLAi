"""Learner states follow actual full-menu decisions without exposing supervision."""

import json
from types import SimpleNamespace

from collect_qasper_operation_states import collect_paper
from collected_handoff import replay_collected_prefix
from milai_lab.methods.laya_memory_policy import payload_actions


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
