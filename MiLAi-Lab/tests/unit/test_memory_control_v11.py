from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from milai_lab.datasets.memory_control_outcomes import outcome_supervision
from milai_lab.datasets.memory_control_revision import REVISION_SCHEMA
from milai_lab.datasets.memory_control_store import SCHEMA, packed
from milai_lab.memory.source_materials import read_original_materials
from milai_lab.methods.literal_delivery_union import literal_delivery
from milai_lab.methods.small_control_learning import state_loss


def test_literal_delivery_preserves_gaps_and_access_scope() -> None:
    body = "abcdefghij"

    def source(ref: str) -> dict:
        return {
            "event_id": ref,
            "source_revision": 1,
            "session": "conversation",
            "role": "user",
            "origin": "dialogue",
            "content": body,
            "observed_at": None,
        }

    def read(materials: list[dict]) -> list[dict]:
        return read_original_materials(materials, source)

    def view(start: int, end: int, scope: str) -> dict:
        binding = {
            "kind": "original_source",
            "id": "same",
            "session_id": "conversation",
            "source_access_scope": scope,
            "turn_range": [0, 1],
            "source_ranges": [
                {"source_ref": "m1", "source_revision": 1, "start": start, "end": end}
            ],
        }
        return {**binding, **read([binding])[0]}

    opened = {0: view(0, 3, "a"), 1: view(2, 5, "a"), 2: view(8, 10, "a"), 3: view(2, 5, "b")}
    delivery = literal_delivery(opened, read, lambda _: 0)
    assert [pieces["label"] for pieces in delivery.evidence] == ["e0", "e3"]
    assert [
        [(piece["content"], piece["range"]) for piece in pack["evidence"]]
        for pack in delivery.evidence
    ] == [[("abcde", [0, 5]), ("ij", [8, 10])], [("cde", [2, 5])]]
    assert delivery.overlap_before_normalization == 1


def test_completed_repeat_pairs_only_and_scaled_loss() -> None:
    torch = pytest.importorskip("torch")
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA + REVISION_SCHEMA)
        for action, repeat, status, quality, cost in (
            ("read_0", 0, "ingested", 1.0, 45),
            ("context_0", 0, "ingested", 0.2, 75),
            ("handoff", 0, "prepared", None, None),
            ("context_0", 1, "reader_error", None, None),
            ("other", 1, "ingested", 1.0, 20),
        ):
            db.execute(
                """
                INSERT INTO action_outcomes
                (state_id,action_id,run_id,repeat_index,reader_protocol,execution_status,
                 training_quality,success_witness,costs) VALUES (1,?, 'shared',?, 'v1',?,?,?,?)
            """,
                (
                    action,
                    repeat,
                    status,
                    quality,
                    quality == 1.0,
                    packed({"reader_input_tokens": cost}),
                ),
            )
        ids = ["read_0", "context_0", "handoff", "other"]
        sup = outcome_supervision(db, 1, set(ids), ("shared",))
        assert sup["observed_values"] == {"read_0": 1.0, "context_0": 0.2, "other": 1.0}
        assert sup["preferences"] == [{"left": "context_0", "right": "read_0", "outcome": "right"}]
        assert sup["success_cost_preferences"] == []
        scores = torch.zeros(len(ids), requires_grad=True)
        loss = state_loss(
            scores, ids, {**sup, "value_loss_weight": 0, "success_cost_loss_weight": 0}
        )
        assert float(loss.detach()) == pytest.approx(float(torch.log(torch.tensor(2.0))) * 0.2)
        loss.backward()
        assert scores.grad.tolist()[2:] == [0.0, 0.0]
