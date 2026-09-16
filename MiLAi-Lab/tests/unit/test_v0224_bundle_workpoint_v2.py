"""Versioned root/route deltas and public-pin regression, synthetic only."""

import ast
import hashlib
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import prepare_v0224_bundle_fixture as old_fixture
import prepare_v0224_bundle_fixture_v2 as fixture
import run_v0224_bundle_preparation as old_controller
import run_v0224_bundle_preparation_v2 as controller
import v0224_bundle_cpu_batch as old_batch
import v0224_bundle_cpu_batch_v2 as batch
from v0222_admission_read_scope import AdmissionReadScope


def normalized(module, replacements):
    tree = ast.parse(Path(module.__file__).read_text())

    class Names(ast.NodeTransformer):
        def visit_Constant(self, node):
            if type(node.value) is str:
                for source, target in replacements.items():
                    node.value = node.value.replace(source, target)
            return node

    return ast.dump(Names().visit(tree), include_attributes=False)


def test_entire_batch_only_fixed_root_and_revision_change():
    assert normalized(
        batch,
        {
            "20260913-gate-a-bundle-v2": "20260913-gate-a-bundle-v1",
            "bundle-v2-slice": "bundle-v1-slice",
            "V0224_BUNDLE_AUTHORITY_CPU_V2": "V0224_BUNDLE_AUTHORITY_CPU_V1",
        },
    ) == normalized(old_batch, {})


def test_entire_controller_only_fixture_and_instance_routes_change():
    assert normalized(
        controller,
        {
            "prepare_v0224_bundle_fixture_v2.py": "prepare_v0224_bundle_fixture.py",
            "bundle-v2-slice": "bundle-v1-slice",
        },
    ) == normalized(old_controller, {})


@pytest.mark.parametrize(
    "name",
    ["_require_fresh_root", "_check_sealed_pins", "_check_initialized_state", "_public_inputs"],
)
def test_existing_fixture_validation_functions_unchanged(name):
    old = ast.parse(textwrap.dedent(inspect.getsource(getattr(old_fixture, name))))
    new = ast.parse(textwrap.dedent(inspect.getsource(getattr(fixture, name))))
    assert ast.dump(old) == ast.dump(new)


def test_original_complete_plan_mapping_loop_unchanged():
    def loop(module):
        tree = ast.parse(inspect.getsource(module._prepare))
        return next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "stage"
        )

    assert ast.dump(loop(old_fixture)) == ast.dump(loop(fixture))


def test_all_old_entries_retained_plus_explicit_new_versions():
    assert set(old_fixture.REQUIRED_TOOLS) <= set(fixture.REQUIRED_TOOLS)
    assert set(old_fixture.REQUIRED_TESTS) <= set(fixture.REQUIRED_TESTS)
    assert {
        "v0224_bundle_cpu_batch_v2.py",
        "prepare_v0224_bundle_fixture_v2.py",
        "run_v0224_bundle_reference_slice_v2.py",
        "run_v0224_bundle_preparation_v2.py",
    } <= set(fixture.REQUIRED_TOOLS)
    assert "test_run_v0224_bundle_reference_slice_v2.py" in fixture.REQUIRED_TESTS


def test_new_fixed_root_refuses_old_instance(monkeypatch):
    monkeypatch.setenv("MILA_V0224_INSTANCE", "bundle-v2-slice")
    assert str(batch.selected_root()).endswith("20260913-gate-a-bundle-v2/bundle-v2-slice")
    monkeypatch.setenv("MILA_V0224_INSTANCE", "bundle-v1-slice")
    with pytest.raises(batch.ProviderStop):
        batch.selected_root()


@pytest.fixture
def public(tmp_path):
    plan = {"P4": [{"root": f"case{i}"} for i in range(4) for _ in range(6)]}
    pins = {}
    for i in range(4):
        path = tmp_path / f"case{i}" / "public-initial.json"
        path.parent.mkdir()
        path.write_bytes(b'{"state":"original"}')
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return plan, pins, tmp_path


def test_all_four_public_direct_pins_use_external_observation_without_rehash(public):
    plan, pins, cases = public
    selected = fixture._public_source_pins(plan, pins, cases)
    assert selected == pins

    def never_hash(path):
        raise AssertionError("must not mint new public pin")

    assert fixture._collect_input_pins({Path(name) for name in pins}, selected, never_hash) == pins
    with pytest.raises(ValueError, match="ALL_TRUSTED_INPUTS"):
        fixture._collect_input_pins(set(), selected, never_hash)


def test_missing_one_external_public_pin_refuses(public):
    plan, pins, cases = public
    pins.pop(next(iter(pins)))
    with pytest.raises(ValueError, match="FOUR_EXTERNALLY_PINNED"):
        fixture._public_source_pins(plan, pins, cases)


def test_scope_body_drift_cannot_be_reblessed_by_input_pin_collection(public):
    plan, pins, cases = public
    selected = fixture._public_source_pins(plan, pins, cases)

    def never_hash(path):
        raise AssertionError("public source must keep trusted pin")

    with pytest.raises(ValueError):
        with AdmissionReadScope() as scope:
            for name, pin in selected.items():
                scope.read_json(Path(name), pin)
            Path(next(iter(selected))).write_bytes(b'{"state":"changed"}')
            assert (
                fixture._collect_input_pins({Path(name) for name in selected}, selected, never_hash)
                == pins
            )
    assert scope.status == "CLOSED_FAILED"


def test_post_close_drift_is_rejected_by_existing_seal_pin_comparison(public):
    plan, pins, cases = public
    selected = fixture._public_source_pins(plan, pins, cases)
    with AdmissionReadScope() as scope:
        for name, pin in selected.items():
            scope.read_json(Path(name), pin)
    Path(next(iter(selected))).write_bytes(b'{"state":"changed after close"}')
    actual = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in selected}
    with pytest.raises(ValueError, match="INPUT_CHANGED_AFTER_SCOPE_CLOSE"):
        fixture._check_sealed_pins({"inputs": actual, "dependencies": {}}, selected, {})
