"""Continuation extends a fixed prefix and never rewrites a sealed batch."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from replay_v0213_cost import save
from run_v0213_decomposition import prepare, wave_selection


def test_wave_preserves_original_acceptance_and_selects_next_pair(tmp_path):
    accepted = {"accepted": [{"key": key} for key in ("a", "b", "c", "d")],
                "first_wave": ["a", "b"]}
    assert wave_selection(tmp_path, accepted)["selected"] == ["a", "b"]
    save(tmp_path / "wave-selection.json", {
        "label": "P3", "previously_run": ["a", "b"], "selected": ["c", "d"]})
    assert wave_selection(tmp_path, accepted)["selected"] == ["c", "d"]
    assert accepted["first_wave"] == ["a", "b"]


@pytest.mark.parametrize("selected", [["b", "c"], ["d"], ["c", "c"], ["x"]])
def test_wave_rejects_rerun_skipping_duplicate_and_unaccepted(tmp_path, selected):
    accepted = {"accepted": [{"key": key} for key in ("a", "b", "c", "d")]}
    save(tmp_path / "wave-selection.json", {
        "label": "P3", "previously_run": ["a", "b"], "selected": selected})
    with pytest.raises(ValueError, match="WAVE_MUST_EXTEND"):
        wave_selection(tmp_path, accepted)


def test_prepare_refuses_existing_seal_before_any_input_write(tmp_path):
    seal = tmp_path / "seal-b.json"
    save(seal, {"frozen": True})
    original = seal.read_bytes()
    with pytest.raises(ValueError, match="SEAL_B_ALREADY_EXISTS"):
        prepare(tmp_path, tmp_path / "nonexistent-tokenizer")
    assert seal.read_bytes() == original
    assert not (tmp_path / "host-inputs").exists()
