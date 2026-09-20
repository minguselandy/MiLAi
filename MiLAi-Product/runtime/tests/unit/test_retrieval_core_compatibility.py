from milai.application import retrieval
from milai.application.retrieval_core import candidates, policy, temporal


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
