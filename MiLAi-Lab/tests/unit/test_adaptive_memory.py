import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from milai_lab.methods.adaptive_memory import AdaptiveMemoryConfig
from milai_lab.methods.hiagent import HiAgentError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from hiagent_terminal_session import HiAgentTerminalSession


def action(name, **args):
    return {"action": name, "arguments": args}


def session(tmp_path, outputs=(), *, config=None, max_calls=32, goal="Complete the work",
            profile="ADAPTIVE_MEMORY_CANDIDATE", terminal=None):
    requests, effects, events = [], [], []
    iterator = iter(outputs)

    def generate(request):
        requests.append(request)
        value = next(iterator)
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, str) else json.dumps(value)

    def execute(command, timeout):
        effects.append(command)
        if terminal:
            return terminal(command, timeout)
        return {"stdout": "Observed current route is available; check suitability.", "exit_code": 0}

    s = HiAgentTerminalSession(
        instruction=goal, binding="adaptive-test", root=tmp_path, terminal=execute,
        generate=generate, method=profile, max_calls=max_calls, emit=events.append,
        control_options={"count_text": len,
                         "count_messages": lambda messages: len(json.dumps(messages)),
                         "config": config or AdaptiveMemoryConfig()},
    )
    return s, requests, effects, events


def body(request):
    return json.loads(request.messages[-1]["content"])


def maintain(refs=()):
    return action("maintain", reason="Reconsider the current work", refs=list(refs))


def test_segments_are_metadata_and_do_not_call_a_summary(tmp_path):
    outputs = [{**action("exec", command=f"work {i}"), "subgoal": f"part {i}"} for i in range(4)]
    outputs.append(action("final", text="Current result"))
    s, requests, effects, _ = session(
        tmp_path, outputs, config=AdaptiveMemoryConfig(max_delivery_reviews=0),
    )
    while not s.host.finished:
        s.host.step()
    assert [r.kind for r in requests] == ["actor"] * 5
    assert len(effects) == len(s.host.segments) == 4
    assert s.host.calls == {"actor": 5, "maintenance": 0}
    assert not s.host.covered_ranges and s.host.delivery_status == "UNREVIEWED"


@pytest.mark.parametrize("proposal", [
    {}, {"observations": ""}, {"workspace_update": {"working_note": "Present work"}},
    {"observations": "would cover", "group_updates": [{"handle": "obs:99", "text": "bad"}]},
    {"observations": ["wrong type"]}, "{",
])
def test_noop_card_only_and_rejected_observe_keep_raw_coverage(tmp_path, proposal):
    s, _, _, _ = session(tmp_path, [action("exec", command="inspect"), proposal],
                         config=AdaptiveMemoryConfig(observation_tokens=1, recent_events=1))
    s.host.step()
    tail = list(s.host.raw_tail)
    plan = s.host._plan(set())
    assert plan["mode"] == "OBSERVE"
    before = copy.deepcopy(s.host.workspace)
    route = s.host._maintain(plan)
    s.host.phase = "IDLE"
    assert s.host.raw_tail == tail and not s.host.covered_ranges
    assert s.host._plan(set()) is None
    if route.get("rejected"):
        assert s.host.workspace == before
    checkpoint = json.loads(json.dumps(s.checkpoint_data(environment_id="world"), sort_keys=True))
    fresh, _, _, _ = session(tmp_path, config=s.host.config)
    fresh.restore_checkpoint_data(checkpoint, environment_id="world")
    assert fresh.host._plan(set()) is None


@pytest.mark.parametrize("adopt", [True, False])
def test_revision_recall_restore_and_reconsidering_a_deferred_route(tmp_path, adopt):
    config = AdaptiveMemoryConfig(observation_tokens=1, recent_events=1)
    initial = [
        action("exec", command="inspect conditions"),
        {"observations": "OLD_UNSUPPORTED_JUDGMENT",
         "workspace_update": {"put_cards": [
             {"text": "Deferred route; prerequisite was missing", "source_refs": ["H001"]},
             {"text": "Other useful option retained", "source_refs": ["H001"]},
         ]}},
        maintain(["obs:1", "card:1"]),
        {"dispatch": {"kind": "RECALL", "refs": ["H001"], "start": 3, "length": 90}},
    ]
    s, requests, effects, _ = session(tmp_path, initial, config=config)
    s.host.step()
    s.host.step()
    assert s.host.workspace.frame.selected_refs == []
    s.host.step()
    assert s.host.pending_control == {"mode": "REVISE", "recalls": 1}
    assert s.host.actor_seen_recalls == 0
    checkpoint = json.loads(json.dumps(s.checkpoint_data(environment_id="world"), sort_keys=True))
    decision = ("Adopt after current suitability check" if adopt
                else "Decline: alternative fits better")
    outputs = [
        {"group_updates": [{"handle": "obs:1", "text": "Corrected scope from actual evidence"}],
         "workspace_update": {"put_cards": [
             {"handle": "card:1", "text": decision, "source_refs": ["H001"]},
         ]}, "frame": {"question": "Use the current assessment", "intent": decision,
                       "selected_refs": ["card:1", "obs:1"]}},
        action("exec", command="adopt current route" if adopt else "use alternative route"),
    ]
    fresh, resumed, new_effects, _ = session(tmp_path, outputs, config=config)
    fresh.restore_checkpoint_data(checkpoint, environment_id="world")
    assert fresh.host.actor_messages() == s.host.actor_messages()
    fresh.host.step()
    assert body(resumed[0])["mode"] == "REVISE"
    assert body(resumed[0])["memory"]["recalls"][0]["start"] == 3
    assert "OLD_UNSUPPORTED_JUDGMENT" not in json.dumps(body(resumed[-1]))
    assert decision in json.dumps(body(resumed[-1]))
    assert "Other useful option retained" == fresh.host.workspace.cards["card:2"].text
    assert fresh.host.workspace.cards["card:1"].revision == 2
    assert fresh.host.observation_groups[0]["revision"] == 2
    assert effects == ["inspect conditions"] and len(new_effects) == 1
    assert fresh.host.calls == {"actor": 3, "maintenance": 3}
    assert len(requests) == 4
    assert checkpoint["host"]["state"]["calls"] != fresh.host.calls


def test_compact_then_observe_preserves_sources_and_remaps_selected_group(tmp_path):
    config = AdaptiveMemoryConfig(observation_tokens=1, reflection_tokens=1, recent_events=1)
    s, requests, _, _ = session(tmp_path, [
        action("exec", command="first"),
        {"observations": "Earlier requirement and current evidence"},
        action("exec", command="second"),
        {"observations": "Compact account", "frame": {"selected_refs": ["obs:1"]}},
        {"observations": "Another actual batch"},
        action("exec", command="third"),
    ], config=config)
    for _ in range(3):
        s.host.step()
    assert [body(r)["mode"] for r in requests if r.kind == "maintenance"] == [
        "OBSERVE", "COMPACT", "OBSERVE",
    ]
    assert s.host.workspace.frame.selected_refs == ["obs:2"]
    old = s.host._read({"refs": ["obs:1"]})[0]
    assert old["status"] == "COMPACTED" and "text" not in old
    assert old["source_ranges"]
    assert s.host._read({"refs": ["event:0"], "start": 2, "length": 5})[0]["text"] == (
        s.host.goal[2:7]
    )
    active = {g["handle"] for g in s.host.observation_groups}
    assert active == {"obs:2", "obs:3"}
    assert set(s.host.covered_ranges) <= s.host.actor_seen_pages
    assert len(s.host.covered_ranges) == 2


def test_compact_and_update_same_group_is_atomic_rejection(tmp_path):
    config = AdaptiveMemoryConfig(observation_tokens=1, reflection_tokens=1, recent_events=1)
    s, _, _, _ = session(tmp_path, [
        action("exec", command="first"), {"observations": "Retained"}, maintain(),
        {"observations": "Replace", "group_updates": [{"handle": "obs:1", "text": "Also edit"}],
         "workspace_update": {"working_note": "Must not commit"}},
    ], config=config)
    s.host.step()
    s.host.step()
    before = copy.deepcopy(s.host.workspace)
    old = copy.deepcopy(s.host.observation_groups)
    route = s.host._maintain(s.host._plan(set()))
    assert route["rejected"] and s.host.workspace == before
    assert s.host.observation_groups == old and not s.host.compacted_groups


@pytest.mark.parametrize("review,status,answer", [
    ({}, "UNREVIEWED", "draft"),
    ({"dispatch": {"kind": "DELIVER"}}, "REVIEWED", "draft"),
    ({"dispatch": {"kind": "DELIVER", "delivery": "revised"}}, "REVIEWED", "revised"),
    ({"frame": {"selected_refs": ["not-published"]}}, "UNREVIEWED", "draft"),
])
def test_optional_review_accept_replace_noop_and_rejection(tmp_path, review, status, answer):
    s, requests, effects, _ = session(tmp_path, [action("final", text="draft"), review])
    s.host.step()
    assert s.host.pending_final and not s.tools.finished
    saved = s.checkpoint_data(environment_id="world")
    fresh, _, _, _ = session(tmp_path, [review])
    fresh.restore_checkpoint_data(saved, environment_id="world")
    fresh.host.step()
    assert fresh.host.delivery_status == status and fresh.tools.final_text == answer
    assert fresh.host.review_count == 1 and fresh.host.calls == {"actor": 1, "maintenance": 1}
    assert len(requests) == 1 and effects == []


def test_review_recall_continuation_and_new_feedback_draft_invalidation(tmp_path):
    s, requests, _, _ = session(tmp_path, [
        action("exec", command="inspect"), action("final", text="draft"),
        {"dispatch": {"kind": "RECALL", "refs": ["H001"], "length": 50}},
        {"dispatch": {"kind": "ACT"}}, action("exec", command="resolve gap"),
        action("final", text="current answer"),
    ])
    for _ in range(5):
        s.host.step()
    assert s.tools.final_text == "current answer" and s.host.review_count == 1
    assert s.host.mode_calls["REVIEW"] == 2
    assert [r.kind for r in requests] == ["actor", "actor", "maintenance", "maintenance",
                                         "actor", "actor"]
    other, _, _, _ = session(tmp_path / "other", [action("final", text="stale"),
                                                 action("final", text="updated")])
    other.host.step()
    other.host.observe("New requirement invalidates the answer")
    assert other.host.pending_final is None and other.host.review_count == 0
    other.host.step()
    assert other.host.pending_final["text"] == "updated"


@pytest.mark.parametrize("last", [action("exec", command="must not run"), maintain(),
                                  action("retrieve", refs=["event:0"]), "invalid"])
def test_closing_actor_keeps_last_call_and_executes_no_new_action(tmp_path, last):
    s, requests, effects, _ = session(tmp_path, [last], max_calls=1)
    s.host.step()
    assert body(requests[0])["call_budget"]["closing"]
    assert s.host.delivery_status == "INCOMPLETE" and not effects
    assert s.host.pending_request is None and not s.host.recalls


def test_maintenance_cannot_take_last_actor_call(tmp_path):
    s, requests, _, _ = session(tmp_path, [maintain(), action("final", text="bounded result")],
                                max_calls=2)
    s.host.step()
    s.host.step()
    assert [r.kind for r in requests] == ["actor", "actor"]
    assert s.host.pending_request and s.host.delivery_status == "UNREVIEWED"


@pytest.mark.parametrize("failure", [RuntimeError("unknown usage"), TimeoutError("unknown effect")])
def test_unknown_stops_without_fallback_delivery_or_checkpoint(tmp_path, failure):
    s, _, _, _ = session(tmp_path, [action("final", text="draft"), failure])
    s.host.step()
    with pytest.raises(type(failure)):
        s.host.step()
    assert s.host.halted and not s.tools.finished
    with pytest.raises(HiAgentError, match="QUIESCENT"):
        s.checkpoint_data(environment_id="world")


def test_sparse_card_retire_unretire_and_catalog_ranges(tmp_path):
    outputs = [maintain(), {"workspace_update": {"working_note": "present", "put_cards": [
        {"text": "Route detail " * 100, "source_refs": ["event:0"]},
    ]}}, maintain(["card:1"]),
        {"workspace_update": {"retire_cards": ["card:1"]}}, maintain(["card:1"]),
        {"workspace_update": {"put_cards": [{"handle": "card:1", "text": "Returned route"}]},
         "frame": {"selected_refs": ["card:1"]}}, action("exec", command="apply"),
    ]
    s, requests, _, _ = session(tmp_path, outputs)
    for _ in range(4):
        s.host.step()
    card = s.host.workspace.cards["card:1"]
    assert card.revision == 3 and not card.retired and card.source_refs == ["event:0"]
    assert s.host.workspace.working_note == "present"
    page = s.host._read({"refs": ["card:1", "event:0"], "start": 2, "length": 4})
    assert [p["length"] for p in page] == [4, 4]
    assert page[0]["text"] == "turn"
    cat = s.host._read({"refs": ["catalog:cards"], "start": 0, "length": 1})[0]
    assert cat["entries"][0]["ref"] == "card:1" and cat["next_start"] is None
    materials = body(requests[-1])["memory"]["materials"]
    assert sum(p["ref"] == "card:1" for p in materials) == 1
    with pytest.raises(HiAgentError):
        s.host._read({"refs": [{"ref": "card:1"}]})
    with pytest.raises(HiAgentError):
        s.host._read({"refs": ["card:1"], "length": 16001})


def test_source_revocation_and_failed_restore_are_atomic(tmp_path):
    s, _, _, _ = session(tmp_path, [action("exec", command="inspect")])
    s.host.step()
    data = s.checkpoint_data(environment_id="world")
    fresh, _, _, _ = session(tmp_path)
    before = fresh.host.snapshot()
    corrupt = copy.deepcopy(data)
    corrupt["host"]["state"]["pages"][1]["text"] = "substituted"
    with pytest.raises(HiAgentError, match="INVALID_ADAPTIVE_CHECKPOINT"):
        fresh.restore_checkpoint_data(corrupt, environment_id="world")
    assert fresh.host.snapshot() == before and not fresh.tools.raw_receipts
    with pytest.raises(ValueError, match="ENVIRONMENT"):
        fresh.restore_checkpoint_data(data, environment_id="different-world")
    different, _, _, _ = session(tmp_path, profile="ADAPTIVE_MEMORY_SIMPLE")
    with pytest.raises(ValueError):
        different.restore_checkpoint_data(data, environment_id="world")
    s.tools.sources["H001"] = replace(s.tools.sources["H001"], eligible=False)
    with pytest.raises(HiAgentError, match="SOURCE_DEPENDENCY"):
        s.host.checkpoint()


def test_new_goal_reopens_finished_session_preserving_budget_and_memory(tmp_path):
    s, _, _, _ = session(tmp_path, [maintain(),
        {"workspace_update": {"working_note": "Retained prior work"}},
        action("final", text="first"), {},
    ])
    while not s.host.finished:
        s.host.step()
    saved = s.checkpoint_data(environment_id="world")
    fresh, _, _, _ = session(tmp_path, goal="New task")
    fresh.restore_checkpoint_data(saved, environment_id="world")
    assert not fresh.tools.finished and fresh.tools.final_text is None
    assert fresh.host.calls == s.host.calls and fresh.host.review_count == 0
    assert fresh.host.workspace.frame.question == "New task"
    assert fresh.host.workspace.working_note == "Retained prior work"
    assert fresh.host.pending_request and not fresh.host.pending_final
    s.set_goal("Another task")
    assert not s.tools.finished and s.host.review_count == 0


def test_omitted_pages_partial_reads_and_pending_request_capacity(tmp_path):
    config = AdaptiveMemoryConfig(context_tokens=15000, actor_output_tokens=500,
        observer_output_tokens=500, reflector_output_tokens=500, maintenance_output_tokens=500,
        page_chars=100, observation_tokens=1, recent_events=1)
    s, requests, _, _ = session(tmp_path, [maintain(),
        {"workspace_update": {"put_cards": [{"text": "large " * 4000}]}},
        maintain(["card:1"]), action("exec", command="continue useful work"),
    ], config=config)
    s.host.observe("new material " * 2000)
    s.host.step()
    shown = body(requests[0])["memory"]
    omitted = {i for p in shown["omitted_pages"]
               for i in range(p["page_start"], p["page_end"] + 1)}
    assert omitted and not omitted & s.host.actor_seen_pages
    assert not omitted & set(s.host.covered_ranges)
    # The request can be recorded without manufacturing a source event.
    event_count = len(s.host.events)
    assert event_count == 2
    s.host.step()
    assert s.host.pending_request["refs"] == ["card:1"]
    s.host.step()
    assert s.host.pending_request["refs"] == ["card:1"]
    assert [r.kind for r in requests] == ["actor", "maintenance", "actor", "actor"]
    assert not s.host.covered_ranges


def test_actor_and_controller_reads_share_ranges_without_covering_them(tmp_path):
    s, requests, _, _ = session(tmp_path, [
        action("exec", command="inspect"),
        action("retrieve", refs=["H001"], start=6, length=25),
        maintain(), {"dispatch": {"kind": "RECALL", "refs": ["H001"],
                                   "start": 6, "length": 25}},
        {}, action("final", text="Current result"),
    ])
    for _ in range(5):
        s.host.step()
    assert s.host.recalls[0]["results"] == s.host.recalls[1]["results"]
    assert s.host.recalls[0]["results"][0]["length"] == 25
    assert not s.host.covered_ranges
    assert body(requests[-1])["memory"]["recalls"]


def test_unchanged_group_card_frame_patch_keeps_revisions(tmp_path):
    s, _, _, _ = session(tmp_path, [
        action("exec", command="inspect"),
        {"observations": "current group", "workspace_update": {
            "put_cards": [{"text": "current card"}]}},
        maintain(["obs:1", "card:1"]),
        {"group_updates": [{"handle": "obs:1", "text": "current group"}],
         "workspace_update": {"put_cards": [{"handle": "card:1", "text": "current card"}]}},
        action("exec", command="continue"),
    ], config=AdaptiveMemoryConfig(observation_tokens=1, recent_events=1))
    s.host.step()
    s.host.step()
    before = s.host.state_revision, s.host.workspace.revision
    s.host.step()
    assert (s.host.state_revision, s.host.workspace.revision) == before
    assert s.host.observation_groups[0]["revision"] == 1
    assert s.host.workspace.cards["card:1"].revision == 1


def test_public_canonicalization_preserves_wire_view_and_attempt_identity(tmp_path):
    s, _, _, _ = session(tmp_path, [maintain(), {"workspace_update": {"put_cards": [
        {"text": f"Retained option {i}"} for i in range(12)
    ]}}, action("exec", command="continue")])
    s.host.step()
    s.host.step()
    saved = json.loads(json.dumps(s.checkpoint_data(environment_id="world"), sort_keys=True))
    fresh, _, _, _ = session(tmp_path)
    fresh.restore_checkpoint_data(saved, environment_id="world")
    assert s.host.actor_messages() == fresh.host.actor_messages()
    assert s.host._identity("REVISE", [], []) == fresh.host._identity("REVISE", [], [])


@pytest.mark.parametrize("last", [
    action("retrieve", refs=["H001"], start=0, length=25),
    action("read", ref="H001", start=0, length=25),
])
def test_closing_read_validation_does_not_read_source_bodies(tmp_path, last):
    s, _, effects, _ = session(tmp_path, [action("exec", command="inspect"), last], max_calls=2)
    s.host.step()
    reads = []
    reader = s.host.read_source

    def tracked(*args):
        reads.append(args)
        return reader(*args)

    s.host.read_source = tracked
    s.host.step()
    assert reads == [] and effects == ["inspect"]
    assert s.host.delivery_status == "INCOMPLETE" and not s.host.recalls


def test_revision_after_recall_past_eof_keeps_a_restorable_source_union(tmp_path):
    config = AdaptiveMemoryConfig(observation_tokens=1, recent_events=1, max_delivery_reviews=0)
    s, _, _, _ = session(tmp_path, [
        action("exec", command="inspect"), {"observations": "Initial account"}, maintain(["obs:1"]),
        {"dispatch": {"kind": "RECALL", "refs": ["H001"], "start": 999999, "length": 100}},
        {"group_updates": [{"handle": "obs:1", "text": "No further source text exists"}]},
        action("final", text="Bounded result"),
    ], config=config)
    for _ in range(4):
        s.host.step()
    assert s.host.recalls[0]["results"][0]["text"] == ""
    saved = s.checkpoint_data(environment_id="world")
    fresh, _, _, _ = session(tmp_path, config=config)
    fresh.restore_checkpoint_data(saved, environment_id="world")
    assert fresh.host.observation_groups == s.host.observation_groups
    assert fresh.host.actor_messages() == s.host.actor_messages()
