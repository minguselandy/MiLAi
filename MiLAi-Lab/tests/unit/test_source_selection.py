"""Train/rollout parity and honest supervision under alternative evidence proofs."""

import copy
import sys
from pathlib import Path

from milai_lab.methods.bounded_evidence import select_bounded, selection_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_source_selection import project
from run_bounded_reader_selection import policies


def test_fixed_budget_rollout_uses_training_payload_and_unique_opens():
    candidates = [{"id": f"p{i}", "title": str(i), "text": f"fact {i}",
                   "answer": "PRIVATE"} for i in range(5)]
    calls = []

    def decide(payload):
        calls.append(payload)
        assert all(k.startswith("open_") for k in payload["questions"]["next"]["criteria"])
        assert "PRIVATE" not in str(payload)
        return next(iter(payload["questions"]["next"]["criteria"]))

    result = select_bounded("query", candidates, decide, selection_only=True)
    assert result["selected_ids"] == ["p0", "p1", "p2", "p3"]
    assert result["decision_calls"] == 4 and result["stop_reason"] == "read_budget"
    assert calls[2] == selection_payload("query", candidates[:2], candidates[2:])
    short = select_bounded("query", candidates[:1], decide, selection_only=True)
    assert short["selected_ids"] == ["p0"] and short["stop_reason"] == "pool_consumed"


def test_source_labels_preserve_alternatives_masks_and_pair_exclusions():
    candidates = [{"id": f"p{i}", "title": str(i), "text": f"fact {i}"} for i in range(3)]
    row = {**selection_payload("query", [], candidates),
           "gold": {"next": {"probabilities": {"open_p0": 1}}},
           "metadata": {"row": 0, "family": "f", "split": "dev", "event_id": "e0",
                        "label_status": "reference", "pool_source_indices": [0, 1, 2],
                        "opened_source_indices": []}}
    rows = [copy.deepcopy(row) for _ in range(4)]
    for i, r in enumerate(rows):
        r["metadata"].update(row=i, event_id=f"e{i}")
    rows[2]["gold"] = {"next": {"probabilities": {"stop_sufficient": 1}}}
    rows[3]["state"] = selection_payload("query", candidates[:2], candidates[2:])["state"]
    rows[3]["metadata"]["opened_source_indices"] = [0, 1]
    rows[3]["gold"] = {"next": {"probabilities": {"open_p2": 1}}}
    reviews = [{"source_row": i, "family": "f", "split": "dev", "review_id": f"r{i}",
                "disposition": "supported", "complete_proofs": [[0, 1], [2]],
                "rationale": "PRIVATE_REVIEW"} for i in range(4)]
    reviews[1]["disposition"] = "masked"
    original = copy.deepcopy(rows)
    exports, stats = project(rows, reviews, "dev")
    assert rows == original
    assert stats["source_labelled"] == 2 and stats["paired_states"] == 1
    assert stats["reference_labelled"] == 3
    assert len(exports["reference"]) == len(exports["source"]) == 4
    assert exports["reference"][1]["gold"] and not exports["source"][1]["gold"]
    assert not exports["reference"][2]["gold"] and exports["source"][2]["gold"]
    assert exports["reference"][3]["gold"]["next"]["probabilities"] == {"open_p2": 1}
    assert stats["paired_changed_targets"] == 1
    assert stats["pair_exclusions"] == {"masked_source_review": 1,
        "reference_has_no_open_target": 1, "reviewed_proof_complete": 1}
    assert exports["source"][0]["gold"]["next"]["probabilities"] == {
        "open_p0": 1 / 3, "open_p1": 1 / 3, "open_p2": 1 / 3}
    assert not exports["source"][1]["gold"] and not exports["source"][3]["gold"]
    for source, reference in zip(
            exports["paired_source"], exports["paired_reference"], strict=True):
        assert source["state"] == reference["state"]
        assert source["questions"] == reference["questions"]
        assert source["metadata"]["training_allowed"] is False
        assert "PRIVATE" not in str(source["state"]) + str(source["questions"])


def test_rollout_runner_saves_fixed4_calls_and_costs_without_adaptive_policy(tmp_path):
    candidates = [{"id": f"p{i}", "title": str(i), "text": f"fact {i}"} for i in range(20)]
    case = {"case_id": "query", "question": "query", "candidates": candidates}

    def predict(payload):
        criteria = payload["questions"]["next"]["criteria"]
        assert all(k.startswith("open_") for k in criteria)
        last = next(reversed(criteria))
        return {"probabilities": {key: float(key == last) for key in criteria},
                "input_tokens": 100, "wall_seconds": 0.01}

    result = policies(case, predict, tmp_path, selection_only=True)
    assert set(result) == {"k4"}
    assert result["k4"]["selected_ids"] == ["p19", "p18", "p17", "p16"]
    assert result["k4"]["standalone_model_input_tokens"] == 400
    assert len(list((tmp_path / "calls").glob("*/input.json"))) == 4
