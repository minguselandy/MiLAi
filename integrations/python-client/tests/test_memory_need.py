from __future__ import annotations

import pytest

from milai_client import (
    CanonicalStateKey,
    CurrentStateEnvelope,
    DeterministicMemoryNeedResolver,
    DeterministicQueryOnlyIntentShadow,
    PrepareContextRequest,
    StateKeyAliasAmbiguousError,
    StateKeyRef,
)


@pytest.mark.parametrize(
    ("query", "intent", "requirement"),
    [
        ("What is the current release status?", "REQUIRED", "EXACT"),
        ("为什么之前的发布决定改变了?", "REQUIRED", "SEARCH"),
        ("Recall 当前 database setting", "REQUIRED", "EXACT"),
        ("Could this affect the release?", "POSSIBLE", "SEARCH"),
        ("What is 17 plus 25?", "NOT_NEEDED", "NONE"),
    ],
)
def test_query_only_shadow_is_task_free_and_does_not_route(
    query: str, intent: str, requirement: str
) -> None:
    result = DeterministicQueryOnlyIntentShadow().interpret(query)

    assert result.intent == intent
    assert result.requirement == requirement
    assert result.interpreter_version == "query-only-shadow-v1"


def test_explicit_read_floor_never_returns_not_needed_for_nonempty_query() -> None:
    result = DeterministicQueryOnlyIntentShadow().interpret(
        "Hello", invocation_mode="EXPLICIT_READ"
    )

    assert result.intent == "POSSIBLE"
    assert result.requirement == "SEARCH"
    assert result.reason_code == "EXPLICIT_READ_REQUIREMENT_FLOOR"


def _keys() -> tuple[CanonicalStateKey, ...]:
    return (
        CanonicalStateKey("release", "release.target", "PROJECT_STATE"),
        CanonicalStateKey("release", "release.deadline", "PROJECT_STATE"),
        CanonicalStateKey("release", "release.decision", "PROJECT_DECISION"),
    )


def _resolve(query: str, *, previous=None):  # type: ignore[no-untyped-def]
    return DeterministicMemoryNeedResolver().resolve(
        query,
        scope={"project_ids": ["release"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        known_state_keys=_keys(),
        previous=previous,
    )


def test_deterministic_need_resolver_routes_exact_history_and_none() -> None:
    exact = _resolve("What is the current release target?")
    assert exact.requested_route == "L0"
    assert exact.signature.intent_class == "CURRENT_STATE"
    assert exact.state_key_ref is not None
    assert exact.state_key_ref.predicate == "release.target"

    history = _resolve("Why did the release decision change?")
    assert history.requested_route == "L1"
    assert history.signature.intent_class == "HISTORY"

    no_memory = _resolve("What is 17 plus 25?")
    assert no_memory.requested_route == "NONE"
    assert no_memory.signature.intent_class == "NONE"

    for resolution in (exact, history, no_memory):
        assert resolution.resolver_model_calls == 0
        assert resolution.resolver_embedding_calls == 0
        assert resolution.resolver_retrieval_calls == 0


def test_retry_reuses_typed_need_and_action_prefers_decision_key() -> None:
    target = _resolve("State the current target")
    retry = _resolve("Repeat that current read again", previous=target)
    assert retry.requested_route == "L0"
    assert retry.state_key_ref is not None
    assert retry.state_key_ref.predicate == "release.target"

    action = _resolve("Under governed current state, may the release proceed?")
    assert action.requested_route == "L0"
    assert action.state_key_ref is not None
    assert action.state_key_ref.predicate == "release.decision"


def test_prepare_request_serializes_typed_need_and_state_key() -> None:
    resolution = _resolve("What is the current release target?")
    request = PrepareContextRequest(
        query="current target",
        active_goal="prepare release",
        session_id="session",
        agent_id="agent",
        profile_id="reader-lite",
        task_epoch="epoch",
        event="EXPLICIT_MEMORY_REQUEST",
        scope={"project_ids": ["release"]},
        authority="INFORMATIONAL",
        consistency="CANONICAL_REQUIRED",
        compiler_digest="a" * 64,
        router_digest="b" * 64,
        tokenizer_digest="c" * 64,
        policy_digest="d" * 64,
        requested_route="L0",
        need_signature_id=resolution.signature.need_signature_id,
        memory_need_signature=resolution.signature,
        state_key_ref=resolution.state_key_ref,
    )
    payload = request.to_api()
    assert payload["need_signature_id"] == resolution.signature.need_signature_id
    assert payload["memory_need_signature"]["intent_class"] == "CURRENT_STATE"
    assert payload["state_key_ref"]["predicate"] == "release.target"


def test_current_state_envelope_is_strict_and_compact() -> None:
    envelope = CurrentStateEnvelope.from_api(
        {
            "status": "HIT",
            "claims": [{"claim_id": "claim", "payload": {"value": "rc-8"}}],
            "open_issues": [{"issue_id": "issue", "revision": 2}],
            "canonical_position": 42,
            "slot_validation_handle": "opaque-handle",
            "trace_id": "trace",
        }
    )
    assert envelope.status == "HIT"
    assert envelope.canonical_position == 42
    assert len(envelope.claims) == 1
    with pytest.raises(ValueError, match="status"):
        CurrentStateEnvelope.from_api(
            {
                "status": "STALE",
                "claims": [],
                "open_issues": [],
                "canonical_position": 1,
            }
        )


def test_state_key_ref_rejects_invalid_position() -> None:
    with pytest.raises(ValueError, match="canonical_position_seen"):
        StateKeyRef({}, "release", "release.target", "PROJECT_STATE", canonical_position_seen=-1)


@pytest.mark.parametrize(
    ("query", "predicate"),
    [
        ("CURRENT   RELEASE　TARGET", "release.target"),
        ("当前发布目标", "release.target"),
        ("current release config", "release.database"),
        ("当前发布数据库", "release.database"),
        ("current governed release decision", "release.decision"),
        ("当前受治理的发布决定", "release.decision"),
    ],
)
def test_frozen_cn_en_exact_aliases_precede_broader_need_rules(query: str, predicate: str) -> None:
    keys = (
        CanonicalStateKey("orchid-release", "release.target", "PROJECT_STATE"),
        CanonicalStateKey("orchid-release", "release.database", "PROJECT_CONFIG"),
        CanonicalStateKey("orchid-release", "release.decision", "PROJECT_DECISION"),
    )
    result = DeterministicMemoryNeedResolver().resolve(
        query,
        scope={"project_ids": ["orchid-release"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        known_state_keys=keys,
    )
    assert result.requested_route == "L0"
    assert result.reason_code == "EXACT_FROZEN_STATE_KEY_ALIAS"
    assert result.state_key_ref is not None
    assert result.state_key_ref.predicate == predicate
    assert result.resolver_model_calls == 0
    assert result.resolver_embedding_calls == 0
    assert result.resolver_retrieval_calls == 0


@pytest.mark.parametrize(
    ("query", "predicate"),
    [
        ("orchid-release 的当前发布目标是什么?", "release.target"),
        ("orchid-release 的当前发布数据库是什么?", "release.database"),
        ("orchid-release 的当前受治理的发布决定是什么?", "release.decision"),
    ],
)
def test_frozen_cn_aliases_resolve_inside_full_questions(query: str, predicate: str) -> None:
    keys = (
        CanonicalStateKey("orchid-release", "release.target", "PROJECT_STATE"),
        CanonicalStateKey("orchid-release", "release.database", "PROJECT_CONFIG"),
        CanonicalStateKey("orchid-release", "release.decision", "PROJECT_DECISION"),
    )

    result = DeterministicMemoryNeedResolver().resolve(
        query,
        scope={"project_ids": ["orchid-release"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        known_state_keys=keys,
    )

    assert result.requested_route == "L0"
    assert result.reason_code == "EXACT_FROZEN_STATE_KEY_ALIAS"
    assert result.state_key_ref is not None
    assert result.state_key_ref.predicate == predicate


def test_cn_non_memory_question_does_not_match_frozen_aliases() -> None:
    result = DeterministicMemoryNeedResolver().resolve(
        "请只计算 17 + 25, 不要读取任何记忆。",
        scope={"project_ids": ["orchid-release"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        known_state_keys=(CanonicalStateKey("orchid-release", "release.target", "PROJECT_STATE"),),
    )

    assert result.requested_route == "NONE"
    assert result.state_key_ref is None


def test_normalized_alias_collision_is_typed_and_never_tie_broken_or_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_client import memory_need

    monkeypatch.setattr(
        memory_need,
        "_STATE_KEY_ALIAS_FAMILIES",
        (
            ("orchid-release", "release.target", "PROJECT_STATE", ("same alias",)),
            (
                "orchid-release",
                "release.database",
                "PROJECT_CONFIG",
                ("\uff33\uff21\uff2d\uff25 alias",),
            ),
        ),
    )
    keys = (
        CanonicalStateKey("orchid-release", "release.target", "PROJECT_STATE"),
        CanonicalStateKey("orchid-release", "release.database", "PROJECT_CONFIG"),
    )
    with pytest.raises(StateKeyAliasAmbiguousError, match="STATE_KEY_ALIAS_AMBIGUOUS"):
        DeterministicMemoryNeedResolver().resolve(
            "same alias",
            scope={"project_ids": ["orchid-release"]},
            required_authority="INFORMATIONAL",
            consistency_floor="CANONICAL_REQUIRED",
            known_state_keys=keys,
        )
