"""Fixed-k and STOP policies share only identical actually visited prefixes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from run_bounded_reader_selection import policies


def test_fixed_and_adaptive_reuse_prefix_and_keep_stopping_failure(tmp_path):
    case = {"case_id": "case", "question": "q", "candidates": [
        {"id": f"p{i}", "title": "title", "text": str(i)} for i in range(3)]}
    calls = []

    def predict(payload):
        calls.append(payload)
        choices = payload["questions"]["next"]["criteria"]
        probs = {key: 0.01 for key in choices}
        probs["stop_exhausted"] = 0.7
        first_open = next(key for key in choices if key.startswith("open_"))
        probs[first_open] = 0.2
        return {"probabilities": probs, "input_tokens": 10, "wall_seconds": 0.0}

    results = policies(case, predict, tmp_path)
    assert len(calls) == 2  # Adaptive reuses the empty prefix already measured by k2.
    assert results["k2"]["selected_ids"] == ["p0", "p1"]
    assert results["adaptive"]["selected_ids"] == []
    assert results["adaptive"]["stop_reason"] == "stop_exhausted"
    assert results["adaptive"]["controller_trace"][0]["reused"] is True
    assert results["adaptive"]["standalone_model_input_tokens"] == 10
    assert results["k2"]["standalone_model_input_tokens"] == 20


def test_full_twenty_pool_is_not_silently_cropped_to_eight(tmp_path):
    case = {"case_id": "case", "question": "q", "candidates": [
        {"id": f"p{i}", "title": "title", "text": str(i)} for i in range(20)]}
    calls = []

    def predict(payload):
        calls.append(len(payload["state"]["candidates"]))
        opened = len(payload["state"]["read_evidence"])
        choices = payload["questions"]["next"]["criteria"]
        preferred = f"open_p{19 - opened}" if opened < 2 else "stop_sufficient"
        assert preferred in choices
        return {"probabilities": {key: float(key == preferred) for key in choices},
                "input_tokens": 10, "wall_seconds": 0.0}

    results = policies(case, predict, tmp_path)
    assert calls == [20, 19, 18]
    assert results["k2"]["selected_ids"] == ["p19", "p18"]
    assert results["adaptive"]["selected_ids"] == ["p19", "p18"]
    assert results["adaptive"]["stop_reason"] == "stop_sufficient"
