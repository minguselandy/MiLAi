from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import dg13u_u1_cleanup as cleanup

RUN_ID = "dg13u-u1-recovery-test"
DB_NAME = "milai_smoke_dg13u_4d7c5efb07aab7777153"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
IDENTITY_SHA = "a" * 64


class FakeBackend:
    def __init__(self) -> None:
        self.markers: dict[int, str] = {101: "9001"}
        self.docker: dict[tuple[str, str], dict[str, str]] = {
            ("network", "milai-dg13u-u1-net-test"): {cleanup.RUN_LABEL: RUN_ID},
            ("container", "milai-dg13u-u1-worker-test"): {
                cleanup.RUN_LABEL: RUN_ID
            },
        }
        self.databases = {DB_NAME: "milai_owner"}
        self.vllm_matches = True
        self.actions: list[tuple[Any, ...]] = []
        self.fail_kind: str | None = None

    def process_marker(self, pid: int) -> str | None:
        return self.markers.get(pid)

    def docker_labels(self, kind: str, name: str) -> dict[str, str] | None:
        return self.docker.get((kind, name))

    def database_owner(self, owner_dsn: str, database_name: str) -> str | None:
        assert owner_dsn == "postgresql://synthetic-owner.invalid/postgres"
        return self.databases.get(database_name)

    def external_vllm_matches(self, origin: str, model_id: str) -> bool:
        assert origin == "http://127.0.0.1:7860"
        assert model_id == MODEL_ID
        return self.vllm_matches

    def _record(self, kind: str, *identity: object) -> None:
        self.actions.append((kind, *identity))
        if self.fail_kind == kind:
            raise RuntimeError("synthetic cleanup failure containing private-body")

    def terminate_process(self, pid: int, marker: str) -> None:
        self._record("process", pid, marker)

    def remove_container(self, name: str) -> None:
        self._record("docker_container", name)

    def remove_network(self, name: str) -> None:
        self._record("docker_network", name)

    def drop_database(self, owner_dsn: str, database_name: str) -> None:
        assert owner_dsn == "postgresql://synthetic-owner.invalid/postgres"
        self._record("database", database_name)

    def remove_directory(self, path: Path) -> None:
        self._record(
            "temporary_root" if path.parent == cleanup.TMP_ROOT else "uds_root",
            str(path),
        )


@pytest.fixture
def owned_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    root = tmp_path / "repo"
    runs = root / "var/dg13/runs"
    temporary = root / "var/dg13/tmp"
    uds = tmp_path / "dev-shm-milai"
    for path in (runs, temporary, uds):
        path.mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "RUNS_ROOT", runs)
    monkeypatch.setattr(cleanup, "TMP_ROOT", temporary)
    monkeypatch.setattr(cleanup, "UDS_ROOT", uds)
    run_dir = runs / RUN_ID
    temp_root = temporary / RUN_ID
    uds_root = uds / cleanup._short_run_id(RUN_ID)
    for path in (run_dir, temp_root, uds_root):
        path.mkdir(mode=0o700)
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        "MILAI_MIGRATION_DATABASE_URL="
        "postgresql://synthetic-owner.invalid/postgres\n",
        encoding="utf-8",
    )
    os.chmod(env_file, 0o600)
    return {
        "run_dir": run_dir,
        "temp_root": temp_root,
        "uds_root": uds_root,
        "env_file": env_file,
        "plan": run_dir / cleanup.PLAN_NAME,
        "receipt": run_dir / cleanup.RECEIPT_NAME,
    }


def resources(paths: dict[str, Path]) -> list[dict[str, object]]:
    return [
        {
            "kind": "external_vllm",
            "ownership": "PRESERVED_EXTERNAL",
            "origin": "http://127.0.0.1:7860",
            "model_id": MODEL_ID,
            "identity_sha256": IDENTITY_SHA,
        },
        {
            "kind": "temporary_root",
            "ownership": "RUN_OWNED",
            "path": str(paths["temp_root"]),
        },
        {
            "kind": "uds_root",
            "ownership": "RUN_OWNED",
            "path": str(paths["uds_root"]),
        },
        {
            "kind": "database",
            "ownership": "RUN_OWNED",
            "database_name": DB_NAME,
            "owner_dsn_ref": "MILAI_MIGRATION_DATABASE_URL",
        },
        {
            "kind": "docker_network",
            "ownership": "RUN_OWNED",
            "name": "milai-dg13u-u1-net-test",
            "required_labels": {cleanup.RUN_LABEL: RUN_ID},
        },
        {
            "kind": "process",
            "ownership": "RUN_OWNED",
            "role": "runtime-api",
            "pid": 101,
            "proc_start_marker": "9001",
        },
        {
            "kind": "docker_container",
            "ownership": "RUN_OWNED",
            "name": "milai-dg13u-u1-worker-test",
            "required_labels": {cleanup.RUN_LABEL: RUN_ID},
        },
    ]


def write_plan(paths: dict[str, Path]) -> dict[str, Any]:
    return cleanup.write_resource_plan(
        paths["plan"],
        run_id=RUN_ID,
        run_dir=paths["run_dir"],
        resources=resources(paths),
    )


def test_plan_initial_write_is_atomic_private_and_blind_overwrite_is_rejected(
    owned_paths: dict[str, Path],
) -> None:
    result = write_plan(owned_paths)

    assert stat.S_IMODE(owned_paths["plan"].stat().st_mode) == 0o600
    assert result["sha256"] == cleanup._sha256_bytes(owned_paths["plan"].read_bytes())
    with pytest.raises(cleanup.CleanupError, match="overwrite"):
        write_plan(owned_paths)


def test_plan_update_requires_exact_previous_digest_and_records_pid_marker(
    owned_paths: dict[str, Path],
) -> None:
    initial_resources = [
        row for row in resources(owned_paths) if row["kind"] != "process"
    ]
    first = cleanup.write_resource_plan(
        owned_paths["plan"],
        run_id=RUN_ID,
        run_dir=owned_paths["run_dir"],
        resources=initial_resources,
    )
    with pytest.raises(cleanup.CleanupError, match="compare-and-swap"):
        cleanup.write_resource_plan(
            owned_paths["plan"],
            run_id=RUN_ID,
            run_dir=owned_paths["run_dir"],
            resources=resources(owned_paths),
            expected_previous_sha256="b" * 64,
        )

    updated = cleanup.write_resource_plan(
        owned_paths["plan"],
        run_id=RUN_ID,
        run_dir=owned_paths["run_dir"],
        resources=resources(owned_paths),
        expected_previous_sha256=first["sha256"],
    )

    assert updated["sha256"] != first["sha256"]
    value = json.loads(owned_paths["plan"].read_text())
    process = next(row for row in value["resources"] if row["kind"] == "process")
    assert process["pid"] == 101
    assert process["proc_start_marker"] == "9001"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows.append({"kind": "unknown"}), "unknown"),
        (lambda rows: rows.append(dict(rows[0])), "duplicate"),
        (lambda rows: rows[3].pop("owner_dsn_ref"), "missing or unknown"),
        (lambda rows: rows[3].update(owner_dsn_ref="postgresql://secret"), "incomplete"),
        (
            lambda rows: rows[3].update(
                database_name="milai_smoke_dg13u_0123456789abcdef0123"
            ),
            "incomplete",
        ),
        (lambda rows: rows[5].update(role="unknown-role"), "incomplete"),
    ],
)
def test_plan_rejects_unknown_duplicate_partial_and_embedded_dsn(
    owned_paths: dict[str, Path], mutation: Any, message: str
) -> None:
    rows = resources(owned_paths)
    mutation(rows)
    with pytest.raises(cleanup.CleanupError, match=message):
        cleanup.write_resource_plan(
            owned_paths["plan"],
            run_id=RUN_ID,
            run_dir=owned_paths["run_dir"],
            resources=rows,
        )


def test_plan_rejects_path_escape_and_symlink_plan(
    owned_paths: dict[str, Path], tmp_path: Path
) -> None:
    rows = resources(owned_paths)
    rows[1]["path"] = str(tmp_path / "outside")
    with pytest.raises(cleanup.CleanupError, match="exact parent"):
        cleanup.write_resource_plan(
            owned_paths["plan"],
            run_id=RUN_ID,
            run_dir=owned_paths["run_dir"],
            resources=rows,
        )
    target = tmp_path / "target"
    target.write_text("{}", encoding="utf-8")
    owned_paths["plan"].symlink_to(target)
    with pytest.raises(cleanup.CleanupError, match="overwrite"):
        write_plan(owned_paths)


@pytest.mark.parametrize("mismatch", ["pid", "docker", "database", "vllm", "path"])
def test_any_preflight_identity_mismatch_causes_zero_destructive_calls(
    owned_paths: dict[str, Path], mismatch: str
) -> None:
    write_plan(owned_paths)
    backend = FakeBackend()
    if mismatch == "pid":
        backend.markers[101] = "different"
    elif mismatch == "docker":
        backend.docker[("container", "milai-dg13u-u1-worker-test")] = {
            cleanup.RUN_LABEL: "some-other-run"
        }
    elif mismatch == "database":
        backend.databases[DB_NAME] = "attacker"
    elif mismatch == "vllm":
        backend.vllm_matches = False
    else:
        owned_paths["uds_root"].rmdir()
        owned_paths["uds_root"].write_text("not-a-directory", encoding="utf-8")

    receipt = cleanup.cleanup_from_plan(
        owned_paths["plan"],
        run_id=RUN_ID,
        env_file=owned_paths["env_file"],
        execute_local=True,
        backend=backend,
    )

    assert receipt["status"] == "FAIL"
    assert receipt["phase"] == "preflight"
    assert receipt["reason_code"] == "RECOVERY_PREFLIGHT_REJECTED"
    assert backend.actions == []
    assert stat.S_IMODE(owned_paths["receipt"].stat().st_mode) == 0o600


def test_cleanup_runs_once_in_exact_reverse_order_and_preserves_external_vllm(
    owned_paths: dict[str, Path],
) -> None:
    write_plan(owned_paths)
    backend = FakeBackend()

    receipt = cleanup.cleanup_from_plan(
        owned_paths["plan"],
        run_id=RUN_ID,
        env_file=owned_paths["env_file"],
        execute_local=True,
        backend=backend,
    )

    assert receipt["status"] == "PASS"
    assert receipt["automatic_retries"] == 0
    assert receipt["external_lifecycle_mutations"] == 0
    assert [action[0] for action in backend.actions] == [
        "docker_container",
        "process",
        "docker_network",
        "database",
        "uds_root",
        "temporary_root",
    ]
    external = next(row for row in receipt["items"] if row["kind"] == "external_vllm")
    assert external == {
        "kind": "external_vllm",
        "ownership": "PRESERVED_EXTERNAL",
        "state": "preserved_external",
        "attempts": 0,
    }


def test_already_absent_resources_are_not_called(
    owned_paths: dict[str, Path],
) -> None:
    write_plan(owned_paths)
    backend = FakeBackend()
    backend.markers.clear()
    backend.docker.clear()
    backend.databases.clear()
    owned_paths["temp_root"].rmdir()
    owned_paths["uds_root"].rmdir()

    receipt = cleanup.cleanup_from_plan(
        owned_paths["plan"],
        run_id=RUN_ID,
        env_file=owned_paths["env_file"],
        execute_local=True,
        backend=backend,
    )

    assert receipt["status"] == "PASS"
    assert backend.actions == []
    assert all(
        row["attempts"] == 0
        for row in receipt["items"]
        if row["kind"] != "external_vllm"
    )


def test_action_failure_is_redacted_recorded_once_and_does_not_trigger_retry(
    owned_paths: dict[str, Path],
) -> None:
    write_plan(owned_paths)
    backend = FakeBackend()
    backend.fail_kind = "docker_container"

    receipt = cleanup.cleanup_from_plan(
        owned_paths["plan"],
        run_id=RUN_ID,
        env_file=owned_paths["env_file"],
        execute_local=True,
        backend=backend,
    )

    assert receipt["status"] == "FAIL"
    assert backend.actions.count(("docker_container", "milai-dg13u-u1-worker-test")) == 1
    assert "private-body" not in owned_paths["receipt"].read_text()
    failed = next(row for row in receipt["items"] if row["kind"] == "docker_container")
    assert failed["error_type"] == "RuntimeError"
    assert failed["attempts"] == 1


def test_execute_local_and_absolute_arguments_are_mandatory(
    owned_paths: dict[str, Path],
) -> None:
    write_plan(owned_paths)
    with pytest.raises(cleanup.CleanupError, match="execute_local"):
        cleanup.cleanup_from_plan(
            owned_paths["plan"],
            run_id=RUN_ID,
            env_file=owned_paths["env_file"],
            execute_local=False,
            backend=FakeBackend(),
        )
    with pytest.raises(cleanup.CleanupError, match="absolute"):
        cleanup.cleanup_from_plan(
            Path("relative-plan.json"),
            run_id=RUN_ID,
            env_file=owned_paths["env_file"],
            execute_local=True,
            backend=FakeBackend(),
        )


def test_cli_help_does_not_touch_resources() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/dg13u_u1_cleanup.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--execute-local" in completed.stdout
    assert "--plan" in completed.stdout
    assert "--env-file" in completed.stdout
