"""Conditional delivery selection is not an autonomous stop, and never consults native outcomes."""

import copy
from dataclasses import asdict

import pytest

from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from prepare_scored_handoff_readouts import nominations


def test_conditional_handoff_keeps_full_argmax_separate_and_ignores_labels():
    actions = [
        MemoryAction("r", "READ", "candidate", {"index": 0}),
        MemoryAction("h", "HANDOFF", "current"),
        MemoryAction("s", "HANDOFF", "subset", {"delivery_indices": []}),
    ]
    full = list(map(asdict, actions))
    branch = {
        "before": MemoryControlState(task={"request": "query"}).project(),
        "actions": full[1:],
        "native_reference_complete": {"h": True, "s": False},
    }
    prediction = {"choice": "r", "logits": {"r": 9.0, "h": 0.0, "s": 1.0}}
    result = nominations(branch, prediction, full)
    assert result["full_argmax"] == "r" and result["conditional_only"]
    assert result["choices"] == {"frozen_conditional": "s", "rules": "h", "fixed_current": "h"}
    altered = copy.deepcopy(branch)
    altered["native_reference_complete"] = {"h": False, "s": True}
    assert nominations(altered, prediction, full) == result
    with pytest.raises(ValueError, match="logits"):
        nominations(branch, {**prediction, "choice": "h"}, full)
