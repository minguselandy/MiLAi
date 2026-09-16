from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scripts import dg13u_u1_aggregate as aggregate
from scripts import dg13u_u1_openworker as runner

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs/runbooks/dg13u-u1-operator.md"
PYTHON = ROOT / "runtime/.venv/bin/python"


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _bash_blocks(text: str) -> str:
    return "\n".join(re.findall(r"```bash\n(.*?)\n```", text, re.DOTALL))


def _normalized(text: str) -> str:
    return " ".join(text.split())


def test_runbook_uses_current_execution_packaging_and_review_clis() -> None:
    text = _text()
    runner_help = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/dg13u_u1_openworker.py"), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    matrix_help = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/dg13u_u1_matrix.py"), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    cleanup_help = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/dg13u_u1_cleanup.py"), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    bundle_help = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/dg13u_u1_bundle.py"), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    review_help = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/dg13u_u1_review.py"), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    test_gate_help = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/dg13u_u1_test_gate.py"), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    for option in (
        "--case-id",
        "--list-cases",
        "--run-id",
        "--execute-local",
        "--env-file",
    ):
        assert option in runner_help
        assert option in text
    for option in ("--batch-id", "--env-file", "--output"):
        assert option in matrix_help
        assert option in text
    for option in ("--plan", "--run-id", "--env-file", "--execute-local"):
        assert option in cleanup_help
        assert option in text
    for option in ("--aggregate", "--report", "--artifact", "--output-dir"):
        assert option in bundle_help
        assert option in text
    for option in (
        "--bundle",
        "--expected-manifest-sha256",
        "--attempt-root",
        "--attempt-id",
    ):
        assert option in review_help
        assert option in text
    assert "--run-root" in test_gate_help and "--run-root" in text
    assert "runtime/.venv/bin/python scripts/dg13u_u1_openworker.py" in text
    assert "runtime/.venv/bin/python scripts/dg13u_u1_matrix.py" in text
    assert "runtime/.venv/bin/python scripts/dg13u_u1_cleanup.py" in text
    assert "runtime/.venv/bin/python scripts/dg13u_u1_bundle.py" in text
    assert "runtime/.venv/bin/python scripts/dg13u_u1_review.py" in text
    assert "runtime/.venv/bin/python scripts/dg13u_u1_test_gate.py" in text
    assert "./integrations/openworker-mcp/build_dg13u_u1_image.sh" in text
    assert "milai-openworker:dg13u-u1-current-local" in text


def test_runbook_freezes_current_source_parity_without_claiming_e2e() -> None:
    text = _text()
    normalized = _normalized(text)
    missing = sorted(set(runner.CASES) - set(runner._IMPLEMENTED_REAL_CASES))

    assert len(runner.CASES) == len(aggregate.REQUIRED_CASE_IDS) == 37
    assert len(runner._IMPLEMENTED_REAL_CASES) == 37
    assert not missing
    assert (
        "37 advertised cases; 37 source implementations; 0 implementation-gap selectors"
        in normalized
    )
    assert (
        "37 advertised cases; 8 real smoke implementations; 29 blocked cases"
        not in normalized
    )
    assert "Twenty-nine advertised cases" not in text
    assert "FULL_MATRIX_IMPLEMENTATION_DRIFT" in text
    assert "set(runner.CASES) != set(runner._IMPLEMENTED_REAL_CASES)" in text
    assert "FULL_MATRIX_IMPLEMENTATION_READY" in text
    assert "source implementation parity only" in normalized
    assert "Product usability is earned only by a current" in normalized
    assert '--batch-id "$DG13U_BATCH_ID"' in text
    assert '--output "$DG13U_AGGREGATE"' in text


def test_runbook_keeps_cleanup_provider_and_data_boundaries_fail_closed() -> None:
    text = _text()
    normalized = _normalized(text)
    bash = _bash_blocks(text)

    for phrase in (
        "synthetic or independently de-identified",
        "automatic retry is prohibited",
        "existing vLLM",
        "cleanup-receipt.json",
        "single failure",
        "provider native request ID",
        "formal labels",
    ):
        assert phrase in normalized
    assert "<run-id>" not in text
    assert "<case-id>" not in text
    assert "TODO" not in text
    assert "TBD" not in text
    assert not re.search(
        r"(?m)^\s*(docker\s+(stop|restart|kill|rm)|kill\s|pkill\s|systemctl\s)",
        bash,
    )
    assert 'runtime/.venv/bin/python - "$DG13U_REPORT"' in bash
    assert "external_lifecycle_mutations" in bash
    assert "existing_vllm_preserved" in bash
    assert "TMPDIR=/dev/shm" in bash
    assert 'TMPDIR="/dev/shm/$DG13U_TEST_ID/t"' in bash
    subprocess.run(
        ["bash", "-n"],
        input=bash,
        check=True,
        capture_output=True,
        text=True,
    )


def test_runbook_names_the_fail_closed_artifact_release_decision() -> None:
    text = _text()
    normalized = _normalized(text)

    assert "scripts/dg13u_u1_cleanup.py" in text
    assert "scripts/dg13u_u1_matrix.py" in text
    assert "--plan" in text and "--execute-local" in text
    assert "--batch-id" in text and "--output" in text
    assert "Current single-case CLI capability" in text
    assert "Current full-matrix CLI capability" in text
    assert "PRODUCT NOT USABLE" in text
    assert "RELEASE STATUS IS ARTIFACT-DERIVED" in text
    assert "U1-G0" in text and "U1-G5" in text
    assert "independent model review" in normalized
    assert "no fabrication" in normalized
    assert "no hidden retry" in normalized
    assert "preserved existing vLLM" in normalized
    assert "gpt-5.6-sol" in text and "xhigh" in text
    assert "entries_sha256" in text
    assert "26-file U1 inventory plus its one U0 support owning test" in normalized
    assert "27-file command" in normalized
    assert 'receipt["source_revalidation"]["status"] == "PASS"' in text
    assert "post_source_inputs_sha256" in text
    assert '"${DG13U_TEST_GATE_SOURCES[@]}"' in text
    assert "test-gate-sources/" in text
    assert "matching bytes and SHA-256 for every receipt source row" in normalized
    assert "attempt_count" in text and "automatic_retries" in text
    for artifact, schema in aggregate.REQUIRED_ARTIFACT_SCHEMAS.items():
        assert artifact in text
        assert schema in text
    assert "13 frozen fault cases" in normalized
    assert "fault-execution.json" in text
    assert aggregate.FAULT_EXECUTION_SCHEMA in text
    assert "recovery-resource-plan.json" in text
