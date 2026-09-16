from __future__ import annotations

from scripts.run_dg24_s7_quality import (
    ARCHITECTURE_MANIFEST_SHA256,
    DG21_ARCHIVAL_IDENTITY_TEST,
    FORBIDDEN_PRODUCT_KEYS,
    _gate_specs,
    _recursive_keys,
    _source_continuity_audit,
    _validate_failure_index,
)


def test_s7_covers_every_predeclared_quality_lane() -> None:
    specs = {spec.gate_id: spec for spec in _gate_specs()}

    assert set(specs) == {
        "runtime-unit",
        "runtime-contract",
        "retrieval-trace-behavior-regression",
        "dg24-targeted-evaluation",
        "dg20-dg23-behavioral-regression",
        "runtime-mypy-strict",
        "dg24-mypy-strict",
        "runtime-ruff",
        "dg24-ruff",
        "runtime-postgresql-integration-security",
        "architecture-validate",
        "architecture-release-lock",
    }
    database = specs["runtime-postgresql-integration-security"]
    assert database.require_database
    assert "tests/integration" in database.command
    assert "tests/security" in database.command
    assert ARCHITECTURE_MANIFEST_SHA256 in specs[
        "architecture-release-lock"
    ].command


def test_s7_covers_dg20_through_dg24_without_conflating_archival_identity() -> None:
    specs = {spec.gate_id: spec for spec in _gate_specs()}

    target = specs["dg24-targeted-evaluation"].command
    assert any(value.endswith("test_dg24_scorer.py") for value in target)
    prior = specs["dg20-dg23-behavioral-regression"].command
    for predecessor in ("dg20", "dg21", "dg22", "dg23"):
        assert any(f"test_{predecessor}" in value for value in prior)
    assert prior[-2:] == ("--deselect", DG21_ARCHIVAL_IDENTITY_TEST)


def test_s2_s3_source_continuity_allows_only_official_probe_instrumentation() -> None:
    audit = _source_continuity_audit()

    assert audit["passed"] is True
    assert audit["changed_paths"] == [
        "runtime/src/milai/application/retrieval_audit_probe.py"
    ]
    assert audit["product_behavior_source_drift"] == []


def test_quality_boundary_recursively_detects_gold_keys() -> None:
    value = {"outer": [{"safe": 1}, {"expected_answer": "forbidden"}]}

    assert "expected_answer" in _recursive_keys(value)
    assert FORBIDDEN_PRODUCT_KEYS.intersection(_recursive_keys(value)) == {
        "expected_answer"
    }


def test_failure_index_preserves_unique_failures_without_retry() -> None:
    audit = _validate_failure_index()

    assert audit["passed"] is True
    assert audit["record_count"] == audit["unique_failure_ids"]
    assert audit["record_count"] >= 8
    assert audit["automatic_retry_count"] == 0
