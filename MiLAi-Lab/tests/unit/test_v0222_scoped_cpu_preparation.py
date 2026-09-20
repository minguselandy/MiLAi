"""Read-only real matrix derivation; not an initialized or executed CPU batch."""

import ast
import inspect
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import prepare_v0222_presentation_v2 as live
import prepare_v0222_scoped_cpu as cpu
from v0218_world import digest
from v0220_evidence import read
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_audit import initial_for
from v0222_scoped_cpu_batch import OfflineBatch


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU_PREPARATION_READ_ONLY")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.mark.skipif(
    not (cpu.PRESENTATION_ROOT / "manifest.json").is_file(),
    reason="external historical V0222 presentation evidence is not part of the Git checkout",
)
def test_real_complete_matrix_has_distinct_cpu_scopes_and_original_business_values():
    original = read(cpu.PRESENTATION_ROOT / "manifest.json")["contract"]
    with AdmissionReadScope() as scope:
        current = cpu.episode_specs(scope)
        planned_live = live.episode_specs(scope)
    assert scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
    assert [len(current[stage]) for stage in ("P3", "P4")] == [16, 24]
    ids, scopes = set(), set()
    for stage in ("P3", "P4"):
        for index, (old, replay, planned) in enumerate(
            zip(original[stage], current[stage], planned_live[stage], strict=True), 1
        ):
            allowed = {"id", "scope"}
            if stage == "P4":
                allowed.add("initial_state_sha256")
                assert digest(initial_for(replay)) == replay["initial_state_sha256"]
                assert replay["initial_state_sha256"] not in {
                    old["initial_state_sha256"],
                    planned["initial_state_sha256"],
                }
            assert {k: v for k, v in old.items() if k not in allowed} == {
                k: v for k, v in replay.items() if k not in allowed
            }
            assert replay["id"] == f"cpu-{stage.lower()}-{index:02d}"
            assert replay["id"] not in {old["id"], planned["id"]}
            assert replay["scope"] not in {old["scope"], planned["scope"]}
            ids.add(replay["id"])
            scopes.add(replay["scope"])
    assert len(ids) == len(scopes) == 40


def test_plan_derivation_diff_is_only_explicit_cpu_id_and_scope_prefixes():
    source = inspect.getsource(cpu.episode_specs)
    source = source.replace(
        'f"cpu-{stage.lower()}-{index:02d}"', 'f"scoped-{stage.lower()}-{index:02d}"'
    )
    source = source.replace('f"v0222-cpu-20260912-', 'f"v0222-scoped-20260912-')
    assert ast.dump(ast.parse(source)) == ast.dump(ast.parse(inspect.getsource(live.episode_specs)))


def test_actual_preparation_reuses_complete_materializer_and_cpu_constructor():
    assert cpu.materialize_references is live.materialize_references
    assert cpu.Batch is OfflineBatch
    current = ast.parse(textwrap.dedent(inspect.getsource(cpu.prepare)))
    first = current.body[0].body.pop(0)
    assert isinstance(first, ast.Expr) and first.value.func.id == "require_cpu_network_guard"
    assert ast.dump(current) == ast.dump(ast.parse(inspect.getsource(live.prepare)))


@pytest.mark.parametrize("operation", ["unguarded", "help", "invalid_root"])
def test_preparation_entry_refuses_invalid_use_in_fresh_child(tmp_path, operation):
    lab = Path(__file__).resolve().parents[2]
    root = tmp_path / "not-created"
    if operation == "unguarded":
        code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from prepare_v0222_scoped_cpu import prepare
try:
    prepare(Path(sys.argv[2]), '0' * 64)
except RuntimeError as exc:
    assert str(exc) == 'FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED'
else:
    raise AssertionError('unguarded preparation accepted')
"""
        command = [sys.executable, "-c", code, str(lab / "tools"), str(root)]
    else:
        command = [sys.executable, str(lab / "tools/run_v0222_scoped_cpu_prepare.py")]
        command += (
            ["--help"]
            if operation == "help"
            else ["--root", str(root), "--binding-sha256", "0" * 64]
        )
    result = subprocess.run(  # noqa: S603 -- Fixed local refusal/help scripts, never a run.
        command, capture_output=True, text=True, timeout=30, cwd=lab
    )
    if operation == "invalid_root":
        assert result.returncode != 0
        assert "ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
    assert not root.exists()
