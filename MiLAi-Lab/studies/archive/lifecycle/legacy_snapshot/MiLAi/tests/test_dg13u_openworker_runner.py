from __future__ import annotations

import io
import json
import os
import stat
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import run_dg13u_openworker as runner

CASE_ID = "U0-IDENTITY-READINESS"
_MIGRATION_1 = b'revision: str = "0001_first"\ndown_revision = None\n'
_MIGRATION_2 = b'revision: str = "0002_second"\ndown_revision: str = "0001_first"\n'


def _configure_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    root = tmp_path / "cra-workspace"
    runs = root / "var/dg13/runs"
    temporary = root / "var/dg13/tmp"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "RUNS_ROOT", runs)
    monkeypatch.setattr(runner, "TMP_ROOT", temporary)
    monkeypatch.setattr(
        runner, "UV_BUILD_CACHE_SEED", root / "var/dg13/cache/uv-build-seed"
    )
    candidate_fixture = root / "contracts/agent/v1/dg13u-u1-candidate-fixture.json"
    candidate_fixture.parent.mkdir(parents=True, exist_ok=True)
    candidate_fixture.write_text(
        json.dumps(
            {
                "schema": "milai.dg13u.u1-candidate-fixture.v1",
                "status": "U1_CANDIDATE_OWNER_ACCEPTANCE_REQUIRED",
                "families": [
                    {"state_key": "a", "aliases": ["a"]},
                    {"state_key": "b", "aliases": ["b"]},
                    {"state_key": "c", "aliases": ["c"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "CANDIDATE_FIXTURE", candidate_fixture)
    monkeypatch.setattr(runner, "_is_cra_path", lambda _path: True)
    return runs, temporary


def _source_identity() -> dict[str, Any]:
    return {
        "kind": "CONTENT_SHA256_NO_GIT_IDENTITY",
        "git_sha": None,
        "sha256": "a" * 64,
        "file_count": 3,
        "total_bytes": 30,
        "entries": [],
        "runtime_entries_sha256": "b" * 64,
        "openworker_entries_sha256": "c" * 64,
    }


def _package_identity(run_dir: Path, temp_dir: Path) -> dict[str, Any]:
    artifact = run_dir / "packages/openworker/current.whl"
    artifact.parent.mkdir(parents=True, mode=0o755)
    artifact.write_bytes(b"current wheel")
    workspace = temp_dir / "installs/wheel"
    workspace.mkdir(parents=True, mode=0o700)
    return {
        "build_environment": {
            "TMPDIR": str(temp_dir / "build-tmp"),
            "UV_CACHE_DIR": str(temp_dir / "uv-cache"),
            "on_cra": True,
        },
        "artifacts": {
            "openworker_wheel": {
                "path": artifact.relative_to(run_dir).as_posix(),
                "bytes": artifact.stat().st_size,
                "sha256": runner._sha256_file(artifact),
            }
        },
        "fresh_installs": {
            "wheel": {
                "installed_identity": {
                    "versions": {
                        "milai-client": "0.1.0",
                        "milai-mcp": "0.1.0",
                        "milai-openworker-mcp": "0.1.0",
                        "milai-runtime": "0.1.0",
                    },
                    "origins": {},
                    "entrypoints": {},
                }
            }
        },
        "migration_head": "0028_dg11_window_projection",
        "command_receipts": [],
    }


def _openworker_identity(
    _packages: dict[str, Any], _run_id: str, _run_dir: Path, _temp_dir: Path
) -> dict[str, Any]:
    return {
        "image": {"reference": runner.OPENWORKER_IMAGE, "id": "sha256:image"},
        "source_files": {},
        "installed_executables": {},
        "installed_modules": {},
        "installed_versions": {"milai-openworker-mcp": "0.1.0"},
        "baked_composition": {
            "relation": {"relay": "CURRENT", "config": "CURRENT", "status": "CURRENT"},
            "task_producer": {
                "status": "READY",
                "observed_marker_count": len(runner._TASK_PRODUCER_MARKERS),
                "required_marker_count": len(runner._TASK_PRODUCER_MARKERS),
                "native_evidence_sha256": "8" * 64,
                "provider_calls": 0,
            },
            "inspection_container": {
                "name_sha256": "9" * 64,
                "created": True,
                "removed": True,
                "started": False,
            },
        },
        "lifecycle_mutated": False,
    }


def _runtime_identity(_packages: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": {"status": "PASS", "live": {}, "ready": {}, "capabilities": {}},
        "doctor_status": "PASS",
        "migration": {
            "current": "0028_dg11_window_projection",
            "head": "0028_dg11_window_projection",
            "packaged_head": "0028_dg11_window_projection",
        },
        "processes": [{"pid": 101, "ownership": "PRESERVED_EXTERNAL"}],
        "lifecycle_mutated": False,
    }


def test_runtime_probe_reads_migration_identity_from_doctor_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            {"status": "PASS"},
            {
                "status": "PASS",
                "checks": [
                    {
                        "name": "alembic",
                        "status": "PASS",
                        "facts": {
                            "current": "0028_dg11_window_projection",
                            "head": "0028_dg11_window_projection",
                        },
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(runner, "_run_json", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(
        runner,
        "_runtime_processes",
        lambda: [{"pid": 101, "ownership": "PRESERVED_EXTERNAL"}],
    )
    result = runner._probe_runtime({"migration_head": "0028_dg11_window_projection"})
    assert result["migration"] == {
        "current": "0028_dg11_window_projection",
        "head": "0028_dg11_window_projection",
        "packaged_head": "0028_dg11_window_projection",
    }


def _vllm_identity() -> dict[str, Any]:
    return {
        "endpoint": runner.VLLM_BASE_URL,
        "service": {"vllm_version": "0.27.1", "served_model_id": "model"},
        "container": {"id": "container-id", "started_at": "2026-08-19T00:00:00Z"},
        "image": {"id": "sha256:vllm"},
        "model_byte_closure": {"entries_sha256": "d" * 64},
        "tokenizer": {"path": "tokenizer.json", "sha256": "e" * 64},
        "tokenizer_config": {"path": "tokenizer_config.json", "sha256": "f" * 64},
        "chat_template": {"bytes": 10, "sha256": "1" * 64},
        "read_only_http_get_count": 4,
        "completion_calls": 0,
        "lifecycle_mutated": False,
    }


def _mock_success_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_collect_source_identity", _source_identity)
    monkeypatch.setattr(runner, "_build_and_probe_packages", _package_identity)
    monkeypatch.setattr(runner, "_probe_openworker", _openworker_identity)
    monkeypatch.setattr(runner, "_probe_runtime", _runtime_identity)
    monkeypatch.setattr(runner, "_probe_vllm", _vllm_identity)


def test_unknown_case_is_rejected_before_any_mutation_or_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("probe or mutation reached")

    monkeypatch.setattr(runner, "_prepare_paths", forbidden)
    monkeypatch.setattr(runner, "_collect_source_identity", forbidden)
    with pytest.raises(runner.DG13URunnerError, match="unsupported case_id"):
        runner.run_identity_readiness("identity-case-0001", "U0-UNKNOWN")
    assert not runs.exists()
    assert not temporary.exists()


@pytest.mark.parametrize("version", [(3, 10), (3, 13), (4, 0)])
def test_unsupported_python_is_rejected_before_run_mutation(
    version: tuple[int, int],
) -> None:
    with pytest.raises(runner.DG13URunnerError, match=r"Python >=3\.11,<3\.13"):
        runner._validate_python_version(version)


@pytest.mark.parametrize("version", [(3, 11), (3, 12)])
def test_supported_python_versions_pass(version: tuple[int, int]) -> None:
    runner._validate_python_version(version)


def test_unsupported_python_stops_before_paths_and_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("run mutation or probe reached")

    monkeypatch.setattr(runner, "sys", SimpleNamespace(version_info=(3, 10, 12)))
    monkeypatch.setattr(runner, "_prepare_paths", forbidden)
    monkeypatch.setattr(runner, "_collect_source_identity", forbidden)
    with pytest.raises(runner.DG13URunnerError, match=r"Python >=3\.11,<3\.13"):
        runner.run_identity_readiness("identity-python-check", CASE_ID)


def test_current_prefetch_fails_before_provider_when_baked_image_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    _mock_success_probes(monkeypatch)

    def stale(
        packages: dict[str, Any], run_id: str, run_dir: Path, temp_dir: Path
    ) -> dict[str, Any]:
        value = _openworker_identity(packages, run_id, run_dir, temp_dir)
        value["baked_composition"]["relation"] = {
            "relay": "STALE",
            "config": "STALE",
            "status": "STALE",
        }
        return value

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("charge-bearing or later readiness probe reached")

    monkeypatch.setattr(runner, "_probe_openworker", stale)
    monkeypatch.setattr(runner, "_probe_runtime", forbidden)
    monkeypatch.setattr(runner, "_probe_vllm", forbidden)
    run_id = "identity-case-0002"
    report = runner.run_identity_readiness(run_id, "U0-CURRENT-PREFETCH")
    run_dir = runs / run_id

    assert report["status"] == "FAIL"
    assert report["calls"]["provider"] == {
        "expected": 0,
        "maximum": 1,
        "observed": 0,
        "unaccounted": 0,
    }
    assert report["correctness"] == {
        "passed": 0,
        "denominator": 0,
        "status": "NOT_RUN",
    }
    capability = json.loads((run_dir / "provider-capability.json").read_text())
    ledger = json.loads((run_dir / "provider-ledger.jsonl").read_text())
    assert capability["maximum_completion_calls"] == 1
    assert capability["automatic_retries"] == 0
    assert ledger["request_issued"] is False
    assert ledger["provider_native_request_id"] is None
    assert not (temporary / run_id).exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "FAIL"
    assert manifest["owner_acceptance"] is None
    assert manifest["current_provider_inventory"]["sha256"] == runner._sha256_file(
        runner.PROVIDER_INVENTORY
    )
    assert manifest["fixture"]["status"] == "U1_CANDIDATE_OWNER_ACCEPTANCE_REQUIRED"
    assert len(manifest["fixture"]["families"]) == 3
    readiness = json.loads((run_dir / "readiness.json").read_text())
    assert readiness["reason_code"] == "CURRENT_IMAGE_COMPOSITION_STALE"
    assert capability["status"] == "FAIL_BEFORE_CALL"
    cleanup = json.loads((run_dir / "cleanup-receipt.json").read_text())
    assert any(
        item["kind"] == "container" and item["state"] == "removed"
        for item in cleanup["items"]
    )


@pytest.mark.parametrize(
    ("producer_status", "reason_code"),
    [
        ("ABSENT", "TASK_PRODUCER_ABSENT_OBSERVED"),
        ("READY", "WAITING_OWNER_ACCEPTANCE"),
    ],
)
def test_current_prefetch_zero_provider_readiness_terminal_is_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    producer_status: str,
    reason_code: str,
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    _mock_success_probes(monkeypatch)

    def producer_probe(
        packages: dict[str, Any], run_id: str, run_dir: Path, temp_dir: Path
    ) -> dict[str, Any]:
        value = _openworker_identity(packages, run_id, run_dir, temp_dir)
        value["baked_composition"]["task_producer"]["status"] = producer_status
        return value

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("provider or later readiness probe reached")

    monkeypatch.setattr(runner, "_probe_openworker", producer_probe)
    monkeypatch.setattr(runner, "_probe_runtime", forbidden)
    monkeypatch.setattr(runner, "_probe_vllm", forbidden)
    run_id = f"producer-{producer_status.lower()}"
    report = runner.run_identity_readiness(run_id, "U0-CURRENT-PREFETCH")
    run_dir = runs / run_id

    assert report["status"] == "NOT_RUN"
    assert report["calls"]["provider"]["observed"] == 0
    assert report["correctness"] == {
        "passed": 0,
        "denominator": 0,
        "status": "NOT_RUN",
    }
    trace = [
        json.loads(line)
        for line in (run_dir / "stage-trace.jsonl").read_text().splitlines()
    ]
    task = next(row for row in trace if row["stage"] == "TASK")
    assert task["status"] == "NOT_RUN"
    assert task["reason_code"] == reason_code
    assert task["native_identity"]["task_producer_status"] == producer_status
    capability = json.loads((run_dir / "provider-capability.json").read_text())
    assert capability["status"] == "NOT_RUN_BEFORE_CALL"
    ledger = json.loads((run_dir / "provider-ledger.jsonl").read_text())
    assert ledger["request_issued"] is False
    assert ledger["provider_native_request_id"] is None
    assert not (temporary / run_id).exists()


def test_identity_readiness_emits_closed_artifacts_and_preserves_external_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    _mock_success_probes(monkeypatch)
    run_id = "identity-case-0003"
    report = runner.run_identity_readiness(run_id, CASE_ID)
    run_dir = runs / run_id

    assert report["status"] == "PASS"
    assert report["baseline_label"] == "DG13U_U0_CURRENT_BASELINE"
    assert report["u1_product_usable"] is False
    assert report["owner_acceptance"] is None
    assert report["calls"]["provider"] == {
        "expected": 0,
        "maximum": 0,
        "observed": 0,
        "unaccounted": 0,
    }
    assert report["correctness"] == {
        "passed": 0,
        "denominator": 0,
        "status": "NOT_RUN",
    }
    assert not (temporary / run_id).exists()
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700

    required = {
        "manifest.json",
        "readiness.json",
        "stage-trace.jsonl",
        "join-reconciliation.json",
        "report.json",
        "cleanup-receipt.json",
    }
    assert required.issubset({path.name for path in run_dir.iterdir()})
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o700
        for path in run_dir.rglob("*")
        if path.is_dir()
    )

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["runner_python"]["version"][:2] == list(runner.sys.version_info[:2])
    assert manifest["source_content_identity"]["git_sha"] is None
    assert manifest["accepted_owner_decision_receipt_digest"] is None
    assert manifest["request_contract"]["provider_call_ceiling"] == 0
    assert manifest["request_contract"]["retry_policy"] == "NO_RETRY"
    readiness = json.loads((run_dir / "readiness.json").read_text())
    assert readiness["combined_e2e"] is False
    assert readiness["components"]["runtime"]["status"] == "PASS"
    assert readiness["components"]["openworker"]["status"] == "NOT_RUN"
    reconciliation = json.loads((run_dir / "join-reconciliation.json").read_text())
    assert reconciliation["expected_turns"] == 0
    assert reconciliation["turns"] == []
    cleanup = json.loads((run_dir / "cleanup-receipt.json").read_text())
    assert cleanup["existing_vllm_preserved"] is True
    assert cleanup["external_lifecycle_mutations"] == 0
    assert any(
        item["kind"] == "vllm" and item["state"] == "preserved_external"
        for item in cleanup["items"]
    )

    trace = [
        json.loads(line)
        for line in (run_dir / "stage-trace.jsonl").read_text().splitlines()
    ]
    assert [row["stage"] for row in trace] == list(runner._TRACE_STAGES)
    assert all(row["attempt"] == 1 for row in trace)
    assert next(row for row in trace if row["stage"] == "PROVIDER")["reason_code"] == (
        "READ_ONLY_VLLM_IDENTITY_NO_COMPLETION"
    )
    for stage in runner._IDENTITY_NOT_RUN:
        assert (
            next(row for row in trace if row["stage"] == stage)["status"] == "NOT_RUN"
        )


def test_created_inspection_container_cleanup_failure_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    _mock_success_probes(monkeypatch)

    def probe_with_pending_container(
        packages: dict[str, Any], run_id: str, run_dir: Path, temp_dir: Path
    ) -> dict[str, Any]:
        value = _openworker_identity(packages, run_id, run_dir, temp_dir)
        container_name = (
            f"milai-dg13u-inspect-{runner._sha256_bytes(run_id.encode())[:16]}"
        )
        runner._atomic_write(
            run_dir / "baked-inspection-receipt.json",
            {
                "schema": "milai.dg13u.baked-image-inspection-receipt.v1",
                "container_name_sha256": runner._sha256_bytes(container_name.encode()),
                "created": True,
                "started": False,
                "removed": False,
            },
        )
        value["baked_composition"]["inspection_container"] = {
            "name_sha256": runner._sha256_bytes(container_name.encode()),
            "created": True,
            "started": False,
            "removed": False,
        }
        return value

    def cleanup_retry_fails(
        command: list[str], *, cwd: Path = runner.ROOT, timeout: int = 300
    ) -> dict[str, Any]:
        del cwd, timeout
        assert command[:3] == ["docker", "rm", "-f"]
        raise runner.DG13URunnerError("synthetic cleanup retry failed")

    monkeypatch.setattr(runner, "_probe_openworker", probe_with_pending_container)
    monkeypatch.setattr(runner, "_run_command", cleanup_retry_fails)
    run_id = "identity-cleanup-failure"
    report = runner.run_identity_readiness(run_id, CASE_ID)
    run_dir = runs / run_id

    assert report["status"] == "FAIL"
    assert not (temporary / run_id).exists()
    cleanup = json.loads((run_dir / "cleanup-receipt.json").read_text())
    assert cleanup["status"] == "FAIL"
    assert cleanup["reason_code"] == "INSPECTION_CONTAINER_CLEANUP_FAILED"
    container = next(item for item in cleanup["items"] if item["kind"] == "container")
    assert container["state"] == "cleanup_failed"
    assert container["retry"]["attempted"] is True
    assert container["retry"]["status"] == "FAIL"
    trace = [
        json.loads(line)
        for line in (run_dir / "stage-trace.jsonl").read_text().splitlines()
    ]
    assert trace[-1]["stage"] == "CLEANUP"
    assert trace[-1]["status"] == "FAIL"


def test_probe_failure_fails_closed_and_cleanup_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    _mock_success_probes(monkeypatch)

    def unavailable(_packages: dict[str, Any]) -> dict[str, Any]:
        raise runner.DG13URunnerError("Runtime unavailable")

    monkeypatch.setattr(runner, "_probe_runtime", unavailable)
    run_id = "identity-case-0004"
    report = runner.run_identity_readiness(run_id, CASE_ID)
    run_dir = runs / run_id

    assert report["status"] == "FAIL"
    assert report["error"]["type"] == "DG13URunnerError"
    assert not (temporary / run_id).exists()
    assert (run_dir / "cleanup-receipt.json").is_file()
    trace = [
        json.loads(line)
        for line in (run_dir / "stage-trace.jsonl").read_text().splitlines()
    ]
    assert next(row for row in trace if row["stage"] == "RUNTIME")["status"] == "FAIL"
    assert (
        next(row for row in trace if row["stage"] == "PROVIDER")["status"] == "NOT_RUN"
    )
    assert trace[-1]["stage"] == "CLEANUP"
    assert trace[-1]["status"] == "PASS"


def test_existing_run_or_temp_root_fails_before_probes_without_deleting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    run_id = "identity-case-0005"
    owned_elsewhere = temporary / run_id
    owned_elsewhere.mkdir(parents=True)
    marker = owned_elsewhere / "do-not-delete"
    marker.write_text("external", encoding="utf-8")

    def forbidden() -> dict[str, Any]:
        raise AssertionError("probe reached")

    monkeypatch.setattr(runner, "_collect_source_identity", forbidden)
    with pytest.raises(runner.DG13URunnerError, match="already exists"):
        runner.run_identity_readiness(run_id, CASE_ID)
    assert marker.read_text(encoding="utf-8") == "external"
    assert not (runs / run_id).exists()


def test_package_build_and_fresh_installs_inherit_run_owned_cra_cache_and_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_roots(tmp_path, monkeypatch)
    run_dir = runner.RUNS_ROOT / "identity-case-0006"
    temp_dir = runner.TMP_ROOT / "identity-case-0006"
    run_dir.mkdir(parents=True, mode=0o700)
    temp_dir.mkdir(parents=True, mode=0o700)
    runner.UV_BUILD_CACHE_SEED.mkdir(parents=True, mode=0o700)
    (runner.UV_BUILD_CACHE_SEED / "seed-marker").write_bytes(b"offline-build-seed")
    seen: list[tuple[str, str]] = []
    commands: list[list[str]] = []

    def fake_command(
        command: list[str], *, cwd: Path, timeout: int = 300
    ) -> dict[str, Any]:
        del cwd, timeout
        seen.append((os.environ["TMPDIR"], os.environ["UV_CACHE_DIR"]))
        commands.append(command)
        if command[:2] == ["uv", "build"]:
            output = Path(command[command.index("--out-dir") + 1])
            project = output.name
            distribution = {
                "client": "milai_client",
                "mcp": "milai_mcp",
                "runtime": "milai_runtime",
                "openworker": "milai_openworker_mcp",
            }[project]
            (output / f"{distribution}-0.1.0-py3-none-any.whl").write_bytes(
                f"{project}-wheel".encode()
            )
            (output / f"{distribution}-0.1.0.tar.gz").write_bytes(
                f"{project}-sdist".encode()
            )
        return {
            "argv_sha256": "a" * 64,
            "status": "PASS",
            "exit_code": 0,
        }

    monkeypatch.setattr(runner, "_run_command", fake_command)
    monkeypatch.setattr(
        runner,
        "_installed_identity",
        lambda _venv: {
            "inspection": "IMPORTLIB_METADATA_ONLY_NO_PRODUCT_MODULE_IMPORT",
            "distributions": {},
            "entrypoints": {},
        },
    )
    monkeypatch.setattr(
        runner,
        "_archive_identity",
        lambda path: {
            "member_count": 3,
            "member_bytes": 3,
            "members_sha256": "b" * 64,
            "member_names": (
                [
                    "milai_openworker_mcp/host_adapter.py",
                    "milai_openworker_mcp/broker.py",
                    "milai_openworker_mcp/relay.py",
                ]
                if "openworker" in str(path)
                else ["package/METADATA"]
            ),
        },
    )
    monkeypatch.setattr(
        runner,
        "_migration_head_from_archive",
        lambda _path: "0028_dg11_window_projection",
    )
    old_tmp = os.environ.get("TMPDIR")
    old_uv = os.environ.get("UV_CACHE_DIR")
    result = runner._build_and_probe_packages(run_dir, temp_dir)

    expected = (str(temp_dir / "build-tmp"), str(temp_dir / "uv-cache"))
    assert seen and all(value == expected for value in seen)
    assert result["build_environment"]["TMPDIR"] == expected[0]
    assert result["build_environment"]["UV_CACHE_DIR"] == expected[1]
    assert result["build_environment"]["on_cra"] is True
    assert len(result["build_environment"]["offline_cache_seed"]["sha256"]) == 64
    assert os.environ.get("TMPDIR") == old_tmp
    assert os.environ.get("UV_CACHE_DIR") == old_uv
    assert len(result["artifacts"]) == 8
    assert sum(command[:2] == ["uv", "build"] for command in commands) == 4
    assert all(
        "--offline" in command for command in commands if command[:2] == ["uv", "build"]
    )
    install = next(
        command for command in commands if command[:3] == ["uv", "pip", "install"]
    )
    assert "--no-deps" in install
    assert "--offline" in install
    assert result["install_policy"] == "UV_PIP_INSTALL_NO_DEPS"
    assert all(
        stat.S_IMODE((run_dir / row["path"]).stat().st_mode) == 0o600
        for row in result["artifacts"].values()
    )


def test_archive_identity_and_migration_head_are_derived_from_package_bytes(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "milai_runtime-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("milai/_migrations/versions/0001_first.py", _MIGRATION_1)
        archive.writestr("milai/_migrations/versions/0002_second.py", _MIGRATION_2)
        archive.writestr("milai_runtime-0.1.0.dist-info/METADATA", b"Version: 0.1.0\n")

    sdist = tmp_path / "milai_runtime-0.1.0.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        for name, raw in (
            ("milai_runtime-0.1.0/migrations/versions/0001_first.py", _MIGRATION_1),
            ("milai_runtime-0.1.0/migrations/versions/0002_second.py", _MIGRATION_2),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))

    assert runner._migration_head_from_archive(wheel) == "0002_second"
    assert runner._migration_head_from_archive(sdist) == "0002_second"
    wheel_identity = runner._archive_identity(wheel)
    assert wheel_identity["member_count"] == 3
    assert len(wheel_identity["members_sha256"]) == 64


def test_baked_image_probe_compares_current_bytes_and_removes_inspection_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_command(
        command: list[str], *, cwd: Path = runner.ROOT, timeout: int = 300
    ) -> dict[str, Any]:
        del cwd, timeout
        commands.append(command)
        if command[:2] == ["docker", "cp"]:
            destination = Path(command[-1])
            destination.write_bytes(
                b"stale-config"
                if destination.name == "opencode.json"
                else b"stale-relay"
            )
        return {"status": "PASS", "exit_code": 0, "argv_sha256": "a" * 64}

    current_relay = runner.OPENWORKER_PROJECT / "src/milai_openworker_mcp/relay.py"
    monkeypatch.setattr(runner, "_run_command", fake_command)
    monkeypatch.setattr(
        runner,
        "_archive_member_identity",
        lambda _path, _suffix: {
            "path": "milai_openworker_mcp/relay.py",
            "bytes": current_relay.stat().st_size,
            "sha256": runner._sha256_file(current_relay),
        },
    )
    run_dir = tmp_path / "run"
    temp_dir = tmp_path / "temp"
    run_dir.mkdir()
    temp_dir.mkdir()
    value = runner._inspect_baked_openworker(
        "identity-case-0007", run_dir, temp_dir, tmp_path / "current.whl"
    )

    assert value["relation"] == {
        "relay": "STALE",
        "config": "STALE",
        "status": "STALE",
    }
    assert value["inspection_container"]["started"] is False
    assert value["inspection_container"]["removed"] is True
    assert any(command[:2] == ["docker", "create"] for command in commands)
    assert commands[-1][:3] == ["docker", "rm", "-f"]
    receipt = json.loads((run_dir / "baked-inspection-receipt.json").read_text())
    assert receipt["created"] is True
    assert receipt["removed"] is True


def test_source_inventory_paths_are_unique_and_include_current_provider_contract() -> (
    None
):
    paths = [
        path.relative_to(runner.ROOT).as_posix() for path in runner._source_files()
    ]
    assert len(paths) == len(set(paths))
    assert "contracts/agent/v1/dg13u-current-provider-inventory.md" in paths
    assert "contracts/agent/v1/dg13u-u1-candidate-fixture.json" in paths


def test_baked_probe_failure_still_removes_owned_container_and_writes_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_command(
        command: list[str], *, cwd: Path = runner.ROOT, timeout: int = 300
    ) -> dict[str, Any]:
        del cwd, timeout
        commands.append(command)
        if command[:2] == ["docker", "cp"]:
            raise runner.DG13URunnerError("copy failed")
        return {"status": "PASS", "exit_code": 0, "argv_sha256": "a" * 64}

    run_dir = tmp_path / "run"
    temp_dir = tmp_path / "temp"
    run_dir.mkdir()
    temp_dir.mkdir()
    monkeypatch.setattr(runner, "_run_command", fake_command)
    with pytest.raises(runner.DG13URunnerError, match="copy failed"):
        runner._inspect_baked_openworker(
            "identity-case-0008", run_dir, temp_dir, tmp_path / "current.whl"
        )

    assert commands[-1][:3] == ["docker", "rm", "-f"]
    receipt = json.loads((run_dir / "baked-inspection-receipt.json").read_text())
    assert receipt["created"] is True
    assert receipt["started"] is False
    assert receipt["removed"] is True
    assert receipt["probe_error_type"] == "DG13URunnerError"


def test_task_producer_readiness_is_derived_from_exact_baked_bytes(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "openworker.js"
    entrypoint = tmp_path / "entrypoint.sh"
    config = tmp_path / "opencode.json"
    entrypoint.write_text("#!/bin/sh\nopencode serve\n", encoding="utf-8")
    config.write_text('{"provider":{"openworker":{}}}\n', encoding="utf-8")
    plugin.write_text(" ".join(runner._TASK_PRODUCER_MARKERS) + "\n", encoding="utf-8")

    ready = runner._task_producer_readiness(plugin, entrypoint, config)
    assert ready["status"] == "READY"
    assert ready["observed_marker_count"] == len(runner._TASK_PRODUCER_MARKERS)
    assert ready["native_evidence_sha256"]

    plugin.write_text(
        "// exact plugin has no MiLAi task metadata producer\n", encoding="utf-8"
    )
    absent = runner._task_producer_readiness(plugin, entrypoint, config)
    assert absent["status"] == "ABSENT"
    assert absent["observed_marker_count"] == 0

    plugin.write_text("sessionID\n", encoding="utf-8")
    unrelated_session_surface = runner._task_producer_readiness(
        plugin, entrypoint, config
    )
    assert unrelated_session_surface["status"] == "ABSENT"
    assert unrelated_session_surface["observed_marker_count"] == 1

    plugin.write_text("chat.headers sessionID\n", encoding="utf-8")
    partial = runner._task_producer_readiness(plugin, entrypoint, config)
    assert partial["status"] == "PARTIAL"


def test_task_producer_markers_are_the_candidate_wire_contract() -> None:
    assert runner._TASK_PRODUCER_MARKERS == (
        "chat.headers",
        "X-MiLAi-Host-Instance",
        "X-MiLAi-Task-Session",
        "X-MiLAi-Task-Operation",
        "sessionID",
        "message.id",
    )
