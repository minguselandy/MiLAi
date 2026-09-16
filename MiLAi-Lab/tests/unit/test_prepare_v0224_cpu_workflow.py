"""Synthetic combined fixture/controller wiring; no actual preparation."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import prepare_v0224_cpu_workflow as controller
import prepare_v0224_verified_digest_fixture as old_fixture
import run_v0224_verified_digest_preparation as old_controller
import v0224_cpu_workflow_batch as batch

ORDER = batch.INSTANCE_ORDER


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
    assert len({tuple(row["argv"][5:]) for row in calls[2:]}) == 1
    assert all("prepare_v0224_cpu_workflow.py" in row["argv"][1] for row in calls[2:])
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


def test_delegated_helpers_are_original_objects():
    for name in ("_remaining", "_run_child", "_approval_input", "_pinned_json"):
        assert getattr(controller, name) is getattr(old_controller, name)
    for name in (
        "_public_inputs",
        "_public_source_pins",
        "_collect_input_pins",
        "_check_sealed_pins",
        "_check_initialized_state",
        "_require_fresh_root",
    ):
        assert getattr(controller, name) is getattr(old_fixture, name)
    assert controller.LIMIT_SECONDS == 300


def test_all_old_entries_and_fixed_evidence_preserved():
    assert set(old_fixture.REQUIRED_TOOLS) <= set(controller.REQUIRED_TOOLS)
    assert set(old_fixture.REQUIRED_TESTS) <= set(controller.REQUIRED_TESTS)
    assert set(controller.REQUIRED_TOOLS) - set(old_fixture.REQUIRED_TOOLS) == {
        "v0224_cpu_workflow_batch.py",
        "prepare_v0224_cpu_workflow.py",
        "run_v0224_cpu_workflow.py",
    }
    assert old_fixture.R04_EVIDENCE_PINS.items() <= controller.R04_EVIDENCE_PINS.items()
    assert len(controller.R04_EVIDENCE_PINS) == 4
    assert (
        "5ba177bd85576f92e8d5eaf3f7047353257c268d46a950d162afb4ef4c034a3a"
        in controller.R04_EVIDENCE_PINS.values()
    )
    assert (
        "792d2f5600097e378e38f3817e7e0fca98499c502d2e4fbf377c1ce1713c6631"
        in controller.R04_EVIDENCE_PINS.values()
    )


def test_missing_future_source_refused(tmp_path):
    with pytest.raises(ValueError, match="SOURCE_MISSING"):
        controller._required_entries(tmp_path)


def test_fixture_command_routed_explicitly(parent):
    path, pin, calls = parent
    controller.run_preparation(path, pin)
    assert all(row["argv"][2] == "fixture" for row in calls[2:])
    assert batch.K3_INSTANCE not in [row["argv"][4] for row in calls[2:]]


def test_parent_rejects_instrumented_before_import_and_io(tmp_path, monkeypatch):
    monkeypatch.setattr(controller.sys, "getprofile", lambda: object())
    with pytest.raises(ValueError, match="UNPROFILED"):
        controller.run_preparation(tmp_path / "missing", "a" * 64)
    assert not (tmp_path / "preparation-controller-v1").exists()


def test_parent_stage_without_new_cli_is_refused():
    for command in ("stage", "worker", "k3"):
        with pytest.raises(ValueError, match="EXPLICIT_FIXTURE_OR_CONTROLLER"):
            controller.main([command])


def test_complete_previous_source_closure_retained():
    from v0220_evidence import dependencies

    lab = Path(__file__).resolve().parents[2]
    previous = set(dependencies(old_fixture._required_entries(lab)))
    current = set(dependencies(controller._required_entries(lab)))
    assert previous <= current
    source = Path(controller.__file__).read_text()
    # Full prior 203 includes inherited manifests beyond the direct entry closure.
    for origin in ("prior_manifest", "original"):
        assert (
            f'entries.extend(Path(name) for name in {origin}["dependencies"])'
            in source
        )


def test_parent_final_recheck_drift_preserves_failure(parent, monkeypatch):
    path, pin, calls = parent
    original = controller._run_child

    def mutate_after_last(argv, phase, *args):
        row = original(argv, phase, *args)
        if phase == "fixture_preparer-" + ORDER[-1]:
            path.write_bytes(path.read_bytes() + b" ")
        return row

    monkeypatch.setattr(controller, "_run_child", mutate_after_last)
    with pytest.raises(ValueError, match="INITIAL_CONTENT_HASH_MISMATCH"):
        controller.run_preparation(path, pin)
    assert len(calls) == 8
    report = json.loads(
        (path.parent / "preparation-controller-v1/preparation-failure.json").read_text()
    )
    assert report["phase"] == "parent_input_recheck"
    assert not (path.parent / "preparation-controller-v1/preparation-result.json").exists()
