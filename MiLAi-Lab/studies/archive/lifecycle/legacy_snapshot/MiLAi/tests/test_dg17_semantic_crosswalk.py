from __future__ import annotations

from evals.dg17.semantic_crosswalk import (
    EXPECTED_LABELS_SHA256,
    IMMUTABLE_Q0_RECEIPT_SHA256,
    build_semantic_crosswalk,
    score_semantic_predictions,
)


def test_q3a_crosswalk_preserves_immutable_q0_and_separates_semantics() -> None:
    receipt = build_semantic_crosswalk()

    assert receipt["source"]["atom_labels_sha256"] == EXPECTED_LABELS_SHA256
    assert (
        receipt["source"]["immutable_q0_receipt_sha256"]
        == IMMUTABLE_Q0_RECEIPT_SHA256
    )
    assert receipt["source"]["source_mutated"] is False
    assert receipt["semantics"] == {
        "legacy_atom_is_measurement_label_only": True,
        "span_is_source_pointer_only": True,
        "interpretation_is_fallible_candidate": True,
        "binding_is_query_local": True,
        "canonical_authority_promoted": False,
        "product_path_labels_exposed": False,
    }
    assert receipt["denominators"] == {
        "case_count": 10,
        "legacy_atom_count": 23,
        "unique_answer_bearing_span_count": 22,
        "expected_interpretation_count": 23,
        "expected_binding_count": 23,
        "typed_contract_case_count": 10,
    }
    assert receipt["typed_contract_gate"] == {
        "status": "PASS",
        "operator_family_expected": 10,
        "compatibility_operator_identity_preserved": 10,
        "compatibility_requirement_identity_preserved": 10,
        "target_event_identity_preserved": 10,
        "generic_lookup_collapse": 0,
        "denominator": 10,
        "annotation_review_boundary": "PROVISIONAL_OPENED_DEV_LABELS",
    }
    temporal_targets = [
        row
        for row in receipt["typed_contract_rows"]
        if row["expected_operator_family"] == "TEMPORAL_FILTER"
    ]
    assert len(temporal_targets) == 2
    assert all(row["target_event_identity_preserved"] for row in temporal_targets)


def test_q3a_crosswalk_scores_exact_source_kind_and_query_local_binding() -> None:
    crosswalk = build_semantic_crosswalk()
    predicted = []
    for case in crosswalk["cases"]:
        spans = [
            {
                "span_id": row["span_id"],
                "source_turn_ref": row["source_turn_ref"],
                "start": row["start"],
                "end": row["end"],
                "text": row["text"],
            }
            for row in case["spans"]
        ]
        interpretations = [
            {
                "interpretation_id": row["interpretation_id"],
                "span_id": row["span_id"],
                "kind": row["kind"],
            }
            for row in case["interpretations"]
        ]
        bindings = [
            {
                "interpretation_id": row["interpretation_id"],
                "requirement_id": row["requirement_id"],
                "status": "MATCH",
            }
            for row in case["bindings"]
        ]
        predicted.append(
            {
                "case_id": case["case_id"],
                "spans": spans,
                "interpretations": interpretations,
                "bindings": bindings,
            }
        )

    score = score_semantic_predictions(predicted)

    assert score["aggregate"] == {
        "answer_bearing_span_recall": 1.0,
        "answer_bearing_interpretation_recall": 1.0,
        "requirement_binding_precision": 1.0,
        "required_slot_coverage": 1.0,
    }
    assert score["denominators"] == {
        "answer_bearing_spans": 22,
        "answer_bearing_interpretations": 23,
        "predicted_match_bindings": 23,
        "required_slots": 16,
    }
