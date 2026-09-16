from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dg10_agent_terminal as terminal
from scripts import dg10_remediation as remediation


def _successful_ledger(
    path: Path, count: int = 1, *, expected_count: int | None = None
) -> tuple[dict[str, object], tuple[str, ...]]:
    slot_count = count if expected_count is None else expected_count
    slots = tuple(f"dg10-test-slot-{index:02d}" for index in range(slot_count))
    with remediation.AttemptLedger(
        path, authorized_model_call_slots=slots
    ) as ledger:
        for index in range(count):
            attempt_id = ledger.start_attempt(
                phase=terminal.authorization.BOOTSTRAP_PHASE,
                arm="T2_CONTROL_PATH",
                case_id=f"case-{index}",
                planned_model_calls=1,
                planned_mcp_calls=0,
                attempt_id=slots[index],
            )
            ledger.record_provider_claimed(
                attempt_id, provider_claim_digest=f"{index:064x}"
            )
            ledger.record_provider_accepted(
                attempt_id,
                f"native-{index}",
                raw_sidecar_digest="a" * 64,
            )
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
            ledger.finalize(
                attempt_id,
                agent_terminal=True,
                parser_terminal=True,
                retention_state="retained",
                failure_reason_code="SUCCESS",
                redacted_public_receipt_digest="b" * 64,
            )
    return (
        remediation.reconcile_attempt_ledger(
            path, expected_model_call_slots=slots
        ),
        slots,
    )


def test_terminal_success_expresses_three_distinct_terminal_states(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    _summary, _slots = _successful_ledger(path)
    snapshot = remediation.read_attempt_ledger(path)[-1]
    record = terminal.public_terminal_record(snapshot)
    assert record == {
        "schema": "milai.dg10.agent-terminal.v1",
        "attempt_id": snapshot["attempt_id"],
        "candidate_id": "candidate.4",
        "provider_status": "TERMINAL",
        "agent_status": "TERMINAL",
        "parser_status": "TERMINAL",
        "native_request_count": 1,
        "native_usage_all_attempts": {
            "input_tokens": 10,
            "output_tokens": 2,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
        },
        "public_result_status": "SUCCESS",
        "stable_reason_code": "SUCCESS",
    }


def test_post_provider_parser_failure_is_partial_and_preserves_usage(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    with remediation.AttemptLedger(path) as ledger:
        attempt_id = ledger.start_attempt(
            phase=terminal.authorization.BOOTSTRAP_PHASE,
            arm="T2_CONTROL_PATH",
            case_id="case-fail",
            planned_model_calls=1,
            planned_mcp_calls=0,
        )
        ledger.record_provider_claimed(
            attempt_id, provider_claim_digest="e" * 64
        )
        ledger.record_provider_accepted(
            attempt_id,
            "native-fail",
            raw_sidecar_digest="c" * 64,
        )
        ledger.record_provider_terminal(
            attempt_id,
            usage={
                "input_tokens": 99,
                "output_tokens": 7,
                "cached_input_tokens": 3,
                "reasoning_tokens": 1,
            },
            raw_sidecar_digest="c" * 64,
        )
        ledger.finalize(
            attempt_id,
            agent_terminal=False,
            parser_terminal=False,
            retention_state="failed",
            failure_reason_code="AGENT_EVENT_PARSE_FAILED",
            redacted_public_receipt_digest="d" * 64,
        )
    record = terminal.public_terminal_record(remediation.read_attempt_ledger(path)[-1])
    assert record["provider_status"] == "TERMINAL"
    assert record["agent_status"] == "FAILED"
    assert record["parser_status"] == "FAILED"
    assert record["public_result_status"] == "PARTIAL"
    assert record["native_usage_all_attempts"]["input_tokens"] == 99


def test_t2_gate_requires_exact_24_successes_and_reconciled_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.jsonl"
    _summary, slots = _successful_ledger(path, count=24)
    monkeypatch.setattr(
        terminal.authorization, "authorized_bootstrap_slots", lambda _receipt: slots
    )
    monkeypatch.setattr(terminal, "ACTIVE_T2_LEDGER", path)
    latest: dict[str, dict[str, object]] = {}
    for snapshot in remediation.read_attempt_ledger(path):
        latest[str(snapshot["attempt_id"])] = snapshot
    records = [terminal.public_terminal_record(snapshot) for snapshot in latest.values()]
    report = terminal.build_t2_gate(
        records,
        ledger_path=path,
        sidecar_sha256="e" * 64,
        source_inventory_sha256="f" * 64,
        authorization_receipt={
            "authorization_payload_sha256": "1" * 64,
            "call_slot_manifest_sha256": "2" * 64,
        },
    )
    assert report["gate_pass"] is True
    assert report["status"] == "T2_24_OF_24_AUTHOR_CANDIDATE_REVIEW_REQUIRED"
    assert report["independent_acceptance"] is False
    assert json.dumps(report)[0] == "{"


def test_t2_gate_does_not_accept_23_of_24(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.jsonl"
    _summary, slots = _successful_ledger(path, count=23, expected_count=24)
    monkeypatch.setattr(
        terminal.authorization, "authorized_bootstrap_slots", lambda _receipt: slots
    )
    monkeypatch.setattr(terminal, "ACTIVE_T2_LEDGER", path)
    latest: dict[str, dict[str, object]] = {}
    for snapshot in remediation.read_attempt_ledger(path):
        latest[str(snapshot["attempt_id"])] = snapshot
    report = terminal.build_t2_gate(
        [terminal.public_terminal_record(snapshot) for snapshot in latest.values()],
        ledger_path=path,
        sidecar_sha256="e" * 64,
        source_inventory_sha256="f" * 64,
        authorization_receipt={
            "authorization_payload_sha256": "1" * 64,
            "call_slot_manifest_sha256": "2" * 64,
        },
    )
    assert report["gate_pass"] is False
    assert report["stage_state"] == "REVISE"
