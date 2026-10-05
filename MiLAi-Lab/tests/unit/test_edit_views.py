"""Meaningful read-only view checks; synthetic engineering evidence only."""

from __future__ import annotations

import copy
from typing import Any

from milai_lab.analysis.edit_views import grounding_sources, maintenance_views


def row(content: str, revision: int, units: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "record",
        "ok": True,
        "value": {
            "revision": revision,
            "content": content,
            "edit_state": {
                "units": units,
                "relations": [
                    {
                        "relation_type": "modifies",
                        "source_unit": "condition",
                        "target_unit": "claim",
                        "evidence_refs": [],
                    }
                ]
                if len(units) > 1
                else [],
            },
        },
    }


def test_delta_retains_existing_scope_and_excludes_unrelated_unchanged_claim() -> None:
    condition = {"unit_id": "condition", "role": "condition", "text": "On weekdays"}
    claim = {"unit_id": "claim", "role": "content", "text": "Two reviewers"}
    unrelated = {"unit_id": "other", "role": "content", "text": "Owner is Kai"}
    before = [row("old", 1, [condition, claim, unrelated])]
    after = [row("new", 2, [condition, {**claim, "text": "Three reviewers"}, unrelated])]
    preserved = copy.deepcopy((before, after))
    view = maintenance_views(before, after, [{"ok": True, "id": "record"}], ["new"], [])
    delta = view["delta_view"][0]
    assert [u["text"] for u in delta["new_or_changed_units"]] == ["Three reviewers"]
    assert {u["text"] for u in delta["necessary_current_context"]} == {
        "On weekdays",
        "Three reviewers",
    }
    assert [u["text"] for u in delta["removed_or_replaced_units"]] == ["Two reviewers"]
    assert (before, after) == preserved
    assert view["official_extracted_compat"] == ["new"]


def test_no_change_stays_in_official_view_but_has_no_new_claim() -> None:
    state = [row("same", 1, [{"unit_id": "claim", "role": "content", "text": "same"}])]
    view = maintenance_views(state, state, [{"ok": True, "id": "record"}], ["same"], [])
    assert view["official_extracted_compat"] == ["same"]
    assert view["delta_view"] == []
    assert len(view["no_change"]) == 1


def test_relation_removal_is_visible_even_when_unit_texts_are_unchanged() -> None:
    units = [
        {"unit_id": "condition", "role": "condition", "text": "On weekdays"},
        {"unit_id": "claim", "role": "content", "text": "Two reviewers"},
    ]
    before = [row("qualified", 1, units)]
    after = [row("separate", 2, units)]
    after[0]["value"]["edit_state"]["relations"] = []
    view = maintenance_views(before, after, [{"ok": True, "id": "record"}], ["separate"], [])
    delta = view["delta_view"][0]
    assert delta["new_or_changed_units"] == []
    assert delta["new_or_changed_relations"] == []
    assert delta["removed_or_replaced_relations"] == before[0]["value"]["edit_state"]["relations"]


def test_rewritten_ids_do_not_duplicate_identical_text_as_new_claims() -> None:
    before = [row("same", 1, [{"unit_id": "claim", "role": "content", "text": "same"}])]
    after = [row("same", 2, [{"unit_id": "new", "role": "content", "text": "same"}])]
    view = maintenance_views(before, after, [{"ok": True, "id": "record"}], ["same"], [])
    assert view["delta_view"][0]["new_or_changed_units"] == []
    assert view["delta_view"][0]["unchanged_text_unit_count"] == 1


def test_missing_old_source_body_is_unknown_not_grounded_by_new_body() -> None:
    units = [
        {
            "unit_id": "claim",
            "role": "content",
            "text": "claim",
            "evidence_refs": [
                {"evidence_id": "old", "source_ref": "past", "start": 0, "end": 5},
                {"evidence_id": "new", "source_ref": "current", "start": 0, "end": 3},
            ],
        }
    ]
    payload = grounding_sources(
        [row("claim", 1, units)],
        {
            "current": {"role": "user", "content": "now source", "observed_at": "today"},
        },
    )
    assert payload["missing_old_support"] == [{"evidence_id": "old", "status": "UNKNOWN"}]
    assert payload["cited_bodies"][0]["text"] == "now"
