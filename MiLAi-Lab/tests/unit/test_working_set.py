"""Evidence delivery coverage keeps current, history, wording and live reads distinct."""

from __future__ import annotations

from milai_lab.memory.working_set import admit_refs, empty_view, read_requirement_status


def test_current_and_original_wording_do_not_satisfy_history_or_live_query() -> None:
    view = {
        **empty_view(),
        "read_goal": {"purpose": "Compare before the exception and check the object again.",
                      "evidence": ["saved_history", "live_business"]},
    }
    actual = [{"type": "record", "version_view": "current_at_snapshot"},
              {"type": "fragment", "origin": "get_reservation"}]
    result = read_requirement_status(view, actual)
    assert result["pending_evidence"] == ["saved_history", "live_business"]
    assert result["delivered_evidence"] == ["current_interpretation", "original_source"]
    assert result["answer_sufficiency"] == "unchecked"


def test_a_history_page_cannot_close_actual_remaining_pages() -> None:
    view = {**empty_view(), "read_goal": {"purpose": "Find the revoked exception.",
            "evidence": ["saved_history"]}, "pending_refs": ["save:actual:3"]}
    continuation = {"tool": "read_revisions", "arguments": {
        "record_id": "actual", "continuation": "actual-issued-page-2"}}
    result = read_requirement_status(view, [
        {"type": "record", "version_view": "historical_exact_revision", "revision": 1},
    ], continuations=[continuation])
    assert result["status"] == "has_delivery_gaps"
    assert result["continuations"] == [continuation]
    assert result["pending_refs"] == ["save:actual:3"]
    assert result["coverage"] == "delivery_only"
    result["continuations"][0]["arguments"]["record_id"] = "changed-output"
    assert continuation["arguments"]["record_id"] == "actual"


def test_legacy_prose_does_not_guess_query_intent_from_now_or_history() -> None:
    view = {**empty_view(), "read_goal": "Read history and now query the latest status."}
    result = read_requirement_status(view, [])
    assert result["purpose"] == view["read_goal"]
    assert result["required_evidence"] == []
    assert result["status"] == "purpose_untyped"


def test_typed_read_goal_is_request_state_without_mutable_input_alias() -> None:
    view = empty_view()
    goal = {"purpose": "Read the actual saved revision.", "evidence": ["saved_history"]}
    updated = admit_refs(view, [], read_goal=goal)
    goal["evidence"].append("live_business")
    assert updated["read_goal"]["evidence"] == ["saved_history"]
    assert view == empty_view()
