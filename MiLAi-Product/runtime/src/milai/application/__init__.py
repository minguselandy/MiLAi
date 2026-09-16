"""Application exports without eagerly importing the full Runtime graph."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from milai.application.acquisition_state import (
        AcquisitionStateTransition,
        AcquisitionTransitionOutcome,
        acquisition_state_trace_summary,
        advance_acquisition_state,
        build_acquisition_action,
        build_acquisition_region,
        build_acquisition_window,
        build_evidence_reference_note,
        initialize_acquisition_state,
        reserve_residual_controller_call,
    )
    from milai.application.causality import CausalityService
    from milai.application.chat import ChatService
    from milai.application.context import ContextService
    from milai.application.context_preparation import PrepareContextService
    from milai.application.context_receipt import ContextReceiptService
    from milai.application.deletion import DeletionService
    from milai.application.derivation import (
        CommitPolicy,
        CommitPolicyResult,
        DeriveAndDiagnose,
        ValidatedProposal,
    )
    from milai.application.episodes import EpisodeService
    from milai.application.evidence import EvidenceService
    from milai.application.evidence_semantics import (
        bind_requirements,
        interpret_evidence_spans,
        project_evidence_spans,
    )
    from milai.application.formation_projection import FormationProjectionStore
    from milai.application.memory_context import MemoryContextCompiler
    from milai.application.memory_query import MemoryQueryCompiler
    from milai.application.memory_resolve import MemoryQueryInterpreter, MemoryResolveService
    from milai.application.memory_state import MemoryStateViewService
    from milai.application.preference_composition import synthesize_preference_evidence_view
    from milai.application.projection_readiness import ProjectionReadinessService
    from milai.application.proposals import ProposalService
    from milai.application.query_planner import QueryPlanner
    from milai.application.recollection import RecollectionFacade, RetrievalExecution
    from milai.application.requirement_acquisition import (
        RequirementAcquisitionCompilationMode,
        RequirementAcquisitionCompilationV01,
        RequirementAcquisitionPlanCompiler,
    )
    from milai.application.residual_refinding import (
        ResidualHintShadowService,
        ResidualRefindingError,
        build_acquisition_observation,
        evaluate_residual_candidate_eligibility,
        validate_residual_search_hint,
    )
    from milai.application.retrieval import RetrievalService
    from milai.application.semantic_hint import SemanticHintShadowService
    from milai.application.state_address import StateAddressService


_EXPORT_MODULES = {
    "AcquisitionStateTransition": "milai.application.acquisition_state",
    "AcquisitionTransitionOutcome": "milai.application.acquisition_state",
    "CausalityService": "milai.application.causality",
    "ChatService": "milai.application.chat",
    "CommitPolicy": "milai.application.derivation",
    "CommitPolicyResult": "milai.application.derivation",
    "ContextReceiptService": "milai.application.context_receipt",
    "ContextService": "milai.application.context",
    "DeletionService": "milai.application.deletion",
    "DeriveAndDiagnose": "milai.application.derivation",
    "EpisodeService": "milai.application.episodes",
    "EvidenceService": "milai.application.evidence",
    "FormationProjectionStore": "milai.application.formation_projection",
    "MemoryContextCompiler": "milai.application.memory_context",
    "MemoryQueryCompiler": "milai.application.memory_query",
    "MemoryQueryInterpreter": "milai.application.memory_resolve",
    "MemoryResolveService": "milai.application.memory_resolve",
    "MemoryStateViewService": "milai.application.memory_state",
    "PrepareContextService": "milai.application.context_preparation",
    "ProjectionReadinessService": "milai.application.projection_readiness",
    "ProposalService": "milai.application.proposals",
    "QueryPlanner": "milai.application.query_planner",
    "RecollectionFacade": "milai.application.recollection",
    "RequirementAcquisitionCompilationMode": "milai.application.requirement_acquisition",
    "RequirementAcquisitionCompilationV01": "milai.application.requirement_acquisition",
    "RequirementAcquisitionPlanCompiler": "milai.application.requirement_acquisition",
    "ResidualHintShadowService": "milai.application.residual_refinding",
    "ResidualRefindingError": "milai.application.residual_refinding",
    "RetrievalExecution": "milai.application.recollection",
    "RetrievalService": "milai.application.retrieval",
    "SemanticHintShadowService": "milai.application.semantic_hint",
    "StateAddressService": "milai.application.state_address",
    "ValidatedProposal": "milai.application.derivation",
    "acquisition_state_trace_summary": "milai.application.acquisition_state",
    "advance_acquisition_state": "milai.application.acquisition_state",
    "bind_requirements": "milai.application.evidence_semantics",
    "build_acquisition_action": "milai.application.acquisition_state",
    "build_acquisition_observation": "milai.application.residual_refinding",
    "build_acquisition_region": "milai.application.acquisition_state",
    "build_acquisition_window": "milai.application.acquisition_state",
    "build_evidence_reference_note": "milai.application.acquisition_state",
    "evaluate_residual_candidate_eligibility": "milai.application.residual_refinding",
    "initialize_acquisition_state": "milai.application.acquisition_state",
    "interpret_evidence_spans": "milai.application.evidence_semantics",
    "project_evidence_spans": "milai.application.evidence_semantics",
    "reserve_residual_controller_call": "milai.application.acquisition_state",
    "synthesize_preference_evidence_view": "milai.application.preference_composition",
    "validate_residual_search_hint": "milai.application.residual_refinding",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


__all__ = [
    "AcquisitionStateTransition",
    "AcquisitionTransitionOutcome",
    "CausalityService",
    "ChatService",
    "CommitPolicy",
    "CommitPolicyResult",
    "ContextReceiptService",
    "ContextService",
    "DeletionService",
    "DeriveAndDiagnose",
    "EpisodeService",
    "EvidenceService",
    "FormationProjectionStore",
    "MemoryContextCompiler",
    "MemoryQueryCompiler",
    "MemoryQueryInterpreter",
    "MemoryResolveService",
    "MemoryStateViewService",
    "PrepareContextService",
    "ProjectionReadinessService",
    "ProposalService",
    "QueryPlanner",
    "RecollectionFacade",
    "RequirementAcquisitionCompilationMode",
    "RequirementAcquisitionCompilationV01",
    "RequirementAcquisitionPlanCompiler",
    "ResidualHintShadowService",
    "ResidualRefindingError",
    "RetrievalExecution",
    "RetrievalService",
    "SemanticHintShadowService",
    "StateAddressService",
    "ValidatedProposal",
    "acquisition_state_trace_summary",
    "advance_acquisition_state",
    "bind_requirements",
    "build_acquisition_action",
    "build_acquisition_observation",
    "build_acquisition_region",
    "build_acquisition_window",
    "build_evidence_reference_note",
    "evaluate_residual_candidate_eligibility",
    "initialize_acquisition_state",
    "interpret_evidence_spans",
    "project_evidence_spans",
    "reserve_residual_controller_call",
    "synthesize_preference_evidence_view",
    "validate_residual_search_hint",
]
