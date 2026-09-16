"""Behavioral contracts for the shared RWC loop; scripted responses, no network."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from milai_lab.methods.hiagent import HiAgentError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from hiagent_terminal_session import HiAgentTerminalSession


def proposal(
    note=None,
    *,
    puts=(),
    retire=(),
    selected=(),
    kind="ACT",
    refs=(),
    delivery=None,
    start=None,
    length=None,
):
    update = (
        None
        if note is None and not puts and not retire
        else {"working_note": note, "put_cards": list(puts), "retire_cards": list(retire)}
    )
    route = {"kind": kind, "refs": list(refs), "delivery": delivery}
    if start is not None:
        route["start"] = start
    if length is not None:
        route["length"] = length
    return json.dumps(
        {
            "workspace_update": update,
            "frame": {
                "question": "Current question",
                "intent": "Next useful work",
                "selected_refs": list(selected),
            },
            "dispatch": route,
        }
    )


def card(text, handle=None, refs=()):
    return {"handle": handle, "text": text, "source_refs": list(refs)}


def actor(command="inspect", subgoal=None, action="exec", **arguments):
    return json.dumps(
        {"subgoal": subgoal, "action": action, "arguments": arguments or {"command": command}}
    )


def make(
    tmp_path, outputs=(), *, method="MILAI_RWC", goal="Current real goal", max_calls=64, **options
):
    replies = iter(outputs)
    requests, effects, events = [], [], []

    def generate(request):
        requests.append(request)
        reply = next(replies)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def terminal(command, timeout):
        effects.append(command)
        return {"stdout": command, "return_code": 0}

    session = HiAgentTerminalSession(
        instruction=goal,
        binding="task",
        root=tmp_path,
        terminal=terminal,
        generate=generate,
        method=method,
        max_calls=max_calls,
        emit=events.append,
        control_options={"use_summary_cache": False, **options},
    )
    return session, requests, effects, events


def body(request):
    return json.loads(request.messages[-1]["content"])


@pytest.mark.parametrize("method", ["WORKSPACE_SIMPLE", "MILAI_RWC"])
def test_batched_control_keeps_actor_feedback_and_consumes_pending_batch(tmp_path, method):
    s, requests, effects, _ = make(
        tmp_path,
        ["{}", actor("first"), actor("second"), actor("third"),
         proposal("Revise the affected boundary", selected=["H001"]), actor("fourth")],
        method=method, feedback_batch_size=3,
    )
    for _ in range(3):
        s.host.step()
    assert s.host.maintained_pairs == 0 and s.host.actor_seen_pairs == 2
    assert body(requests[2])["new_event_ids"] == [0]
    assert body(requests[3])["new_event_ids"] == [1]
    s.host.step()
    assert [r.kind for r in requests] == [
        "maintenance", "actor", "actor", "actor", "maintenance", "actor"
    ]
    assert body(requests[4])["new_event_ids"] == [0, 1, 2]
    assert body(requests[5])["new_event_ids"] == [2]
    assert body(requests[5])["workspace"]["working_note"] == "Revise the affected boundary"
    assert body(requests[5])["selected_sources"][0]["ref"] == "H001"
    assert effects == ["first", "second", "third", "fourth"]


def test_external_feedback_and_context_boundary_force_control_before_batch_fills(tmp_path):
    s, requests, _, _ = make(
        tmp_path,
        ["{}", actor("first", "Inspect"), "{}", actor("second", "Change"),
         "{}", actor("third")],
        feedback_batch_size=99,
    )
    s.host.step()
    s.host.observe("The user revised a constraint.")
    s.host.step()
    s.host.step()
    assert [body(r)["reason"] for r in requests if r.kind == "maintenance"] == [
        "initial", "external_feedback", "context_boundary"
    ]
    assert body(requests[3])["external_observations"] == ["The user revised a constraint."]


def test_actor_recall_forces_control_without_losing_unmaintained_feedback(tmp_path):
    s, requests, effects, _ = make(
        tmp_path,
        ["{}", actor("first"), actor(action="retrieve", refs=["H001"]),
         "{}", actor("next")],
        feedback_batch_size=4,
    )
    for _ in range(3):
        s.host.step()
    assert [r.kind for r in requests] == ["maintenance", "actor", "actor", "maintenance", "actor"]
    assert body(requests[3])["reason"] == "recall"
    assert body(requests[3])["new_event_ids"] == [0]
    assert body(requests[4])["new_event_ids"] == []
    assert body(requests[4])["recall_observations"][0]["refs"] == ["H001"]
    assert effects == ["first", "next"]


@pytest.mark.parametrize("method", ["WORKSPACE_SIMPLE", "MILAI_RWC"])
def test_new_feedback_current_history_and_focus_share_one_source_page(tmp_path, method):
    s, requests, effects, _ = make(
        tmp_path,
        [
            proposal(),
            actor("UNIQUE_SOURCE_SENTINEL", "Inspect"),
            proposal(selected=["H001", "seg:1"]),
            actor("next"),
        ],
        method=method,
    )
    s.host.step()
    s.host.step()
    value = body(requests[-1])
    assert len(value["materials"]) == 1
    assert value["new_event_ids"] == [0]
    assert value["selected_sources"][0]["ref"] == "H001"
    assert value["observations"][0]["observation"]["ref"] == "H001"
    assert effects == ["UNIQUE_SOURCE_SENTINEL", "next"]


def test_cards_exist_before_segments_and_untouched_cards_survive_updates(tmp_path):
    s, requests, _, _ = make(
        tmp_path,
        [
            proposal("Start", puts=[card("First lead"), card("Second lead")]),
            actor("one", "Inspect"),
            proposal("Refine", puts=[card("First lead corrected", "card:1")]),
            actor("two"),
            proposal(retire=["card:1"]),
            actor("three"),
        ],
    )
    for _ in range(3):
        s.host.step()
    cards = s.host.workspace.cards
    assert cards["card:1"].retired and cards["card:1"].revision == 3
    assert cards["card:2"].text == "Second lead" and cards["card:2"].revision == 1
    assert {c["handle"] for c in body(requests[1])["workspace"]["cards"]} == {"card:1", "card:2"}
    assert not body(requests[-1])["workspace"]["cards"]


def test_controller_recall_reenters_control_and_does_not_swallow_original_feedback(tmp_path):
    s, requests, effects, events = make(
        tmp_path,
        [
            proposal(),
            actor("REAL_CONTRADICTION", "Inspect"),
            proposal(kind="RECALL", refs=["H001"]),
            proposal("Reconsider with actual source"),
            actor("continue"),
        ],
    )
    s.host.step()
    s.host.step()
    assert [r.kind for r in requests] == [
        "maintenance",
        "actor",
        "maintenance",
        "maintenance",
        "actor",
    ]
    assert body(requests[3])["reason"] == "recall"
    assert "REAL_CONTRADICTION" in body(requests[-1])["materials"][0]["text"]
    assert body(requests[-1])["new_event_ids"] == [0]
    assert len(body(requests[-1])["materials"]) == 1
    assert effects == ["REAL_CONTRADICTION", "continue"]
    assert sum(e["event"] == "SOURCE_RECALLED" for e in events) == 1


def test_actor_segment_return_uses_same_recall_loop(tmp_path):
    s, requests, effects, _ = make(
        tmp_path,
        [
            proposal(),
            actor("OLD", "First"),
            proposal(),
            actor("NEW", "Second"),
            proposal(),
            actor(action="retrieve", segments=[1]),
            proposal(selected=["seg:1"]),
            actor("recheck"),
        ],
    )
    for _ in range(4):
        s.host.step()
    assert body(requests[-2])["reason"] == "recall"
    assert body(requests[-2])["recall_observations"]
    assert "OLD" in json.dumps(body(requests[-1])["materials"])
    assert effects == ["OLD", "NEW", "recheck"]


def test_recall_limit_returns_control_to_actor_with_original_feedback(tmp_path):
    s, requests, effects, _ = make(
        tmp_path,
        [
            proposal(),
            actor("feedback", "Start"),
            *[proposal(kind="RECALL", refs=["H001"]) for _ in range(3)],
            actor("next"),
        ],
    )
    s.host.step()
    s.host.step()
    assert "NOT_EVIDENCE_EXHAUSTION" in body(requests[-1])["control_feedback"]
    assert effects == ["feedback", "next"]
    assert len(s.host.recall_observations) == 2


def test_final_can_be_delivered_by_controller_without_extra_actor(tmp_path):
    s, requests, effects, _ = make(
        tmp_path,
        [
            proposal(),
            actor(subgoal="Deliver", action="final", text="Draft"),
            proposal(kind="DELIVER", delivery="Scoped actual result"),
        ],
    )
    s.host.step()
    assert not s.tools.finished and not s.tools.raw_receipts
    s.host.step()
    assert s.tools.final_text == "Scoped actual result"
    assert len(requests) == 3 and not effects
    assert s.host.delivery_reviews == 1


def test_continue_after_review_does_not_reset_review_allowance(tmp_path):
    s, requests, effects, _ = make(
        tmp_path,
        [
            proposal(),
            actor(subgoal="Inspect", action="final", text="Draft"),
            proposal("Useful gap"),
            actor("real check", "Check"),
            proposal("Observed result"),
            actor(action="final", text="Bounded result"),
        ],
    )
    for _ in range(3):
        s.host.step()
    assert s.tools.final_text == "Bounded result" and s.host.delivery_reviews == 1
    assert len(requests) == 6 and effects == ["real check"]


@pytest.mark.parametrize("review", ["{}", '{"delivery_proposal":{"text":"echo"}}', "{bad"])
def test_optional_review_without_action_delivers_current_draft_as_unreviewed(tmp_path, review):
    s, requests, effects, events = make(
        tmp_path, ["{}", actor(action="final", text="Current result"), review]
    )
    s.host.step()
    s.host.step()
    assert s.tools.final_text == "Current result" and not effects
    assert len(requests) == 3 and s.host.delivery_status == "UNREVIEWED"
    assert events[-1]["event"] == "DELIVERY_COMPLETED"
    assert body(requests[-1])["delivery_review_active"]


def test_new_feedback_invalidates_draft_before_optional_review(tmp_path):
    s, requests, _, events = make(
        tmp_path,
        ["{}", actor(action="final", text="Old result"),
         proposal(kind="DELIVER"), actor(action="final", text="Incomplete after new evidence")],
        max_calls=4,
    )
    s.host.step()
    s.host.observe("The latest requirement is not satisfied.")
    s.host.step()
    assert s.tools.final_text == "Incomplete after new evidence"
    assert body(requests[2])["delivery_proposal"] is None
    assert body(requests[3])["external_observations"] == [
        "The latest requirement is not satisfied."
    ]
    assert any(e["event"] == "CONTROL_REJECTED" for e in events)


def test_last_slot_is_reserved_for_actor_instead_of_old_segment_summary(tmp_path):
    s, requests, effects, events = make(
        tmp_path,
        ["{}", actor("first", "First"), "{}", actor("second", "Second"),
         actor(action="final", text="Actual work and remaining limitations")],
        max_calls=5, use_summary_cache=True,
    )
    for _ in range(3):
        s.host.step()
    assert [r.kind for r in requests] == ["maintenance", "actor", "maintenance", "actor", "actor"]
    assert effects == ["first", "second"]
    assert s.tools.final_text == "Actual work and remaining limitations"
    assert body(requests[-1])["call_budget"] == {"remaining": 1, "closing": True}
    assert any(e["event"] == "SUMMARY_DEFERRED" for e in events)


def test_draft_does_not_enter_review_without_budget_for_revision(tmp_path):
    s, requests, effects, _ = make(
        tmp_path, ["{}", actor(action="final", text="Result")], max_calls=3
    )
    s.host.step()
    assert s.tools.final_text == "Result" and len(requests) == 2 and not effects
    assert s.host.delivery_status == "UNREVIEWED" and s.host.delivery_reviews == 0


def test_ending_actor_cannot_spend_last_call_starting_another_business_action(tmp_path):
    s, requests, effects, _ = make(tmp_path, [actor("unexecuted write")], max_calls=1)
    s.host.step()
    assert s.host.finished and len(requests) == 1 and not effects
    assert s.host.delivery_status == "INCOMPLETE"
    assert "Task completion is not established" in s.tools.final_text


def test_review_recall_preserves_ending_call_and_does_not_accept_old_draft(tmp_path):
    s, requests, effects, events = make(
        tmp_path,
        ["{}", actor(action="final", text="Old claim"),
         proposal(kind="RECALL", refs=["catalog:sources"]),
         actor(action="final", text="Unable to check the requested history")],
        max_calls=4,
    )
    s.host.step()
    s.host.step()
    assert s.tools.final_text == "Unable to check the requested history" and not effects
    assert "NOT_EVIDENCE_SUFFICIENCY" in body(requests[-1])["control_feedback"]
    assert not any(e["event"] == "SOURCE_RECALLED" for e in events)


def test_unknown_review_call_stops_without_delivering_old_draft(tmp_path):
    s, _, _, _ = make(
        tmp_path, ["{}", actor(action="final", text="Draft"), RuntimeError("unknown usage")]
    )
    s.host.step()
    with pytest.raises(RuntimeError, match="unknown usage"):
        s.host.step()
    assert s.host.halted and not s.tools.finished and s.host.delivery_status is None


@pytest.mark.parametrize(
    "bad",
    [
        '{"dispatch": {}}',
        "[]",
        proposal(kind="DELIVER", delivery="Forbidden"),
        proposal(selected=["seg:1"]),
        proposal(puts=[card("No", "card:91")]),
        proposal(retire=["H001"]),
        proposal(puts=[card("Bad ref", refs=["private/file"])]),
    ],
)
def test_invalid_proposal_is_visible_and_never_commits_partial_cards(tmp_path, bad):
    s, requests, effects, _ = make(tmp_path, [bad, actor("legal", "Start")])
    s.host.step()
    assert s.host.workspace.revision == 0 and not s.host.workspace.cards
    assert body(requests[-1])["control_status"] == "REJECTED_PREVIOUS_WORKSPACE_RETAINED"
    assert len(requests) == 2 and effects == ["legal"]


def test_same_bytes_from_distinct_real_executions_keep_distinct_identities(tmp_path):
    s, requests, _, _ = make(
        tmp_path,
        [
            proposal(),
            actor("same", "First"),
            proposal(),
            actor("same", "Second"),
            proposal(selected=["H001", "H002"]),
            actor("third"),
        ],
    )
    for _ in range(3):
        s.host.step()
    pages = body(requests[-1])["materials"]
    assert {p["ref"] for p in pages} == {"H001", "H002"}
    assert len(pages) == 2


def test_optional_material_capacity_keeps_new_feedback_and_readback_entry(tmp_path):
    s, requests, _, _ = make(
        tmp_path,
        [
            proposal(),
            actor("X" * 100, "First"),
            proposal(),
            actor("Y" * 100, "Second"),
            proposal(selected=["H001"]),
            actor("continue"),
        ],
        page_chars=100,
        material_chars=100,
    )
    for _ in range(3):
        s.host.step()
    value = body(requests[-1])
    assert [p["ref"] for p in value["materials"]] == ["H002"]
    assert value["materials"][0]["next_start"] == 100
    assert value["omitted_material"][0]["ref"] == "H001"
    assert value["new_event_ids"] == [1]


def test_external_contradiction_survives_recall_roundtrip(tmp_path):
    s, requests, _, _ = make(
        tmp_path,
        [
            proposal(),
            actor("first", "Start"),
            proposal(kind="RECALL", refs=["H001"]),
            proposal(),
            actor("next"),
        ],
    )
    s.host.step()
    s.host.observe("NEW_USER_VISIBLE_CONTRADICTION")
    s.host.step()
    assert body(requests[-1])["external_observations"] == ["NEW_USER_VISIBLE_CONTRADICTION"]


def test_unreadable_source_cannot_leak_via_old_raw_pair_or_derived_note(tmp_path):
    s, requests, effects, _ = make(tmp_path, [proposal(), actor("PRIVATE", "Start")])
    s.host.step()
    s.tools.sources["H001"] = replace(s.tools.sources["H001"], eligible=False)
    with pytest.raises(HiAgentError, match="DEPENDENCY_NOT_READABLE"):
        s.host.step()
    assert len(requests) == 2 and effects == ["PRIVATE"]


def test_restore_runs_controller_even_without_new_business_feedback(tmp_path):
    s, _, effects, _ = make(
        tmp_path,
        [
            proposal(),
            actor("once", "Start"),
            proposal(),
            actor(subgoal="Deliver", action="final", text="Draft"),
        ],
    )
    s.host.step()
    s.host.step()
    checkpoint = tmp_path / "saved.json"
    s.save_checkpoint(checkpoint, environment_id="world")
    fresh, requests, new_effects, _ = make(
        tmp_path / "fresh",
        [proposal("New goal"), actor("new work")],
        goal="New legitimate user goal",
    )
    fresh.restore_checkpoint(checkpoint, environment_id="world")
    fresh.host.step()
    assert body(requests[0])["reason"] == "resume"
    assert body(requests[0])["delivery_proposal"] is None
    assert effects == ["once"] and new_effects == ["new work"]
    assert sum(fresh.host.calls.values()) == 6
    assert fresh.host.goal_revision == 2


def test_saved_unseen_feedback_and_cards_survive_fresh_registry(tmp_path):
    s, _, _, _ = make(
        tmp_path,
        [proposal(puts=[card("Remember return point")]), actor("UNMAINTAINED_RESULT", "Start")],
    )
    s.host.step()
    value = s.checkpoint_data(environment_id="world")
    fresh, requests, effects, _ = make(tmp_path / "new", [proposal(), actor("continue")])
    fresh.restore_checkpoint_data(value, environment_id="world")
    fresh.host.step()
    assert fresh.host.workspace.cards["card:1"].text == "Remember return point"
    assert "UNMAINTAINED_RESULT" in json.dumps(body(requests[0])["materials"])
    assert effects == ["continue"] and sum(fresh.host.calls.values()) == 4


def test_summary_cache_reuses_unchanged_source_and_survives_checkpoint(tmp_path):
    s, requests, _, events = make(
        tmp_path,
        [
            proposal(),
            actor("first", "One"),
            proposal(),
            actor("second", "Two"),
            "First segment summary",
            proposal(),
            actor("third"),
            proposal(),
            actor("fourth"),
        ],
        use_summary_cache=True,
    )
    for _ in range(4):
        s.host.step()
    assert sum(r.kind == "summary" for r in requests) == 1
    assert any(e["event"] == "SUMMARY_REUSED" for e in events)
    value = s.checkpoint_data(environment_id="world")
    fresh, requests, _, _ = make(
        tmp_path / "new", [proposal(), actor("continue")], use_summary_cache=True
    )
    fresh.restore_checkpoint_data(value, environment_id="world")
    fresh.host.step()
    assert all(r.kind != "summary" for r in requests)


def test_policy_pair_has_identical_capabilities_and_actor_but_distinct_controller(tmp_path):
    simple, *_ = make(tmp_path / "simple", method="WORKSPACE_SIMPLE")
    candidate, *_ = make(tmp_path / "rwc")
    assert type(simple.host) is type(candidate.host)
    assert simple.actor_policy == candidate.actor_policy
    assert simple.summary_policy != candidate.summary_policy
    left, right = simple.host._contract(), candidate.host._contract()
    for contract in (left, right):
        contract.pop("policy_version")
        contract.pop("policy_hash")
    assert left == right


def test_unknown_generation_stops_without_retry_or_checkpoint(tmp_path):
    s, requests, effects, _ = make(tmp_path, [TimeoutError("unknown")])
    with pytest.raises(TimeoutError):
        s.host.step()
    with pytest.raises(HiAgentError):
        s.checkpoint_data(environment_id="world")
    assert len(requests) == 1 and not effects


def test_revoked_closed_source_blocks_summary_and_checkpoint_before_model_call(tmp_path):
    s, requests, _, _ = make(
        tmp_path,
        [proposal(), actor("PRIVATE", "One"), proposal(), actor("second", "Two")],
        use_summary_cache=True,
    )
    s.host.step()
    s.host.step()
    s.tools.sources["H001"] = replace(s.tools.sources["H001"], eligible=False)
    with pytest.raises(HiAgentError, match="DEPENDENCY_NOT_READABLE"):
        s.checkpoint_data(environment_id="world")
    with pytest.raises(HiAgentError, match="DEPENDENCY_NOT_READABLE"):
        s.host.step()
    assert len(requests) == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("next_card", 1),
        ("new_card_handles", ["card:99"]),
        ("summary_cache", {"99": "f" * 64}),
        ("maintained_recalls", 100),
    ],
)
def test_invalid_new_checkpoint_fields_leave_session_fresh(tmp_path, field, value):
    s, _, _, _ = make(tmp_path, [proposal(puts=[card("Return")]), actor("once", "One")])
    s.host.step()
    artifact = s.checkpoint_data(environment_id="world")
    artifact["host"]["state"][field] = value
    fresh, requests, effects, events = make(tmp_path / "fresh")
    with pytest.raises(HiAgentError, match="INVALID_WORKSPACE_CHECKPOINT"):
        fresh.restore_checkpoint_data(artifact, environment_id="world")
    assert not fresh.host.segments and not fresh.host.initialized
    assert not fresh.tools.raw_receipts and sum(fresh.host.calls.values()) == 0
    assert not requests and not effects and not events


def test_recalled_and_selected_card_have_one_body_per_revision(tmp_path):
    s, requests, _, _ = make(
        tmp_path,
        [
            proposal(puts=[card("ONLY_CARD_BODY")]),
            actor("once", "One"),
            proposal(kind="RECALL", refs=["card:1"]),
            proposal(selected=["card:1"]),
            actor("next"),
        ],
    )
    s.host.step()
    s.host.step()
    value = body(requests[-1])
    assert len(value["workspace"]["cards"]) == 1
    assert value["recall_observations"][0]["cards"] == [{"handle": "card:1", "revision": 1}]


@pytest.mark.parametrize("method", ["WORKSPACE_SIMPLE", "MILAI_RWC"])
def test_first_action_without_optional_label_gets_host_segment(tmp_path, method):
    s, requests, effects, _ = make(tmp_path, [proposal(), actor("once")], method=method)
    s.host.step()
    assert effects == ["once"] and len(requests) == 2
    assert s.host.segments[0].subgoal == "Next useful work"


def test_sparse_updates_preserve_state_and_ignore_act_extras(tmp_path):
    s, _, effects, events = make(tmp_path, ["{}", actor("once")])
    s.host.step()
    assert s.host.workspace.revision == 0 and effects == ["once"]
    s.host._accept(
        json.dumps(
            {
                "workspace_update": {
                    "put_cards": [{"text": "A useful lead", "source_refs": ["H001"]}]
                }
            }
        )
    )
    original = s.host.workspace
    original_card = original.cards["card:1"]
    s.host._accept("{}")
    assert s.host.workspace is original
    s.host._accept(
        json.dumps(
            {
                "workspace_update": {"put_cards": [{"handle": "card:1", "text": "Updated lead"}]},
                "frame": {"selected_refs": ["H001", "H001"]},
                "dispatch": {"kind": "ACT", "refs": ["unknown"], "delivery": "ignored"},
            }
        )
    )
    assert s.host.workspace.cards["card:1"].source_refs == ["H001"]
    assert original_card.text == "A useful lead"
    assert s.host.workspace.frame.selected_refs == ["H001"]
    before = s.host.workspace
    with pytest.raises(HiAgentError, match="UNKNOWN_CARD_HANDLE"):
        s.host._accept(
            json.dumps(
                {
                    "workspace_update": {
                        "working_note": "Must not commit",
                        "retire_cards": ["card:1"],
                        "put_cards": [{"handle": "card:99", "text": "bad"}],
                    }
                }
            )
        )
    assert s.host.workspace is before and not before.cards["card:1"].retired
    assert any(e.get("classification") == "NORMALIZED" for e in events)


def test_new_goal_after_completed_checkpoint_reopens_tool_loop_and_clears_old_final(tmp_path):
    s, _, _, _ = make(
        tmp_path, [proposal(), actor(action="final", text="Old delivery"), proposal(kind="DELIVER")]
    )
    s.host.step()
    s.host.step()
    assert s.tools.finished and s.host.finished
    artifact = s.checkpoint_data(environment_id="world")
    fresh, requests, effects, _ = make(
        tmp_path / "fresh", [proposal(), actor("new work")], goal="New authorized task goal"
    )
    fresh.restore_checkpoint_data(artifact, environment_id="world")
    assert not fresh.tools.finished and not fresh.host.finished
    assert fresh.tools.final_text is None
    fresh.host.step()
    assert effects == ["new work"] and body(requests[0])["reason"] == "resume"
    assert fresh.host.goal_revision == 2


def test_checkpoint_artifact_is_detached_from_saving_and_restored_sessions(tmp_path):
    s, _, _, _ = make(
        tmp_path, [proposal(puts=[card("Return point")]), actor("once")], feedback_batch_size=3
    )
    s.host.step()
    artifact = s.checkpoint_data(environment_id="world")
    original = json.dumps(artifact, sort_keys=True)
    s.host._accept(proposal(puts=[card("Later lead")]))
    s.host._recall(["H001"], 0, 16000)
    assert json.dumps(artifact, sort_keys=True) == original
    fresh, requests, effects, _ = make(
        tmp_path / "fresh", [proposal(), actor("continue")], feedback_batch_size=3
    )
    fresh.restore_checkpoint_data(artifact, environment_id="world")
    assert fresh.host.maintained_pairs == 0 and fresh.host.actor_seen_pairs == 0
    fresh.host.step()
    assert effects == ["continue"] and len(fresh.tools.raw_receipts) == 2
    assert body(requests[0])["reason"] == "resume"
    assert json.dumps(artifact, sort_keys=True) == original


def test_actor_reads_retired_card_directory_and_v02_archive_migrates(tmp_path):
    s, requests, _, _ = make(
        tmp_path,
        [
            "{}",
            actor(action="retrieve", refs=["catalog:cards"]),
            "{}",
            actor(action="retrieve", refs=["card:1"]),
        ],
    )
    s.host._accept(json.dumps({"workspace_update": {"put_cards": [{"text": "Return point"}]}}))
    s.host._accept(json.dumps({"workspace_update": {"retire_cards": ["card:1"]}}))
    s.host.step()
    first = body(requests[1])
    assert first["catalogs"]["cards"]["entries"] == []
    assert first["catalogs"]["cards"]["archived"] == 1
    s.host.step()
    assert s.host.recall_observations[-1]["cards"][0]["text"] == "Return point"
    artifact = s.checkpoint_data(environment_id="old-live-world")
    artifact.pop("method")
    artifact["host"]["contract"]["method"] = "milai-rwc-v0.2"
    artifact["host"]["contract"]["policy_hash"] = "previous-policy-hash"
    artifact["host"]["contract"].pop("feedback_batch_size")
    artifact["host"]["state"]["method"] = "milai-rwc-v0.2"
    fresh, _, _, _ = make(tmp_path)
    fresh.restore_checkpoint_data(artifact, environment_id="old-live-world")
    assert fresh.host.workspace == s.host.workspace
    assert fresh.host.calls == s.host.calls
