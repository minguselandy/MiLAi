from pathlib import Path

from scripts.run_gdpm_b0_context_truth import (
    COMPUTE_CONTRACT_PATHS,
    ROOT,
    _artifact_path,
    _run_lock,
)


def test_artifact_path_supports_repository_and_external_output_roots() -> None:
    assert _artifact_path(ROOT / "var" / "gdpm" / "trace.json") == (
        "var/gdpm/trace.json"
    )
    assert _artifact_path(Path("/tmp/gdpm/trace.json")) == (
        "/tmp/gdpm/trace.json"
    )


def test_run_lock_binds_runner_tests_and_compute_contract() -> None:
    lock = _run_lock("fixture-run", "2026-08-31T00:00:00Z")

    assert "scripts/run_gdpm_b0_context_truth.py" in lock["code_artifacts"]
    assert "tests/test_gdpm_b0_runner.py" in lock["code_artifacts"]
    assert set(lock["compute_contract"]) == set(COMPUTE_CONTRACT_PATHS)
    assert lock["benchmark_case_manifest"] == []
    assert lock["scope"]["benchmark_cases_authorized"] is False
    assert lock["scope"]["reader_answer_judge_calls_authorized"] is False
