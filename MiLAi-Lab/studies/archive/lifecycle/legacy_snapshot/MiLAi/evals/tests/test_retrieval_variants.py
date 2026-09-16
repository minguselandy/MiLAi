from __future__ import annotations

import numpy

from evals.benchmark import dg11_retrieval as retrieval


def _sessions() -> tuple[list[str], list[list[dict[str, str]]], list[str]]:
    return (
        ["s1", "s2"],
        [
            [
                {"role": "user", "content": "I prefer blue trail shoes."},
                {"role": "assistant", "content": "I recommend the Alpine model."},
            ],
            [
                {"role": "user", "content": "The weather is mild."},
                {"role": "assistant", "content": "Take a light jacket."},
            ],
        ],
        ["2026-08-01T00:00:00+00:00", "2026-08-02T00:00:00+00:00"],
    )


def test_window_documents_preserve_parent_and_turn_identity() -> None:
    documents = retrieval.build_window_documents(*_sessions())

    assert {document.parent_session_id for document in documents} == {"s1", "s2"}
    assert {document.kind for document in documents} == {"turn", "window"}
    assert len({document.document_id for document in documents}) == len(documents)
    assert any(document.roles == ("user", "assistant") for document in documents)


def test_duplicate_source_session_ids_keep_unique_documents_and_shared_parent() -> None:
    documents = retrieval.build_window_documents(
        ["same", "same"],
        [
            [{"role": "user", "content": "first observation"}],
            [{"role": "user", "content": "second observation"}],
        ],
        ["2026-08-01T00:00:00+00:00", "2026-08-02T00:00:00+00:00"],
    )

    assert len({document.document_id for document in documents}) == 2
    assert {document.parent_session_id for document in documents} == {"same"}


def test_retrieval_deduplicates_windows_to_parent_and_records_lanes() -> None:
    documents = retrieval.build_window_documents(*_sessions())
    vector_scores = [
        0.95 if document.parent_session_id == "s1" else 0.1 for document in documents
    ]

    result = retrieval.retrieve_parents(
        "What shoes do I prefer?", documents, vector_scores, k=2
    )

    assert result["session_ids"][0] == "s1"
    assert len(result["session_ids"]) == len(set(result["session_ids"]))
    assert "vector" in result["items"][0]["matched_by"]
    assert result["recent_lane_enabled"] is False
    assert result["items"][0]["lane_evidence"][0]["raw_score"] is not None


def test_recency_lane_is_only_enabled_by_query_intent() -> None:
    documents = retrieval.build_window_documents(*_sessions())
    scores = [0.5] * len(documents)

    plain = retrieval.retrieve_parents("Which shoes do I prefer?", documents, scores)
    recent = retrieval.retrieve_parents(
        "What did I prefer most recently?", documents, scores
    )

    assert plain["recent_lane_enabled"] is False
    assert recent["recent_lane_enabled"] is True


def test_projection_dimensions_are_normalized_and_versioned() -> None:
    source = numpy.zeros((2, 384), dtype="float32")
    source[0, 0] = 1.0
    source[1, 1] = 1.0

    projected_16 = retrieval.project_source(source, 16, numpy_module=numpy)
    projected_128 = retrieval.project_source(source, 128, numpy_module=numpy)
    projected_384 = retrieval.project_source(source, 384, numpy_module=numpy)

    assert projected_16.shape == (2, 16)
    assert projected_128.shape == (2, 128)
    assert projected_384.shape == (2, 384)
    assert numpy.allclose(numpy.linalg.norm(projected_16, axis=1), 1.0)
    assert (
        retrieval.projection_identity(16).key != retrieval.projection_identity(128).key
    )


def test_high_dimension_requires_stable_gain_over_passing_16d() -> None:
    def variant(hit: float, coverage: float) -> dict[str, object]:
        summary = {
            "overall": {"hit_at_3": hit, "relevant_coverage_at_3": coverage},
            "category": {
                "single-session-preference": {"hit_at_3": 1.0},
                "single-session-assistant": {"hit_at_3": 1.0},
            },
        }
        return {"summary": summary, "gates": {"all": True}}

    assert (
        retrieval.choose_winner(
            {
                "A1": variant(0.90, 0.85),
                "A2": variant(0.91, 0.87),
                "A3": variant(0.90, 0.85),
            }
        )
        == "A1"
    )
    assert (
        retrieval.choose_winner(
            {
                "A1": variant(0.90, 0.85),
                "A2": variant(0.92, 0.88),
                "A3": variant(0.90, 0.85),
            }
        )
        == "A2"
    )
