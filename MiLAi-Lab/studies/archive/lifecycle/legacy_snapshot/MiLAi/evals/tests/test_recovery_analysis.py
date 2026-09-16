from __future__ import annotations

from evals.benchmark import dg11_recovery


def _row(index: int, category: str) -> dict[str, object]:
    source_id = f"case-{index:03d}"
    return {
        "question_id": source_id,
        "question_type": category,
        "question": f"question {index}",
        "answer": "answer",
        "answer_session_ids": [f"session-{index}"],
    }


def test_partition_remaining_freezes_exact_mutually_exclusive_stratified_halves() -> None:
    rows = [_row(index, "a" if index < 360 else "b") for index in range(500)]
    consumed = {f"case-{index:03d}" for index in range(300)}

    first = dg11_recovery.partition_remaining(rows, consumed)
    second = dg11_recovery.partition_remaining(rows, consumed)

    assert first == second
    v2 = set(first["generalization_v2"])
    paper = set(first["paper_test_v1"])
    assert len(v2) == len(paper) == 100
    assert not v2.intersection(paper)
    assert not v2.union(paper).intersection(consumed)
    assert first["generalization_v2_allocation"] == {"a": 30, "b": 70}
    assert first["paper_test_v1_allocation"] == {"a": 30, "b": 70}


def test_error_matrix_preserves_signals_and_maps_targeted_fix() -> None:
    source_ids = ["94f70d80"] + [f"case-{index:03d}" for index in range(99)]
    rows = []
    scored = []
    current_contexts = []
    dg10_contexts = []
    for source_id in source_ids:
        session_id = f"session-{source_id}"
        rows.append(
            {
                "question_id": source_id,
                "question_type": "temporal-reasoning",
                "question": "How long did it take?",
                "answer": "4 hours",
                "answer_session_ids": [session_id],
            }
        )
        for arm, answer, f1 in (
            ("MILAI_DG11_CURRENT", "UNKNOWN", 0.0),
            ("MILAI_DG10_FROZEN", "UNKNOWN", 0.0),
        ):
            scored.append(
                {
                    "source_id": source_id,
                    "arm": arm,
                    "answer": answer,
                    "memory_tokens": 20,
                    "scorer_v1": {"exact_match": 0, "normalized_f1": f1},
                    "scorer_v2": {"exact_match": 0, "normalized_f1": f1},
                }
            )
        context_record = {
            "source_id": source_id,
            "context": {
                "status": "UNCERTAIN",
                "rendered": "MEMORY_STATUS=UNCERTAIN",
            },
            "trace": {"retrieved_session_ids": []},
        }
        current_contexts.append(context_record)
        dg10_contexts.append(context_record)

    matrix = dg11_recovery.build_v1_error_matrix(
        rows, scored, current_contexts, dg10_contexts, source_ids
    )

    assert matrix["case_count"] == 100
    targeted = matrix["records"][0]
    assert targeted["layer_flags"]["R0"] is True
    assert targeted["layer_flags"]["R6"] is True
    assert targeted["primary_layer"] == "R0"
    assert targeted["targeted_fix"]["fix"].startswith("duration wording")
