from dataclasses import replace

import pytest

from milai_lab.methods.state_attention import (
    AttentionLimits,
    AttentionState,
    CoverageReview,
    StateField,
    decide_attention,
    question_digest,
)
from milai_lab.methods.state_focus import SourceSnapshot, SourceUnit


def fixture(*, conflict=False, coverage="SUFFICIENT"):
    snapshot = SourceSnapshot(
        "scope",
        tuple(
            SourceUnit(ref, "1", "scope", text)
            for ref, text in (("a", "é"), ("b", "contradiction"), ("c", "irrelevant"))
        ),
    )
    state = AttentionState(
        "task",
        "scope",
        question_digest("question"),
        snapshot.sha256,
        (
            StateField("memory_intentions", "ACTOR", 1, 10, "review:relevance", snapshot.units[:1]),
            StateField(
                "open_conflicts",
                "HOST",
                1,
                10,
                "review:conflict",
                snapshot.units[:2] if conflict else (),
            ),
        ),
    )
    review = CoverageReview(
        state.sha256,
        snapshot.sha256,
        ("a", "b") if conflict else ("a",),
        coverage,
        "review:coverage",
        2,
        10,
    )
    return dict(
        task_id="task",
        question="question",
        sequence=3,
        snapshot=snapshot,
        baseline_ids=("a", "b", "c"),
        state=state,
        coverage=review,
        expansion_attempts=0,
        check_source=lambda _: "ELIGIBLE",
    )


def ids(result):
    return tuple(s["source_id"] for s in result["selected_sources"])


def test_focus_is_deterministic_preserves_exact_sources_and_does_not_claim_effect():
    inputs = fixture()
    first = decide_attention(**inputs)
    assert first == decide_attention(**inputs)
    assert (first["mode"], first["action"], ids(first)) == ("FOCUS", "CONTEXT", ("a",))
    assert first["selected_bytes"] == 2  # UTF-8 bytes, not characters or reported tokens.
    assert first["selected_sources"] == [inputs["snapshot"].units[0].reference()]
    assert first["observable_use"] == "UNKNOWN"
    assert first["claim_ceiling"] == "POLICY_DECISION_NOT_EFFECT"
    assert first["retrieval"] is None


def test_supported_conflict_preserves_both_sides_even_without_focus_or_coverage():
    inputs = fixture(conflict=True, coverage="GAP")
    result = decide_attention(**inputs)
    assert result["mode"] == "CONFLICT"
    assert result["action"] == "CONTEXT"
    assert ids(result) == ("a", "b")
    assert result["retrieval"] is None
    inputs["state"] = replace(inputs["state"], fields=inputs["state"].fields[1:])
    inputs["coverage"] = None
    result = decide_attention(**inputs)
    assert ids(result) == ("a", "b")
    assert result["coverage"] == "UNKNOWN"


@pytest.mark.parametrize("limits", [AttentionLimits(max_sources=1), AttentionLimits(max_bytes=2)])
def test_conflict_is_never_silently_truncated_to_one_side(limits):
    result = decide_attention(**fixture(conflict=True), limits=limits)
    assert result["action"] == "ABSTAIN_MEMORY"
    assert result["reason"] == "CONFLICT_OVER_BUDGET"
    assert ids(result) == ()


def test_known_gap_requests_one_bounded_expansion_and_failure_does_not_reset_it():
    inputs = fixture(coverage="GAP")
    result = decide_attention(**inputs, limits=AttentionLimits(expansion_limit=2))
    assert result["mode"] == "EXPLORE"
    assert result["action"] == "RETRIEVE_ONCE"
    assert result["retrieval"] == {
        "query": "question",
        "scope": "scope",
        "exclude_source_ids": ["a", "b", "c"],
        "limit": 2,
        "max_bytes": 65536 - sum(len(s.content.encode()) for s in inputs["snapshot"].units),
    }
    # Runner debits before attempting retrieval, including an exception/no new result.
    inputs["expansion_attempts"] = 1
    second = decide_attention(**inputs)
    assert second["action"] == "ABSTAIN_MEMORY"
    assert second["retrieval"] is None
    assert second["reason"] == "EXPANSION_EXHAUSTED"
    assert ids(second) == ()


def test_expansion_result_requires_new_review_before_convergence():
    inputs = fixture(coverage="GAP")
    assert decide_attention(**inputs)["action"] == "RETRIEVE_ONCE"
    old = inputs["snapshot"]
    inputs["snapshot"] = SourceSnapshot(
        old.scope, (*old.units, SourceUnit("d", "1", "scope", "new"))
    )
    inputs["expansion_attempts"] = 1
    stale = decide_attention(**inputs)
    assert stale["coverage"] == "UNKNOWN"
    assert stale["retrieval"] is None
    assert stale["field_status"]["open_conflicts"] == "UNKNOWN"
    # A new, caller-authenticated review is necessary; the policy never refreshes it.
    inputs["state"] = replace(inputs["state"], snapshot_sha256=inputs["snapshot"].sha256)
    inputs["coverage"] = replace(
        inputs["coverage"],
        snapshot_sha256=inputs["snapshot"].sha256,
        state_sha256=inputs["state"].sha256,
        status="SUFFICIENT",
    )
    fresh = decide_attention(**inputs)
    assert fresh["action"] == "CONTEXT"
    assert fresh["coverage"] == "SUFFICIENT"
    assert fresh["retrieval"] is None


@pytest.mark.parametrize(
    "change", ["absent", "task", "scope", "question", "stale", "future", "owner", "provenance"]
)
def test_missing_stale_cross_task_or_unsupported_state_uses_simple_baseline(change):
    inputs = fixture(coverage="GAP")
    state = inputs["state"]
    if change == "absent":
        inputs["state"] = None
    elif change in {"task", "scope", "question"}:
        field = {"task": "task_id", "scope": "scope", "question": "input_sha256"}[change]
        inputs["state"] = replace(state, **{field: "changed"})
    else:
        changes = {
            "stale": {"valid_through_sequence": 2},
            "future": {"observed_sequence": 3},
            "owner": {"owner": "EVALUATOR"},
            "provenance": {"artifact_ref": None},
        }
        inputs["state"] = replace(
            state, fields=(replace(state.fields[0], **changes[change]), state.fields[1])
        )
    result = decide_attention(**inputs)
    assert ids(result) == ("a", "b", "c")
    assert result["retrieval"] is None
    assert result["coverage"] == "UNKNOWN"


@pytest.mark.parametrize(
    "change", ["absent", "unknown", "pool_not_selection", "stale", "future", "provenance"]
)
def test_unknown_or_mismatched_coverage_does_not_authorize_expansion(change):
    inputs = fixture(coverage="GAP")
    changes = {
        "unknown": {"status": "UNKNOWN"},
        "pool_not_selection": {"selected_ids": ("a", "b", "c")},
        "stale": {"valid_through_sequence": 2},
        "future": {"observed_sequence": 3},
        "provenance": {"artifact_ref": None},
    }
    inputs["coverage"] = (
        None if change == "absent" else replace(inputs["coverage"], **changes[change])
    )
    result = decide_attention(**inputs)
    assert result["reason"] == "BASELINE_COVERAGE_UNKNOWN"
    assert result["retrieval"] is None


@pytest.mark.parametrize("eligibility", ["DENIED", "UNKNOWN", None, {}])
def test_denied_unknown_or_invalid_eligibility_is_never_selected(eligibility):
    inputs = fixture(conflict=True)
    inputs["check_source"] = lambda unit: eligibility if unit.source_id == "b" else "ELIGIBLE"
    result = decide_attention(**inputs)
    assert "b" not in ids(result)
    assert result["field_status"]["open_conflicts"] == "UNKNOWN"
    assert result["coverage"] == "UNKNOWN"


def test_eligibility_rechecked_on_every_decision_and_errors_are_unknown():
    inputs = fixture()
    assert ids(decide_attention(**inputs)) == ("a",)

    def unavailable(_):
        raise OSError("unavailable")

    inputs["check_source"] = unavailable
    result = decide_attention(**inputs)
    assert result["action"] == "ABSTAIN_MEMORY"
    assert ids(result) == ()
    assert set(result["eligibility"].values()) == {"UNKNOWN"}


def test_changed_version_or_body_invalidates_state_not_just_coverage():
    inputs = fixture()
    old = inputs["snapshot"]
    inputs["snapshot"] = SourceSnapshot(
        old.scope, (replace(old.units[0], content="changed"), *old.units[1:])
    )
    result = decide_attention(**inputs)
    assert result["field_status"]["memory_intentions"] == "UNKNOWN"
    assert result["coverage"] == "UNKNOWN"


def test_known_empty_conflict_is_distinct_from_absent_or_one_sided_conflict():
    inputs = fixture()
    assert decide_attention(**inputs)["reason"] == "REVIEWED_FOCUS"
    state = inputs["state"]
    inputs["state"] = replace(state, fields=state.fields[:1])
    assert decide_attention(**inputs)["reason"] == "BASELINE_STATE_UNKNOWN"
    inputs["state"] = replace(
        state, fields=(state.fields[0], replace(state.fields[1], sources=state.fields[0].sources))
    )
    assert decide_attention(**inputs)["reason"] == "BASELINE_STATE_UNKNOWN"


@pytest.mark.parametrize(
    "changes",
    [
        {"question": " "},
        {"sequence": True},
        {"expansion_attempts": -1},
        {"expansion_attempts": 2},
        {"limits": AttentionLimits(max_sources=0)},
        {"limits": AttentionLimits(max_bytes=-1)},
        {"baseline_ids": ("missing",)},
        {"baseline_ids": ("a", "a")},
    ],
)
def test_invalid_inputs_fail_closed(changes):
    with pytest.raises(ValueError, match="INVALID_ATTENTION"):
        decide_attention(**(fixture() | changes))


def test_baseline_and_focus_share_byte_count_and_source_count_caps():
    inputs = fixture()
    inputs["state"] = None
    result = decide_attention(**inputs, limits=AttentionLimits(max_sources=1, max_bytes=2))
    assert ids(result) == ("a",)
    assert result["selected_bytes"] == 2
    assert result["coverage"] == "UNKNOWN"


def test_full_snapshot_cannot_request_expansion_past_shared_source_cap():
    inputs = fixture(coverage="GAP")
    old = inputs["snapshot"]
    inputs["snapshot"] = SourceSnapshot(
        old.scope, (*old.units, *(SourceUnit(f"extra:{n}", "1", old.scope, "x") for n in range(29)))
    )
    inputs["state"] = replace(inputs["state"], snapshot_sha256=inputs["snapshot"].sha256)
    inputs["coverage"] = replace(
        inputs["coverage"],
        snapshot_sha256=inputs["snapshot"].sha256,
        state_sha256=inputs["state"].sha256,
    )
    result = decide_attention(**inputs)
    assert result["action"] == "ABSTAIN_MEMORY"
    assert result["retrieval"] is None


def test_duplicate_and_unknown_state_fields_are_rejected():
    inputs = fixture()
    state = inputs["state"]
    for extra in (state.fields[0], replace(state.fields[0], name="hidden_native_result")):
        inputs["state"] = replace(state, fields=(*state.fields, extra))
        with pytest.raises(ValueError, match="INVALID_ATTENTION_STATE_FIELDS"):
            decide_attention(**inputs)


def test_conflict_reserves_capacity_before_earlier_relevant_nonconflict_source():
    inputs = fixture(conflict=True)
    state = inputs["state"]
    inputs["state"] = replace(
        state,
        fields=(
            state.fields[0],
            replace(state.fields[1], sources=inputs["snapshot"].units[1:]),
        ),
    )
    result = decide_attention(**inputs, limits=AttentionLimits(max_sources=2))
    assert result["mode"] == "CONFLICT"
    assert ids(result) == ("b", "c")


def test_full_byte_capacity_does_not_request_unusable_expansion():
    inputs = fixture(coverage="GAP")
    old = inputs["snapshot"]
    units = (old.units[0], replace(old.units[1], content="x" * 65534))
    inputs["snapshot"] = SourceSnapshot(old.scope, units)
    inputs["baseline_ids"] = ("a", "b")
    inputs["state"] = replace(inputs["state"], snapshot_sha256=inputs["snapshot"].sha256)
    inputs["coverage"] = replace(
        inputs["coverage"],
        snapshot_sha256=inputs["snapshot"].sha256,
        state_sha256=inputs["state"].sha256,
    )
    result = decide_attention(**inputs)
    assert result["action"] == "ABSTAIN_MEMORY"
    assert result["retrieval"] is None


def test_revoked_unselected_pool_member_invalidates_derived_state_and_coverage():
    inputs = fixture()
    assert ids(decide_attention(**inputs)) == ("a",)
    inputs["check_source"] = lambda unit: "DENIED" if unit.source_id == "c" else "ELIGIBLE"
    result = decide_attention(**inputs)
    assert result["reason"] == "BASELINE_STATE_UNKNOWN"
    assert result["field_status"]["memory_intentions"] == "UNKNOWN"
    assert result["coverage"] == "UNKNOWN"
    assert ids(result) == ("a", "b")
