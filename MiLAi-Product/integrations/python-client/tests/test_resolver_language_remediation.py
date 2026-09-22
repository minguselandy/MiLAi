from __future__ import annotations

import pytest

from milai_client import CanonicalStateKey, DeterministicMemoryNeedResolver
from milai_client.memory_need import MemoryNeedResolution


def _resolve(
    query: str,
    keys: tuple[CanonicalStateKey, ...],
    previous: MemoryNeedResolution | None = None,
) -> MemoryNeedResolution:
    return DeterministicMemoryNeedResolver().resolve(
        query,
        scope={"project_ids": ["typed-boundary"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        known_state_keys=keys,
        previous=previous,
    )


@pytest.mark.parametrize(
    ("subject", "predicate", "query"),
    [
        ("maple", "deploy.region", "Current maple deploy.region"),
        ("maple", "deploy.region", "Ｃｕｒｒｅｎｔ maple deploy.region"),  # noqa: RUF001
        ("地图", "部署.区域", "地图当前部署.区域是什么"),
        ("проект", "сервис.регион", "Current проект сервис.регион"),
        ("équipe", "service.région", "Current équipe service.région"),
        ("проект", "сервис.регион", "сервис.регион"),
        ("maple", "deploy.region", "Current deploy_region"),
    ],
)
def test_key_derived_matching_does_not_depend_on_diagnostic_identifiers(
    subject: str, predicate: str, query: str
) -> None:
    wanted = CanonicalStateKey(subject, predicate, "PROJECT_STATE")
    other = CanonicalStateKey(subject, "unrelated.field", "PROJECT_STATE")
    for keys in ((wanted, other), (other, wanted)):
        result = _resolve(query, keys)
        assert result.requested_route == "L0"
        assert result.state_key_ref is not None
        assert result.state_key_ref.predicate == predicate
        assert result.state_key_ref.subject == subject
        assert not any(
            (
                result.resolver_model_calls,
                result.resolver_embedding_calls,
                result.resolver_retrieval_calls,
            )
        )


def test_ambiguity_is_order_independent_and_qualified_exact_key_wins() -> None:
    north = CanonicalStateKey("north", "deploy.region", "PROJECT_STATE")
    south = CanonicalStateKey("south", "deploy.region", "PROJECT_STATE")
    for keys in ((north, south), (south, north)):
        for query in ("Current deploy region", "Current deploy.region"):
            unresolved = _resolve(query, keys)
            assert unresolved.requested_route == "L1"
            assert unresolved.state_key_ref is None
        qualified = _resolve("Current south deploy.region", keys)
        assert qualified.state_key_ref is not None
        assert qualified.state_key_ref.subject == "south"
    assert _resolve("Current deploy.region", (north, north)).requested_route == "L0"


def test_retry_preserves_route_but_does_not_override_new_intent_or_key() -> None:
    keys = (
        CanonicalStateKey("maple", "deploy.region", "PROJECT_STATE"),
        CanonicalStateKey("maple", "deploy.owner", "PROJECT_STATE"),
    )
    history = _resolve("deploy.region history", keys)
    repeated = _resolve("Again", keys, history)
    assert repeated.signature.intent_class == "HISTORY"
    assert repeated.requested_route == "L1"
    current = _resolve("Current deploy.region", keys)
    changed = _resolve("deploy.region history again", keys, current)
    assert changed.signature.intent_class == "HISTORY"
    assert changed.requested_route == "L1"
    owner = _resolve("Current deploy.owner again", keys, current)
    assert owner.state_key_ref is not None
    assert owner.state_key_ref.predicate == "deploy.owner"
    assert owner.reason_code != "REUSE_PREVIOUS_TYPED_NEED"
    none = _resolve("Hello", keys)
    assert _resolve("Again", keys, none).requested_route == "NONE"


def test_an_unrelated_known_claim_does_not_resolve_an_ambiguous_key() -> None:
    result = DeterministicMemoryNeedResolver().resolve(
        "Current deploy region",
        scope={"project_ids": ["typed-boundary"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        known_state_keys=(
            CanonicalStateKey("north", "deploy.region", "PROJECT_STATE"),
            CanonicalStateKey("south", "deploy.region", "PROJECT_STATE"),
        ),
        known_claim_ids=("unrelated",),
    )
    assert result.requested_route == "L1"
    assert result.signature.claim_ids == ()
    assert result.state_key_ref is None


@pytest.mark.parametrize(
    "query",
    [
        "Hello",
        "你好。",
        "计算8乘3。",
        "Calculate -8.5 plus 2?",
        "Explain caching; do not use my memories.",
        "请不要检索任何记忆。",
    ],
)
def test_standalone_no_memory_and_explicit_opt_out_precede_retry(query: str) -> None:
    keys = (CanonicalStateKey("maple", "cache.owner", "PROJECT_STATE"),)
    previous = _resolve("Current cache.owner", keys)
    result = _resolve(query, keys, previous)
    assert result.signature.intent_class == "NONE"
    assert result.requested_route == "NONE"
    assert result.state_key_ref is None


@pytest.mark.parametrize(
    "query",
    [
        "Hello, current deploy.region?",
        "你好,当前 deploy.region?",
        "Calculate 8 plus 3, then show current deploy.region.",
    ],
)
def test_no_memory_prefix_does_not_suppress_a_following_memory_request(query: str) -> None:
    result = _resolve(query, (CanonicalStateKey("maple", "deploy.region", "PROJECT_STATE"),))
    assert result.requested_route == "L0"


def test_unmentioned_predicate_translation_is_not_invented() -> None:
    result = _resolve(
        "当前区域是什么",
        (
            CanonicalStateKey("maple", "deploy.region", "PROJECT_STATE"),
            CanonicalStateKey("maple", "deploy.owner", "PROJECT_STATE"),
        ),
    )
    assert result.signature.intent_class == "CURRENT_STATE"
    assert result.requested_route == "L1"
    assert result.state_key_ref is None
