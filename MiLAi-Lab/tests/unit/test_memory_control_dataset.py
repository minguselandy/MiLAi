"""Regression checks for annotation dialects and the masked native evidence loss."""

from __future__ import annotations

import pytest

from milai_lab.datasets.memory_control_normalize import (
    PRIMING_PREFIX,
    align_qasper,
    bool_field,
    is_priming,
    query_message,
    snippet_match,
    source_history,
)
from milai_lab.methods.small_control_learning import state_loss


def test_qasper_keeps_ambiguity_and_caption_identity() -> None:
    paragraphs = [(1, "A paragraph."), (2, "A paragraph."), (3, "Text with\nspace.")]
    captions = [(4, "Figure 1.")]  # The file reference supplies no image bytes.
    assert align_qasper("A paragraph.", paragraphs, captions) == {
        "evidence_kind": "text",
        "status": "ambiguous",
        "objects": [1, 2],
    }
    assert align_qasper("Text with space.", paragraphs, captions) == {
        "evidence_kind": "text",
        "status": "normalized",
        "objects": [3],
    }
    assert align_qasper("FLOAT SELECTED: Figure 1.", paragraphs, captions) == {
        "evidence_kind": "caption_only",
        "status": "exact",
        "objects": [4],
    }
    assert align_qasper("Figure without a file", paragraphs, captions)["status"] == "unmatched"


def test_persona_priming_preserves_original_index_and_real_system_messages() -> None:
    priming = PRIMING_PREFIX + '\n{"short_persona": "Persona"}'
    assert is_priming("system", priming)
    assert is_priming("system", PRIMING_PREFIX + " {}")
    assert not is_priming("user", priming)
    assert not is_priming("system", "Instruction visible to the original dialogue")
    assert query_message("{'role': 'user', 'content': 'Which one?'}") == (
        "Which one?",
        "python_literal",
    )
    assert bool_field("False") is False
    history = source_history(
        [
            {"role": "system", "content": priming},
            {"role": "assistant"},
            {"role": "user", "content": "I prefer\n tea."},
        ]
    )
    assert snippet_match([("user", "I prefer tea.")], history, [None, None, 0]) == {
        "status": "normalized",
        "raw_indices": [[2]],
        "processed_indices": [[0]],
    }


def test_weak_loss_leaves_unknown_actions_and_executed_objective_separate() -> None:
    torch = pytest.importorskip("torch")
    scores = torch.zeros(3, requires_grad=True)
    ids = ["read_0", "read_1", "handoff"]
    inputs = {
        "weak_evidence_loss_weight": 1,
        "weak_evidence_values": dict(zip(ids, [True, False, None], strict=True)),
        "observed_action_ids": [],
    }
    loss = state_loss(scores, ids, inputs)
    loss.backward()
    assert scores.grad.tolist() == [-0.25, 0.25, 0.0]
    with pytest.raises(ValueError, match="actually observed"):
        state_loss(
            scores,
            ids,
            {**inputs, "preferences": [{"left": "read_0", "right": "handoff", "outcome": "left"}]},
        )
