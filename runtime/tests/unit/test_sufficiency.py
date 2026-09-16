"""Stable compatibility entrypoint for direct Sufficiency regressions."""

from runtime.tests.unit.test_dg17_sufficiency import (
    test_ambiguous_text_with_access_plan_remains_fail_closed,
    test_exact_state_miss_uses_query_ir_requirement_identity,
    test_q1_contract_cannot_encode_candidate_presence_as_completeness,
    test_q1_nonempty_candidates_do_not_complete_an_operator_query,
)

__all__ = [
    "test_ambiguous_text_with_access_plan_remains_fail_closed",
    "test_exact_state_miss_uses_query_ir_requirement_identity",
    "test_q1_contract_cannot_encode_candidate_presence_as_completeness",
    "test_q1_nonempty_candidates_do_not_complete_an_operator_query",
]
