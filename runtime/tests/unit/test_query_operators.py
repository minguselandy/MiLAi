from __future__ import annotations

from datetime import UTC, datetime

from milai.application.query_operators import execute_query_operator
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

SCOPE = {"project_ids": ["milai"]}


def _plan(query: str):  # type: ignore[no-untyped-def]
    return QueryPlanner().plan(
        RetrievalRequest(route="L1", query=query, requested_scope=SCOPE),
    )


def _item(value: object, observed_at: str, *, issue: bool = False):  # type: ignore[no-untyped-def]
    suffix = str(value).replace(" ", "-")
    return {
        "claim_id": f"claim-{suffix}",
        "claim_version_id": f"version-{suffix}",
        "payload": {"value": value},
        "scope_predicate": SCOPE,
        "valid_time_from": observed_at,
        "evidence_ids": [f"evidence-{suffix}"],
        "open_issue_ids": ["issue-1"] if issue else [],
    }


def test_planner_selects_controlled_operators_without_model_calls() -> None:
    assert _plan("What was my latest preference?").operator is None
    assert _plan("How many projects do I currently have?").operator == "COUNT_DISTINCT"
    assert _plan("What is the total amount?").operator == "SUM_VALUES"
    assert _plan("What happened before the launch?").operator == "TEMPORAL_BEFORE_AFTER"
    assert _plan("What is the difference between the two values?").operator == "COMPARE_EVENTS"


def test_state_count_uses_latest_relevant_state_instead_of_counting_records() -> None:
    plan = _plan("How many tops have I bought from H&M so far?")
    items = [
        {
            **_item("older", "2023-08-11T03:18:00+00:00"),
            "payload": {"memory_text": "user: I've already bought three tops from H&M."},
        },
        {
            **_item("newer", "2023-09-30T06:40:00+00:00"),
            "payload": {"memory_text": "user: I've already got five tops from H&M so far."},
        },
    ]

    result = execute_query_operator(plan, items)

    assert plan.operator == "COUNT_DISTINCT"
    assert plan.operator_arguments["count_mode"] == "scalar_fact"
    assert plan.operator_arguments["slot_schema_version"] == "typed-operator-v1"
    assert plan.operator_arguments["route_reason"] == "EXPLICIT_SCALAR_COUNT_FACT"
    assert result is not None
    assert result["value"] == "five"
    assert len(result["operands"]) == 1


def test_state_count_prefers_latest_valid_numeric_fact_over_higher_word_overlap() -> None:
    plan = _plan("How many videos of Corey Schafer's Python series have I completed so far?")
    items = [
        {
            **_item("older", "2023-05-24T18:34:00+00:00"),
            "payload": {
                "memory_text": ("user: I completed 20 videos of Corey Schafer's Python series.")
            },
        },
        {
            **_item("newer", "2023-05-26T00:03:00+00:00"),
            "payload": {"memory_text": "user: I've completed 30 videos so far."},
        },
    ]

    result = execute_query_operator(plan, items)

    assert result is not None and result["value"] == "30"


def test_state_count_rejects_pronoun_list_marker_and_hyphenated_year() -> None:
    plan = _plan("How many of Emma's recipes have I tried out?")
    items = [
        {
            **_item("fact", "2023-05-29T04:51:00+00:00"),
            "payload": {"memory_text": "user: I've already tried out two of Emma's recipes."},
        },
        {
            **_item("pronoun", "2023-05-29T07:44:00+00:00"),
            "payload": {
                "memory_text": (
                    "assistant: 1.\n"
                    "user: I tried a brisket recipe and had an amazing one at a festival."
                )
            },
        },
    ]

    result = execute_query_operator(plan, items)

    assert result is not None and result["value"] == "two"

    coin = execute_query_operator(
        _plan("How many pre-1920 American coins do I have?"),
        [
            {
                **_item("coin", "2023-05-29T00:54:00+00:00"),
                "payload": {
                    "memory_text": (
                        "user: I added a 1915-S quarter to my pre-1920 coin collection."
                    )
                },
            }
        ],
    )

    assert coin is not None and coin["status"] == "ABSTAINED"
    assert coin["reason"] == "NUMERIC_OPERAND_MISSING"


def test_current_state_selects_latest_query_relevant_item_not_newest_distractor() -> None:
    plan = _plan("Where is the painting Ethereal Dreams currently hanging?")
    items = [
        {
            **_item("painting", "2023-10-30T16:38:00+00:00"),
            "payload": {
                "memory_text": (
                    "assistant: The Ethereal Dreams painting is hanging in your bedroom."
                )
            },
        },
        {
            **_item("newer", "2023-11-18T17:40:00+00:00"),
            "payload": {"memory_text": "assistant: Coastal design is currently trending."},
        },
    ]

    result = execute_query_operator(plan, items)

    assert plan.operator == "LATEST_VALID_STATE"
    assert result is not None
    assert "bedroom" in str(result["value"])


def test_latest_state_uses_structured_canonical_value_not_rendered_role_labels() -> None:
    plan = _plan("What type of camera lens did I purchase most recently?")
    items = [
        {
            **_item("older", "2023-03-11T03:12:00+00:00"),
            "payload": {
                "memory_text": (
                    "assistant: Check camera and lens compatibility before a purchase.\n"
                    "user: I recently got a new 50mm prime lens."
                )
            },
        },
        {
            **_item("newer", "2023-08-30T14:23:00+00:00"),
            "payload": {
                "value": "70-200mm zoom lens",
                "memory_text": (
                    "assistant: Remember to check filter compatibility with your camera "
                    "and lens before making a purchase.\n"
                    "user: I recently took great shots with my 70-200mm zoom lens."
                )
            },
        },
    ]

    result = execute_query_operator(plan, items)

    assert "subject_role" not in plan.operator_arguments
    assert result is not None and result["status"] == "OK"
    assert "70-200mm zoom lens" in str(result["value"])
    assert "filter compatibility" not in str(result["value"])


def test_latest_user_state_abstains_without_a_user_fact() -> None:
    plan = _plan("What camera lens did I purchase most recently?")
    result = execute_query_operator(
        plan,
        [
            {
                **_item("advice", "2023-08-30T14:23:00+00:00"),
                "payload": {
                    "memory_text": (
                        "assistant: Check camera and lens compatibility before a purchase."
                    )
                },
            }
        ],
    )

    assert "subject_role" not in plan.operator_arguments
    assert result is not None and result["status"] == "ABSTAINED"
    assert result["reason"] == "STATE_VALUE_MISSING"


def test_compound_state_count_is_left_for_evidence_based_answering() -> None:
    plan = _plan("How many engineers did I lead when I started? How many engineers do I lead now?")

    assert plan.operator is None
    assert plan.operator_arguments == {}


def test_distinct_count_without_completeness_proof_falls_back_to_recall() -> None:
    plan = _plan("How many projects did I mention?")

    assert plan.operator is None
    assert plan.operator_arguments == {}


def test_planner_distinguishes_temporal_distance_and_relative_point() -> None:
    between = _plan("How many days passed between the first event and the second event?")
    relative = _plan("How many months have passed since I visited the museum?")
    point = _plan("Which book did I finish a week ago?")

    assert between.operator == "TEMPORAL_DISTANCE"
    assert between.operator_arguments["distance_mode"] == "between_events"
    assert relative.operator == "TEMPORAL_DISTANCE"
    assert relative.operator_arguments["distance_mode"] == "from_reference"
    assert relative.operator_arguments["distance_unit"] == "month"
    assert point.operator == "TEMPORAL_BEFORE_AFTER"
    assert point.operator_arguments["target_mode"] == "relative_point"


def test_latest_and_temporal_distance_use_canonical_operand_pointers() -> None:
    items = [
        _item("old", "2026-08-01T00:00:00+00:00"),
        _item("new", "2026-08-11T00:00:00+00:00"),
    ]
    latest = execute_query_operator(_plan("What was my latest state?"), items)
    distance_plan = _plan("How long was the distance between the two events?")
    distance = execute_query_operator(distance_plan, items)

    assert latest is not None and latest["value"] == "new"
    assert latest["operands"][0]["evidence_ids"] == ["evidence-new"]
    assert distance is not None and distance["value"] == 10.0
    assert distance["unit"] == "days"
    assert latest["hidden_model_calls"] == 0
    assert latest["canonical_mutation"] is False


def test_before_operator_bounds_session_text_to_query_relevant_sentence() -> None:
    plan = _plan("What new kitchen gadget did I invest in before getting the Air Fryer?")
    items = [
        {
            **_item("older", "2023-05-21T05:48:00+00:00"),
            "payload": {
                "memory_text": (
                    "assistant: unrelated meal planning details.\n" * 100
                    + "user: I invested in a new Instant Pot for the kitchen."
                )
            },
        },
        {
            **_item("newer", "2023-05-21T22:54:00+00:00"),
            "payload": {"memory_text": "user: I got an Air Fryer yesterday."},
        },
    ]

    result = execute_query_operator(plan, items)

    assert result is not None
    assert result["value"] == {
        "selected": "user: I invested in a new Instant Pot for the kitchen.",
        "direction": "before",
    }
    assert len(result["value"]["selected"]) <= 600


def test_temporal_distance_extracts_query_relevant_dates_from_gated_sessions() -> None:
    plan = _plan("How many days had passed between the Sunday mass and the Ash Wednesday service?")
    items = [
        {
            **_item("mass", "2023-02-20T16:20:00+00:00"),
            "payload": {"memory_text": "user: I attended Sunday mass on January 2nd."},
        },
        {
            **_item("service", "2023-02-20T04:43:00+00:00"),
            "payload": {
                "memory_text": "user: I attended the Ash Wednesday service on February 1st."
            },
        },
    ]

    result = execute_query_operator(plan, items)

    assert result is not None and result["value"] == 30
    assert result["unit"] == "days"
    assert result["date_boundary"] == "exclusive"
    assert {pointer["time_basis"] for pointer in result["operands"]} == {"EXPLICIT_CALENDAR_DATE"}


def test_temporal_distance_retains_a_resolved_anchor_without_claiming_a_pair() -> None:
    plan = _plan(
        "How many days had passed between the Sunday mass and the Ash Wednesday service?"
    )
    item = {
        "evidence_id": "service-evidence",
        "source_ref": "memory://session/service/turn/0",
        "observed_at": "2023-02-20T04:43:00+00:00",
        "payload": {
            "memory_text": "user: I attended the Ash Wednesday service on February 1st."
        },
    }

    result = execute_query_operator(plan, [item])

    assert result is not None and result["status"] == "PARTIAL"
    assert result["value"] is None
    assert result["reason"] == "TIME_UNCERTAIN"
    assert result["completeness"] == {
        "required_slots": ["EVENT_1", "EVENT_2"],
        "filled_slots": ["EVENT_2"],
        "unresolved_reasons": ["TIME_UNCERTAIN"],
    }
    assert result["operands"][0]["evidence_ids"] == ["service-evidence"]
    assert result["operands"][0]["source_ref"] == "memory://session/service/turn/0"
    assert "Ash Wednesday" in result["operands"][0]["source_span"]


def test_relative_distance_uses_reference_time_and_calendar_months() -> None:
    request = RetrievalRequest(
        route="L1",
        query="How many months have passed since I visited the museum with a friend?",
        requested_scope=SCOPE,
        as_of=datetime.fromisoformat("2023-03-25T17:18:00+00:00"),
    )
    plan = QueryPlanner().plan(request)
    item = {
        **_item("museum", "2022-10-22T18:38:00+00:00"),
        "payload": {"memory_text": "user: I visited the Science Museum with a friend today."},
    }

    result = execute_query_operator(plan, [item])

    assert result is not None and result["value"] == 5
    assert result["unit"] == "months"
    assert result["operands"][0]["time_basis"] == "RELATIVE_TO_CANONICAL_VALID_TIME"


def test_sum_and_compare_are_deterministic_and_unit_aware() -> None:
    items = [
        _item(10, "2026-08-01T00:00:00+00:00"),
        _item(16, "2026-08-11T00:00:00+00:00"),
    ]

    total = execute_query_operator(_plan("What is the total?"), items)
    comparison = execute_query_operator(
        _plan("What is the difference between the two values?"), items
    )

    assert total is not None and total["value"] == 26.0
    assert comparison is not None and comparison["value"] == 6.0


def test_operator_abstains_on_open_issue_scope_or_missing_operand() -> None:
    issue = execute_query_operator(
        _plan("What was my latest state?"),
        [_item("uncertain", "2026-08-01T00:00:00+00:00", issue=True)],
    )
    wrong_scope = _item("other", "2026-08-01T00:00:00+00:00")
    wrong_scope["scope_predicate"] = {"project_ids": ["other"]}
    scope = execute_query_operator(_plan("What was my latest state?"), [wrong_scope])
    missing = execute_query_operator(_plan("What is the difference between the two values?"), [])

    assert issue is not None and issue["reason"] == "OPEN_ISSUE_PRESENT"
    assert scope is not None and scope["reason"] == "SCOPE_INCONSISTENT"
    assert missing is not None and missing["reason"] == "OPERAND_MISSING"
    assert datetime.now(UTC).tzinfo is not None


def test_scalar_count_uses_relevant_sentence_and_rejects_missing_qualifier() -> None:
    released = execute_query_operator(
        _plan("How many copies of the debut album were released worldwide?"),
        [
            {
                **_item("album", "2023-05-27T15:55:00+00:00"),
                "payload": {
                    "memory_text": (
                        "assistant: 1.\nuser: The debut album was limited to 500 copies worldwide."
                    )
                },
            }
        ],
    )
    missing_tank = execute_query_operator(
        _plan("How many fish are there in my 30-gallon tank?"),
        [
            {
                **_item("tank", "2023-05-27T15:55:00+00:00"),
                "payload": {"memory_text": "My 20-gallon tank has ten fish."},
            }
        ],
    )

    assert released is not None and released["value"] == "500"
    assert released["route_reason"] == "EXPLICIT_SCALAR_COUNT_FACT"
    assert missing_tank is not None
    assert missing_tank["status"] == "ABSTAINED"
    assert missing_tank["reason"] == "NUMERIC_OPERAND_MISSING"


def test_sum_requires_two_numeric_operands_and_compare_rejects_ambiguity() -> None:
    partial_sum = execute_query_operator(
        _plan("What is the total amount?"),
        [_item(10, "2023-05-27T15:55:00+00:00")],
    )
    ambiguous_compare = execute_query_operator(
        _plan("What is the difference between the first and second values?"),
        [
            _item(10, "2023-05-25T15:55:00+00:00"),
            _item(20, "2023-05-26T15:55:00+00:00"),
            _item(30, "2023-05-27T15:55:00+00:00"),
        ],
    )

    assert partial_sum is not None and partial_sum["reason"] == "NUMERIC_OPERAND_MISSING"
    assert ambiguous_compare is not None
    assert ambiguous_compare["reason"] == "OPERAND_AMBIGUOUS"


def test_binary_event_order_binds_both_anchors_and_selects_earliest_event() -> None:
    plan = _plan(
        "Which event happened first, my participation in the #PlankChallenge "
        "or my post about vegan chili recipe?"
    )
    chili = {
        **_item("chili", "2023-03-10T11:15:00+00:00"),
        "payload": {
            "memory_text": (
                "user: I shared a recipe for vegan chili in an Instagram post yesterday."
            )
        },
    }
    plank = {
        **_item("plank", "2023-03-15T14:28:00+00:00"),
        "payload": {"memory_text": "user: I participated in the #PlankChallenge today."},
    }

    result = execute_query_operator(plan, [plank, chili])

    assert result is not None and result["status"] == "OK"
    assert result["value"] == {
        "selected": "user: I shared a recipe for vegan chili in an Instagram post yesterday.",
        "ordering": "earliest",
    }
    assert len(result["operands"]) == 2
    assert {pointer["time_basis"] for pointer in result["operands"]} == {
        "RELATIVE_TO_CANONICAL_VALID_TIME"
    }


def test_binary_event_order_abstains_when_one_anchor_is_missing() -> None:
    plan = _plan("Which event happened first, the meeting with Rachel or the pride parade?")
    meeting = {
        **_item("meeting", "2023-05-09T07:55:00+00:00"),
        "payload": {"memory_text": "user: I had a meeting with Rachel on April 10th."},
    }

    result = execute_query_operator(plan, [meeting])

    assert result is not None and result["status"] == "ABSTAINED"
    assert result["reason"] == "OPERAND_MISSING"


def test_relative_point_can_use_a_reranked_temporal_sentence_without_term_overlap() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What gardening-related activity did I do two weeks ago?",
        requested_scope=SCOPE,
        as_of=datetime.fromisoformat("2023-05-05T16:42:00+00:00"),
    )
    plan = QueryPlanner().plan(request)
    planting = {
        **_item("planting", "2023-04-21T00:30:00+00:00"),
        "payload": {"memory_text": "user: I just planted 12 new tomato saplings today."},
    }

    result = execute_query_operator(plan, [planting])

    assert result is not None and result["status"] == "OK"
    assert result["value"] == {
        "selected": "user: I just planted 12 new tomato saplings today.",
        "relation": "at_relative_point",
        "target_date": "2023-04-21",
        "selected_date": "2023-04-21",
        "date_distance_days": 0,
    }


def test_relative_point_ignores_unrepresentable_historical_span() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What family life event did I participate in a week ago?",
        requested_scope=SCOPE,
        as_of=datetime.fromisoformat("2023-06-22T18:33:00+00:00"),
    )
    plan = QueryPlanner().plan(request)
    ancient_history = {
        **_item("history", "2023-06-01T00:00:00+00:00"),
        "evidence_id": "evidence-history",
        "payload": {
            "memory_text": (
                "assistant: This religion originated around 4000 years ago."
            )
        },
    }
    family_event = {
        **_item("family", "2023-06-15T18:33:00+00:00"),
        "evidence_id": "evidence-family",
        "payload": {
            "memory_text": "user: I attended my cousin's wedding today."
        },
    }

    result = execute_query_operator(plan, [ancient_history, family_event])

    assert result is not None and result["status"] == "OK"
    assert "cousin's wedding" in str(result["value"]["selected"])


def test_relative_user_event_rejects_assistant_closing_and_requires_entity_majority() -> None:
    request = RetrievalRequest(
        route="L1",
        query="I mentioned cooking something for my friend two days ago. What was it?",
        requested_scope=SCOPE,
        as_of=datetime.fromisoformat("2022-04-12T22:57:00+00:00"),
    )
    plan = QueryPlanner().plan(request)
    assistant_closing = {
        **_item("closing", "2022-04-10T23:28:00+00:00"),
        "evidence_id": "evidence-closing",
        "payload": {"memory_text": "assistant: Take care, and happy cooking!"},
    }
    user_event = {
        **_item("cake", "2022-04-10T23:27:00+00:00"),
        "evidence_id": "evidence-cake",
        "payload": {
            "memory_text": (
                "user: I just baked a chocolate cake for my friend's birthday party."
            )
        },
    }

    result = execute_query_operator(plan, [assistant_closing, user_event])

    assert "subject_role" not in plan.operator_arguments
    assert result is not None and result["status"] == "OK"
    assert "chocolate cake" in str(result["value"]["selected"])
    assert "happy cooking" not in str(result["value"]["selected"])


def test_relative_point_abstains_when_only_a_nearby_date_is_available() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What gardening-related activity did I do two weeks ago?",
        requested_scope=SCOPE,
        as_of=datetime.fromisoformat("2023-05-05T16:42:00+00:00"),
    )
    plan = QueryPlanner().plan(request)
    nearby = {
        **_item("nearby", "2023-04-20T00:30:00+00:00"),
        "payload": {"memory_text": "user: I watered the garden today."},
    }

    result = execute_query_operator(plan, [nearby])

    assert result is not None and result["status"] == "ABSTAINED"
    assert result["reason"] == "RELATIVE_POINT_NOT_FOUND"


def test_issue_date_is_not_used_as_the_read_event_date() -> None:
    request = RetrievalRequest(
        route="L1",
        query="How many days ago did I read the March 15th issue of The New Yorker?",
        requested_scope=SCOPE,
        as_of=datetime.fromisoformat("2023-04-01T08:36:00+00:00"),
    )
    plan = QueryPlanner().plan(request)
    item = {
        **_item("new-yorker", "2023-03-20T18:06:00+00:00"),
        "payload": {"memory_text": ("user: I read the March 15th issue of The New Yorker today.")},
    }

    result = execute_query_operator(plan, [item])

    assert result is not None and result["status"] == "OK"
    assert result["value"] == 12
    assert result["operands"][0]["time_basis"] == "RELATIVE_TO_CANONICAL_VALID_TIME"
