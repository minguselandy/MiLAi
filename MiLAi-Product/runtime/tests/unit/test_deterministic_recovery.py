from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from milai.adapters import ProjectionIdentity
from milai.application.accuracy_acquisition import (
    AccuracyAcquisitionExecutor,
    _rank_requirement,
    accuracy_bundle_query_text,
    compile_requirement_complete_bundle,
)
from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
)
from milai.application.acquisition_execution_policy import (
    default_acquisition_execution_policy,
)
from milai.application.decision_engine import (
    DEFAULT_DECISION_ENGINE,
    FINAL_COMPLETE_AUTHORITY,
)
from milai.application.deterministic_recovery import (
    CapabilityConstrainedRecoveryService,
    _bounded_bound_results,
    build_acquisition_observation_v02,
    select_deterministic_recovery_action,
)
from milai.application.evidence_acquisition import EvidenceAcquisitionExecutor
from milai.application.evidence_semantics import (
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_state import resolve_requirement_state
from milai.application.retrieval import (
    _accepted_binding_spans,
    _accuracy_execution_safe_summary,
    _decision_accepted_evidence_ids,
    _operator_support_refs,
    _ScopedAccuracyRepository,
)
from milai.domain import RetrievalRequest
from milai.domain.semantic_query import LexicalCueSetV01
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState

REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)
CONTEXT = SessionContext(UUID(int=1), UUID(int=2))


def _accuracy_rank_evidence(evidence_id: str, content: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://accuracy/turn/{evidence_id}",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": REFERENCE.isoformat(),
        "content": content,
    }


class _Repository:
    def search_evidence(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        return []

    def search_evidence_dense(self) -> None:
        pass

    def scan_evidence_range(self) -> None:
        pass

    def hydrate_evidence_adjacency(self) -> None:
        pass

    def exact_candidates(self) -> None:
        pass


class _Embedding128:
    dimensions = 128
    identity = ProjectionIdentity(
        provider="test",
        model_id="dg20-test-embedding",
        source_dimensions=128,
        projection_dimensions=128,
        normalization="l2",
        code_version="projection-128/v1",
    )

    def embed(self, _text: str) -> list[float]:
        return [0.0] * self.dimensions

    def embed_many(self, texts: list[str], _batch_size: int) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class _DenseRepository(_Repository):
    dense_calls = 0

    def search_evidence_dense(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.dense_calls += 1
        return {
            "status": "COMPLETE",
            "items": [
                {
                    "kind": "EVIDENCE_OBSERVATION",
                    "canonical": False,
                    "canonical_mutation": False,
                    "evidence_id": "dense-holi-and-mass",
                    "source_ref": "memory://session-dg20/turn/1",
                    "subject_id": "session-dg20",
                    "speaker": "user",
                    "speaker_source": "STRUCTURED_TURN_METADATA",
                    "observed_at": "2026-08-27T12:00:00+00:00",
                    "captured_at": "2026-08-27T12:00:01+00:00",
                    "content": (
                        "I joined the Holi festival on March 8 and attended "
                        "Sunday mass on March 10."
                    ),
                    "content_hash": "d" * 64,
                    "permission_snapshot": {"readable": True},
                    "retention_state": "READABLE",
                    "revoked_at": None,
                    "relevance_score": 1.0,
                }
            ],
        }


class _AccuracyRepository(_DenseRepository):
    def scan_accuracy_bundle(self, **_kwargs: object) -> list[dict[str, object]]:
        result = self.search_evidence_dense()
        items = result["items"]
        assert isinstance(items, list)
        return items


class _SnapshotRepository:
    def __init__(self) -> None:
        self.call: tuple[object, ...] | None = None
        self.timeout: int | None = None

    def search_evidence(
        self,
        *args: object,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, object]]:
        self.call = args
        self.timeout = statement_timeout_ms
        return [{"evidence_id": "e-1"}]


def _policy_inputs(query: str):  # type: ignore[no-untyped-def]
    repository = _Repository()
    request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=2_048)
    assert query_plan.memory_query_ir is not None
    baseline_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=8,
        context_tokens=2_048,
    )
    policy = AcquisitionCapabilityPolicy(max_candidates=8)
    projection = ProjectionState(7, 7, 7, False, False, 7, False)
    baseline_capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=projection,
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
        source_observed_range=baseline_plan.global_constraints.source_observed_range,
        event_occurrence_range=baseline_plan.global_constraints.event_occurrence_range,
    )
    baseline = EvidenceAcquisitionExecutor(repository).execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=baseline_plan,
        capability_set=baseline_capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )
    recovery_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=8,
        context_tokens=2_048,
        enable_dense=True,
    )
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            evidence_dense_enabled=True,
            embedding_projection_dimensions=128,
        ),
        projection_state=projection,
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
        source_observed_range=recovery_plan.global_constraints.source_observed_range,
        event_occurrence_range=recovery_plan.global_constraints.event_occurrence_range,
    )
    state = resolve_requirement_state(
        plan=recovery_plan,
        requirements=query_plan.memory_query_ir.requirements,
        acquisition_capability_digest=capabilities.capability_digest,
        candidates=baseline.candidates,
        spans=baseline.spans,
        interpretations=baseline.interpretations,
        bindings=baseline.bindings,
        sufficiency_decision=baseline.sufficiency_decision,
        state_epoch=0,
        memory_query_ir=query_plan.memory_query_ir,
    )
    actions = feasible_acquisition_actions(
        state,
        capabilities,
        policy,
        source_observed_range=recovery_plan.global_constraints.source_observed_range,
        remaining_candidates=8,
        acquisition_plan=recovery_plan,
    )
    observation = build_acquisition_observation_v02(
        requirement_state=state,
        capability_set=capabilities,
        policy=policy,
        probe_dispositions=baseline.probe_dispositions,
        feasible_actions=actions,
        remaining_budget={
            "acquisition_passes": 1,
            "candidate_count": 8,
            "model_calls": 0,
        },
    )
    return state, capabilities, policy, actions, observation


def test_policy_selects_one_digest_bound_nonrepeated_dense_action() -> None:
    state, capabilities, policy, actions, observation = _policy_inputs(
        "How many days passed between the Holi festival and Sunday mass?"
    )

    decision = select_deterministic_recovery_action(
        requirement_state=state,
        capability_set=capabilities,
        policy=policy,
        observation=observation,
        feasible_actions=actions,
    )

    assert decision.reason_code == "SELECTED_EVIDENCE_DENSE"
    assert decision.selected_action is not None
    assert decision.selected_action.channel == "EVIDENCE_DENSE"
    assert decision.selected_action.target_requirement_id in state.missing_requirement_ids
    assert decision.extra_passes_authorized == 1
    assert decision.provider_calls_authorized == 0


def test_policy_does_not_turn_completeness_gap_into_lexical_retry() -> None:
    state, capabilities, policy, actions, observation = _policy_inputs(
        "How many times did I bake something in the past two weeks?"
    )

    decision = select_deterministic_recovery_action(
        requirement_state=state,
        capability_set=capabilities,
        policy=policy,
        observation=observation,
        feasible_actions=actions,
    )

    assert decision.selected_action is None
    assert decision.reason_code == "COMPLETENESS_PROOF_CHANNEL_UNAVAILABLE"
    assert decision.extra_passes_authorized == 0


def test_policy_rejects_observation_from_a_different_state_epoch() -> None:
    state, capabilities, policy, actions, observation = _policy_inputs(
        "How many days passed between the Holi festival and Sunday mass?"
    )
    stale = observation.model_copy(update={"requirement_state_epoch": 1})

    try:
        select_deterministic_recovery_action(
            requirement_state=state,
            capability_set=capabilities,
            policy=policy,
            observation=stale,
            feasible_actions=actions,
        )
    except ValueError as exc:
        assert str(exc) == "deterministic policy input identity mismatch"
    else:
        raise AssertionError("stale observation was accepted")


def test_official_recovery_product_shadow_candidate_identity() -> None:
    repository = _DenseRepository()
    embedding = _Embedding128()
    executor = EvidenceAcquisitionExecutor(repository, embedding)
    service = CapabilityConstrainedRecoveryService(executor)
    request = RetrievalRequest(
        route="L1",
        query="How many days passed between the Holi festival and Sunday mass?",
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=2_048)
    baseline_plan = compile_acquisition_plan(
        query_plan,
        query=request.query or "",
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=8,
        context_tokens=2_048,
    )
    recovery_plan = compile_acquisition_plan(
        query_plan,
        query=request.query or "",
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=8,
        context_tokens=2_048,
        enable_dense=True,
    )
    policy = AcquisitionCapabilityPolicy(max_candidates=8)
    projection = ProjectionState(7, 7, 7, False, False, 7, False)
    baseline_capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=projection,
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
        source_observed_range=baseline_plan.global_constraints.source_observed_range,
        event_occurrence_range=baseline_plan.global_constraints.event_occurrence_range,
    )
    recovery_capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            evidence_dense_enabled=True,
            embedding_projection_dimensions=128,
        ),
        projection_state=projection,
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
        source_observed_range=recovery_plan.global_constraints.source_observed_range,
        event_occurrence_range=recovery_plan.global_constraints.event_occurrence_range,
    )
    baseline = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=baseline_plan,
        capability_set=baseline_capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )

    shadow = service.recover(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        recovery_plan=recovery_plan,
        capability_set=recovery_capabilities,
        policy=policy,
        baseline_execution=baseline,
        mode="SHADOW_NO_CONTEXT_MUTATION",
    )
    product = service.recover(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        recovery_plan=recovery_plan,
        capability_set=recovery_capabilities,
        policy=policy,
        baseline_execution=baseline,
        mode="PRODUCT",
    )

    assert shadow.extra_pass_count == product.extra_pass_count == 1
    assert shadow.decision.decision_digest == product.decision.decision_digest
    assert shadow.final_execution is not None
    assert product.final_execution is not None
    assert shadow.final_execution.mode == "SHADOW_NO_CONTEXT_MUTATION"
    assert product.final_execution.mode == "PRODUCT"
    assert shadow.final_execution.results == product.final_execution.results
    assert shadow.final_execution.candidates == product.final_execution.candidates
    assert (
        shadow.final_execution.requirement_state.state_digest
        == product.final_execution.requirement_state.state_digest
    )
    assert shadow.final_execution.sufficiency_decision == (
        product.final_execution.sufficiency_decision
    )
    assert not shadow.final_execution.canonical_mutation
    assert not product.final_execution.canonical_mutation
    assert repository.dense_calls == 4


def test_accuracy_recovery_recompiles_selected_results_without_second_probe() -> None:
    repository = _AccuracyRepository()
    embedding = _Embedding128()
    executor = EvidenceAcquisitionExecutor(repository, embedding)
    service = CapabilityConstrainedRecoveryService(executor)
    request = RetrievalRequest(
        route="L1",
        query="How many days passed between the Holi festival and Sunday mass?",
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=2_048)
    baseline_plan = compile_acquisition_plan(
        query_plan,
        query=request.query or "",
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=8,
        context_tokens=2_048,
    )
    recovery_plan = compile_acquisition_plan(
        query_plan,
        query=request.query or "",
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=8,
        context_tokens=2_048,
        enable_dense=True,
    )
    policy = AcquisitionCapabilityPolicy(max_candidates=8)
    projection = ProjectionState(7, 7, 7, False, False, 7, False)
    baseline_capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(),
        projection_state=projection,
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
        source_observed_range=baseline_plan.global_constraints.source_observed_range,
        event_occurrence_range=baseline_plan.global_constraints.event_occurrence_range,
    )
    recovery_capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            evidence_dense_enabled=True,
            embedding_projection_dimensions=128,
        ),
        projection_state=projection,
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
        source_observed_range=recovery_plan.global_constraints.source_observed_range,
        event_occurrence_range=recovery_plan.global_constraints.event_occurrence_range,
    )
    baseline = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=baseline_plan,
        capability_set=baseline_capabilities,
        policy=policy,
        mode="PRODUCT",
        state_epoch=0,
    )

    recovery = service.recover(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        recovery_plan=recovery_plan,
        capability_set=recovery_capabilities,
        policy=policy,
        baseline_execution=baseline,
        mode="PRODUCT",
        execution_policy=default_acquisition_execution_policy(),
        accuracy_executor=AccuracyAcquisitionExecutor(repository),
    )

    assert recovery.extra_pass_count == 1
    assert recovery.final_execution is not None
    assert recovery.accuracy_execution is not None
    assert recovery.accuracy_execution["repository_probe_calls"] == 1
    assert recovery.accuracy_execution["candidates_hydrated"] == 1
    assert recovery.accuracy_decision is not None
    assert recovery.accuracy_decision["status"] == "EXECUTE_ONE_PASS"
    assert recovery.superseded_execution_selection is not None
    assert recovery.execution_selection is None
    assert repository.dense_calls == 1


def test_binding_fusion_and_snapshot_respect_single_value_cardinality() -> None:
    request = RetrievalRequest(
        route="L1",
        query=(
            "How many days before the team meeting I was preparing for did I attend "
            "the workshop on Effective Communication in the Workplace?"
        ),
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=2_048)
    query_ir = query_plan.memory_query_ir
    assert query_ir is not None
    statements = [
        "I attended the workshop on Effective Communication in the Workplace on January 10.",
        "I reflected on the workshop on Effective Communication in the Workplace on January 10.",
        (
            "I was glad I attended the workshop on Effective Communication "
            "in the Workplace on January 10."
        ),
    ]
    results = [
        {
            "kind": "EVIDENCE_OBSERVATION",
            "canonical": False,
            "canonical_mutation": False,
            "evidence_id": f"workshop-{index}",
            "source_ref": f"memory://session-cardinality/turn/{index * 4}",
            "subject_id": "session-cardinality",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
            "source_context": {
                "session_id": "session-cardinality",
                "turn_id": f"session-cardinality:turn:{index * 4}",
                "turn_ordinal": index * 4,
                "round_id": f"session-cardinality:round:{index * 2}",
                "round_ordinal": index * 2,
                "previous_turn_id": None,
                "next_turn_id": None,
            },
            "source_context_source": "STRUCTURED_TURN_METADATA",
            "observed_at": REFERENCE.isoformat(),
            "captured_at": (REFERENCE + timedelta(seconds=index)).isoformat(),
            "content": statement,
            "content_hash": f"hash-{index}",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "revoked_at": None,
        }
        for index, statement in enumerate(statements)
    ]
    spans = project_evidence_spans(results)
    interpretations, bindings, _audit = run_type_directed_semantics(
        query_ir.requirements,
        spans,
        compatibility_profile="dg22-v0.2",
    )
    execution = SimpleNamespace(
        results=results,
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
    )

    fused = _bounded_bound_results(query_ir, execution)  # type: ignore[arg-type]
    projected = _accepted_binding_spans(
        execution,  # type: ignore[arg-type]
        accepted_evidence_ids={str(item["evidence_id"]) for item in results},
        requirements=query_ir.requirements,
    )

    assert [item["evidence_id"] for item in fused] == ["workshop-0"]
    # The fused item remains a useful retrieval diagnostic, but a Raw-language
    # classifier cannot promote it into an accepted operator span.
    assert projected == []


def test_scoped_accuracy_repository_uses_governed_fts_with_speaker_lineage() -> None:
    repository = _SnapshotRepository()
    request = RetrievalRequest(
        route="L1",
        query="What did I remember?",
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    adapter = _ScopedAccuracyRepository(
        repository,  # type: ignore[arg-type]
        CONTEXT,
        request,
        statement_timeout_ms=321,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=2_048)
    query_ir = query_plan.memory_query_ir
    assert query_ir is not None
    target_ids = [item.slot_id for item in query_ir.requirements if item.required]
    bundle = compile_requirement_complete_bundle(
        query_ir,
        target_ids,
        channel="FTS_ENRICHED",
        requirement_state_digest="1" * 64,
        acquisition_capability_digest="2" * 64,
    )

    assert adapter.scan_accuracy_bundle(query_ir=query_ir, bundle=bundle) == [
        {"evidence_id": "e-1"}
    ]
    assert repository.call is not None
    assert repository.call[0] == CONTEXT
    assert isinstance(repository.call[1], str) and repository.call[1]
    assert repository.call[2:] == (
        {"project_ids": ["milai"]},
        REFERENCE,
        120,
    )
    assert repository.timeout == 321


def test_accuracy_query_uses_retrieval_cue_instead_of_semantic_entity_constraint() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What speed is my internet plan?",
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_ir = QueryPlanner().plan(request).memory_query_ir
    assert query_ir is not None
    requirement = query_ir.requirements[0].model_copy(
        update={"entity_constraints": ["semanticanchor"]}
    )
    cue = LexicalCueSetV01(
        requirement_slot=requirement.slot_id,
        surface_terms=["lexicalneedle"],
        provenance=["QUERY_TASK_CONTRACT_V01", "QUERY_SURFACE_ONLY"],
    )
    separated = query_ir.model_copy(
        update={"requirements": [requirement], "lexical_cues": [cue]}
    )
    bundle = compile_requirement_complete_bundle(
        separated,
        [requirement.slot_id],
        channel="FTS_ENRICHED",
        requirement_state_digest="1" * 64,
        acquisition_capability_digest="2" * 64,
    )

    query_text = accuracy_bundle_query_text(separated, bundle)

    assert "lexicalneedle" in query_text.split()
    assert "semanticanchor" not in query_text.split()


def test_accuracy_ranking_treats_retrieval_cue_as_soft_signal() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What speed is my internet plan?",
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_ir = QueryPlanner().plan(request).memory_query_ir
    assert query_ir is not None
    requirement = query_ir.requirements[0].model_copy(
        update={"entity_constraints": ["semanticanchor"]}
    )
    cue = LexicalCueSetV01(
        requirement_slot=requirement.slot_id,
        surface_terms=["lexicalneedle"],
        provenance=["QUERY_TASK_CONTRACT_V01", "QUERY_SURFACE_ONLY"],
    )
    evidence = [
        _accuracy_rank_evidence("semantic-only", "The semanticanchor is documented."),
        _accuracy_rank_evidence("lexical-hit", "The lexicalneedle is documented."),
    ]

    ranked = _rank_requirement(requirement, evidence, lexical_cue=cue)
    legacy_ranked = _rank_requirement(requirement, evidence)
    empty_cue_ranked = _rank_requirement(
        requirement,
        evidence,
        lexical_cue=cue.model_copy(update={"surface_terms": []}),
    )

    assert [item["evidence_id"] for item in ranked] == [
        "lexical-hit",
        "semantic-only",
    ]
    assert [item["evidence_id"] for item in legacy_ranked] == ["semantic-only"]
    assert {item["evidence_id"] for item in empty_cue_ranked} == {
        "lexical-hit",
        "semantic-only",
    }


def test_operator_provenance_bounds_exhaustive_binding_protection() -> None:
    request = RetrievalRequest(
        route="L1",
        query="How many workshops did I attend in March?",
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=2_048)
    query_ir = query_plan.memory_query_ir
    assert query_ir is not None
    results = [
        {
            "kind": "EVIDENCE_OBSERVATION",
            "canonical": False,
            "canonical_mutation": False,
            "evidence_id": evidence_id,
            "source_ref": f"memory://session-proof/turn/{index}",
            "subject_id": "session-proof",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
            "source_context": {
                "session_id": "session-proof",
                "turn_id": f"session-proof:turn:{index}",
                "turn_ordinal": index,
                "round_id": f"session-proof:round:{index // 2}",
                "round_ordinal": index // 2,
                "previous_turn_id": None,
                "next_turn_id": None,
            },
            "source_context_source": "STRUCTURED_TURN_METADATA",
            "observed_at": REFERENCE.isoformat(),
            "captured_at": (REFERENCE + timedelta(seconds=index)).isoformat(),
            "content": f"I attended a workshop on March {index + 1}th.",
            "content_hash": f"hash-{index}",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "revoked_at": None,
        }
        for index, evidence_id in enumerate(("answer-support", "proof-only"))
    ]
    spans = project_evidence_spans(results)
    interpretations, bindings, _audit = run_type_directed_semantics(
        query_ir.requirements,
        spans,
        compatibility_profile="dg22-v0.2",
    )
    execution = SimpleNamespace(spans=spans, interpretations=interpretations, bindings=bindings)
    support_ids, support_refs = _operator_support_refs(
        {
            "canonical_mutation": False,
            "evidence_refs": ["answer-support"],
            "source_turn_refs": ["memory://session-proof/turn/0"],
        }
    )

    projected = _accepted_binding_spans(
        execution,  # type: ignore[arg-type]
        accepted_evidence_ids={"answer-support", "proof-only"},
        requirements=query_ir.requirements,
        supporting_evidence_ids=support_ids,
        supporting_source_refs=support_refs,
    )

    # Explicit result provenance narrows diagnostics; it does not turn the
    # preceding Raw-language classification into operand authority.
    assert projected == []


def test_operator_support_completes_a_bounded_state_note_set_without_injection() -> None:
    results = [
        {"evidence_id": "event-1", "source_ref": "memory://episode-a/turn/0"},
        {"evidence_id": "event-2", "source_ref": "memory://episode-b/turn/0"},
        {"evidence_id": "noise", "source_ref": "memory://episode-c/turn/0"},
    ]
    state = SimpleNamespace(
        accepted_evidence_refs=[SimpleNamespace(evidence_id="event-2")]
    )
    execution = SimpleNamespace(
        spans=[
            SimpleNamespace(
                source_evidence_id="event-1",
                source_turn_ref="memory://episode-a/turn/0",
            )
        ]
    )

    accepted = _decision_accepted_evidence_ids(
        acquisition_state=state,  # type: ignore[arg-type]
        acquisition_execution=execution,  # type: ignore[arg-type]
        results=results,
        supporting_evidence_ids={"off-snapshot"},
        supporting_source_refs={"memory://episode-a/turn/0", "memory://stale/turn/0"},
    )

    assert accepted == ["event-1", "event-2"]


def test_empty_binding_state_never_promotes_governed_candidates_to_accepted() -> None:
    results = [
        {"evidence_id": "question-paraphrase", "source_ref": "memory://episode-a/turn/0"},
        {"evidence_id": "wrong-relation", "source_ref": "memory://episode-b/turn/0"},
    ]
    state = SimpleNamespace(accepted_evidence_refs=[])
    execution = SimpleNamespace(spans=[])

    accepted = _decision_accepted_evidence_ids(
        acquisition_state=state,  # type: ignore[arg-type]
        acquisition_execution=execution,  # type: ignore[arg-type]
        results=results,
        supporting_evidence_ids=set(),
        supporting_source_refs=set(),
    )

    assert accepted == []


def test_formation_operator_exposes_only_explicit_operand_evidence() -> None:
    results = [
        {"evidence_id": "answer-support", "source_ref": "memory://episode-a/turn/0"},
        {"evidence_id": "assistant-noise", "source_ref": "memory://episode-a/turn/1"},
    ]
    state = SimpleNamespace(
        accepted_evidence_refs=[SimpleNamespace(evidence_id="assistant-noise")]
    )
    execution = SimpleNamespace(
        spans=[
            SimpleNamespace(
                source_evidence_id="answer-support",
                source_turn_ref="memory://episode-a/turn/0",
                provenance={"formation_artifact_kind": "STATE_ASSERTION"},
            )
        ]
    )

    accepted = _decision_accepted_evidence_ids(
        acquisition_state=state,  # type: ignore[arg-type]
        acquisition_execution=execution,  # type: ignore[arg-type]
        results=results,
        supporting_evidence_ids={"answer-support"},
        supporting_source_refs=set(),
    )

    assert accepted == ["answer-support"]


def test_final_complete_is_downgraded_when_typed_requirements_are_missing() -> None:
    state, _capabilities, _policy, _actions, _observation = _policy_inputs(
        "How many days passed between the Holi festival and Sunday mass?"
    )
    assert state.missing_requirement_ids
    request = RetrievalRequest(route="L1", query="Where do I live?")
    plan = QueryPlanner().plan(request)
    result = DEFAULT_DECISION_ENGINE.decide(
        plan.memory_query_ir,
        (),
        ({"kind": "CANONICAL_CLAIM", "claim_version_id": "c-1"},),
        (),
        (),
        (),
        None,
        None,
        request=request,
        plan=plan,
        requirement_state=state,
    )
    decision, reason = result.sufficiency_decision, result.reason_code

    assert not decision.complete
    assert decision.missing_slots == state.missing_requirement_ids
    assert reason == "REQUIREMENT_STATE_INCOMPLETE"


def test_final_complete_authority_has_one_product_identity() -> None:
    assert FINAL_COMPLETE_AUTHORITY == "milai-decision-engine-v0.1"


def test_accuracy_trace_summary_excludes_candidate_payloads() -> None:
    summary = _accuracy_execution_safe_summary(
        {
            "executor_identity": "executor-v1",
            "policy_version": "policy-v1",
            "candidates_scanned": 9,
            "candidates_hydrated": 3,
            "useful_candidate_count": 2,
            "repository_probe_calls": 1,
            "provider_controller_calls": 0,
            "automatic_retries": 0,
            "canonical_mutation": False,
            "selected_evidence": [{"content": "must-not-leak"}],
        }
    )

    assert summary == {
        "executor_identity": "executor-v1",
        "policy_version": "policy-v1",
        "candidates_scanned": 9,
        "candidates_hydrated": 3,
        "useful_candidate_count": 2,
        "repository_probe_calls": 1,
        "provider_controller_calls": 0,
        "automatic_retries": 0,
        "canonical_mutation": False,
    }
