"""Fixed six-root routing and preparation budget; synthetic children only."""

import ast
import hashlib
import inspect
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import prepare_v0224_bundle_fixture_v2 as old_fixture
import prepare_v0224_runtime_union_fixture as fixture
import run_v0224_bundle_preparation_v2 as old_controller
import run_v0224_runtime_union_preparation as controller
import v0224_bundle_cpu_batch_v2 as old_batch
import v0224_runtime_union_batch as batch

ORDER = (
    "unionv1-d1-u1",
    "unionv1-d1-s1",
    "unionv1-d1-s2",
    "unionv1-d1-u2",
    "unionv1-d1-u3",
    "unionv1-d1-s3",
)


def tree(value):
    return ast.dump(ast.parse(textwrap.dedent(inspect.getsource(value))))


def test_Batch_class_and_pure_authorization_functions_identical():
    assert tree(batch.OfflineBatch) == tree(old_batch.OfflineBatch)
    assert tree(batch.StaticAuthority) == tree(old_batch.StaticAuthority)
    for name in ("selected_root", "cpu_authorization_source", "make_cpu_authorization"):
        assert tree(getattr(batch, name)) == tree(getattr(old_batch, name))
    assert batch.INSTANCE_ORDER == ORDER and len({len(name) for name in ORDER}) == 1


@pytest.mark.parametrize("name", ORDER)
def test_only_six_fixed_fresh_roots(name, monkeypatch):
    monkeypatch.setenv("MILA_V0224_INSTANCE", name)
    assert str(batch.selected_root()) == (
        "/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-runtime-union-v1/" + name
    )
    monkeypatch.setenv("MILA_V0224_INSTANCE", "bundle-v2-slice")
    with pytest.raises(batch.ProviderStop):
        batch.selected_root()


@pytest.mark.parametrize(
    "name", ["_public_source_pins", "_collect_input_pins", "_public_inputs", "_check_sealed_pins"]
)
def test_public_pin_safety_unchanged(name):
    assert tree(getattr(fixture, name)) == tree(getattr(old_fixture, name))


def test_all_previous_sources_and_tests_retained():
    assert set(old_fixture.REQUIRED_TOOLS) <= set(fixture.REQUIRED_TOOLS)
    assert set(old_fixture.REQUIRED_TESTS) <= set(fixture.REQUIRED_TESTS)
    assert "v0224_runtime_admission_observation.py" in fixture.REQUIRED_TOOLS
    assert "run_v0224_runtime_union_calibration.py" in fixture.REQUIRED_TOOLS
    assert (
        fixture.FAILED_REFERENCE_REVIEW_SHA256
        == "44c265a11de8c1fee0d52f00c1d5b4ee18f549b29c439e7d105699898c07001b"
    )
    source = Path(fixture.__file__).read_text()
    assert "str(FAILED_REFERENCE_REVIEW): FAILED_REFERENCE_REVIEW_SHA256" in source


@pytest.mark.parametrize(
    "name",
    [
        "_remaining",
        "_group_gone",
        "_cleanup_owned",
        "_run_child",
        "_approval_input",
        "_pinned_json",
    ],
)
def test_controller_lifecycle_and_approval_helpers_identical(name):
    assert tree(getattr(controller, name)) == tree(getattr(old_controller, name))


@pytest.fixture
def parent(monkeypatch, tmp_path):
    import prepare_v0224_bundle_authority as authority
    import v0220_evidence as evidence
    import v0222_scoped_cpu_guard as guard

    monkeypatch.setattr(guard, "enable_cpu_network_guard", lambda: None)
    monkeypatch.setattr(authority, "_validate_contract", lambda *args: None)
    monkeypatch.setattr(evidence, "dependencies", lambda *args: [])
    path = tmp_path / "contract.json"
    limits = {"max_header_bytes": 100, "max_payload_bytes": 100, "max_paths": 10, "max_blobs": 10}
    path.write_text(json.dumps({"files": {}, "limits": limits}))
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    calls = []

    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    candidate = {"status": "STATIC_BUNDLE_CANDIDATE_NOT_APPROVED", "bundle_sha256": "a" * 64}

    def child(argv, phase, out, deadline, rows):
        calls.append({"phase": phase, "argv": argv, "deadline": deadline})
        row = {"pid": 1000 + len(calls), "returncode": 0, "cleanup_complete": True}
        rows.append(row)
        directory = tmp_path / "authority-v1"
        if phase == "authority_builder":
            generated = {
                str(directory / "sealed/candidate-receipt.json"): put(
                    directory / "sealed/candidate-receipt.json", candidate
                ),
                str(directory / "sealed/static.bundle"): "a" * 64,
                str(directory / "sealed/seal-observation.json"): "b" * 64,
                str(directory / "revalidated/mechanical-revalidation.json"): "c" * 64,
            }
            put(
                directory / "authority-prepared.json",
                {
                    "status": "READY_FOR_INDEPENDENT_AUTHORITY_REVIEW",
                    "runtime_authorized": False,
                    "pid": row["pid"],
                    "contract_sha256": pin,
                    "generated_files": generated,
                },
            )
        elif phase == "finalizer":
            receipt = directory / "approved-receipt.json"
            receipt_sha = put(
                receipt, {**candidate, "status": "INDEPENDENT_STATIC_BUNDLE_APPROVED"}
            )
            put(
                out / "finalizer.stdout",
                {
                    "path": str(receipt),
                    "sha256": receipt_sha,
                    "status": "APPROVED_RECEIPT_MATERIALIZED_NOT_GATE_A",
                },
            )
        return row

    monkeypatch.setattr(controller, "_run_child", child)
    monkeypatch.setattr(
        controller,
        "_approval_input",
        lambda path, *args: {"approval_path": str(path), "approval_sha256": "d" * 64},
    )
    return path, pin, calls


def test_all_six_fixture_children_share_one_authority_and_deadline(parent):
    path, pin, calls = parent
    report = controller.run_preparation(path, pin)
    assert len(calls) == 8 and len(report["children"]) == 8
    assert len({row["deadline"] for row in calls}) == 1
    assert [row["phase"] for row in calls[2:]] == ["fixture_preparer-" + name for name in ORDER]
    assert [row["argv"][row["argv"].index("--instance") + 1] for row in calls[2:]] == list(ORDER)
    assert len({tuple(row["argv"][4:]) for row in calls[2:]}) == 1
    assert all("prepare_v0224_runtime_union_fixture.py" in row["argv"][1] for row in calls[2:])
    assert report["status"] == "PREPARATION_STEPS_COMPLETE_EXTERNAL_EXIT_REQUIRED"


def test_middle_fixture_failure_stops_wave_without_replacement(parent, monkeypatch):
    path, pin, calls = parent
    original = controller._run_child
    primary = TimeoutError("one shared budget exhausted")

    def fail(argv, phase, *args):
        if phase == "fixture_preparer-" + ORDER[2]:
            raise primary
        return original(argv, phase, *args)

    monkeypatch.setattr(controller, "_run_child", fail)
    with pytest.raises(TimeoutError) as raised:
        controller.run_preparation(path, pin)
    assert raised.value is primary
    assert len(calls) == 4
    result = json.loads(
        (path.parent / "preparation-controller-v1/preparation-failure.json").read_text()
    )
    assert result["phase"] == "fixture_preparer-" + ORDER[2]
