from milai.application import memory_context
from milai.application.memory_context_core import (
    activation,
    common,
    compiler,
    contracts,
    provenance,
    receipts,
    rendering,
    semantics,
    trace,
    units,
    windows,
)


def test_memory_context_facade_preserves_compiler() -> None:
    assert memory_context.MemoryContextCompiler is compiler.MemoryContextCompiler


def test_memory_context_facade_preserves_activation_helpers() -> None:
    assert memory_context._TERM is activation._TERM
    assert memory_context._VALUE is activation._VALUE
    assert memory_context._MULTI_SESSION is activation._MULTI_SESSION
    assert memory_context._LOCAL_CONTEXT is activation._LOCAL_CONTEXT
    assert memory_context._QUERY_STOPWORDS is activation._QUERY_STOPWORDS
    assert (
        memory_context._conditional_activation_thresholds
        is activation._conditional_activation_thresholds
    )
    assert memory_context._admissible_conditional_gain is activation._admissible_conditional_gain
    assert memory_context._stable_evidence_views is activation._stable_evidence_views
    assert memory_context._normalized_unit_semantics is activation._normalized_unit_semantics
    assert memory_context._breadth_first_binding_spans is activation._breadth_first_binding_spans
    assert memory_context._canonical_item_identity is activation._canonical_item_identity
    assert memory_context._canonical_item_sort_key is activation._canonical_item_sort_key
    assert memory_context._fallback_decision_snapshot is activation._fallback_decision_snapshot
    assert memory_context._candidate_item_sort_key is activation._candidate_item_sort_key
    assert memory_context._required_requirement_ids is activation._required_requirement_ids
    assert memory_context._without_presentation_budget is activation._without_presentation_budget
    assert memory_context._local_context_activation is activation._local_context_activation
    assert memory_context._evidence_views is activation._evidence_views
    assert memory_context._derived_operand_views is activation._derived_operand_views
    assert memory_context._query_terms is activation._query_terms
    assert memory_context._answer_signal is activation._answer_signal
    assert memory_context._legacy_session_identity is activation._legacy_session_identity
    assert memory_context._structured_source_context is activation._structured_source_context


def test_memory_context_facade_preserves_compilation_contracts() -> None:
    assert memory_context.ContextCompilation is contracts.ContextCompilation
    assert memory_context.ContextPlanCompilation is contracts.ContextPlanCompilation
    assert memory_context.EvidenceAdjacencyReader is contracts.EvidenceAdjacencyReader
    assert memory_context.ContextTokenAccountingError is contracts.ContextTokenAccountingError


def test_memory_context_facade_preserves_common_helpers() -> None:
    assert memory_context._string_values is common._string_values
    assert memory_context._estimated_tokens is common._estimated_tokens
    assert memory_context._authority_class is common._authority_class
    assert memory_context._positions is common._positions
    assert memory_context._sufficiency_status is common._sufficiency_status
    assert memory_context._unique is common._unique
    assert memory_context._sha256 is common._sha256


def test_memory_context_facade_preserves_semantic_helpers() -> None:
    assert memory_context._OPAQUE_READER_KEYS is semantics._OPAQUE_READER_KEYS
    assert memory_context._query_ir_operator_family is semantics._query_ir_operator_family
    assert (
        memory_context._query_ir_has_temporal_constraint
        is semantics._query_ir_has_temporal_constraint
    )
    assert memory_context._query_ir_enumerates_members is semantics._query_ir_enumerates_members
    assert memory_context._reader_semantic_value is semantics._reader_semantic_value
    assert memory_context._validated_operand is semantics._validated_operand


def test_memory_context_facade_preserves_provenance_helpers() -> None:
    assert memory_context._required_sources is provenance._required_sources
    assert memory_context._operand_sources is provenance._operand_sources
    assert memory_context._provenance_values is provenance._provenance_values
    assert memory_context._canonical_item_sources is provenance._canonical_item_sources
    assert memory_context._canonical_sources is provenance._canonical_sources


def test_memory_context_facade_preserves_unit_helpers() -> None:
    assert memory_context._reader_unit is units._reader_unit
    assert memory_context._status_unit_text is units._status_unit_text
    assert memory_context._render_reader_units is units._render_reader_units
    assert memory_context._render_infeasible_context is units._render_infeasible_context


def test_memory_context_facade_preserves_window_helpers() -> None:
    assert memory_context._WORKSPACE_WRAPPER_TERMS is windows._WORKSPACE_WRAPPER_TERMS
    assert memory_context._SOFT_WINDOW_TOKEN_CAP == windows._SOFT_WINDOW_TOKEN_CAP
    assert memory_context._SOFT_SESSION_DIVERSITY_PREFIX == windows._SOFT_SESSION_DIVERSITY_PREFIX
    assert memory_context._build_windows is windows._build_windows
    assert memory_context._bounded_window_members is windows._bounded_window_members
    assert memory_context._session_landmark is windows._session_landmark
    assert memory_context._linked_context_neighbor is windows._linked_context_neighbor
    assert memory_context._marginal_window_order is windows._marginal_window_order
    assert (
        memory_context._instance_preserving_window_order
        is windows._instance_preserving_window_order
    )
    assert (
        memory_context._marginal_conditional_unit_order is windows._marginal_conditional_unit_order
    )
    assert memory_context._workspace_candidate_provenance is windows._workspace_candidate_provenance
    assert memory_context._workspace_target_hints is windows._workspace_target_hints
    assert memory_context._order_windows is windows._order_windows
    assert memory_context._speaker_neighbor is windows._speaker_neighbor
    assert memory_context._turn_sort is windows._turn_sort


def test_memory_context_facade_preserves_rendering_helpers() -> None:
    assert memory_context._render_context is rendering._render_context
    assert memory_context._derived_context is rendering._derived_context
    assert memory_context._reader_derived_value is rendering._reader_derived_value
    assert memory_context._reader_derived_completeness is rendering._reader_derived_completeness
    assert memory_context._fit_window is rendering._fit_window
    assert memory_context._reserve_required_windows is rendering._reserve_required_windows
    assert memory_context._fit_windows_together is rendering._fit_windows_together
    assert memory_context._fit_derived_with_windows is rendering._fit_derived_with_windows
    assert memory_context._fit_derived is rendering._fit_derived
    assert memory_context._focused_excerpt is rendering._focused_excerpt
    assert memory_context._excerpt_focus is rendering._excerpt_focus
    assert memory_context._excerpt_at is rendering._excerpt_at
    assert memory_context._open_issue_ids is rendering._open_issue_ids


def test_memory_context_facade_preserves_receipt_helpers() -> None:
    assert memory_context._RECEIPT_WINDOW_HEADER is receipts._RECEIPT_WINDOW_HEADER
    assert memory_context._RECEIPT_ALIAS_HEADER is receipts._RECEIPT_ALIAS_HEADER
    assert memory_context._evidence_receipt is receipts._evidence_receipt
    assert memory_context._receipt_mapping is receipts._receipt_mapping
    assert memory_context._semantic_context_material is receipts._semantic_context_material
    assert memory_context._requires_multiple_sessions is receipts._requires_multiple_sessions


def test_memory_context_facade_preserves_trace_helpers() -> None:
    assert memory_context._acquired_candidate_trace is trace._acquired_candidate_trace
    assert memory_context._reader_boundary_trace is trace._reader_boundary_trace
    assert memory_context._bound_evidence_trace is trace._bound_evidence_trace
    assert memory_context._admitted_evidence_trace is trace._admitted_evidence_trace
    assert memory_context._reader_visible_trace is trace._reader_visible_trace
    assert memory_context._evidence_lifecycle_trace is trace._evidence_lifecycle_trace
