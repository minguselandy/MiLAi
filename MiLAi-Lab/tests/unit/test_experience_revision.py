import json

import pytest
from test_reasoning_bank import fixture_session, item

from milai_lab.methods.experience_revision import ExperienceRevisionSession
from milai_lab.methods.reasoning_bank import MemoryOutputError


def candidate(bank, responses, **kwargs):
    reference, _, _ = fixture_session([], bank)
    pending = iter(responses)
    return ExperienceRevisionSession(
        bank=bank,
        config=reference.config,
        policies=reference.policies,
        generate=lambda call: next(pending),
        embed=reference.embed,
        **kwargs,
    )


def actor_context(session):
    text = session.memory_context()
    session.confirm_actor_input()
    return text


def adopt(*handles):
    return json.dumps({"frame": {"selected_refs": list(handles)}})


def test_explicit_revision_reads_source_changes_next_projection_and_survives_restore():
    base, _, _ = fixture_session(["success", item("Original lesson")])
    base.start("support", "red task")
    base.finish("original visible trace", commit=True)
    revise = {
        "expected_revisions": {"card:1": 1},
        "workspace_update": {
            "put_cards": [
                {
                    "handle": "card:1",
                    "text": item("Revised lesson").split("\n", 1)[1],
                    "source_refs": ["source:2", "source:4"],
                }
            ]
        },
    }
    session = candidate(
        base.bank,
        [
            adopt("card:1"),
            json.dumps({"dispatch": {"kind": "RECALL", "refs": ["source:2"]}}),
            json.dumps(revise),
            "fail",
            item("New failure lesson"),
        ],
    )
    session.start("later", "red followup")
    assert "Original lesson" in actor_context(session)
    ref = session.observe("tool", "The old approach failed on an empty result.")
    assert ref == "source:4"
    result = session.request_revision(
        {"handles": ["card:1"], "feedback_refs": [ref], "reason": "Empty results need handling"}
    )
    assert result["changed"] == {"card:1": {"before": 1, "after": 2}}
    assert "Revised lesson" in actor_context(session)
    assert "Original lesson" not in actor_context(session)
    assert "Original lesson" in session.read("card:1@1")["text"]
    session.finish("real followup work", commit=True)
    restored = type(base.bank).restore(
        session.checkpoint(), scope=base.bank.scope, contract=base.bank.contract
    )
    assert restored.cards["card:1"].revision == 2
    assert "card:1@1" in restored.historical_cards


def test_no_automatic_revision_and_frozen_overlay_is_discarded():
    base, _, _ = fixture_session(["success", item()])
    cold = candidate(base.bank, [])
    cold.start("cold", "empty-bank request")
    assert cold.memory_context() == ""
    base.start("support", "red support")
    base.finish("visible", commit=True)
    original = base.checkpoint()
    session = candidate(base.bank, [adopt("card:1"), "success", item("Local only")])
    session.start("frozen", "red test")
    session.observe("tool", "Failure: this alone does not invoke the controller")
    with pytest.raises(MemoryOutputError, match="SEEN_EXPERIENCE"):
        session.request_revision({"handles": ["card:1"], "feedback_refs": [], "reason": "x"})
    session.finish("visible work", commit=False)
    assert base.checkpoint() == original


def test_failed_new_extraction_does_not_revoke_an_accepted_online_revision():
    base, _, _ = fixture_session(["success", item("Prior")])
    base.start("support", "red support")
    base.finish("visible", commit=True)
    proposal = json.dumps(
        {
            "expected_revisions": {"card:1": 1},
            "workspace_update": {
                "put_cards": [{"handle": "card:1", "text": "Revised existing lesson"}],
            },
        }
    )
    session = candidate(
        base.bank, [adopt("card:1"), proposal, "fail", "No valid new extracted item"]
    )
    session.start("later", "red next")
    actor_context(session)
    ref = session.observe("tool", "The prior assumption failed in this observed case")
    session.request_revision(
        {"handles": ["card:1"], "feedback_refs": [ref], "reason": "Observed mismatch"}
    )
    result = session.finish("actual unsuccessful work", commit=True)
    assert result["accepted_revisions_retained"] and result["committed"]
    assert len(base.bank.records) == 1
    assert base.bank.cards["card:1"].text == "Revised existing lesson"
    assert base.bank.completed_tasks == ["support", "later"]


def test_append_only_keeps_old_active_and_indexes_correction_with_same_query():
    base, _, _ = fixture_session(["success", item("Old advice")])
    base.start("support", "red support")
    base.finish("visible", commit=True)
    proposal = json.dumps(
        {
            "expected_revisions": {"card:1": 1},
            "workspace_update": {"put_cards": [{"handle": "card:1", "text": "Correction"}]},
        }
    )
    session = candidate(
        base.bank,
        [adopt("card:1"), proposal, "fail", "invalid extraction"],
        revision_application="append_only",
    )
    session.start("later", "red next")
    actor_context(session)
    ref = session.observe("tool", "Observed mismatch")
    session.request_revision({"handles": ["card:1"], "feedback_refs": [ref], "reason": "Mismatch"})
    assert "Old advice" in actor_context(session) and "Correction" in actor_context(session)
    session.finish("visible", commit=True)
    assert base.bank.cards["card:1"].revision == 1
    assert base.bank.cards["card:2"].text == "Correction"
    assert base.bank.records[0]["handles"] == ["card:1", "card:2"]
    assert base.bank.historical_cards == {}


def test_adoption_cannot_change_persistent_advice():
    base, _, _ = fixture_session(["success", item("Old advice")])
    base.start("support", "red support")
    base.finish("visible", commit=True)
    session = candidate(
        base.bank,
        [
            json.dumps(
                {
                    "expected_revisions": {"card:1": 1},
                    "workspace_update": {"put_cards": [{"handle": "card:1", "text": "Changed"}]},
                }
            )
        ],
    )
    session.start("later", "red next")
    assert "Old advice" not in actor_context(session)
    assert session.working.cards["card:1"].revision == 1


def test_authorized_facts_reach_adoption_and_actor_before_any_source_read():
    base, _, _ = fixture_session(["success", item("Old advice")])
    base.start("support", "red support")
    base.finish("visible", commit=True)
    session = candidate(base.bank, [])
    calls = []

    def generate(call):
        calls.append(call)
        return "{}"

    session.generate = generate
    fact = "Previously completed plan: leave at 09:00 and return at 17:00."
    session.start("later", "red next", task_facts=(("Prior plan", fact),))
    adoption = json.loads(calls[0].messages[-1]["content"])
    ref = next(iter(session.fact_catalog))
    assert adoption["task_facts"][ref] == {"label": "Prior plan", "text": fact}
    assert ref in adoption["published_refs"]
    assert fact in actor_context(session)
    assert session.read(ref)["text"] == fact
    assert session.working.cards["card:1"].revision == 1

    session = candidate(base.bank, [])
    session.generate = generate
    session.start("without-facts", "red next")
    assert "task_facts" not in json.loads(calls[-1].messages[-1]["content"])
    assert fact not in actor_context(session)


def two_lesson_bank():
    lessons = item("ALPHA_ADVICE") + "\n" + item("BETA_ADVICE").replace("Item 1", "Item 2")
    base, _, _ = fixture_session(["success", lessons])
    base.start("support", "red support")
    base.finish("Original legal feedback", commit=True)
    return base.bank


def test_empty_selection_suppresses_all_advice_and_derived_notes_but_keeps_authorized_facts():
    proposal = json.dumps(
        {
            "workspace_update": {"working_note": "ALPHA_ADVICE is irrelevant but do its check"},
            "frame": {"selected_refs": [], "intent": "BETA_ADVICE check"},
            "adoption_notes": {"card:1": "ALPHA_ADVICE extra step"},
        }
    )
    session = candidate(two_lesson_bank(), [proposal])
    session.start(
        "test", "red next", task_facts=(("Current user requirement", "Do BETA_ADVICE now"),)
    )
    context = actor_context(session)
    assert "ALPHA_ADVICE" not in context
    assert "BETA_ADVICE check" not in context
    assert "Do BETA_ADVICE now" in context
    assert "Below are some memory items" not in context
    assert session.seen == {}
    assert "ALPHA_ADVICE" in session.read("card:1")["text"]
    feedback = session.observe("tool", "Fresh failure ALPHA_ADVICE")
    assert "Fresh failure ALPHA_ADVICE" in session.read(feedback)["text"]


def test_partial_selection_controls_body_and_scoped_note_without_legacy_note_leak():
    bank = two_lesson_bank()
    bank.cards["card:1"].text += "\n" + "required detail " * 1200 + "END_OF_CARD"
    proposal = json.dumps(
        {
            "workspace_update": {"working_note": "BETA_ADVICE excluded but restated"},
            "frame": {"selected_refs": ["card:1"], "intent": "BETA_ADVICE repeated in frame"},
            "adoption_notes": {"card:1": "Use ALPHA_ADVICE conditionally", "card:2": "BETA_ADVICE"},
        }
    )
    session = candidate(bank, [proposal])
    session.start("test", "red next")
    context = actor_context(session)
    assert bank.cards["card:1"].text in context and "END_OF_CARD" in context
    assert "BETA_ADVICE" not in context
    assert "Use ALPHA_ADVICE conditionally" in context
    assert session.seen == {"card:1": 1}
    page = session.read("card:1", 0, 10)
    assert page["has_more"] and page["total_chars"] == len(bank.cards["card:1"].text)


def test_omitted_selection_retains_previous_selection_and_explicit_empty_clears_it():
    session = candidate(two_lesson_bank(), [adopt("card:1"), "{}", adopt()])
    session.start("test", "red next")
    session._maintain("adopt", "Leave the existing selection unchanged")
    assert "ALPHA_ADVICE" in actor_context(session)
    session._maintain("adopt", "Explicitly deselect")
    context = actor_context(session)
    assert "ALPHA_ADVICE" not in context and "BETA_ADVICE" not in context
    assert not session.workspace.frame.selected_refs
    assert "ALPHA_ADVICE" in session.read("card:1")["text"]


def test_unknown_adoption_reference_is_rejected_without_implicit_all_fallback():
    session = candidate(two_lesson_bank(), [adopt("card:999")])
    session.start("test", "red next")
    assert not session.workspace.frame.selected_refs
    assert "ALPHA_ADVICE" not in actor_context(session)
    assert "BETA_ADVICE" not in actor_context(session)


def test_legacy_projection_is_an_explicit_diagnostic_with_the_same_adoption_output():
    output = json.dumps(
        {
            "frame": {"selected_refs": []},
            "workspace_update": {"working_note": "ALPHA_ADVICE derived check"},
        }
    )
    legacy = candidate(two_lesson_bank(), [output], projection_mode="legacy_all")
    fixed = candidate(two_lesson_bank(), [output])
    for session in (legacy, fixed):
        session.start("test", "red next")
    assert "ALPHA_ADVICE" in legacy.memory_context() and "BETA_ADVICE" in legacy.memory_context()
    assert "ALPHA_ADVICE" not in fixed.memory_context()
    assert "BETA_ADVICE" not in fixed.memory_context()


def revision_envelope(handle="card:1", feedback="source:4"):
    return json.dumps(
        {
            "new_memory": item("New conditional lesson"),
            "revision": {
                "handles": [handle],
                "feedback_refs": [feedback],
                "reason": "Actual tool feedback contradicts the unconditional old advice",
                "proposal": {
                    "expected_revisions": {handle: 1},
                    "workspace_update": {
                        "put_cards": [
                            {
                                "handle": handle,
                                "text": "CONDITIONAL_CORRECTION",
                            }
                        ]
                    },
                },
            },
        }
    )


@pytest.mark.parametrize("application", ["replace", "append_only"])
def test_existing_extraction_call_can_revise_with_feedback_and_next_task_consumes_it(application):
    bank = two_lesson_bank()
    calls = []
    responses = iter([adopt("card:1"), "fail", revision_envelope()])
    session = candidate(bank, [], post_task_revision=True, revision_application=application)

    def generate(call):
        calls.append(call)
        return next(responses)

    session.generate = generate
    session.start("online", "red related task")
    assert "ALPHA_ADVICE" in actor_context(session)
    assert session.observe("tool", "Observed exception to the unconditional rule") == "source:4"
    result = session.finish("Actual native conversation without evaluator answers", commit=True)
    assert result["status"] == "EXTRACTED"
    assert [call.role for call in calls] == ["adopt", "self_judge", "extract"]
    payload = json.loads(calls[-1].messages[-1]["content"])
    assert list(payload["seen_experience"]) == ["card:1"]
    assert "source:4" in payload["visible_tool_feedback"]
    corrected = "card:1" if application == "replace" else "card:3"
    assert bank.cards[corrected].text == "CONDITIONAL_CORRECTION"
    assert "source:4" in bank.cards[corrected].source_refs
    assert bank.cards["card:1"].revision == (2 if application == "replace" else 1)
    restored = type(bank).restore(bank.checkpoint(), scope=bank.scope, contract=bank.contract)
    later = candidate(restored, [adopt(corrected)])
    later.start("later", "red later related task")
    assert "CONDITIONAL_CORRECTION" in later.memory_context()
    if application == "replace":
        assert "ALPHA_ADVICE" in later.read("card:1@1")["text"]
    else:
        assert "ALPHA_ADVICE" in bank.cards["card:1"].text


def test_post_task_revision_does_not_change_the_frozen_bank():
    bank = two_lesson_bank()
    before = bank.checkpoint()
    session = candidate(
        bank, [adopt("card:1"), "fail", revision_envelope()], post_task_revision=True
    )
    session.start("frozen", "red task")
    actor_context(session)
    session.observe("tool", "Observed exception")
    session.finish("Visible trajectory", commit=False)
    assert session.working.cards["card:1"].text == "CONDITIONAL_CORRECTION"
    assert bank.checkpoint() == before


@pytest.mark.parametrize("handle,feedback", [("card:2", "source:4"), ("card:1", "hidden-score")])
def test_unseen_or_nonvisible_post_task_revision_is_rejected_but_extraction_survives(
    handle, feedback
):
    bank = two_lesson_bank()
    events = []
    session = candidate(
        bank,
        [adopt("card:1"), "fail", revision_envelope(handle, feedback)],
        post_task_revision=True,
        emit=events.append,
    )
    session.start("online", "red task")
    actor_context(session)
    session.observe("tool", "Visible tool receipt")
    result = session.finish("Visible trajectory", commit=True)
    assert result["status"] == "EXTRACTED"
    assert any(e["event"] == "POST_TASK_REVISION_REJECTED" for e in events)
    assert bank.cards["card:1"].revision == bank.cards["card:2"].revision == 1
    assert "New conditional lesson" in bank.cards["card:3"].text


def test_task_interpretation_and_deselection_do_not_edit_long_term_experience_or_reuse_old_note():
    bank = two_lesson_bank()
    initial = bank.checkpoint()
    session = candidate(
        bank,
        [
            json.dumps(
                {
                    "frame": {"selected_refs": ["card:1"]},
                    "workspace_update": {"working_note": "ALPHA_ADVICE derived obligation"},
                }
            )
        ],
    )
    session.start("local", "red task")
    session.request_task_update({"kind": "state", "frame": {"selected_refs": []}})
    assert "ALPHA_ADVICE" not in actor_context(session)
    session.request_task_update({"kind": "state", "working_note": "The requested unit is a record"})
    assert "The requested unit is a record" in actor_context(session)
    assert bank.checkpoint() == initial and session.working.cards == bank.cards
    with pytest.raises(MemoryOutputError, match="TASK_STATE_CANNOT_EDIT"):
        session.request_task_update({"kind": "state", "put_cards": []})


def test_reading_in_the_controller_does_not_mark_actor_exposure_but_actor_read_does():
    session = candidate(two_lesson_bank(), [adopt()])
    session.start("test", "red next")
    session.read("card:1")
    assert session.seen == {}
    session.actor_read("card:1")
    assert session.seen == {}
    session.confirm_actor_input()
    assert session.seen == {"card:1": 1}


def test_assembly_without_a_provider_response_does_not_prove_actor_exposure():
    session = candidate(two_lesson_bank(), [adopt("card:1")])
    session.start("test", "red task")
    assert "ALPHA_ADVICE" in session.memory_context()
    assert session.seen == {}
    feedback = session.observe("tool", "Actual tool feedback")
    with pytest.raises(MemoryOutputError, match="SEEN_EXPERIENCE"):
        session.request_revision(
            {"handles": ["card:1"], "feedback_refs": [feedback], "reason": "x"}
        )
    session.confirm_actor_input()
    assert session.seen == {"card:1": 1}


def test_empty_extraction_is_valid_abstention_and_does_not_create_empty_retrieval_record():
    bank = two_lesson_bank()
    count = len(bank.records)
    session = candidate(
        bank, [adopt(), "success", '{"new_memory":"","revision":null}'], post_task_revision=True
    )
    session.start("no-new-lesson", "red task")
    result = session.finish("Visible successful work with no useful new lesson", commit=True)
    assert result["status"] == "NO_NEW_EXPERIENCE" and result["committed"]
    assert len(bank.records) == count
    assert bank.completed_tasks[-1] == "no-new-lesson"


def test_native_plans_can_be_adoption_visible_without_duplicate_actor_projection():
    budget = {"limit": 30, "used": 0, "remaining": 30, "final_uses_slot": True}
    session = candidate(two_lesson_bank(), [], project_task_facts=False, action_budget=budget)
    calls = []
    session.generate = lambda call: calls.append(call) or adopt()
    fact = "Actual earlier plan: depart on day 2 and return on day 5."
    session.start("later-person", "red task", task_facts=(("Actual prior plan", fact),))
    body = json.loads(calls[0].messages[-1]["content"])
    ref = next(iter(session.fact_catalog))
    assert body["task_facts"][ref]["text"] == fact
    assert body["native_action_budget"] == budget
    assert fact not in session.memory_context()
    assert session.read(ref)["text"] == fact
