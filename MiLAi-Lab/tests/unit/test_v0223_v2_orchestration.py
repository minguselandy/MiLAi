"""V2 bindings and wiring only; never create or time a real fixture."""

import ast
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import assemble_v0223_k0_v2 as assembly
import prepare_v0223_measurement_fixture as fixture_v1
import prepare_v0223_measurement_fixture_v2 as fixture_v2
import run_v0223_admission_pair_v2 as worker
import v0223_cpu_batch as binding_v1
import v0223_cpu_batch_v2 as binding_v2
from v0220_provider_hardened import ProviderStop

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def test_v2_binding_refuses_v1_root_and_preserves_original_caps(monkeypatch):
    monkeypatch.setenv("MILA_V0223_INSTANCE", "k1-u1")
    root = binding_v2.selected_root()
    assert root.name == "v2-k1-u1" and root.parent == binding_v2.CPU_BASE
    assert root != binding_v1.selected_root()
    history = {"sources": [], "unresolved_reservations": [{"unknown": True}]}
    arguments = {"issued": 100, "expires": 200, "history": history}
    old = binding_v1.make_cpu_authorization(binding_v1.selected_root(), **arguments)
    new = binding_v2.make_cpu_authorization(root, **arguments)
    assert {k for k in new if new[k] != old[k]} == {"root", "batch_id", "coordinator_revision"}
    with pytest.raises(ProviderStop, match="CANONICAL_CPU"):
        binding_v2.make_cpu_authorization(binding_v1.selected_root(), **arguments)


@pytest.mark.parametrize("name", ["v2-k1-u1", "../k1-u1", "", "k1-u4"])
def test_v2_only_accepts_frozen_instance_selector(monkeypatch, name):
    monkeypatch.setenv("MILA_V0223_INSTANCE", name)
    with pytest.raises(ProviderStop, match="FROZEN_V0223_INSTANCE"):
        binding_v2.selected_root()


def test_v2_batch_code_and_dynamic_methods_are_unchanged():
    assert ast.dump(ast.parse(inspect.getsource(binding_v1.OfflineBatch))) == ast.dump(
        ast.parse(inspect.getsource(binding_v2.OfflineBatch))
    )
    own = {"__init__", "_authorize"}
    for name in dir(binding_v1.OfflineBatch):
        previous = getattr(binding_v1.OfflineBatch, name)
        if name not in own and inspect.isfunction(previous):
            assert getattr(binding_v2.OfflineBatch, name) is previous


@pytest.mark.parametrize("name", ["_public_inputs", "_require_fresh_root", "_check_sealed_pins"])
def test_transitive_public_pin_and_seal_guards_not_relaxed(name):
    before, after = getattr(fixture_v1, name), getattr(fixture_v2, name)
    assert ast.dump(ast.parse(inspect.getsource(before))) == ast.dump(
        ast.parse(inspect.getsource(after))
    )


def test_fixture_entries_bind_actual_v2_executables_and_keep_old_closure():
    source = inspect.getsource(fixture_v2.prepare)
    strings = {
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    expected = {
        "v0223_cpu_batch_v2.py",
        "v0223_coarse_observation.py",
        "prepare_v0223_measurement_fixture_v2.py",
        "run_v0223_admission_pair_v2.py",
        "v0223_reference_prefix_v2.py",
        "run_v0223_calibration_v2.py",
        "inventory_v0223_fixture_v2.py",
    }
    assert expected <= strings
    assert 'entries.extend(Path(name) for name in original["dependencies"])' in source
    assert 'OLD_ROOT / "executed-source"' in source
    assert 'inputs.update(Path(name) for name in original["dependencies"])' in source
    assert "ONLY_K1_PREPARATION_NOT_K3_SEAL" in strings


def test_worker_passes_strict_U_mode_to_only_v2_helper():
    tree = ast.parse((TOOLS / "run_v0223_admission_pair_v2.py").read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "v0223_reference_prefix_v2" in imports
    assert "v0223_reference_prefix" not in imports
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_reference_prefix"
    ]
    assert len(calls) == 1
    timing = next(k.value for k in calls[0].keywords if k.arg == "observe_internal_timing")
    assert ast.dump(timing) == ast.dump(ast.parse('args.mode == "S"', mode="eval").body)


def test_parent_selects_actual_v2_worker_and_order_unchanged():
    tree = ast.parse((TOOLS / "run_v0223_calibration_v2.py").read_text())
    strings = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "tools/run_v0223_admission_pair_v2.py" in strings
    assert "tools/run_v0223_admission_pair.py" not in strings
    assert worker.CALIBRATION_ORDER == (
        ("k1-u1", "U"),
        ("k1-s1", "S"),
        ("k1-s2", "S"),
        ("k1-u2", "U"),
        ("k1-u3", "U"),
        ("k1-s3", "S"),
    )


def test_assembler_uses_v2_basename_for_mechanical_id_mapping():
    value = {
        stage: [
            {
                "id": f"v2-k1-u1-{stage.lower()}-{i:02d}",
                "scope": f"v0223-v2-k1-u1-{stage.lower()}-{i:02d}",
                "root": "synthetic",
                "initial_state_sha256": "verified",
            }
            for i in range(1, count + 1)
        ]
        for stage, count in (("P3", 16), ("P4", 24))
    }
    normalized = assembly.normalize_plan(
        value, "v2-k1-u1", {"synthetic": {}}, lambda spec, public: (spec, {})
    )
    assert normalized["P4"][0]["id"] == "<INSTANCE>-p4-01"
    with pytest.raises(ValueError, match="MECHANICAL_ID"):
        assembly.normalize_plan(value, "k1-u1", {"synthetic": {}}, lambda spec, public: (spec, {}))
