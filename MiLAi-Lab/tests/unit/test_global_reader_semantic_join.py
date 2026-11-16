"""Reader abstention, task completion, grounding and output failure stay separate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from join_global_reader_review import verdict


def test_same_abstention_can_be_correct_reader_response_but_lost_task_answer():
    annotation = {
        "answer_target": "no_answer",
        "source_grounding": "correct_insufficiency",
        "citation_grounding": "not_applicable",
        "output_contract": "valid",
    }
    positive = verdict(annotation, "supported")
    negative = verdict(annotation, "pool_insufficient")
    assert positive["reader_response_pass"] is negative["reader_response_pass"] is True
    assert positive["source_contract_task_pass"] is False
    assert negative["source_contract_task_pass"] is True
    assert verdict(annotation, "masked")["source_contract_task_pass"] is None


def test_matching_value_without_identity_evidence_or_with_bad_contract_is_not_pass():
    annotation = {
        "answer_target": "correct",
        "source_grounding": "unsupported_claim",
        "citation_grounding": "inadequate",
        "output_contract": "valid",
    }
    assert not verdict(annotation, "supported")["source_contract_task_pass"]
    annotation.update(
        source_grounding="supported_by_delivered_material", citation_grounding="adequate"
    )
    assert verdict(annotation, "supported")["source_contract_task_pass"]
    annotation["output_contract"] = "schema_or_generation_failure"
    assert verdict(annotation, "supported")["grounded_target_answer"]
    assert not verdict(annotation, "supported")["source_contract_task_pass"]
    assert verdict(annotation, "supported")["schema_or_generation_failure"]
