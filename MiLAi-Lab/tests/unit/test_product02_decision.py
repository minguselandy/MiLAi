from __future__ import annotations

import hashlib

from milai_lab.product02_decision import (
    native_answer_evidence,
    required_role_coverage,
    sealed_answer_evidence,
    sealed_strict_wrong_complete,
)


def _event(source_ref: str, session_id: str, role: str, content: str) -> dict[str, object]:
    return {
        "payload": {
            "source_ref": source_ref,
            "speaker": role,
            "content": content,
            "source_context": {"session_id": session_id},
        }
    }


def test_native_labels_join_after_label_free_capture_plan() -> None:
    record = {
        "answer": "Cobalt Blue",
        "haystack_sessions": [
            [
                {"role": "user", "content": "My lock is cobalt blue.", "has_answer": True},
                {"role": "assistant", "content": "Noted: cobalt blue.", "has_answer": True},
                {"role": "user", "content": "Thanks."},
            ]
        ],
    }
    evidence = native_answer_evidence(
        record,
        [
            _event("source://0", "session-1", "user", "My lock is cobalt blue."),
            _event("source://1", "session-1", "assistant", "Noted: cobalt blue."),
            _event("source://2", "session-1", "user", "Thanks."),
        ],
    )

    assert [label.source_turn_ref for label in evidence.labels] == [
        "source://0",
        "source://1",
    ]
    assert [label.text for label in evidence.labels] == ["cobalt blue", "cobalt blue"]
    assert evidence.exact_span_count == 2
    assert evidence.required_role_groups == (("source://1",), ("source://0",))
    assert required_role_coverage(["source://0"], evidence.required_role_groups) == 0.5


def test_native_turn_without_verbatim_answer_does_not_invent_span() -> None:
    record = {
        "answer": "350000",
        "haystack_sessions": [
            [
                {
                    "role": "user",
                    "content": "The two amounts sum to the requested total.",
                    "has_answer": True,
                }
            ]
        ],
    }
    evidence = native_answer_evidence(
        record,
        [
            _event(
                "source://0",
                "session-1",
                "user",
                "The two amounts sum to the requested total.",
            )
        ],
    )

    assert evidence.labels[0].text is None
    assert evidence.exact_span_count == 0


def test_required_role_coverage_requires_each_nonempty_group() -> None:
    assert required_role_coverage(["a", "c"], [("a", "b"), ("c",)]) == 1.0


def test_native_abstention_case_has_an_explicit_empty_positive_label_set() -> None:
    record = {
        "question_id": "negative_abs",
        "answer": "You did not mention this information.",
        "haystack_sessions": [[{"role": "user", "content": "I have a cat."}]],
    }
    evidence = native_answer_evidence(
        record,
        [_event("source://0", "session-1", "user", "I have a cat.")],
    )

    assert evidence.labels == ()
    assert evidence.required_role_groups == ()
    assert evidence.exact_span_count == 0


def test_sealed_labels_separate_direct_answer_turns_from_required_operands() -> None:
    record = {
        "question_id": "case-1",
        "answer": "19 days",
        "haystack_session_ids": ["website", "contract"],
        "haystack_sessions": [
            [{"role": "user", "content": "I launched my website today."}],
            [{"role": "user", "content": "I signed my first contract today."}],
        ],
    }
    events = [
        _event("source://website", "runtime-1", "user", "I launched my website today."),
        _event("source://contract", "runtime-2", "user", "I signed my first contract today."),
    ]
    labels = sealed_answer_evidence(
        record,
        events,
        {
            "case_id": "case-1",
            "negative_without_answer_turn": False,
            "selections": [
                {
                    "session_ordinal": 0,
                    "source_session_id": "website",
                    "turn_ordinal": 0,
                    "requirement_role": "START_EVENT",
                    "direct_answer": False,
                    "quote": "I launched my website today.",
                    "speaker": "user",
                    "source_text_sha256": hashlib.sha256(
                        b"I launched my website today."
                    ).hexdigest(),
                },
                {
                    "session_ordinal": 1,
                    "source_session_id": "contract",
                    "turn_ordinal": 0,
                    "requirement_role": "END_EVENT",
                    "direct_answer": False,
                    "quote": "I signed my first contract today.",
                    "speaker": "user",
                    "source_text_sha256": hashlib.sha256(
                        b"I signed my first contract today."
                    ).hexdigest(),
                },
            ],
        },
    )

    assert labels.answer_labels == ()
    assert labels.required_role_groups == (
        ("source://website",),
        ("source://contract",),
    )
    assert labels.required_role_labels == ("START_EVENT", "END_EVENT")

    wrong, missing = sealed_strict_wrong_complete(
        lean_recall_mode="STRICT",
        sufficiency_status="COMPLETE",
        accepted_source_turn_refs=("source://contract",),
        evidence=labels,
    )
    assert wrong == 1
    assert missing == ("START_EVENT",)

    correct, no_missing = sealed_strict_wrong_complete(
        lean_recall_mode="STRICT",
        sufficiency_status="COMPLETE",
        accepted_source_turn_refs=("source://website", "source://contract"),
        evidence=labels,
    )
    assert correct == 0
    assert no_missing == ()

    ordinary, ordinary_missing = sealed_strict_wrong_complete(
        lean_recall_mode="ORDINARY",
        sufficiency_status="COMPLETE",
        accepted_source_turn_refs=(),
        evidence=labels,
    )
    assert ordinary == 0
    assert ordinary_missing == ("START_EVENT", "END_EVENT")
