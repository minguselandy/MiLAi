from __future__ import annotations

from scripts.run_dg23_s8_quality import (
    ARCHITECTURE_MANIFEST_SHA256,
    DG21_ARCHIVAL_IDENTITY_TEST,
    _dg21_archival_identity_audit,
    _gate_specs,
)


def test_dg23_s8_covers_every_predeclared_quality_lane() -> None:
    specs = {spec.gate_id: spec for spec in _gate_specs()}

    assert set(specs) == {
        "runtime-unit",
        "runtime-contract",
        "context-retrieval-regression",
        "dg23-targeted-evaluation",
        "dg20-dg21-dg22-evaluation-regression",
        "runtime-mypy-strict",
        "dg23-mypy-strict",
        "runtime-ruff",
        "dg23-ruff",
        "runtime-postgresql-integration-security",
        "architecture-validate",
        "architecture-release-lock",
    }
    assert specs["runtime-postgresql-integration-security"].require_database
    assert "tests/integration" in specs[
        "runtime-postgresql-integration-security"
    ].command
    assert "tests/security" in specs[
        "runtime-postgresql-integration-security"
    ].command
    assert ARCHITECTURE_MANIFEST_SHA256 in specs["architecture-release-lock"].command


def test_dg23_s8_evaluation_gates_include_target_and_predecessors() -> None:
    specs = {spec.gate_id: spec for spec in _gate_specs()}

    assert any(
        value.endswith("test_dg23_s7_matched_reader.py")
        for value in specs["dg23-targeted-evaluation"].command
    )
    prior = specs["dg20-dg21-dg22-evaluation-regression"].command
    assert any("test_dg20" in value for value in prior)
    assert any("test_dg21" in value for value in prior)
    assert any("test_dg22" in value for value in prior)
    assert prior[-2:] == ("--deselect", DG21_ARCHIVAL_IDENTITY_TEST)


def test_dg23_s8_separates_archival_integrity_from_live_behavior() -> None:
    audit = _dg21_archival_identity_audit()

    assert audit["passed"] is True
    assert audit["sealed_artifacts_unchanged"] is True
    assert audit["source_drift_count"] >= 1
    assert audit["behavior_regression_covered_by_remaining_tests"] is True
