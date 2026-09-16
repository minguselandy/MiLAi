from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from scripts import dg13u_u1_review as review


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "bundle"
    root.mkdir(mode=0o700)
    aggregate = root / "aggregate" / "aggregate.json"
    aggregate.parent.mkdir(mode=0o700)
    aggregate_raw = _canonical({"schema": "synthetic.aggregate.v1", "status": "PASS"})
    aggregate.write_bytes(aggregate_raw)
    aggregate.chmod(0o600)
    files: list[dict[str, object]] = [
        {
            "bytes": len(aggregate_raw),
            "case_id": None,
            "path": "aggregate/aggregate.json",
            "run_id": None,
            "schema": "synthetic.aggregate.v1",
            "sha256": hashlib.sha256(aggregate_raw).hexdigest(),
            "source_kind": "AGGREGATE",
        }
    ]
    for case_id in review.REQUIRED_CASE_IDS:
        run_id = f"synthetic-{case_id.casefold()}"
        report_relative = f"reports/{case_id}--{run_id}.json"
        report_raw = _canonical(
            {"schema": "synthetic.report.v1", "status": "PASS", "case_id": case_id}
        )
        report_path = root / report_relative
        report_path.parent.mkdir(mode=0o700, exist_ok=True)
        report_path.write_bytes(report_raw)
        report_path.chmod(0o600)
        files.append(
            {
                "bytes": len(report_raw),
                "case_id": case_id,
                "path": report_relative,
                "run_id": run_id,
                "schema": "synthetic.report.v1",
                "sha256": hashlib.sha256(report_raw).hexdigest(),
                "source_kind": "RUN_REPORT",
            }
        )
        for index in range(review.REQUIRED_RUN_ARTIFACTS_PER_CASE):
            artifact_relative = f"runs/{case_id}--{run_id}/artifact-{index}.json"
            artifact_raw = _canonical(
                {"schema": "synthetic.artifact.v1", "status": "PASS", "index": index}
            )
            artifact_path = root / artifact_relative
            artifact_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            artifact_path.write_bytes(artifact_raw)
            artifact_path.chmod(0o600)
            files.append(
                {
                    "bytes": len(artifact_raw),
                    "case_id": case_id,
                    "path": artifact_relative,
                    "run_id": run_id,
                    "schema": "synthetic.artifact.v1",
                    "sha256": hashlib.sha256(artifact_raw).hexdigest(),
                    "source_kind": "RUN_ARTIFACT",
                }
            )
    manifest = {
        "schema": review.BUNDLE_SCHEMA,
        "status": "PASS",
        "release_label": "LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE",
        "release_label_earned": True,
        "input_mode": "EXPLICIT_PATHS_ONLY_NO_DISCOVERY",
        "network_calls": 0,
        "resource_starts": 0,
        "reruns": 0,
        "gates": {name: "PASS" for name in review.GATE_NAMES},
        "aggregate_sha256": hashlib.sha256(aggregate_raw).hexdigest(),
        "counts": {
            "aggregate": 1,
            "reports": len(review.REQUIRED_CASE_IDS),
            "run_artifacts": len(review.REQUIRED_CASE_IDS)
            * review.REQUIRED_RUN_ARTIFACTS_PER_CASE,
            "supplemental_artifacts": 0,
        },
        "entries_sha256": hashlib.sha256(_canonical(files)).hexdigest(),
        "files": files,
        "secret_scan": {
            "status": "PASS",
            "files_scanned": len(files),
            "raw_secret_persisted": False,
        },
    }
    raw = _canonical(manifest)
    (root / "manifest.json").write_bytes(raw)
    (root / "manifest.json").chmod(0o600)
    return root, hashlib.sha256(raw).hexdigest()


def _codex(tmp_path: Path) -> Path:
    path = tmp_path / "codex"
    path.write_bytes(b"synthetic fixed executable\n")
    path.chmod(0o555)
    return path


def _response(manifest_sha256: str, verdict: str = "PASS") -> dict[str, object]:
    return {
        "schema": "milai.dg13u.u1-review-response.v1",
        "review_scope": "DG13U_U1_RELEASE_BUNDLE",
        "verdict": verdict,
        "summary": "The synthetic bundle evidence was reviewed.",
        "open_findings": [],
        "missing_evidence": [],
        "reviewed_manifest_sha256": manifest_sha256,
    }


def _successful_executor(response: dict[str, object], calls: list[list[str]]):
    def execute(
        command: list[str],
        _prompt: bytes,
        _timeout: int,
        _environment: dict[str, str],
    ) -> review.ExecutionResult:
        calls.append(command)
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_bytes(_canonical(response))
        executable = Path(command[0])
        return review.ExecutionResult(
            returncode=0,
            termination_reason="COMPLETED",
            stdout=b'{"type":"turn.completed"}\n',
            stderr=b"",
            child_pid=401,
            proc_exe_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            proc_cmdline_sha256=hashlib.sha256(review._argv_raw(command)).hexdigest(),
        )

    return execute


def test_command_freezes_supported_sol_xhigh_read_only_flags(tmp_path: Path) -> None:
    command = review.build_command(
        codex=tmp_path / "codex",
        bundle=tmp_path / "bundle",
        output=tmp_path / "attempt/model-output.json",
        response_schema=review.RESPONSE_SCHEMA_PATH,
    )

    assert command[:4] == [
        str(tmp_path / "codex"),
        "--ask-for-approval",
        "never",
        "exec",
    ]
    assert command.count("exec") == 1
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="xhigh"' in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    for flag in (
        "--strict-config",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--output-schema",
        "--json",
        "--output-last-message",
    ):
        assert flag in command
    assert not {"--search", "resume", "--approve-for-me"}.intersection(command)
    assert command[-1] == "-"


def test_one_mock_attempt_materializes_hash_attested_json_and_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest_sha256 = _bundle(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        review,
        "_execute_once",
        _successful_executor(_response(manifest_sha256), calls),
    )

    attempt, returncode = review.run_review(
        bundle=bundle.resolve(),
        expected_manifest_sha256=manifest_sha256,
        attempt_root=(tmp_path / "attempt-001").resolve(),
        attempt_id="dg13u-u1-review-primary-001",
        timeout_seconds=60,
        codex=_codex(tmp_path),
    )

    assert returncode == 0
    assert len(calls) == 1
    assert json.loads((attempt / "review.json").read_text())["verdict"] == "PASS"
    assert "Verdict: `PASS`" in (attempt / "review.md").read_text()
    assert json.loads((attempt / "terminal.json").read_text()) == {
        "attempt_id": "dg13u-u1-review-primary-001",
        "model_response_valid": True,
        "reason_code": "REVIEW_SCHEMA_VALIDATED",
        "reviewed_manifest_sha256": manifest_sha256,
        "schema": "milai.dg13u.u1-review-terminal.v1",
        "status": "COMPLETED",
        "verdict": "PASS",
        "verdict_origin": "MODEL_SCHEMA_VALIDATED",
    }
    process = json.loads((attempt / "process.json").read_text())
    assert process["attempt_count"] == 1
    assert process["automatic_retries"] == 0
    assert process["model"] == "gpt-5.6-sol"
    assert process["reasoning_effort"] == "xhigh"
    assert process["approval_policy"] == "never"
    assert process["sandbox"] == "read-only"
    assert process["ephemeral"] is True
    assert process["ignore_user_config"] is True
    assert process["ignore_rules"] is True
    assert (
        process["argv_sha256"] == hashlib.sha256(review._argv_raw(calls[0])).hexdigest()
    )
    assert process["inputs"]["bundle_manifest_sha256"] == manifest_sha256
    assert (
        process["outputs"]["review_json"]["sha256"]
        == hashlib.sha256((attempt / "review.json").read_bytes()).hexdigest()
    )
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in attempt.iterdir()
        if path.is_file()
    )


def test_pass_with_open_p1_fails_local_schema_and_terminal_is_honest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest_sha256 = _bundle(tmp_path)
    response = _response(manifest_sha256)
    response["open_findings"] = [
        {
            "finding_id": "DG13U-U1-RV-001",
            "severity": "P1",
            "title": "Open safety defect",
            "evidence": ["aggregate/aggregate.json:status"],
            "required_action": "Close the defect and rerun evidence.",
        }
    ]
    calls: list[list[str]] = []
    monkeypatch.setattr(review, "_execute_once", _successful_executor(response, calls))

    attempt, returncode = review.run_review(
        bundle=bundle.resolve(),
        expected_manifest_sha256=manifest_sha256,
        attempt_root=(tmp_path / "attempt-invalid-pass").resolve(),
        attempt_id="dg13u-u1-review-primary-002",
        timeout_seconds=60,
        codex=_codex(tmp_path),
    )

    assert returncode == 2
    assert len(calls) == 1
    assert not (attempt / "review.json").exists()
    terminal = json.loads((attempt / "terminal.json").read_text())
    assert terminal["status"] == "FAIL_CLOSED"
    assert terminal["verdict"] == "BLOCKED_BY_MISSING_EVIDENCE"
    assert terminal["verdict_origin"] == "RUNNER_FAIL_CLOSED"
    assert terminal["reason_code"] == "OUTPUT_PASS_WITH_OPEN_P0_P1"


def test_revise_requires_and_preserves_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest_sha256 = _bundle(tmp_path)
    response = _response(manifest_sha256, "REVISE")
    response["open_findings"] = [
        {
            "finding_id": "DG13U-U1-RV-001",
            "severity": "P2",
            "title": "Evidence wording needs correction",
            "evidence": ["aggregate/aggregate.json:status"],
            "required_action": "Correct the unsupported wording.",
        }
    ]
    calls: list[list[str]] = []
    monkeypatch.setattr(review, "_execute_once", _successful_executor(response, calls))

    attempt, returncode = review.run_review(
        bundle=bundle.resolve(),
        expected_manifest_sha256=manifest_sha256,
        attempt_root=(tmp_path / "attempt-revise").resolve(),
        attempt_id="dg13u-u1-review-primary-003",
        timeout_seconds=60,
        codex=_codex(tmp_path),
    )

    assert returncode == 0
    assert json.loads((attempt / "terminal.json").read_text())["verdict"] == "REVISE"
    assert "DG13U-U1-RV-001" in (attempt / "review.md").read_text()


@pytest.mark.parametrize("drift", ["manifest_sha", "extra_file", "symlink"])
def test_bundle_substitution_and_closure_drift_fail_before_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    bundle, manifest_sha256 = _bundle(tmp_path)
    expected = manifest_sha256
    if drift == "manifest_sha":
        expected = "0" * 64
    elif drift == "extra_file":
        (bundle / "unbound.json").write_text("{}\n")
        (bundle / "unbound.json").chmod(0o600)
    else:
        (bundle / "link").symlink_to(bundle / "manifest.json")
    called = False

    def forbidden(*_args: object, **_kwargs: object) -> review.ExecutionResult:
        nonlocal called
        called = True
        raise AssertionError("model must not run")

    monkeypatch.setattr(review, "_execute_once", forbidden)
    with pytest.raises(review.ReviewRunError):
        review.run_review(
            bundle=bundle.resolve(),
            expected_manifest_sha256=expected,
            attempt_root=(tmp_path / f"attempt-{drift}").resolve(),
            attempt_id="dg13u-u1-review-primary-004",
            timeout_seconds=60,
            codex=_codex(tmp_path),
        )
    assert called is False


def test_bundle_entries_sha256_drift_fails_before_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, _manifest_sha256 = _bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["entries_sha256"] = "0" * 64
    manifest_raw = _canonical(manifest)
    manifest_path.write_bytes(manifest_raw)
    expected = hashlib.sha256(manifest_raw).hexdigest()
    called = False

    def forbidden(*_args: object, **_kwargs: object) -> review.ExecutionResult:
        nonlocal called
        called = True
        raise AssertionError("model must not run")

    monkeypatch.setattr(review, "_execute_once", forbidden)
    with pytest.raises(review.ReviewRunError, match="entries SHA-256 binding mismatch"):
        review.run_review(
            bundle=bundle.resolve(),
            expected_manifest_sha256=expected,
            attempt_root=(tmp_path / "attempt-entries-drift").resolve(),
            attempt_id="dg13u-u1-review-primary-008",
            timeout_seconds=60,
            codex=_codex(tmp_path),
        )
    assert called is False


def test_nonzero_model_process_is_one_attempt_with_zero_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest_sha256 = _bundle(tmp_path)
    calls = 0

    def failed(
        command: list[str],
        _prompt: bytes,
        _timeout: int,
        _environment: dict[str, str],
    ) -> review.ExecutionResult:
        nonlocal calls
        calls += 1
        return review.ExecutionResult(
            returncode=124,
            termination_reason="TIMEOUT",
            stdout=b"",
            stderr=b"fail closed\n",
            child_pid=402,
            proc_exe_sha256=hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
            proc_cmdline_sha256=hashlib.sha256(review._argv_raw(command)).hexdigest(),
        )

    monkeypatch.setattr(review, "_execute_once", failed)
    attempt, returncode = review.run_review(
        bundle=bundle.resolve(),
        expected_manifest_sha256=manifest_sha256,
        attempt_root=(tmp_path / "attempt-timeout").resolve(),
        attempt_id="dg13u-u1-review-primary-005",
        timeout_seconds=60,
        codex=_codex(tmp_path),
    )

    assert calls == 1
    assert returncode == 124
    process = json.loads((attempt / "process.json").read_text())
    assert process["attempt_count"] == 1
    assert process["automatic_retries"] == 0
    assert process["termination_reason"] == "TIMEOUT"
    assert (
        json.loads((attempt / "terminal.json").read_text())["status"] == "FAIL_CLOSED"
    )


def test_bundle_mutation_during_mock_attempt_fails_closed_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest_sha256 = _bundle(tmp_path)
    calls = 0

    def mutate(
        command: list[str],
        _prompt: bytes,
        _timeout: int,
        _environment: dict[str, str],
    ) -> review.ExecutionResult:
        nonlocal calls
        calls += 1
        (bundle / "aggregate/aggregate.json").write_bytes(b"drift\n")
        executable = Path(command[0])
        return review.ExecutionResult(
            returncode=0,
            termination_reason="COMPLETED",
            stdout=b"",
            stderr=b"",
            child_pid=403,
            proc_exe_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            proc_cmdline_sha256=hashlib.sha256(review._argv_raw(command)).hexdigest(),
        )

    monkeypatch.setattr(review, "_execute_once", mutate)
    attempt, returncode = review.run_review(
        bundle=bundle.resolve(),
        expected_manifest_sha256=manifest_sha256,
        attempt_root=(tmp_path / "attempt-bundle-drift").resolve(),
        attempt_id="dg13u-u1-review-primary-007",
        timeout_seconds=60,
        codex=_codex(tmp_path),
    )

    assert calls == 1
    assert returncode == 2
    terminal = json.loads((attempt / "terminal.json").read_text())
    assert terminal["reason_code"] == "BUNDLE_DRIFT"
    assert terminal["verdict"] == "BLOCKED_BY_MISSING_EVIDENCE"


def test_attempt_root_must_be_new_and_disjoint(tmp_path: Path) -> None:
    bundle, manifest_sha256 = _bundle(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()

    with pytest.raises(review.ReviewRunError, match="must be new"):
        review.run_review(
            bundle=bundle.resolve(),
            expected_manifest_sha256=manifest_sha256,
            attempt_root=existing.resolve(),
            attempt_id="dg13u-u1-review-primary-006",
            timeout_seconds=60,
            codex=_codex(tmp_path),
        )


def test_response_schema_and_prompt_freeze_review_contract() -> None:
    schema = json.loads(review.RESPONSE_SCHEMA_PATH.read_text())
    prompt = review.PROMPT_PATH.read_text()

    assert schema["properties"]["verdict"]["enum"] == [
        "PASS",
        "REVISE",
        "BLOCKED_BY_MISSING_EVIDENCE",
    ]
    assert schema["properties"]["open_findings"]["items"]["$ref"] == "#/$defs/finding"
    assert "gpt-5.6-sol" not in prompt
    normalized_prompt = " ".join(prompt.split())
    assert "number of open P0 findings is zero" in normalized_prompt
    assert "number of open P1 findings is zero" in normalized_prompt
    assert "Do not execute scripts or binaries" in prompt
    assert "Return exactly one JSON object" in prompt


def test_blocked_verdict_requires_missing_evidence() -> None:
    schema = json.loads(review.RESPONSE_SCHEMA_PATH.read_text())
    response = _response("a" * 64, "BLOCKED_BY_MISSING_EVIDENCE")
    assert schema["allOf"][2]["then"]["properties"]["missing_evidence"]["minItems"] == 1
    assert response["missing_evidence"] == []
