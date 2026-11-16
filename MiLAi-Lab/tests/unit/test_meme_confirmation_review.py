"""Native before gates pair the same condition and seed; failures stay missing."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from milai_lab.harness.artifact_io import write_json
from review_meme_confirmation import prepare, score


def test_review_waits_for_original_cohort_completion(tmp_path):
    write_json(tmp_path / "driver.json", {"status": "RUNNING"})
    with pytest.raises(ValueError, match="Complete all"):
        prepare(tmp_path)


def test_before_gate_does_not_borrow_another_seed_or_conditions_pass(tmp_path):
    references = [{"episode": "e", "id": "before-0", "phase": "before",
                   "task_type": "Abs", "before_id": None},
                  {"episode": "e", "id": "after-0", "phase": "after",
                   "task_type": "Abs", "before_id": "before-0"}]
    mapping, judgments = {}, {}
    for seed in (1, 2):
        for variant in ("baseline", "compact"):
            for phase in ("before", "after"):
                key = str(len(mapping))
                mapping[key] = {"seed": seed, "episode": "e", "variant": variant,
                                "id": phase + "-0", "source_result": "fixture",
                                "missing_prediction": False}
                passed = phase == "after" or (seed, variant) in {(1, "compact"), (2, "baseline")}
                judgments[key] = {"judgment": "pass" if passed else "ambiguous", "reason": "test"}
    write_json(tmp_path / "prepared/references.json", references)
    write_json(tmp_path / "review-pack/join-after-review.json", mapping)
    path = tmp_path / "judgments.json"
    write_json(path, {"judgments": judgments})
    result = score(tmp_path, path)
    cells = {(c["seed"], c["variant"]): c for c in result["cells"]}
    assert cells[1, "baseline"]["after_gated_pass"] == 0
    assert cells[2, "compact"]["after_gated_pass"] == 0
    assert cells[1, "compact"]["after_gated_pass"] == 1
    assert result["episode_macro_difference"] == 0
    mapping["0"]["missing_prediction"] = True
    write_json(tmp_path / "review-pack/join-after-review.json", mapping)
    with pytest.raises(ValueError, match="remain explicitly missing"):
        score(tmp_path, path)
