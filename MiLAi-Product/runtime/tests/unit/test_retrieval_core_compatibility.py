from milai.application import retrieval
from milai.application.retrieval_core import candidates, policy


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
