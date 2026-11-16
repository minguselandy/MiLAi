"""Calibration improves confidence without changing choices or family weighting."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from reader_calibration import fit_temperature, log_probabilities, metrics
from run_reader_calibration import eligible_rows


def samples():
    rows, predictions = [], []
    for index in range(10):
        target = "stop_sufficient" if index < 8 else "stop_exhausted"
        rows.append({"gold": {"next": {"probabilities": {target: 1}}},
                     "metadata": {"family": str(index), "row": index, "label_status": target}})
        predictions.append({"logits": {"stop_sufficient": math.log(0.99),
                                        "stop_exhausted": math.log(0.01)}})
    return rows, predictions


def test_calibration_matches_empirical_rate_and_does_not_change_policy():
    rows, predictions = samples()
    fit = fit_temperature(rows, predictions)
    scaled = log_probabilities(predictions[0]["logits"], fit["temperature"])
    assert math.exp(scaled["stop_sufficient"]) == pytest.approx(0.8, abs=1e-6)
    before, after = metrics(rows, predictions, 1), metrics(rows, predictions, fit["temperature"])
    assert after["soft_ce"] < before["soft_ce"]
    assert after["accepted_top"] == before["accepted_top"] == 0.8
    assert after["stop_reliability"]["stop_sufficient"]["ece"] < 1e-6
    # A duplicated prefix within one event must not change that family's weight.
    duplicate = fit_temperature([*rows, rows[0]], [*predictions, predictions[0]])
    assert duplicate["temperature"] == pytest.approx(fit["temperature"], abs=1e-6)


def test_equivalent_actions_use_soft_target_and_stable_extreme_logits():
    rows, predictions = samples()
    rows = rows[:1]
    rows[0]["gold"]["next"]["probabilities"] = {"stop_sufficient": 0.5, "stop_exhausted": 0.5}
    result = metrics(rows, predictions[:1], 1)
    assert result["accepted_top"] == 1
    assert result["acceptable_action_mass"] == pytest.approx(1)
    assert result["top_soft_target_reliability"]["ece"] == pytest.approx(0.49)
    assert math.isfinite(log_probabilities({"a": 10000, "b": -10000}, 0.05)["b"])


def test_known_exposure_is_removed_before_model_input(tmp_path):
    import json

    rows, _ = samples()
    (tmp_path / "test.jsonl").write_text("\n".join(map(json.dumps, rows)))
    selected, inventory = eligible_rows({"data": str(tmp_path),
        "exclude_families": {"test": ["0", "2"]}, "exclusion_source": "source-review"}, "test")
    assert len(selected) == inventory["eligible_states"] == 8
    assert not {r["metadata"]["family"] for r in selected} & {"0", "2"}
