from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import dg10_remediation as remediation
from scripts import dg10_serving_metrics as serving


def _measurement(value: float | None = 1.0) -> dict[str, object]:
    if value is None:
        return {"state": "NOT_ESTIMABLE", "value": None, "reason": "NOT_EXPOSED"}
    return {"state": "MEASURED", "value": value, "reason": None}


def _attempt(
    index: int,
    *,
    tier: str = "T0",
    concurrency: int = 1,
    workload_sha256: str = "a" * 64,
) -> serving.ServingAttempt:
    model_rounds = 2 if tier == "T3b" else 1
    mcp_rounds = 1 if tier in {"T3a", "T3b"} else 0
    native_request_ids = tuple(
        f"native-{tier}-{concurrency}-{index}-{round_index}"
        for round_index in range(model_rounds)
    )
    return serving.ServingAttempt(
        attempt_id=f"attempt-{tier}-{concurrency}-{index}",
        workload_case_id="case",
        ledger_attempt_ids=tuple(
            f"ledger-{tier}-{concurrency}-{index}-{round_index}"
            for round_index in range(model_rounds)
        ),
        tier=tier,
        concurrency=concurrency,
        terminal=True,
        native_request_ids=native_request_ids,
        usage={
            "input_tokens": 10,
            "output_tokens": 2,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
        },
        e2e_ms=float(index + 1),
        ttft_ms=1.0,
        tpot_ms=2.0,
        itl_ms=None,
        model_rounds=model_rounds,
        mcp_rounds=mcp_rounds,
        retry_count=0,
        trace={name: _measurement() for name in serving.TRACE_COMPONENTS},
        resources={name: _measurement() for name in serving.RESOURCE_FIELDS},
        failure_reason_code="SUCCESS",
        candidate_id="candidate.4",
        workload_contract_sha256=workload_sha256,
        ledger_sha256="b" * 64,
        model_identity_sha256="c" * 64,
    )


def test_nearest_rank_uses_ceiling_rank_and_reports_n_min_max() -> None:
    result = serving.nearest_rank([1, 2, 3, 4], 0.75, minimum_n=4)
    assert result["value"] == 3
    assert (result["n"], result["min"], result["max"]) == (4, 1.0, 4.0)


def test_p99_below_one_hundred_is_not_estimable() -> None:
    result = serving.nearest_rank(range(99), 0.99, minimum_n=100)
    assert result["state"] == "NOT_ESTIMABLE"
    assert result["value"] is None


def test_cell_rejects_p50_p95_acceptance_from_eight_attempts() -> None:
    cell = serving.summarize_cell([_attempt(index) for index in range(8)], exclusive_window=True, wall_seconds=2)
    assert cell["latency_ms"]["p50"]["state"] == "NOT_ESTIMABLE"
    assert cell["latency_ms"]["p95"]["state"] == "NOT_ESTIMABLE"
    assert cell["acceptance_eligible"] is False


def test_failed_attempt_stays_in_usage_denominator() -> None:
    attempts = [_attempt(index) for index in range(30)]
    attempts[-1] = replace(
        attempts[-1],
        terminal=False,
        native_request_ids=(),
        usage=dict.fromkeys(("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")),
        failure_reason_code="PROVIDER_REQUEST_FAILED",
    )
    cell = serving.summarize_cell(attempts, exclusive_window=True, wall_seconds=3)
    assert cell["all_attempt_usage_denominator"] == 30
    assert cell["usage_incomplete_attempt_count"] == 1
    assert cell["functional_gate"] == "NO_GO"


def test_trace_or_resource_must_be_measured_or_explicitly_unavailable() -> None:
    attempt = _attempt(0)
    invalid_trace = dict(attempt.trace)
    invalid_trace["runtime"] = {"state": "NOT_ESTIMABLE", "value": None, "reason": None}
    with pytest.raises(serving.ServingMetricsError, match="reason is absent"):
        serving.summarize_cell([replace(attempt, trace=invalid_trace)], exclusive_window=False, wall_seconds=1)


def test_native_ids_must_be_unique_across_cell() -> None:
    first = _attempt(0)
    second = replace(_attempt(1), native_request_ids=first.native_request_ids)
    with pytest.raises(serving.ServingMetricsError, match="repeats within cell"):
        serving.summarize_cell([first, second], exclusive_window=False, wall_seconds=1)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("concurrency", True, "concurrency"),
        ("terminal", "true", "terminal state"),
        ("e2e_ms", "1", "E2E latency"),
        ("ttft_ms", -1.0, "TTFT latency"),
        ("model_rounds", True, "model round count"),
        ("retry_count", True, "retry round count"),
    ],
)
def test_attempt_rejects_boolean_string_or_negative_numeric_spoofs(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(serving.ServingMetricsError, match=message):
        serving.summarize_cell(
            [replace(_attempt(0), **{field: value})],
            exclusive_window=False,
            wall_seconds=1,
        )


def test_workload_contract_binds_all_comparability_inputs() -> None:
    contract = serving.freeze_workload_contract(
        workload_case_ids=["a", "b"],
        request_lengths={"a": 10, "b": 20},
        repetitions=30,
        generation={"temperature": 0, "max_output_tokens": 256},
        frozen_at="2026-08-22T00:00:00+00:00",
        model_identity_sha256="c" * 64,
    )
    assert contract["tiers"] == list(serving.TIERS)
    assert contract["concurrencies"] == [1, 4, 8]
    assert len(contract["contract_sha256"]) == 64


def test_workload_contract_rejects_generation_policy_drift() -> None:
    with pytest.raises(serving.ServingMetricsError, match="generation policy drift"):
        serving.freeze_workload_contract(
            workload_case_ids=["a"],
            request_lengths={"a": 10},
            repetitions=30,
            generation={"temperature": 0.1, "max_output_tokens": 256},
            frozen_at="2026-08-22T00:00:00+00:00",
            model_identity_sha256="c" * 64,
        )


def _sealed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    contract = serving.freeze_workload_contract(
        workload_case_ids=["case"],
        request_lengths={"case": 10},
        repetitions=30,
        generation={"temperature": 0, "max_output_tokens": 256},
        frozen_at="2026-08-22T00:00:00+00:00",
        model_identity_sha256="c" * 64,
    )
    workload_path = tmp_path / "workload.json"
    workload_path.write_text(json.dumps(contract), encoding="utf-8")
    receipt_root = tmp_path / "receipts"
    receipt_root.mkdir()
    ledger_path = tmp_path / "attempts.jsonl"
    started = datetime(2026, 8, 22, 0, 1, tzinfo=UTC)
    windows: list[dict[str, object]] = []
    with remediation.AttemptLedger(ledger_path) as ledger:
        for cell_index, tier in enumerate(serving.TIERS):
            for concurrency in serving.CONCURRENCIES:
                cell_start = started + timedelta(minutes=cell_index * 10 + concurrency)
                cell_finish = cell_start + timedelta(seconds=60)
                trace_path = tmp_path / f"trace-{tier}-{concurrency}.log"
                trace_path.write_text("exclusive scheduler capture\n", encoding="utf-8")
                windows.append(
                    {
                        "tier": tier,
                        "concurrency": concurrency,
                        "started_at": cell_start.isoformat(),
                        "finished_at": cell_finish.isoformat(),
                        "exclusive_window": True,
                        "scheduler_trace": {
                            "path": trace_path.relative_to(tmp_path).as_posix(),
                            "sha256": remediation.sha256_file(trace_path),
                        },
                    }
                )
                for index in range(30):
                    logical = _attempt(
                        index,
                        tier=tier,
                        concurrency=concurrency,
                        workload_sha256=contract["contract_sha256"],
                    )
                    raw = {
                        "schema": "milai.dg10.serving-attempt-raw.v1",
                        "attempt_id": logical.attempt_id,
                        "workload_case_id": logical.workload_case_id,
                        "ledger_attempt_ids": list(logical.ledger_attempt_ids),
                        "tier": tier,
                        "concurrency": concurrency,
                        "terminal": True,
                        "native_request_ids": list(logical.native_request_ids),
                        "usage": {
                            key: int(logical.usage[key] or 0) * logical.model_rounds
                            for key in remediation.USAGE_KEYS
                        },
                        "e2e_ms": logical.e2e_ms,
                        "ttft_ms": logical.ttft_ms,
                        "tpot_ms": logical.tpot_ms,
                        "itl_ms": logical.itl_ms,
                        "model_rounds": logical.model_rounds,
                        "mcp_rounds": logical.mcp_rounds,
                        "retry_count": logical.retry_count,
                        "trace": logical.trace,
                        "resources": logical.resources,
                        "failure_reason_code": "SUCCESS",
                        "candidate_id": "candidate.4",
                        "workload_contract_sha256": contract["contract_sha256"],
                        "model_identity_sha256": "c" * 64,
                        "started_at": (cell_start + timedelta(seconds=1)).isoformat(),
                        "finished_at": (cell_start + timedelta(seconds=2)).isoformat(),
                    }
                    raw_bytes = (json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n").encode()
                    receipt_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                    for round_index, ledger_attempt_id in enumerate(logical.ledger_attempt_ids):
                        attempt_id = ledger.start_attempt(
                            phase=f"SERVING_{tier}",
                            arm=tier,
                            case_id=logical.attempt_id,
                            planned_model_calls=1,
                            planned_mcp_calls=int(round_index == 0 and logical.mcp_rounds == 1),
                            attempt_id=ledger_attempt_id,
                        )
                        ledger.record_provider_accepted(
                            attempt_id,
                            logical.native_request_ids[round_index],
                        )
                        ledger.record_provider_terminal(
                            attempt_id,
                            usage=logical.usage,
                            raw_sidecar_digest=receipt_sha256,
                        )
                        if round_index == 0 and logical.mcp_rounds == 1:
                            ledger.record_mcp_accepted(attempt_id, f"mcp-{logical.attempt_id}")
                            ledger.record_mcp_terminal(
                                attempt_id,
                                raw_sidecar_digest=receipt_sha256,
                            )
                        ledger.finalize(
                            attempt_id,
                            agent_terminal=True,
                            parser_terminal=True,
                            retention_state="retained",
                            failure_reason_code="SUCCESS",
                            redacted_public_receipt_digest=receipt_sha256,
                        )
                    name = f"{hashlib.sha256(logical.attempt_id.encode()).hexdigest()}.json"
                    (receipt_root / name).write_bytes(raw_bytes)
    ledger_path.chmod(0o600)
    window_receipt = {
        "schema": "milai.dg10.serving-cell-windows.v1",
        "candidate_id": "candidate.4",
        "workload_contract_sha256": remediation.sha256_file(workload_path),
        "ledger_sha256": remediation.sha256_file(ledger_path),
        "cells": windows,
    }
    window_path = tmp_path / "windows.json"
    window_path.write_text(json.dumps(window_receipt), encoding="utf-8")
    monkeypatch.setattr(serving.remediation, "ROOT", tmp_path)
    monkeypatch.setattr(serving, "ACTIVE_SERVING_WORKLOAD", workload_path)
    monkeypatch.setattr(serving, "ACTIVE_SERVING_WORKLOAD_SHA256", remediation.sha256_file(workload_path))
    monkeypatch.setattr(serving, "ACTIVE_SERVING_LEDGER", ledger_path)
    monkeypatch.setattr(serving, "ACTIVE_SERVING_LEDGER_SHA256", remediation.sha256_file(ledger_path))
    monkeypatch.setattr(serving, "ACTIVE_SERVING_RAW_RECEIPTS", receipt_root)
    _paths, receipt_set_sha256 = serving._receipt_set(receipt_root)
    monkeypatch.setattr(serving, "ACTIVE_SERVING_RECEIPT_SET_SHA256", receipt_set_sha256)
    monkeypatch.setattr(serving, "ACTIVE_SERVING_WINDOW_RECEIPT", window_path)
    monkeypatch.setattr(
        serving,
        "ACTIVE_SERVING_WINDOW_RECEIPT_SHA256",
        remediation.sha256_file(window_path),
    )
    return receipt_root, ledger_path


def test_gate_requires_complete_matrix_and_treats_t3b_as_characterization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sealed_run(tmp_path, monkeypatch)
    gate = serving.build_serving_gate()
    assert gate["gate_pass"] is True
    assert gate["t3b_role"] == "CHARACTERIZATION_ONLY"
    assert gate["independent_acceptance"] is False


def test_gate_rejects_raw_receipt_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_root, _ledger_path = _sealed_run(tmp_path, monkeypatch)
    receipt = min(receipt_root.glob("*.json"))
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["e2e_ms"] = 0
    receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(serving.ServingMetricsError, match="receipt set hash drift"):
        serving.build_serving_gate()


def test_gate_rejects_overlapping_exclusive_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sealed_run(tmp_path, monkeypatch)
    window_path = serving.ACTIVE_SERVING_WINDOW_RECEIPT
    value = json.loads(window_path.read_text(encoding="utf-8"))
    value["cells"][1]["started_at"] = value["cells"][0]["started_at"]
    window_path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(
        serving,
        "ACTIVE_SERVING_WINDOW_RECEIPT_SHA256",
        remediation.sha256_file(window_path),
    )
    with pytest.raises(serving.ServingMetricsError, match="windows overlap"):
        serving.build_serving_gate()
