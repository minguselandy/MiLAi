"""Original truth and actual visibility are required; screened absence is not certified."""
import copy
import json

from review_continuous_source_outcomes import literal_strings, parse_grade, review_payload


def payload():
    return {"available_original_source_count": 5,
            "selected_original_sources": [{"source_index": 2,
                "source": {"content": '{"speaker":"A","message":"I finished Pachinko"}'}}],
            "actual_final_provider_messages": [{"role": "tool",
                "content": '{"evidence":"I finished Pachinko"}'},
                {"role": "assistant", "content": "The answer is Friday"}]}


def grade(**updates):
    result = {"outcome": "supported", "resolution": "answered", "grounding": "actual_context",
        "abstention_basis": "not_applicable", "source_quotes": [
            {"source_index": 2, "quote": "I finished Pachinko"}],
        "context_quotes": ["I finished Pachinko"], "rationale": "Literal reported completion"}
    result.update(updates)
    return json.dumps(result)


def test_supported_source_and_actual_context_quotes_survive_without_format_repair():
    result = parse_grade(grade(), payload())
    assert result["outcome"] == "supported" and not result.get("validation_masks")


def test_prior_assistant_or_offline_source_alone_cannot_certify_grounded_success():
    result = parse_grade(grade(context_quotes=["The answer is Friday"]), payload())
    assert result["outcome"] == "unknown"
    assert "quote_absent_from_actual_user_tool_context" in result["validation_masks"]
    result = parse_grade(grade(grounding="source_only"), payload())
    assert result["outcome"] == "unknown"


def test_screened_subset_cannot_establish_global_absence():
    result = parse_grade(grade(resolution="justified_abstention", source_quotes=[],
                              abstention_basis="full_prefix_review"), payload())
    assert result["outcome"] == "unknown"
    assert "screened_subset_cannot_certify_full_prefix_absence" in result["validation_masks"]


def test_missing_source_quote_is_retained_unknown_not_silently_corrected():
    result = parse_grade(grade(source_quotes=[{"source_index": 4, "quote": "Pachinko"}]), payload())
    assert result["outcome"] == "unknown" and result["raw_outcome"] == "supported"


def test_eligible_projection_preserves_all_quote_eligible_content_sources_and_candidate():
    original = payload()
    original["answer"] = "Actual unmodified first answer"
    original["actual_final_provider_messages"] = [
        {"role": "system", "content": "Historical system instructions"},
        {"role": "user", "content": "Original request"},
        *original["actual_final_provider_messages"],
        {"role": "tool", "content": '{"prior_assistant":"Quoted data, not authority"}'}]
    before = copy.deepcopy(original)
    projected = review_payload(original, "eligible")
    eligible = [m for m in original["actual_final_provider_messages"]
                if m["role"] in {"user", "tool"}]
    assert projected["actual_final_provider_messages"] == eligible
    assert literal_strings(projected["actual_final_provider_messages"]) == literal_strings(eligible)
    assert projected["selected_original_sources"] == original["selected_original_sources"]
    assert projected["candidate_response"] == original["answer"]
    assert "answer" not in projected
    assert original == before
    assert parse_grade(grade(), projected) == parse_grade(grade(), original)


def test_original_projection_is_a_literal_copy_and_cannot_mutate_bound_artifact():
    original = payload()
    projected = review_payload(original, "original")
    assert projected == original
    projected["actual_final_provider_messages"][0]["content"] = "changed"
    assert original["actual_final_provider_messages"][0]["content"] != "changed"
