"""Passive task conditions apply without memory_state or a semantic classifier."""

from __future__ import annotations

import json

import pytest

from milai_lab.methods.contextual_memory.query_context import scope_result
from milai_lab.methods.contextual_user_memory import ContextualMemory, Observation


def test_unanchored_state_filters_remain_unknown_until_trusted_turn_input() -> None:
    mem = ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, state_policy="optional",
    )
    mem.start_task("session", "Where does this apply?")
    source = mem.publish(Observation("one", "Home after 2024", "user", "fixture"))
    claim = mem.save(content="Applies at home", source_ref=source,
                     conditions={"setting": "home"}, valid_from="2024-01-01")["record"]["ref"]
    mem.update_state(conditions={"setting": "home"}, valid_at="2024-06-01")
    ungrounded = mem.read(claim)
    assert ungrounded["applicability"] == "PENDING"
    projection = mem.search("Applies at home")["query_projection"]
    assert projection["filters"]["valid_at"] == ""
    assert projection["sources"]["state_valid_at"] == "unverified_not_applied"
    assert projection["sources"]["conditions"]["state_unverified"] == ["setting"]
    mem.advance_turn("Is home applicable?", conditions={"setting": "home"},
                     valid_at="2024-06-01")
    assert mem.read(claim)["applicability"] == "USABLE"


@pytest.mark.parametrize("profile", ["ordinary", "support"])
def test_condition_match_mismatch_unknown_and_task_scope(profile: str) -> None:
    mem = ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, state_policy="off", profile=profile,
    )
    mem.start_task("one", "Are home visits possible?", task_valid_at="2024-06-01")
    source = mem.publish(Observation("a", "Home visits are possible", "user", "fixture"))
    if profile == "ordinary":
        claim = mem.save(
            content="Available for home visits", source_ref=source,
            conditions={"setting": "home"},
        )["record"]["ref"]
    else:
        result = mem.save(changeset={"groups": [{"operations": [
            {"op": "claim", "alias": "new:c", "content": "Available for home visits",
             "conditions": {"setting": "home"}},
            {"op": "justification", "target_ref": "new:c", "polarity": "support",
             "items": [{"ref": source}], "conditions": {"setting": "home"}},
        ]}]})
        claim = result["changeset"]["aliases"]["new:c"]
    missing = mem.read(claim)
    assert missing["applicability"] == "PENDING"
    assert missing["applicability_reasons"][0]["verdict"] == "UNKNOWN"
    if profile == "support":
        assert missing["support_status"] == "PENDING"
    matched = mem.read(claim, condition_evidence=[{
        "key": "setting", "value": "home", "basis": "visible_question", "quote": "home",
    }])
    assert matched["applicability"] == "USABLE"
    assert matched["applicability_reasons"][0]["evidence"][0]["basis"] == "visible_question"
    if profile == "support":
        assert matched["support_status"] == "USABLE"
    assert mem.state.valid_at == "2024-06-01" and mem.state.known_at == ""
    same = ContextualMemory.restore(mem.checkpoint(), user_id="alice", embed=mem.embed)
    assert same.read(claim)["applicability"] == "USABLE"
    assert "condition_evidence" not in json.dumps(mem.checkpoint(include_task=False))
    same.start_task("two", "Can I visit the office?", task_conditions={"setting": "office"})
    mismatch = same.read(claim)
    assert mismatch["applicability"] == "UNUSABLE"
    assert mismatch["applicability_reasons"][0]["verdict"] == "MISMATCH"
    assert same._rank("home visits", sources=False).refs == []
    same.start_task("three", "Where now?")
    assert same.read(claim)["applicability"] == "PENDING"


def test_visible_source_and_inference_evidence_are_checked_and_traced() -> None:
    mem = ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, state_policy="off",
    )
    mem.start_task("one", "What setting?", task_conditions={"setting": "home"})
    source = mem.publish(Observation("a", "The setting is office", "user", "fixture"))
    claim = mem.save(content="Office note", conditions={"setting": "office"})["record"]["ref"]
    cited = {"key": "setting", "value": "office", "basis": "visible_source",
             "basis_ref": source, "quote": "setting is office"}
    with pytest.raises(ValueError, match="SOURCE_QUOTE_NOT_VISIBLE"):
        mem.read(claim, condition_evidence=[cited])
    mem.read(source, length=3)
    with pytest.raises(ValueError, match="SOURCE_QUOTE_NOT_VISIBLE"):
        mem.read(claim, condition_evidence=[cited])
    mem.read(source)
    disputed = mem.read(claim, condition_evidence=[cited])
    assert disputed["applicability"] == "PENDING"
    assert disputed["applicability_reasons"][0]["verdict"] == "CONFLICT"
    mem.start_task("two", "Maybe office?")
    inferred = mem.search("Office note", condition_evidence=[{
        "key": "setting", "value": "office", "basis": "inference",
        "reason": "The current question suggests office, but does not state it as fact.",
    }])
    assert inferred["materials"][0]["applicability"] == "USABLE"
    assert mem.read(claim)["applicability_reasons"][0]["evidence"][0]["inferred"] is True


@pytest.mark.parametrize("profile", ["ordinary", "support"])
def test_unknown_condition_definition_is_rejected_before_any_retention(profile: str) -> None:
    mem = ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, profile=profile,
    )
    source = mem.publish(Observation("a", "Original claim", "user", "fixture"))
    before = mem.checkpoint()
    with pytest.raises(ValueError, match="UNKNOWN_CONDITION_DEFINITION"):
        if profile == "ordinary":
            mem.save(content="A claim", source_ref=source,
                     conditions={"status": "new_observation"})
        else:
            mem.save(changeset={"groups": [{"operations": [
                {"op": "claim", "content": "A claim", "source_refs": [source],
                 "conditions": {"status": "new_observation"}},
            ]}]})
    assert mem.checkpoint() == before
    assert source not in mem.retained
    with pytest.raises(ValueError, match="UNKNOWN_CONDITION_DEFINITION"):
        mem.start_task("next", "Question", task_conditions={"status": "current"})


@pytest.mark.parametrize("profile", ["ordinary", "support"])
def test_invalid_date_rejected_and_unknown_boundary_remains_pending(
    profile: str,
) -> None:
    mem = ContextualMemory(
        "alice", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, state_policy="off", profile=profile,
    )
    mem.start_task("dated", "What applies?", task_valid_at="2026-09-24")
    source = mem.publish(Observation("a", "Current preference", "user", "fixture"))
    if profile == "ordinary":
        with pytest.raises(ValueError, match="INVALID_VALID_UNTIL"):
            mem.save(
                content="Current preference", source_ref=source,
                valid_from="2025-01-01", valid_until="present",
            )
        assert source not in mem.retained
        claim = mem.save(
            content="Current preference", source_ref=source,
            valid_from="2025-01-01", uncertain_end=True,
        )["record"]["ref"]
    else:
        with pytest.raises(ValueError, match="INVALID_VALID_UNTIL"):
            mem.save(changeset={"groups": [{"operations": [
                {"op": "claim", "alias": "new:c", "content": "Current preference",
                 "valid_from": "2025-01-01", "valid_until": "present"},
            ]}]})
        saved = mem.save(changeset={"groups": [{"operations": [
            {"op": "claim", "alias": "new:c", "content": "Current preference",
             "valid_from": "2025-01-01", "uncertain_end": True},
            {"op": "justification", "target_ref": "new:c", "polarity": "support",
             "items": [{"ref": source}]},
        ]}]})
        claim = saved["changeset"]["aliases"]["new:c"]
    current = mem.read(claim)
    assert current["applicability"] == "PENDING"
    assert current["applicability_reasons"][-1]["verdict"] == "UNKNOWN_DATE"
    assert mem.read(claim, valid_at="2024-01-01")["applicability"] == "UNUSABLE"
    assert scope_result(
        {}, "present", "2026-01-01", mem.state.query_context, {}, "2026-09-24",
    )["status"] == "UNUSABLE"
