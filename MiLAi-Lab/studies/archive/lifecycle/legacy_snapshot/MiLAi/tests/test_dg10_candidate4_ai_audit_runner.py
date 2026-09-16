from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_dg10_candidate4_ai_audit as runner


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir(mode=0o755)
    for name, raw in {
        "audit-prompt.md": b"audit\n",
        "audit-response.schema.json": b"{}\n",
        "review-manifest.json": b"{}\n",
    }.items():
        path = bundle / name
        path.write_bytes(raw)
        path.chmod(0o444)
    bundle.chmod(0o555)
    return bundle


def test_operator_interruption_writes_fail_closed_terminal_receipt(
    tmp_path: Path, monkeypatch: object
) -> None:
    def run(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(returncode=0, stdout=b"codex-cli test\n")

    def interrupt(**_kwargs: object) -> object:
        raise KeyboardInterrupt

    attempts = tmp_path / "attempts"
    attempts.mkdir(mode=0o700)
    codex = tmp_path / "codex"
    codex.write_bytes(b"test executable\n")
    codex.chmod(0o555)
    policy = {
        "authority_uid": attempts.stat().st_uid,
        "authority_gid": attempts.stat().st_gid,
        "protected_attempt_roots": {"R0_R2_PRIMARY": str(attempts)},
    }
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(runner.provenance, "load_authority_policy", lambda: policy)
    monkeypatch.setattr(
        runner.provenance,
        "assert_current_authority_process",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(runner.provenance, "pinned_codex", lambda: codex)
    monkeypatch.setattr(
        runner.provenance,
        "codex_child_environment",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(runner.provenance, "execute_pinned_codex", interrupt)
    attempt, returncode = runner.run_audit(
        bundle=_bundle(tmp_path),
        output_root=attempts,
        attempt_id="candidate.4-primary-test",
        timeout_seconds=60,
    )
    process = json.loads((attempt / "process.json").read_text())
    assert returncode == 130
    assert process["termination_reason"] == "OPERATOR_INTERRUPTED"
    assert process["process_exit_code"] == 130
    assert process["output_sha256"] is None
    assert stat.S_IMODE((attempt / "events.jsonl").stat().st_mode) == 0o600
    assert (attempt / "stderr.log").read_bytes().endswith(b"FAIL_CLOSED\n")


def test_legacy_attempt_without_execution_attestation_is_rejected(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(runner.provenance, "load_authority_policy", lambda: {})
    with pytest.raises(
        runner.provenance.AIProvenanceError,
        match="signed execution attestation key drift",
    ):
        runner.provenance.validate_execution_attestation(
            None,
            bundle=tmp_path / "bundle",
            output=tmp_path / "output.json",
            materialized_runner=tmp_path / "runner.py",
            process={},
        )
