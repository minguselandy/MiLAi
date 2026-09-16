from __future__ import annotations

from scripts import build_dg10_inventory


def test_post_sol_inventory_candidate_and_output_are_distinct() -> None:
    assert "candidate.2.13" in build_dg10_inventory.DEFAULT_OUTPUT.name


def test_post_sol_accounting_contract_is_explicit_in_source() -> None:
    source = build_dg10_inventory.Path(build_dg10_inventory.__file__).read_text(
        encoding="utf-8"
    )
    assert '"tier3_known_completed_native_calls": 44' in source
    assert '"tier3_early_diagnostic_completed_native_calls": "UNKNOWN"' in source
    assert '"self_hosted_compute_cost": "UNAVAILABLE_NOT_ZERO"' in source
    assert '"cost": "UNAVAILABLE"' in source
