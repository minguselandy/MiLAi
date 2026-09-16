from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from milai.adapters import RerankerExecution, RerankerUnavailable
from milai.application.evidence_acquisition import AcquisitionProbeDisposition
from milai.application.memory_access import MemoryAccessPlan
from milai.application.query_planner import QueryPlanner
from milai.application.retrieval import (
    RetrievalService,
    _assemble_results,
    _candidate_pool_floor,
    _latency_spans,
    _merge_candidates,
    _mmr_select,
    _public_acquisition_probe_disposition,
    _public_temporal_acquisition_trace,
    _relative_point_cover,
    _retrieval_policy,
    _state_count_cover,
    _weighted_set_cover_select,
)
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import DatabaseStatementTimeout, SessionContext
from milai.persistence.retrieval_repository import (
    GatedBatch,
    ProjectionState,
    RetrievalCandidate,
)


def test_access_trace_reports_formation_stage_latencies() -> None:
    spans = _latency_spans(
        {
            "durations_ms": {
                "query_total_ms": 12.5,
                "formation_selection_ms": 1.25,
                "formation_hydration_ms": 2.5,
            }
        }
    )

    assert spans["formation_selection_ms"] == 1.25
    assert spans["formation_hydration_ms"] == 2.5


def test_trace_read_redacts_query_material_from_legacy_rows() -> None:
    class _LegacyTraceRepository:
        def get_trace(
            self,
            _context: SessionContext,
            _trace_id: UUID,
        ) -> dict[str, Any]:
            return {
                "request_id": "legacy-trace",
                "canonical_snapshot_outbox_sequence": 3,
                "query_plan": {
                    "planner_version": "legacy-plan",
                    "intent": "HYBRID_SEARCH",
                    "entities": [],
                    "time_constraint": {},
                    "scope_predicate": {},
                    "required_authority": "INFORMATIONAL",
                    "required_lifecycle": "ACTIVE",
                    "accepted_epistemic_statuses": ["VERIFIED"],
                    "required_freshness": "CURRENT",
                    "minimum_confidence": 0.0,
                    "require_user_confirmation": False,
                    "complexity": "L1",
                    "consistency_mode": "EVENTUAL",
                    "minimum_outbox_sequence": None,
                    "context_budget": 8_000,
                    "routes": ["L1"],
                    "operator": None,
                    "memory_query_ir": {
                        "surface_terms": ["private-legacy-query"]
                    },
                    "future_query_analysis": {
                        "surface_terms": ["private-future-query"]
                    },
                },
                "execution_trace": {
                    "attempted_stages": ["FTS", "CANONICAL_GATE"],
                    "terminal_stage": "FTS",
                },
                "stage_metrics": {"durations_ms": {}, "counts": {}},
            }

    service = RetrievalService(_LegacyTraceRepository())  # type: ignore[arg-type]

    trace = service.get_trace(
        SessionContext(UUID(int=500), UUID(int=501)),
        UUID(int=999),
    )

    assert trace is not None
    encoded = str(trace["query_plan"])
    assert "private-legacy-query" not in encoded
    assert "private-future-query" not in encoded
    assert trace["query_plan"]["planner_version"] == "legacy-plan"
    assert trace["access_trace"]["canonical_position"] == 3


def test_weighted_rrf_rewards_cross_lane_evidence_and_is_deterministic() -> None:
    first = UUID("11111111-1111-4111-8111-111111111111")
    fused = UUID("22222222-2222-4222-8222-222222222222")
    vector_only = UUID("33333333-3333-4333-8333-333333333333")
    groups = [
        [
            RetrievalCandidate(first, 1000.0, "fts"),
            RetrievalCandidate(fused, 0.01, "fts"),
        ],
        [
            RetrievalCandidate(fused, 0.0001, "vector"),
            RetrievalCandidate(vector_only, 1000.0, "vector"),
        ],
    ]
    ranked, matched = _merge_candidates(groups, 3)
    assert [candidate.claim_version_id for candidate in ranked] == [fused, first, vector_only]
    assert matched[fused] == ["fts", "vector"]
    repeated, repeated_matched = _merge_candidates(groups, 3)
    assert repeated == ranked
    assert repeated_matched == matched


def test_rrf_limit_is_applied_after_cross_lane_deduplication() -> None:
    value = UUID("11111111-1111-4111-8111-111111111111")
    other = UUID("22222222-2222-4222-8222-222222222222")
    ranked, matched = _merge_candidates(
        [
            [RetrievalCandidate(value, 1.0, "fts")],
            [
                RetrievalCandidate(value, 1.0, "vector"),
                RetrievalCandidate(other, 0.9, "vector"),
            ],
        ],
        1,
    )
    assert [candidate.claim_version_id for candidate in ranked] == [value]
    assert matched[value] == ["fts", "vector"]


def test_retrieval_policy_only_enables_recent_for_temporal_update_intent() -> None:
    plain_weights, plain_recent, plain_multi = _retrieval_policy("Which shoes do I prefer?")
    recent_weights, recent_enabled, recent_multi = _retrieval_policy(
        "How many new postcards have I added since I started again?"
    )

    assert plain_weights["vector"] == 1.0
    assert plain_recent is False
    assert plain_multi is False
    assert recent_weights["vector"] == 0.4
    assert recent_enabled is True
    assert recent_multi is True


def test_retrieval_policy_enables_recent_for_implicit_state_count() -> None:
    _weights, recent_enabled, multi = _retrieval_policy(
        "How many of Emma's recipes have I tried out?"
    )

    assert recent_enabled is True
    assert multi is True


def test_state_count_cover_keeps_newer_strong_update_over_old_reranker_winner() -> None:
    candidates = [
        {
            "claim_version_id": "old",
            "valid_time_from": "2023-05-29T04:51:00+00:00",
            "payload": {"memory_text": "user: I've tried out two of Emma's recipes."},
        },
        {
            "claim_version_id": "distractor",
            "valid_time_from": "2023-06-01T00:00:00+00:00",
            "payload": {"memory_text": "assistant: 1.\nuser: I like recipes."},
        },
        {
            "claim_version_id": "new",
            "valid_time_from": "2023-05-30T06:32:00+00:00",
            "payload": {"memory_text": "user: So far I have tried 3 recipes from Emma."},
        },
    ]

    selected = _state_count_cover(candidates, "How many of Emma's recipes have I tried out?", 2)

    assert [item["claim_version_id"] for item in selected] == ["new", "old"]


def test_typed_temporal_plan_expands_only_the_internal_candidate_pool() -> None:
    planner = QueryPlanner()
    temporal = planner.plan(
        RetrievalRequest(
            route="L1",
            query="Which espresso machine did I get 10 days ago?",
        )
    )
    ordinary = planner.plan(RetrievalRequest(route="L1", query="Which shoes do I prefer?"))

    assert _candidate_pool_floor(temporal, False) == 30
    assert _candidate_pool_floor(ordinary, False) == 12
    assert _candidate_pool_floor(ordinary, True) == 30


def test_progressive_trace_preserves_typed_temporal_unavailable_compatibility() -> None:
    event = AcquisitionProbeDisposition(
        probe_id="planned:event-range",
        channel="TEMPORAL_EVENT",
        status="UNAVAILABLE",
        reason_code="EVENT_PROJECTION_NOT_READY",
        raw_candidate_count=0,
        selected_candidate_count=0,
        latency_ms=0,
    )
    dense = AcquisitionProbeDisposition(
        probe_id="dense:target",
        requirement_id="TARGET_EVENT",
        channel="EVIDENCE_DENSE",
        status="UNAVAILABLE",
        reason_code="EVENT_TIME_FILTER_UNAVAILABLE",
        raw_candidate_count=0,
        selected_candidate_count=0,
        latency_ms=0,
    )

    assert _public_temporal_acquisition_trace("EVENT_OCCURRENCE_TIME", event) == {
        "query_axis": "EVENT_OCCURRENCE_TIME",
        "scan_axis": "CANDIDATE_SET",
        "disposition": "EVENT_PROJECTION_UNAVAILABLE",
    }
    dense_trace = _public_acquisition_probe_disposition(dense)
    assert dense_trace["status"] == "EVENT_TIME_FILTER_UNAVAILABLE"
    assert dense_trace["candidate_count"] == 0


def test_relative_point_cover_matches_acquisition_intent_at_target_date() -> None:
    candidates = [
        {
            "claim_version_id": "place",
            "valid_time_from": "2023-03-15T07:41:00+00:00",
            "payload": {"memory_text": "Today, Haight-Ashbury has a bohemian vibe."},
        },
        {
            "claim_version_id": "espresso-machine",
            "valid_time_from": "2023-03-15T11:56:00+00:00",
            "payload": {"memory_text": "Today I got an espresso machine."},
        },
        {
            "claim_version_id": "lamp",
            "valid_time_from": "2023-03-07T16:21:00+00:00",
            "payload": {"memory_text": "I ordered modern lamps about a week ago."},
        },
    ]

    selected = _relative_point_cover(
        candidates,
        datetime.fromisoformat("2023-03-15T18:26:00+00:00"),
        2,
        query="Which espresso machine did I get 10 days ago?",
    )

    assert selected[0]["claim_version_id"] == "espresso-machine"


def test_weighted_set_cover_prefers_query_evidence_and_quantity_spans() -> None:
    candidates = [
        {
            "claim_version_id": "generic",
            "relevance_score": 1.0,
            "payload": {"memory_text": "I visited a bicycle shop and looked around."},
        },
        {
            "claim_version_id": "first-service",
            "relevance_score": 0.9,
            "payload": {"memory_text": "In March I serviced one road bike."},
        },
        {
            "claim_version_id": "second-service",
            "relevance_score": 0.85,
            "payload": {"memory_text": "I planned to service 1 mountain bike in March."},
        },
        {
            "claim_version_id": "noise",
            "relevance_score": 0.8,
            "payload": {"memory_text": "Unrelated production deployment notes."},
        },
    ]

    selected = _weighted_set_cover_select(
        candidates,
        3,
        query="How many bikes did I service or plan to service in March?",
    )

    selected_ids = [item["claim_version_id"] for item in selected]
    assert set(selected_ids[:2]) == {"first-service", "second-service"}
    assert len(selected_ids) == len(set(selected_ids)) == 3
    assert _weighted_set_cover_select(candidates, 3, query="How many bikes in March?") == (
        _weighted_set_cover_select(candidates, 3, query="How many bikes in March?")
    )


def test_small_candidate_rrf_prefers_two_strong_lexical_ranks_over_noisy_vector() -> None:
    relevant = UUID(int=1)
    noisy = UUID(int=2)

    def lane(source: str, first: UUID, second: UUID, first_rank: int, second_rank: int):
        values = [
            RetrievalCandidate(UUID(int=1000 + offset + index), 0.0, source)
            for index in range(30)
            for offset in (0 if source == "fts" else 100 if source == "vector" else 200,)
        ]
        values[first_rank] = RetrievalCandidate(first, 1.0, source)
        values[second_rank] = RetrievalCandidate(second, 1.0, source)
        return values

    ranked, _matched = _merge_candidates(
        [
            lane("fts", relevant, noisy, 0, 3),
            lane("vector", relevant, noisy, 29, 0),
            lane("recent", relevant, noisy, 0, 3),
        ],
        2,
    )

    assert [candidate.claim_version_id for candidate in ranked] == [relevant, noisy]


def test_optional_mmr_selects_diverse_gated_result_deterministically() -> None:
    candidates = [
        {
            "claim_version_id": "a",
            "relevance_score": 1.0,
            "predicate": "runtime language",
            "payload": {"value": "python runtime service"},
            "open_issue_ids": [],
        },
        {
            "claim_version_id": "b",
            "relevance_score": 0.95,
            "predicate": "runtime language",
            "payload": {"value": "python runtime service"},
            "open_issue_ids": [],
        },
        {
            "claim_version_id": "c",
            "relevance_score": 0.9,
            "predicate": "storage engine",
            "payload": {"value": "postgres canonical state"},
            "open_issue_ids": [],
        },
    ]
    selected = _mmr_select(candidates, 2, relevance_weight=0.6)
    assert [item["claim_version_id"] for item in selected] == ["a", "c"]
    assert _mmr_select(candidates, 2, relevance_weight=0.6) == selected


def test_mmr_never_applies_novelty_penalty_to_open_issue_result() -> None:
    candidates = [
        {
            "claim_version_id": "a",
            "relevance_score": 1.0,
            "payload": {"value": "same content"},
            "open_issue_ids": [],
        },
        {
            "claim_version_id": "b",
            "relevance_score": 0.95,
            "payload": {"value": "same content"},
            "open_issue_ids": ["issue-1"],
        },
        {
            "claim_version_id": "c",
            "relevance_score": 0.9,
            "payload": {"value": "diverse content"},
            "open_issue_ids": [],
        },
    ]
    selected = _mmr_select(candidates, 2, relevance_weight=0.6)
    assert [item["claim_version_id"] for item in selected] == ["a", "b"]


def _gated_fixture() -> tuple[list[RetrievalCandidate], GatedBatch]:
    version_ids = [UUID(int=index) for index in range(1, 5)]
    ranked = [
        RetrievalCandidate(version_id, 1.0 - index / 10, "fts")
        for index, version_id in enumerate(version_ids)
    ]
    outcomes = [
        {
            "claim_id": UUID(int=100 + index),
            "claim_version_id": version_id,
            "accepted": True,
            "evidence_ids": [UUID(int=200 + index)],
            "open_issue_ids": [],
        }
        for index, version_id in enumerate(version_ids)
    ]
    claims = [
        {
            "claim_id": UUID(int=100 + index),
            "claim_version_id": version_id,
            "payload": {"memory_text": f"memory {index}"},
        }
        for index, version_id in enumerate(version_ids)
    ]
    return ranked, GatedBatch(ProjectionState(0, 0, 0, False, False), outcomes, claims)


class _ReverseReranker:
    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        limit: int,
        pool_size: int,
    ) -> RerankerExecution:
        assert query
        assert pool_size == 10
        selected = []
        for candidate in reversed(candidates[:pool_size]):
            result = dict(candidate)
            result["reranker"] = {"score": float(len(candidates) - len(selected))}
            selected.append(result)
        return RerankerExecution(selected[:limit], {"pairs": len(candidates)})


def test_cross_encoder_reranks_only_canonical_gated_pool_and_preserves_trace_order() -> None:
    ranked, batch = _gated_fixture()
    accepted, rejected, results, issues = _assemble_results(
        ranked,
        {candidate.claim_version_id: ["fts"] for candidate in ranked},
        batch,
        3,
        query="How many facts are combined?",
        reranker=_ReverseReranker(),
    )

    expected = [str(UUID(int=index)) for index in (4, 3, 2)]
    assert [str(item["claim_version_id"]) for item in results] == expected
    assert [str(item["claim_version_id"]) for item in accepted] == expected
    assert all("reranker" in item for item in accepted)
    assert rejected == []
    assert issues == []


def test_explicit_compound_subject_cannot_resolve_a_shorter_subject_suffix() -> None:
    version_id = UUID(int=1)
    ranked = [RetrievalCandidate(version_id, 1.0, "fts")]
    batch = GatedBatch(
        ProjectionState(0, 0, 0, False, False),
        [
            {
                "claim_id": UUID(int=101),
                "claim_version_id": version_id,
                "accepted": True,
                "evidence_ids": [],
                "open_issue_ids": [],
            }
        ],
        [
            {
                "claim_id": UUID(int=101),
                "claim_version_id": version_id,
                "subject_id": "orchid-release",
                "predicate": "release.target",
                "payload": {"value": "synthetic-target"},
            }
        ],
    )

    accepted, rejected, results, _issues = _assemble_results(
        ranked,
        {version_id: ["fts"]},
        batch,
        3,
        query="What is the target for outside-orchid-release?",
    )

    assert accepted == []
    assert results == []
    assert rejected == [
        {
            "claim_version_id": str(version_id),
            "reject_reason": "QUERY_SUBJECT_MISMATCH",
        }
    ]


def test_explicit_compound_subject_still_resolves_its_exact_address() -> None:
    ranked, batch = _gated_fixture()
    batch.claims[0]["subject_id"] = "orchid-release"

    accepted, rejected, results, _issues = _assemble_results(
        ranked[:1],
        {ranked[0].claim_version_id: ["fts"]},
        GatedBatch(batch.projection_state, batch.outcomes[:1], batch.claims[:1]),
        3,
        query="What is the target for orchid-release?",
    )

    assert len(accepted) == len(results) == 1
    assert rejected == []


def test_unrelated_compound_does_not_block_an_ordinary_subject_match() -> None:
    ranked, batch = _gated_fixture()
    batch.claims[0]["subject_id"] = "orchid-release"

    accepted, rejected, results, _issues = _assemble_results(
        ranked[:1],
        {ranked[0].claim_version_id: ["fts"]},
        GatedBatch(batch.projection_state, batch.outcomes[:1], batch.claims[:1]),
        3,
        query="What is the state-of-art target for orchid release?",
    )

    assert len(accepted) == len(results) == 1
    assert rejected == []


def test_binary_event_order_preserves_one_canonical_candidate_per_anchor() -> None:
    version_ids = [UUID(int=index) for index in range(1, 5)]
    ranked = [
        RetrievalCandidate(version_id, 1.0 / index, "fts")
        for index, version_id in enumerate(version_ids, start=1)
    ]
    texts = [
        "unrelated first candidate",
        "another unrelated candidate",
        "I participated in the #PlankChallenge today.",
        "I shared a vegan chili recipe in an Instagram post yesterday.",
    ]
    batch = GatedBatch(
        ProjectionState(0, 0, 0, False, False),
        [
            {
                "claim_id": UUID(int=100 + index),
                "claim_version_id": version_id,
                "accepted": True,
                "evidence_ids": [],
                "open_issue_ids": [],
            }
            for index, version_id in enumerate(version_ids)
        ],
        [
            {
                "claim_id": UUID(int=100 + index),
                "claim_version_id": version_id,
                "payload": {"memory_text": texts[index]},
                "valid_time_from": f"2023-03-{10 + index:02d}T00:00:00+00:00",
            }
            for index, version_id in enumerate(version_ids)
        ],
    )
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=(
                "Which event happened first, my participation in the "
                "#PlankChallenge or my post about vegan chili recipe?"
            ),
        )
    )

    _accepted, _rejected, results, _issues = _assemble_results(
        ranked,
        {version_id: ["fts"] for version_id in version_ids},
        batch,
        3,
        query=(
            "Which event happened first, my participation in the "
            "#PlankChallenge or my post about vegan chili recipe?"
        ),
        plan=plan,
        reranker=_ReverseReranker(),
    )

    assert [str(item["claim_version_id"]) for item in results[:2]] == [
        str(version_ids[2]),
        str(version_ids[3]),
    ]


def test_cross_encoder_is_not_invoked_for_an_empty_canonical_pool() -> None:
    reranker = _UnavailableReranker()
    empty_batch = GatedBatch(
        ProjectionState(0, 0, 0, False, False),
        [],
        [],
    )

    accepted, rejected, results, issues = _assemble_results(
        [],
        {},
        empty_batch,
        3,
        query="Which memory applies?",
        reranker=reranker,
    )

    assert accepted == rejected == results == issues == []
    assert reranker.calls == 0


class _UnavailableReranker:
    calls = 0

    def rerank(self, *args: Any, **kwargs: Any) -> RerankerExecution:
        self.calls += 1
        raise RerankerUnavailable("injected outage")


class _CandidateRepository:
    def __init__(self) -> None:
        self.ranked, self.batch = _gated_fixture()
        self.trace: Any | None = None

    def projection_state(self, *args: Any, **kwargs: Any) -> ProjectionState:
        return self.batch.projection_state

    def exact_candidates(self, *args: Any, **kwargs: Any) -> list[RetrievalCandidate]:
        return self.ranked

    def search_fts(self, *args: Any, **kwargs: Any) -> list[RetrievalCandidate]:
        return []

    def search_evidence(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def search_vector(self, *args: Any, **kwargs: Any) -> list[RetrievalCandidate]:
        return []

    def gate_and_hydrate(self, *args: Any, **kwargs: Any) -> GatedBatch:
        return self.batch

    def record_trace(self, _context: Any, trace: Any) -> UUID:
        self.trace = trace
        return UUID(int=999)


class _ProgressiveRepository(_CandidateRepository):
    def __init__(self) -> None:
        super().__init__()
        self.ranked = self.ranked[:1]
        self.vector_calls = 0

    def search_vector(self, *args: Any, **kwargs: Any) -> list[RetrievalCandidate]:
        self.vector_calls += 1
        return self.ranked


class _SparseProgressiveRepository(_ProgressiveRepository):
    def exact_candidates(self, *args: Any, **kwargs: Any) -> list[RetrievalCandidate]:
        return []


class _DeadlineRepository(_ProgressiveRepository):
    def exact_candidates(self, *args: Any, **kwargs: Any) -> list[RetrievalCandidate]:
        raise DatabaseStatementTimeout("injected bounded search timeout")


class _EvidenceReferenceRepository(_CandidateRepository):
    def search_evidence(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "canonical": False,
                "canonical_mutation": False,
                "evidence_id": "evidence-mugs",
                "source_ref": "memory://session-mugs/turn/0",
                "subject_id": "session-mugs",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
                "source_context": {
                    "session_id": "session-mugs",
                    "turn_id": "session-mugs:turn:0",
                    "turn_ordinal": 0,
                    "round_id": "session-mugs:round:0",
                    "round_ordinal": 0,
                    "previous_turn_id": None,
                    "next_turn_id": None,
                },
                "source_context_source": "STRUCTURED_TURN_METADATA",
                "observed_at": "2026-08-27T12:00:00+00:00",
                "captured_at": "2026-08-27T12:00:01+00:00",
                "content": "I paid $60 for 5 ceramic mugs.",
                "content_hash": "a" * 64,
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "revoked_at": None,
                "relevance_score": 1.0,
            }
        ]


class _CountingEvidenceReferenceRepository(_EvidenceReferenceRepository):
    def __init__(self) -> None:
        super().__init__()
        self.evidence_search_calls = 0

    def search_evidence(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.evidence_search_calls += 1
        return super().search_evidence(*args, **kwargs)


def _access_plan(intent: str = "POSSIBLE") -> MemoryAccessPlan:
    return MemoryAccessPlan(
        access_intent="POSSIBLE" if intent == "POSSIBLE" else "REQUIRED",
        candidate_cap=30,
        deadline_ms=250,
        context_token_budget=768,
        reranker_candidate_cap=0 if intent == "POSSIBLE" else 20,
        hard_partitions=("tenant", "principal_scope", "valid_time"),
    )


def test_dg18_raw_bindings_do_not_enter_authoritative_acquisition_state() -> None:
    repository = _EvidenceReferenceRepository()
    service = RetrievalService(repository)  # type: ignore[arg-type]

    result = service.retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="How much did I pay per ceramic mug?",
            as_of=datetime.fromisoformat("2026-08-28T00:00:00+00:00"),
            system_as_of=datetime.fromisoformat("2026-08-28T00:00:00+00:00"),
            memory_intent="HISTORY",
            evidence_need="RAW_EVIDENCE",
            consistency="CANONICAL_REQUIRED",
            limit=3,
        ),
        "dg18-binding-backed-state",
        access_plan=_access_plan("REQUIRED"),
    )

    state = result.body["progressive_l1"]["acquisition_state"]
    assert state["accepted_evidence_note_count"] == 0
    assert state["satisfied_requirement_ids"] == []
    assert state["missing_requirement_ids"] == ["ITEM_COUNT", "TOTAL_PRICE"]
    assert repository.trace.execution_trace["acquisition_state"] == state
    assert result.body["access_trace"]["acquisition_state"] == state
    encoded = str(repository.trace.execution_trace)
    assert "evidence-mugs" not in encoded
    assert "session-mugs" not in encoded
    assert "paid $60" not in encoded


def test_dg20_raw_matches_do_not_masquerade_as_deterministic_complete() -> None:
    context = SessionContext(UUID(int=500), UUID(int=501))
    request = RetrievalRequest(
        route="L1",
        query="How much did I pay per ceramic mug?",
        as_of=datetime.fromisoformat("2026-08-28T00:00:00+00:00"),
        system_as_of=datetime.fromisoformat("2026-08-28T00:00:00+00:00"),
        memory_intent="HISTORY",
        evidence_need="RAW_EVIDENCE",
        consistency="CANONICAL_REQUIRED",
        limit=3,
    )
    baseline_repository = _CountingEvidenceReferenceRepository()
    recovery_repository = _CountingEvidenceReferenceRepository()

    baseline = RetrievalService(baseline_repository).retrieve(  # type: ignore[arg-type]
        context,
        request,
        "dg20-complete-baseline",
        access_plan=_access_plan("REQUIRED"),
    )
    recovered = RetrievalService(  # type: ignore[arg-type]
        recovery_repository,
        deterministic_recovery_enabled=True,
    ).retrieve(
        context,
        request,
        "dg20-complete-candidate",
        access_plan=_access_plan("REQUIRED"),
    )

    assert "deterministic_recovery" not in baseline.body["progressive_l1"]
    recovery = recovered.body["progressive_l1"]["deterministic_recovery"]
    assert recovery["decision"]["reason_code"] == "NO_NONREPEATED_FEASIBLE_ACTION"
    assert recovery["attempted"] is True
    assert recovery["extra_pass_count"] == 0
    assert recovery["provider_calls"] == 0
    assert recovery["automatic_retries"] == 0
    assert recovery["canonical_mutation"] is False
    assert baseline_repository.evidence_search_calls == (
        recovery_repository.evidence_search_calls
    )
    assert baseline.body["results"] == recovered.body["results"]
    assert baseline.body["derived_result"] == recovered.body["derived_result"]
    assert baseline.body["abstained"] == recovered.body["abstained"]
    assert baseline.body["abstention_reason"] == recovered.body["abstention_reason"]
    baseline_state = deepcopy(baseline.body["progressive_l1"]["acquisition_state"])
    recovery_state = deepcopy(recovered.body["progressive_l1"]["acquisition_state"])
    baseline_state["remaining_budget"].pop("latency_ms")
    recovery_state["remaining_budget"].pop("latency_ms")
    assert baseline_state == recovery_state


def test_dg21_can_search_again_but_raw_matches_stay_non_authoritative() -> None:
    repository = _CountingEvidenceReferenceRepository()
    result = RetrievalService(  # type: ignore[arg-type]
        repository,
        deterministic_recovery_enabled=True,
        type_directed_acquisition_enabled=True,
    ).retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="How much did I pay per ceramic mug?",
            as_of=datetime.fromisoformat("2026-08-28T00:00:00+00:00"),
            system_as_of=datetime.fromisoformat("2026-08-28T00:00:00+00:00"),
            memory_intent="HISTORY",
            evidence_need="RAW_EVIDENCE",
            consistency="CANONICAL_REQUIRED",
            limit=3,
        ),
        "dg21-complete-fast-stop",
        access_plan=_access_plan("REQUIRED"),
    )

    recovery = result.body["progressive_l1"]["deterministic_recovery"]
    selection = recovery["execution_selection"]
    # Raw matches cannot satisfy the operator, so the bounded deterministic
    # recovery policy may spend its one declared official pass.
    assert selection is None
    assert recovery["attempted"] is True
    assert recovery["decision"]["reason_code"] == "SELECTED_FTS_ENRICHED"
    assert recovery["extra_pass_count"] == 1
    assert recovery["provider_calls"] == 0
    assert repository.trace.execution_trace["sufficiency_decision"]["status"] == (
        "UNSATISFIED"
    )


def test_possible_probe_stops_after_canonical_gated_fts_with_fixed_budget() -> None:
    repository = _ProgressiveRepository()
    reranker = _UnavailableReranker()
    service = RetrievalService(repository, reranker=reranker)  # type: ignore[arg-type]

    result = service.retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="Could this affect the release?",
            consistency="CANONICAL_REQUIRED",
            limit=3,
        ),
        "possible-fts-probe",
        context_budget=768,
        access_plan=_access_plan(),
    )

    progressive = result.body["progressive_l1"]
    assert progressive["access_intent"] == "POSSIBLE"
    assert progressive["budget"] == {
        "candidate_cap": 30,
        "deadline_ms": 250,
        "context_token_budget": 768,
        "reranker_candidate_cap": 0,
    }
    assert progressive["stop_stage"] == "FTS"
    assert progressive["candidate_counts"]["exact"] == 1
    assert progressive["candidate_counts"]["fts"] == 0
    assert progressive["candidate_counts"]["fused_fts"] == 1
    assert progressive["deadline_outcome"] == "MET"
    assert repository.vector_calls == 0
    assert reranker.calls == 0
    assert result.body["access_plan"]["vector_policy"] == "SPARSE_INSUFFICIENCY_ONLY"
    assert "recent_canonical_ms" not in result.body["stage_metrics"]["counts"]


def test_possible_probe_escalates_to_filtered_vector_only_after_sparse_fts() -> None:
    repository = _SparseProgressiveRepository()
    reranker = _UnavailableReranker()
    service = RetrievalService(repository, reranker=reranker)  # type: ignore[arg-type]

    result = service.retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="Could this affect the release?",
            consistency="CANONICAL_REQUIRED",
            limit=3,
        ),
        "possible-vector-probe",
        context_budget=768,
        access_plan=_access_plan(),
    )

    progressive = result.body["progressive_l1"]
    assert progressive["stages_attempted"] == [
        "EVIDENCE_FTS",
        "EXACT_FTS",
        "VECTOR",
    ]
    assert progressive["escalation_reasons"] == [
        "FTS_INSUFFICIENT:NO_CANONICAL_RESULT"
    ]
    assert progressive["stop_stage"] == "VECTOR"
    assert progressive["candidate_counts"]["vector"] == 1
    assert repository.vector_calls == 1
    assert reranker.calls == 0


def test_possible_probe_deadline_exhaustion_is_typed_and_skips_vector() -> None:
    repository = _DeadlineRepository()
    service = RetrievalService(repository)  # type: ignore[arg-type]

    result = service.retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="Could this affect the release?",
            consistency="CANONICAL_REQUIRED",
            limit=3,
        ),
        "possible-deadline-probe",
        context_budget=768,
        access_plan=_access_plan(),
    )

    assert result.body["abstained"] is True
    assert result.body["abstention_reason"] == "SEARCH_BUDGET_EXHAUSTED"
    assert result.body["progressive_l1"]["stop_stage"] == "BUDGET"
    assert result.body["progressive_l1"]["deadline_outcome"] == "EXHAUSTED"
    assert result.body["degraded_components"] == ["search_budget"]
    assert repository.vector_calls == 0


def test_required_complex_search_reranks_only_the_small_canonical_gated_pool() -> None:
    repository = _CandidateRepository()
    reranker = _ReverseReranker()
    service = RetrievalService(repository, reranker=reranker)  # type: ignore[arg-type]

    result = service.retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="How many facts are combined?",
            consistency="CANONICAL_REQUIRED",
            limit=3,
        ),
        "required-bounded-reranker",
        context_budget=2_500,
        access_plan=_access_plan("REQUIRED"),
    )

    progressive = result.body["progressive_l1"]
    assert progressive["stages_attempted"] == [
        "EVIDENCE_FTS",
        "EXACT_FTS",
        "VECTOR",
        "RERANKER",
    ]
    assert progressive["candidate_counts"]["reranker_input"] == 4
    assert progressive["candidate_counts"]["reranker_output"] == 3
    assert result.body["access_plan"]["reranker_candidate_cap"] == 20


def test_typed_current_singleton_stops_after_canonical_gated_fts() -> None:
    repository = _ProgressiveRepository()
    reranker = _UnavailableReranker()
    service = RetrievalService(repository, reranker=reranker)  # type: ignore[arg-type]

    result = service.retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="Which project target applies?",
            memory_intent="CURRENT_STATE",
            evidence_need="SUPPORT_POINTERS",
            consistency="CANONICAL_REQUIRED",
            limit=3,
        ),
        "progressive-current",
    )

    assert result.body["progressive_l1"]["stop_stage"] == "FTS"
    assert result.body["progressive_l1"]["sufficiency_reason"] == (
        "NATURAL_LANGUAGE_READER_ONLY"
    )
    assert result.body["progressive_l1"]["terminal_sufficiency_decision"]["status"] == (
        "PARTIAL"
    )
    assert result.body["stage_metrics"]["counts"]["progressive_l1_fts_stop"] == 1
    assert "query_embedding_ms" not in result.body["stage_metrics"]["counts"]
    assert repository.vector_calls == 0
    assert reranker.calls == 0
    trace = repository.trace.execution_trace
    assert trace["schema_version"] == "retrieval-execution-v1"
    assert trace["requested_intent"] == "CURRENT_STATE"
    assert trace["terminal_stage"] == "FTS"
    assert trace["stop_reason"] == "NATURAL_LANGUAGE_READER_ONLY"
    assert trace["result_count"] == 1
    assert trace["route_trace_complete"] is True
    assert trace["sufficiency_decision"]["status"] == "PARTIAL"
    assert trace["sufficiency_decision"]["missing_slots"] == ["LOOKUP_ANSWER"]
    assert trace["acquisition_state"] == result.body["progressive_l1"][
        "acquisition_state"
    ]
    assert repository.trace.stage_metrics["counts"]["query_total_ms"] == 1
    assert result.body["access_trace"]["retrieval_trace_id"] == str(UUID(int=999))
    assert result.body["access_trace"]["canonical_position"] == 0
    assert result.body["access_trace"]["spans"]["mcp_decode_ms"] is None


def test_why_change_without_version_chain_never_claims_complete_history() -> None:
    repository = _ProgressiveRepository()
    reranker = _UnavailableReranker()
    service = RetrievalService(repository, reranker=reranker)  # type: ignore[arg-type]

    result = service.retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="Why did the project decision change?",
            memory_intent="HISTORY",
            evidence_need="SUPPORT_POINTERS",
            consistency="CANONICAL_REQUIRED",
            limit=3,
        ),
        "progressive-history",
    )

    assert result.body["progressive_l1"]["stages_attempted"] == [
        "EVIDENCE_FTS",
        "EXACT_FTS",
        "VECTOR",
        "RERANKER",
    ]
    assert result.body["abstained"] is True
    assert result.body["abstention_reason"] == (
        "SUFFICIENCY_PARTIAL_SEARCH_SPACE_EXHAUSTED"
    )
    terminal = result.body["progressive_l1"]["terminal_sufficiency_decision"]
    assert terminal["status"] == "PARTIAL"
    assert terminal["missing_slots"] == ["CONCLUSION", "SUPPORT"]
    assert result.body["stage_metrics"]["counts"]["query_embedding_ms"] == 1
    assert result.body["stage_metrics"]["counts"]["vector_ms"] == 1
    assert result.body["fallback_reason"] == "RERANKER_UNAVAILABLE"
    assert repository.vector_calls == 1
    assert reranker.calls == 1
    assert repository.trace.execution_trace["attempted_stages"] == [
        "EVIDENCE_FTS",
        "EXACT",
        "FTS",
        "CANONICAL_GATE",
        "HYDRATE",
        "SUFFICIENCY",
        "VECTOR",
        "CANONICAL_GATE",
        "HYDRATE",
        "SUFFICIENCY",
        "RERANKER",
        "HYDRATE",
        "SUFFICIENCY",
    ]
    assert repository.trace.execution_trace["terminal_stage"] == "CANONICAL_GATE"


def test_reranker_outage_falls_back_to_original_top_three() -> None:
    repository = _CandidateRepository()
    reranker = _UnavailableReranker()
    service = RetrievalService(  # type: ignore[arg-type]
        repository,
        reranker=reranker,
    )
    result = service.retrieve(
        SessionContext(UUID(int=500), UUID(int=501)),
        RetrievalRequest(
            route="L1",
            query="How many facts are combined?",
            consistency="EVENTUAL",
            limit=3,
        ),
        "reranker-outage",
    )

    assert result.status_code == 200
    assert result.body["degraded_components"] == ["reranker"]
    assert result.body["fallback_used"] is True
    assert result.body["fallback_reason"] == "RERANKER_UNAVAILABLE"
    assert reranker.calls == 1
    assert [str(item["claim_version_id"]) for item in result.body["results"]] == [
        str(UUID(int=index)) for index in (1, 2, 3)
    ]


def test_reranker_is_not_used_for_nonstandard_visible_limit() -> None:
    repository = _CandidateRepository()
    reranker = _UnavailableReranker()
    service = RetrievalService(repository, reranker=reranker)  # type: ignore[arg-type]
    context = SessionContext(UUID(int=500), UUID(int=501))

    limited = service.retrieve(
        context,
        RetrievalRequest(
            route="L1",
            query="Which fact applies?",
            consistency="EVENTUAL",
            limit=2,
        ),
        "reranker-limit-two",
    )

    assert limited.status_code == 200
    assert limited.body["degraded_components"] == []
    assert reranker.calls == 0
