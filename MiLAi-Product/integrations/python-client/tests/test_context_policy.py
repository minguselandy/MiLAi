from __future__ import annotations

from milai_client.context_policy import (
    PrefetchContext,
    compile_agent_messages,
    prepare_compact_prefetch,
    prepare_prefetch,
    prepare_turn_window_prefetch,
)


class ExactTestCounter:
    def count_text(self, text: str) -> int:
        return len(text.split())


def test_available_memory_is_compiled_and_provenance_stays_in_sidecar() -> None:
    context = prepare_prefetch(
        {
            "status": "OK",
            "items": [
                {
                    "memory_text": "Synthetic private fact is LANTERN-8427.",
                    "claim_id": "claim-1",
                    "evidence_id": "evidence-1",
                    "authority": "ACTION_SAFE",
                    "epistemic_status": "SUPPORTED",
                }
            ],
            "open_issue_ids": [],
            "trace_id": "trace-1",
            "request_id": "request-1",
            "degraded_components": [],
            "abstention_reason": None,
        }
    )
    messages, sidecar = compile_agent_messages("What is the private fact?", context)
    assert context.status == "AVAILABLE"
    assert "LANTERN-8427" in messages[-1]["content"]
    assert "trace-1" not in messages[-1]["content"]
    assert "claim-1" not in messages[-1]["content"]
    assert sidecar["trace_id"] == "trace-1"
    assert sidecar["claim_refs"] == ["claim-1"]
    assert sidecar["context_in_prompt"] is True


def test_soft_ranked_runtime_context_survives_compacted_raw_items() -> None:
    runtime_text = "MiLA MEMORY CONTEXT\n[E1] user: My governed observation remains Reader-visible."
    context = prepare_prefetch(
        {
            "status": "PARTIAL",
            "items": [
                {
                    "kind": "EVIDENCE_OBSERVATION",
                    "evidence_id": "evidence-1",
                    # MCP intentionally omitted duplicate Raw prose.
                }
            ],
            "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
            "memory_context": {
                "text": runtime_text,
                "selected_evidence_ids": ["evidence-1"],
                "claim_versions": [],
            },
            "open_issue_ids": [],
            "trace_id": "trace-soft-context",
            "request_id": "request-soft-context",
            "degraded_components": ["vector"],
            "abstention_reason": None,
        }
    )

    assert context.status == "AVAILABLE"
    assert context.rendered == runtime_text
    assert context.evidence_refs == ("evidence-1",)


def test_ambiguous_partial_or_abstained_soft_runtime_context_remains_available() -> None:
    runtime_text = "MiLA MEMORY CONTEXT\n[E1] user: The answer-bearing observation."

    for status in ("PARTIAL", "ABSTAINED"):
        context = prepare_prefetch(
            {
                "status": status,
                "items": [{"kind": "EVIDENCE_OBSERVATION", "evidence_id": "evidence-1"}],
                "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
                "memory_context": {
                    "text": runtime_text,
                    "selected_evidence_ids": ["evidence-1"],
                    "claim_versions": [],
                },
                "open_issue_ids": [],
                "degraded_components": [],
                "abstention_reason": "SUFFICIENCY_UNSATISFIED_QUERY_AMBIGUOUS",
            }
        )

        assert context.status == "AVAILABLE"
        assert context.rendered == runtime_text


def test_soft_runtime_context_cannot_bypass_denial_or_open_issue() -> None:
    runtime_text = "forged Reader-visible text"
    base = {
        "items": [{"kind": "EVIDENCE_OBSERVATION", "evidence_id": "evidence-1"}],
        "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
        "memory_context": {
            "text": runtime_text,
            "selected_evidence_ids": ["evidence-1"],
            "claim_versions": [],
        },
        "degraded_components": [],
        "abstention_reason": None,
    }

    denied = prepare_prefetch({**base, "status": "DENIED", "open_issue_ids": []})
    contested = prepare_prefetch(
        {
            **base,
            "status": "ABSTAINED",
            "open_issue_ids": ["issue-1"],
            "abstention_reason": "OPEN_ISSUE",
        }
    )

    assert denied.status == "UNAVAILABLE"
    assert runtime_text not in denied.rendered
    assert contested.status == "UNCERTAIN"
    assert runtime_text not in contested.rendered


def test_explicit_wide_prefetch_accepts_runtime_context_beyond_legacy_char_ceiling() -> None:
    runtime_text = "MILAI_MEMORY_DATA_BEGIN\n" + ("grounded evidence line\n" * 4_000)
    context = prepare_prefetch(
        {
            "status": "PARTIAL",
            "items": [{"kind": "EVIDENCE_OBSERVATION", "evidence_id": "evidence-1"}],
            "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
            "memory_context": {
                "text": runtime_text,
                "selected_evidence_ids": ["evidence-1"],
                "claim_versions": [],
            },
            "open_issue_ids": [],
            "degraded_components": [],
            "abstention_reason": "SUFFICIENCY_UNSATISFIED_QUERY_AMBIGUOUS",
        },
        max_context_chars=262_144,
    )

    assert len(runtime_text) > 65_536
    assert context.status == "AVAILABLE"
    assert context.rendered == runtime_text


def test_strict_or_missing_runtime_context_does_not_bypass_partial_boundary() -> None:
    base = {
        "status": "PARTIAL",
        "items": [{"kind": "EVIDENCE_OBSERVATION", "evidence_id": "evidence-1"}],
        "open_issue_ids": [],
        "degraded_components": ["vector"],
        "abstention_reason": None,
    }

    strict = prepare_prefetch(
        {
            **base,
            "reader_evidence_boundary": "DECISION_ACCEPTED_ONLY",
            "memory_context": {
                "text": "must not cross the strict incomplete boundary",
                "selected_evidence_ids": ["evidence-1"],
                "claim_versions": [],
            },
        }
    )
    missing = prepare_prefetch(
        {
            **base,
            "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
            "memory_context": {
                "text": "",
                "selected_evidence_ids": ["evidence-1"],
                "claim_versions": [],
            },
        }
    )

    assert strict.status == "UNAVAILABLE"
    assert missing.status == "UNAVAILABLE"


def test_open_issue_discards_fact_text_and_compiles_uncertainty() -> None:
    context = prepare_prefetch(
        {
            "status": "ABSTAINED",
            "items": [{"memory_text": "must-not-be-used"}],
            "open_issue_ids": ["issue-1"],
            "trace_id": "trace-2",
            "request_id": "request-2",
            "degraded_components": [],
            "abstention_reason": "CANONICAL_GATE_REJECTED",
        }
    )
    messages, sidecar = compile_agent_messages("Which branch is true?", context)
    assert context.status == "UNCERTAIN"
    assert "must-not-be-used" not in messages[-1]["content"]
    assert "issue-1" not in messages[-1]["content"]
    assert sidecar["open_issue_ids"] == ["issue-1"]


def test_canonical_mcp_claim_is_compiled_without_provenance_in_prompt() -> None:
    context = prepare_prefetch(
        {
            "status": "OK",
            "items": [
                {
                    "claim_id": "claim-2",
                    "claim_version_id": "version-2",
                    "subject_id": "synthetic-project",
                    "predicate": "runtime.python.version",
                    "claim_type": "RUNTIME_VERSION",
                    "payload": {"python": "3.11"},
                    "authority": "ACTION_SAFE",
                    "epistemic_status": "SUPPORTED",
                    "evidence_ids": ["evidence-2"],
                }
            ],
            "open_issue_ids": [],
            "trace_id": "trace-3",
            "degraded_components": [],
            "abstention_reason": None,
        }
    )
    messages, sidecar = compile_agent_messages("What is the runtime Python version?", context)

    assert context.status == "AVAILABLE"
    assert '"python":"3.11"' in messages[-1]["content"]
    assert "claim-2" not in messages[-1]["content"]
    assert "evidence-2" not in messages[-1]["content"]
    assert sidecar["claim_refs"] == ["claim-2"]
    assert sidecar["evidence_refs"] == ["evidence-2"]


def test_canonical_derived_result_is_compiled_without_operand_pointers() -> None:
    context = prepare_prefetch(
        {
            "status": "OK",
            "items": [
                {
                    "claim_id": "claim-1",
                    "claim_version_id": "version-1",
                    "payload": {"memory_text": "user: The first event was recorded."},
                    "authority": "ACTION_SAFE",
                    "epistemic_status": "VERIFIED",
                    "evidence_ids": ["evidence-1"],
                }
            ],
            "open_issue_ids": [],
            "degraded_components": [],
            "abstention_reason": None,
            "derived_result": {
                "status": "OK",
                "kind": "DERIVED_QUERY_RESULT",
                "operator": "TEMPORAL_DISTANCE",
                "value": 18.0,
                "unit": "days",
                "date_boundary": "inclusive",
                "operands": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "version-1",
                        "evidence_ids": ["evidence-1"],
                        "valid_time_from": "2026-08-01T00:00:00+00:00",
                    }
                ],
                "hidden_model_calls": 0,
                "canonical_mutation": False,
            },
        }
    )

    assert '"value":18.0' in context.rendered
    assert '"unit":"days"' in context.rendered
    assert "claim-1" not in context.rendered
    assert "evidence-1" not in context.rendered


def test_accepted_evidence_composition_is_compiled_for_model_use() -> None:
    context = prepare_prefetch(
        {
            "status": "HIT",
            "items": [
                {
                    "subject_id": "synthetic-coffee-mugs",
                    "authority": "EVIDENCE_ONLY",
                    "evidence_id": "evidence-price",
                }
            ],
            "open_issue_ids": [],
            "degraded_components": [],
            "abstention_reason": None,
            "derived_result": {
                "status": "COMPLETE",
                "kind": "EVIDENCE_COMPOSITION_RESULT",
                "operator": "DIVIDE_EVIDENCE_VALUES",
                "operand_authority": "ACCEPTED_BINDING_ONLY",
                "value": 12,
                "unit": "USD_PER_ITEM",
                "display_value": "$12 per item",
                "operands": [
                    {
                        "evidence_id": "evidence-price",
                        "source_ref": "private-source-pointer",
                    },
                    {
                        "evidence_id": "evidence-count",
                        "source_ref": "other-private-source-pointer",
                    },
                ],
                "hidden_model_calls": 0,
                "canonical_mutation": False,
            },
        }
    )

    assert '"operator":"DIVIDE_EVIDENCE_VALUES"' in context.rendered
    assert '"value":12' in context.rendered
    assert '"display_value":"$12 per item"' in context.rendered
    assert "evidence-price" not in context.rendered
    assert "private-source-pointer" not in context.rendered


def test_abstained_or_invalid_derived_result_never_becomes_model_visible() -> None:
    recall = {
        "status": "OK",
        "items": [
            {
                "memory_text": "user: A safe source fact.",
                "authority": "ACTION_SAFE",
                "epistemic_status": "VERIFIED",
            }
        ],
        "open_issue_ids": [],
        "degraded_components": [],
        "abstention_reason": None,
        "derived_result": {
            "status": "ABSTAINED",
            "kind": "DERIVED_QUERY_RESULT",
            "operator": "TEMPORAL_DISTANCE",
            "reason": "TIME_UNCERTAIN",
            "operands": [],
            "hidden_model_calls": 0,
            "canonical_mutation": False,
        },
    }

    context = prepare_prefetch(recall)

    assert "derived_query_result" not in context.rendered
    assert "TIME_UNCERTAIN" not in context.rendered


def test_no_memory_and_unavailable_are_explicit() -> None:
    for context, expected in (
        (PrefetchContext.no_memory(), "NO_MEMORY"),
        (PrefetchContext.unavailable(), "UNAVAILABLE"),
    ):
        messages, sidecar = compile_agent_messages("What is the fact?", context)
        assert f"MEMORY_STATUS={expected}" in messages[-1]["content"]
        assert sidecar["memory_status"] == expected


def test_abstained_no_candidate_is_no_memory_but_gate_rejection_is_uncertain() -> None:
    base = {
        "status": "ABSTAINED",
        "items": [],
        "open_issue_ids": [],
        "degraded_components": [],
    }
    assert prepare_prefetch({**base, "abstention_reason": "NO_CANDIDATE"}).status == "NO_MEMORY"
    assert (
        prepare_prefetch({**base, "abstention_reason": "CANONICAL_GATE_REJECTED"}).status
        == "UNCERTAIN"
    )


def test_access_outcome_vnext_statuses_keep_absence_conflict_and_failure_distinct() -> None:
    base = {
        "items": [],
        "open_issue_ids": [],
        "degraded_components": [],
        "abstention_reason": None,
    }
    assert prepare_prefetch({**base, "status": "ABSENT"}).status == "NO_MEMORY"
    assert prepare_prefetch({**base, "status": "CONTESTED"}).status == "UNCERTAIN"
    assert prepare_prefetch({**base, "status": "ABSTAINED"}).status == "UNCERTAIN"
    assert prepare_prefetch({**base, "status": "DENIED"}).status == "UNAVAILABLE"
    assert prepare_prefetch({**base, "status": "UNAVAILABLE"}).status == "UNAVAILABLE"


def test_compact_prefetch_selects_relevant_user_facts_within_budget() -> None:
    noisy = "assistant: " + "unrelated setup details " * 100
    context = prepare_compact_prefetch(
        {
            "status": "OK",
            "items": [
                {
                    "claim_id": "claim-1",
                    "valid_time_from": "2023-03-19T15:44:00+00:00",
                    "evidence_ids": ["evidence-1"],
                    "authority": "ACTION_SAFE",
                    "epistemic_status": "VERIFIED",
                    "payload": {
                        "session_id": "session-1",
                        "memory_text": (
                            f"{noisy}\nuser: My cat is named Luna. She likes sunny windows.\n"
                            f"{noisy}"
                        ),
                    },
                }
            ],
            "open_issue_ids": [],
            "degraded_components": [],
            "abstention_reason": None,
            "trace_id": "trace-1",
        },
        query="What is the name of my cat?",
        max_context_chars=600,
    )

    assert context.status == "AVAILABLE"
    assert "Luna" in context.rendered
    assert "valid_time_from=2023-03-19T15:44:00+00:00" in context.rendered
    assert "session_id=session-1" not in context.rendered
    assert context.session_refs == ("session-1",)
    assert context.compiler_version == "grouped-compact/v3"
    assert len(context.rendered) <= 600
    assert context.claim_refs == ("claim-1",)
    assert context.evidence_refs == ("evidence-1",)


def test_compact_prefetch_selects_requested_ordinal_list_item() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "assistant: 25. Monologue (internal or external). "
                "26. Soliloquy (dramatic or introspective). "
                "27. Sound effects (ambient, diegetic, or non-diegetic). "
                "28. Music (genre or tempo).",
                session="parameter-list",
                score=0.9,
            )
        ),
        query="Can you remind me what was the 27th parameter on that list?",
        max_context_chars=500,
    )

    assert "27. Sound effects (ambient, diegetic, or non-diegetic)." in context.rendered
    assert "28. Music" not in context.rendered


def test_compact_prefetch_shares_governance_header_across_items() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "user: My first preference is tea.",
                session="session-alpha-uuid",
                score=0.9,
            ),
            _item(
                "user: My second preference is quiet rooms.",
                session="session-beta-uuid",
                score=0.8,
            ),
        ),
        query="What are my preferences for tea and rooms?",
        max_context_chars=700,
    )

    assert context.rendered.count("GROUP authority=ACTION_SAFE epistemic=VERIFIED") == 1
    assert context.rendered.count("ITEM_BEGIN") == 2
    assert "session-alpha-uuid" not in context.rendered
    assert "session-beta-uuid" not in context.rendered
    assert context.session_refs == ("session-alpha-uuid", "session-beta-uuid")


def test_compact_prefetch_moves_legacy_embedded_session_metadata_to_sidecar() -> None:
    item = _item(
        "session_id=legacy-session-uuid\n"
        "valid_time_from=2023-11-30T18:35:00+00:00\n"
        "user: I now have 25 postcards.",
        session="unused-structured-session",
        score=0.9,
    )
    payload = item.get("payload")
    assert isinstance(payload, dict)
    payload.pop("session_id")
    context = prepare_compact_prefetch(
        _recall(item),
        query="How many postcards do I have now?",
        max_context_chars=700,
    )

    assert "legacy-session-uuid" not in context.rendered
    assert "valid_time_from=2023-11-30T18:35:00+00:00" in context.rendered
    assert context.session_refs == ("legacy-session-uuid",)


def test_compact_prefetch_keeps_derived_value_without_operand_identifiers() -> None:
    recall = _recall(
        _item(
            "user: I attended the first event on January 2nd.",
            session="dated",
            score=0.9,
        )
    )
    recall["derived_result"] = {
        "status": "OK",
        "kind": "DERIVED_QUERY_RESULT",
        "operator": "TEMPORAL_DISTANCE",
        "value": 30,
        "unit": "days",
        "date_boundary": "exclusive",
        "operands": [
            {
                "claim_id": "claim-secret",
                "claim_version_id": "version-secret",
                "evidence_ids": ["evidence-secret"],
                "valid_time_from": "2023-01-02T00:00:00+00:00",
            }
        ],
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }

    context = prepare_compact_prefetch(
        recall,
        query="How many days passed?",
        max_context_chars=700,
    )

    assert "VALUE 30 unit=days" in context.rendered
    assert "claim-secret" not in context.rendered
    assert "evidence-secret" not in context.rendered


def test_compact_prefetch_renders_selected_event_as_noncanonical_derived_evidence() -> None:
    recall = _recall(
        _item(
            "user: I discussed gardening plans.",
            session="dated",
            score=0.9,
        )
    )
    recall["derived_result"] = {
        "status": "OK",
        "kind": "DERIVED_QUERY_RESULT",
        "operator": "TEMPORAL_BEFORE_AFTER",
        "value": {
            "selected": "I planted 12 new tomato saplings today.",
            "relation": "at_relative_point",
            "target_date": "2023-04-21",
            "selected_date": "2023-04-21",
            "date_distance_days": 0,
        },
        "date_boundary": "exclusive",
        "operands": [{"claim_id": "claim-secret"}],
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }

    context = prepare_compact_prefetch(
        recall,
        query="What gardening activity did I do two weeks ago?",
        max_context_chars=700,
    )

    assert "GROUP authority=QUERY_OPERATOR epistemic=VERIFIED_DERIVATION" in context.rendered
    assert 'selected_event="I planted 12 new tomato saplings today."' in context.rendered
    assert context.rendered.count("I planted 12 new tomato saplings today.") == 1
    assert (
        'VALUE {"date_distance_days":0,"relation":"at_relative_point",'
        '"selected_date":"2023-04-21","target_date":"2023-04-21"}' in context.rendered
    )
    assert "claim-secret" not in context.rendered
    assert context.compiler_version == "grouped-compact/v3"


def test_compact_prefetch_matches_inflected_update_fact_under_tight_budget() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "assistant: Rachel has options.\n"
                "user: My friend Rachel moved back to the suburbs after living downtown.\n"
                "assistant: Rachel can decide later.",
                session="rachel-update",
                score=0.9,
            )
        ),
        query="Where did Rachel move after her recent relocation?",
        max_context_chars=330,
    )

    assert "Rachel moved back to the suburbs" in context.rendered


def test_compact_prefetch_does_not_reorder_non_update_query_for_inflection() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "user: I am making an elaborate lasagna for dinner tonight.\n"
                "user: The exact Negroni count is ten from my home cocktail notes.\n"
                "assistant: Dinner is ready.",
                session="stable-exact-ranking",
                score=0.9,
            )
        ),
        query="How many times did I make a Negroni?",
        max_context_chars=256,
    )

    assert "The exact Negroni count is ten" in context.rendered
    assert "making an elaborate lasagna" not in context.rendered


def test_compact_prefetch_omits_oversized_derived_value_without_failing_budget() -> None:
    recall = _recall(
        _item(
            "user: The bounded source answer is Instant Pot.",
            session="bounded-source",
            score=0.9,
        )
    )
    recall["derived_result"] = {
        "status": "OK",
        "kind": "DERIVED_QUERY_RESULT",
        "operator": "TEMPORAL_BEFORE_AFTER",
        "value": {"selected": "x" * 2_000, "direction": "before"},
        "unit": None,
        "date_boundary": "exclusive",
        "operands": [{"claim_id": "claim-1"}],
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }

    context = prepare_compact_prefetch(
        recall,
        query="What was selected before the anchor?",
        max_context_chars=600,
    )

    assert context.status == "AVAILABLE"
    assert "Instant Pot" in context.rendered
    assert "x" * 100 not in context.rendered
    assert len(context.rendered) <= 600


def test_compact_prefetch_never_compacts_away_open_issue_abstention() -> None:
    context = prepare_compact_prefetch(
        {
            "status": "ABSTAINED",
            "items": [
                {
                    "memory_text": "user: a disputed fact",
                    "authority": "ACTION_SAFE",
                    "epistemic_status": "CHALLENGED",
                }
            ],
            "open_issue_ids": ["issue-1"],
            "degraded_components": [],
            "abstention_reason": "OPEN_ISSUE",
        },
        query="What is the fact?",
        max_context_chars=600,
    )

    assert context.status == "UNCERTAIN"
    assert '"memory_items":[]' in context.rendered
    assert context.open_issue_ids == ("issue-1",)


def _recall(*items: dict[str, object]) -> dict[str, object]:
    return {
        "status": "OK",
        "items": list(items),
        "open_issue_ids": [],
        "degraded_components": [],
        "abstention_reason": None,
    }


def _item(text: str, *, session: str, score: float) -> dict[str, object]:
    return {
        "authority": "ACTION_SAFE",
        "epistemic_status": "VERIFIED",
        "relevance_score": score,
        "payload": {"session_id": session, "memory_text": text},
    }


def test_turn_window_preserves_assistant_answer_instead_of_fixed_user_bonus() -> None:
    context = prepare_turn_window_prefetch(
        _recall(
            _item(
                "user: What runtime should I use for the deployment?\n"
                "assistant: I recommend Python 3.12 for the deployment.\n"
                "user: Thanks, I will update the configuration.",
                session="assistant-answer",
                score=0.9,
            )
        ),
        query="What did you recommend for my deployment runtime?",
        max_context_chars=600,
        max_context_tokens=80,
        token_counter=ExactTestCounter(),
    )

    assert "assistant: I recommend Python 3.12" in context.rendered


def test_compact_prefetch_scores_assistant_role_for_prior_recommendation() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "user: Which languages should I learn for back-end development?\n"
                "assistant: Learn a back-end language such as Ruby, Python, or PHP.\n"
                "user: Which online back-end development courses do you recommend?",
                session="language-recommendation",
                score=0.9,
            )
        ),
        query="Which back-end programming languages did you recommend I learn?",
        max_context_chars=380,
    )

    assert "assistant: Learn a back-end language such as Ruby, Python, or PHP." in context.rendered


def test_compact_prefetch_treats_you_mentioned_and_say_as_assistant_intent() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "user: What are natural remedies for dark circles?\n"
                "assistant: Tomato juice mixed with lemon juice should be washed off "
                "after 10 minutes.\n"
                "user: I mentioned that another remedy sounded useful.",
                session="dark-circles",
                score=0.9,
            )
        ),
        query="You mentioned tomato juice; how long did you say I should leave it on?",
        max_context_chars=600,
    )

    assert "assistant: Tomato juice" in context.rendered
    assert "after 10 minutes" in context.rendered


def test_compact_prefetch_carries_assistant_role_across_multiline_list() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "user: How do I become a full-stack developer?\n"
                "assistant: Follow these steps:\n"
                "1. Learn HTML and CSS.\n"
                "2. Learn a back-end programming language such as Ruby, Python, or PHP.\n"
                "user: Which courses should I take?",
                session="multiline-assistant",
                score=0.9,
            )
        ),
        query="Which back-end programming languages did you recommend I learn?",
        max_context_chars=390,
    )

    assert "assistant: Learn a back-end programming language" in context.rendered
    assert "\na\n" not in context.rendered


def test_compact_prefetch_keeps_numbered_subject_for_later_pronoun_fact() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "user: Compare 6S, MAJA, and Sen2Cor.\n"
                "assistant: 6S, MAJA, and Sen2Cor are all algorithms for atmospheric "
                "correction of remote sensing images.\n"
                "1. 6S is a radiative transfer model. It is implemented in the "
                "SIAC\\_GEE tool.\n"
                "2. MAJA uses a physical atmospheric model. It is implemented in MAJA.",
                session="atmospheric-correction",
                score=0.9,
            )
        ),
        query="Which algorithm is implemented in the SIAC_GEE tool?",
        max_context_chars=360,
    )

    assert "assistant: 6S: It is implemented in the SIAC\\_GEE tool." in context.rendered


def test_compact_prefetch_scores_numeric_user_fact_for_quantity_question() -> None:
    context = prepare_compact_prefetch(
        _recall(
            _item(
                "assistant: Have you changed any laptop hardware aside from the RAM upgrade?\n"
                "user: Battery life was longer before I installed 16GB of RAM.",
                session="ram-upgrade",
                score=0.9,
            )
        ),
        query="How much RAM did I upgrade my laptop to?",
        max_context_chars=330,
    )

    assert "user: Battery life was longer before I installed 16GB" in context.rendered


def test_turn_window_keeps_later_effective_number_without_partial_truncation() -> None:
    context = prepare_turn_window_prefetch(
        _recall(
            _item(
                "user: My earlier travel budget was 100 dollars.\n"
                "assistant: I recorded the earlier amount.\n"
                "user: I updated my current travel budget to 250 dollars exactly.",
                session="numeric-update",
                score=0.95,
            )
        ),
        query="What is my updated current travel budget?",
        max_context_chars=500,
        max_context_tokens=64,
        token_counter=ExactTestCounter(),
    )

    assert "250 dollars exactly." in context.rendered
    assert context.rendered_tokens is not None and context.rendered_tokens <= 64


def test_turn_window_preserves_exact_date_amount_in_adjacent_assistant_turn() -> None:
    context = prepare_turn_window_prefetch(
        _recall(
            _item(
                "user: What payment deadline did we settle on?\n"
                "assistant: I told you to pay $425.75 on 2026-08-23 at 14:30.\n"
                "user: I acknowledged the deadline.",
                session="payment",
                score=0.8,
            )
        ),
        query="What payment deadline and amount did you tell me?",
        max_context_chars=500,
        max_context_tokens=64,
        token_counter=ExactTestCounter(),
    )

    assert "$425.75 on 2026-08-23 at 14:30" in context.rendered


def test_top_item_gets_majority_budget_instead_of_equal_distractor_split() -> None:
    context = prepare_turn_window_prefetch(
        _recall(
            _item(
                "user: deployment runtime question\n"
                "assistant: The exact deployment runtime is Python 3.12.",
                session="top",
                score=0.95,
            ),
            _item("user: unrelated garden notes " * 20, session="distractor-1", score=0.2),
            _item("user: unrelated recipe notes " * 20, session="distractor-2", score=0.1),
        ),
        query="What is the exact deployment runtime?",
        max_context_chars=650,
        max_context_tokens=80,
        token_counter=ExactTestCounter(),
    )

    assert "exact deployment runtime is Python 3.12" in context.rendered
    assert context.rendered_tokens is not None and context.rendered_tokens <= 80
