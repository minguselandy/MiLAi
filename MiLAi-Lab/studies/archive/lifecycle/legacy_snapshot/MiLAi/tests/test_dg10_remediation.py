from __future__ import annotations

import copy
import json
import stat
from pathlib import Path

import pytest
import yaml

from scripts import dg10_remediation as remediation
from scripts import validate_dg10_remediation as validator


def test_ai_audit_stderr_allows_only_the_known_model_refresh_timeout() -> None:
    known = (
        b"2026-08-22T10:56:05.429515Z ERROR codex_models_manager::manager: "
        b"failed to refresh available models: timeout waiting for child process to exit\n"
    )
    assert remediation.ai_audit_stderr_is_nonfatal(b"")
    assert remediation.ai_audit_stderr_is_nonfatal(known)
    assert not remediation.ai_audit_stderr_is_nonfatal(known + known)
    assert not remediation.ai_audit_stderr_is_nonfatal(b"prefix " + known)
    assert not remediation.ai_audit_stderr_is_nonfatal(known[:-1] + b" suffix\n")
    assert not remediation.ai_audit_stderr_is_nonfatal(known.rstrip(b"\n"))
    assert not remediation.ai_audit_stderr_is_nonfatal(known.rstrip(b"\n") + b"\r\n")
    assert not remediation.ai_audit_stderr_is_nonfatal(b"\xff" + known)
    assert not remediation.ai_audit_stderr_is_nonfatal(
        known.replace(b".429515Z", b".42951Z")
    )
    assert not remediation.ai_audit_stderr_is_nonfatal(
        known + b"ERROR codex_core::tools::router: sandbox unavailable\n"
    )
    assert not remediation.ai_audit_stderr_is_nonfatal(
        b"ERROR failed to refresh available models: connection refused\n"
    )


def _matrix() -> dict[str, object]:
    value = yaml.safe_load(validator.CLAIM_MATRIX.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_candidate_2_baseline_is_hash_and_archive_bound() -> None:
    report = remediation.build_baseline_report()
    assert report["status"] == "R0_AUTHOR_CANDIDATE_BOUND_REVIEW_REQUIRED"
    assert report["stage_state"] == "AUTHOR_CANDIDATE"
    assert report["independent_acceptance"] is False
    assert report["model_run_authorized"] is False
    assert report["archive_closure"] == {
        "member_count": 201,
        "regular_file_count": 201,
        "unsafe_path_or_duplicate_count": 0,
        "symlink_count": 0,
        "hardlink_count": 0,
        "status": "PASS_SAFE_REGULAR_MEMBERS",
    }
    assert report["open_blocking_findings"][:2] == ["DG10-SOL-001", "DG10-SOL-002"]
    assert report["open_blocking_findings"][2:] == [
        f"DG10-C3-AI-{index:03d}" for index in range(1, 9)
    ]
    assert report["parent_candidate_3_review"]["status"] == "REVISE"


def test_remediation_contracts_pass_but_do_not_authorize_model_or_test() -> None:
    report = validator.validate("contracts")
    assert report["status"] == "PASS_AUTHOR_CANDIDATE_REVIEW_REQUIRED"
    assert report["independent_acceptance"] is False
    assert report["model_run_authorized"] is False
    assert report["test_access_authorized"] is False
    assert report["R1"]["claim_matrix"]["aggregate_allowed"] is False
    assert report["R1"]["acceptance"]["track_a_answer_calls_per_arm"] == {
        "NO_MEMORY": 1,
        "NAIVE_RAG": 1,
        "MILAI_RETRIEVAL": 1,
    }


def test_claim_request_rejects_unaccepted_and_author_evidence() -> None:
    value = _matrix()
    record = copy.deepcopy(value["qualified_evidence"][0])
    with pytest.raises(validator.ValidationError, match="stage is not ACCEPTED"):
        validator.validate_claim_request(
            record,
            value["claim_catalog"],
            quality_outcome="TARGET_MET",
        )
    record["stage_state"] = "ACCEPTED"
    record["allowed"] = True
    with pytest.raises(validator.ValidationError, match="AUTHOR evidence"):
        validator.validate_claim_request(
            record,
            value["claim_catalog"],
            quality_outcome="TARGET_MET",
        )


def test_claim_request_rejects_cross_candidate_receipt() -> None:
    value = _matrix()
    record = copy.deepcopy(value["qualified_evidence"][0])
    record["gate_receipts"][0]["candidate_id"] = "candidate.3"
    with pytest.raises(validator.ValidationError, match="cross-candidate"):
        validator.validate_evidence_record(
            record,
            value["claim_catalog"],
            verify_files=False,
        )


def test_claim_request_rejects_missing_gate_or_hash_and_unknown_values() -> None:
    value = _matrix()
    record = copy.deepcopy(value["qualified_evidence"][0])
    record["gate_receipts"].pop()
    with pytest.raises(validator.ValidationError, match="missing gate"):
        validator.validate_evidence_record(
            record,
            value["claim_catalog"],
            verify_files=False,
        )
    record = copy.deepcopy(value["qualified_evidence"][0])
    record["gate_receipts"][0]["sha256"] = ""
    with pytest.raises(remediation.RemediationError, match="SHA-256"):
        validator.validate_evidence_record(
            record,
            value["claim_catalog"],
            verify_files=False,
        )
    record = copy.deepcopy(value["qualified_evidence"][0])
    record["claim_id"] = "UNKNOWN"
    with pytest.raises(validator.ValidationError, match="unknown claim"):
        validator.validate_evidence_record(
            record,
            value["claim_catalog"],
            verify_files=False,
        )


def test_quality_below_target_rejects_aggregate_request() -> None:
    value = _matrix()
    record = copy.deepcopy(value["qualified_evidence"][0])
    record["claim_id"] = "LOCAL_VLLM_MCP_AGENT_CANDIDATE"
    record["stage_id"] = "DG10-L5"
    record["stage_state"] = "ACCEPTED"
    record["evidence_class"] = "INDEPENDENT"
    record["required_gates"] = [
        "DG10-L1",
        "DG10-L2",
        "DG10-L3",
        "DG10-L4",
        "DG10-L5",
    ]
    record["gate_receipts"] = [
        {
            "gate_id": gate,
            "candidate_id": "candidate.2",
            "path": "unused",
            "sha256": "0" * 64,
        }
        for gate in record["required_gates"]
    ]
    record["allowed"] = True
    with pytest.raises(validator.ValidationError, match="BELOW_TARGET"):
        validator.validate_claim_request(
            record,
            value["claim_catalog"],
            quality_outcome="BELOW_TARGET",
            verify_files=False,
        )


def test_attempt_ledger_fsyncs_native_usage_before_parser_failure(tmp_path: Path) -> None:
    ledger_path = tmp_path / "attempts.jsonl"
    digest = "a" * 64
    with remediation.AttemptLedger(ledger_path) as ledger:
        attempt_id = ledger.start_attempt(
            phase="T2_SMOKE",
            arm="T2",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        ledger.record_provider_accepted(attempt_id, "native-1")
        ledger.record_provider_terminal(
            attempt_id,
            usage={
                "input_tokens": 101,
                "output_tokens": 9,
                "cached_input_tokens": 4,
                "reasoning_tokens": 0,
            },
            raw_sidecar_digest=digest,
        )
        ledger.finalize(
            attempt_id,
            agent_terminal=False,
            parser_terminal=False,
            retention_state="failed",
            failure_reason_code="AGENT_EVENT_PARSE_FAILED",
            redacted_public_receipt_digest="b" * 64,
        )
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600
    summary = remediation.reconcile_attempt_ledger(ledger_path)
    assert summary["known_completed_calls"] == 1
    assert summary["known_failed_calls"] == 1
    assert summary["retained_successful_calls"] == 0
    assert summary["unknown_early_diagnostics"] == 0
    snapshots = remediation.read_attempt_ledger(ledger_path)
    terminal = next(item for item in snapshots if item["attempt_state"] == "PROVIDER_TERMINAL")
    assert terminal["native_request_ids"] == ["native-1"]
    assert terminal["usage"]["input_tokens"] == 101


def test_attempt_ledger_rejects_extra_call_duplicate_id_and_unknown_reason(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "attempts.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        attempt_id = ledger.start_attempt(
            phase="TRACK_A",
            arm="NO_MEMORY",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        ledger.record_provider_accepted(attempt_id, "native-1")
        with pytest.raises(remediation.RemediationError, match="exceeds the plan"):
            ledger.record_provider_accepted(attempt_id, "native-2")
        second = ledger.start_attempt(
            phase="TRACK_A",
            arm="NAIVE_RAG",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        with pytest.raises(remediation.RemediationError, match="not unique"):
            ledger.record_provider_accepted(second, "native-1")
        with pytest.raises(remediation.RemediationError, match="unknown terminal reason"):
            ledger.finalize(
                attempt_id,
                agent_terminal=False,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="E2EGateError",
                redacted_public_receipt_digest="c" * 64,
            )


def test_attempt_ledger_hash_chain_detects_tampering(tmp_path: Path) -> None:
    ledger_path = tmp_path / "attempts.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        ledger.start_attempt(
            phase="REVIEW",
            case_id="finding-1",
            planned_model_calls=0,
            planned_mcp_calls=0,
        )
    rows = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    rows[0]["case_id"] = "tampered"
    ledger_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    ledger_path.chmod(0o600)
    with pytest.raises(remediation.RemediationError, match="digest mismatch"):
        remediation.reconcile_attempt_ledger(ledger_path)


def test_attempt_ledger_supports_mcp_only_terminal_attempt(tmp_path: Path) -> None:
    ledger_path = tmp_path / "mcp-attempts.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        attempt_id = ledger.start_attempt(
            phase="REAL_RUNTIME_MCP_RECALL",
            arm="MILAI_RETRIEVAL",
            case_id="case-1",
            planned_model_calls=0,
            planned_mcp_calls=1,
        )
        ledger.record_mcp_accepted(attempt_id, "mcp-trace-1")
        ledger.record_mcp_terminal(attempt_id, raw_sidecar_digest="d" * 64)
        ledger.finalize(
            attempt_id,
            agent_terminal=True,
            parser_terminal=True,
            retention_state="retained",
            failure_reason_code="SUCCESS",
            redacted_public_receipt_digest="e" * 64,
        )
    summary = remediation.reconcile_attempt_ledger(ledger_path)
    assert summary["retained_successful_calls"] == 0
    assert summary["known_completed_calls"] == 0
    assert summary["retained_successful_mcp_calls"] == 1
    assert summary["known_completed_mcp_calls"] == 1
    assert summary["unknown_early_diagnostics"] == 0


def test_finalized_attempt_with_missing_native_id_is_unknown_and_incomplete(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "missing-native-id.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        attempt_id = ledger.start_attempt(
            phase="T2_SMOKE",
            arm="T2",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        ledger.finalize(
            attempt_id,
            agent_terminal=False,
            parser_terminal=False,
            retention_state="failed",
            failure_reason_code="PROVIDER_REQUEST_FAILED",
            redacted_public_receipt_digest="f" * 64,
        )
    summary = remediation.reconcile_attempt_ledger(ledger_path)
    assert summary["missing_native_id_count"] == 1
    assert summary["unknown_early_diagnostics"] == 1
    assert summary["complete"] is False


def test_journaled_native_id_without_terminal_is_unknown_and_incomplete(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "missing-terminal.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        attempt_id = ledger.start_attempt(
            phase="T2_SMOKE",
            arm="T2",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        ledger.record_provider_accepted(attempt_id, "native-1")
        ledger.finalize(
            attempt_id,
            agent_terminal=False,
            parser_terminal=False,
            retention_state="failed",
            failure_reason_code="PROVIDER_TERMINAL_MISSING",
            redacted_public_receipt_digest="f" * 64,
        )
    summary = remediation.reconcile_attempt_ledger(ledger_path)
    assert summary["missing_terminal_count"] == 1
    assert summary["complete"] is False


def test_attempt_is_single_call_and_finalized_snapshot_is_immutable(tmp_path: Path) -> None:
    with (
        remediation.AttemptLedger(tmp_path / "invalid-plan.jsonl") as ledger,
        pytest.raises(remediation.RemediationError, match="at most one"),
    ):
        ledger.start_attempt(
            phase="TRACK_A",
            arm="NO_MEMORY",
            case_id="case-1",
            planned_model_calls=2,
            planned_mcp_calls=0,
        )

    ledger_path = tmp_path / "finalized.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        attempt_id = ledger.start_attempt(
            phase="REVIEW",
            case_id="finding-1",
            planned_model_calls=0,
            planned_mcp_calls=0,
        )
        ledger.finalize(
            attempt_id,
            agent_terminal=True,
            parser_terminal=True,
            retention_state="retained",
            failure_reason_code="SUCCESS",
            redacted_public_receipt_digest="a" * 64,
        )
        with pytest.raises(remediation.RemediationError, match="finalized"):
            ledger.record_mcp_accepted(attempt_id, "late-mcp")


def test_reconciliation_rejects_rehashed_immutable_field_rewrite(tmp_path: Path) -> None:
    ledger_path = tmp_path / "rewritten.jsonl"
    with remediation.AttemptLedger(ledger_path) as ledger:
        attempt_id = ledger.start_attempt(
            phase="TRACK_A",
            arm="NO_MEMORY",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        ledger.record_provider_accepted(attempt_id, "native-1")
    rows = remediation.read_attempt_ledger(ledger_path)
    rows[1]["phase"] = "TAMPERED"
    rows[1]["entry_sha256"] = remediation._entry_hash(rows[1])
    ledger_path.write_text("".join(remediation.encoded_json(row).decode() for row in rows))
    ledger_path.chmod(0o600)
    with pytest.raises(remediation.RemediationError, match="immutable field"):
        remediation.reconcile_attempt_ledger(ledger_path)


def test_authorized_call_slots_are_consumed_before_provider_access(
    tmp_path: Path,
) -> None:
    path = tmp_path / "slot-ledger.jsonl"
    with remediation.AttemptLedger(
        path,
        authorized_model_call_slots=("slot-01", "slot-02"),
    ) as ledger:
        with pytest.raises(
            remediation.RemediationError,
            match="does not consume an authorized call slot",
        ):
            ledger.start_attempt(
                phase="T2_CONTROL_PATH_SMOKE",
                case_id="case-unbound",
                planned_model_calls=1,
                planned_mcp_calls=0,
                attempt_id="unbound-slot",
            )
        ledger.start_attempt(
            phase="T2_CONTROL_PATH_SMOKE",
            case_id="case-01",
            planned_model_calls=1,
            planned_mcp_calls=0,
            attempt_id="slot-01",
        )
        with pytest.raises(remediation.RemediationError, match="already consumed"):
            ledger.start_attempt(
                phase="T2_CONTROL_PATH_SMOKE",
                case_id="case-repeat",
                planned_model_calls=1,
                planned_mcp_calls=0,
                attempt_id="slot-01",
            )


def test_invalid_authorized_slots_do_not_create_an_immutable_ledger(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid-slots.jsonl"
    with pytest.raises(remediation.RemediationError, match="slots are invalid"):
        remediation.AttemptLedger(
            path,
            authorized_model_call_slots=("slot-01", "slot-01"),
        )
    assert not path.exists()


def test_ledger_rejects_invalid_fields_before_append(tmp_path: Path) -> None:
    path = tmp_path / "invalid-fields.jsonl"
    with remediation.AttemptLedger(path) as ledger:
        with pytest.raises(remediation.RemediationError, match="case ID is invalid"):
            ledger.start_attempt(
                phase="TRACK_A",
                case_id="",
                planned_model_calls=1,
                planned_mcp_calls=0,
            )
        attempt_id = ledger.start_attempt(
            phase="TRACK_A",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        with pytest.raises(remediation.RemediationError, match="native request ID"):
            ledger.record_provider_accepted(attempt_id, "")
        with pytest.raises(remediation.RemediationError, match="terminal flags"):
            ledger.finalize(
                attempt_id,
                agent_terminal=1,
                parser_terminal=False,
                retention_state="failed",
                failure_reason_code="PROVIDER_REQUEST_FAILED",
                redacted_public_receipt_digest="a" * 64,
            )
    assert len(remediation.read_attempt_ledger(path)) == 1


def test_reconciliation_rejects_non_boolean_terminal_and_naive_time(
    tmp_path: Path,
) -> None:
    boolean_path = tmp_path / "boolean.jsonl"
    with remediation.AttemptLedger(boolean_path) as ledger:
        ledger.start_attempt(
            phase="TRACK_A",
            case_id="case-1",
            planned_model_calls=0,
            planned_mcp_calls=0,
        )
    rows = remediation.read_attempt_ledger(boolean_path)
    rows[0]["provider_terminal"] = 1
    rows[0]["entry_sha256"] = remediation._entry_hash(rows[0])
    boolean_path.write_bytes(b"".join(remediation.encoded_json(row) for row in rows))
    boolean_path.chmod(0o600)
    with pytest.raises(remediation.RemediationError, match="terminal field"):
        remediation.reconcile_attempt_ledger(boolean_path)

    time_path = tmp_path / "time.jsonl"
    with remediation.AttemptLedger(time_path) as ledger:
        ledger.start_attempt(
            phase="TRACK_A",
            case_id="case-1",
            planned_model_calls=0,
            planned_mcp_calls=0,
        )
    rows = remediation.read_attempt_ledger(time_path)
    rows[0]["started_at"] = "2026-08-22T00:00:00"
    rows[0]["entry_sha256"] = remediation._entry_hash(rows[0])
    time_path.write_bytes(b"".join(remediation.encoded_json(row) for row in rows))
    time_path.chmod(0o600)
    with pytest.raises(remediation.RemediationError, match="lacks timezone"):
        remediation.reconcile_attempt_ledger(time_path)


def test_attempt_ledger_resumes_hash_chain_and_unfinished_attempt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "resumable.jsonl"
    with remediation.AttemptLedger(path) as ledger:
        attempt_id = ledger.start_attempt(
            phase="TRACK_A_MEMORY_QUALITY",
            arm="NO_MEMORY",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        ledger.record_provider_accepted(attempt_id, "native-1")
        ledger.record_provider_terminal(
            attempt_id,
            usage={
                "input_tokens": 10,
                "output_tokens": 2,
                "cached_input_tokens": 0,
                "reasoning_tokens": 0,
            },
            raw_sidecar_digest="a" * 64,
        )

    with remediation.AttemptLedger(path, resume=True) as resumed:
        resumed.finalize(
            attempt_id,
            agent_terminal=True,
            parser_terminal=True,
            retention_state="retained",
            failure_reason_code="SUCCESS",
            redacted_public_receipt_digest="b" * 64,
        )
        second = resumed.start_attempt(
            phase="TRACK_A_MEMORY_QUALITY",
            arm="NAIVE_RAG",
            case_id="case-1",
            planned_model_calls=0,
            planned_mcp_calls=0,
        )
        resumed.finalize(
            second,
            agent_terminal=True,
            parser_terminal=True,
            retention_state="retained",
            failure_reason_code="SUCCESS",
            redacted_public_receipt_digest="c" * 64,
        )

    summary = remediation.reconcile_attempt_ledger(path)
    assert summary["attempt_count"] == 2
    assert summary["entry_count"] == 6
    assert summary["retained_successful_calls"] == 1
    assert summary["complete"] is True


def test_attempt_ledger_resume_rejects_slot_drift_and_concurrent_writer(
    tmp_path: Path,
) -> None:
    path = tmp_path / "resumable-slots.jsonl"
    with remediation.AttemptLedger(
        path,
        authorized_model_call_slots=("slot-01", "slot-02"),
    ) as ledger:
        ledger.start_attempt(
            phase="T2_CONTROL_PATH_SMOKE",
            arm="T2_CONTROL_PATH",
            case_id="case-1",
            planned_model_calls=1,
            planned_mcp_calls=0,
            attempt_id="slot-01",
        )
        with pytest.raises(remediation.RemediationError, match="resume attempt ledger"):
            remediation.AttemptLedger(path, resume=True)

    with pytest.raises(remediation.RemediationError, match="outside the authorized"):
        remediation.AttemptLedger(
            path,
            resume=True,
            authorized_model_call_slots=("slot-02",),
        )

    with remediation.AttemptLedger(
        path,
        resume=True,
        authorized_model_call_slots=("slot-01", "slot-02"),
    ) as resumed, pytest.raises(
        remediation.RemediationError, match="already consumed"
    ):
        resumed.start_attempt(
            phase="T2_CONTROL_PATH_SMOKE",
            arm="T2_CONTROL_PATH",
            case_id="case-repeat",
            planned_model_calls=1,
            planned_mcp_calls=0,
            attempt_id="slot-01",
        )
