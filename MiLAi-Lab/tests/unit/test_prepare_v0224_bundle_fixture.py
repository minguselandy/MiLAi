"""Pure fixture admission boundaries; no real preparation or network guard install."""

import ast
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import prepare_v0224_bundle_fixture as prepare


def test_fresh_root_refuses_existing_alias_and_parent_traversal(tmp_path):
    fresh = tmp_path / "new"
    prepare._require_fresh_root(fresh)
    fresh.mkdir()
    with pytest.raises(ValueError, match="FRESH"):
        prepare._require_fresh_root(fresh)
    alias = tmp_path / "alias"
    alias.symlink_to(fresh, target_is_directory=True)
    with pytest.raises(ValueError, match="CANONICAL"):
        prepare._require_fresh_root(alias)
    with pytest.raises(ValueError, match="CANONICAL"):
        prepare._require_fresh_root(fresh / ".." / "other")


def test_source_or_input_drift_after_close_refuses():
    inputs = {"/input": "a" * 64}
    sources = {"/source": "b" * 64}
    manifest = {"inputs": copy.deepcopy(inputs), "dependencies": copy.deepcopy(sources)}
    prepare._check_sealed_pins(manifest, inputs, sources)
    manifest["dependencies"]["/source"] = "c" * 64
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        prepare._check_sealed_pins(manifest, inputs, sources)
    manifest["inputs"]["/input"] = "d" * 64
    with pytest.raises(ValueError, match="INPUT_CHANGED"):
        prepare._check_sealed_pins(manifest, inputs, sources)


def test_all_required_sources_include_future_runner_and_refuse_missing(tmp_path):
    assert "run_v0224_bundle_reference_slice.py" in prepare.REQUIRED_TOOLS
    assert {
        "v0224_static_bundle.py",
        "v0224_bundle_read_scope.py",
        "v0224_bundle_lineage.py",
        "v0224_bundle_cpu_batch.py",
        "v0224_bundle_revalidation.py",
        "v0224_reference_outer_bounds.py",
        "prepare_v0224_bundle_fixture.py",
    } <= set(prepare.REQUIRED_TOOLS)
    for name in prepare.REQUIRED_TOOLS:
        path = tmp_path / "tools" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("# synthetic")
    for name in prepare.REQUIRED_TESTS:
        path = tmp_path / "tests/unit" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic")
    assert len(prepare._required_entries(tmp_path)) == len(prepare.REQUIRED_TOOLS) + len(
        prepare.REQUIRED_TESTS
    )
    (tmp_path / "tools/run_v0224_bundle_reference_slice.py").unlink()
    with pytest.raises(ValueError, match="REQUIRED_R03_SOURCE_MISSING"):
        prepare._required_entries(tmp_path)


@pytest.mark.parametrize("change", ["stop", "count", "running", "events"])
def test_exact_empty_initialized_state(change):
    snapshot = {"stop": None, "episodes": [{"status": "PENDING"} for _ in range(40)]}
    prepare._check_initialized_state(snapshot, [])
    events = []
    if change == "stop":
        snapshot["stop"] = "FAIL"
    elif change == "count":
        snapshot["episodes"].pop()
    elif change == "running":
        snapshot["episodes"][0]["status"] = "RUNNING"
    else:
        events = [{"event": "RESERVED"}]
    with pytest.raises(ValueError, match="40_PENDING_EMPTY_EVENT"):
        prepare._check_initialized_state(snapshot, events)


def test_preparation_source_explicit_authority_and_no_approval_generation():
    source = Path(prepare.__file__).read_text()
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = {n.func.id for n in calls if isinstance(n.func, ast.Name)}
    assert "seal_static_bundle" not in names and "revalidate_candidate" not in names
    assert "installed_candidate" not in names
    assert "BundleReadScope" in names and "verify_lineage_r03" in names
    assert (
        "static_authority.bundle_sha256" in source and "static_authority.receipt_sha256" in source
    )
    assert 'plan["static_authority"] = static_authority.contract_value()' in source
    assert "a72effffc756a8ee237304e3672cc35bd43e4c3a4dcb4afca1b5a284ff3577a6" in source
    assert 'prior_root / "execution-binding.json"' in source
    assert "scope.physical_reads()" in source
