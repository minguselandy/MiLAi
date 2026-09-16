from __future__ import annotations

from scripts import run_dg10_final_quality_state as final_state


def test_final_quality_state_binds_inputs_and_denies_promotion() -> None:
    state = final_state.build_state(final_state._load_inputs())
    assert state["status"] == "EVALUATION_STOPPED_NO_GO_TEST_DENIED"
    assert state["quality_outcome"] == "BELOW_TARGET"
    assert state["full_test_execution"] == "DENIED_NOT_RUN"
    assert state["decision"]["run_full_test"] is False
    assert state["decision"]["promote_local_vllm_mcp_agent_candidate"] is False
    assert state["gate_state"]["BMG-02"].startswith("NO_GO")
    assert state["gate_state"]["BMG-03"].startswith("NO_GO")
    assert state["gate_state"]["BMG-04"].startswith("NO_GO")


def test_tier3_remains_nonrelease_and_milai_below_rag() -> None:
    state = final_state.build_state(final_state._load_inputs())
    tier3 = state["scoring_tiers"]["tier_3_same_vllm"]
    assert tier3["release_input"] is False
    assert tier3["native_judge_calls"] == 36
    assert tier3["milai_minus_naive_rag"] < 0
    assert tier3["may_override_tier_1"] is False


def test_tier2_is_packaged_but_waiting_for_two_humans() -> None:
    state = final_state.build_state(final_state._load_inputs())
    tier2 = state["scoring_tiers"]["tier_2_blinded_human"]
    assert tier2["package_ready"] is True
    assert tier2["required_independent_humans"] == 2
    assert tier2["completed_independent_humans"] == 0
    assert tier2["audit_complete"] is False
