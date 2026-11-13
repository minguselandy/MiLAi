"""Original truth and actual visibility are required; screened absence is not certified."""
import json

from review_continuous_source_outcomes import parse_grade


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
