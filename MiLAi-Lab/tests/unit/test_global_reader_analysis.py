"""Reference, source proof and presentation controls have distinct denominators."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from analyze_global_reader import diagnostics, source_diagnostics


def row(index, target, opened, origin):
    return {
        "gold": {"next": {"probabilities": target}},
        "questions": {
            "next": {
                "criteria": {
                    "open_p0": "",
                    "open_p1": "",
                    "stop_sufficient": "",
                    "stop_exhausted": "",
                }
            }
        },
        "metadata": {
            "row": index,
            "family": str(index),
            "question_id": str(index),
            "steps": 2,
            "prefix_origins": [origin],
            "label_status": origin,
            "pool_source_indices": [1, 0],
            "opened_source_indices": opened,
            "bm25_source_indices": [0, 1],
            "answerable_full_context": True,
        },
    }


def prediction(choice):
    return {
        "choice": choice,
        "probabilities": {
            "stop_exhausted": 0.7,
            "open_p1": 0.2,
            "open_p0": 0.09,
            "stop_sufficient": 0.01,
        },
    }


def test_best_open_and_bm25_are_not_argmax_or_first_presented_candidate():
    rows = [
        row(0, {"open_p1": 1}, [], "empty"),
        row(0, {"stop_sufficient": 1}, [0], "reference_complete"),
    ]
    result = diagnostics(rows, [prediction("stop_exhausted"), prediction("stop_exhausted")])
    assert result["reference"]["counts"]["accepted"] == 0
    assert result["reference"]["counts"]["first_remaining_candidate_accepted"] == 0
    assert result["counts"]["best_open_accepted"] == 1
    assert result["counts"]["bm25_next_accepted"] == 1
    assert result["state_transitions"]["empty_to_reference_complete"] == {
        "pairs": 1,
        "both_accepted": 0,
        "semantic_action_kind_changed": 0,
    }


def test_source_evaluation_keeps_masked_and_insufficient_without_fake_gold():
    rows = [
        row(0, {"open_p1": 1}, [], "empty"),
        row(1, {"stop_sufficient": 1}, [0], "reference_complete"),
        row(2, {"stop_sufficient": 1}, [0], "reference_complete"),
    ]
    reviews = {
        0: {"disposition": "supported", "complete_proofs": [[0]]},
        1: {"disposition": "pool_insufficient", "complete_proofs": []},
        2: {"disposition": "masked", "complete_proofs": []},
    }
    result = source_diagnostics(
        rows,
        [prediction("open_p1"), prediction("stop_sufficient"), prediction("stop_sufficient")],
        reviews,
    )
    assert result["counts"]["source_missing_complement_accepted"] == 1
    assert result["counts"]["strict_pool_insufficient_selected_sufficient"] == 1
    assert result["counts"]["masked_states"] == 1
    assert result["supported_family_macro_acceptance"] == 1
    assert set(result["supported_family_results"]) == {"0"}
