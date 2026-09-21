from milai.application import retrieval
from milai.application.retrieval_core import (
    acquisition,
    assembly,
    candidates,
    operators,
    policy,
    selection,
    temporal,
)


def test_retrieval_facade_preserves_extracted_helper_imports() -> None:
    assert retrieval._merge_candidates is candidates._merge_candidates
    assert retrieval._deduplicate_evidence is candidates._deduplicate_evidence
    assert retrieval._diversify_evidence_by_subject is candidates._diversify_evidence_by_subject
    assert retrieval._rank_evidence_turns is candidates._rank_evidence_turns
    assert retrieval._result_identity is candidates._result_identity
    assert retrieval._retrieval_policy is policy._retrieval_policy
    assert retrieval._candidate_pool_floor is policy._candidate_pool_floor
    assert retrieval._remaining_timeout_ms is policy._remaining_timeout_ms
    assert retrieval._deadline_exhausted is policy._deadline_exhausted


def test_retrieval_facade_preserves_temporal_helper_imports() -> None:
    assert retrieval._binary_event_anchor_terms is temporal._binary_event_anchor_terms
    assert retrieval._binary_event_anchor_queries is temporal._binary_event_anchor_queries
    assert retrieval._binary_anchor_cover is temporal._binary_anchor_cover
    assert retrieval._relative_point_target is temporal._relative_point_target
    assert retrieval._relative_point_cover is temporal._relative_point_cover
    assert retrieval._temporal_tokens is temporal._temporal_tokens
    assert retrieval._temporal_text is temporal._temporal_text
    assert retrieval._temporal_timestamp is temporal._temporal_timestamp
    assert retrieval._temporal_subject_indices is temporal._temporal_subject_indices
    assert retrieval._relative_target is temporal._relative_target
    assert retrieval._rerank_by_reference is temporal._rerank_by_reference
    assert retrieval._relative_event_dates is temporal._relative_event_dates
    assert retrieval._intent_tokens is temporal._intent_tokens
    assert retrieval._relative_event_intent_overlap is temporal._relative_event_intent_overlap
    assert retrieval._relative_event_distance is temporal._relative_event_distance
    assert retrieval._temporal_rerank is temporal._temporal_rerank


def test_retrieval_facade_preserves_selection_helper_imports() -> None:
    assert retrieval._apply_context_budget is selection._apply_context_budget
    assert retrieval._context_candidate_budget is selection._context_candidate_budget
    assert retrieval._context_budget_view is selection._context_budget_view
    assert retrieval._set_cover_text is selection._set_cover_text
    assert retrieval._set_cover_tokens is selection._set_cover_tokens
    assert retrieval._weighted_set_cover_select is selection._weighted_set_cover_select
    assert retrieval._mmr_select is selection._mmr_select
    assert retrieval._mmr_tokens is selection._mmr_tokens
    assert retrieval._jaccard is selection._jaccard


def test_retrieval_facade_preserves_acquisition_helper_imports() -> None:
    assert retrieval._merge_evidence_results is acquisition._merge_evidence_results
    assert retrieval._formation_candidate_results is acquisition._formation_candidate_results
    assert retrieval._union_formation_and_raw is acquisition._union_formation_and_raw
    assert (
        retrieval._acquisition_candidate_envelopes
        is acquisition._acquisition_candidate_envelopes
    )
    assert retrieval._acquisition_reference_material is acquisition._acquisition_reference_material
    assert retrieval._use_acquisition_composition is acquisition._use_acquisition_composition


def test_retrieval_facade_preserves_operator_helper_imports() -> None:
    assert (
        retrieval._explicit_compound_subject_matches
        is operators._explicit_compound_subject_matches
    )
    assert retrieval._state_count_cover is operators._state_count_cover
    assert (
        retrieval._execute_operator_with_accepted_inputs
        is operators._execute_operator_with_accepted_inputs
    )
    assert retrieval._operator_support_refs is operators._operator_support_refs


def test_retrieval_facade_preserves_assembly_helper_imports() -> None:
    assert retrieval._assemble_results is assembly._assemble_results
    assert retrieval._response_body is assembly._response_body
    assert retrieval._contains_evidence_observation is assembly._contains_evidence_observation
    assert retrieval._projection_state_payload is assembly._projection_state_payload
    assert retrieval._decision_snapshot is assembly._decision_snapshot
    assert retrieval._requirement_evidence_set is assembly._requirement_evidence_set
    assert retrieval._decision_requirement_ids is assembly._decision_requirement_ids
    assert (
        retrieval._decision_accepted_evidence_ids
        is assembly._decision_accepted_evidence_ids
    )
    assert retrieval._accepted_binding_spans is assembly._accepted_binding_spans
    assert (
        retrieval._binding_span_provenance_order
        is assembly._binding_span_provenance_order
    )
    assert retrieval._result_evidence_ids is assembly._result_evidence_ids
