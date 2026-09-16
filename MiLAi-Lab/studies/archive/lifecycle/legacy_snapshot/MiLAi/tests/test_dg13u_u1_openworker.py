from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from scripts import dg13u_u1_cleanup as recovery_cleanup
from scripts import dg13u_u1_openworker as runner
from scripts import dg13u_u1_task_scenarios as task_scenarios

_CACHE_GOVERNANCE_CASES = {
    "U1-CACHE-FALLBACK",
    "U1-WRONG-TASK",
    "U1-WRONG-SCOPE",
    "U1-STALE-CURRENT",
    "U1-REVOKE-REENTRY",
    "U1-AUTHORITY-ESCALATION",
    "U1-ALIAS-COLLISION",
    "U1-OPEN-ISSUE",
}


def _configure_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    root = tmp_path / "cra-workspace"
    runs = root / "var/dg13/runs"
    temporary = root / "var/dg13/tmp"
    uds = tmp_path / "dev-shm-milai"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "RUNS_ROOT", runs)
    monkeypatch.setattr(runner, "TMP_ROOT", temporary)
    monkeypatch.setattr(runner, "UDS_ROOT", uds)
    monkeypatch.setattr(recovery_cleanup, "ROOT", root)
    monkeypatch.setattr(recovery_cleanup, "RUNS_ROOT", runs)
    monkeypatch.setattr(recovery_cleanup, "TMP_ROOT", temporary)
    monkeypatch.setattr(recovery_cleanup, "UDS_ROOT", uds)
    monkeypatch.setattr(runner.u0, "_is_cra_path", lambda _path: True)
    bindings = {
        "INTERFACE_FREEZE": "interface",
        "EXECUTION_OVERRIDE": "override",
        "HEADER_CONTRACT": "headers",
    }
    for attribute, content in bindings.items():
        path = root / f"contracts/{content}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        monkeypatch.setattr(runner, attribute, path)
    fixture = root / "contracts/fixture.json"
    fixture.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(runner, "CANDIDATE_FIXTURE", fixture)
    monkeypatch.setattr(
        runner,
        "_REQUIRED_FIXTURE_SHA256",
        runner.hashlib.sha256(fixture.read_bytes()).hexdigest(),
    )
    return runs, temporary, uds


def test_list_cases_exposes_single_case_selectors_without_running_any_case() -> None:
    cases = runner.list_cases()
    assert cases
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert {"U1-NONE-EN", "U1-EXACT-TARGET-CN", "U1-CACHE-FALLBACK"}.issubset(
        {case["case_id"] for case in cases}
    )
    assert {
        "U1-EXACT-DATABASE-EN",
        "U1-EXACT-DATABASE-CN",
        "U1-EXACT-DECISION-EN",
        "U1-EXACT-DECISION-CN",
        "U1-ALIAS-COLLISION",
        "U1-OPEN-ISSUE",
        "U1-BROKER-DOWN",
        "U1-BROKER-MALFORMED",
        "U1-BROKER-TIMEOUT",
        "U1-PROVIDER-DOWN",
        "U1-PROVIDER-MALFORMED",
        "U1-PROVIDER-TIMEOUT",
        "U1-BROKER-INODE-RECREATE",
        "U1-ADAPTER-RESTART",
        "U1-STREAM",
        "U1-ORDINARY-SYNC-TOOL",
        "U1-TASK-CONTINUE",
        "U1-TASK-SWITCH",
        "U1-TASK-RETURN",
        "U1-TASK-CONCURRENT",
        "U1-RUNTIME-DOWN",
        "U1-RUNTIME-MALFORMED",
        "U1-RUNTIME-TIMEOUT",
        "U1-MCP-CHILD-DOWN",
        "U1-MCP-CHILD-MALFORMED",
        "U1-MCP-CHILD-TIMEOUT",
    }.issubset({case["case_id"] for case in cases})
    assert runner.main(["--list-cases"]) == 0


def test_operator_script_lists_cases_when_invoked_by_file_path() -> None:
    completed = subprocess.run(
        [sys.executable, str(Path(runner.__file__).resolve()), "--list-cases"],
        cwd=Path(runner.__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == runner.list_cases()


def test_unknown_case_is_rejected_before_any_filesystem_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary, uds = _configure_roots(tmp_path, monkeypatch)
    with pytest.raises(runner.RunError, match="unsupported case_id"):
        runner.run_case("dg13u-u1-unknown", "U1-UNKNOWN")
    assert not runs.exists()
    assert not temporary.exists()
    assert not uds.exists()


def test_pending_composition_writes_typed_not_run_report_and_cleans_owned_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary, uds = _configure_roots(tmp_path, monkeypatch)
    run_id = "dg13u-u1-pending"
    report = runner.run_case(run_id, "U1-EXACT-TARGET-CN")
    run_dir = runs / run_id

    assert report["status"] == "NOT_RUN"
    assert report["release_label_earned"] is False
    assert report["wall_latency_ms"] >= 0
    assert report["context_tokens"] == 0
    assert report["gates"] == {
        f"U1-G{index}": {
            "status": "NOT_RUN",
            "reason_code": "U1_LOCAL_COMPOSITION_DRIVER_PENDING",
        }
        for index in range(6)
    }
    assert set(report["safety_counters"]) == set(runner.SAFETY_COUNTERS)
    assert all(
        value == {"failures": 0, "denominator": 0, "status": "NOT_RUN"}
        for value in report["safety_counters"].values()
    )
    assert (
        report["feature_support"]["delayed_or_asynchronous_tool_result"]
        == "UNSUPPORTED"
    )
    assert report["calls"]["provider"]["observed"] == 0
    assert report["calls"]["provider"]["automatic_retries"] == 0
    assert not (temporary / run_id).exists()
    assert not (uds / runner._short_run_id(run_id)).exists()
    assert run_dir.is_dir()
    cleanup = json.loads((run_dir / "cleanup-receipt.json").read_text())
    assert cleanup["case_id"] == "U1-EXACT-TARGET-CN"
    assert cleanup["status"] == "PASS"
    assert cleanup["existing_vllm_preserved"] is True
    assert cleanup["external_lifecycle_mutations"] == 0
    assert any(
        item["kind"] == "external_vllm" and item["state"] == "preserved_external"
        for item in cleanup["items"]
    )
    plan_path = run_dir / recovery_cleanup.PLAN_NAME
    plan = json.loads(plan_path.read_text())
    assert plan["schema"] == recovery_cleanup.PLAN_SCHEMA
    assert {row["kind"] for row in plan["resources"]} >= {
        "external_vllm",
        "temporary_root",
        "uds_root",
        "database",
        "docker_network",
        "docker_container",
    }
    assert cleanup["recovery_plan"] == {
        "schema": recovery_cleanup.PLAN_SCHEMA,
        "path": str(plan_path),
        "sha256": runner.hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "status": "PASS",
    }
    external_vllm = next(
        item for item in cleanup["items"] if item["kind"] == "external_vllm"
    )
    assert external_vllm["attempts"] == 0
    assert (
        report["cleanup"]["recovery_plan_sha256"] == cleanup["recovery_plan"]["sha256"]
    )
    assert plan_path.stat().st_mode & 0o777 == 0o600
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "NOT_RUN"
    assert manifest["scope"]["delayed_or_asynchronous_tool_result"] == "UNSUPPORTED"
    assert manifest["call_policy"] == {
        "provider_automatic_retries": 0,
        "mcp_automatic_retries": 0,
        "provider_calls_per_turn_maximum": 1,
        "provider_calls_case_maximum": 1,
    }


def test_final_product_binding_detects_exact_manifest_drift(tmp_path: Path) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths("dg13u-u1-product-binding", durable, temporary, uds)
    exact = {
        "schema": "milai.dg13u.u1-exact-product-manifest.v1",
        "run_id": paths.run_id,
        "case_id": "U1-NONE-EN",
        "status": "PASS",
    }
    runner._atomic_write(durable / "exact-product-manifest.json", exact)
    identity = {
        "schema": "milai.dg13u.u1-identity-preflight.v1",
        "run_id": paths.run_id,
        "case_id": "U1-NONE-EN",
        "status": "PASS",
        "exact_product": exact,
    }
    runner._atomic_write(durable / "identity-preflight.json", identity)
    manifest = {
        "schema": "milai.dg13u.u1-run-manifest.v1",
        "run_id": paths.run_id,
        "case_id": "U1-NONE-EN",
        "resolved_composition": {
            "exact_product": exact,
            "exact_product_manifest": runner.u0._file_identity(
                durable / "exact-product-manifest.json", relative_to=durable
            ),
        },
    }
    runner._atomic_write(durable / "manifest.json", manifest)

    runner._verify_final_product_binding(paths, identity)

    runner._atomic_write(
        durable / "exact-product-manifest.json", {**exact, "status": "FAIL"}
    )
    with pytest.raises(runner.RunError, match="final exact product binding drifted"):
        runner._verify_final_product_binding(paths, identity)


def test_original_stage_failure_survives_final_evidence_persistence_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, _temporary, _uds = _configure_roots(tmp_path, monkeypatch)
    driver = runner.LocalComposition(tmp_path / "unused.env")
    original_sha256 = "a" * 64
    monkeypatch.setattr(
        driver,
        "start",
        lambda *_args: runner.CompositionResult(
            runner.TerminalStatus.PASS, "STARTED", {}
        ),
    )
    monkeypatch.setattr(
        driver,
        "readiness",
        lambda *_args: runner.CompositionResult(
            runner.TerminalStatus.PASS, "READY", {}
        ),
    )
    monkeypatch.setattr(
        driver,
        "smoke",
        lambda *_args: runner.CompositionResult(
            runner.TerminalStatus.FAIL,
            "ORIGINAL_FAILURE",
            {
                "error_type": "OriginalFailure",
                "error_message_sha256": original_sha256,
            },
        ),
    )
    monkeypatch.setattr(
        driver,
        "write_final_evidence_artifacts",
        lambda *_args: (_ for _ in ()).throw(OSError("secondary evidence write")),
    )

    report = runner.run_case(
        "dg13u-u1-secondary-evidence", "U1-NONE-EN", composition=driver
    )

    assert report["error"] == {
        "type": "OriginalFailure",
        "message_sha256": original_sha256,
    }
    assert report["secondary_errors"] == [
        {
            "stage": "final_evidence_persistence",
            "type": "OSError",
            "message_sha256": runner.hashlib.sha256(
                b"secondary evidence write"
            ).hexdigest(),
        }
    ]
    assert (runs / "dg13u-u1-secondary-evidence" / "report.json").is_file()


@pytest.mark.parametrize(
    ("failure_target", "secondary_stage"),
    [
        ("cleanup-receipt.json", "cleanup_receipt_persistence"),
        ("manifest.json", "final_manifest"),
    ],
)
def test_original_stage_failure_survives_secondary_terminal_persistence_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_target: str,
    secondary_stage: str,
) -> None:
    _configure_roots(tmp_path, monkeypatch)
    original_sha256 = "b" * 64

    class OriginalFailureComposition(runner.PendingLocalComposition):
        def start(self, *_args):  # type: ignore[no-untyped-def]
            return runner.CompositionResult(
                runner.TerminalStatus.FAIL,
                "ORIGINAL_FAILURE",
                {
                    "error_type": "OriginalFailure",
                    "error_message_sha256": original_sha256,
                },
            )

    original_write = runner._atomic_write
    calls = {"manifest": 0}

    def write(path, value):  # type: ignore[no-untyped-def]
        if path.name == "manifest.json":
            calls["manifest"] += 1
        should_fail = path.name == failure_target and (
            failure_target != "manifest.json" or calls["manifest"] == 2
        )
        if should_fail:
            raise OSError(f"secondary {secondary_stage}")
        original_write(path, value)

    monkeypatch.setattr(runner, "_atomic_write", write)

    report = runner.run_case(
        f"dg13u-u1-secondary-{secondary_stage.replace('_', '-')}",
        "U1-NONE-EN",
        composition=OriginalFailureComposition(),
    )

    assert report["error"] == {
        "type": "OriginalFailure",
        "message_sha256": original_sha256,
    }
    assert [row["stage"] for row in report["secondary_errors"]] == [secondary_stage]
    assert report["secondary_errors"][0]["type"] == "OSError"


def test_reserve_writes_plan_after_durable_but_before_first_deletable_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary, uds = _configure_roots(tmp_path, monkeypatch)
    run_id = "dg13u-u1-plan-order"
    calls: list[str] = []
    original = recovery_cleanup.write_resource_plan

    def write(*args, **kwargs):  # type: ignore[no-untyped-def]
        assert (runs / run_id).is_dir()
        assert not (temporary / run_id).exists()
        assert not (uds / runner._short_run_id(run_id)).exists()
        calls.append("plan")
        return original(*args, **kwargs)

    monkeypatch.setattr(recovery_cleanup, "write_resource_plan", write)
    paths = runner.RunPaths.reserve(run_id)

    assert calls == ["plan"]
    assert paths.recovery is not None
    assert (
        paths.recovery.sha256
        == runner.hashlib.sha256(
            (runs / run_id / recovery_cleanup.PLAN_NAME).read_bytes()
        ).hexdigest()
    )


def test_existing_recovery_plan_fails_closed_with_explicit_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, _temporary, _uds = _configure_roots(tmp_path, monkeypatch)
    run_id = "dg13u-u1-needs-recovery"
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    plan = run_dir / recovery_cleanup.PLAN_NAME
    plan.write_text("preserve", encoding="utf-8")

    with pytest.raises(runner.RunError) as raised:
        runner.RunPaths.reserve(run_id)

    message = str(raised.value)
    assert "dg13u_u1_cleanup.py" in message
    assert f"--plan {plan}" in message
    assert f"--run-id {run_id}" in message
    assert "--env-file <ABSOLUTE_ENV_FILE>" in message
    assert "--execute-local" in message
    assert plan.read_text(encoding="utf-8") == "preserve"


def test_process_identity_is_cas_persisted_with_stable_proc_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, _temporary, _uds = _configure_roots(tmp_path, monkeypatch)
    run_id = "dg13u-u1-process-plan"
    paths = runner.RunPaths.reserve(run_id)
    assert paths.recovery is not None
    before = paths.recovery.sha256

    paths.recovery.record_process("runtime-api", 12345, "67890")

    plan_path = runs / run_id / recovery_cleanup.PLAN_NAME
    plan = json.loads(plan_path.read_text())
    process = next(row for row in plan["resources"] if row["kind"] == "process")
    assert process == {
        "kind": "process",
        "ownership": "RUN_OWNED",
        "role": "runtime-api",
        "pid": 12345,
        "proc_start_marker": "67890",
    }
    assert paths.recovery.sha256 != before
    assert (
        paths.recovery.binding()["sha256"]
        == runner.hashlib.sha256(plan_path.read_bytes()).hexdigest()
    )


def test_process_plan_cas_failure_is_terminal_and_does_not_keep_partial_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_roots(tmp_path, monkeypatch)
    paths = runner.RunPaths.reserve("dg13u-u1-cas-negative")
    assert paths.recovery is not None
    original = paths.recovery.binding()

    def reject(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise recovery_cleanup.CleanupError("synthetic stale digest")

    monkeypatch.setattr(recovery_cleanup, "write_resource_plan", reject)
    with pytest.raises(runner.RunError, match="CAS update failed"):
        paths.recovery.record_process("runtime-api", 12345, "67890")

    assert paths.recovery.binding() == original
    assert all(row["kind"] != "process" for row in paths.recovery._ordered_resources())


def test_plan_binding_drift_still_emits_typed_failed_cleanup_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_roots(tmp_path, monkeypatch)
    paths = runner.RunPaths.reserve("dg13u-u1-binding-drift")
    assert paths.recovery is not None
    paths.recovery.plan_path.write_text("tampered", encoding="utf-8")
    registry = runner.ResourceRegistry(paths.run_id, paths.recovery)

    receipt = registry.cleanup_all()

    assert receipt["status"] == "FAIL"
    assert receipt["recovery_plan"]["status"] == "FAIL"
    assert receipt["recovery_plan"]["expected_sha256"] == paths.recovery.sha256
    assert (
        receipt["recovery_plan"]["observed_sha256"]
        == runner.hashlib.sha256(b"tampered").hexdigest()
    )
    assert receipt["recovery_plan"]["error_type"] == "RunError"


def test_process_marker_must_be_two_consecutive_stable_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = iter([None, "10", "11", "11"])
    monkeypatch.setattr(runner, "_process_marker", lambda _pid: next(values))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    assert runner._stable_process_marker(12345) == "11"


def test_unstable_process_marker_fails_without_plan_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_process_marker", lambda _pid: None)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    with pytest.raises(runner.RunError, match="did not stabilize"):
        runner._stable_process_marker(12345)
    assert {
        case_id: (
            runner.CASES[case_id].expected_mcp_calls,
            runner.CASES[case_id].expected_provider_calls,
        )
        for case_id in (
            "U1-TASK-CONTINUE",
            "U1-TASK-SWITCH",
            "U1-TASK-RETURN",
            "U1-TASK-CONCURRENT",
        )
    } == {
        "U1-TASK-CONTINUE": (2, 2),
        "U1-TASK-SWITCH": (2, 2),
        "U1-TASK-RETURN": (3, 3),
        "U1-TASK-CONCURRENT": (2, 2),
    }


def test_keyboard_interrupt_still_runs_owned_cleanup_finally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary, uds = _configure_roots(tmp_path, monkeypatch)

    class Interrupted:
        def start(self, paths, case, resources):  # type: ignore[no-untyped-def]
            del paths, case, resources
            raise KeyboardInterrupt

        def readiness(self, paths, case):  # type: ignore[no-untyped-def]
            raise AssertionError((paths, case))

        def smoke(self, paths, case):  # type: ignore[no-untyped-def]
            raise AssertionError((paths, case))

        def reconciliation(self, paths, case):  # type: ignore[no-untyped-def]
            raise AssertionError((paths, case))

    run_id = "dg13u-u1-interrupted"
    with pytest.raises(KeyboardInterrupt):
        runner.run_case(
            run_id,
            "U1-NONE-EN",
            composition=Interrupted(),
        )
    cleanup = json.loads((runs / run_id / "cleanup-receipt.json").read_text())
    assert cleanup["status"] == "PASS"
    assert cleanup["existing_vllm_preserved"] is True
    assert not (temporary / run_id).exists()
    assert not (uds / runner._short_run_id(run_id)).exists()


def test_failed_smoke_retains_measured_call_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, _temporary, _uds = _configure_roots(tmp_path, monkeypatch)

    class FailedSmoke:
        def start(self, paths, case, resources):  # type: ignore[no-untyped-def]
            del paths, case, resources
            return runner.CompositionResult(runner.TerminalStatus.PASS, "STARTED", {})

        def readiness(self, paths, case):  # type: ignore[no-untyped-def]
            del paths, case
            return runner.CompositionResult(runner.TerminalStatus.PASS, "READY", {})

        def smoke(self, paths, case):  # type: ignore[no-untyped-def]
            del paths, case
            return runner.CompositionResult(
                runner.TerminalStatus.FAIL,
                "MEASURED_PROVIDER_FAILURE",
                {
                    "observed_provider_calls": 1,
                    "observed_mcp_calls": 0,
                    "unaccounted_calls": 0,
                },
            )

        def reconciliation(self, paths, case):  # type: ignore[no-untyped-def]
            raise AssertionError((paths, case))

    report = runner.run_case(
        "dg13u-u1-measured-fail",
        "U1-NONE-EN",
        composition=FailedSmoke(),
    )

    assert report["status"] == "FAIL"
    assert report["calls"]["provider"]["observed"] == 1
    assert report["calls"]["provider"]["status"] == "FAIL"
    assert report["calls"]["mcp"]["observed"] == 0
    persisted = json.loads(
        (runs / "dg13u-u1-measured-fail" / "report.json").read_text()
    )
    assert persisted["calls"] == report["calls"]


def test_local_composition_runs_fresh_u1_lifecycle_and_none_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary, uds = _configure_roots(tmp_path, monkeypatch)
    original_file_identity = runner.u0._file_identity

    def file_identity(path: Path, *, relative_to: Path | None = None):  # type: ignore[no-untyped-def]
        if relative_to is not None and not path.is_relative_to(relative_to):
            relative_to = None
        return original_file_identity(path, relative_to=relative_to)

    monkeypatch.setattr(runner.u0, "_file_identity", file_identity)
    monkeypatch.setattr(
        runner.u0,
        "_collect_source_identity",
        lambda: {"sha256": "a" * 64, "git_sha": None, "entries": []},
    )
    monkeypatch.setattr(
        runner.u0,
        "_build_and_probe_packages",
        lambda _run, _temp: {
            "migration_head": "0028_dg11_window_projection",
            "artifacts": {},
        },
    )
    monkeypatch.setattr(
        runner.u0,
        "_run_json",
        lambda _argv: [
            {
                "Id": "sha256:u1-image",
                "Created": "2026-08-25T00:00:00Z",
                "Architecture": "amd64",
                "Os": "linux",
            }
        ],
    )
    monkeypatch.setattr(
        runner.u0,
        "_probe_vllm",
        lambda: {
            "container": {"id": "existing-vllm"},
            "completion_calls": 0,
            "lifecycle_mutated": False,
        },
    )

    def build_product(paths, packages, *, case_id):  # type: ignore[no-untyped-def]
        del packages
        product = paths.temporary / "product-venv"
        product.mkdir()
        manifest = {
            "schema": "milai.dg13u.u1-exact-product-manifest.v1",
            "run_id": paths.run_id,
            "case_id": case_id,
            "status": "PASS",
            "wheel_inputs": {
                "runtime": {"sha256": "b" * 64},
                "client": {"sha256": "c" * 64},
                "mcp": {"sha256": "d" * 64},
                "openworker": {"sha256": "e" * 64},
            },
            "entrypoints": {
                "milai-api": {"sha256": "f" * 64},
                "milai-worker": {"sha256": "1" * 64},
            },
        }
        runner._atomic_write(paths.durable / "exact-product-manifest.json", manifest)
        return product, manifest

    monkeypatch.setattr(runner, "_build_product_venv", build_product)

    class FakeRuntime:
        def __init__(  # type: ignore[no-untyped-def]
            self, paths, env_file, migration_head, product_venv
        ):
            del paths, env_file
            assert migration_head == "0028_dg11_window_projection"
            assert product_venv.name == "product-venv"

        def start(self, resources):  # type: ignore[no-untyped-def]
            del resources
            return runner.FreshRuntimeIdentity(
                "milai_smoke_dg13u_synthetic",
                "http://127.0.0.1:19001",
                101,
                "api-marker",
                102,
                "worker-marker",
                "0028_dg11_window_projection",
            )

        def ready(self) -> bool:
            return True

    monkeypatch.setattr(runner, "FreshRuntimeLifecycle", FakeRuntime)

    class FakeU1:
        def __init__(self, paths, case, runtime, product_venv):  # type: ignore[no-untyped-def]
            del paths, runtime
            assert case.case_id == "U1-NONE-EN"
            assert product_venv.name == "product-venv"
            self.readiness_latencies_ms = {
                "runtime": 0.0,
                "broker": 2.0,
                "host": 3.0,
                "openworker": 4.0,
                "provider": 5.0,
            }

        def start(self, resources):  # type: ignore[no-untyped-def]
            del resources
            return {"network": "run-owned", "host": "direct"}

        def readiness(self):  # type: ignore[no-untyped-def]
            return {
                "runtime": "PASS",
                "broker": "PASS",
                "host": "PASS",
                "openworker": "PASS",
                "provider": "PASS_IDENTITY_ONLY_ZERO_COMPLETIONS",
                "provider_completion_calls": 0,
                "security": {
                    "status": "PASS",
                    "network_internal": True,
                    "network_mode_sha256": "3" * 64,
                    "cap_drop_all": True,
                    "no_new_privileges": True,
                    "reader_lite_socket_read_only": True,
                    "docker_socket_mounted": False,
                    "forbidden_environment_names": [],
                },
                "latencies_ms": dict(self.readiness_latencies_ms),
                "worker_health_sha256": "4" * 64,
                "mcp_list_sha256": "5" * 64,
            }

        def smoke(self):  # type: ignore[no-untyped-def]
            return {
                "observed_provider_calls": 1,
                "observed_mcp_calls": 0,
                "native_request_id_sha256": "2" * 64,
                "provider_terminal_status": "SUCCEEDED",
                "worker_exit_code": 0,
                "worker_output_sha256": "6" * 64,
                "worker_output_bytes": 128,
                "automatic_retries": 0,
                "mcp_automatic_retries": 0,
                "unaccounted_mcp_calls": 0,
                "unaccounted_provider_calls": 0,
                "memory_route": "NONE",
                "context_tokens": 0,
                "latencies_ms": {
                    "openworker": 1.0,
                    "adapter": 2.0,
                    "mcp": 0.0,
                    "runtime": 0.0,
                    "compile": 0.0,
                    "provider": 3.0,
                },
                "model_visible_memory_tool_events": 0,
                "raw_prompt_or_answer_persisted": False,
            }

        def reconciliation(self):  # type: ignore[no-untyped-def]
            return {
                "observed_provider_calls": 1,
                "observed_mcp_calls": 0,
                "native_request_id_sha256": "2" * 64,
                "unaccounted_calls": 0,
                "provider_terminal_status": "SUCCEEDED",
                "worker_exit_code": 0,
                "worker_output_sha256": "6" * 64,
                "worker_output_bytes": 128,
                "automatic_retries": 0,
                "mcp_automatic_retries": 0,
                "unaccounted_mcp_calls": 0,
                "unaccounted_provider_calls": 0,
                "memory_route": "NONE",
                "context_tokens": 0,
                "latencies_ms": {
                    "openworker": 1.0,
                    "adapter": 2.0,
                    "mcp": 0.0,
                    "runtime": 0.0,
                    "compile": 0.0,
                    "provider": 3.0,
                },
                "model_visible_memory_tool_events": 0,
                "raw_prompt_or_answer_persisted": False,
                "broker_socket_inode_preserved": True,
                "host_process_preserved": True,
                "broker_process_preserved": True,
                "durable_credentials_found": 0,
            }

    monkeypatch.setattr(runner, "OpenWorkerU1Lifecycle", FakeU1)
    run_id = "dg13u-u1-local-preflight"
    report = runner.run_case(
        run_id,
        "U1-NONE-EN",
        composition=runner.LocalComposition(tmp_path / "runtime.env"),
    )

    assert report["status"] == "PASS"
    assert report["stages"][0]["status"] == "PASS"
    assert report["stages"][0]["reason_code"] == ("EXACT_FRESH_U1_COMPOSITION_STARTED")
    assert report["stages"][1]["status"] == "PASS"
    assert report["stages"][1]["reason_code"] == (
        "FRESH_RUNTIME_BROKER_HOST_OPENWORKER_READY"
    )
    assert report["stages"][2]["status"] == "PASS"
    assert report["stages"][3]["status"] == "PASS"
    assert report["calls"]["provider"] == {
        "expected": 1,
        "maximum_per_model_round": 1,
        "model_rounds": 1,
        "calls_per_task_operation": 1,
        "case_maximum": 1,
        "observed": 1,
        "unaccounted": 0,
        "automatic_retries": 0,
        "status": "PASS",
    }
    assert report["calls"]["mcp"]["status"] == "PASS"
    assert report["wall_latency_ms"] >= 0
    assert report["context_tokens"] == 0
    assert report["safety_counters"]["SilentMemoryNeedNone"] == {
        "failures": 0,
        "denominator": 1,
        "status": "PASS",
    }
    assert report["safety_counters"]["WrongScopeAcceptance"]["status"] == ("NOT_RUN")
    identity = json.loads((runs / run_id / "identity-preflight.json").read_text())
    assert identity["schema"] == "milai.dg13u.u1-identity-preflight.v1"
    assert identity["run_id"] == run_id
    assert identity["case_id"] == "U1-NONE-EN"
    assert identity["status"] == "PASS"
    assert identity["openworker_image"]["id"] == "sha256:u1-image"
    assert identity["vllm"]["completion_calls"] == 0
    manifest = json.loads((runs / run_id / "manifest.json").read_text())
    assert manifest["status"] == "PASS"
    cleanup = json.loads((runs / run_id / "cleanup-receipt.json").read_text())
    assert cleanup["case_id"] == "U1-NONE-EN"
    for name, schema in {
        "readiness.json": "milai.dg13u.u1-readiness.v1",
        "smoke-evidence.json": "milai.dg13u.u1-smoke-evidence.v1",
        "reconciliation.json": "milai.dg13u.u1-reconciliation.v1",
    }.items():
        artifact = json.loads((runs / run_id / name).read_text())
        assert artifact["schema"] == schema
        assert artifact["run_id"] == run_id
        assert artifact["case_id"] == "U1-NONE-EN"
        assert artifact["status"] == "PASS"
    readiness_artifact = json.loads((runs / run_id / "readiness.json").read_text())
    assert readiness_artifact["provider_completion_calls"] == 0
    assert readiness_artifact["security"]["network_internal"] is True
    assert set(readiness_artifact["latencies_ms"]) == {
        "runtime",
        "broker",
        "host",
        "openworker",
        "provider",
    }
    smoke_artifact = json.loads((runs / run_id / "smoke-evidence.json").read_text())
    assert smoke_artifact["calls"]["provider"]["observed"] == 1
    assert (
        smoke_artifact["joined_identities"]["provider_native_request_id_sha256"]
        == "2" * 64
    )
    reconciliation_artifact = json.loads(
        (runs / run_id / "reconciliation.json").read_text()
    )
    assert reconciliation_artifact["unaccounted_calls"] == 0
    assert reconciliation_artifact["existing_vllm_preserved"] is True
    assert reconciliation_artifact["latencies_ms"]["reconciliation"] >= 0
    indexed = {row["path"]: row for row in report["artifacts"]}
    for name in ("readiness.json", "smoke-evidence.json", "reconciliation.json"):
        path = runs / run_id / name
        assert indexed[name]["bytes"] == path.stat().st_size
        assert (
            indexed[name]["sha256"]
            == runner.hashlib.sha256(path.read_bytes()).hexdigest()
        )
    assert identity["fresh_runtime"]["database_lifecycle"] == "RUN_OWNED_FRESH"
    assert identity["exact_product"]["wheel_inputs"]["runtime"]["sha256"] == ("b" * 64)
    manifest = json.loads((runs / run_id / "manifest.json").read_text())
    assert manifest["resolved_composition"]["exact_product"]["entrypoints"][
        "milai-api"
    ]["sha256"] == ("f" * 64)
    assert not (temporary / run_id).exists()
    assert not (uds / runner._short_run_id(run_id)).exists()


def test_product_venv_installs_exact_wheels_with_offline_dependencies_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cra-workspace"
    monkeypatch.setattr(runner, "ROOT", root)
    durable = root / "var/dg13/runs/dg13u-u1-product"
    temporary = root / "var/dg13/tmp/dg13u-u1-product"
    uds = tmp_path / "dev-shm-milai/u1-product"
    for path in (durable, temporary, uds):
        path.mkdir(parents=True)
    (temporary / "uv-cache").mkdir()
    locked_cache = root / "locked-uv-cache"
    (locked_cache / "wheels-v5/pypi/synthetic").mkdir(parents=True)
    (locked_cache / "wheels-v5/pypi/synthetic/index.msgpack").write_text(
        "locked", encoding="utf-8"
    )
    monkeypatch.setattr(runner, "LOCKED_UV_CACHE", locked_cache)
    paths = runner.RunPaths("dg13u-u1-product", durable, temporary, uds)
    artifacts: dict[str, object] = {}
    for name in runner._PRODUCT_WHEELS:
        wheel = durable / f"packages/{name}/{name}-0.1.0.whl"
        wheel.parent.mkdir(parents=True)
        wheel.write_bytes(f"wheel:{name}".encode())
        artifacts[f"{name}_wheel"] = {
            "path": str(wheel.relative_to(durable)),
            "sha256": runner.u0._sha256_file(wheel),
        }

    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(command, **kwargs):  # type: ignore[no-untyped-def]
        environment = dict(kwargs["env"])
        calls.append((list(command), environment))
        assert Path(environment["TMPDIR"]).is_dir()
        assert Path(environment["UV_CACHE_DIR"]).is_dir()
        assert environment["UV_LINK_MODE"] == "copy"
        if command[1] == "venv":
            product_bin = temporary / "product-venv/bin"
            product_bin.mkdir(parents=True)
            (product_bin / "python").write_text("python", encoding="utf-8")
            for entrypoint in runner._PRODUCT_ENTRYPOINTS:
                executable = product_bin / entrypoint
                executable.write_text(f"entrypoint:{entrypoint}", encoding="utf-8")
                executable.chmod(0o700)
        return subprocess.CompletedProcess(command, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(
        runner.u0,
        "_installed_identity",
        lambda _venv: {
            "distributions": {
                "milai-runtime": {"version": "0.1.0"},
                "milai-client": {"version": "0.1.0"},
                "milai-mcp": {"version": "0.1.0"},
                "milai-openworker-mcp": {"version": "0.1.0"},
            },
            "entrypoints": {},
        },
    )

    product_venv, manifest = runner._build_product_venv(
        paths, {"artifacts": artifacts}, case_id="U1-NONE-EN"
    )

    assert product_venv == temporary / "product-venv"
    assert len(calls) == 2
    install = calls[1][0]
    assert install[:4] == ["uv", "pip", "install", "--offline"]
    assert "--no-deps" not in install
    assert [Path(value).name for value in install[-4:]] == [
        "client-0.1.0.whl",
        "mcp-0.1.0.whl",
        "runtime-0.1.0.whl",
        "openworker-0.1.0.whl",
    ]
    assert set(manifest["wheel_inputs"]) == set(runner._PRODUCT_WHEELS)
    assert manifest["run_id"] == paths.run_id
    assert manifest["case_id"] == "U1-NONE-EN"
    assert manifest["status"] == "PASS"
    assert set(manifest["entrypoints"]) == set(runner._PRODUCT_ENTRYPOINTS)
    assert manifest["environment"]["UV_LINK_MODE"] == "copy"
    assert manifest["environment"]["UV_DEPENDENCY_CACHE_DIR"] == str(locked_cache)
    assert manifest["environment"]["dependency_cache_access"] == (
        "PREEXISTING_LOCKED_OFFLINE_SOURCE"
    )
    assert manifest["environment"]["locked_dependency_wheels"]["sha256"]
    assert all(row["sha256"] for row in manifest["entrypoints"].values())
    persisted = json.loads(
        (durable / "exact-product-manifest.json").read_text(encoding="utf-8")
    )
    assert persisted["installation"] == ("FRESH_RUN_OWNED_OFFLINE_FULL_DEPENDENCIES")


def test_product_venv_rejects_wheel_digest_drift_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths("dg13u-u1-wheel-drift", durable, temporary, uds)
    artifacts: dict[str, object] = {}
    for name in runner._PRODUCT_WHEELS:
        wheel = durable / f"{name}.whl"
        wheel.write_bytes(name.encode())
        artifacts[f"{name}_wheel"] = {
            "path": wheel.name,
            "sha256": runner.u0._sha256_file(wheel),
        }
    artifacts["runtime_wheel"]["sha256"] = "0" * 64  # type: ignore[index]
    called = False

    def run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True

    monkeypatch.setattr(runner.subprocess, "run", run)
    with pytest.raises(runner.RunError, match="runtime wheel digest drift"):
        runner._build_product_venv(
            paths, {"artifacts": artifacts}, case_id="U1-NONE-EN"
        )
    assert called is False


def test_owned_logs_directory_reuses_private_product_install_directory(
    tmp_path: Path,
) -> None:
    durable = tmp_path / "run"
    durable.mkdir(mode=0o700)
    logs = durable / "logs"
    logs.mkdir(mode=0o700)
    install_log = logs / "product-install.log"
    install_log.write_text("exact product install receipt", encoding="utf-8")
    paths = runner.RunPaths(
        "dg13u-u1-log-reuse", durable, tmp_path / "temporary", tmp_path / "uds"
    )

    assert runner._owned_logs_directory(paths) == logs
    assert install_log.read_text(encoding="utf-8") == "exact product install receipt"
    assert logs.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("bad_kind", ["symlink", "file", "permissions"])
def test_owned_logs_directory_rejects_unsafe_existing_path(
    tmp_path: Path, bad_kind: str
) -> None:
    durable = tmp_path / "run"
    durable.mkdir(mode=0o700)
    logs = durable / "logs"
    if bad_kind == "symlink":
        target = tmp_path / "outside"
        target.mkdir(mode=0o700)
        logs.symlink_to(target, target_is_directory=True)
    elif bad_kind == "file":
        logs.write_text("not a directory", encoding="utf-8")
    else:
        logs.mkdir(mode=0o755)
    paths = runner.RunPaths(
        "dg13u-u1-log-negative",
        durable,
        tmp_path / "temporary",
        tmp_path / "uds",
    )

    with pytest.raises(runner.RunError, match="run-owned log"):
        runner._owned_logs_directory(paths)


def test_provider_capability_budgets_each_task_turn_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runner._PROVIDER_PROMPT_TOKENS_PER_TURN == 16_384
    _configure_roots(tmp_path, monkeypatch)
    paths = runner.RunPaths(
        "dg13u-u1-task-return",
        tmp_path / "durable",
        tmp_path / "temporary",
        tmp_path / "uds",
    )
    capability = runner._provider_capability(
        paths,
        runner.CASES["U1-TASK-RETURN"],
        "synthetic task return",
        now=runner.datetime(2026, 8, 25, tzinfo=runner.UTC),
    )
    assert capability["max_native_requests"] == 3
    assert capability["max_prompt_tokens"] == (
        runner._PROVIDER_PROMPT_TOKENS_PER_TURN * 3
    )
    assert capability["max_completion_tokens"] == (
        runner._PROVIDER_COMPLETION_TOKENS_PER_TURN * 3
    )


def test_all_frozen_task_scenarios_are_real_and_seeded_positive_cases() -> None:
    task_cases = set(task_scenarios.TASK_SCENARIOS)

    assert task_cases <= runner._IMPLEMENTED_REAL_CASES
    assert task_cases <= runner._CANONICAL_POSITIVE_CASES
    assert {
        case_id: (
            runner.CASES[case_id].expected_mcp_calls,
            runner.CASES[case_id].expected_provider_calls,
        )
        for case_id in task_cases
    } == {
        case_id: (
            scenario.expected_mcp_calls,
            scenario.expected_provider_calls,
        )
        for case_id, scenario in task_scenarios.TASK_SCENARIOS.items()
    }


def test_all_frozen_fault_scenarios_are_real_with_exact_case_totals() -> None:
    fault_cases = set(runner.fault_scenarios.FAULT_SCENARIOS)

    assert len(fault_cases) == 13
    assert fault_cases <= runner._IMPLEMENTED_REAL_CASES
    assert {
        case_id: (
            runner.CASES[case_id].expected_mcp_calls,
            runner.CASES[case_id].expected_provider_calls,
        )
        for case_id in fault_cases
    } == {
        case_id: (
            scenario.expected_mcp_calls,
            scenario.expected_provider_calls,
        )
        for case_id, scenario in runner.fault_scenarios.FAULT_SCENARIOS.items()
    }


def _fault_plan(tmp_path: Path, case_id: str):  # type: ignore[no-untyped-def]
    root = tmp_path / case_id.casefold()
    root.mkdir(mode=0o700)
    return runner.fault_execution.build_fault_execution_plan(
        case_id,
        run_owned_root=root,
        python_executable=Path(sys.executable),
    )


def _fault_observations(plan):  # type: ignore[no-untyped-def]
    expected = plan.expected_terminal
    if plan.case_id.startswith("U1-PROVIDER-"):
        return (
            [
                {
                    "event": "HOST_INGRESS_TERMINAL",
                    "reason_code": expected.reason_code,
                    "http_status": expected.http_status,
                }
            ],
            [
                {"event": "RESERVED", "logical_request_id": "logical-1"},
                {
                    "event": "PROVIDER_TERMINAL",
                    "logical_request_id": "logical-1",
                    "status": "FAILED",
                    "reason_code": expected.reason_code,
                    "request_started": plan.fixture.mode == "MALFORMED",
                    "native_request_observed": False,
                    "native_request_id": None,
                },
            ],
        )
    attempt_trace_id = "host-mcp-attempt:" + "a" * 64
    return (
        [
            {
                "event": "HOST_MCP_PREPARE_ATTEMPT",
                "logical_mcp_calls": 1,
                "attempt_trace_id": attempt_trace_id,
            },
            {
                "event": "HOST_MCP_PREPARE_CONTEXT",
                "attempt_trace_id": attempt_trace_id,
                "access_outcome": {
                    "status": expected.access_status,
                    "execution_action": expected.execution_action,
                    "provider_execution": expected.provider_execution,
                    "terminal_stage": expected.terminal_stage,
                    "context_digest": None,
                    "canonical_position": None,
                    "reason_code": expected.reason_code,
                    "trace_id": "content-free-trace",
                },
            },
        ],
        [],
    )


def _memory_fault_stdout(expected) -> bytes:  # type: ignore[no-untyped-def]
    content = json.dumps(
        {
            "answer": "UNKNOWN",
            "status": expected.access_status,
            "memory_used": False,
            "memory_outcome": expected.access_status,
            "execution_action": expected.execution_action,
            "provider_execution": expected.provider_execution,
            "terminal_stage": expected.terminal_stage,
            "reason_code": expected.reason_code,
            "trace_id": "content-free-trace",
        },
        sort_keys=True,
    )
    return (
        json.dumps(
            {
                "type": "text",
                "sessionID": "session-only-in-memory",
                "part": {"type": "text", "text": content},
            }
        ).encode()
        + b"\n"
    )


def test_fault_opencode_terminals_are_bound_to_provider_error_or_memory_outcome(
    tmp_path: Path,
) -> None:
    provider = _fault_plan(tmp_path, "U1-PROVIDER-MALFORMED")
    provider_output = subprocess.CompletedProcess(
        [],
        0,
        stdout=b'{"type":"error","error":{"name":"ProviderCallError"}}\n',
        stderr=b"",
    )
    provider_truth = runner.SmokeCommandTruth(
        runner.TerminalStatus.FAIL,
        "OPENCODE_TYPED_ERROR",
        0,
        1,
    )
    assert runner._opencode_fault_command_accounting(
        provider,
        completed=provider_output,
        command_truth=provider_truth,
    ) == {
        "opencode_typed_error_count": 1,
        "opencode_success_text_count": 0,
        "opencode_memory_terminal_sha256": None,
    }

    memory = _fault_plan(tmp_path, "U1-BROKER-DOWN")
    memory_output = subprocess.CompletedProcess(
        [],
        0,
        stdout=_memory_fault_stdout(memory.expected_terminal),
        stderr=b"",
    )
    memory_truth = runner.SmokeCommandTruth(
        runner.TerminalStatus.PASS,
        "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR",
        0,
        0,
    )
    observed = runner._opencode_fault_command_accounting(
        memory,
        completed=memory_output,
        command_truth=memory_truth,
    )
    assert observed["opencode_typed_error_count"] == 0
    assert observed["opencode_memory_terminal_sha256"] is not None


@pytest.mark.parametrize(
    ("case_id", "stdout", "status", "typed_errors", "message"),
    [
        (
            "U1-PROVIDER-DOWN",
            (
                b'{"type":"error"}\n'
                b'{"type":"text","part":{"text":"unexpected success"}}\n'
            ),
            runner.TerminalStatus.FAIL,
            1,
            "provider fault OpenCode typed terminal",
        ),
        (
            "U1-PROVIDER-DOWN",
            b'{"type":"step_finish"}\n',
            runner.TerminalStatus.PASS,
            0,
            "provider fault OpenCode typed terminal",
        ),
        (
            "U1-BROKER-DOWN",
            b'{"type":"error"}\n',
            runner.TerminalStatus.FAIL,
            1,
            "memory fault OpenCode terminal",
        ),
        (
            "U1-BROKER-DOWN",
            b'{"type":"text","part":{"text":"UNKNOWN"}}\n',
            runner.TerminalStatus.PASS,
            0,
            "memory fault OpenCode typed completion",
        ),
        (
            "U1-BROKER-DOWN",
            _memory_fault_stdout(
                runner.fault_scenarios.FAULT_SCENARIOS[
                    "U1-BROKER-DOWN"
                ].expected_terminal
            )
            + b'{"type":"text","part":{"text":"unexpected extra text"}}\n',
            runner.TerminalStatus.PASS,
            0,
            "memory fault OpenCode typed completion",
        ),
    ],
)
def test_fault_opencode_terminal_negative_twins_fail_closed(
    tmp_path: Path,
    case_id: str,
    stdout: bytes,
    status: runner.TerminalStatus,
    typed_errors: int,
    message: str,
) -> None:
    plan = _fault_plan(tmp_path, case_id)
    completed = subprocess.CompletedProcess([], 0, stdout=stdout, stderr=b"")
    truth = runner.SmokeCommandTruth(status, "SYNTHETIC", 0, typed_errors)

    with pytest.raises(runner.RunError, match=message):
        runner._opencode_fault_command_accounting(
            plan,
            completed=completed,
            command_truth=truth,
        )


@pytest.mark.parametrize("mutation", ("extra_field", "empty_trace", "outcome_mismatch"))
def test_memory_fault_opencode_completion_shape_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    plan = _fault_plan(tmp_path, "U1-BROKER-DOWN")
    event = json.loads(_memory_fault_stdout(plan.expected_terminal))
    content = json.loads(event["part"]["text"])
    if mutation == "extra_field":
        content["unexpected"] = None
    elif mutation == "empty_trace":
        content["trace_id"] = ""
    else:
        content["memory_outcome"] = "NO_MEMORY_NEEDED"
    event["part"]["text"] = json.dumps(content, sort_keys=True)
    completed = subprocess.CompletedProcess(
        [], 0, stdout=json.dumps(event).encode() + b"\n", stderr=b""
    )
    truth = runner.SmokeCommandTruth(
        runner.TerminalStatus.PASS,
        "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR",
        0,
        0,
    )

    with pytest.raises(runner.RunError, match="typed completion drifted"):
        runner._opencode_fault_command_accounting(
            plan,
            completed=completed,
            command_truth=truth,
        )


@pytest.mark.parametrize("case_id", sorted(runner.fault_scenarios.FAULT_SCENARIOS))
def test_fault_trace_accounting_is_exact_and_attempt_events_are_not_double_counted(
    tmp_path: Path,
    case_id: str,
) -> None:
    plan = _fault_plan(tmp_path, case_id)
    trace, ledger = _fault_observations(plan)

    measured = runner._fault_trace_accounting(plan, trace=trace, ledger=ledger)

    assert measured["host_terminal"] == runner.asdict(plan.expected_terminal)
    assert measured["ledger_calls"] == {
        "mcp": plan.expected_mcp_calls,
        "provider": plan.expected_provider_calls,
    }
    assert measured["provider_barrier"] == plan.provider_barrier
    assert measured["mcp_attempt_count"] == plan.expected_mcp_calls
    if plan.expected_mcp_calls:
        assert measured["mcp_terminal_event"] == "HOST_MCP_PREPARE_CONTEXT"
    else:
        assert measured["provider_terminal_status"] == "FAILED"
        assert measured["provider_terminal_reason_code"] == (
            plan.expected_terminal.reason_code
        )
        assert measured["provider_terminal_observation"] == {
            "event_sequence": ["RESERVED", "PROVIDER_TERMINAL"],
            "logical_reservations": 1,
            "logical_request_id_sha256": runner.hashlib.sha256(
                b"logical-1"
            ).hexdigest(),
            "terminal_status": "FAILED",
            "reason_code": plan.expected_terminal.reason_code,
            "request_started": plan.fixture.mode == "MALFORMED",
            "native_request_observed": False,
            "native_request_id_sha256": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "post_terminal_count": 0,
            "automatic_retries": 0,
        }


def test_broker_fault_accepts_exact_typed_prepare_context_terminal(
    tmp_path: Path,
) -> None:
    plan = _fault_plan(tmp_path, "U1-BROKER-DOWN")
    trace, ledger = _fault_observations(plan)
    trace[1]["event"] = "HOST_MCP_PREPARE_CONTEXT"

    measured = runner._fault_trace_accounting(plan, trace=trace, ledger=ledger)

    assert measured["mcp_terminal_event"] == "HOST_MCP_PREPARE_CONTEXT"
    assert measured["ledger_calls"] == {"mcp": 1, "provider": 0}
    assert measured["provider_barrier"] == "BLOCKED"


@pytest.mark.parametrize("mutation", ("missing", "legacy_branch", "mixed", "duplicate"))
def test_memory_fault_requires_exactly_one_prepare_context_terminal(
    tmp_path: Path,
    mutation: str,
) -> None:
    plan = _fault_plan(tmp_path, "U1-BROKER-DOWN")
    trace, ledger = _fault_observations(plan)
    terminal = trace[1]
    if mutation == "missing":
        trace.pop()
    elif mutation == "legacy_branch":
        terminal["event"] = "HOST_MCP_PREFETCH_FAILED"
    elif mutation == "mixed":
        trace.append({**terminal, "event": "HOST_MCP_PREFETCH_FAILED"})
    else:
        trace.append(dict(terminal))

    with pytest.raises(runner.RunError, match="terminal trace is absent or ambiguous"):
        runner._fault_trace_accounting(plan, trace=trace, ledger=ledger)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_outcome", "outcome is absent"),
        ("non_object_outcome", "outcome is absent"),
        ("extra_field", "outcome shape drifted"),
        ("context_digest", "outcome shape drifted"),
        ("canonical_position", "outcome shape drifted"),
        ("empty_trace", "outcome shape drifted"),
        ("wrong_status", "typed access outcome drifted"),
        ("wrong_action", "typed access outcome drifted"),
        ("wrong_provider", "typed access outcome drifted"),
        ("wrong_stage", "typed access outcome drifted"),
        ("wrong_reason", "typed access outcome drifted"),
        ("attempt_identity", "attempt identity drifted"),
    ],
)
def test_memory_fault_access_outcome_and_attempt_join_fail_closed(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    plan = _fault_plan(tmp_path, "U1-BROKER-DOWN")
    trace, ledger = _fault_observations(plan)
    outcome = trace[1]["access_outcome"]
    if mutation == "missing_outcome":
        trace[1].pop("access_outcome")
    elif mutation == "non_object_outcome":
        trace[1]["access_outcome"] = "typed-looking-text"
    elif mutation == "extra_field":
        outcome["unexpected"] = None
    elif mutation == "context_digest":
        outcome["context_digest"] = "a" * 64
    elif mutation == "canonical_position":
        outcome["canonical_position"] = False
    elif mutation == "empty_trace":
        outcome["trace_id"] = ""
    elif mutation == "wrong_status":
        outcome["status"] = "NO_MEMORY_NEEDED"
    elif mutation == "wrong_action":
        outcome["execution_action"] = "CONTINUE"
    elif mutation == "wrong_provider":
        outcome["provider_execution"] = "ALLOWED"
    elif mutation == "wrong_stage":
        outcome["terminal_stage"] = "NONE"
    elif mutation == "wrong_reason":
        outcome["reason_code"] = "WRONG_REASON"
    else:
        trace[1]["attempt_trace_id"] = "host-mcp-attempt:" + "b" * 64

    with pytest.raises(runner.RunError, match=message):
        runner._fault_trace_accounting(plan, trace=trace, ledger=ledger)


@pytest.mark.parametrize("case_id", ["U1-RUNTIME-DOWN", "U1-PROVIDER-DOWN"])
def test_fault_trace_accounting_excludes_only_exact_bootstrap_terminal(
    tmp_path: Path,
    case_id: str,
) -> None:
    plan = _fault_plan(tmp_path, case_id)
    trace, ledger = _fault_observations(plan)
    trace.insert(
        0,
        {
            "event": "HOST_INGRESS_TERMINAL",
            "exception_type": "OpenWorkerAdapterError",
            "http_status": 400,
            "reason_code": "PROVIDER_REQUEST_UNSUPPORTED",
        },
    )

    measured = runner._fault_trace_accounting(plan, trace=trace, ledger=ledger)

    assert measured["host_terminal"] == runner.asdict(plan.expected_terminal)


def test_fault_trace_accounting_rejects_bootstrap_terminal_shape_drift(
    tmp_path: Path,
) -> None:
    plan = _fault_plan(tmp_path, "U1-RUNTIME-DOWN")
    trace, ledger = _fault_observations(plan)
    trace.insert(
        0,
        {
            "event": "HOST_INGRESS_TERMINAL",
            "exception_type": "OpenWorkerAdapterError",
            "http_status": 409,
            "reason_code": "PROVIDER_REQUEST_UNSUPPORTED",
        },
    )

    with pytest.raises(runner.RunError, match="unexpected ingress terminal"):
        runner._fault_trace_accounting(plan, trace=trace, ledger=ledger)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate_mcp", "MCP attempt"),
        ("provider_crossed", "provider barrier"),
        ("post_provider_crossed", "provider barrier"),
        ("provider_answer_crossed", "provider barrier"),
        ("terminal_reason", "typed access outcome"),
    ],
)
def test_memory_fault_accounting_fails_closed_on_retry_barrier_or_terminal_drift(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    plan = _fault_plan(tmp_path, "U1-BROKER-TIMEOUT")
    trace, ledger = _fault_observations(plan)
    if mutation == "duplicate_mcp":
        trace.insert(1, dict(trace[0]))
    elif mutation == "provider_crossed":
        ledger.append({"event": "RESERVED"})
    elif mutation == "post_provider_crossed":
        ledger.append({"event": "POST_PROVIDER_TERMINAL"})
    elif mutation == "provider_answer_crossed":
        trace.append({"event": "PROVIDER_ANSWER"})
    else:
        trace[1]["access_outcome"]["reason_code"] = "WRONG_REASON"

    with pytest.raises(runner.RunError, match=message):
        runner._fault_trace_accounting(plan, trace=trace, ledger=ledger)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_ingress", "Host terminal"),
        ("duplicate_reservation", "reservation count"),
        ("missing_terminal", "reservation count"),
        ("reverse_order", "reservation count"),
        ("unknown_ledger", "reservation count"),
        ("logical_id_mismatch", "terminal ledger drifted"),
        ("provider_answer", "unexpected success trace"),
        ("wrong_http", "Host terminal drifted"),
        ("wrong_reason", "Host terminal drifted"),
    ],
)
def test_provider_fault_accounting_requires_one_failed_terminal_and_no_retry(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    plan = _fault_plan(tmp_path, "U1-PROVIDER-MALFORMED")
    trace, ledger = _fault_observations(plan)
    if mutation == "missing_ingress":
        trace.clear()
    elif mutation == "duplicate_reservation":
        ledger.insert(1, {"event": "RESERVED", "logical_request_id": "logical-2"})
    elif mutation == "missing_terminal":
        ledger.pop()
    elif mutation == "reverse_order":
        ledger.reverse()
    elif mutation == "unknown_ledger":
        ledger.append({"event": "UNKNOWN_PROVIDER_EVENT"})
    elif mutation == "logical_id_mismatch":
        ledger[1]["logical_request_id"] = "logical-2"
    elif mutation == "provider_answer":
        trace.append({"event": "PROVIDER_ANSWER"})
    elif mutation == "wrong_http":
        trace[0]["http_status"] = 503
    else:
        trace[0]["reason_code"] = "JSON_TRANSPORT_ONLY_REASON"

    with pytest.raises(runner.RunError, match=message):
        runner._fault_trace_accounting(plan, trace=trace, ledger=ledger)


def test_provider_fault_capability_uses_run_owned_endpoint_and_short_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    fixture = tmp_path / "fixture.json"
    fixture.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(runner, "CANDIDATE_FIXTURE", fixture)
    monkeypatch.setattr(
        runner,
        "_bound_identity",
        lambda _path: {"sha256": runner.hashlib.sha256(b"fixture").hexdigest()},
    )
    paths = runner.RunPaths("dg13u-u1-provider-fault", durable, temporary, uds)
    capability = runner._provider_capability(
        paths,
        runner.CASES["U1-PROVIDER-DOWN"],
        "synthetic no-memory turn",
        endpoint_identity="http://127.0.0.1:45678",
    )

    assert capability["endpoint_identity"] == "http://127.0.0.1:45678"
    assert capability["max_native_requests"] == 1
    assert capability["max_prompt_tokens"] == 16_384


def test_runtime_fault_uses_dual_socket_and_fault_runtime_from_host_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    product = temporary / "product"
    (product / "bin").mkdir(parents=True)
    mcp = product / "bin/milai-mcp"
    mcp.write_text("#!/bin/sh\n", encoding="utf-8")
    mcp.chmod(0o700)

    class Identity:
        base_url = "http://127.0.0.1:44001"

    class Runtime:
        identity = Identity()
        reader_token = "reader-token"

    class Injector:
        def __init__(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            self.base_url = "http://127.0.0.1:44002"
            self._active = False

        def start(self):  # type: ignore[no-untyped-def]
            self._active = True

        def stop(self):  # type: ignore[no-untyped-def]
            self._active = False

    paths = runner.RunPaths("dg13u-u1-runtime-fault", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths,
        runner.CASES["U1-RUNTIME-MALFORMED"],
        Runtime(),
        product,
    )
    registry = runner.ResourceRegistry(paths.run_id)
    started_policies: list[Path] = []
    monkeypatch.setattr(runner.runtime_fault, "RuntimeFaultInjector", Injector)
    monkeypatch.setattr(
        lifecycle,
        "_start_fault_broker",
        lambda _resources, policy: started_policies.append(policy),
    )

    lifecycle._prepare_fault_before_host(registry)

    assert lifecycle.host_prefetch_socket != lifecycle.socket_path
    policy = json.loads(lifecycle.host_policy_path.read_text(encoding="utf-8"))
    assert policy["base_url"] == "http://127.0.0.1:44002"
    assert policy["socket_path"] == str(lifecycle.host_prefetch_socket)
    assert started_policies == [lifecycle.host_policy_path]
    receipt = registry.cleanup_all()
    assert receipt["status"] == runner.TerminalStatus.PASS


@pytest.mark.parametrize(
    ("case_id", "expected_endpoint", "expected_timeout"),
    [
        ("U1-PROVIDER-DOWN", None, 1.0),
        ("U1-PROVIDER-MALFORMED", "http://127.0.0.1:45002", 1.0),
        ("U1-PROVIDER-TIMEOUT", "http://127.0.0.1:45002", 1.0),
    ],
)
def test_provider_fault_endpoint_is_bound_before_host_and_never_used_for_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    expected_endpoint: str | None,
    expected_timeout: float,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)

    class Identity:
        base_url = "http://127.0.0.1:44001"

    class Runtime:
        identity = Identity()
        reader_token = "reader-token"

    class Injector:
        native_attempts = 0

        def __init__(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            self.base_url = "http://127.0.0.1:45002"
            self._active = False

        def start(self):  # type: ignore[no-untyped-def]
            self._active = True

        def stop(self):  # type: ignore[no-untyped-def]
            self._active = False

    class Closed:
        base_url = "http://127.0.0.1:45003"

    paths = runner.RunPaths("dg13u-u1-provider-start", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES[case_id], Runtime(), temporary / "product"
    )
    registry = runner.ResourceRegistry(paths.run_id)
    monkeypatch.setattr(runner.provider_fault, "ProviderFaultInjector", Injector)
    monkeypatch.setattr(
        runner.runtime_fault,
        "closed_loopback_endpoint_identity",
        lambda: Closed(),
    )

    lifecycle._prepare_fault_before_host(registry)

    assert lifecycle.provider_timeout_seconds == expected_timeout
    assert lifecycle.provider_endpoint_identity == (
        expected_endpoint or "http://127.0.0.1:45003"
    )
    if lifecycle.fault_provider is not None:
        assert lifecycle.fault_provider.native_attempts == 0
    assert registry.cleanup_all()["status"] == runner.TerminalStatus.PASS


def test_host_fault_launch_uses_fault_paths_endpoint_and_explicit_short_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds, durable / "logs"):
        path.mkdir(mode=0o700, exist_ok=True)
    product = temporary / "product"
    (product / "bin").mkdir(parents=True)
    host = product / "bin/milai-openworker-adapter"
    host.write_text("#!/bin/sh\n", encoding="utf-8")
    host.chmod(0o700)

    class Runtime:
        reader_token = "reader-token"

    class Process:
        pid = 43210

        @staticmethod
        def poll():  # type: ignore[no-untyped-def]
            return None

    paths = runner.RunPaths("dg13u-u1-host-fault", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-PROVIDER-MALFORMED"], Runtime(), product
    )
    lifecycle.gateway = "127.0.0.1"
    lifecycle.host_prefetch_socket = uds / "fault.sock"
    lifecycle.host_policy_path = uds / "fault-policy.json"
    lifecycle.provider_endpoint_identity = "http://127.0.0.1:45002"
    lifecycle.provider_timeout_seconds = 1.0
    launched: list[list[str]] = []

    def popen(command, **_kwargs):  # type: ignore[no-untyped-def]
        launched.append(list(command))
        return Process()

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner, "_stable_process_marker", lambda _pid: "1")
    monkeypatch.setattr(runner, "_free_bind_port", lambda _host: 45100)
    monkeypatch.setattr(
        runner,
        "_wait_http_json",
        lambda *_args, **_kwargs: {"data": [{"id": runner.MODEL_ID}]},
    )
    monkeypatch.setattr(runner, "_terminate_owned_process", lambda *_args: None)
    monkeypatch.setattr(runner, "_process_alive", lambda *_args: False)
    registry = runner.ResourceRegistry(paths.run_id)

    lifecycle._start_host(registry)

    command = launched[0]
    assert command[command.index("--prefetch-socket") + 1] == str(
        lifecycle.host_prefetch_socket
    )
    assert command[command.index("--broker-policy") + 1] == str(
        lifecycle.host_policy_path
    )
    assert command[command.index("--provider-timeout-seconds") + 1] == "1.0"
    manifest = json.loads(lifecycle.provider_manifest.read_text(encoding="utf-8"))
    assert manifest["endpoint_identity"] == "http://127.0.0.1:45002"
    assert registry.cleanup_all()["status"] == runner.TerminalStatus.PASS


@pytest.mark.parametrize(
    "case_id", ["U1-BROKER-DOWN", "U1-BROKER-MALFORMED", "U1-BROKER-TIMEOUT"]
)
def test_broker_fault_uses_separate_host_socket_after_normal_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    product = temporary / "product"
    (product / "bin").mkdir(parents=True)
    mcp = product / "bin/milai-mcp"
    mcp.write_text("#!/bin/sh\n", encoding="utf-8")
    mcp.chmod(0o700)

    class Identity:
        base_url = "http://127.0.0.1:44001"

    class Runtime:
        identity = Identity()
        reader_token = "reader-token"

    class Endpoint:
        def __init__(self, _mode, *, socket_path, **_kwargs):  # type: ignore[no-untyped-def]
            self.socket_path = Path(socket_path)
            self._active = False

        def start(self):  # type: ignore[no-untyped-def]
            self.socket_path.write_text("fault endpoint", encoding="utf-8")
            self._active = True

        def stop(self):  # type: ignore[no-untyped-def]
            self._active = False
            self.socket_path.unlink(missing_ok=True)

    paths = runner.RunPaths("dg13u-u1-broker-fault", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES[case_id], Runtime(), product
    )
    registry = runner.ResourceRegistry(paths.run_id)
    monkeypatch.setattr(runner.mcp_fault, "McpFaultEndpoint", Endpoint)

    lifecycle._prepare_fault_before_host(registry)
    assert lifecycle.host_prefetch_socket != lifecycle.socket_path
    assert not lifecycle.host_prefetch_socket.exists()
    policy = json.loads(lifecycle.host_policy_path.read_text(encoding="utf-8"))
    assert Path(policy["socket_path"]).name == "reader-lite.sock"
    assert Path(policy["socket_path"]) != lifecycle.host_prefetch_socket

    lifecycle._activate_post_readiness_fault(registry)
    if case_id == "U1-BROKER-DOWN":
        assert lifecycle.fault_mcp is None
        assert not lifecycle.host_prefetch_socket.exists()
    else:
        assert lifecycle.fault_mcp is not None
        assert lifecycle.host_prefetch_socket.exists()
    assert registry.cleanup_all()["status"] == runner.TerminalStatus.PASS


@pytest.mark.parametrize(
    "case_id",
    [
        "U1-MCP-CHILD-DOWN",
        "U1-MCP-CHILD-MALFORMED",
        "U1-MCP-CHILD-TIMEOUT",
    ],
)
def test_mcp_child_fault_broker_is_deferred_until_after_normal_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    product = temporary / "product"
    (product / "bin").mkdir(parents=True)
    mcp = product / "bin/milai-mcp"
    mcp.write_text("#!/bin/sh\n", encoding="utf-8")
    mcp.chmod(0o700)

    class Identity:
        base_url = "http://127.0.0.1:44001"

    class Runtime:
        identity = Identity()
        reader_token = "reader-token"

    def build_child(_mode, **kwargs):  # type: ignore[no-untyped-def]
        executable = Path(kwargs["executable_path"])
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o700)
        Path(kwargs["manifest_path"]).write_text("{}", encoding="utf-8")
        return {"mcp_executable": str(executable)}

    paths = runner.RunPaths("dg13u-u1-child-fault", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES[case_id], Runtime(), product
    )
    registry = runner.ResourceRegistry(paths.run_id)
    launches: list[Path] = []
    monkeypatch.setattr(runner.mcp_child_fault, "build_child_fixture", build_child)
    monkeypatch.setattr(
        lifecycle,
        "_start_fault_broker",
        lambda _resources, policy: launches.append(policy),
    )

    lifecycle._prepare_fault_before_host(registry)
    assert launches == []
    assert lifecycle.host_prefetch_socket != lifecycle.socket_path
    lifecycle._activate_post_readiness_fault(registry)
    assert launches == [lifecycle.host_policy_path]
    assert registry.cleanup_all()["status"] == runner.TerminalStatus.PASS


@pytest.mark.parametrize("case_id", ["U1-RUNTIME-DOWN", "U1-PROVIDER-DOWN"])
def test_fault_smoke_calls_frozen_reducer_and_persists_only_bounded_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)

    class Runtime:
        reader_token = "private-reader-token-value"

    paths = runner.RunPaths("dg13u-u1-fault-smoke", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES[case_id], Runtime(), temporary / "product"
    )
    lifecycle._resources = runner.ResourceRegistry(paths.run_id)
    lifecycle.fault_plan = runner.fault_execution.build_fault_execution_plan(
        case_id,
        run_owned_root=uds,
        python_executable=Path(sys.executable),
    )
    lifecycle.fault_fixture_observation = {
        "state": "HELD_CLOSED",
        "attempts": 0,
        "cleanup_complete": True,
    }
    expected = lifecycle.fault_plan.expected_terminal
    prewarm = {
        "event": "HOST_INGRESS_TERMINAL",
        "reason_code": "PROVIDER_REQUEST_UNSUPPORTED",
        "http_status": 400,
    }
    lifecycle.host_trace.write_text(json.dumps(prewarm) + "\n", encoding="utf-8")

    def command(_argv, **_kwargs):  # type: ignore[no-untyped-def]
        if case_id.startswith("U1-PROVIDER-"):
            lifecycle.host_trace.write_text(
                lifecycle.host_trace.read_text(encoding="utf-8")
                + json.dumps(
                    {
                        "event": "HOST_INGRESS_TERMINAL",
                        "reason_code": expected.reason_code,
                        "http_status": expected.http_status,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            lifecycle.provider_ledger.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {"event": "RESERVED", "logical_request_id": "logical-1"},
                        {
                            "event": "PROVIDER_TERMINAL",
                            "logical_request_id": "logical-1",
                            "status": "FAILED",
                            "reason_code": expected.reason_code,
                            "request_started": False,
                            "native_request_observed": False,
                            "native_request_id": None,
                            "prompt_tokens": None,
                            "completion_tokens": None,
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            stdout = b'{"type":"error","error":{"name":"ProviderCallError"}}\n'
        else:
            attempt_trace_id = "host-mcp-attempt:" + "a" * 64
            lifecycle.host_trace.write_text(
                lifecycle.host_trace.read_text(encoding="utf-8")
                + "\n".join(
                    json.dumps(row)
                    for row in (
                        {
                            "event": "HOST_MCP_PREPARE_ATTEMPT",
                            "logical_mcp_calls": 1,
                            "attempt_trace_id": attempt_trace_id,
                        },
                        {
                            "event": "HOST_MCP_PREPARE_CONTEXT",
                            "attempt_trace_id": attempt_trace_id,
                            "access_outcome": {
                                "status": expected.access_status,
                                "execution_action": expected.execution_action,
                                "provider_execution": expected.provider_execution,
                                "terminal_stage": expected.terminal_stage,
                                "context_digest": None,
                                "canonical_position": None,
                                "reason_code": expected.reason_code,
                                "trace_id": "content-free-trace",
                            },
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            stdout = _memory_fault_stdout(expected)
        return subprocess.CompletedProcess(_argv, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(lifecycle, "_activate_post_readiness_fault", lambda _r: None)
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_fault_fixture", lambda: None)

    measured = lifecycle._smoke_fault_scenario()

    fault_artifact = json.loads(
        (durable / "fault-execution.json").read_text(encoding="utf-8")
    )
    assert fault_artifact["schema"] == "milai.dg13u.u1-fault-execution.v1"
    assert fault_artifact["status"] == "PASS"
    assert fault_artifact["exact_calls"] == {
        "mcp": lifecycle.fault_plan.expected_mcp_calls,
        "provider": lifecycle.fault_plan.expected_provider_calls,
    }
    assert fault_artifact["external_attempts"] == 0
    assert fault_artifact["external_lifecycle_mutations"] == 0
    assert measured["fault_execution_sha256"] == runner.u0._sha256_file(
        durable / "fault-execution.json"
    )
    persisted = (durable / "fault-execution.json").read_text(encoding="utf-8")
    assert "private-reader-token-value" not in persisted
    assert runner._case_prompt(runner.CASES[case_id]) not in persisted


def test_fault_smoke_failure_preserves_measured_calls_without_claiming_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    durable = tmp_path / "dg13u-u1-fault-failure"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)

    class Runtime:
        reader_token = "private-reader-token-value"

    paths = runner.RunPaths("dg13u-u1-fault-failure", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-BROKER-DOWN"], Runtime(), temporary / "product"
    )
    lifecycle._resources = runner.ResourceRegistry(paths.run_id)
    lifecycle.fault_plan = runner.fault_execution.build_fault_execution_plan(
        "U1-BROKER-DOWN",
        run_owned_root=uds,
        python_executable=Path(sys.executable),
    )
    lifecycle.fault_fixture_observation = {
        "state": "HELD_CLOSED",
        "attempts": 0,
        "cleanup_complete": True,
    }
    expected = lifecycle.fault_plan.expected_terminal

    def command(_argv, **_kwargs):  # type: ignore[no-untyped-def]
        attempt_trace_id = "host-mcp-attempt:" + "a" * 64
        attempt = {
            "event": "HOST_MCP_PREPARE_ATTEMPT",
            "logical_mcp_calls": 1,
            "attempt_trace_id": attempt_trace_id,
        }
        terminal = {
            "event": "HOST_MCP_PREPARE_CONTEXT",
            "attempt_trace_id": attempt_trace_id,
            "access_outcome": {
                "status": expected.access_status,
                "execution_action": expected.execution_action,
                "provider_execution": expected.provider_execution,
                "terminal_stage": expected.terminal_stage,
                "context_digest": None,
                "canonical_position": None,
                "reason_code": expected.reason_code,
                "trace_id": "content-free-trace",
            },
        }
        lifecycle.host_trace.write_text(
            "\n".join(json.dumps(row) for row in (attempt, attempt, terminal)) + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            _argv, 0, stdout=_memory_fault_stdout(expected), stderr=b""
        )

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(lifecycle, "_activate_post_readiness_fault", lambda _r: None)
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_fault_fixture", lambda: None)

    with pytest.raises(runner.RunError, match="MCP attempt count"):
        lifecycle._smoke_fault_scenario()

    observation = json.loads(
        (durable / "fault-execution-observation.json").read_text(encoding="utf-8")
    )
    assert observation["status"] == "FAIL"
    assert observation["mcp_attempts"] == 2
    assert observation["provider_reservations"] == 0
    assert lifecycle.smoke_evidence["observed_mcp_calls"] == 2
    assert set(lifecycle.smoke_evidence["latencies_ms"]) == {
        "openworker",
        "adapter",
        "mcp",
        "runtime",
        "compile",
        "provider",
    }
    smoke_receipt = runner.evidence_artifacts.write_smoke_evidence_artifact(
        durable,
        runner._smoke_artifact_measurement(
            paths,
            lifecycle.case,
            runner.TerminalStatus.FAIL,
            lifecycle.smoke_evidence,
        ),
    )
    assert smoke_receipt["path"] == "smoke-evidence.json"
    assert (
        json.loads((durable / smoke_receipt["path"]).read_text(encoding="utf-8"))[
            "status"
        ]
        == "FAIL"
    )
    assert not (durable / "fault-execution.json").exists()


def test_fault_smoke_binds_private_fixture_receipt_schema_path_and_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)

    class Runtime:
        reader_token = "private-reader-token-value"

    paths = runner.RunPaths("dg13u-u1-fault-receipt", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths,
        runner.CASES["U1-RUNTIME-MALFORMED"],
        Runtime(),
        temporary / "product",
    )
    lifecycle._resources = runner.ResourceRegistry(paths.run_id)
    lifecycle.fault_plan = runner.fault_execution.build_fault_execution_plan(
        "U1-RUNTIME-MALFORMED",
        run_owned_root=uds,
        python_executable=Path(sys.executable),
    )
    expected = lifecycle.fault_plan.expected_terminal

    def command(_argv, **_kwargs):  # type: ignore[no-untyped-def]
        attempt_trace_id = "host-mcp-attempt:" + "a" * 64
        lifecycle.host_trace.write_text(
            "\n".join(
                json.dumps(row)
                for row in (
                    {
                        "event": "HOST_MCP_PREPARE_ATTEMPT",
                        "logical_mcp_calls": 1,
                        "attempt_trace_id": attempt_trace_id,
                    },
                    {
                        "event": "HOST_MCP_PREPARE_CONTEXT",
                        "attempt_trace_id": attempt_trace_id,
                        "access_outcome": {
                            "status": expected.access_status,
                            "execution_action": expected.execution_action,
                            "provider_execution": expected.provider_execution,
                            "terminal_stage": expected.terminal_stage,
                            "context_digest": None,
                            "canonical_position": None,
                            "reason_code": expected.reason_code,
                            "trace_id": "content-free-trace",
                        },
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            _argv, 0, stdout=_memory_fault_stdout(expected), stderr=b""
        )

    def stop_fixture() -> None:
        receipt = lifecycle.fault_plan.receipts[0]
        receipt.path.write_text(
            json.dumps(
                {
                    "schema": receipt.schema,
                    "mode": "MALFORMED",
                    "request_count": 1,
                    "capability_request_count": 1,
                    "faults_injected": 1,
                    "automatic_retries": 0,
                    "raw_request_persisted": False,
                    "credential_material_persisted": False,
                    "prompt_material_persisted": False,
                    "cleanup": {
                        "attempted": True,
                        "listener_closed": True,
                        "server_stopped": True,
                        "worker_threads_stopped": True,
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        receipt.path.chmod(0o600)

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(lifecycle, "_activate_post_readiness_fault", lambda _r: None)
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)
    monkeypatch.setattr(lifecycle, "_stop_fault_fixture", stop_fixture)

    measured = lifecycle._smoke_fault_scenario()

    identity = measured["fault_execution"]["receipt_identities"][0]
    receipt = lifecycle.fault_plan.receipts[0]
    assert identity == {
        "name": receipt.name,
        "path": str(receipt.path),
        "schema": receipt.schema,
        "sha256": runner.u0._sha256_file(receipt.path),
    }
    assert measured["fault_execution"]["provider_terminal"] is None


def test_fault_failure_receipt_observation_keeps_only_identity_not_raw_content(
    tmp_path: Path,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)

    class Runtime:
        reader_token = "private-reader-token-value"

    paths = runner.RunPaths("dg13u-u1-failure-receipt", durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths,
        runner.CASES["U1-RUNTIME-MALFORMED"],
        Runtime(),
        temporary / "product",
    )
    lifecycle.fault_plan = runner.fault_execution.build_fault_execution_plan(
        "U1-RUNTIME-MALFORMED",
        run_owned_root=uds,
        python_executable=Path(sys.executable),
    )
    receipt = lifecycle.fault_plan.receipts[0]
    private_value = "private raw prompt must never reach failure observation"
    receipt.path.write_text(
        json.dumps({"schema": receipt.schema, "prompt": private_value}) + "\n",
        encoding="utf-8",
    )
    receipt.path.chmod(0o600)

    lifecycle._preserve_fault_failure_measurement(
        completed=None,
        openworker_latency_ms=0.0,
        previous_ledger=(),
        previous_trace=(),
    )

    raw = (durable / "fault-execution-observation.json").read_text(encoding="utf-8")
    observation = json.loads(raw)
    assert private_value not in raw
    assert observation["fixture_receipts"] == [
        {
            "name": receipt.name,
            "path": str(receipt.path),
            "expected_schema": receipt.schema,
            "observed_schema": receipt.schema,
            "present": True,
            "private_regular_file": True,
            "bytes": len(receipt.path.read_bytes()),
            "sha256": runner.u0._sha256_file(receipt.path),
        }
    ]


def test_openworker_launch_uses_secret_env_file_and_dedicated_reader_lite_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir()
    paths = runner.RunPaths("dg13u-u1-worker-start", durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = "runtime-reader-secret-12345678901234567890"

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    lifecycle.gateway = "172.31.0.1"
    lifecycle.host_port = 49153
    lifecycle.ingress_token = "private-ingress-token-value"
    lifecycle.socket_path.write_text("synthetic-socket", encoding="utf-8")
    commands: list[list[str]] = []

    def command_bytes(command, **_kwargs):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return subprocess.CompletedProcess(
            command, 0, stdout=b"container-id", stderr=b""
        )

    present = {lifecycle.container_name}

    def remove(name: str) -> None:
        present.remove(name)

    monkeypatch.setattr(runner, "_command_bytes", command_bytes)
    monkeypatch.setattr(runner, "_docker_remove_container", remove)
    monkeypatch.setattr(
        runner, "_docker_absent", lambda _kind, name: name not in present
    )
    resources = runner.ResourceRegistry(paths.run_id)
    lifecycle._start_worker(resources)

    docker_run = commands[0]
    assert docker_run[:2] == ["docker", "run"]
    assert "private-ingress-token-value" not in docker_run
    assert [docker_run[docker_run.index("--network") + 1]] == [lifecycle.network_name]
    assert "ALL" in docker_run
    assert "no-new-privileges:true" in docker_run
    assert any(
        value.endswith(",dst=/run/milai-mcp/reader-lite.sock,readonly")
        for value in docker_run
    )
    env_file = Path(docker_run[docker_run.index("--env-file") + 1])
    assert env_file.is_relative_to(temporary)
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "OPENWORKER_KEY=private-ingress-token-value",
        "OPENWORKER_URL=http://172.31.0.1:49153/v1",
    ]
    receipt = resources.cleanup_all()
    assert receipt["status"] == "PASS"
    assert present == set()


def test_host_ingress_token_generation_is_always_validator_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)

    class Runtime:
        identity = None
        reader_token = "runtime-reader-token"

    lifecycle = runner.OpenWorkerU1Lifecycle(
        runner.RunPaths("dg13u-u1-ingress-token", durable, temporary, uds),
        runner.CASES["U1-NONE-EN"],
        Runtime(),
        temporary / "product",
    )
    lifecycle.gateway = "127.0.0.1"
    expected = "ab" * 32

    def token_hex(byte_count: int) -> str:
        assert byte_count == 32
        return expected

    monkeypatch.setattr(runner.secrets, "token_hex", token_hex)
    monkeypatch.setattr(
        runner.secrets,
        "token_urlsafe",
        lambda _count: pytest.fail("URL-safe '-' is outside the Host token alphabet"),
    )
    monkeypatch.setattr(
        runner,
        "_provider_capability",
        lambda *_args, **_kwargs: {"schema": "synthetic.provider-capability.v1"},
    )
    monkeypatch.setattr(runner, "_free_bind_port", lambda _host: 49153)

    lifecycle._initialize_host_assets()

    token_path = temporary / "secrets/host-ingress.token"
    assert lifecycle.ingress_token == expected
    assert token_path.read_text(encoding="utf-8") == expected
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert runner.re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:]{15,255}", expected)


def test_reader_lite_broker_uses_exact_product_and_keeps_runtime_token_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = Path("/dev/shm") / (
        "u1-broker-test-"
        + runner.hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    )
    product_bin = temporary / "product-venv/bin"
    for path in (durable, temporary, uds, product_bin):
        path.mkdir(parents=True, exist_ok=True)
    for name in ("milai-mcp", "milai-mcp-broker"):
        executable = product_bin / name
        executable.write_text(f"exact:{name}", encoding="utf-8")
        executable.chmod(0o700)
    paths = runner.RunPaths("dg13u-u1-broker-start", durable, temporary, uds)

    class Runtime:
        identity = runner.FreshRuntimeIdentity(
            "fresh-db",
            "http://127.0.0.1:49154",
            101,
            "api",
            102,
            "worker",
            "head",
        )
        reader_token = "private-runtime-reader-token-value"

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths,
        runner.CASES["U1-NONE-EN"],
        Runtime(),
        temporary / "product-venv",
    )
    listener: socket.socket | None = None
    alive = True
    popen_arguments: list[str] = []

    class Process:
        pid = 31234

        def poll(self):  # type: ignore[no-untyped-def]
            return None if alive else 0

    def popen(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal listener
        popen_arguments.extend(arguments)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(lifecycle.socket_path))
        os.chmod(lifecycle.socket_path, 0o600)
        listener.listen()
        return Process()

    def terminate(_process, _marker):  # type: ignore[no-untyped-def]
        nonlocal alive
        alive = False
        assert listener is not None
        listener.close()
        lifecycle.socket_path.unlink()

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner, "_process_marker", lambda _pid: "7001")
    monkeypatch.setattr(runner, "_process_alive", lambda _pid, _marker: alive)
    monkeypatch.setattr(runner, "_terminate_owned_process", terminate)
    resources = runner.ResourceRegistry(paths.run_id)
    lifecycle._start_broker(resources)

    assert popen_arguments[0] == str(product_bin / "milai-mcp-broker")
    assert Runtime.reader_token not in popen_arguments
    policy = json.loads(lifecycle.policy_path.read_text(encoding="utf-8"))
    assert policy["mcp_executable"] == str(product_bin / "milai-mcp")
    assert policy["mcp_executable_sha256"] == runner.u0._sha256_file(
        product_bin / "milai-mcp"
    )
    assert policy["scope"] == {"project_ids": ["orchid-release"]}
    assert policy["required_authority"] == "INFORMATIONAL"
    assert policy["mcp_max_retries"] == 0
    token_file = temporary / "secrets/reader.token"
    assert token_file.read_text(encoding="utf-8") == Runtime.reader_token
    assert token_file.stat().st_mode & 0o777 == 0o600
    assert all(
        Runtime.reader_token.encode() not in artifact.read_bytes()
        for artifact in durable.rglob("*")
        if artifact.is_file()
    )
    receipt = resources.cleanup_all()
    assert receipt["status"] == "PASS"
    assert not lifecycle.socket_path.exists()
    lifecycle.policy_path.unlink()
    uds.rmdir()


def test_openworker_security_identity_rejects_non_internal_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = runner.RunPaths(
        "dg13u-u1-security-twin",
        tmp_path / "durable",
        tmp_path / "temporary",
        tmp_path / "uds",
    )

    class Runtime:
        identity = None
        reader_token = None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), tmp_path / "product"
    )
    container = {
        "HostConfig": {
            "NetworkMode": lifecycle.network_name,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Config": {"Env": ["OPENWORKER_KEY=redacted", "OPENWORKER_URL=http://host"]},
        "Mounts": [
            {
                "Destination": "/run/milai-mcp/reader-lite.sock",
                "RW": False,
            }
        ],
    }

    def inspect(command):  # type: ignore[no-untyped-def]
        if command[1] == "container":
            return [container]
        return [{"Internal": False}]

    monkeypatch.setattr(runner.u0, "_run_json", inspect)
    with pytest.raises(runner.RunError, match="isolation boundary"):
        lifecycle._security_identity()


@pytest.mark.parametrize(
    ("return_code", "output", "expected_message"),
    [
        (17, b"milai failed", "MCP list command failed"),
        (0, b"milai failed", "reader-lite MCP is not connected"),
        (0, b"milai disconnected", "reader-lite MCP is not connected"),
    ],
)
def test_readiness_persists_bounded_mcp_diagnostic_before_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    return_code: int,
    output: bytes,
    expected_message: str,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths("dg13u-u1-readiness", durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = "runtime-reader-secret-12345678901234567890"

    class Process:
        @staticmethod
        def poll() -> None:
            return None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    lifecycle.started = True
    lifecycle.ingress_token = "ingress-secret-123456789012345678901234"
    lifecycle.host_process = Process()  # type: ignore[assignment]
    lifecycle.broker_process = Process()  # type: ignore[assignment]
    captured: list[bool] = []
    prompt = runner._case_prompt(lifecycle.case)
    observed_output = (
        output
        + (
            "\nMCP error: connection closed "
            f"TOKEN={Runtime.reader_token} /private/host/socket "
            f"ses_private123 msg_private456 {'z' * 64} {prompt}"
        ).encode()
    )

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        if arguments[-1] == "list":
            return subprocess.CompletedProcess(
                arguments, return_code, stdout=observed_output, stderr=b""
            )
        return subprocess.CompletedProcess(arguments, 0, stdout=b"healthy", stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(
        lifecycle, "_capture_worker_logs", lambda: captured.append(True)
    )
    with pytest.raises(runner.RunError, match=expected_message):
        lifecycle.readiness()

    diagnostic_path = durable / "readiness-diagnostic.json"
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["status"] == "FAIL"
    assert diagnostic["exit_code"] == return_code
    assert diagnostic["stdout"] == {
        "bytes": len(observed_output),
        "sha256": runner.hashlib.sha256(observed_output).hexdigest(),
    }
    assert diagnostic["allowlisted_observation"]["detected_mcp_names"] == (
        ["milai"] if b"milai" in output else []
    )
    assert diagnostic["allowlisted_observation"]["reason_code"] in {
        "MCP_LIST_EXIT_NONZERO",
        "MCP_CONNECTION_STATUS_NOT_CONNECTED",
    }
    assert diagnostic["allowlisted_observation"]["line_count"] == 2
    assert diagnostic["redacted_text"]["bytes"] <= 12 * 1024
    persisted = diagnostic_path.read_bytes()
    assert Runtime.reader_token.encode() not in persisted
    assert lifecycle.ingress_token.encode() not in persisted
    assert prompt.encode() not in persisted
    assert b"/private/host/socket" not in persisted
    assert b"ses_private123" not in persisted
    assert b"msg_private456" not in persisted
    assert ("z" * 64).encode() not in persisted
    assert b"connection closed" in persisted
    assert diagnostic_path.stat().st_mode & 0o777 == 0o600
    assert captured == [True]


def test_readiness_uses_one_ansi_stripped_connected_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths("dg13u-u1-readiness-ansi", durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = None

    class Process:
        @staticmethod
        def poll() -> None:
            return None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    lifecycle.started = True
    lifecycle.host_process = Process()  # type: ignore[assignment]
    lifecycle.broker_process = Process()  # type: ignore[assignment]
    captured: list[bool] = []

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        output = b"milai connec\x1b[32mted" if arguments[-1] == "list" else b"healthy"
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(lifecycle, "_security_identity", lambda: {"status": "PASS"})
    monkeypatch.setattr(lifecycle, "_wait_worker_bootstrap_quiescent", lambda: None)
    monkeypatch.setattr(
        lifecycle, "_capture_worker_logs", lambda: captured.append(True)
    )

    readiness = lifecycle.readiness()

    assert readiness["openworker"] == "PASS"
    diagnostic = json.loads((durable / "readiness-diagnostic.json").read_text())
    assert diagnostic["status"] == "PASS"
    assert diagnostic["allowlisted_observation"] == {
        "detected_mcp_names": ["milai"],
        "detected_state_tokens": ["connected"],
        "line_count": 1,
        "reason_code": "MCP_CONNECTED",
    }
    assert diagnostic["redacted_text"]["text"] == "milai connected"
    assert captured == [True]


def test_worker_bootstrap_quiescence_waits_for_marker_and_stable_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)

    class Runtime:
        reader_token = None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        runner.RunPaths("dg13u-u1-bootstrap-ready", durable, temporary, uds),
        runner.CASES["U1-RUNTIME-DOWN"],
        Runtime(),
        temporary / "product",
    )
    lifecycle.host_trace.write_text('{"event":"PREWARM_REJECTED"}\n', encoding="utf-8")
    lifecycle.provider_ledger.write_text("", encoding="utf-8")
    calls = {"count": 0}

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        output = (
            b"Pre-warmed in 0s\nDatabase migration complete.\n"
            if calls["count"] > 1
            else b"OpenCode ready\n"
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(runner, "_docker_absent", lambda *_args: False)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    lifecycle._wait_worker_bootstrap_quiescent()

    assert calls["count"] == 11


def test_worker_log_capture_is_bounded_and_redacts_credentials_paths_and_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths("dg13u-u1-worker-log", durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = "runtime-reader-private-value-1234567890"

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    lifecycle.ingress_token = "ingress-private-value-12345678901234567890"
    prompt = runner._case_prompt(lifecycle.case)
    raw = (
        f"API_KEY={lifecycle.ingress_token} path=/private/run/file prompt={prompt}\n"
        + Runtime.reader_token
        + "\n"
        + "worker event failed\n" * 2000
    ).encode()
    monkeypatch.setattr(
        runner,
        "_command_bytes",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["docker"], 0, stdout=raw, stderr=b""
        ),
    )

    lifecycle._capture_worker_logs()

    persisted = lifecycle.worker_log.read_bytes()
    value = json.loads(persisted)
    assert len(persisted) < 16 * 1024
    assert value["schema"] == "milai.dg13u.u1-worker-log.v1"
    assert value["observed_bytes"] == len(raw)
    assert value["truncated"] is True
    assert value["excerpt_bytes"] <= 12 * 1024
    assert lifecycle.ingress_token.encode() not in persisted
    assert Runtime.reader_token.encode() not in persisted
    assert prompt.encode() not in persisted
    assert b"/private/run/file" not in persisted


def test_smoke_command_diagnostic_is_bounded_allowlisted_and_fail_closed_redacted(
    tmp_path: Path,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths("dg13u-u1-smoke-diagnostic", durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = "runtime-reader-private-value-1234567890"

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    lifecycle.ingress_token = "ingress-private-value-12345678901234567890"
    prompt = runner._case_prompt(lifecycle.case)
    opaque = "z" * 64
    sensitive_line = (
        "\x1b[31mError\x1b[0m: request max_tokens exceeds its reservation "
        f"prompt={prompt} Bearer {lifecycle.ingress_token} "
        f"TOKEN={Runtime.reader_token} OPENWORKER_KEY=env-private-value "
        "/private/host/runtime.json ses_private123 msg_private456 task_private789 "
        "session_id=session-private message-id=message-private task_id=task-private "
        f"{opaque}\n"
    )
    stderr = (sensitive_line * 900).encode()
    completed = subprocess.CompletedProcess(
        ["opencode", "run"], 23, stdout=b"ordinary private answer\n", stderr=stderr
    )

    lifecycle._write_smoke_command_diagnostic(completed, prompt=prompt)

    path = durable / "smoke-command-diagnostic.json"
    persisted = path.read_bytes()
    diagnostic = json.loads(persisted)
    assert len(persisted) < 16 * 1024
    assert path.stat().st_mode & 0o777 == 0o600
    assert diagnostic == {
        **diagnostic,
        "schema": "milai.dg13u.u1-smoke-command-diagnostic.v1",
        "run_id": paths.run_id,
        "case_id": lifecycle.case.case_id,
        "stage": "OPENCODE_RUN",
        "status": "FAIL",
        "reason_code": "OPENCODE_EXIT_NONZERO",
        "exit_code": 23,
        "typed_error_count": 0,
        "stdout": {
            "bytes": len(completed.stdout),
            "sha256": runner.hashlib.sha256(completed.stdout).hexdigest(),
        },
        "stderr": {
            "bytes": len(completed.stderr),
            "sha256": runner.hashlib.sha256(completed.stderr).hexdigest(),
        },
    }
    assert diagnostic["redacted_text"]["retention"] == ("ERROR_STATUS_ALLOWLIST_ONLY")
    assert diagnostic["redacted_text"]["bytes"] <= 12 * 1024
    assert diagnostic["redacted_text"]["truncated"] is True
    assert b"Error: request max_tokens exceeds its reservation" in persisted
    for sensitive in (
        b"ordinary private answer",
        prompt.encode(),
        lifecycle.ingress_token.encode(),
        Runtime.reader_token.encode(),
        b"env-private-value",
        b"/private/host/runtime.json",
        b"ses_private123",
        b"msg_private456",
        b"task_private789",
        b"session-private",
        b"message-private",
        b"task-private",
        opaque.encode(),
        b"\x1b[31m",
    ):
        assert sensitive not in persisted


def test_successful_smoke_command_diagnostic_does_not_retain_answer_text(
    tmp_path: Path,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths(
        "dg13u-u1-smoke-diagnostic-success", durable, temporary, uds
    )

    class Runtime:
        identity = None
        reader_token = None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    completed = subprocess.CompletedProcess(
        ["opencode", "run"],
        0,
        stdout=(
            b"The private provider answer says error is an ordinary word.\n"
            b'{"type":"answer","content":{"type":"error"}}\n'
            b'{"type":"message","error":"nested error content"}'
        ),
        stderr=b"",
    )

    lifecycle._write_smoke_command_diagnostic(
        completed,
        prompt=runner._case_prompt(lifecycle.case),
    )

    diagnostic = json.loads(
        (durable / "smoke-command-diagnostic.json").read_text(encoding="utf-8")
    )
    assert diagnostic["status"] == "PASS"
    assert diagnostic["reason_code"] == "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR"
    assert diagnostic["exit_code"] == 0
    assert diagnostic["typed_error_count"] == 0
    assert diagnostic["redacted_text"]["text"] == ""
    assert diagnostic["redacted_text"]["bytes"] == 0
    assert diagnostic["redacted_text"]["line_count"] == 0


def test_exit_zero_top_level_opencode_typed_error_is_a_failed_command_truth(
    tmp_path: Path,
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths(
        "dg13u-u1-smoke-diagnostic-typed-error", durable, temporary, uds
    )

    class Runtime:
        identity = None
        reader_token = None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    stdout = (
        b'{"type":"answer","content":"ordinary error word"}\n'
        b'{"type":"er\x1b[31mror","error":{"message":"fixed failure",'
        b'"reason_code":"TASK_OPERATION_REPLAY"}}\n'
    )
    completed = subprocess.CompletedProcess(
        ["opencode", "run"], 0, stdout=stdout, stderr=b""
    )

    lifecycle._write_smoke_command_diagnostic(
        completed,
        prompt=runner._case_prompt(lifecycle.case),
    )

    diagnostic = json.loads(
        (durable / "smoke-command-diagnostic.json").read_text(encoding="utf-8")
    )
    assert diagnostic["status"] == "FAIL"
    assert diagnostic["reason_code"] == "OPENCODE_TYPED_ERROR"
    assert diagnostic["exit_code"] == 0
    assert diagnostic["typed_error_count"] == 1
    assert "fixed failure" in diagnostic["redacted_text"]["text"]
    assert "TASK_OPERATION_REPLAY" in diagnostic["redacted_text"]["text"]
    assert "ordinary error word" not in diagnostic["redacted_text"]["text"]
    assert "\x1b" not in diagnostic["redacted_text"]["text"]


def test_local_readiness_persists_typed_reason_code(
    tmp_path: Path,
) -> None:
    durable = tmp_path / "durable"
    for path in (durable, tmp_path / "temporary", tmp_path / "uds"):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths(
        "dg13u-u1-readiness-typed",
        durable,
        tmp_path / "temporary",
        tmp_path / "uds",
    )

    class Runtime:
        @staticmethod
        def ready() -> bool:
            return True

    class U1:
        @staticmethod
        def readiness() -> dict[str, object]:
            raise runner.RunError("OpenWorker MCP list command failed")

    composition = runner.LocalComposition(tmp_path / "runtime.env")
    composition.runtime = Runtime()  # type: ignore[assignment]
    composition.u1 = U1()  # type: ignore[assignment]
    composition.identity = {}
    result = composition.readiness(paths, runner.CASES["U1-NONE-EN"])

    assert result.status == "FAIL"
    assert result.reason_code == "OPENWORKER_MCP_LIST_COMMAND_FAILED"
    failure = json.loads((durable / "readiness-failure.json").read_text())
    assert failure["reason_code"] == result.reason_code
    assert failure["exception_class"] == "RunError"


def test_none_smoke_executes_once_and_rejects_duplicate_provider_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir()
    paths = runner.RunPaths("dg13u-u1-once-only", durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    ledger_rows = [
        {"event": "RESERVED", "logical_request_id": "once"},
        {
            "event": "PROVIDER_TERMINAL",
            "logical_request_id": "once",
            "status": "SUCCEEDED",
            "native_request_id": "native-once",
        },
    ]
    lifecycle.provider_ledger.write_text(
        "".join(json.dumps(row) + "\n" for row in ledger_rows), encoding="utf-8"
    )
    lifecycle.host_trace.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in (
                {"event": "HOST_MEMORY_ROUTE_NONE", "mcp_calls": 0},
                {
                    "event": "PROVIDER_ANSWER",
                    "mcp_calls": 0,
                    "context_in_prompt": False,
                    "logical_request_id": "once",
                },
            )
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def command(command, **_kwargs):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=b"answer", stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)
    evidence = lifecycle.smoke()
    assert len(commands) == 1
    assert evidence["observed_provider_calls"] == 1
    assert evidence["observed_mcp_calls"] == 0
    assert evidence["automatic_retries"] == 0
    command_diagnostic = json.loads(
        (durable / "smoke-command-diagnostic.json").read_text(encoding="utf-8")
    )
    assert command_diagnostic["status"] == "PASS"
    assert command_diagnostic["reason_code"] == ("OPENCODE_EXIT_ZERO_NO_TYPED_ERROR")

    lifecycle.provider_ledger.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in [
                *ledger_rows,
                {"event": "RESERVED", "logical_request_id": "retry"},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(runner.RunError, match="accounting failed"):
        lifecycle.smoke()


def test_none_smoke_rejects_exit_zero_typed_error_after_successful_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir()
    paths = runner.RunPaths(
        "dg13u-u1-typed-error-after-provider", durable, temporary, uds
    )

    class Runtime:
        identity = None
        reader_token = None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths, runner.CASES["U1-NONE-EN"], Runtime(), temporary / "product"
    )
    lifecycle.provider_ledger.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in (
                {"event": "RESERVED", "logical_request_id": "once"},
                {
                    "event": "PROVIDER_TERMINAL",
                    "logical_request_id": "once",
                    "status": "SUCCEEDED",
                    "native_request_id": "native-once",
                },
            )
        ),
        encoding="utf-8",
    )
    lifecycle.host_trace.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in (
                {"event": "HOST_MEMORY_ROUTE_NONE", "mcp_calls": 0},
                {
                    "event": "PROVIDER_ANSWER",
                    "mcp_calls": 0,
                    "context_in_prompt": False,
                    "logical_request_id": "once",
                },
            )
        ),
        encoding="utf-8",
    )
    typed_error = (
        b'{"type":"error","error":{"message":"Host request failed",'
        b'"reason_code":"TASK_OPERATION_REPLAY"}}\n'
    )
    monkeypatch.setattr(
        runner,
        "_command_bytes",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout=typed_error, stderr=b""
        ),
    )
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)

    with pytest.raises(runner.RunError, match="accounting failed"):
        lifecycle.smoke()

    diagnostic = json.loads(
        (durable / "smoke-command-diagnostic.json").read_text(encoding="utf-8")
    )
    assert diagnostic["status"] == "FAIL"
    assert diagnostic["reason_code"] == "OPENCODE_TYPED_ERROR"
    assert diagnostic["exit_code"] == 0
    assert diagnostic["typed_error_count"] == 1


def test_exact_smoke_requires_one_hidden_mcp_and_context_in_provider_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir()
    paths = runner.RunPaths("dg13u-u1-exact-unit", durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths,
        runner.CASES["U1-EXACT-TARGET-EN"],
        Runtime(),
        temporary / "product",
    )
    lifecycle.provider_ledger.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in (
                {"event": "RESERVED", "logical_request_id": "exact-once"},
                {
                    "event": "PROVIDER_TERMINAL",
                    "logical_request_id": "exact-once",
                    "status": "SUCCEEDED",
                    "native_request_id": "native-exact-once",
                },
            )
        ),
        encoding="utf-8",
    )
    prepare = {
        "event": "HOST_MCP_PREPARE_CONTEXT",
        "route": "EXACT",
        "current_state_status": "READY",
        "current_state_claim_count": 1,
        "compiled_memory_tokens": 42,
        "access_outcome": {"status": "READY"},
        "recall_execution_trace": {"terminal_route": "EXACT"},
    }
    answer = {
        "event": "PROVIDER_ANSWER",
        "mcp_calls": 1,
        "context_in_prompt": True,
        "logical_request_id": "exact-once",
        "trace_id": "runtime-trace-exact",
    }
    lifecycle.host_trace.write_text(
        json.dumps(prepare) + "\n" + json.dumps(answer) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "_command_bytes",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout=b"answer", stderr=b""
        ),
    )
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)

    evidence = lifecycle.smoke()
    assert evidence["observed_provider_calls"] == 1
    assert evidence["observed_mcp_calls"] == 1
    assert evidence["context_tokens"] == 42
    assert evidence["context_in_prompt"] is True
    assert evidence["memory_route"] == "EXACT"
    assert evidence["access_id_sha256"]
    assert evidence["mcp_receipt_sha256"]
    assert evidence["runtime_trace_sha256"]

    answer["context_in_prompt"] = False
    lifecycle.host_trace.write_text(
        json.dumps(prepare) + "\n" + json.dumps(answer) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(runner.RunError, match="accounting failed"):
        lifecycle.smoke()


def _task_smoke_lifecycle(
    tmp_path: Path,
    case_id: str,
) -> runner.OpenWorkerU1Lifecycle:
    run_id = f"dg13u-u1-{case_id.casefold()}"
    durable = tmp_path / run_id
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths(run_id, durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = None

    return runner.OpenWorkerU1Lifecycle(
        paths,
        runner.CASES[case_id],
        Runtime(),
        temporary / "product",
    )


def _install_task_smoke_transport(
    lifecycle: runner.OpenWorkerU1Lifecycle,
    monkeypatch: pytest.MonkeyPatch,
    *,
    duplicate_operation: bool = False,
    omit_provider_turn: str | None = None,
    continuation_cache_reuse: bool = False,
) -> tuple[list[list[str]], dict[str, int]]:
    scenario = task_scenarios.scenario_for_case(lifecycle.case.case_id)
    prompts = {
        runner._task_turn_prompt(lifecycle.case, turn): turn for turn in scenario.turns
    }
    commands: list[list[str]] = []
    created_sessions: list[str] = []
    active = 0
    concurrency = {"max_active": 0}
    lock = threading.Lock()
    concurrent_entry = (
        threading.Barrier(2) if lifecycle.case.case_id == "U1-TASK-CONCURRENT" else None
    )

    def append_rows(path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("a", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True) + "\n")

    def command(command, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal active
        current = list(command)
        if "curl" in current:
            session_id = f"ses-{'a' if not created_sessions else 'b'}"
            created_sessions.append(session_id)
            return subprocess.CompletedProcess(
                current,
                0,
                stdout=json.dumps(
                    {"id": session_id, "directory": "/openworker/runtime"}
                ).encode(),
                stderr=b"",
            )
        prompt = current[-1]
        turn = prompts[prompt]
        assert current[current.index("--attach") + 1] == "http://127.0.0.1:4096"
        session_id = current[current.index("--session") + 1]
        assert current[current.index("--dir") + 1] == "/openworker/runtime"
        if turn.session_action == "NEW":
            assert session_id == f"ses-{turn.session_ref.casefold()}"
        if concurrent_entry is not None:
            with lock:
                active += 1
                concurrency["max_active"] = max(concurrency["max_active"], active)
            concurrent_entry.wait(timeout=2)
        session_sha = runner.hashlib.sha256(session_id.encode()).hexdigest()
        operation_sha = runner.hashlib.sha256(
            ("same-operation" if duplicate_operation else f"op:{turn.turn_id}").encode()
        ).hexdigest()
        task_sha = runner.hashlib.sha256(
            f"task:{turn.session_ref}".encode()
        ).hexdigest()
        question_sha = runner.hashlib.sha256(prompt.encode()).hexdigest()
        logical_id = f"logical-{turn.turn_id.casefold()}"
        trace_id = f"trace-{turn.turn_id.casefold()}"
        native_id = f"native-{turn.turn_id.casefold()}"
        query_first = lifecycle.case.case_id == "U1-TASK-CONTINUE"
        cached = turn.session_action == "CONTINUE" and (
            not query_first or continuation_cache_reuse
        )
        route = "CACHE" if cached else ("SEARCH" if query_first else "L0")
        trace_rows: list[dict[str, object]] = [
            {
                "event": "HOST_NATIVE_REQUEST_OBSERVED",
                "question_sha256": question_sha,
                "task_session_sha256": session_sha,
                "task_operation_sha256": operation_sha,
                "tool_count": 2,
            },
            {
                "event": "HOST_NATIVE_TASK_BOUND",
                "task_session_sha256": session_sha,
                "task_operation_sha256": operation_sha,
                "task_id_sha256": task_sha,
                "task_relation": (
                    "CONTINUE" if turn.session_action == "CONTINUE" else "TASK_START"
                ),
            },
            {
                "event": "HOST_MCP_PREPARE_ATTEMPT",
                "question_sha256": question_sha,
                "task_session_sha256": session_sha,
                "task_operation_sha256": operation_sha,
                "requested_route": route,
                "logical_mcp_calls": 1,
                "fresh_resolve": query_first and not cached,
                "mcp_tool": "milai_memory_resolve" if query_first else None,
            },
            {
                "event": "HOST_MCP_PREPARE_CONTEXT",
                "question_sha256": question_sha,
                "task_session_sha256": session_sha,
                "task_operation_sha256": operation_sha,
                "route": route,
                "prepare_status": ("UNCHANGED" if cached else "READY"),
                "current_state_status": (None if cached else "HIT"),
                "current_state_claim_count": (0 if cached else 1),
                "compiled_memory_tokens": (None if cached else 41),
                "access_outcome": {
                    "terminal_stage": (
                        "CACHE" if cached else ("FTS" if query_first else "EXACT")
                    ),
                    "status": "CONTEXT_READY_CURRENT",
                },
                "cache_validation_outcome": ("HIT" if cached else None),
                "recall_execution_trace": {
                    "terminal_route": route
                },
                "fresh_resolve": query_first and not cached,
                "mcp_tool": "milai_memory_resolve" if query_first else None,
                "trace_id": trace_id,
                "timing": {
                    "mcp_handler_ms": 2.0,
                    "runtime_total_ms": 1.0,
                    "context_compile_ms": 0.5,
                },
            },
        ]
        ledger_rows: list[dict[str, object]] = []
        if turn.turn_id != omit_provider_turn:
            trace_rows.append(
                {
                    "event": "PROVIDER_ANSWER",
                    "logical_request_id": logical_id,
                    "native_request_id": native_id,
                    "trace_id": trace_id,
                    "mcp_calls": 1,
                    "context_in_prompt": True,
                    "ordinary_tool_count": 0,
                    "adapter_total_ms": 4.0,
                    "provider_prefill_answer_ms": 2.0,
                }
            )
            ledger_rows.extend(
                (
                    {"event": "RESERVED", "logical_request_id": logical_id},
                    {
                        "event": "PROVIDER_TERMINAL",
                        "logical_request_id": logical_id,
                        "status": "SUCCEEDED",
                        "native_request_id": native_id,
                    },
                )
            )
        with lock:
            commands.append(current)
            append_rows(lifecycle.host_trace, trace_rows)
            append_rows(lifecycle.provider_ledger, ledger_rows)
        raw = "\n".join(
            (
                json.dumps(
                    {
                        "type": "step_start",
                        "sessionID": session_id,
                        "part": {"type": "step-start"},
                    }
                ),
                json.dumps(
                    {
                        "type": "text",
                        "sessionID": session_id,
                        "part": {"type": "text", "text": "private answer"},
                    }
                ),
            )
        ).encode()
        if concurrent_entry is not None:
            with lock:
                active -= 1
        return subprocess.CompletedProcess(current, 0, stdout=raw, stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)
    return commands, concurrency


@pytest.mark.parametrize(
    ("case_id", "expected_calls", "expected_sessions"),
    (
        ("U1-TASK-CONTINUE", 2, 1),
        ("U1-TASK-SWITCH", 2, 2),
        ("U1-TASK-RETURN", 3, 2),
    ),
)
def test_task_smoke_executes_frozen_serial_scenario_with_hash_only_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    expected_calls: int,
    expected_sessions: int,
) -> None:
    lifecycle = _task_smoke_lifecycle(tmp_path, case_id)
    commands, _concurrency = _install_task_smoke_transport(lifecycle, monkeypatch)

    evidence = lifecycle.smoke()

    assert len(commands) == expected_calls
    assert all("--attach" in command for command in commands)
    assert evidence["observed_mcp_calls"] == expected_calls
    assert evidence["observed_provider_calls"] == expected_calls
    assert evidence["automatic_retries"] == 0
    assert evidence["model_visible_memory_tool_events"] == 0
    task = evidence["task_case_evidence"]
    assert task["status"] == "PASS"
    assert task["turn_count"] == expected_calls
    assert task["session_count"] == expected_sessions
    assert task["operation_ids_unique"] is True
    contexts = evidence["task_turn_context_evidence"]
    assert [row["prepare_status"] for row in contexts] == [
        (
            "UNCHANGED"
            if turn.session_action == "CONTINUE" and case_id != "U1-TASK-CONTINUE"
            else "READY"
        )
        for turn in task_scenarios.scenario_for_case(case_id).turns
    ]
    assert all(
        row["cache_validation_outcome"] == "HIT"
        for row in contexts
        if row["session_action"] == "CONTINUE" and case_id != "U1-TASK-CONTINUE"
    )
    if case_id == "U1-TASK-CONTINUE":
        assert evidence["memory_route"] == "QUERY_FIRST"
        assert task["all_turns_fresh_resolve"] is True
        assert task["mcp_tool"] == "milai_memory_resolve"
        assert all(row["fresh_resolve"] is True for row in contexts)
        assert all(row["mcp_tool"] == "milai_memory_resolve" for row in contexts)
    encoded = json.dumps(task, sort_keys=True)
    assert "ses-a" not in encoded
    assert "ses-b" not in encoded
    assert "private answer" not in encoded
    assert all("--session" in command and "--dir" in command for command in commands)
    command_sessions = [command[command.index("--session") + 1] for command in commands]
    assert len(set(command_sessions)) == expected_sessions


def test_task_concurrent_uses_one_real_barrier_and_preserves_session_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _task_smoke_lifecycle(tmp_path, "U1-TASK-CONCURRENT")
    commands, concurrency = _install_task_smoke_transport(lifecycle, monkeypatch)

    evidence = lifecycle.smoke()

    assert len(commands) == 2
    assert concurrency["max_active"] == 2
    task = evidence["task_case_evidence"]
    barrier_hashes = {row["barrier_release_sha256"] for row in task["rows"]}
    assert len(barrier_hashes) == 1
    assert None not in barrier_hashes
    assert task["session_count"] == 2
    assert task["session_task_bindings_distinct"] is True


def test_task_smoke_fails_closed_on_reused_operation_and_preserves_measured_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _task_smoke_lifecycle(tmp_path, "U1-TASK-CONTINUE")
    _install_task_smoke_transport(
        lifecycle,
        monkeypatch,
        duplicate_operation=True,
    )

    with pytest.raises(runner.RunError, match="task smoke accounting failed"):
        lifecycle.smoke()

    assert lifecycle.smoke_evidence is not None
    assert lifecycle.smoke_evidence["observed_mcp_calls"] == 2
    assert lifecycle.smoke_evidence["observed_provider_calls"] == 2
    assert lifecycle.smoke_evidence["automatic_retries"] == 0


def test_task_continuation_rejects_cache_reuse_in_query_first_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _task_smoke_lifecycle(tmp_path, "U1-TASK-CONTINUE")
    _install_task_smoke_transport(
        lifecycle,
        monkeypatch,
        continuation_cache_reuse=True,
    )

    with pytest.raises(runner.RunError, match="task smoke accounting failed"):
        lifecycle.smoke()

    assert lifecycle.smoke_evidence is not None
    assert lifecycle.smoke_evidence["observed_mcp_calls"] == 2
    assert lifecycle.smoke_evidence["observed_provider_calls"] == 2


def test_task_smoke_measurement_is_accepted_by_frozen_evidence_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _task_smoke_lifecycle(tmp_path, "U1-TASK-RETURN")
    _install_task_smoke_transport(lifecycle, monkeypatch)
    evidence = lifecycle.smoke()

    receipt = runner.evidence_artifacts.write_smoke_evidence_artifact(
        lifecycle.paths.durable,
        runner._smoke_artifact_measurement(
            lifecycle.paths,
            lifecycle.case,
            runner.TerminalStatus.PASS,
            evidence,
        ),
    )

    artifact = json.loads(
        (lifecycle.paths.durable / receipt["path"]).read_text(encoding="utf-8")
    )
    assert artifact["status"] == "PASS"
    assert artifact["calls"]["mcp"]["observed"] == 3
    assert artifact["calls"]["provider"]["observed"] == 3
    assert artifact["context_tokens"] > 0
    assert all(artifact["joined_identities"].values())


def test_task_smoke_preserves_incremental_mcp_fact_when_later_provider_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _task_smoke_lifecycle(tmp_path, "U1-TASK-CONTINUE")
    _install_task_smoke_transport(
        lifecycle,
        monkeypatch,
        omit_provider_turn="A-CONTINUE",
    )

    with pytest.raises(runner.RunError, match="task smoke accounting failed"):
        lifecycle.smoke()

    assert lifecycle.smoke_evidence is not None
    assert lifecycle.smoke_evidence["observed_mcp_calls"] == 2
    assert lifecycle.smoke_evidence["observed_provider_calls"] == 1
    assert lifecycle.smoke_evidence["automatic_retries"] == 0


def test_v_like_provider_failure_persists_measured_exact_smoke_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "dg13u-u1-v-like-provider-failure"
    durable = tmp_path / run_id
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths(run_id, durable, temporary, uds)
    case = runner.CASES["U1-EXACT-TARGET-EN"]

    class Runtime:
        identity = None
        reader_token = None

    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths,
        case,
        Runtime(),
        temporary / "product",
    )
    lifecycle.provider_ledger.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in (
                {
                    "event": "RESERVED",
                    "logical_request_id": "v-like-once",
                },
                {
                    "event": "PROVIDER_TERMINAL",
                    "logical_request_id": "v-like-once",
                    "status": "FAILED",
                    "reason_code": "PROVIDER_HTTP_400",
                    "native_request_id": None,
                    "native_request_observed": False,
                },
            )
        ),
        encoding="utf-8",
    )
    prepare = {
        "event": "HOST_MCP_PREPARE_CONTEXT",
        "route": "L0",
        "prepare_status": "READY",
        "current_state_status": "HIT",
        "current_state_claim_count": 1,
        "compiled_memory_tokens": 42,
        "access_outcome": {
            "status": "CONTEXT_READY_CURRENT",
            "terminal_stage": "EXACT",
        },
        "recall_execution_trace": {"terminal_route": "L0"},
        "timing": {
            "mcp_handler_ms": 2.0,
            "runtime_total_ms": 3.0,
            "context_compile_ms": 1.0,
        },
    }
    lifecycle.host_trace.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                prepare,
                {
                    "event": "HOST_INGRESS_TERMINAL",
                    "exception_type": "ProviderCallError",
                    "reason_code": "PROVIDER_HTTP_400",
                },
                {
                    "event": "HOST_INGRESS_TERMINAL",
                    "exception_type": "OpenWorkerAdapterError",
                    "reason_code": "TASK_OPERATION_REPLAY",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    typed_error = (
        b'{"type":"error","error":{"message":"Host request failed",'
        b'"reason_code":"TASK_OPERATION_REPLAY"}}\n'
    )
    monkeypatch.setattr(
        runner,
        "_command_bytes",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout=typed_error, stderr=b""
        ),
    )
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)
    composition = runner.LocalComposition(tmp_path / "runtime.env")
    composition.u1 = lifecycle

    result = composition.smoke(paths, case)

    assert result.status == runner.TerminalStatus.FAIL
    assert result.reason_code == "U1_EXACT_REAL_OPENWORKER_SMOKE_FAILED"
    assert result.evidence["observed_mcp_calls"] == 1
    assert result.evidence["observed_provider_calls"] == 1
    artifact = json.loads((durable / "smoke-evidence.json").read_text())
    assert artifact["schema"] == "milai.dg13u.u1-smoke-evidence.v1"
    assert artifact["run_id"] == run_id
    assert artifact["case_id"] == case.case_id
    assert artifact["status"] == "FAIL"
    assert artifact["calls"]["mcp"]["observed"] == 1
    assert artifact["calls"]["provider"]["observed"] == 1
    assert artifact["context_tokens"] == 42


def test_canonical_fixture_lifecycle_redacts_receipts_and_revokes_in_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir()
    paths = runner.RunPaths("dg13u-u1-canonical", durable, temporary, uds)

    class Runtime:
        identity = runner.FreshRuntimeIdentity(
            "fresh-db", "http://127.0.0.1:49155", 1, "api", 2, "worker", "head"
        )
        fixture_role_tokens = runner.FreshRuntimeRoleTokens(
            "submitter-private", "reviewer-private", "operator-private"
        )

    writer = object()
    monkeypatch.setattr(
        runner, "LoopbackRuntimeFixtureWriter", lambda *_args, **_kwargs: writer
    )
    seeded = {
        "schema": "milai.dg13u.u1-canonical-fixture.v1",
        "status": "SEEDED",
        "run_id_sha256": "a" * 64,
        "families": [
            {
                "state_key": "release.target",
                "claim_id": "private-claim-id",
                "claim_version_id": "private-version-id",
                "evidence_id": "private-evidence-id",
            }
        ],
        "mutations": [
            {
                "kind": "EVIDENCE_CAPTURE",
                "role": "submitter",
                "evidence_id": "private-evidence-id",
                "outbox_id": "private-outbox-id",
            }
        ],
    }
    monkeypatch.setattr(
        runner, "seed_u1_canonical_fixture", lambda *_args, **_kwargs: seeded
    )
    cleanup_calls: list[object] = []

    def cleanup(active_writer, active_seeded, *, run_id):  # type: ignore[no-untyped-def]
        cleanup_calls.append((active_writer, active_seeded, run_id))
        return {
            "schema": "milai.dg13u.u1-canonical-fixture-cleanup.v1",
            "status": "CLEANUP_REQUESTED",
            "run_id_sha256": "b" * 64,
            "canonical_claims_deleted": False,
            "evidence_revocations": 1,
            "receipts": [
                {
                    "evidence_id": "private-evidence-id",
                    "deletion_request_id": "private-deletion-id",
                    "canonical_block_status": "APPLIED",
                }
            ],
        }

    monkeypatch.setattr(runner, "cleanup_u1_canonical_fixture", cleanup)
    lifecycle = runner.CanonicalFixtureLifecycle(paths, Runtime())
    resources = runner.ResourceRegistry(paths.run_id)
    public = lifecycle.start(resources)

    assert (
        public["families"][0]["claim_id_sha256"]
        == runner.hashlib.sha256(b"private-claim-id").hexdigest()
    )
    seed_artifact = (durable / "canonical-fixture.json").read_text()
    assert "private-claim-id" not in seed_artifact
    assert "private-evidence-id" not in seed_artifact
    assert "private-outbox-id" not in seed_artifact
    receipt = resources.cleanup_all()
    assert receipt["status"] == "PASS"
    assert len(cleanup_calls) == 1
    cleanup_artifact = (durable / "canonical-fixture-cleanup.json").read_text()
    assert "private-evidence-id" not in cleanup_artifact
    assert "private-deletion-id" not in cleanup_artifact


def test_partial_canonical_seed_is_still_controlled_revoked_by_registry_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir()
    paths = runner.RunPaths("dg13u-u1-partial-seed", durable, temporary, uds)

    class Runtime:
        identity = runner.FreshRuntimeIdentity(
            "fresh-db", "http://127.0.0.1:49156", 1, "api", 2, "worker", "head"
        )
        fixture_role_tokens = runner.FreshRuntimeRoleTokens(
            "submitter-private", "reviewer-private", "operator-private"
        )

    monkeypatch.setattr(
        runner, "LoopbackRuntimeFixtureWriter", lambda *_args, **_kwargs: object()
    )
    partial = {
        "schema": "milai.dg13u.u1-fixture-partial.v1",
        "status": "PARTIAL",
        "run_id_sha256": "a" * 64,
        "mutations": [
            {
                "kind": "EVIDENCE_CAPTURE",
                "role": "submitter",
                "evidence_id": "partial-private-evidence-id",
            }
        ],
    }

    def seed(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise runner.FixtureSeedError("PROPOSAL_CREATE_FAILED", partial)

    monkeypatch.setattr(runner, "seed_u1_canonical_fixture", seed)
    revoked: list[str] = []

    def cleanup(_writer, seeded, *, run_id):  # type: ignore[no-untyped-def]
        del run_id
        revoked.extend(
            item["evidence_id"]
            for item in seeded["mutations"]
            if item["kind"] == "EVIDENCE_CAPTURE"
        )
        return {
            "status": "CLEANUP_REQUESTED",
            "evidence_revocations": len(revoked),
            "receipts": [{"evidence_id": value} for value in revoked],
        }

    monkeypatch.setattr(runner, "cleanup_u1_canonical_fixture", cleanup)
    lifecycle = runner.CanonicalFixtureLifecycle(paths, Runtime())
    resources = runner.ResourceRegistry(paths.run_id)
    with pytest.raises(runner.RunError, match="partial mutation"):
        lifecycle.start(resources)
    receipt = resources.cleanup_all()
    assert receipt["status"] == "PASS"
    assert revoked == ["partial-private-evidence-id"]
    assert (
        "partial-private-evidence-id"
        not in (durable / "canonical-fixture-partial.json").read_text()
    )
    assert (
        "partial-private-evidence-id"
        not in (durable / "canonical-fixture-cleanup.json").read_text()
    )


def test_resource_registry_reconciles_run_owned_resources_in_reverse_order() -> None:
    events: list[str] = []
    present = {"first", "second"}
    registry = runner.ResourceRegistry("dg13u-u1-resources")
    for name in ("first", "second"):
        registry.register(
            runner.ResourceHandle(
                "synthetic",
                f"resource/{name}",
                runner.ResourceOwnership.RUN_OWNED,
                cleanup=lambda name=name: (events.append(name), present.remove(name)),
                absent=lambda name=name: name not in present,
            )
        )
    receipt = registry.cleanup_all()
    assert receipt["status"] == "PASS"
    assert events == ["second", "first"]


def test_owned_process_cleanup_terminates_waits_and_reaps_exact_child() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        marker = runner._process_marker(process.pid)
        assert marker is not None
        runner._terminate_owned_process(process, marker)
        assert process.returncode is not None
        assert not runner._process_alive(process.pid, marker)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_owned_process_cleanup_rejects_pid_marker_mismatch() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        marker = runner._process_marker(process.pid)
        assert marker is not None
        runner._terminate_owned_process(process, marker + "-wrong")
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_zombie_child_is_not_reported_as_running() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        marker = runner._process_marker(process.pid)
        assert marker is not None
        os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)
        assert runner._process_state(process.pid) == "Z"
        assert not runner._process_alive(process.pid, marker)
    finally:
        process.wait(timeout=5)


def test_cleanup_failure_is_visible_and_never_relabels_external_vllm() -> None:
    registry = runner.ResourceRegistry("dg13u-u1-cleanup-fail")
    registry.register(
        runner.ResourceHandle(
            "external_vllm",
            "127.0.0.1:7860",
            runner.ResourceOwnership.PRESERVED_EXTERNAL,
        )
    )
    registry.register(
        runner.ResourceHandle(
            "container",
            "container/run-owned",
            runner.ResourceOwnership.RUN_OWNED,
            cleanup=lambda: (_ for _ in ()).throw(RuntimeError("synthetic")),
            absent=lambda: False,
        )
    )
    receipt = registry.cleanup_all()
    assert receipt["status"] == "FAIL"
    assert receipt["existing_vllm_preserved"] is True
    assert receipt["external_lifecycle_mutations"] == 0
    assert receipt["items"][0]["state"] == "cleanup_failed"
    assert receipt["items"][1]["state"] == "preserved_external"


def test_cache_governance_selectors_are_real_and_fixture_options_are_exact() -> None:
    assert _CACHE_GOVERNANCE_CASES <= runner._IMPLEMENTED_REAL_CASES
    assert runner._CACHE_GOVERNANCE_CASE_IDS == _CACHE_GOVERNANCE_CASES
    expected = {
        "U1-CACHE-FALLBACK": runner.FixtureOptions(),
        "U1-WRONG-TASK": runner.FixtureOptions(),
        "U1-WRONG-SCOPE": runner.FixtureOptions(wrong_scope=True),
        "U1-STALE-CURRENT": runner.FixtureOptions(),
        "U1-REVOKE-REENTRY": runner.FixtureOptions(revoke=True),
        "U1-OPEN-ISSUE": runner.FixtureOptions(open_issue=True),
    }
    assert {
        case_id: runner._fixture_options_for_case(case_id) for case_id in expected
    } == expected
    assert runner._fixture_options_for_case("U1-AUTHORITY-ESCALATION") is None
    assert runner._fixture_options_for_case("U1-ALIAS-COLLISION") is None


def test_live_post_warm_mutation_reuses_writer_updates_cleanup_receipt_and_preserves_seed_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir()
    paths = runner.RunPaths("dg13u-u1-live-mutation", durable, temporary, uds)

    class Runtime:
        identity = runner.FreshRuntimeIdentity(
            "fresh-db", "http://127.0.0.1:49157", 1, "api", 2, "worker", "head"
        )
        fixture_role_tokens = runner.FreshRuntimeRoleTokens(
            "submitter-private", "reviewer-private", "operator-private"
        )

    writer = object()
    monkeypatch.setattr(
        runner, "LoopbackRuntimeFixtureWriter", lambda *_args, **_kwargs: writer
    )
    seeded = {
        "schema": "milai.dg13u.u1-canonical-fixture.v1",
        "status": "SEEDED",
        "candidate_fixture_sha256": "a" * 64,
        "run_id_sha256": "b" * 64,
        "data_boundary": "SYNTHETIC",
        "formal_evaluation_input": False,
        "writer_roles": ["submitter", "steward"],
        "families": [
            {
                "state_key": "release.target",
                "claim_id": "private-claim",
                "claim_version_id": "private-before",
                "payload_sha256": "c" * 64,
            }
        ],
        "negative_setups": {},
        "mutations": [
            {
                "kind": "EVIDENCE_CAPTURE",
                "role": "submitter",
                "evidence_id": "private-seed-evidence",
            }
        ],
    }
    original = copy.deepcopy(seeded)
    updated = copy.deepcopy(seeded)
    updated["families"][0]["claim_version_id"] = "private-after"
    updated["negative_setups"]["state_change"] = {
        "state_key": "release.target",
        "current_claim_version_id": "private-after",
        "supporting_evidence_id": "private-change-evidence",
    }
    updated["mutations"].append(
        {
            "kind": "EVIDENCE_CAPTURE",
            "role": "submitter",
            "evidence_id": "private-change-evidence",
        }
    )
    calls: list[tuple[object, object, str]] = []

    def apply(active_writer, active_seeded, *, run_id, observed_at):  # type: ignore[no-untyped-def]
        del observed_at
        calls.append((active_writer, active_seeded, run_id))
        return updated

    monkeypatch.setattr(runner, "apply_u1_state_change", apply)
    lifecycle = runner.CanonicalFixtureLifecycle(paths, Runtime())
    lifecycle.seeded = seeded
    lifecycle.seeded_snapshot = copy.deepcopy(seeded)
    runner._atomic_write(
        durable / "canonical-fixture.json", runner._redact_fixture_receipt(seeded)
    )
    seed_bytes = (durable / "canonical-fixture.json").read_bytes()

    observation = lifecycle.apply_post_warm_state_change()

    assert calls == [(writer, seeded, lifecycle.fixture_run_id)]
    assert seeded == original
    assert lifecycle.seeded is updated
    assert observation["seeded_snapshot_unchanged"] is True
    assert (
        observation["mutation_receipt_sha256"]
        == runner.hashlib.sha256(
            runner.u0._canonical_bytes(
                runner._redact_fixture_receipt(
                    updated["negative_setups"]["state_change"]
                )
            )
        ).hexdigest()
    )
    assert (durable / "canonical-fixture.json").read_bytes() == seed_bytes
    mutation_artifact = (
        durable / "canonical-fixture-post-warm-mutation.json"
    ).read_text()
    assert "private-after" not in mutation_artifact
    assert "private-change-evidence" not in mutation_artifact


def _authority_measurement() -> dict[str, object]:
    scenario = runner.cache_governance.scenario_for_case("U1-AUTHORITY-ESCALATION")
    steps: list[dict[str, object]] = []
    for index, expected in enumerate(scenario.steps):
        steps.append(
            {
                "step_id": expected.step_id,
                "boundary": expected.boundary,
                "operation_sha256": runner.hashlib.sha256(
                    f"operation:{index}".encode()
                ).hexdigest(),
                "session_sha256": None,
                "task_sha256": None,
                "requested_route": expected.requested_route,
                "attempted_routes": list(expected.attempted_routes),
                "terminal_route": expected.terminal_route,
                "route_result": expected.route_result,
                "fallback_reason": expected.fallback_reason,
                "prepare_status": expected.prepare_status,
                "reason_code": expected.reason_code,
                "access_status": expected.access_status,
                "execution_action": expected.execution_action,
                "provider_execution": expected.provider_execution,
                "mcp_calls": expected.mcp_calls,
                "provider_calls": expected.provider_calls,
                "automatic_retries": 0,
                "l0_calls": expected.l0_calls,
                "exact_calls": expected.exact_calls,
                "query_embedding_calls": 0,
                "vector_calls": 0,
                "fts_calls": 0,
                "reranker_calls": 0,
                "receipt_sha256": runner.hashlib.sha256(
                    f"receipt:{index}".encode()
                ).hexdigest(),
            }
        )
    digest = lambda value: runner.hashlib.sha256(value.encode()).hexdigest()
    return {
        "schema": runner.cache_governance.MEASUREMENT_SCHEMA,
        "case_id": scenario.case_id,
        "execution_class": scenario.execution_class,
        "steps": steps,
        "mcp_calls": 0,
        "provider_calls": 0,
        "automatic_retries": 0,
        "vllm_lifecycle_attempts": 0,
        "invariants": {
            "requested_authority_sha256": digest("ACTION_SAFE"),
            "effective_authority_sha256": digest("INFORMATIONAL"),
            "policy_receipt_sha256": digest("policy"),
            "startup_rejected": True,
            "authority_widened": False,
        },
        "cleanup": None,
    }


def test_cache_governance_finalizer_reduces_only_after_real_cleanup_receipt(
    tmp_path: Path,
) -> None:
    durable = tmp_path / "durable"
    durable.mkdir()
    paths = runner.RunPaths(
        "dg13u-u1-finalizer", durable, tmp_path / "temporary", tmp_path / "uds"
    )
    finalizer = runner.CacheGovernanceScenarioFinalizer(
        paths,
        "U1-AUTHORITY-ESCALATION",
        _authority_measurement(),
    )
    failed_cleanup = {
        "schema": "milai.dg13u.u1-cleanup-receipt.v1",
        "run_id": paths.run_id,
        "status": "FAIL",
        "existing_vllm_preserved": True,
        "external_lifecycle_mutations": 0,
        "items": [],
    }
    with pytest.raises(runner.RunError, match="scenario cleanup is incomplete"):
        finalizer.finalize(failed_cleanup)
    assert not (durable / "cache-governance-evidence.json").exists()

    cleanup = {
        **failed_cleanup,
        "status": "PASS",
        "items": [
            {
                "kind": "temporary_root",
                "identity": "temporary/run",
                "ownership": "RUN_OWNED",
                "state": "removed",
            },
            {
                "kind": "external_vllm",
                "identity": "127.0.0.1:7860",
                "ownership": "PRESERVED_EXTERNAL",
                "state": "preserved_external",
                "attempts": 0,
            },
        ],
    }
    runner._atomic_write(durable / "cleanup-receipt.json", cleanup)
    evidence = finalizer.finalize(cleanup)

    assert evidence["status"] == "PASS"
    assert evidence["cleanup"] == {
        "status": "PASS",
        "attempts": 1,
        "run_owned_resources_absent": True,
        "receipt_sha256": runner.hashlib.sha256(
            (durable / "cleanup-receipt.json").read_bytes()
        ).hexdigest(),
    }
    artifact = json.loads((durable / "cache-governance-evidence.json").read_text())
    assert artifact == evidence
    with pytest.raises(runner.RunError, match="not repeatable"):
        finalizer.finalize(cleanup)


@pytest.mark.parametrize("case_id", sorted(_CACHE_GOVERNANCE_CASES))
def test_cache_governance_smoke_dispatches_only_to_frozen_scenario_path(
    case_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = object.__new__(runner.OpenWorkerU1Lifecycle)
    lifecycle.case = runner.CASES[case_id]
    sentinel = {"case_id": case_id, "measured": True}
    calls: list[str] = []

    def smoke():  # type: ignore[no-untyped-def]
        calls.append(case_id)
        return sentinel

    monkeypatch.setattr(lifecycle, "_smoke_cache_governance_scenario", smoke)

    assert lifecycle.smoke() is sentinel
    assert calls == [case_id]


def test_run_case_finalizes_cache_scenario_only_after_registry_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary, uds = _configure_roots(tmp_path, monkeypatch)
    run_id = "dg13u-u1-cache-final-order"
    case = runner.CASES["U1-CACHE-FALLBACK"]
    composition = runner.LocalComposition(tmp_path / "runtime.env")
    measured = {
        "observed_provider_calls": 2,
        "observed_mcp_calls": 2,
        "native_request_id_sha256": "a" * 64,
        "provider_terminal_status": "SUCCEEDED",
        "worker_exit_code": 0,
        "worker_output_sha256": "b" * 64,
        "worker_output_bytes": 2,
        "automatic_retries": 0,
        "mcp_automatic_retries": 0,
        "unaccounted_mcp_calls": 0,
        "unaccounted_provider_calls": 0,
        "unaccounted_calls": 0,
        "memory_route": "CACHE",
        "context_tokens": 2,
        "latencies_ms": {
            "openworker": 1.0,
            "adapter": 1.0,
            "mcp": 1.0,
            "runtime": 1.0,
            "compile": 1.0,
            "provider": 1.0,
        },
        "model_visible_memory_tool_events": 0,
        "raw_prompt_or_answer_persisted": False,
        "safety_failures": {name: 0 for name in case.safety_counters},
    }
    composition.start = lambda _paths, _case, _resources: runner.CompositionResult(  # type: ignore[method-assign]
        runner.TerminalStatus.PASS, "STARTED", {}
    )
    composition.readiness = lambda _paths, _case: runner.CompositionResult(  # type: ignore[method-assign]
        runner.TerminalStatus.PASS, "READY", {}
    )
    composition.smoke = lambda _paths, _case: runner.CompositionResult(  # type: ignore[method-assign]
        runner.TerminalStatus.PASS, "SMOKE", measured
    )
    composition.reconciliation = lambda _paths, _case: runner.CompositionResult(  # type: ignore[method-assign]
        runner.TerminalStatus.PASS, "RECONCILED", measured
    )
    composition.write_final_evidence_artifacts = lambda *_args: None  # type: ignore[method-assign]
    calls: list[str] = []

    def finalize(paths, active_case, cleanup):  # type: ignore[no-untyped-def]
        assert active_case is case
        assert cleanup["status"] == "PASS"
        assert (paths.durable / "cleanup-receipt.json").is_file()
        assert not (temporary / run_id).exists()
        assert not (uds / runner._short_run_id(run_id)).exists()
        calls.append("after-cleanup")
        return {**measured, "cache_governance_evidence_sha256": "c" * 64}

    composition.finalize_after_cleanup = finalize  # type: ignore[method-assign]

    report = runner.run_case(run_id, case.case_id, composition=composition)

    assert calls == ["after-cleanup"]
    assert report["status"] == "PASS"
    assert report["stages"][-1]["stage"] == "scenario_finalization"
    assert report["stages"][-1]["status"] == "PASS"
    assert (
        json.loads((runs / run_id / "cleanup-receipt.json").read_text())["status"]
        == "PASS"
    )


def test_cache_scenario_cleanup_finalizer_failure_cannot_leave_case_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runs, _temporary, _uds = _configure_roots(tmp_path, monkeypatch)
    case = runner.CASES["U1-AUTHORITY-ESCALATION"]
    composition = runner.LocalComposition(tmp_path / "runtime.env")
    measured = {
        "observed_provider_calls": 0,
        "observed_mcp_calls": 0,
        "unaccounted_calls": 0,
        "context_tokens": 0,
    }
    composition.start = lambda *_args: runner.CompositionResult(  # type: ignore[method-assign]
        runner.TerminalStatus.PASS, "STARTED", {}
    )
    composition.readiness = lambda *_args: runner.CompositionResult(  # type: ignore[method-assign]
        runner.TerminalStatus.PASS, "READY", {}
    )
    composition.smoke = lambda *_args: runner.CompositionResult(  # type: ignore[method-assign]
        runner.TerminalStatus.PASS, "SMOKE", measured
    )
    composition.reconciliation = lambda *_args: runner.CompositionResult(  # type: ignore[method-assign]
        runner.TerminalStatus.PASS, "RECONCILED", measured
    )
    composition.write_final_evidence_artifacts = lambda *_args: None  # type: ignore[method-assign]
    composition.finalize_after_cleanup = (  # type: ignore[method-assign]
        lambda *_args: (_ for _ in ()).throw(runner.RunError("synthetic finalizer"))
    )

    report = runner.run_case(
        "dg13u-u1-finalizer-negative",
        case.case_id,
        composition=composition,
    )

    assert report["status"] == "FAIL"
    assert report["stages"][-1]["stage"] == "scenario_finalization"
    assert report["stages"][-1]["reason_code"] == (
        "CACHE_GOVERNANCE_FINALIZATION_FAILED"
    )


def _scenario_turn_lifecycle(tmp_path: Path) -> runner.OpenWorkerU1Lifecycle:
    lifecycle = object.__new__(runner.OpenWorkerU1Lifecycle)
    lifecycle.case = runner.CASES["U1-WRONG-SCOPE"]
    lifecycle.container_name = "milai-dg13u-u1-worker-synthetic"
    durable = tmp_path / "durable"
    durable.mkdir()
    lifecycle.paths = runner.RunPaths(
        "dg13u-u1-scenario-turn", durable, tmp_path / "temporary", tmp_path / "uds"
    )
    lifecycle.provider_ledger = durable / "provider-ledger.jsonl"
    lifecycle.host_trace = durable / "host-access-trace.jsonl"
    lifecycle.provider_ledger.write_text("", encoding="utf-8")
    lifecycle.host_trace.write_text("", encoding="utf-8")
    lifecycle.ingress_token = "private-ingress-token"
    lifecycle.runtime = type("Runtime", (), {"reader_token": "private-reader-token"})()
    return lifecycle


def _state_key_ref_sha256(predicate: str, claim_type: str) -> str:
    return runner.hashlib.sha256(
        json.dumps(
            {
                "version": "state-key-ref-v1",
                "scope": {"project_ids": ["orchid-release"]},
                "subject": "orchid-release",
                "predicate": predicate,
                "claim_type": claim_type,
                "claim_id": None,
                "relevant_open_issue_ids": [],
                "canonical_position_seen": None,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _write_scenario_turn_rows(
    lifecycle: runner.OpenWorkerU1Lifecycle, *, duplicate_reservation: bool = False
) -> bytes:
    prompt = runner._cache_governance_prompt(lifecycle.case)
    question_sha256 = runner.hashlib.sha256(prompt.encode()).hexdigest()
    session_id = "session-A"
    session_sha256 = runner.hashlib.sha256(session_id.encode()).hexdigest()
    operation_sha256 = runner.hashlib.sha256(b"operation-A").hexdigest()
    task_sha256 = runner.hashlib.sha256(b"task-A").hexdigest()
    logical_id = "logical-A"
    native_id = "native-A"
    access = {
        "canonical_position": 9,
        "context_digest": "d" * 64,
        "execution_action": "CONTINUE",
        "provider_execution": "ALLOWED",
        "reason_code": None,
        "status": "CONTEXT_READY_CURRENT",
        "terminal_stage": "EXACT",
        "trace_id": "trace-A",
    }
    recall = {
        "need_signature_id": "need:" + "1" * 64,
        "requested_route": "L0",
        "attempted_routes": ["L0"],
        "terminal_route": "L0",
        "result": "HIT",
        "fallback_reason": None,
        "l0_calls": 1,
        "exact_calls": 0,
        "query_embedding_calls": 0,
        "vector_calls": 0,
        "fts_calls": 0,
        "reranker_calls": 0,
    }
    trace = [
        {
            "event": "HOST_NATIVE_REQUEST_OBSERVED",
            "tool_count": 1,
            "task_session_sha256": session_sha256,
            "task_operation_sha256": operation_sha256,
            "question_sha256": question_sha256,
        },
        {
            "event": "HOST_NATIVE_TASK_BOUND",
            "task_session_sha256": session_sha256,
            "task_operation_sha256": operation_sha256,
            "task_id_sha256": task_sha256,
            "task_relation": "TASK_START",
            "scope_sha256": runner.hashlib.sha256(
                runner.u0._canonical_bytes({"project_ids": ["orchid-release"]})
            ).hexdigest(),
        },
        {
            "event": "HOST_MEMORY_NEED_RESOLVED",
            "question_sha256": question_sha256,
            "need_signature_id": "need:" + "1" * 64,
            "intent_class": "CURRENT_STATE",
            "temporal_need": "CURRENT",
            "evidence_need": "SUPPORT_POINTERS",
            "resolver_route": "L0",
            "requested_route": "L0",
            "state_key_ref_present": True,
            "state_key_ref_sha256": _state_key_ref_sha256(
                "release.target", "PROJECT_STATE"
            ),
            "state_key_subject_sha256": runner.hashlib.sha256(
                b"orchid-release"
            ).hexdigest(),
            "state_key_predicate_sha256": runner.hashlib.sha256(
                b"release.target"
            ).hexdigest(),
            "state_key_claim_type_sha256": runner.hashlib.sha256(
                b"PROJECT_STATE"
            ).hexdigest(),
            "resolver_embedding_calls": 0,
            "resolver_retrieval_calls": 0,
            "resolver_model_calls": 0,
        },
        {
            "event": "HOST_MCP_PREPARE_ATTEMPT",
            "logical_mcp_calls": 1,
            "question_sha256": question_sha256,
        },
        {
            "event": "HOST_MCP_PREPARE_CONTEXT",
            "question_sha256": question_sha256,
            "access_outcome": access,
            "recall_execution_trace": recall,
            "prepare_status": "READY",
            "compiled_memory_tokens": 41,
            "current_state_status": "HIT",
            "current_state_claim_count": 1,
            "trace_id": "trace-A",
        },
        {
            "event": "PROVIDER_ANSWER",
            "logical_request_id": logical_id,
            "native_request_id": native_id,
            "trace_id": "trace-A",
            "mcp_calls": 1,
            "context_in_prompt": True,
            "ordinary_tool_count": 0,
        },
    ]
    ledger = [
        {"event": "RESERVED", "logical_request_id": logical_id},
        {
            "event": "PROVIDER_TERMINAL",
            "logical_request_id": logical_id,
            "native_request_id": native_id,
            "status": "SUCCEEDED",
        },
    ]
    if duplicate_reservation:
        ledger.insert(1, {"event": "RESERVED", "logical_request_id": "extra"})
    lifecycle.host_trace.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in trace),
        encoding="utf-8",
    )
    lifecycle.provider_ledger.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in ledger),
        encoding="utf-8",
    )
    return json.dumps({"type": "text", "sessionID": session_id}).encode() + b"\n"


def _write_revoke_scenario_turn_rows(
    lifecycle: runner.OpenWorkerU1Lifecycle,
) -> None:
    prompt = runner._cache_governance_prompt(lifecycle.case)
    question_sha256 = runner.hashlib.sha256(prompt.encode()).hexdigest()
    session_sha256 = runner.hashlib.sha256(b"session-A").hexdigest()
    operation_sha256 = runner.hashlib.sha256(b"operation-A").hexdigest()
    trace = [
        {
            "event": "HOST_NATIVE_REQUEST_OBSERVED",
            "tool_count": 1,
            "task_session_sha256": session_sha256,
            "task_operation_sha256": operation_sha256,
            "question_sha256": question_sha256,
        },
        {
            "event": "HOST_NATIVE_TASK_BOUND",
            "task_session_sha256": session_sha256,
            "task_operation_sha256": operation_sha256,
            "task_id_sha256": runner.hashlib.sha256(b"task-A").hexdigest(),
            "task_relation": "TASK_START",
        },
        {
            "event": "HOST_MCP_PREPARE_ATTEMPT",
            "logical_mcp_calls": 1,
            "question_sha256": question_sha256,
        },
        {
            "event": "HOST_MCP_PREPARE_CONTEXT",
            "question_sha256": question_sha256,
            "prepare_status": "ABSTAIN",
            "prepare_reason": "CANONICAL_GATE_REJECTED",
            "memory_status": "UNAVAILABLE",
            "compiled_memory_bytes": None,
            "compiled_memory_tokens": None,
            "current_state_status": "BLOCKED",
            "current_state_claim_count": 0,
            "access_outcome": {
                "canonical_position": 11,
                "context_digest": None,
                "execution_action": "ABSTAIN",
                "provider_execution": "PROHIBITED",
                "reason_code": "CANONICAL_GATE_REJECTED",
                "status": "GOVERNANCE_BLOCKED",
                "terminal_stage": "GATE",
                "trace_id": "trace-A",
            },
            "recall_execution_trace": {
                "need_signature_id": "need:" + "2" * 64,
                "requested_route": "L0",
                "attempted_routes": ["L0"],
                "terminal_route": "L0",
                "result": "ABSTAINED",
                "fallback_reason": None,
                "l0_calls": 1,
                "exact_calls": 0,
                "query_embedding_calls": 0,
                "vector_calls": 0,
                "fts_calls": 0,
                "reranker_calls": 0,
            },
        },
    ]
    trace.insert(
        2,
        {
            "event": "HOST_MEMORY_NEED_RESOLVED",
            "question_sha256": question_sha256,
            "need_signature_id": "need:" + "2" * 64,
            "intent_class": "CURRENT_STATE",
            "temporal_need": "CURRENT",
            "evidence_need": "SUPPORT_POINTERS",
            "resolver_route": "L0",
            "requested_route": "L0",
            "state_key_ref_present": True,
            "state_key_ref_sha256": _state_key_ref_sha256(
                "release.database", "PROJECT_CONFIG"
            ),
            "state_key_subject_sha256": runner.hashlib.sha256(
                b"orchid-release"
            ).hexdigest(),
            "state_key_predicate_sha256": runner.hashlib.sha256(
                b"release.database"
            ).hexdigest(),
            "state_key_claim_type_sha256": runner.hashlib.sha256(
                b"PROJECT_CONFIG"
            ).hexdigest(),
            "resolver_embedding_calls": 0,
            "resolver_retrieval_calls": 0,
            "resolver_model_calls": 0,
        },
    )
    lifecycle.host_trace.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in trace),
        encoding="utf-8",
    )


def _write_open_issue_scenario_turn_rows(
    lifecycle: runner.OpenWorkerU1Lifecycle,
    *,
    open_issue_count: int = 0,
) -> None:
    _write_revoke_scenario_turn_rows(lifecycle)
    trace = [
        json.loads(line)
        for line in lifecycle.host_trace.read_text(encoding="utf-8").splitlines()
    ]
    need = next(row for row in trace if row["event"] == "HOST_MEMORY_NEED_RESOLVED")
    need["state_key_ref_sha256"] = _state_key_ref_sha256(
        "release.decision", "PROJECT_DECISION"
    )
    need["state_key_predicate_sha256"] = runner.hashlib.sha256(
        b"release.decision"
    ).hexdigest()
    need["state_key_claim_type_sha256"] = runner.hashlib.sha256(
        b"PROJECT_DECISION"
    ).hexdigest()
    prepare = next(row for row in trace if row["event"] == "HOST_MCP_PREPARE_CONTEXT")
    prepare["current_state_open_issue_count"] = open_issue_count
    lifecycle.host_trace.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in trace),
        encoding="utf-8",
    )


def _open_issue_seeded_fixture(
    *,
    head_claim_version_id: str = "00000000-0000-4000-8000-000000000102",
    captured_conflicting_evidence_id: str = "00000000-0000-4000-8000-000000000104",
) -> dict[str, object]:
    return {
        "families": [
            {
                "project": "orchid-release",
                "state_key": "release.decision",
                "claim_type": "PROJECT_DECISION",
                "claim_id": "00000000-0000-4000-8000-000000000101",
                "claim_version_id": "00000000-0000-4000-8000-000000000102",
                "evidence_id": "00000000-0000-4000-8000-000000000103",
                "payload_sha256": runner.hashlib.sha256(
                    runner.u0._canonical_bytes(
                        {
                            "state_key": "release.decision",
                            "value": "proceed-after-governance-pass",
                        }
                    )
                ).hexdigest(),
            }
        ],
        "negative_setups": {
            "open_issue": {
                "state_key": "release.decision",
                "claim_id": "00000000-0000-4000-8000-000000000101",
                "head_claim_version_id": head_claim_version_id,
                "conflicting_evidence_id": "00000000-0000-4000-8000-000000000104",
                "open_issue_id": "00000000-0000-4000-8000-000000000105",
            }
        },
        "mutations": [
            {
                "kind": "EVIDENCE_CAPTURE",
                "evidence_id": captured_conflicting_evidence_id,
            }
        ],
    }


def _open_issue_runtime_payloads(
    seeded: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    family = seeded["families"][0]
    issue = seeded["negative_setups"]["open_issue"]
    assert isinstance(family, dict)
    assert isinstance(issue, dict)
    runtime_issue = {
        "issue_id": issue["open_issue_id"],
        "target_claim_id": issue["claim_id"],
        "issue_type": "CONFLICT",
        "status": "OPEN",
        "revision": 1,
        "scope_predicate": {"project_ids": ["orchid-release"]},
        "discharge_rule": {
            "rule_version": "1",
            "required_evidence_kinds": ["RUNTIME_OBSERVATION"],
            "required_scope": {"project_ids": ["orchid-release"]},
            "required_authority": "INFORMATIONAL",
            "minimum_independent_sources": 1,
            "must_address_branches": [
                "SUPPORT_BRANCH",
                "CONTRADICT_BRANCH",
            ],
            "review_required": True,
        },
        "required_authority": "INFORMATIONAL",
        "resolved_by_decision_id": None,
        "resolved_at": None,
        "branches": [
            {
                "relation_type": "CONTRADICT_BRANCH",
                "evidence_id": issue["conflicting_evidence_id"],
            },
            {
                "relation_type": "SUPPORT_BRANCH",
                "evidence_id": family["evidence_id"],
            },
        ],
        "transitions": [
            {
                "event_type": "ISSUE_CREATED",
                "from_status": None,
                "to_status": "OPEN",
                "from_revision": 0,
                "to_revision": 1,
            }
        ],
        "request_id": "request-private",
    }
    runtime_claim = {
        "claim_id": issue["claim_id"],
        "claim_version_id": issue["head_claim_version_id"],
        "subject_id": family["project"],
        "predicate": family["state_key"],
        "claim_type": family["claim_type"],
        "payload": {
            "state_key": "release.decision",
            "value": "proceed-after-governance-pass",
        },
        "scope_predicate": {"project_ids": ["orchid-release"]},
        "has_live_open_issue": True,
        "effective_status": "CONFLICTED",
        "lifecycle": "ACTIVE",
        "authority": "INFORMATIONAL",
        "request_id": "request-private",
    }
    return runtime_issue, runtime_claim


def _install_open_issue_runtime_probe(
    lifecycle: runner.OpenWorkerU1Lifecycle,
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, object],
    *,
    issue_mutation=None,  # type: ignore[no-untyped-def]
    claim_mutation=None,  # type: ignore[no-untyped-def]
) -> None:
    runtime_issue, runtime_claim = _open_issue_runtime_payloads(seeded)
    if issue_mutation is not None:
        issue_mutation(runtime_issue)
    if claim_mutation is not None:
        claim_mutation(runtime_claim)
    monkeypatch.setattr(
        lifecycle,
        "_read_runtime_open_issue",
        lambda _issue_id: runtime_issue,
    )
    monkeypatch.setattr(
        lifecycle,
        "_read_runtime_claim",
        lambda _claim_id: runtime_claim,
    )


class _CanonicalProbeResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self.raw = json.dumps(payload, separators=(",", ":")).encode()
        self.read_bounds: list[int] = []

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *_exc):  # type: ignore[no-untyped-def]
        return None

    def read(self, bound: int) -> bytes:
        self.read_bounds.append(bound)
        return self.raw[:bound]


class _CanonicalProbeOpener:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = iter(outcomes)
        self.calls: list[tuple[object, float]] = []

    def open(self, request, *, timeout: float):  # type: ignore[no-untyped-def]
        self.calls.append((request, timeout))
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _execute_blocked_scenario_turn(
    lifecycle: runner.OpenWorkerU1Lifecycle,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exit_code: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
):  # type: ignore[no-untyped-def]
    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        output = (
            b'{"id":"session-A","directory":"/openworker/runtime"}'
            if "curl" in arguments
            else stdout
        )
        return subprocess.CompletedProcess(
            arguments,
            0 if "curl" in arguments else exit_code,
            stdout=output,
            stderr=b"" if "curl" in arguments else stderr,
        )

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(
        lifecycle,
        "_write_smoke_command_diagnostic",
        lambda *_args, **_kwargs: runner.SmokeCommandTruth(
            (
                runner.TerminalStatus.PASS
                if exit_code == 0
                else runner.TerminalStatus.FAIL
            ),
            (
                "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR"
                if exit_code == 0
                else "OPENCODE_EXIT_NONZERO"
            ),
            exit_code,
            0,
        ),
    )
    expected = runner.cache_governance.scenario_for_case(lifecycle.case.case_id).steps[
        0
    ]
    return lifecycle._execute_cache_governance_turn(
        expected,
        prompt=runner._cache_governance_prompt(lifecycle.case),
        known_sessions={},
        previous_ledger=[],
        previous_trace=[],
    )


def test_cache_governance_turn_maps_measured_trace_without_double_counting_mcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    stdout = _write_scenario_turn_rows(lifecycle)

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        output = (
            b'{"id":"session-A","directory":"/openworker/runtime"}'
            if "curl" in arguments
            else stdout
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(
        runner,
        "_command_bytes",
        command,
    )
    monkeypatch.setattr(
        lifecycle,
        "_write_smoke_command_diagnostic",
        lambda *_args, **_kwargs: runner.SmokeCommandTruth(
            runner.TerminalStatus.PASS,
            "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR",
            0,
            0,
        ),
    )
    expected = runner.cache_governance.scenario_for_case(lifecycle.case.case_id).steps[
        0
    ]

    step, detail, sessions, ledger, trace = lifecycle._execute_cache_governance_turn(
        expected,
        prompt=runner._cache_governance_prompt(lifecycle.case),
        known_sessions={},
        previous_ledger=[],
        previous_trace=[],
    )

    assert step["mcp_calls"] == 1
    assert step["provider_calls"] == 1
    assert step["requested_route"] == "L0"
    assert step["attempted_routes"] == ["L0"]
    assert step["terminal_route"] == "L0"
    assert step["route_result"] == "HIT"
    assert len(detail["attempts"]) == 1
    assert len(detail["prepare"]["recall_execution_trace"]) > 0
    assert set(sessions) == {"A"}
    assert len(ledger) == 2
    assert len(trace) == 6


def test_cache_governance_turn_accepts_empty_cli_events_only_with_exact_provider_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    _write_scenario_turn_rows(lifecycle)

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        output = (
            b'{"id":"session-A","directory":"/openworker/runtime"}'
            if "curl" in arguments
            else b""
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(
        lifecycle,
        "_write_smoke_command_diagnostic",
        lambda *_args, **_kwargs: runner.SmokeCommandTruth(
            runner.TerminalStatus.PASS,
            "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR",
            0,
            0,
        ),
    )
    expected = runner.cache_governance.scenario_for_case(lifecycle.case.case_id).steps[
        0
    ]

    step, detail, sessions, ledger, trace = lifecycle._execute_cache_governance_turn(
        expected,
        prompt=runner._cache_governance_prompt(lifecycle.case),
        known_sessions={},
        previous_ledger=[],
        previous_trace=[],
    )

    assert detail["event_evidence"]["event_count"] == 0
    assert sessions == {"A": "session-A"}
    assert step["mcp_calls"] == 1
    assert step["provider_calls"] == 1
    assert len(ledger) == 2
    assert len(trace) == 6


def test_cache_governance_turn_rejects_empty_cli_events_without_provider_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        output = (
            b'{"id":"session-A","directory":"/openworker/runtime"}'
            if "curl" in arguments
            else b""
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(
        lifecycle,
        "_write_smoke_command_diagnostic",
        lambda *_args, **_kwargs: runner.SmokeCommandTruth(
            runner.TerminalStatus.PASS,
            "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR",
            0,
            0,
        ),
    )
    expected = runner.cache_governance.scenario_for_case(lifecycle.case.case_id).steps[
        0
    ]

    with pytest.raises(runner.RunError, match="incremental call accounting"):
        lifecycle._execute_cache_governance_turn(
            expected,
            prompt=runner._cache_governance_prompt(lifecycle.case),
            known_sessions={},
            previous_ledger=[],
            previous_trace=[],
        )


def test_cache_governance_turn_rejects_duplicate_provider_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    stdout = _write_scenario_turn_rows(lifecycle, duplicate_reservation=True)

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        output = (
            b'{"id":"session-A","directory":"/openworker/runtime"}'
            if "curl" in arguments
            else stdout
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(
        runner,
        "_command_bytes",
        command,
    )
    monkeypatch.setattr(
        lifecycle,
        "_write_smoke_command_diagnostic",
        lambda *_args, **_kwargs: runner.SmokeCommandTruth(
            runner.TerminalStatus.PASS,
            "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR",
            0,
            0,
        ),
    )
    expected = runner.cache_governance.scenario_for_case(lifecycle.case.case_id).steps[
        0
    ]

    with pytest.raises(runner.RunError, match="incremental call accounting"):
        lifecycle._execute_cache_governance_turn(
            expected,
            prompt=runner._cache_governance_prompt(lifecycle.case),
            known_sessions={},
            previous_ledger=[],
            previous_trace=[],
        )


def test_revoke_turn_accepts_only_empty_pre_provider_terminal_with_exact_host_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-REVOKE-REENTRY"]
    _write_revoke_scenario_turn_rows(lifecycle)

    step, detail, sessions, ledger, trace = _execute_blocked_scenario_turn(
        lifecycle, monkeypatch
    )

    assert step["mcp_calls"] == 1
    assert step["provider_calls"] == 0
    assert step["route_result"] == "ABSTAINED"
    assert step["access_status"] == "GOVERNANCE_BLOCKED"
    assert step["provider_execution"] == "PROHIBITED"
    assert detail["event_evidence"]["event_count"] == 0
    assert sessions == {"A": "session-A"}
    assert ledger == []
    assert len(trace) == 5
    smoke = lifecycle._cache_governance_smoke_evidence(
        prompt=runner._cache_governance_prompt(lifecycle.case),
        details=[detail],
        trace_rows=trace,
        steps=[step],
    )
    assert smoke["memory_route"] == "L0"
    assert smoke["observed_mcp_calls"] == 1
    assert smoke["observed_provider_calls"] == 0
    lifecycle.fixture = type(
        "Fixture",
        (),
        {
            "seeded": {
                "families": [
                    {
                        "state_key": "release.database",
                        "claim_id": "claim-current",
                        "evidence_id": "evidence-current",
                    }
                ],
                "negative_setups": {
                    "revoke": {
                        "state_key": "release.database",
                        "claim_id": "claim-current",
                        "evidence_id": "evidence-current",
                        "canonical_block_status": "APPLIED",
                    }
                },
            }
        },
    )()
    invariants = lifecycle._cache_governance_invariants(
        details=[detail], mutation=None, adjacent=None
    )
    assert invariants["canonical_block_applied"] is True
    assert invariants["revoked_claim_accepted"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("provider_reservation", "incremental call accounting"),
        ("missing_mcp_attempt", "incremental call accounting"),
        ("missing_need_resolution", "incremental call accounting"),
        ("wrong_reason", "pre-provider terminal drifted"),
        ("wrong_state_key", "prompt binding failed"),
        ("wrong_state_ref", "prompt binding failed"),
        ("wrong_prompt", "prompt binding failed"),
    ],
)
def test_revoke_turn_rejects_call_or_terminal_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-REVOKE-REENTRY"]
    _write_revoke_scenario_turn_rows(lifecycle)
    trace = [
        json.loads(line)
        for line in lifecycle.host_trace.read_text(encoding="utf-8").splitlines()
    ]
    if mutation == "provider_reservation":
        lifecycle.provider_ledger.write_text(
            json.dumps({"event": "RESERVED", "logical_request_id": "leak"}) + "\n",
            encoding="utf-8",
        )
    elif mutation == "missing_mcp_attempt":
        trace = [row for row in trace if row["event"] != "HOST_MCP_PREPARE_ATTEMPT"]
    elif mutation == "missing_need_resolution":
        trace = [row for row in trace if row["event"] != "HOST_MEMORY_NEED_RESOLVED"]
    elif mutation == "wrong_reason":
        prepare = next(
            row for row in trace if row["event"] == "HOST_MCP_PREPARE_CONTEXT"
        )
        prepare["prepare_reason"] = "UNRELATED_GATE"
        prepare["access_outcome"]["reason_code"] = "UNRELATED_GATE"
    elif mutation == "wrong_state_key":
        need = next(row for row in trace if row["event"] == "HOST_MEMORY_NEED_RESOLVED")
        need["state_key_predicate_sha256"] = runner.hashlib.sha256(
            b"release.target"
        ).hexdigest()
    elif mutation == "wrong_state_ref":
        need = next(row for row in trace if row["event"] == "HOST_MEMORY_NEED_RESOLVED")
        need["state_key_ref_sha256"] = "f" * 64
    else:
        trace[-1]["question_sha256"] = "f" * 64
    lifecycle.host_trace.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in trace),
        encoding="utf-8",
    )

    with pytest.raises(runner.RunError, match=message):
        _execute_blocked_scenario_turn(lifecycle, monkeypatch)


@pytest.mark.parametrize(
    ("exit_code", "stdout", "stderr", "message"),
    [
        (1, b"", b"", "OpenCode terminal failed"),
        (0, b"not-json", b"", "session evidence is invalid"),
        (0, b"", b"unexpected", "session evidence is invalid"),
    ],
)
def test_revoke_turn_rejects_invalid_command_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    stdout: bytes,
    stderr: bytes,
    message: str,
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-REVOKE-REENTRY"]
    _write_revoke_scenario_turn_rows(lifecycle)

    with pytest.raises(runner.RunError, match=message):
        _execute_blocked_scenario_turn(
            lifecycle,
            monkeypatch,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )


def test_revoke_invariant_rejects_fixture_target_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-REVOKE-REENTRY"]
    _write_revoke_scenario_turn_rows(lifecycle)
    _step, detail, *_rest = _execute_blocked_scenario_turn(lifecycle, monkeypatch)
    lifecycle.fixture = type(
        "Fixture",
        (),
        {
            "seeded": {
                "families": [
                    {
                        "state_key": "release.database",
                        "claim_id": "claim-current",
                        "evidence_id": "evidence-current",
                    }
                ],
                "negative_setups": {
                    "revoke": {
                        "state_key": "release.database",
                        "claim_id": "claim-current",
                        "evidence_id": "evidence-other",
                        "canonical_block_status": "APPLIED",
                    }
                },
            }
        },
    )()

    with pytest.raises(runner.RunError, match="revocation fixture binding"):
        lifecycle._cache_governance_invariants(
            details=[detail], mutation=None, adjacent=None
        )


def test_cache_governance_failure_preserves_measured_trace_call_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-REVOKE-REENTRY"]
    lifecycle.fixture = object()
    lifecycle.smoke_evidence = None
    _write_revoke_scenario_turn_rows(lifecycle)
    rows = [
        json.loads(line)
        for line in lifecycle.host_trace.read_text(encoding="utf-8").splitlines()
    ]
    prepare = next(row for row in rows if row["event"] == "HOST_MCP_PREPARE_CONTEXT")
    prepare["prepare_reason"] = "UNRELATED_GATE"
    prepare["access_outcome"]["reason_code"] = "UNRELATED_GATE"
    lifecycle.host_trace.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    trace_payload = lifecycle.host_trace.read_bytes()
    lifecycle.host_trace.write_bytes(b"")

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        if "curl" not in arguments:
            lifecycle.host_trace.write_bytes(trace_payload)
        output = (
            b'{"id":"session-A","directory":"/openworker/runtime"}'
            if "curl" in arguments
            else b""
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(
        lifecycle,
        "_write_smoke_command_diagnostic",
        lambda *_args, **_kwargs: runner.SmokeCommandTruth(
            runner.TerminalStatus.PASS,
            "OPENCODE_EXIT_ZERO_NO_TYPED_ERROR",
            0,
            0,
        ),
    )
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)

    with pytest.raises(runner.RunError, match="pre-provider terminal drifted"):
        lifecycle._smoke_cache_governance_scenario()

    assert lifecycle.smoke_evidence["observed_mcp_calls"] == 1
    assert lifecycle.smoke_evidence["observed_provider_calls"] == 0
    assert lifecycle.smoke_evidence["mcp_receipt_sha256"]
    assert lifecycle.smoke_evidence["runtime_trace_sha256"]
    assert lifecycle.smoke_evidence["memory_route"] == "L0"


def test_open_issue_turn_binds_fixture_and_runtime_blocked_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-OPEN-ISSUE"]
    _write_open_issue_scenario_turn_rows(lifecycle)
    step, detail, sessions, ledger, _trace = _execute_blocked_scenario_turn(
        lifecycle, monkeypatch
    )
    seeded = _open_issue_seeded_fixture()
    lifecycle.fixture = type("Fixture", (), {"seeded": seeded})()
    _install_open_issue_runtime_probe(lifecycle, monkeypatch, seeded)

    invariants = lifecycle._cache_governance_invariants(
        details=[detail], mutation=None, adjacent=None
    )
    measurement = {
        "schema": runner.cache_governance.MEASUREMENT_SCHEMA,
        "case_id": lifecycle.case.case_id,
        "execution_class": "OPENWORKER_E2E",
        "steps": [step],
        "mcp_calls": 1,
        "provider_calls": 0,
        "automatic_retries": 0,
        "vllm_lifecycle_attempts": 0,
        "invariants": invariants,
        "cleanup": {
            "status": "PASS",
            "attempts": 1,
            "run_owned_resources_absent": True,
            "receipt_sha256": "a" * 64,
        },
    }

    assert sessions == {"A": "session-A"}
    assert ledger == []
    assert invariants["canonical_open_issue_present"] is True
    assert invariants["runtime_issue_closure_present"] is False
    assert invariants["unsafe_branch_selected"] is False
    assert invariants["provider_called"] is False
    assert (
        runner.cache_governance.reduce_measurement(lifecycle.case.case_id, measurement)[
            "status"
        ]
        == "PASS"
    )


@pytest.mark.parametrize(
    ("head_claim_version_id", "captured_evidence_id"),
    [
        ("other-head", "00000000-0000-4000-8000-000000000104"),
        ("00000000-0000-4000-8000-000000000102", "other-evidence"),
    ],
)
def test_open_issue_invariant_rejects_fixture_join_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    head_claim_version_id: str,
    captured_evidence_id: str,
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-OPEN-ISSUE"]
    _write_open_issue_scenario_turn_rows(lifecycle)
    _step, detail, *_rest = _execute_blocked_scenario_turn(lifecycle, monkeypatch)
    lifecycle.fixture = type(
        "Fixture",
        (),
        {
            "seeded": _open_issue_seeded_fixture(
                head_claim_version_id=head_claim_version_id,
                captured_conflicting_evidence_id=captured_evidence_id,
            )
        },
    )()

    with pytest.raises(runner.RunError, match="OpenIssue fixture binding"):
        lifecycle._cache_governance_invariants(
            details=[detail], mutation=None, adjacent=None
        )


def test_open_issue_zero_host_issue_count_uses_live_runtime_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-OPEN-ISSUE"]
    _write_open_issue_scenario_turn_rows(lifecycle, open_issue_count=0)
    step, detail, *_rest = _execute_blocked_scenario_turn(lifecycle, monkeypatch)
    seeded = _open_issue_seeded_fixture()
    lifecycle.fixture = type("Fixture", (), {"seeded": seeded})()
    _install_open_issue_runtime_probe(lifecycle, monkeypatch, seeded)
    invariants = lifecycle._cache_governance_invariants(
        details=[detail], mutation=None, adjacent=None
    )

    assert invariants["canonical_open_issue_present"] is True
    assert (
        runner.cache_governance.reduce_measurement(
            lifecycle.case.case_id,
            {
                "schema": runner.cache_governance.MEASUREMENT_SCHEMA,
                "case_id": lifecycle.case.case_id,
                "execution_class": "OPENWORKER_E2E",
                "steps": [step],
                "mcp_calls": 1,
                "provider_calls": 0,
                "automatic_retries": 0,
                "vllm_lifecycle_attempts": 0,
                "invariants": invariants,
                "cleanup": {
                    "status": "PASS",
                    "attempts": 1,
                    "run_owned_resources_absent": True,
                    "receipt_sha256": "a" * 64,
                },
            },
        )["status"]
        == "PASS"
    )


@pytest.mark.parametrize(
    ("issue_mutation", "claim_mutation", "message"),
    [
        (lambda value: value.update(status="RESOLVED"), None, "identity or state"),
        (
            lambda value: value.update(target_claim_id="wrong-claim"),
            None,
            "identity or state",
        ),
        (lambda value: value["branches"].pop(), None, "branch binding"),
        (
            lambda value: value["transitions"][0].update(event_type="DISMISSED"),
            None,
            "transition binding",
        ),
        (
            lambda value: value["discharge_rule"].update(review_required=False),
            None,
            "discharge rule",
        ),
        (None, lambda value: value.update(claim_version_id="wrong-head"), "claim-head"),
        (None, lambda value: value.update(has_live_open_issue=False), "claim-head"),
    ],
)
def test_open_issue_live_probe_rejects_runtime_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    issue_mutation,
    claim_mutation,
    message: str,
) -> None:  # type: ignore[no-untyped-def]
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.case = runner.CASES["U1-OPEN-ISSUE"]
    _write_open_issue_scenario_turn_rows(lifecycle)
    _step, detail, *_rest = _execute_blocked_scenario_turn(lifecycle, monkeypatch)
    seeded = _open_issue_seeded_fixture()
    lifecycle.fixture = type("Fixture", (), {"seeded": seeded})()
    _install_open_issue_runtime_probe(
        lifecycle,
        monkeypatch,
        seeded,
        issue_mutation=issue_mutation,
        claim_mutation=claim_mutation,
    )

    with pytest.raises(runner.RunError, match=message):
        lifecycle._cache_governance_invariants(
            details=[detail], mutation=None, adjacent=None
        )


def test_open_issue_live_probe_uses_two_exact_bounded_reader_gets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.runtime = type(
        "Runtime",
        (),
        {
            "identity": runner.FreshRuntimeIdentity(
                "fresh-db",
                "http://127.0.0.1:49191",
                801,
                "8001",
                802,
                "8002",
                "head",
            ),
            "reader_token": "private-reader-token",
        },
    )()
    seeded = _open_issue_seeded_fixture()
    runtime_issue, runtime_claim = _open_issue_runtime_payloads(seeded)
    opener = _CanonicalProbeOpener(
        [
            _CanonicalProbeResponse(runtime_issue),
            _CanonicalProbeResponse(runtime_claim),
        ]
    )
    monkeypatch.setattr(
        runner.urllib.request,
        "build_opener",
        lambda *_handlers: opener,
    )
    issue = seeded["negative_setups"]["open_issue"]
    family = seeded["families"][0]
    assert isinstance(issue, dict)
    assert isinstance(family, dict)

    probe = lifecycle._probe_runtime_open_issue(
        issue=issue,
        canonical=family,
        conflicting_evidence_id=str(issue["conflicting_evidence_id"]),
    )

    requests = [request for request, _timeout in opener.calls]
    assert probe["present"] is True
    assert len(requests) == 2
    assert [request.get_method() for request in requests] == ["GET", "GET"]
    assert [request.full_url for request in requests] == [
        f"http://127.0.0.1:49191/v1/open-issues/{issue['open_issue_id']}",
        f"http://127.0.0.1:49191/v1/claims/{issue['claim_id']}",
    ]
    assert [request.get_header("Authorization") for request in requests] == [
        "Bearer private-reader-token",
        "Bearer private-reader-token",
    ]
    assert [timeout for _request, timeout in opener.calls] == [5.0, 5.0]


def test_open_issue_live_probe_transport_failure_is_one_attempt_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = _scenario_turn_lifecycle(tmp_path)
    lifecycle.runtime = type(
        "Runtime",
        (),
        {
            "identity": runner.FreshRuntimeIdentity(
                "fresh-db",
                "http://127.0.0.1:49191",
                801,
                "8001",
                802,
                "8002",
                "head",
            ),
            "reader_token": "private-reader-token",
        },
    )()
    opener = _CanonicalProbeOpener(
        [runner.urllib.error.URLError("private transport body")]
    )
    monkeypatch.setattr(
        runner.urllib.request,
        "build_opener",
        lambda *_handlers: opener,
    )

    with pytest.raises(runner.RunError, match="canonical read failed") as captured:
        lifecycle._read_runtime_open_issue("00000000-0000-4000-8000-000000000105")

    assert len(opener.calls) == 1
    failure = str(captured.value) + repr(captured.value)
    assert "private-reader-token" not in failure
    assert "private transport body" not in failure


def test_authority_scenario_executes_exact_bracketed_plan_without_early_reducer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = object.__new__(runner.OpenWorkerU1Lifecycle)
    lifecycle.case = runner.CASES["U1-AUTHORITY-ESCALATION"]
    durable = tmp_path / "durable"
    durable.mkdir()
    lifecycle.paths = runner.RunPaths(
        "dg13u-u1-authority-plan",
        durable,
        tmp_path / "temporary",
        tmp_path / "uds",
    )
    lifecycle.provider_ledger = durable / "provider-ledger.jsonl"
    lifecycle.host_trace = durable / "host-access-trace.jsonl"
    lifecycle.provider_ledger.write_text("", encoding="utf-8")
    lifecycle.host_trace.write_text("", encoding="utf-8")
    lifecycle.fixture = None
    lifecycle.smoke_evidence = None
    lifecycle.cache_governance_measurement = None
    readiness_calls: list[int] = []

    def readiness():  # type: ignore[no-untyped-def]
        readiness_calls.append(len(readiness_calls))
        return {
            "host_pid_marker_sha256": "1" * 64,
            "broker_pid_marker_sha256": "2" * 64,
            "socket_identity_sha256": "3" * 64,
            "model_identity_sha256": "4" * 64,
            "provider_calls": 0,
            "mcp_calls": 0,
        }

    probe = {
        "requested_authority_sha256": runner.hashlib.sha256(b"ACTION_SAFE").hexdigest(),
        "effective_authority_sha256": runner.hashlib.sha256(
            b"INFORMATIONAL"
        ).hexdigest(),
        "policy_receipt_sha256": "5" * 64,
        "startup_rejected": True,
        "authority_widened": False,
        "exit_code": 2,
        "output_sha256": "6" * 64,
    }
    monkeypatch.setattr(lifecycle, "_main_composition_observation", readiness)
    monkeypatch.setattr(lifecycle, "_authority_probe", lambda: probe)
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)

    evidence = lifecycle._smoke_cache_governance_scenario()

    assert readiness_calls == [0, 1]
    assert evidence["observed_mcp_calls"] == 0
    assert evidence["observed_provider_calls"] == 0
    assert lifecycle.cache_governance_measurement is not None
    assert lifecycle.cache_governance_measurement["cleanup"] is None
    assert [
        row["boundary"] for row in lifecycle.cache_governance_measurement["steps"]
    ] == [
        "MAIN_COMPOSITION_READINESS",
        "INDEPENDENT_NEGATIVE_HOST_STARTUP",
        "MAIN_COMPOSITION_READINESS",
    ]
    assert not (durable / "cache-governance-evidence.json").exists()


def test_run_owned_resource_requires_cleanup_and_absence_probes() -> None:
    registry = runner.ResourceRegistry("dg13u-u1-resource-contract")
    with pytest.raises(runner.RunError, match="requires cleanup and absence"):
        registry.register(
            runner.ResourceHandle(
                "container",
                "container/no-cleanup",
                runner.ResourceOwnership.RUN_OWNED,
            )
        )


def test_existing_run_root_is_preserved_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, _temporary, _uds = _configure_roots(tmp_path, monkeypatch)
    run_id = "dg13u-u1-existing"
    existing = runs / run_id
    existing.mkdir(parents=True)
    marker = existing / "do-not-delete"
    marker.write_text("external", encoding="utf-8")

    with pytest.raises(runner.RunError, match="already owns"):
        runner.run_case(run_id, "U1-NONE-EN")
    assert marker.read_text(encoding="utf-8") == "external"


def _interaction_smoke_lifecycle(
    tmp_path: Path,
    case_id: str,
) -> runner.OpenWorkerU1Lifecycle:
    run_id = f"dg13u-u1-{case_id.casefold()}"
    durable = tmp_path / run_id
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    for path in (durable, temporary, uds):
        path.mkdir(mode=0o700)
    paths = runner.RunPaths(run_id, durable, temporary, uds)

    class Runtime:
        identity = None
        reader_token = None

    return runner.OpenWorkerU1Lifecycle(
        paths,
        runner.CASES[case_id],
        Runtime(),
        temporary / "product",
    )


def _interaction_stdout(
    case_id: str, *, tool_name: str = "read", tools: int = 1
) -> bytes:
    session_id = "session-interaction-1"
    rows: list[dict[str, object]] = [
        {
            "type": "step_start",
            "sessionID": session_id,
            "part": {"type": "step-start"},
        },
        {
            "type": "text",
            "sessionID": session_id,
            "part": {"type": "text", "text": "private interaction response"},
        },
    ]
    if case_id == "U1-ORDINARY-SYNC-TOOL":
        rows.append(
            {
                "type": "step_finish",
                "sessionID": session_id,
                "part": {"type": "step-finish"},
            }
        )
        for index in range(tools):
            rows.append(
                {
                    "type": "tool_use",
                    "sessionID": session_id,
                    "part": {
                        "type": "tool",
                        "tool": tool_name,
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "/openworker/runtime/opencode.json"},
                            "output": "private ordinary read result",
                            "index": index,
                        },
                    },
                }
            )
    rows.append(
        {
            "type": "step_finish",
            "sessionID": session_id,
            "part": {"type": "step-finish"},
        }
    )
    return "".join(json.dumps(row) + "\n" for row in rows).encode()


def _interaction_trace_rows(case_id: str, *, rounds: int | None = None):  # type: ignore[no-untyped-def]
    plan = runner.interaction_scenarios.interaction_plan(case_id)
    round_count = plan.provider_rounds if rounds is None else rounds
    read_sha256 = runner.hashlib.sha256(b"read").hexdigest()
    call_sha256 = runner.hashlib.sha256(b"call-read-1").hexdigest()
    rows: list[dict[str, object]] = []
    for index in range(round_count):
        rows.append(
            {
                "event": "HOST_NATIVE_REQUEST_OBSERVED",
                "stream": True,
                "stream_include_usage": True,
                "tool_count": 1 if case_id == "U1-STREAM" else 2,
                "has_tool_result": case_id == "U1-ORDINARY-SYNC-TOOL" and index == 1,
            }
        )
        if case_id == "U1-STREAM":
            rows.extend(
                (
                    {
                        "event": "HOST_MCP_PREPARE_ATTEMPT",
                        "logical_mcp_calls": 1,
                    },
                    {
                        "event": "HOST_MCP_PREPARE_CONTEXT",
                        "route": "L0",
                        "prepare_status": "READY",
                        "current_state_status": "HIT",
                        "current_state_claim_count": 1,
                        "compiled_memory_tokens": 42,
                        "access_outcome": {
                            "status": "CONTEXT_READY_CURRENT",
                            "terminal_stage": "EXACT",
                        },
                        "recall_execution_trace": {"terminal_route": "L0"},
                        "trace_id": "trace-stream-1",
                        "timing": {
                            "mcp_handler_ms": 2.0,
                            "runtime_total_ms": 1.0,
                            "context_compile_ms": 0.5,
                        },
                    },
                )
            )
            policy = None
            finish_reason = "stop"
            mcp_calls = 1
            context_in_prompt = True
            trace_id = "trace-stream-1"
            ordinary_count = 0
        else:
            policy = {
                "policy": "SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
                "round": "CALL" if index == 0 else "FINAL",
                "requested_tool_choice": "AUTO",
                "effective_tool_choice": "NAMED" if index == 0 else "NONE",
                "ordinary_tool_count": 1,
                "ordinary_tool_name_sha256": read_sha256,
                "assistant_tool_call_count": 0 if index == 0 else 1,
                "tool_result_count": 0 if index == 0 else 1,
                "matching_tool_result_count": 0 if index == 0 else 1,
                "tool_call_id_sha256": None if index == 0 else call_sha256,
            }
            finish_reason = "stop"
            mcp_calls = 0
            context_in_prompt = False
            trace_id = None
            ordinary_count = 0 if index == 0 else 1
            ordinary_delivery = (
                "VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER" if index == 0 else "NATIVE_NONE"
            )
        rows.append(
            {
                "event": "PROVIDER_ANSWER",
                "provider_call": True,
                "logical_request_id": f"logical-{index + 1}",
                "native_request_id": f"native-{index + 1}",
                "trace_id": trace_id,
                "mcp_calls": mcp_calls,
                "context_in_prompt": context_in_prompt,
                "ordinary_tool_count": ordinary_count,
                "ordinary_tool_policy": policy,
                "ordinary_tool_delivery": (
                    ordinary_delivery
                    if case_id == "U1-ORDINARY-SYNC-TOOL"
                    else "NATIVE"
                ),
                "ordinary_tool_delivery_evidence": (
                    {
                        "incoming_tool_choice": "AUTO",
                        "provider_tool_choice": "ABSENT",
                        "provider_tool_count": 0,
                        "native_finish_reason": "stop",
                        "native_tool_call_count": 0,
                        "delivery_owner": "HOST_ADAPTER",
                        "client_finish_reason": "tool_calls",
                        "delivered_read_count": 1,
                    }
                    if case_id == "U1-ORDINARY-SYNC-TOOL" and index == 0
                    else None
                ),
                "excluded_memory_tools": ["milai_milai_recall"],
                "provider_transport": "stream",
                "finish_reason": finish_reason,
                "prompt_tokens": 8,
                "completion_tokens": 2,
                "adapter_total_ms": 4.0,
                "provider_prefill_answer_ms": 2.0,
            }
        )
    return rows


def _interaction_ledger_rows(case_id: str, *, rounds: int | None = None):  # type: ignore[no-untyped-def]
    plan = runner.interaction_scenarios.interaction_plan(case_id)
    round_count = plan.provider_rounds if rounds is None else rounds
    rows: list[dict[str, object]] = []
    for index in range(round_count):
        finish_reason = "stop"
        rows.extend(
            (
                {
                    "event": "RESERVED",
                    "logical_request_id": f"logical-{index + 1}",
                    "transport": "stream",
                },
                {
                    "event": "PROVIDER_TERMINAL",
                    "logical_request_id": f"logical-{index + 1}",
                    "transport": "stream",
                    "status": "SUCCEEDED",
                    "reason_code": None,
                    "request_started": True,
                    "native_request_observed": True,
                    "native_request_id": f"native-{index + 1}",
                    "prompt_tokens": 8,
                    "completion_tokens": 2,
                    "finish_reason": finish_reason,
                },
                {
                    "event": "POST_PROVIDER_TERMINAL",
                    "logical_request_id": f"logical-{index + 1}",
                    "status": "SUCCEEDED",
                    "reason_code": None,
                },
            )
        )
    return rows


def _install_interaction_smoke_transport(
    lifecycle: runner.OpenWorkerU1Lifecycle,
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure: str | None = None,
) -> list[list[str]]:
    case_id = lifecycle.case.case_id
    commands: list[list[str]] = []

    def command(argv, **_kwargs):  # type: ignore[no-untyped-def]
        current = list(argv)
        if "curl" in current:
            return subprocess.CompletedProcess(
                current,
                0,
                stdout=(
                    b'{"id":"session-interaction-1","directory":"/openworker/runtime"}'
                ),
                stderr=b"",
            )
        commands.append(current)
        prompt = runner.interaction_scenarios.interaction_prompt(case_id)
        assert tuple(
            current
        ) == runner.interaction_scenarios.build_opencode_interaction_command(
            case_id,
            container_name=lifecycle.container_name,
            prompt=prompt,
            model=f"openworker/{runner.MODEL_ID}",
            session_id="session-interaction-1",
        )
        rounds = 3 if failure == "third_round" else None
        trace_rows = _interaction_trace_rows(case_id, rounds=rounds)
        ledger_rows = _interaction_ledger_rows(case_id, rounds=rounds)
        if failure == "missing_done":
            ledger_rows.pop()
            ledger_rows[-1]["status"] = "FAILED"
            ledger_rows[-1]["reason_code"] = "PROVIDER_STREAM_DONE_MISSING"
        elif failure == "missing_usage":
            ledger_rows[1]["prompt_tokens"] = None
        lifecycle.host_trace.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in trace_rows),
            encoding="utf-8",
        )
        lifecycle.provider_ledger.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in ledger_rows),
            encoding="utf-8",
        )
        if failure == "cli_truncated":
            stdout = json.dumps(
                {
                    "type": "step_start",
                    "sessionID": "session-interaction-1",
                    "part": {"type": "step-start"},
                }
            ).encode()
        elif failure == "stream_error":
            stdout = json.dumps(
                {
                    "type": "error",
                    "sessionID": "session-interaction-1",
                    "error": {"name": "ProviderStreamError"},
                }
            ).encode()
        else:
            tool_name = "bash" if failure == "wrong_tool" else "read"
            tools = 2 if failure == "multiple_tools" else 1
            stdout = _interaction_stdout(case_id, tool_name=tool_name, tools=tools)
        if failure == "raw_persistence":
            (lifecycle.paths.durable / "forbidden-raw-events.log").write_bytes(stdout)
        elif failure == "sensitive_leaf_persistence":
            (lifecycle.paths.durable / "forbidden-sensitive-leaf.log").write_text(
                "private ordinary read result",
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(current, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(runner, "_command_bytes", command)
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)
    return commands


def test_interaction_case_contracts_are_real_and_stream_uses_canonical_fixture() -> (
    None
):
    assert len(runner._IMPLEMENTED_REAL_CASES) == 37
    assert runner._LIFECYCLE_CASE_IDS <= runner._IMPLEMENTED_REAL_CASES
    assert runner._INTERACTION_CASE_IDS <= runner._IMPLEMENTED_REAL_CASES
    assert "U1-STREAM" in runner._CANONICAL_POSITIVE_CASES
    stream = runner.CASES["U1-STREAM"]
    ordinary = runner.CASES["U1-ORDINARY-SYNC-TOOL"]
    assert (stream.title, stream.memory_requirement) == (
        "Streaming EXACT memory semantics",
        "EXACT",
    )
    assert (stream.expected_mcp_calls, stream.expected_provider_calls) == (1, 1)
    assert (ordinary.memory_requirement, ordinary.expected_mcp_calls) == ("NONE", 0)
    assert ordinary.expected_provider_calls == 2
    assert runner._fixture_options_for_case("U1-STREAM") == runner.FixtureOptions()


@pytest.mark.parametrize("case_id", ["U1-STREAM", "U1-ORDINARY-SYNC-TOOL"])
def test_interaction_smoke_executes_attached_command_and_persists_hash_only_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, case_id)
    commands = _install_interaction_smoke_transport(lifecycle, monkeypatch)

    evidence = lifecycle.smoke()

    assert len(commands) == 1
    assert commands[0][commands[0].index("--attach") + 1] == "http://127.0.0.1:4096"
    assert evidence["observed_mcp_calls"] == lifecycle.case.expected_mcp_calls
    assert evidence["observed_provider_calls"] == lifecycle.case.expected_provider_calls
    assert evidence["automatic_retries"] == 0
    assert evidence["model_visible_memory_tool_events"] == 0
    assert evidence["raw_prompt_or_answer_persisted"] is False
    interaction = evidence["interaction_evidence"]
    assert interaction["status"] == "PASS"
    assert interaction["provider_rounds"] == lifecycle.case.expected_provider_calls
    artifact = json.loads(
        (lifecycle.paths.durable / "interaction-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert artifact["interaction"] == interaction
    persisted = json.dumps(artifact, sort_keys=True)
    assert "private interaction response" not in persisted
    assert "private ordinary read result" not in persisted
    assert "/openworker/runtime/opencode.json" not in persisted
    assert "session-interaction-1" not in persisted
    assert "openworker-local" not in persisted


def test_stream_smoke_proves_exact_stream_usage_done_and_provider_join(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, "U1-STREAM")
    _install_interaction_smoke_transport(lifecycle, monkeypatch)

    evidence = lifecycle.smoke()

    assert evidence["memory_route"] == "EXACT"
    assert evidence["context_tokens"] == 42
    assert evidence["context_in_prompt"] is True
    assert evidence["mcp_receipt_sha256"]
    assert evidence["runtime_trace_sha256"]
    sse = evidence["interaction_evidence"]["sse"]
    assert sse["include_usage"] is True
    assert sse["done"] is True
    assert sse["finish_reason"] == "stop"
    assert sse["gateway_terminal_event_count"] == 1


def test_ordinary_smoke_proves_one_read_two_rounds_and_no_third_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, "U1-ORDINARY-SYNC-TOOL")
    commands = _install_interaction_smoke_transport(lifecycle, monkeypatch)

    evidence = lifecycle.smoke()

    assert "--agent" in commands[0]
    assert commands[0][commands[0].index("--agent") + 1] == "dg13u-ordinary-sync"
    assert evidence["observed_mcp_calls"] == 0
    assert evidence["observed_provider_calls"] == 2
    ordinary = evidence["interaction_evidence"]["ordinary_tool"]
    assert ordinary["execution_count"] == 1
    assert ordinary["final_tool_choice"] == "NONE"
    assert ordinary["third_round_observed"] is False
    assert ordinary["tool_name_sha256"] == runner.hashlib.sha256(b"read").hexdigest()


@pytest.mark.parametrize("case_id", ["U1-STREAM", "U1-ORDINARY-SYNC-TOOL"])
def test_interaction_smoke_uses_host_terminal_when_cli_jsonl_is_truncated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, case_id)
    _install_interaction_smoke_transport(
        lifecycle, monkeypatch, failure="cli_truncated"
    )

    evidence = lifecycle.smoke()

    assert evidence["provider_terminal_status"] == "SUCCEEDED"
    assert evidence["opencode_interaction_events"]["terminal_success_event_count"] == 0
    assert evidence["observed_provider_calls"] == lifecycle.case.expected_provider_calls
    if case_id == "U1-ORDINARY-SYNC-TOOL":
        assert evidence["interaction_evidence"]["ordinary_tool"]["execution_count"] == 1


@pytest.mark.parametrize(
    ("case_id", "failure"),
    (
        ("U1-STREAM", "missing_done"),
        ("U1-STREAM", "missing_usage"),
        ("U1-STREAM", "stream_error"),
        ("U1-ORDINARY-SYNC-TOOL", "wrong_tool"),
        ("U1-ORDINARY-SYNC-TOOL", "multiple_tools"),
        ("U1-ORDINARY-SYNC-TOOL", "third_round"),
        ("U1-ORDINARY-SYNC-TOOL", "raw_persistence"),
    ),
)
def test_interaction_smoke_negative_twins_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    failure: str,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, case_id)
    _install_interaction_smoke_transport(lifecycle, monkeypatch, failure=failure)

    with pytest.raises(runner.RunError, match="interaction smoke accounting failed"):
        lifecycle.smoke()


def test_opencode_sensitive_leaf_substring_leak_is_detected_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, "U1-ORDINARY-SYNC-TOOL")
    _install_interaction_smoke_transport(
        lifecycle,
        monkeypatch,
        failure="sensitive_leaf_persistence",
    )
    captured: dict[str, object] = {}
    original_reduce = runner.interaction_scenarios.reduce_interaction

    def capture_then_reduce(case_id, observation):  # type: ignore[no-untyped-def]
        captured.update(observation["persistence"])
        return original_reduce(case_id, observation)

    monkeypatch.setattr(
        runner.interaction_scenarios,
        "reduce_interaction",
        capture_then_reduce,
    )

    with pytest.raises(runner.RunError, match="interaction smoke accounting failed"):
        lifecycle.smoke()

    assert captured == {
        "tool_arguments": True,
        "tool_result": True,
        "prompt": True,
        "credentials": False,
    }
    assert not (lifecycle.paths.durable / "interaction-evidence.json").exists()


def test_opencode_sensitive_payload_needles_cover_tool_body_leaves(
    tmp_path: Path,
) -> None:
    values = {
        "argument": "private singular argument",
        "arguments": {"query": "private nested arguments", "mode": "x"},
        "input": {"filePath": "/private/fixture/input.json"},
        "result": "private tool result",
        "output": "private tool output",
        "empty": "",
    }
    raw = (json.dumps({"type": "tool_use", "part": values}) + "\n").encode()
    marker = b"safe-fixture-marker"

    needles = runner._opencode_sensitive_payload_needles(
        raw,
        fixture_markers=(marker,),
    )

    assert set(needles) == {
        b"private singular argument",
        b"private nested arguments",
        b"x",
        b"/private/fixture/input.json",
        b"private tool result",
        b"private tool output",
        marker,
    }
    (tmp_path / "leak.log").write_bytes(b"prefix private tool result suffix")
    assert runner._durable_payload_observed(
        tmp_path,
        needles,
        minimum_needle_bytes=1,
    )


@pytest.mark.parametrize(
    ("case_id", "memory_mode", "ordinary_flag"),
    (
        ("U1-STREAM", "prefetch", False),
        ("U1-ORDINARY-SYNC-TOOL", "none", True),
    ),
)
def test_interaction_host_launch_uses_case_specific_memory_and_single_read_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    memory_mode: str,
    ordinary_flag: bool,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, case_id)
    (lifecycle.paths.durable / "logs").mkdir()
    (lifecycle.product_venv / "bin").mkdir(parents=True)
    executable = lifecycle.product_venv / "bin/milai-openworker-adapter"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    lifecycle.gateway = "127.0.0.1"
    launched: list[list[str]] = []

    class Process:
        pid = 54321

        @staticmethod
        def poll():  # type: ignore[no-untyped-def]
            return None

    def popen(command, **_kwargs):  # type: ignore[no-untyped-def]
        launched.append(list(command))
        return Process()

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner, "_stable_process_marker", lambda _pid: "7002")
    monkeypatch.setattr(runner, "_free_bind_port", lambda _host: 45101)
    monkeypatch.setattr(
        runner,
        "_wait_http_json",
        lambda *_args, **_kwargs: {"data": [{"id": runner.MODEL_ID}]},
    )
    monkeypatch.setattr(runner, "_terminate_owned_process", lambda *_args: None)
    monkeypatch.setattr(runner, "_process_alive", lambda *_args: False)
    resources = runner.ResourceRegistry(lifecycle.paths.run_id)

    lifecycle._start_host(resources)

    command = launched[0]
    assert command[command.index("--memory-mode") + 1] == memory_mode
    assert ("--single-ordinary-tool-required-once" in command) is ordinary_flag
    assert ("--ordinary-tool-provider-compatibility" in command) is ordinary_flag
    prefetch_options = {
        "--prefetch-socket": str(lifecycle.host_prefetch_socket),
        "--tokenizer-json": str(runner.TOKENIZER_JSON),
        "--broker-policy": str(lifecycle.host_policy_path),
        "--task-fixture": str(runner.CANDIDATE_FIXTURE),
    }
    assert all(
        command.count(option) == (0 if ordinary_flag else 1)
        for option in prefetch_options
    )
    if not ordinary_flag:
        assert all(
            command[command.index(option) + 1] == value
            for option, value in prefetch_options.items()
        )
    if ordinary_flag:
        assert command.count("--single-ordinary-tool-required-once") == 1
        assert (
            command[command.index("--single-ordinary-tool-required-once") + 1] == "read"
        )
        assert (
            command[command.index("--ordinary-tool-provider-compatibility") + 1]
            == "VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER"
        )
    manifest = json.loads(lifecycle.provider_manifest.read_text(encoding="utf-8"))
    assert manifest["max_native_requests"] == lifecycle.case.expected_provider_calls
    assert resources.cleanup_all()["status"] == runner.TerminalStatus.PASS


def test_session_create_is_one_shell_free_control_call_and_never_persists_raw_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, "U1-STREAM")
    private_session = "ses_private_runner_created_1"
    commands: list[list[str]] = []

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        commands.append(list(arguments))
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=json.dumps(
                {"id": private_session, "directory": "/openworker/runtime"}
            ).encode(),
            stderr=b"",
        )

    monkeypatch.setattr(runner, "_command_bytes", command)

    observed = lifecycle._create_opencode_session()

    assert observed == private_session
    assert commands == [
        list(
            task_scenarios.build_opencode_session_create_command(
                lifecycle.container_name
            )
        )
    ]
    assert not lifecycle.provider_ledger.exists()
    assert not lifecycle.host_trace.exists()
    assert all(
        private_session.encode() not in artifact.read_bytes()
        for artifact in lifecycle.paths.durable.rglob("*")
        if artifact.is_file()
    )


def test_session_create_fails_if_control_call_mutates_provider_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _interaction_smoke_lifecycle(tmp_path, "U1-STREAM")

    def command(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        lifecycle.provider_ledger.write_text(
            '{"event":"RESERVED","logical_request_id":"forbidden"}\n',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=b'{"id":"ses_created_but_accounted"}',
            stderr=b"",
        )

    monkeypatch.setattr(runner, "_command_bytes", command)

    with pytest.raises(runner.RunError, match="consumed a provider or MCP call"):
        lifecycle._create_opencode_session()


class _LifecycleProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


def _lifecycle_unit(
    tmp_path: Path,
    case_id: str,
) -> tuple[runner.OpenWorkerU1Lifecycle, runner.ResourceRegistry]:
    run_id = f"dg13u-u1-{case_id.casefold()}"
    durable = tmp_path / run_id
    temporary = tmp_path / "temporary"
    uds = tmp_path / "uds"
    product = temporary / "product"
    for path in (durable / "logs", temporary / "secrets", uds, product / "bin"):
        path.mkdir(parents=True, exist_ok=True)
    durable.chmod(0o700)

    class Runtime:
        identity = runner.FreshRuntimeIdentity(
            "fresh-db",
            "http://127.0.0.1:49191",
            801,
            "8001",
            802,
            "8002",
            "head",
        )
        reader_token = "reader-token"

    paths = runner.RunPaths(run_id, durable, temporary, uds)
    lifecycle = runner.OpenWorkerU1Lifecycle(
        paths,
        runner.CASES[case_id],
        Runtime(),
        product,
    )
    lifecycle.policy_path.write_text('{"policy":"fixed"}\n', encoding="utf-8")
    lifecycle.provider_manifest.write_text('{"manifest":"fixed"}\n', encoding="utf-8")
    lifecycle.provider_ledger.write_text("", encoding="utf-8")
    lifecycle.host_trace.write_text("", encoding="utf-8")
    lifecycle.gateway = "127.0.0.1"
    lifecycle.host_port = 45191
    lifecycle.ingress_token = "ingress-token"
    lifecycle.started = True
    registry = runner.ResourceRegistry(paths.run_id)
    lifecycle._resources = registry
    return lifecycle, registry


def test_recovery_process_replacement_is_cas_and_rolls_back_checkpoint_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = runner.RecoveryPlanCoordinator(
        "dg13u-u1-recovery-cas",
        tmp_path / "durable",
        tmp_path / "temporary",
        tmp_path / "uds",
    )
    coordinator.sha256 = "a" * 64
    coordinator._resources.append(
        {
            "kind": "process",
            "ownership": "RUN_OWNED",
            "role": "host-adapter",
            "pid": 701,
            "proc_start_marker": "9001",
        }
    )
    monkeypatch.setattr(
        coordinator, "checkpoint", lambda: setattr(coordinator, "sha256", "b" * 64)
    )

    coordinator.replace_process("host-adapter", 701, "9001", 702, "9002")
    current = next(
        row for row in coordinator._resources if row.get("role") == "host-adapter"
    )
    assert (current["pid"], current["proc_start_marker"]) == (702, "9002")
    with pytest.raises(runner.RunError, match="generation CAS mismatch"):
        coordinator.replace_process("host-adapter", 701, "9001", 703, "9003")

    def fail_checkpoint() -> None:
        coordinator.sha256 = "c" * 64
        raise runner.RunError("checkpoint failed")

    monkeypatch.setattr(coordinator, "checkpoint", fail_checkpoint)
    with pytest.raises(runner.RunError, match="checkpoint failed"):
        coordinator.replace_process("host-adapter", 702, "9002", 703, "9003")
    current = next(
        row for row in coordinator._resources if row.get("role") == "host-adapter"
    )
    assert (current["pid"], current["proc_start_marker"]) == (702, "9002")
    assert coordinator.sha256 == "b" * 64


@pytest.mark.parametrize("component", ("broker", "host"))
def test_spawn_marker_failure_reaps_unregistered_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component: str,
) -> None:
    lifecycle, _registry = _lifecycle_unit(tmp_path, "U1-BROKER-INODE-RECREATE")
    executable = (
        lifecycle.product_venv
        / "bin"
        / ("milai-mcp-broker" if component == "broker" else "milai-openworker-adapter")
    )
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    process = _LifecycleProcess(711 if component == "broker" else 712)
    terminated: list[tuple[object, str]] = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        runner,
        "_stable_process_marker",
        lambda _pid: (_ for _ in ()).throw(runner.RunError("marker unavailable")),
    )
    monkeypatch.setattr(runner, "_process_marker", lambda _pid: "9999")
    monkeypatch.setattr(
        runner,
        "_terminate_owned_process",
        lambda owned, marker: terminated.append((owned, marker)),
    )

    with pytest.raises(runner.RunError, match="marker unavailable"):
        if component == "broker":
            lifecycle._spawn_broker(lifecycle.broker_log)
        else:
            lifecycle._spawn_host(
                trace_path=lifecycle.host_trace,
                log_path=lifecycle.host_log,
            )
    assert terminated == [(process, "9999")]


@pytest.mark.parametrize("silent_follow", (False, True))
def test_broker_lifecycle_smoke_replaces_inode_and_requires_explicit_remount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    silent_follow: bool,
) -> None:
    lifecycle, registry = _lifecycle_unit(tmp_path, "U1-BROKER-INODE-RECREATE")
    old = _LifecycleProcess(721)
    new = _LifecycleProcess(722)
    old_present = {"value": True}
    lifecycle.broker_process = old  # type: ignore[assignment]
    lifecycle.broker_marker = "9101"
    lifecycle.broker_generation = 1
    lifecycle.socket_identity = (11, 101)
    registry.register_process(
        "mcp-broker",
        old.pid,
        "9101",
        lambda _generation: None,
        lambda _generation: not old_present["value"],
    )
    events: list[str] = []
    mounts = iter(((11, 101), (11, 101), (11, 202)))
    unavailable = iter((True, not silent_follow))
    worker_ids = iter(("a" * 64, "b" * 64))

    def stop() -> tuple[_LifecycleProcess, str]:
        events.append("stop")
        old_present["value"] = False
        old.returncode = 0
        return old, "9101"

    def start(
        resources: runner.ResourceRegistry,
        previous: _LifecycleProcess,
        marker: str,
    ) -> tuple[int, int]:
        events.append("start")
        assert (previous, marker) == (old, "9101")
        generation = resources.replace_process(
            "mcp-broker",
            old.pid,
            "9101",
            new.pid,
            "9102",
            lambda _generation: None,
            lambda _generation: False,
        )
        lifecycle.broker_process = new  # type: ignore[assignment]
        lifecycle.broker_marker = "9102"
        lifecycle.broker_generation = generation.generation
        lifecycle.socket_identity = (11, 202)
        return (11, 202)

    monkeypatch.setattr(lifecycle, "_worker_mount_identity", lambda: next(mounts))
    monkeypatch.setattr(
        lifecycle, "_worker_bound_socket_unavailable", lambda: next(unavailable)
    )
    monkeypatch.setattr(
        lifecycle, "_worker_process_identity_sha256", lambda: next(worker_ids)
    )
    monkeypatch.setattr(lifecycle, "_stop_broker_for_replacement", stop)
    monkeypatch.setattr(lifecycle, "_start_broker_replacement", start)
    monkeypatch.setattr(
        lifecycle, "_recreate_worker", lambda: events.append("recreate")
    )
    monkeypatch.setattr(lifecycle, "_wait_worker_health", lambda: "c" * 64)
    monkeypatch.setattr(
        lifecycle,
        "_mcp_catalog_readiness",
        lambda: events.append("catalog") or "d" * 64,
    )
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)

    if silent_follow:
        with pytest.raises(runner.RunError, match="silently followed"):
            lifecycle._smoke_lifecycle_scenario()
        assert events == ["stop", "start"]
        return

    evidence = lifecycle._smoke_lifecycle_scenario()

    assert events == ["stop", "start", "recreate", "catalog"]
    assert evidence["observed_mcp_calls"] == 0
    assert evidence["observed_provider_calls"] == 0
    assert set(evidence["latencies_ms"]) == {
        "openworker",
        "adapter",
        "mcp",
        "runtime",
        "compile",
        "provider",
    }
    assert lifecycle.lifecycle_measurement is not None
    assert lifecycle.lifecycle_measurement["readiness_calls"] == {
        "host_health": 0,
        "mcp_catalog": 1,
    }
    current = runner.resource_registry.process_snapshot_by_role(registry.snapshot())[
        "mcp-broker"
    ]
    assert (current.pid, current.marker, current.generation) == (722, "9102", 2)


def _adapter_turn(
    lifecycle: runner.OpenWorkerU1Lifecycle,
    *,
    suffix: int,
    output: str,
) -> dict[str, object]:
    digest = lambda label: runner.hashlib.sha256(label.encode()).hexdigest()
    return {
        "session_sha256": digest("session"),
        "task_sha256": digest("task"),
        "operation_sha256": digest(f"operation-{suffix}"),
        "output_sha256": digest(output),
        "output_bytes": len(output),
        "known_sessions": {"A": "private-session"},
        "ledger": [],
        "trace": [],
        "logical_request_id": f"{lifecycle.paths.run_id}-ow-{suffix:02d}",
        "native_request_id": f"native-{suffix}",
        "access_outcome": {"status": "CONTEXT_READY_CURRENT"},
        "recall_execution_trace": {"terminal_route": "L0"},
        "trace_id": f"trace-{suffix}",
        "slot_key": digest(f"slot-{suffix}"),
        "context_sha256": digest(f"context-{suffix}"),
        "task_relation": "TASK_START",
        "prepare_status": "READY",
        "route": "EXACT",
        "compiled_memory_tokens": 39 + suffix,
        "current_state_status": "HIT",
        "current_state_claim_count": 1,
        "registry_revision_before": 0,
        "retained_slot_present": False,
        "latencies_ms": {
            "openworker": 1.0,
            "adapter": 2.0,
            "mcp": 3.0,
            "runtime": 4.0,
            "compile": 5.0,
            "provider": 6.0,
        },
    }


@pytest.mark.parametrize("old_slot_reused", (False, True))
def test_adapter_lifecycle_smoke_uses_new_host_generation_and_writes_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old_slot_reused: bool,
) -> None:
    lifecycle, registry = _lifecycle_unit(tmp_path, "U1-ADAPTER-RESTART")
    old = _LifecycleProcess(731)
    new = _LifecycleProcess(732)
    old_present = {"value": True}
    lifecycle.host_process = old  # type: ignore[assignment]
    lifecycle.host_marker = "9201"
    lifecycle.host_generation = 1
    registry.register_process(
        "host-adapter",
        old.pid,
        "9201",
        lambda _generation: None,
        lambda _generation: not old_present["value"],
    )
    events: list[str] = []
    worker_sha = "e" * 64

    def turn(spec, **_kwargs):  # type: ignore[no-untyped-def]
        events.append(spec.turn_id)
        result = _adapter_turn(
            lifecycle,
            suffix=1 if spec.turn_id == "WARM" else 2,
            output=spec.turn_id,
        )
        if spec.turn_id == "CONTINUATION" and old_slot_reused:
            result["registry_revision_before"] = 1
            result["retained_slot_present"] = True
        return result

    def stop() -> tuple[_LifecycleProcess, str]:
        events.append("stop")
        old_present["value"] = False
        old.returncode = 0
        return old, "9201"

    replacement_trace = lifecycle.paths.durable / "host-access-trace.gen2.jsonl"

    def start(
        resources: runner.ResourceRegistry,
        previous: _LifecycleProcess,
        marker: str,
    ) -> Path:
        events.append("start")
        assert (previous, marker) == (old, "9201")
        generation = resources.replace_process(
            "host-adapter",
            old.pid,
            "9201",
            new.pid,
            "9202",
            lambda _generation: None,
            lambda _generation: False,
        )
        lifecycle.host_process = new  # type: ignore[assignment]
        lifecycle.host_marker = "9202"
        lifecycle.host_generation = generation.generation
        replacement_trace.write_text("", encoding="utf-8")
        lifecycle.host_trace = replacement_trace
        return replacement_trace

    monkeypatch.setattr(lifecycle, "_execute_lifecycle_exact_turn", turn)
    monkeypatch.setattr(
        lifecycle, "_worker_process_identity_sha256", lambda: worker_sha
    )
    monkeypatch.setattr(lifecycle, "_stop_host_for_replacement", stop)
    monkeypatch.setattr(lifecycle, "_start_host_replacement", start)
    monkeypatch.setattr(lifecycle, "_wait_host_ready", lambda: events.append("health"))
    monkeypatch.setattr(lifecycle, "_capture_worker_logs", lambda: None)
    monkeypatch.setattr(runner, "_durable_payload_observed", lambda *_args: False)

    if old_slot_reused:
        with pytest.raises(runner.RunError, match="reused old task cache"):
            lifecycle._smoke_lifecycle_scenario()
        assert events == ["WARM", "stop", "start", "health", "CONTINUATION"]
        return

    evidence = lifecycle._smoke_lifecycle_scenario()

    assert events == ["WARM", "stop", "start", "health", "CONTINUATION"]
    assert evidence["context_tokens"] == 81
    assert evidence["observed_mcp_calls"] == 2
    assert evidence["observed_provider_calls"] == 2
    assert all(
        isinstance(evidence[name], str) and len(evidence[name]) == 64
        for name in (
            "access_id_sha256",
            "mcp_receipt_sha256",
            "runtime_trace_sha256",
            "native_request_id_sha256",
        )
    )
    assert set(evidence["latencies_ms"]) == {
        "openworker",
        "adapter",
        "mcp",
        "runtime",
        "compile",
        "provider",
    }
    measured = runner._smoke_artifact_measurement(
        lifecycle.paths,
        lifecycle.case,
        runner.TerminalStatus.PASS,
        evidence,
    )
    artifact_receipt = runner.evidence_artifacts.write_smoke_evidence_artifact(
        lifecycle.paths.durable,
        measured,
    )
    artifact = json.loads(
        (lifecycle.paths.durable / artifact_receipt["path"]).read_text(encoding="utf-8")
    )
    assert artifact["context_tokens"] == 81
    assert artifact["calls"]["mcp"]["observed"] == 2
    assert artifact["joined_identities"]["access_id_sha256"]


def _partial_broker_lifecycle_measurement() -> dict[str, object]:
    scenario = runner.lifecycle_scenarios.scenario_for_case("U1-BROKER-INODE-RECREATE")
    digest = lambda value: runner.hashlib.sha256(value.encode()).hexdigest()
    old_socket = digest("old-socket")
    new_socket = digest("new-socket")
    policy = digest("policy")
    return {
        "schema": runner.lifecycle_scenarios.MEASUREMENT_SCHEMA,
        "case_id": scenario.case_id,
        "execution_class": scenario.execution_class,
        "steps": [
            {
                "step_id": step.step_id,
                "status": "COMPLETED",
                "attempts": 1,
                "receipt_sha256": digest(step.step_id),
            }
            for step in scenario.steps[:-1]
        ],
        "mcp_calls": 0,
        "provider_calls": 0,
        "automatic_retries": 0,
        "readiness_calls": {"host_health": 0, "mcp_catalog": 1},
        "vllm": None,
        "cleanup": None,
        "identity": {
            "old_policy_sha256": policy,
            "replacement_policy_sha256": policy,
            "old_broker_process_sha256": digest("old-process"),
            "replacement_broker_process_sha256": digest("new-process"),
            "old_socket_identity_sha256": old_socket,
            "old_worker_bind_identity_sha256": old_socket,
            "replacement_socket_identity_sha256": new_socket,
            "recreated_worker_bind_identity_sha256": new_socket,
            "old_broker_stopped": True,
            "old_worker_bind_unavailable_after_stop": True,
            "old_worker_followed_replacement": False,
            "worker_recreated_and_remounted": True,
            "mcp_catalog_readiness_restored": True,
        },
    }


def test_lifecycle_finalizer_binds_cleanup_and_preserves_vllm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle, _registry = _lifecycle_unit(tmp_path, "U1-BROKER-INODE-RECREATE")
    vllm = {
        "completion_calls": 0,
        "lifecycle_mutated": False,
        "endpoint": "http://127.0.0.1:8000",
        "container": {"id": "external-container"},
        "image": {"id": "external-image"},
        "model_byte_closure": {"sha256": "a" * 64},
        "tokenizer": {"sha256": "b" * 64},
        "tokenizer_config": {"sha256": "c" * 64},
        "chat_template": {"sha256": "d" * 64},
    }
    finalizer = runner.LifecycleScenarioFinalizer(
        lifecycle.paths,
        lifecycle.case.case_id,
        _partial_broker_lifecycle_measurement(),
        vllm,
    )
    cleanup = {
        "schema": "milai.dg13u.u1-cleanup-receipt.v1",
        "run_id": lifecycle.paths.run_id,
        "status": "PASS",
        "existing_vllm_preserved": True,
        "external_lifecycle_mutations": 0,
        "items": [
            {
                "kind": "process",
                "identity": "mcp-broker:722:9102:g2",
                "ownership": "RUN_OWNED",
                "state": "removed",
                "attempts": 1,
            },
            {
                "kind": "external_vllm",
                "identity": "external",
                "ownership": "PRESERVED_EXTERNAL",
                "state": "preserved_external",
                "attempts": 0,
            },
        ],
    }
    (lifecycle.paths.durable / "cleanup-receipt.json").write_text(
        json.dumps(cleanup, sort_keys=True), encoding="utf-8"
    )
    monkeypatch.setattr(runner.u0, "_probe_vllm", lambda: copy.deepcopy(vllm))

    reduced = finalizer.finalize(cleanup)

    assert reduced["status"] == "PASS"
    assert reduced["cleanup"]["run_owned_resources_absent"] is True
    assert reduced["vllm"]["lifecycle_attempts"] == 0
    assert (lifecycle.paths.durable / "lifecycle-evidence.json").is_file()
    with pytest.raises(runner.RunError, match="not repeatable"):
        finalizer.finalize(cleanup)


def test_lifecycle_finalizer_rejects_incomplete_cleanup(
    tmp_path: Path,
) -> None:
    lifecycle, _registry = _lifecycle_unit(tmp_path, "U1-BROKER-INODE-RECREATE")
    vllm = {
        "completion_calls": 0,
        "lifecycle_mutated": False,
        "endpoint": "http://127.0.0.1:8000",
        "container": {},
        "image": {},
        "model_byte_closure": {},
        "tokenizer": {},
        "tokenizer_config": {},
        "chat_template": {},
    }
    finalizer = runner.LifecycleScenarioFinalizer(
        lifecycle.paths,
        lifecycle.case.case_id,
        _partial_broker_lifecycle_measurement(),
        vllm,
    )
    cleanup = {
        "schema": "milai.dg13u.u1-cleanup-receipt.v1",
        "run_id": lifecycle.paths.run_id,
        "status": "PASS",
        "existing_vllm_preserved": True,
        "external_lifecycle_mutations": 0,
        "items": [
            {
                "ownership": "RUN_OWNED",
                "state": "present",
                "attempts": 0,
            }
        ],
    }
    with pytest.raises(runner.RunError, match="cleanup is incomplete"):
        finalizer.finalize(cleanup)
