from __future__ import annotations

from datetime import UTC, datetime

import pytest

from milai.application.acquisition import (
    ADDITIVE_UNION_V2_POLICY,
    QUERY_PRESERVING_UNION_CANDIDATE_CAP,
    QUERY_PRESERVING_UNION_DIRECT_CAP,
    QUERY_PRESERVING_UNION_HYDRATE_CAP,
    QUERY_PRESERVING_UNION_POLICY,
    apply_probe_source_policy,
    compile_acquisition_plan,
    fuse_acquisition_probe_results,
)
from milai.application.query_planner import QueryPlanner
from milai.domain import (
    EvidenceSourcePolicyV02,
    RequirementSemanticRolesV02,
    RetrievalRequest,
)
from milai.domain.semantic_query import LexicalCueSetV01


def _plan(query: str):  # type: ignore[no-untyped-def]
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            requested_scope={"project_ids": ["milai"]},
        )
    )


def _candidate(
    evidence_id: str,
    source_ref: str,
    content: str,
    score: float,
    *,
    speaker: str | None = None,
    speaker_source: str | None = None,
) -> dict[str, object]:
    candidate: dict[str, object] = {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": evidence_id,
        "source_ref": source_ref,
        "subject_id": source_ref.split("/")[2],
        "observed_at": "2026-08-27T00:00:00+00:00",
        "content": content,
        "relevance_score": score,
    }
    if speaker is not None:
        candidate["speaker"] = speaker
    if speaker_source is not None:
        candidate["speaker_source"] = speaker_source
    return candidate


def _with_per_slot_source_semantics(plan):  # type: ignore[no-untyped-def]
    query_ir = plan.memory_query_ir
    assert query_ir is not None
    requirements = []
    for requirement in query_ir.requirements:
        preferred = "ASSISTANT" if requirement.slot_id == "TOTAL_PRICE" else "USER"
        actor = "USER" if requirement.slot_id == "TOTAL_PRICE" else "MERCHANT"
        requirements.append(
            requirement.model_copy(
                update={
                    "semantic_roles": RequirementSemanticRolesV02(actor=actor),
                    "evidence_source": EvidenceSourcePolicyV02(
                        preferred_speakers=[preferred],
                        provenance="SEMANTIC_PARSER",
                    ),
                }
            )
        )
    return plan.model_copy(
        update={"memory_query_ir": query_ir.model_copy(update={"requirements": requirements})}
    )


def test_a2_compiles_global_and_every_required_slot_to_explicit_raw_fts_probe() -> None:
    plan = _plan("How much did I pay per ceramic planter?")

    acquisition = compile_acquisition_plan(
        plan,
        query="How much did I pay per ceramic planter?",
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=30,
        context_tokens=2048,
    )

    assert acquisition.schema_version == "acquisition-plan-v0.1"
    assert acquisition.residual_policy.allowed is False
    assert acquisition.probes[0].requirement_slot is None
    assert {probe.requirement_slot for probe in acquisition.probes[1:]} == {
        "TOTAL_PRICE",
        "ITEM_COUNT",
    }
    assert set(acquisition.fusion.per_slot_quota) == {"TOTAL_PRICE", "ITEM_COUNT"}
    assert all(probe.channel == "FTS_RAW" for probe in acquisition.probes)
    assert acquisition.probes[0].evidence_source_policy.provenance == "NONE"
    assert acquisition.probes[0].evidence_source_policy.preferred_speakers == []
    assert all(
        probe.evidence_source_policy.provenance == "NONE" for probe in acquisition.probes[1:]
    )
    assert all(probe.expansion_policy == "NONE" for probe in acquisition.probes)
    assert acquisition.fusion.global_cap == 30


def test_raw_fts_uses_retrieval_hints_without_promoting_them_to_entities() -> None:
    plan = _plan("Which access code did the assistant share earlier?")
    query_ir = plan.memory_query_ir
    assert query_ir is not None
    requirement = query_ir.requirements[0].model_copy(
        update={"entity_constraints": ["access-code-subject"]}
    )
    query_ir = query_ir.model_copy(
        update={
            "requirements": [requirement],
            "lexical_cues": [
                LexicalCueSetV01(
                    requirement_slot=requirement.slot_id,
                    surface_terms=["assistant", "shared", "access", "code"],
                    provenance=["QUERY_TASK_CONTRACT_V01"],
                )
            ],
        }
    )
    plan = plan.model_copy(update={"memory_query_ir": query_ir})

    acquisition = compile_acquisition_plan(
        plan,
        query="Which access code did the assistant share earlier?",
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )

    slot_probe = next(
        probe for probe in acquisition.probes if probe.requirement_slot is not None
    )
    assert slot_probe.lexical_terms == ["assistant", "shared", "access", "code"]
    assert slot_probe.entities == ["access-code-subject"]


def test_a2_locality_reserve_gives_each_required_role_a_direct_candidate_first() -> None:
    query = "How much did I pay per ceramic planter?"
    plan = _plan(query)
    acquisition = compile_acquisition_plan(
        plan,
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=6,
        context_tokens=512,
        enable_same_session_expansion=True,
    )
    assert all(probe.expansion_policy == "SAME_SESSION" for probe in acquisition.probes)
    slots = sorted(acquisition.fusion.per_slot_quota)
    first_role = [
        _candidate("role-a-1", "memory://session-a/turn-1", "$60 total", 0.9),
        _candidate("role-a-2", "memory://session-a/turn-2", "$54 total", 0.8),
    ]
    second_role = [_candidate("role-b-1", "memory://session-b/turn-1", "six planters", 0.7)]
    probe_results = []
    for probe in acquisition.probes:
        items = (
            first_role
            if probe.requirement_slot == slots[0]
            else second_role
            if probe.requirement_slot == slots[1]
            else []
        )
        probe_results.append((probe, items))

    fused = fuse_acquisition_probe_results(acquisition, probe_results)

    assert [item["evidence_id"] for item in fused] == ["role-a-1", "role-b-1"]
    assert {slot for item in fused for slot in item["acquisition_candidate"]["matched_slots"]} == {
        *slots
    }


def test_a5_acquisition_keeps_source_and_event_temporal_ranges_separate() -> None:
    reference = datetime(2023, 3, 27, 12, tzinfo=UTC)
    source_query = "I mentioned cooking something for my friend a couple of days ago. What was it?"
    source_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=source_query,
            as_of=reference,
            system_as_of=reference,
        )
    )
    source_acquisition = compile_acquisition_plan(
        source_plan,
        query=source_query,
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    assert source_acquisition.global_constraints.source_observed_range is not None
    assert source_acquisition.global_constraints.event_occurrence_range is None
    assert {
        probe.temporal_axis
        for probe in source_acquisition.probes
        if probe.requirement_slot is not None
    } == {"SOURCE_OBSERVED_TIME"}

    event_query = "How many times did I bake something in the past two weeks?"
    event_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=event_query,
            as_of=reference,
            system_as_of=reference,
        )
    )
    event_acquisition = compile_acquisition_plan(
        event_plan,
        query=event_query,
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    assert event_acquisition.global_constraints.source_observed_range is None
    assert event_acquisition.global_constraints.event_occurrence_range is not None
    assert {
        probe.temporal_axis
        for probe in event_acquisition.probes
        if probe.requirement_slot is not None
    } == {"EVENT_OCCURRENCE_TIME"}


def test_a6_dense_is_an_independent_full_turn_channel_with_stable_fts_budget() -> None:
    query = "Which device was associated with the cobalt workshop?"
    plan = _plan(query)
    baseline = compile_acquisition_plan(
        plan,
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    dense = compile_acquisition_plan(
        plan,
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
        enable_dense=True,
    )

    baseline_fts_limits = {probe.probe_id: probe.candidate_limit for probe in baseline.probes}
    dense_fts_limits = {
        probe.probe_id: probe.candidate_limit
        for probe in dense.probes
        if probe.channel != "EVIDENCE_DENSE"
    }
    assert dense_fts_limits == baseline_fts_limits
    dense_probes = [probe for probe in dense.probes if probe.channel == "EVIDENCE_DENSE"]
    assert len(dense_probes) == 2
    assert dense_probes[0].probe_id == "global:evidence-dense"
    assert dense_probes[0].dense_query_text == query
    assert all(probe.lexical_terms == [] and probe.phrases == [] for probe in dense_probes)
    assert dense.fusion.policy_identity == "RRF_K60_PER_SLOT_FTS_PLUS_EVIDENCE_DENSE_V1"

    dense_candidate = _candidate(
        "dense-only",
        "memory://dense/turn-0",
        "A lossless full Evidence turn.",
        0.91,
        speaker="tool",
        speaker_source="STRUCTURED_TURN_METADATA",
    )
    probe_results = [
        (probe, [dense_candidate] if probe.channel == "EVIDENCE_DENSE" else [])
        for probe in dense.probes
    ]
    fused = fuse_acquisition_probe_results(dense, probe_results)
    envelope = fused[0]["acquisition_candidate"]
    assert envelope["channel_ranks"] == {"EVIDENCE_DENSE": 1}
    assert envelope["matched_fields"] == ["evidence_dense_embedding"]
    assert fused[0]["content"] == "A lossless full Evidence turn."


def test_product07_query_preserving_union_is_independent_of_query_ir_slots() -> None:
    query = "How much more did I spend in Hawaii compared with Tokyo?"
    acquisition = compile_acquisition_plan(
        _plan(query),
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=120,
        context_tokens=16_384,
        enable_dense=True,
        enable_same_session_expansion=True,
        query_preserving_union=True,
    )

    assert acquisition.fusion.policy_identity == QUERY_PRESERVING_UNION_POLICY
    assert acquisition.fusion.global_cap == QUERY_PRESERVING_UNION_CANDIDATE_CAP
    assert acquisition.budget.hydrate_count == QUERY_PRESERVING_UNION_HYDRATE_CAP
    assert acquisition.fusion.per_slot_quota == {}
    assert [probe.channel for probe in acquisition.probes] == [
        "FTS_RAW",
        "EVIDENCE_DENSE",
    ]
    assert all(probe.requirement_slot is None for probe in acquisition.probes)
    assert (
        next(
            probe for probe in acquisition.probes if probe.channel == "FTS_RAW"
        ).candidate_limit
        == QUERY_PRESERVING_UNION_DIRECT_CAP
    )
    assert (
        next(
            probe for probe in acquisition.probes if probe.channel == "EVIDENCE_DENSE"
        ).candidate_limit
        == 30
    )
    assert acquisition.probes[1].dense_query_text == query
    assert all(probe.expansion_policy == "SAME_SESSION" for probe in acquisition.probes)


def test_product07_union_orders_one_real_session_before_same_session_depth() -> None:
    query = "What did I spend per night?"
    acquisition = compile_acquisition_plan(
        _plan(query),
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=120,
        context_tokens=16_384,
        enable_same_session_expansion=True,
        query_preserving_union=True,
    )
    probe = acquisition.probes[0]
    candidates = [
        _candidate("a-1", "memory://session-a/turn-1", "night cost", 1.0),
        _candidate("a-2", "memory://session-a/turn-2", "night cost", 0.9),
        _candidate("b-1", "memory://session-b/turn-1", "night cost", 0.8),
        _candidate("c-1", "memory://session-c/turn-1", "night cost", 0.7),
    ]

    fused = fuse_acquisition_probe_results(acquisition, [(probe, candidates)])

    assert [item["evidence_id"] for item in fused] == ["a-1", "b-1", "c-1", "a-2"]


def test_product08_additive_union_preserves_global_fts_and_adds_soft_slots() -> None:
    query = "How much did I pay per ceramic planter?"
    acquisition = compile_acquisition_plan(
        _plan(query),
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=120,
        context_tokens=16_384,
        enable_dense=True,
        enable_same_session_expansion=True,
        additive_union_v0_2=True,
    )

    assert acquisition.fusion.policy_identity == ADDITIVE_UNION_V2_POLICY
    assert set(acquisition.fusion.per_slot_quota.values()) == {1}
    assert acquisition.probes[0].probe_id == "global:fts-raw"
    assert acquisition.probes[1].probe_id == "global:evidence-dense"
    assert {
        probe.requirement_slot
        for probe in acquisition.probes
        if probe.requirement_slot is not None
    } == {"TOTAL_PRICE", "ITEM_COUNT"}
    assert {
        probe.channel for probe in acquisition.probes
    } == {"FTS_RAW", "EVIDENCE_DENSE"}
    assert all(
        probe.candidate_limit == QUERY_PRESERVING_UNION_DIRECT_CAP
        for probe in acquisition.probes
        if probe.channel == "FTS_RAW"
    )
    assert next(
        probe for probe in acquisition.probes if probe.probe_id == "global:evidence-dense"
    ).candidate_limit == 30

    global_items = [
        _candidate(
            f"global-{index:02d}",
            f"memory://global-{index:02d}/turn-0",
            "ceramic planter purchase",
            1.0 - index / 100,
        )
        for index in range(30)
    ]
    slot_items = {
        "TOTAL_PRICE": [
            _candidate("slot-price", "memory://price/turn-0", "$60 total", 0.9)
        ],
        "ITEM_COUNT": [
            _candidate("slot-count", "memory://count/turn-0", "six planters", 0.9)
        ],
    }
    dense_items = [
        _candidate(
            "dense-only" if index == 0 else f"dense-{index:02d}",
            f"memory://dense-{index:02d}/turn-0",
            "The complete purchase appeared in another wording.",
            0.99 - index / 100,
        )
        for index in range(12)
    ]
    probe_results = []
    for probe in acquisition.probes:
        if probe.probe_id == "global:fts-raw":
            items = global_items
        elif probe.probe_id == "global:evidence-dense":
            items = dense_items
        elif probe.channel == "FTS_RAW":
            items = slot_items[str(probe.requirement_slot)]
        else:
            items = []
        probe_results.append((probe, items))

    fused = fuse_acquisition_probe_results(acquisition, probe_results)
    fused_ids = [str(item["evidence_id"]) for item in fused]

    assert fused_ids[:20] == [f"global-{index:02d}" for index in range(20)]
    assert {"slot-price", "slot-count", "dense-only"}.issubset(fused_ids)
    assert len(fused_ids) == QUERY_PRESERVING_UNION_DIRECT_CAP


def test_product08_additive_union_and_product07_union_are_exclusive() -> None:
    query = "What color is my bicycle lock?"

    with pytest.raises(ValueError, match="mutually exclusive"):
        compile_acquisition_plan(
            _plan(query),
            query=query,
            principal_scope={},
            authority_floor="INFORMATIONAL",
            candidate_limit=40,
            context_tokens=512,
            query_preserving_union=True,
            additive_union_v0_2=True,
        )


def test_a2_fusion_preserves_probe_slot_channel_rank_and_stable_identity() -> None:
    plan = _plan("How much did I pay per ceramic planter?")
    acquisition = compile_acquisition_plan(
        plan,
        query="How much did I pay per ceramic planter?",
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=6,
        context_tokens=2048,
    )
    global_probe, total_probe, count_probe = acquisition.probes
    shared = _candidate(
        "evidence-shared",
        "memory://session-a/turn-0",
        "user: I paid $60 for six ceramic planters",
        0.8,
        speaker="user",
        speaker_source="STRUCTURED_TURN_METADATA",
    )
    price_only = _candidate(
        "evidence-price",
        "memory://session-b/turn-0",
        "user: the ceramic planter order cost $60",
        0.7,
    )
    count_only = _candidate(
        "evidence-count",
        "memory://session-c/turn-0",
        "user: I bought six ceramic planters",
        0.75,
    )

    fused = fuse_acquisition_probe_results(
        acquisition,
        [
            (global_probe, [shared]),
            (total_probe, [price_only, shared]),
            (count_probe, [count_only, shared]),
        ],
    )
    by_id = {str(item["evidence_id"]): item for item in fused}
    envelope = by_id["evidence-shared"]["acquisition_candidate"]

    assert envelope["schema_version"] == "candidate-envelope-v0.2"
    assert envelope["source_turn_ref"] == "memory://session-a/turn-0"
    assert envelope["matched_slots"] == ["ITEM_COUNT", "TOTAL_PRICE"]
    assert envelope["matched_probes"] == sorted(
        [global_probe.probe_id, total_probe.probe_id, count_probe.probe_id]
    )
    assert envelope["channel_ranks"] == {"FTS_RAW": 1}
    assert envelope["probe_ranks"] == {
        global_probe.probe_id: 1,
        total_probe.probe_id: 2,
        count_probe.probe_id: 2,
    }
    assert envelope["fusion_rank"] == 1
    assert envelope["speaker"] == "user"
    assert envelope["speaker_source"] == "STRUCTURED_TURN_METADATA"
    assert envelope["body_hydrated"] is True
    assert len(fused) == 3


def test_a2_fusion_preserves_one_candidate_opportunity_per_direct_channel() -> None:
    query = "What color is my bicycle lock?"
    acquisition = compile_acquisition_plan(
        _plan(query),
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=4,
        context_tokens=512,
        enable_dense=True,
    )
    raw = [
        _candidate(
            f"raw-{index}",
            f"memory://raw/turn-{index}",
            f"raw candidate {index}",
            1.0 - index / 10,
        )
        for index in range(4)
    ]
    dense = _candidate(
        "dense-only",
        "memory://dense/turn-0",
        "A full turn reached only through dense retrieval.",
        0.01,
    )
    fused = fuse_acquisition_probe_results(
        acquisition,
        [
            (
                probe,
                [dense] if probe.channel == "EVIDENCE_DENSE" else raw,
            )
            for probe in acquisition.probes
        ],
    )

    assert len(fused) == acquisition.fusion.global_cap
    channels = {
        channel
        for item in fused
        for channel in item["acquisition_candidate"]["channel_ranks"]
    }
    assert {"FTS_RAW", "EVIDENCE_DENSE"}.issubset(channels)


def test_a2_fusion_applies_slot_quota_before_global_fill() -> None:
    plan = _plan("How much did I pay per ceramic planter?")
    acquisition = compile_acquisition_plan(
        plan,
        query="How much did I pay per ceramic planter?",
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=3,
        context_tokens=512,
    )
    global_probe, total_probe, count_probe = acquisition.probes
    global_only = _candidate("global", "memory://session-g/turn-0", "user: ceramic planter", 1.0)
    price = _candidate("price", "memory://session-p/turn-0", "user: paid $60", 0.1)
    count = _candidate("count", "memory://session-c/turn-0", "user: bought six", 0.1)

    fused = fuse_acquisition_probe_results(
        acquisition,
        [
            (global_probe, [global_only]),
            (total_probe, [price]),
            (count_probe, [count]),
        ],
    )

    assert {item["evidence_id"] for item in fused} == {"global", "price", "count"}
    assert fused[0]["evidence_id"] == "count" or fused[0]["evidence_id"] == "price"


def test_a3_compiler_copies_per_slot_semantics_without_query_global_role() -> None:
    plan = _with_per_slot_source_semantics(_plan("How much did I pay per ceramic planter?"))
    acquisition = compile_acquisition_plan(
        plan,
        query="How much did I pay per ceramic planter?",
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=9,
        context_tokens=2048,
    )

    probes = {probe.requirement_slot: probe for probe in acquisition.probes}
    assert probes[None].evidence_source_policy.preferred_speakers == []
    assert probes["TOTAL_PRICE"].semantic_subject.actor == "USER"
    assert probes["TOTAL_PRICE"].evidence_source_policy.preferred_speakers == ["ASSISTANT"]
    assert probes["ITEM_COUNT"].semantic_subject.actor == "MERCHANT"
    assert probes["ITEM_COUNT"].evidence_source_policy.preferred_speakers == ["USER"]


def test_a3_body_prefix_never_creates_structured_speaker() -> None:
    acquisition = compile_acquisition_plan(
        _plan("What happened at the project meeting?"),
        query="What happened at the project meeting?",
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=4,
        context_tokens=512,
    )
    global_probe = acquisition.probes[0]
    prefixed_only = _candidate(
        "prefixed",
        "memory://session-a/turn-0",
        "assistant: the meeting moved to Tuesday",
        0.9,
    )

    fused = fuse_acquisition_probe_results(
        acquisition,
        [(global_probe, [prefixed_only]), *[(probe, []) for probe in acquisition.probes[1:]]],
    )

    envelope = fused[0]["acquisition_candidate"]
    assert envelope["speaker"] == "unknown"
    assert envelope["speaker_source"] == "UNKNOWN"
    assert "speaker" not in envelope["matched_fields"]


def test_a3_explicit_allowed_speaker_filters_only_structured_metadata() -> None:
    plan = _with_per_slot_source_semantics(_plan("How much did I pay per ceramic planter?"))
    query_ir = plan.memory_query_ir
    assert query_ir is not None
    requirements = [
        requirement.model_copy(
            update={
                "evidence_source": EvidenceSourcePolicyV02(
                    preferred_speakers=["ASSISTANT"],
                    allowed_speakers=["ASSISTANT"],
                    provenance="EXPLICIT_QUERY",
                )
            }
        )
        if requirement.slot_id == "TOTAL_PRICE"
        else requirement
        for requirement in query_ir.requirements
    ]
    plan = plan.model_copy(
        update={"memory_query_ir": query_ir.model_copy(update={"requirements": requirements})}
    )
    acquisition = compile_acquisition_plan(
        plan,
        query="How much did I pay per ceramic planter?",
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=9,
        context_tokens=512,
    )
    price_probe = next(
        probe for probe in acquisition.probes if probe.requirement_slot == "TOTAL_PRICE"
    )
    candidates = [
        _candidate(
            "assistant",
            "memory://s/turn-0",
            "unprefixed structured source",
            0.5,
            speaker="assistant",
            speaker_source="STRUCTURED_TURN_METADATA",
        ),
        _candidate("body-prefix", "memory://s/turn-1", "assistant: guessed", 1.0),
        _candidate(
            "user",
            "memory://s/turn-2",
            "structured user source",
            1.0,
            speaker="user",
            speaker_source="STRUCTURED_TURN_METADATA",
        ),
    ]

    filtered = apply_probe_source_policy(price_probe, candidates)

    assert [item["evidence_id"] for item in filtered] == ["assistant"]


@pytest.mark.parametrize(
    "query",
    [
        'Who wrote, "you recommended tea"?',
        "They mentioned it after that; what was recommended?",
        "What did I buy, and what did you later suggest?",
        "你没有说这是我推荐的吗?",
        "你说 I recommended 哪一种茶?",
    ],
)
def test_a3_query_surface_never_reconstructs_source_speaker_in_acquisition(
    query: str,
) -> None:
    acquisition = compile_acquisition_plan(
        _plan(query),
        query=query,
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )

    assert all(
        probe.evidence_source_policy.preferred_speakers == []
        and probe.evidence_source_policy.allowed_speakers is None
        and probe.evidence_source_policy.provenance == "NONE"
        for probe in acquisition.probes
    )


def test_semantic_assistant_attribution_is_a_soft_source_preference() -> None:
    query = "Didn't you say that I recommended tea?"
    acquisition = compile_acquisition_plan(
        _plan(query),
        query=query,
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )

    slot_probes = [probe for probe in acquisition.probes if probe.requirement_slot]
    assert slot_probes
    assert all(
        probe.evidence_source_policy.preferred_speakers == ["ASSISTANT"]
        and probe.evidence_source_policy.allowed_speakers is None
        and probe.evidence_source_policy.provenance == "SEMANTIC_PARSER"
        for probe in slot_probes
    )
    # A semantic preference changes ranking only; it never becomes an
    # admission restriction or rewrites the user participant in the fact.
    assert all(
        probe.evidence_source_policy.allowed_speakers is None
        for probe in acquisition.probes
    )
