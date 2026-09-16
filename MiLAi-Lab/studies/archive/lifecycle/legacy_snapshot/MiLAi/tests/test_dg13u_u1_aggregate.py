from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts import dg13u_u1_aggregate as aggregate
from scripts import dg13u_u1_fault_scenarios as fault_scenarios
from scripts import dg13u_u1_openworker as runner


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_case(
    root: Path,
    case_id: str,
    index: int,
    *,
    status: str = "PASS",
    cleanup_status: str = "PASS",
    manifest_binding: str = "a" * 64,
    gate_overrides: dict[str, str] | None = None,
    safety_failures: dict[str, int] | None = None,
    provider_unaccounted: int = 0,
    retries: int = 0,
    include_metrics: bool = True,
) -> Path:
    spec = aggregate.CASE_CONTRACTS[case_id]
    run_id = f"dg13u-u1-aggregate-{index:03d}"
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "schema": aggregate.MANIFEST_SCHEMA,
        "run_id": run_id,
        "case_id": case_id,
        "status": status,
        "release_label": aggregate.RELEASE_LABEL,
        "release_label_earned": False,
        "scope": dict(aggregate.CURRENT_SCOPE),
        "bindings": {
            name: {"path": f"contracts/{name}.json", "sha256": manifest_binding}
            for name in aggregate.REQUIRED_BINDINGS
        },
        "requested_composition": dict(aggregate.CURRENT_COMPOSITION),
        "call_policy": {
            **aggregate.CALL_POLICY,
            "provider_calls_case_maximum": spec.expected_provider_calls,
        },
        "formal_evaluation_input": False,
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    recovery_plan_path = run_dir / "recovery-resource-plan.json"
    recovery_plan = {
        "schema": "milai.dg13u.u1-recovery-resource-plan.v1",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "resources": [
            {
                "kind": "external_vllm",
                "ownership": "PRESERVED_EXTERNAL",
                "origin": "http://127.0.0.1:7860",
                "model_id": aggregate.MODEL_ID,
                "identity_sha256": "f" * 64,
            }
        ],
    }
    recovery_plan_path.write_bytes(_canonical(recovery_plan) + b"\n")
    recovery_plan_sha256 = hashlib.sha256(recovery_plan_path.read_bytes()).hexdigest()
    artifact_documents = {
        "exact-product-manifest.json": {
            "schema": aggregate.REQUIRED_ARTIFACT_SCHEMAS[
                "exact-product-manifest.json"
            ],
            "run_id": run_id,
            "case_id": case_id,
            "status": "PASS",
        },
        "identity-preflight.json": {
            "schema": aggregate.REQUIRED_ARTIFACT_SCHEMAS["identity-preflight.json"],
            "run_id": run_id,
            "case_id": case_id,
            "status": "PASS",
        },
        "readiness.json": {
            "schema": aggregate.REQUIRED_ARTIFACT_SCHEMAS["readiness.json"],
            "run_id": run_id,
            "case_id": case_id,
            "status": status,
            "runtime": "PASS",
            "broker": "PASS",
            "host": "PASS",
            "openworker": "PASS",
            "provider": "PASS_IDENTITY_ONLY_ZERO_COMPLETIONS",
            "security": {
                "status": "PASS",
                "network_internal": True,
                "reader_lite_socket_read_only": True,
                "docker_socket_mounted": False,
                "forbidden_environment_names": [],
            },
        },
        "smoke-evidence.json": {
            "schema": aggregate.REQUIRED_ARTIFACT_SCHEMAS["smoke-evidence.json"],
            "run_id": run_id,
            "case_id": case_id,
            "status": status,
        },
        "reconciliation.json": {
            "schema": aggregate.REQUIRED_ARTIFACT_SCHEMAS["reconciliation.json"],
            "run_id": run_id,
            "case_id": case_id,
            "status": status,
            "unaccounted_calls": 0,
            "durable_credentials_found": 0,
        },
        "cleanup-receipt.json": {
            "schema": aggregate.REQUIRED_ARTIFACT_SCHEMAS["cleanup-receipt.json"],
            "run_id": run_id,
            "case_id": case_id,
            "status": cleanup_status,
            "existing_vllm_preserved": True,
            "external_lifecycle_mutations": 0,
            "recovery_plan": {
                "schema": "milai.dg13u.u1-recovery-resource-plan.v1",
                "path": str(recovery_plan_path),
                "sha256": recovery_plan_sha256,
                "status": "PASS",
            },
            "items": [
                {
                    "kind": "external_vllm",
                    "ownership": "PRESERVED_EXTERNAL",
                    "state": "preserved_external",
                    "attempts": 0,
                }
            ],
        },
    }
    if case_id in fault_scenarios.FAULT_SCENARIOS:
        scenario = fault_scenarios.FAULT_SCENARIOS[case_id]
        artifact_documents["fault-execution.json"] = {
            "schema": aggregate.FAULT_EXECUTION_SCHEMA,
            "run_id": run_id,
            "case_id": case_id,
            "status": "PASS",
            "host_terminal": asdict(scenario.expected_terminal),
            "exact_calls": {
                "mcp": scenario.expected_mcp_calls,
                "provider": scenario.expected_provider_calls,
            },
            "automatic_retries": 0,
            "provider_barrier": scenario.expected_provider_barrier,
            "external_attempts": 0,
            "external_lifecycle_mutations": 0,
            "external_vllm": {"attempts": 0, "lifecycle_mutations": 0},
        }
    for name, document in artifact_documents.items():
        (run_dir / name).write_bytes(_canonical(document) + b"\n")
    osafety = safety_failures or {}
    safety = {}
    for name in aggregate.SAFETY_COUNTERS:
        denominator = 1 if name in spec.safety_counters else 0
        failures = osafety.get(name, 0)
        safety[name] = {
            "failures": failures,
            "denominator": denominator,
            "status": (
                "PASS"
                if denominator and failures == 0
                else "FAIL"
                if denominator
                else "NOT_RUN"
            ),
        }
    gates = {
        name: {"status": "NOT_RUN", "reason_code": "SINGLE_CASE_CANNOT_EARN_GATE"}
        for name in aggregate.GATE_NAMES
    }
    for name, value in (gate_overrides or {}).items():
        gates[name]["status"] = value
    report = {
        "schema": aggregate.REPORT_SCHEMA,
        "run_id": run_id,
        "case_id": case_id,
        "status": status,
        "release_label_earned": False,
        "feature_support": {"delayed_or_asynchronous_tool_result": "UNSUPPORTED"},
        "stages": [
            {"stage": stage, "status": "PASS", "duration_ms": float(index + offset)}
            for offset, stage in enumerate(aggregate.REQUIRED_STAGES)
        ],
        "gates": gates,
        "safety_counters": safety,
        "calls": {
            "mcp": {
                "expected": spec.expected_mcp_calls,
                "observed": spec.expected_mcp_calls,
                "unaccounted": 0,
                "automatic_retries": 0,
                "status": "PASS",
            },
            "provider": {
                "expected": spec.expected_provider_calls,
                "maximum_per_model_round": 1,
                "model_rounds": spec.expected_provider_calls,
                "calls_per_task_operation": spec.expected_provider_calls,
                "case_maximum": spec.expected_provider_calls,
                "observed": spec.expected_provider_calls,
                "unaccounted": provider_unaccounted,
                "automatic_retries": retries,
                "status": "PASS"
                if not provider_unaccounted and not retries
                else "FAIL",
            },
        },
        "stage_latency_ms": {
            stage: float(index + offset)
            for offset, stage in enumerate(aggregate.REQUIRED_STAGES)
        },
        "cleanup": {
            "status": cleanup_status,
            "receipt": "cleanup-receipt.json",
            "existing_vllm_preserved": True,
            "recovery_plan_sha256": recovery_plan_sha256,
        },
        "joined_identities": {
            "access_id_sha256": "b" * 64,
            "mcp_receipt_sha256": "c" * 64,
            "runtime_trace_sha256": "d" * 64,
            "provider_native_request_id_sha256": "e" * 64,
        },
        "artifacts": [],
    }
    for artifact_path in sorted(run_dir.glob("*.json")):
        report["artifacts"].append(
            {
                "path": artifact_path.name,
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "bytes": artifact_path.stat().st_size,
            }
        )
    if include_metrics:
        report["wall_latency_ms"] = float(index)
        report["context_tokens"] = (
            index if case_id in aggregate.MEMORY_CONTEXT_CASE_IDS else 0
        )
    report_path = run_dir / "report.json"
    report_path.write_bytes(_canonical(report) + b"\n")
    return report_path


def _matrix(root: Path) -> list[Path]:
    return [
        _write_case(root, case_id, index)
        for index, case_id in enumerate(aggregate.REQUIRED_CASE_IDS, start=1)
    ]


def _refresh_artifact_entry(report_path: Path, artifact_name: str) -> None:
    report = json.loads(report_path.read_text())
    artifact_path = report_path.with_name(artifact_name)
    row = next(item for item in report["artifacts"] if item["path"] == artifact_name)
    row["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    row["bytes"] = artifact_path.stat().st_size
    report_path.write_bytes(_canonical(report) + b"\n")


def _remove_artifact(report_path: Path, artifact_name: str) -> None:
    report = json.loads(report_path.read_text())
    report["artifacts"] = [
        row for row in report["artifacts"] if row["path"] != artifact_name
    ]
    report_path.write_bytes(_canonical(report) + b"\n")
    report_path.with_name(artifact_name).unlink()


def _mutate_fault_execution(report_path: Path, mutation: str) -> None:
    artifact = report_path.with_name("fault-execution.json")
    value = json.loads(artifact.read_text())
    if mutation == "schema":
        value["schema"] = "milai.dg13u.u1-fault-execution.v0"
    elif mutation == "status":
        value["status"] = "FAIL"
    elif mutation == "run_id":
        value["run_id"] = "different-run"
    elif mutation == "case_id":
        value["case_id"] = "U1-BROKER-MALFORMED"
    elif mutation == "host_reason":
        value["host_terminal"]["reason_code"] = "WRONG_REASON"
    elif mutation == "exact_calls":
        value["exact_calls"]["mcp"] += 1
    elif mutation == "retries":
        value["automatic_retries"] = 1
    elif mutation == "barrier":
        value["provider_barrier"] = "ALLOWED_ONCE"
    elif mutation == "external_attempts":
        value["external_attempts"] = 1
    elif mutation == "external_lifecycle":
        value["external_lifecycle_mutations"] = 1
    elif mutation == "vllm_attempts":
        value["external_vllm"]["attempts"] = 1
    elif mutation == "vllm_lifecycle":
        value["external_vllm"]["lifecycle_mutations"] = 1
    else:  # pragma: no cover - test helper invariant
        raise AssertionError(f"unknown fault mutation: {mutation}")
    artifact.write_bytes(_canonical(value) + b"\n")
    _refresh_artifact_entry(report_path, artifact.name)


def _case_evidence(result: dict[str, object], case_id: str) -> dict[str, object]:
    evidence = result["evidence_validation"]
    assert isinstance(evidence, dict)
    cases = evidence["cases"]
    assert isinstance(cases, list)
    return next(item for item in cases if item["case_id"] == case_id)


def test_frozen_matrix_and_case_accounting_match_the_single_case_runner() -> None:
    assert set(runner.CASES) == set(aggregate.REQUIRED_CASE_IDS)
    assert set(runner.SAFETY_COUNTERS) == set(aggregate.SAFETY_COUNTERS)
    for case_id, contract in aggregate.CASE_CONTRACTS.items():
        case = runner.CASES[case_id]
        assert (
            contract.expected_mcp_calls,
            contract.expected_provider_calls,
            contract.safety_counters,
        ) == (
            case.expected_mcp_calls,
            case.expected_provider_calls,
            case.safety_counters,
        )


def test_memory_context_and_exact_join_sets_cover_all_successful_exact_routes() -> None:
    expected_adjacent_exact = {
        "U1-CACHE-FALLBACK",
        "U1-WRONG-TASK",
        "U1-WRONG-SCOPE",
        "U1-STALE-CURRENT",
        "U1-ADAPTER-RESTART",
        "U1-STREAM",
    }

    assert expected_adjacent_exact <= aggregate.MEMORY_CONTEXT_CASE_IDS
    assert aggregate.EXACT_SUCCESS_CASE_IDS == aggregate.MEMORY_CONTEXT_CASE_IDS
    assert {
        "U1-ORDINARY-SYNC-TOOL",
        "U1-REVOKE-REENTRY",
        "U1-OPEN-ISSUE",
        "U1-AUTHORITY-ESCALATION",
        "U1-ALIAS-COLLISION",
    }.isdisjoint(aggregate.MEMORY_CONTEXT_CASE_IDS)


def test_full_exact_matrix_earns_release_and_uses_nearest_rank_metrics(
    tmp_path: Path,
) -> None:
    reports = _matrix(tmp_path)

    result = aggregate.aggregate_reports(reports)

    assert result["status"] == "PASS"
    assert result["release_label"] == aggregate.RELEASE_LABEL
    assert result["release_label_earned"] is True
    assert result["matrix"] == {
        "required": len(aggregate.REQUIRED_CASE_IDS),
        "observed": len(aggregate.REQUIRED_CASE_IDS),
        "missing_case_ids": [],
        "unexpected_case_ids": [],
        "status": "PASS",
    }
    assert all(
        result["gates"][name]["status"] == "PASS" for name in aggregate.GATE_NAMES
    )
    assert all(
        value["failures"] == 0
        and value["denominator"] > 0
        and value["status"] == "PASS"
        for value in result["safety_counters"].values()
    )
    wall = result["metrics"]["wall_latency_ms"]
    assert wall == {
        "unit": "ms",
        "sample_count": len(reports),
        "expected_sample_count": len(reports),
        "missing_case_ids": [],
        "p50": 19.0,
        "p95": 36.0,
        "p99": 37.0,
        "status": "PASS",
    }
    tokens = result["metrics"]["context_tokens"]
    assert tokens["unit"] == "tokens"
    assert tokens["p50"] == 0
    assert tokens["p95"] == 30
    assert tokens["p99"] == 31


def test_missing_any_required_case_keeps_g2_g4_and_release_nonpass(
    tmp_path: Path,
) -> None:
    reports = _matrix(tmp_path)
    missing = aggregate.REQUIRED_CASE_IDS[-1]
    reports = [
        path for path in reports if json.loads(path.read_text())["case_id"] != missing
    ]

    result = aggregate.aggregate_reports(reports)

    assert result["matrix"]["missing_case_ids"] == [missing]
    assert result["gates"]["U1-G2"]["status"] != "PASS"
    assert result["gates"]["U1-G4"]["status"] != "PASS"
    assert result["status"] != "PASS"
    assert result["release_label_earned"] is False


def test_safety_failure_blocks_later_green_gates(tmp_path: Path) -> None:
    reports = _matrix(tmp_path)
    target = reports[0]
    value = json.loads(target.read_text())
    value["safety_counters"]["SilentMemoryNeedNone"] = {
        "failures": 1,
        "denominator": 1,
        "status": "FAIL",
    }
    target.write_bytes(_canonical(value) + b"\n")

    result = aggregate.aggregate_reports(reports)

    assert result["gates"]["U1-G0"]["status"] == "PASS"
    assert result["gates"]["U1-G1"]["status"] == "FAIL"
    assert result["gates"]["U1-G2"]["intrinsic_status"] == "PASS"
    assert result["gates"]["U1-G2"]["status"] == "BLOCKED"
    assert result["release_label_earned"] is False


def test_duplicate_case_and_unknown_case_are_rejected(tmp_path: Path) -> None:
    first = _write_case(tmp_path, aggregate.REQUIRED_CASE_IDS[0], 1)
    duplicate = _write_case(tmp_path, aggregate.REQUIRED_CASE_IDS[0], 2)
    with pytest.raises(aggregate.AggregateError, match="duplicate case_id"):
        aggregate.aggregate_reports([first, duplicate])

    value = json.loads(first.read_text())
    value["case_id"] = "U1-UNKNOWN"
    first.write_bytes(_canonical(value) + b"\n")
    with pytest.raises(aggregate.AggregateError, match="unexpected case_id"):
        aggregate.aggregate_reports([first])


def test_invalid_report_schema_or_status_is_rejected_before_aggregation(
    tmp_path: Path,
) -> None:
    wrong_schema = _write_case(tmp_path / "schema", aggregate.REQUIRED_CASE_IDS[0], 1)
    value = json.loads(wrong_schema.read_text())
    value["schema"] = "milai.dg13u.u1-run-report.v0"
    wrong_schema.write_bytes(_canonical(value) + b"\n")
    with pytest.raises(aggregate.AggregateError, match="schema is invalid"):
        aggregate.aggregate_reports([wrong_schema])

    wrong_status = _write_case(tmp_path / "status", aggregate.REQUIRED_CASE_IDS[0], 1)
    value = json.loads(wrong_status.read_text())
    value["status"] = "PARTIAL"
    wrong_status.write_bytes(_canonical(value) + b"\n")
    with pytest.raises(aggregate.AggregateError, match="status is invalid"):
        aggregate.aggregate_reports([wrong_status])


def test_manifest_binding_drift_fails_g0_without_hiding_later_intrinsic_results(
    tmp_path: Path,
) -> None:
    reports = _matrix(tmp_path)
    manifest = reports[-1].with_name("manifest.json")
    value = json.loads(manifest.read_text())
    value["requested_composition"]["provider_model"] = "AUTO"
    manifest.write_bytes(_canonical(value) + b"\n")

    result = aggregate.aggregate_reports(reports)

    assert result["manifest_binding"]["status"] == "FAIL"
    assert result["gates"]["U1-G0"]["status"] == "FAIL"
    assert result["gates"]["U1-G1"]["intrinsic_status"] == "PASS"
    assert result["gates"]["U1-G1"]["status"] == "BLOCKED"
    assert result["release_label_earned"] is False


@pytest.mark.parametrize(
    ("case_id", "expected_case_maximum"),
    (
        ("U1-RUNTIME-DOWN", 0),
        ("U1-NONE-EN", 1),
        ("U1-ORDINARY-SYNC-TOOL", 2),
    ),
)
def test_manifest_call_policy_binds_the_case_specific_provider_ceiling(
    tmp_path: Path, case_id: str, expected_case_maximum: int
) -> None:
    report = _write_case(tmp_path, case_id, 1)
    manifest_path = report.with_name("manifest.json")
    manifest = json.loads(manifest_path.read_text())

    assert manifest["call_policy"] == {
        **aggregate.CALL_POLICY,
        "provider_calls_case_maximum": expected_case_maximum,
    }
    assert aggregate.aggregate_reports([report])["manifest_binding"]["status"] == (
        "PASS"
    )

    manifest["call_policy"]["provider_calls_case_maximum"] = expected_case_maximum + 1
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    _refresh_artifact_entry(report, manifest_path.name)

    result = aggregate.aggregate_reports([report])
    assert result["manifest_binding"]["status"] == "FAIL"
    assert "CALL_POLICY_DRIFT" in result["manifest_binding"]["reason_codes"]


def test_manifest_terminal_status_is_bound_to_the_report(tmp_path: Path) -> None:
    report = _write_case(tmp_path, "U1-NONE-EN", 1)
    manifest_path = report.with_name("manifest.json")
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "NOT_RUN"
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    _refresh_artifact_entry(report, manifest_path.name)

    result = aggregate.aggregate_reports([report])

    assert result["manifest_binding"]["status"] == "FAIL"
    assert "MANIFEST_STATUS_MISMATCH" in result["manifest_binding"]["reason_codes"]


def test_missing_only_denominator_for_a_safety_counter_cannot_pass_g1(
    tmp_path: Path,
) -> None:
    reports = _matrix(tmp_path)
    reports = [
        path
        for path in reports
        if json.loads(path.read_text())["case_id"] != "U1-REVOKE-REENTRY"
    ]

    result = aggregate.aggregate_reports(reports)

    revoked = result["safety_counters"]["RevokedEvidenceReentry"]
    assert revoked == {"failures": 0, "denominator": 0, "status": "FAIL"}
    assert result["gates"]["U1-G1"]["intrinsic_status"] == "FAIL"
    assert result["release_label_earned"] is False


def test_unaccounted_call_or_retry_fails_reconciliation_and_operations(
    tmp_path: Path,
) -> None:
    reports = _matrix(tmp_path)
    value = json.loads(reports[0].read_text())
    value["calls"]["provider"]["unaccounted"] = 1
    value["calls"]["provider"]["automatic_retries"] = 1
    reports[0].write_bytes(_canonical(value) + b"\n")

    result = aggregate.aggregate_reports(reports)

    assert result["calls"]["provider"]["unaccounted"] == 1
    assert result["calls"]["provider"]["automatic_retries"] == 1
    assert result["calls"]["status"] == "FAIL"
    assert result["gates"]["U1-G4"]["intrinsic_status"] == "FAIL"
    assert result["gates"]["U1-G5"]["intrinsic_status"] == "FAIL"
    assert result["release_label_earned"] is False


def test_missing_wall_or_context_metric_fails_g5_instead_of_inferring(
    tmp_path: Path,
) -> None:
    reports = _matrix(tmp_path)
    value = json.loads(reports[0].read_text())
    value.pop("wall_latency_ms")
    value.pop("context_tokens")
    reports[0].write_bytes(_canonical(value) + b"\n")

    result = aggregate.aggregate_reports(reports)

    assert result["metrics"]["wall_latency_ms"]["status"] == "FAIL"
    assert result["metrics"]["context_tokens"]["status"] == "FAIL"
    assert result["gates"]["U1-G5"]["intrinsic_status"] == "FAIL"
    assert result["release_label_earned"] is False


def test_not_run_and_cleanup_failure_cannot_be_promoted_by_green_local_gates(
    tmp_path: Path,
) -> None:
    reports = _matrix(tmp_path)
    value = json.loads(reports[0].read_text())
    value["status"] = "NOT_RUN"
    value["cleanup"]["status"] = "FAIL"
    value["safety_counters"] = {
        name: {"failures": 0, "denominator": 0, "status": "NOT_RUN"}
        for name in aggregate.SAFETY_COUNTERS
    }
    for kind in ("mcp", "provider"):
        value["calls"][kind]["observed"] = 0
        value["calls"][kind]["status"] = "NOT_RUN"
    reports[0].write_bytes(_canonical(value) + b"\n")

    result = aggregate.aggregate_reports(reports)

    assert result["gates"]["U1-G0"]["status"] != "PASS"
    assert result["gates"]["U1-G4"]["intrinsic_status"] == "FAIL"
    assert result["cleanup"]["status"] == "FAIL"
    assert result["status"] != "PASS"
    assert result["release_label_earned"] is False


def test_cli_requires_explicit_reports_and_writes_atomic_0600_output(
    tmp_path: Path,
) -> None:
    reports = _matrix(tmp_path / "inputs")
    output = tmp_path / "out" / "aggregate.json"
    argv = [item for report in reports for item in ("--report", str(report))]
    argv.extend(("--output", str(output)))

    assert aggregate.main(argv) == 0

    value = json.loads(output.read_text())
    assert value["status"] == "PASS"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(output.parent.glob(f".{output.name}.*"))


def test_status_only_fake_matrix_cannot_earn_release(tmp_path: Path) -> None:
    reports = _matrix(tmp_path)
    for report_path in reports:
        value = json.loads(report_path.read_text())
        value.pop("feature_support")
        value.pop("joined_identities")
        value["artifacts"] = [
            row for row in value["artifacts"] if row["path"] == "manifest.json"
        ]
        report_path.write_bytes(_canonical(value) + b"\n")

    result = aggregate.aggregate_reports(reports)

    assert result["evidence_validation"]["status"] == "FAIL"
    assert result["evidence_validation"]["categories"]["artifacts"]["status"] == (
        "FAIL"
    )
    assert (
        result["evidence_validation"]["categories"]["feature_support"]["status"]
        == "FAIL"
    )
    assert result["release_label_earned"] is False
    assert result["status"] != "PASS"


@pytest.mark.parametrize(
    ("case_id", "bad_tokens", "reason_code"),
    (
        ("U1-EXACT-TARGET-EN", 0, "MEMORY_CONTEXT_TOKENS_NOT_POSITIVE"),
        ("U1-CACHE-FALLBACK", 0, "MEMORY_CONTEXT_TOKENS_NOT_POSITIVE"),
        ("U1-TASK-RETURN", 0, "MEMORY_CONTEXT_TOKENS_NOT_POSITIVE"),
        ("U1-NONE-EN", 1, "NON_MEMORY_OR_TERMINAL_CONTEXT_TOKENS_NOT_ZERO"),
        ("U1-PROVIDER-DOWN", 1, "NON_MEMORY_OR_TERMINAL_CONTEXT_TOKENS_NOT_ZERO"),
        ("U1-WRONG-TASK", 0, "MEMORY_CONTEXT_TOKENS_NOT_POSITIVE"),
        ("U1-WRONG-SCOPE", 0, "MEMORY_CONTEXT_TOKENS_NOT_POSITIVE"),
        ("U1-STALE-CURRENT", 0, "MEMORY_CONTEXT_TOKENS_NOT_POSITIVE"),
        ("U1-ADAPTER-RESTART", 0, "MEMORY_CONTEXT_TOKENS_NOT_POSITIVE"),
        ("U1-STREAM", 0, "MEMORY_CONTEXT_TOKENS_NOT_POSITIVE"),
    ),
)
def test_context_tokens_are_case_specific_and_never_inferred(
    tmp_path: Path, case_id: str, bad_tokens: int, reason_code: str
) -> None:
    report = _write_case(tmp_path, case_id, 1)
    value = json.loads(report.read_text())
    value["context_tokens"] = bad_tokens
    report.write_bytes(_canonical(value) + b"\n")

    result = aggregate.aggregate_reports([report])

    case = _case_evidence(result, case_id)
    assert reason_code in case["categories"]["context_tokens"]["reason_codes"]
    assert result["release_label_earned"] is False


def test_provider_and_exact_memory_join_hashes_are_required(tmp_path: Path) -> None:
    provider = _write_case(tmp_path / "provider", "U1-NONE-EN", 1)
    value = json.loads(provider.read_text())
    value["joined_identities"]["provider_native_request_id_sha256"] = None
    provider.write_bytes(_canonical(value) + b"\n")
    result = aggregate.aggregate_reports([provider])
    reasons = _case_evidence(result, "U1-NONE-EN")["categories"]["joined_identities"][
        "reason_codes"
    ]
    assert "PROVIDER_NATIVE_REQUEST_ID_HASH_MISSING" in reasons

    exact = _write_case(tmp_path / "exact", "U1-EXACT-TARGET-CN", 2)
    value = json.loads(exact.read_text())
    value["joined_identities"]["access_id_sha256"] = None
    value["joined_identities"]["mcp_receipt_sha256"] = "not-a-hash"
    value["joined_identities"]["runtime_trace_sha256"] = None
    exact.write_bytes(_canonical(value) + b"\n")
    result = aggregate.aggregate_reports([exact])
    reasons = _case_evidence(result, "U1-EXACT-TARGET-CN")["categories"][
        "joined_identities"
    ]["reason_codes"]
    assert {
        "ACCESS_ID_SHA256_MISSING",
        "MCP_RECEIPT_SHA256_MISSING",
        "RUNTIME_TRACE_SHA256_MISSING",
    }.issubset(reasons)


def test_provider_fault_accepts_truthful_missing_native_id_without_weakening_success_cases(
    tmp_path: Path,
) -> None:
    report_path = _write_case(tmp_path, "U1-PROVIDER-DOWN", 1)
    report = json.loads(report_path.read_text())
    report["joined_identities"]["provider_native_request_id_sha256"] = None
    report_path.write_bytes(_canonical(report) + b"\n")

    result = aggregate.aggregate_reports([report_path])
    category = _case_evidence(result, "U1-PROVIDER-DOWN")["categories"][
        "joined_identities"
    ]

    assert category["status"] == "PASS"
    assert "PROVIDER_NATIVE_REQUEST_ID_HASH_MISSING" not in category["reason_codes"]


def test_required_artifact_hash_schema_status_and_identity_are_validated(
    tmp_path: Path,
) -> None:
    report = _write_case(tmp_path, "U1-NONE-EN", 1)
    artifact = report.with_name("exact-product-manifest.json")
    value = json.loads(artifact.read_text())
    value["schema"] = "milai.dg13u.u1-exact-product-manifest.v0"
    value["status"] = "NOT_RUN"
    value["run_id"] = "different-run"
    value["case_id"] = "U1-NONE-CN"
    artifact.write_bytes(_canonical(value) + b"\n")
    _refresh_artifact_entry(report, artifact.name)

    result = aggregate.aggregate_reports([report])

    reasons = _case_evidence(result, "U1-NONE-EN")["categories"]["artifacts"][
        "reason_codes"
    ]
    assert {
        "ARTIFACT_EXACT_PRODUCT_MANIFEST_SCHEMA_INVALID",
        "ARTIFACT_EXACT_PRODUCT_MANIFEST_STATUS_MISMATCH",
        "ARTIFACT_EXACT_PRODUCT_MANIFEST_RUN_ID_MISMATCH",
        "ARTIFACT_EXACT_PRODUCT_MANIFEST_CASE_ID_MISMATCH",
    }.issubset(reasons)

    artifact.write_bytes(artifact.read_bytes() + b" ")
    result = aggregate.aggregate_reports([report])
    reasons = _case_evidence(result, "U1-NONE-EN")["categories"]["artifacts"][
        "reason_codes"
    ]
    assert "ARTIFACT_EXACT_PRODUCT_MANIFEST_BYTES_MISMATCH" in reasons
    assert "ARTIFACT_EXACT_PRODUCT_MANIFEST_SHA256_MISMATCH" in reasons


def test_artifact_statuses_follow_their_own_schema_semantics(tmp_path: Path) -> None:
    report = _write_case(
        tmp_path,
        "U1-NONE-EN",
        1,
        status="FAIL",
        cleanup_status="PASS",
    )

    result = aggregate.aggregate_reports([report])
    artifacts = _case_evidence(result, "U1-NONE-EN")["categories"]["artifacts"]

    assert artifacts == {"status": "PASS", "reason_codes": []}
    assert (
        json.loads(report.with_name("exact-product-manifest.json").read_text())[
            "status"
        ]
        == "PASS"
    )
    assert (
        json.loads(report.with_name("identity-preflight.json").read_text())["status"]
        == "PASS"
    )
    assert (
        json.loads(report.with_name("cleanup-receipt.json").read_text())["status"]
        == "PASS"
    )


@pytest.mark.parametrize(
    "artifact_name",
    (
        "exact-product-manifest.json",
        "identity-preflight.json",
        "cleanup-receipt.json",
    ),
)
def test_run_bound_artifacts_require_the_exact_case_id(
    tmp_path: Path, artifact_name: str
) -> None:
    report = _write_case(tmp_path, "U1-NONE-EN", 1)
    artifact = report.with_name(artifact_name)
    value = json.loads(artifact.read_text())
    value.pop("case_id")
    artifact.write_bytes(_canonical(value) + b"\n")
    _refresh_artifact_entry(report, artifact_name)

    result = aggregate.aggregate_reports([report])
    token = artifact_name.removesuffix(".json").replace("-", "_").upper()
    reasons = _case_evidence(result, "U1-NONE-EN")["categories"]["artifacts"][
        "reason_codes"
    ]

    assert f"ARTIFACT_{token}_CASE_ID_MISMATCH" in reasons


def test_cleanup_status_binds_report_cleanup_not_report_terminal_status(
    tmp_path: Path,
) -> None:
    report = _write_case(
        tmp_path,
        "U1-NONE-EN",
        1,
        status="FAIL",
        cleanup_status="PASS",
    )
    cleanup = report.with_name("cleanup-receipt.json")
    value = json.loads(cleanup.read_text())
    value["status"] = "FAIL"
    cleanup.write_bytes(_canonical(value) + b"\n")
    _refresh_artifact_entry(report, cleanup.name)

    result = aggregate.aggregate_reports([report])
    reasons = _case_evidence(result, "U1-NONE-EN")["categories"]["artifacts"][
        "reason_codes"
    ]

    assert "ARTIFACT_CLEANUP_RECEIPT_STATUS_MISMATCH" in reasons


def test_recovery_plan_requires_only_schema_and_run_binding(tmp_path: Path) -> None:
    report = _write_case(tmp_path, "U1-NONE-EN", 1)
    plan = report.with_name("recovery-resource-plan.json")
    value = json.loads(plan.read_text())
    assert "case_id" not in value
    assert "status" not in value

    result = aggregate.aggregate_reports([report])
    reasons = _case_evidence(result, "U1-NONE-EN")["categories"]["artifacts"][
        "reason_codes"
    ]

    assert not any("RECOVERY_RESOURCE_PLAN_CASE_ID" in reason for reason in reasons)
    assert not any("RECOVERY_RESOURCE_PLAN_STATUS" in reason for reason in reasons)


def test_readiness_security_and_reconciliation_must_be_explicit(
    tmp_path: Path,
) -> None:
    report = _write_case(tmp_path, "U1-NONE-EN", 1)
    readiness = report.with_name("readiness.json")
    value = json.loads(readiness.read_text())
    value["host"] = "NOT_RUN"
    value["security"]["forbidden_environment_names"] = ["MILAI_TOKEN"]
    value["security"]["network_internal"] = False
    readiness.write_bytes(_canonical(value) + b"\n")
    _refresh_artifact_entry(report, readiness.name)

    reconciliation = report.with_name("reconciliation.json")
    value = json.loads(reconciliation.read_text())
    value["unaccounted_calls"] = 1
    value["durable_credentials_found"] = 1
    reconciliation.write_bytes(_canonical(value) + b"\n")
    _refresh_artifact_entry(report, reconciliation.name)

    cleanup = report.with_name("cleanup-receipt.json")
    value = json.loads(cleanup.read_text())
    value["existing_vllm_preserved"] = False
    value["external_lifecycle_mutations"] = 1
    value["items"] = []
    cleanup.write_bytes(_canonical(value) + b"\n")
    _refresh_artifact_entry(report, cleanup.name)

    result = aggregate.aggregate_reports([report])
    case = _case_evidence(result, "U1-NONE-EN")

    assert case["categories"]["readiness_security"]["status"] == "FAIL"
    assert case["categories"]["reconciliation"]["status"] == "FAIL"
    assert {
        "RECONCILIATION_UNACCOUNTED_CALLS_NOT_ZERO",
        "RECONCILIATION_CREDENTIALS_NOT_ZERO",
        "CLEANUP_EXTERNAL_VLLM_NOT_PRESERVED",
        "CLEANUP_EXTERNAL_VLLM_MUTATED",
        "CLEANUP_EXTERNAL_VLLM_RECEIPT_MISSING",
    }.issubset(case["categories"]["reconciliation"]["reason_codes"])


@pytest.mark.parametrize(
    ("mutation", "artifact_name", "reason_code"),
    (
        (
            lambda report, _plan, _receipt: report["cleanup"].update(
                recovery_plan_sha256="A" * 64
            ),
            None,
            "CLEANUP_RECOVERY_PLAN_SHA256_INVALID",
        ),
        (
            lambda _report, plan, _receipt: plan.update(run_id="different-run"),
            "recovery-resource-plan.json",
            "RECOVERY_PLAN_RUN_ID_MISMATCH",
        ),
        (
            lambda _report, _plan, receipt: receipt["recovery_plan"].update(
                sha256="0" * 64
            ),
            "cleanup-receipt.json",
            "CLEANUP_RECOVERY_PLAN_SHA256_MISMATCH",
        ),
        (
            lambda _report, _plan, receipt: receipt["items"][0].update(attempts=1),
            "cleanup-receipt.json",
            "CLEANUP_EXTERNAL_VLLM_RECEIPT_MISSING",
        ),
    ),
)
def test_recovery_plan_or_cleanup_binding_drift_fails_g4_and_g5_intrinsically(
    tmp_path: Path,
    mutation: object,
    artifact_name: str | None,
    reason_code: str,
) -> None:
    reports = _matrix(tmp_path)
    target = reports[0]
    report = json.loads(target.read_text())
    plan_path = target.with_name("recovery-resource-plan.json")
    receipt_path = target.with_name("cleanup-receipt.json")
    plan = json.loads(plan_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    assert callable(mutation)
    mutation(report, plan, receipt)
    target.write_bytes(_canonical(report) + b"\n")
    plan_path.write_bytes(_canonical(plan) + b"\n")
    receipt_path.write_bytes(_canonical(receipt) + b"\n")
    if artifact_name is not None:
        _refresh_artifact_entry(target, artifact_name)

    result = aggregate.aggregate_reports(reports)

    case = _case_evidence(result, aggregate.REQUIRED_CASE_IDS[0])
    assert reason_code in case["categories"]["reconciliation"]["reason_codes"]
    assert result["gates"]["U1-G4"]["intrinsic_status"] == "FAIL"
    assert result["gates"]["U1-G5"]["intrinsic_status"] == "FAIL"
    assert result["release_label_earned"] is False


def test_all_frozen_fault_cases_have_conditionally_required_execution_evidence(
    tmp_path: Path,
) -> None:
    assert len(fault_scenarios.FAULT_SCENARIOS) == 13
    assert aggregate.FAULT_CASE_IDS == frozenset(fault_scenarios.FAULT_SCENARIOS)
    reports = [
        _write_case(tmp_path, case_id, index)
        for index, case_id in enumerate(sorted(aggregate.FAULT_CASE_IDS), start=1)
    ]

    result = aggregate.aggregate_reports(reports)

    assert result["evidence_validation"]["categories"]["fault_execution"] == {
        "status": "PASS",
        "failed_case_ids": [],
    }
    for case_id in aggregate.FAULT_CASE_IDS:
        category = _case_evidence(result, case_id)["categories"]["fault_execution"]
        assert category == {"status": "PASS", "reason_codes": []}


def test_non_fault_case_does_not_require_fault_execution_artifact(
    tmp_path: Path,
) -> None:
    report = _write_case(tmp_path, "U1-NONE-EN", 1)

    result = aggregate.aggregate_reports([report])

    case = _case_evidence(result, "U1-NONE-EN")
    assert case["categories"]["fault_execution"] == {
        "status": "PASS",
        "reason_codes": [],
    }
    assert not report.with_name("fault-execution.json").exists()


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        ("schema", "FAULT_EXECUTION_SCHEMA_INVALID"),
        ("status", "FAULT_EXECUTION_STATUS_NOT_PASS"),
        ("run_id", "FAULT_EXECUTION_RUN_ID_MISMATCH"),
        ("case_id", "FAULT_EXECUTION_CASE_ID_MISMATCH"),
        ("host_reason", "FAULT_EXECUTION_HOST_TERMINAL_MISMATCH"),
        ("exact_calls", "FAULT_EXECUTION_EXACT_CALLS_MISMATCH"),
        ("retries", "FAULT_EXECUTION_AUTOMATIC_RETRIES_NOT_ZERO"),
        ("barrier", "FAULT_EXECUTION_PROVIDER_BARRIER_MISMATCH"),
        ("external_attempts", "FAULT_EXECUTION_EXTERNAL_ATTEMPTS_NOT_ZERO"),
        (
            "external_lifecycle",
            "FAULT_EXECUTION_EXTERNAL_LIFECYCLE_MUTATIONS_NOT_ZERO",
        ),
        ("vllm_attempts", "FAULT_EXECUTION_EXTERNAL_VLLM_INVALID"),
        ("vllm_lifecycle", "FAULT_EXECUTION_EXTERNAL_VLLM_INVALID"),
    ),
)
def test_fault_execution_contract_fields_fail_closed(
    tmp_path: Path, mutation: str, reason_code: str
) -> None:
    report = _write_case(tmp_path, "U1-BROKER-DOWN", 1)
    _mutate_fault_execution(report, mutation)

    result = aggregate.aggregate_reports([report])

    category = _case_evidence(result, "U1-BROKER-DOWN")["categories"]["fault_execution"]
    assert category["status"] == "FAIL"
    assert reason_code in category["reason_codes"]
    assert result["release_label_earned"] is False


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        ("missing", "FAULT_EXECUTION_ARTIFACT_MISSING"),
        ("host_reason", "FAULT_EXECUTION_HOST_TERMINAL_MISMATCH"),
        ("barrier", "FAULT_EXECUTION_PROVIDER_BARRIER_MISMATCH"),
    ),
)
def test_missing_wrong_reason_or_wrong_barrier_fails_g4(
    tmp_path: Path, mutation: str, reason_code: str
) -> None:
    reports = _matrix(tmp_path)
    target = next(
        report
        for report in reports
        if json.loads(report.read_text())["case_id"] == "U1-BROKER-DOWN"
    )
    if mutation == "missing":
        _remove_artifact(target, "fault-execution.json")
    else:
        _mutate_fault_execution(target, mutation)

    result = aggregate.aggregate_reports(reports)

    category = _case_evidence(result, "U1-BROKER-DOWN")["categories"]["fault_execution"]
    assert category["status"] == "FAIL"
    assert reason_code in category["reason_codes"]
    if mutation == "missing":
        assert (
            "ARTIFACT_FAULT_EXECUTION_MISSING"
            in _case_evidence(result, "U1-BROKER-DOWN")["categories"]["artifacts"][
                "reason_codes"
            ]
        )
    assert result["gates"]["U1-G4"]["intrinsic_status"] == "FAIL"
    assert result["release_label_earned"] is False
