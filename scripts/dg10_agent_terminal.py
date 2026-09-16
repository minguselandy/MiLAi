from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation

TERMINAL_SCHEMA = remediation.ROOT / "docs/contracts/DG-10-agent-terminal.schema.json"
ACTIVE_T2_LEDGER = remediation.ROOT / "var/dg10/t2-bootstrap-candidate.4/attempts.jsonl"


class TerminalContractError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise TerminalContractError(reason)


def _usage(value: object) -> dict[str, int | None]:
    _require(isinstance(value, Mapping), "native usage must be an object")
    result: dict[str, int | None] = {}
    for key in remediation.USAGE_KEYS:
        item = value.get(key)
        _require(
            item is None
            or (isinstance(item, int) and not isinstance(item, bool) and item >= 0),
            f"invalid native usage: {key}",
        )
        result[key] = item
    _require(set(value) == set(remediation.USAGE_KEYS), "native usage key set drift")
    return result


def public_terminal_record(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    remediation._validate_attempt_snapshot(snapshot)
    _require(snapshot.get("attempt_state") == "FINALIZED", "attempt is not finalized")
    _require(snapshot.get("candidate_id") == remediation.CANDIDATE, "terminal candidate splice")
    reason = snapshot.get("failure_reason_code")
    _require(reason in remediation.STABLE_REASON_CODES, "unknown stable reason code")
    native_ids = snapshot.get("native_request_ids")
    _require(
        isinstance(native_ids, list)
        and len(native_ids) == len(set(native_ids))
        and all(isinstance(item, str) and item for item in native_ids),
        "native request ID set is invalid",
    )
    provider_terminal = snapshot.get("provider_terminal")
    if provider_terminal is True:
        provider_status = "TERMINAL"
    elif native_ids:
        provider_status = "ACCEPTED"
    elif reason == "PROVIDER_REQUEST_FAILED":
        provider_status = "REQUEST_FAILED"
    else:
        provider_status = "NOT_STARTED"
    agent_terminal = snapshot.get("agent_terminal")
    parser_terminal = snapshot.get("parser_terminal")
    agent_status = "TERMINAL" if agent_terminal is True else "FAILED"
    parser_status = "TERMINAL" if parser_terminal is True else "FAILED"
    if reason == "SUCCESS":
        public_status = "SUCCESS"
    elif provider_terminal is True:
        public_status = "PARTIAL"
    else:
        public_status = "FAILED"
    usage = _usage(snapshot.get("usage"))
    if provider_terminal is True:
        _require(all(value is not None for value in usage.values()), "terminal usage missing")
    record = {
        "schema": "milai.dg10.agent-terminal.v1",
        "attempt_id": snapshot.get("attempt_id"),
        "candidate_id": snapshot.get("candidate_id"),
        "provider_status": provider_status,
        "agent_status": agent_status,
        "parser_status": parser_status,
        "native_request_count": len(native_ids),
        "native_usage_all_attempts": usage,
        "public_result_status": public_status,
        "stable_reason_code": reason,
    }
    validate_public_terminal_record(record)
    return record


def validate_public_terminal_record(record: Mapping[str, Any]) -> None:
    schema = json.loads(TERMINAL_SCHEMA.read_text(encoding="utf-8"))
    required = set(schema["required"])
    _require(set(record) == required, "terminal record key set drift")
    _require(
        record.get("schema") == "milai.dg10.agent-terminal.v1",
        "terminal schema drift",
    )
    _require(
        isinstance(record.get("attempt_id"), str)
        and bool(record.get("attempt_id"))
        and record.get("candidate_id") == remediation.CANDIDATE,
        "terminal attempt or candidate identity drift",
    )
    _require(
        record.get("provider_status") in {"NOT_STARTED", "REQUEST_FAILED", "ACCEPTED", "TERMINAL"},
        "provider status drift",
    )
    _require(
        record.get("agent_status") in {"TERMINAL", "FAILED"},
        "agent status drift",
    )
    _require(
        record.get("parser_status") in {"TERMINAL", "FAILED"},
        "parser status drift",
    )
    _require(
        record.get("public_result_status") in {"SUCCESS", "FAILED", "PARTIAL"},
        "public result status drift",
    )
    _require(
        record.get("stable_reason_code") in remediation.STABLE_REASON_CODES,
        "stable reason code drift",
    )
    _require(
        isinstance(record.get("native_request_count"), int)
        and not isinstance(record.get("native_request_count"), bool)
        and int(record["native_request_count"]) >= 0,
        "native request count is invalid",
    )
    usage = _usage(record.get("native_usage_all_attempts"))
    provider_status = record.get("provider_status")
    public_status = record.get("public_result_status")
    reason = record.get("stable_reason_code")
    native_count = record.get("native_request_count")
    if provider_status == "TERMINAL":
        _require(native_count == 1, "terminal provider native count drift")
        _require(all(value is not None for value in usage.values()), "terminal usage missing")
    else:
        _require(all(value is None for value in usage.values()), "non-terminal provider has usage")
        _require(
            (provider_status == "ACCEPTED" and native_count == 1)
            or (provider_status in {"NOT_STARTED", "REQUEST_FAILED"} and native_count == 0),
            "non-terminal provider native count drift",
        )
    if provider_status == "REQUEST_FAILED":
        _require(reason == "PROVIDER_REQUEST_FAILED", "provider request-failure reason drift")
    if public_status == "SUCCESS":
        _require(
            provider_status == "TERMINAL"
            and record.get("agent_status") == "TERMINAL"
            and record.get("parser_status") == "TERMINAL"
            and reason == "SUCCESS",
            "success record terminal invariants failed",
        )
    elif public_status == "PARTIAL":
        _require(
            provider_status == "TERMINAL" and reason != "SUCCESS",
            "partial record terminal invariants failed",
        )
    else:
        _require(
            provider_status != "TERMINAL" and reason != "SUCCESS",
            "failed record terminal invariants failed",
        )


def build_t2_gate(
    records: Sequence[Mapping[str, Any]],
    *,
    ledger_path: Path,
    sidecar_sha256: str,
    source_inventory_sha256: str,
    authorization_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    remediation._require_sha256(sidecar_sha256, "T2 sidecar digest")
    remediation._require_sha256(source_inventory_sha256, "source inventory digest")
    resolved_ledger = ledger_path.resolve()
    _require(
        resolved_ledger == ACTIVE_T2_LEDGER.resolve()
        and resolved_ledger.is_file()
        and not resolved_ledger.is_symlink(),
        "T2 ledger is not the fixed execution ledger",
    )
    call_slots = authorization.authorized_bootstrap_slots(authorization_receipt)
    ledger_summary = remediation.reconcile_attempt_ledger(
        resolved_ledger,
        candidate_id=remediation.CANDIDATE,
        expected_model_call_slots=call_slots,
    )
    latest: dict[str, Mapping[str, Any]] = {}
    for snapshot in remediation.read_attempt_ledger(resolved_ledger):
        latest[str(snapshot["attempt_id"])] = snapshot
    expected_records = {
        attempt_id: public_terminal_record(snapshot)
        for attempt_id, snapshot in latest.items()
    }
    supplied_records: dict[str, Mapping[str, Any]] = {}
    for record in records:
        validate_public_terminal_record(record)
        attempt_id = str(record["attempt_id"])
        _require(attempt_id not in supplied_records, "T2 terminal attempt ID repeats")
        supplied_records[attempt_id] = record
    _require(
        supplied_records == expected_records
        and all(
            snapshot["phase"] == authorization.BOOTSTRAP_PHASE
            and snapshot["arm"] == "T2_CONTROL_PATH"
            for snapshot in latest.values()
        ),
        "T2 terminal records differ from the fixed attempt ledger",
    )
    attempt_ids = [str(record["attempt_id"]) for record in records]
    reason_counts = Counter(str(record["stable_reason_code"]) for record in records)
    success_count = sum(record["public_result_status"] == "SUCCESS" for record in records)
    native_count = sum(int(record["native_request_count"]) for record in records)
    ledger_known_completed = ledger_summary.get("known_completed_calls")
    reconciled = (
        len(records) == 24
        and len(attempt_ids) == len(set(attempt_ids))
        and success_count == 24
        and native_count == 24
        and ledger_known_completed == 24
        and ledger_summary.get("retained_successful_calls") == 24
        and ledger_summary.get("known_failed_calls") == 0
        and ledger_summary.get("unknown_early_diagnostics") == 0
        and ledger_summary.get("complete") is True
        and set(attempt_ids) == set(call_slots)
        and ledger_summary.get("expected_model_call_slot_count") == 24
        and ledger_summary.get("consumed_model_call_slot_count") == 24
        and ledger_summary.get("model_call_slot_manifest_match") is True
    )
    return {
        "schema": "milai.dg10.agent-terminal-gate.v1",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": (
            "T2_24_OF_24_AUTHOR_CANDIDATE_REVIEW_REQUIRED"
            if reconciled
            else "T2_NO_GO_TERMINAL_OR_LEDGER_MISMATCH"
        ),
        "stage_id": "DG10-R3",
        "stage_state": "AUTHOR_CANDIDATE" if reconciled else "REVISE",
        "independent_acceptance": False,
        "attempt_count": len(records),
        "terminal_success_count": success_count,
        "terminal_failure_count": len(records) - success_count,
        "native_request_count": native_count,
        "reason_counts": dict(sorted(reason_counts.items())),
        "ledger_summary": dict(ledger_summary),
        "redacted_sidecar": {
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "sha256": sidecar_sha256,
        },
        "source_inventory_sha256": source_inventory_sha256,
        "authorization_payload_sha256": authorization_receipt[
            "authorization_payload_sha256"
        ],
        "call_slot_manifest_sha256": authorization_receipt[
            "call_slot_manifest_sha256"
        ],
        "model_run_authorizes_benchmark": False,
        "gate_pass": reconciled,
    }
