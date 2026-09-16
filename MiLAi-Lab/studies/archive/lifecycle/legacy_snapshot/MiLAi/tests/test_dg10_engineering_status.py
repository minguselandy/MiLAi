from __future__ import annotations

from scripts import build_dg10_engineering_status as status


def test_engineering_status_preserves_blockers_and_never_self_accepts() -> None:
    report = status.build_status()
    assert report["status"] == "BLOCKED_EXTERNAL_ACCEPTANCE_AND_MODEL_RUNS"
    assert report["independent_acceptance"] is False
    assert report["model_authorization"]["provider_requests"] == 0
    assert report["real_runtime_mcp_fixture"]["known_completed_mcp_calls"] == 3
    assert report["retained_pre_ledger_disclosure"]["unknown_early_diagnostics"] == 5
    assert report["full_test_authorized"] is False
    assert report["release_authorized"] is False
    assert "R3_agent_terminal_gate" in report["missing_terminal_outputs"]
