"""Contract, timing interpretation, and primary preservation; no real cold wave."""

import copy
import json
import sys
from pathlib import Path

import pytest
from test_run_v0224_bundle_reference_slice_v2 import synthetic as source_synthetic

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_v0224_retained_static as runner

synthetic = source_synthetic


@pytest.mark.parametrize("arm", ["U", "S"])
def test_complete_synthetic_reference_original_audit_and_sql(synthetic, monkeypatch, arm):
    import v0224_bundle_cpu_batch_v2 as old_batch
    import v0224_retained_static_batch as new_batch

    state = synthetic(2)
    monkeypatch.setattr(new_batch, "selected_root", lambda: state.root)
    class ManagedFake(old_batch.OfflineBatch):
        def __enter__(self):
            self._static_released = False
            return self

        def __exit__(self, *args):
            self._static_released = True
            return False

        def retained_authority_stats(self):
            return {"synthetic_fake_admission": True}

    monkeypatch.setattr(new_batch, "OfflineBatch", ManagedFake)
    monkeypatch.setattr(new_batch, "workpoint_purpose", lambda root: "A1_REFERENCE_CALIBRATION")
    # This integration verifies original four-turn business behavior with fake admission.
    # Fixed selection and exact original-case rejection are separately tested below.
    monkeypatch.setattr(runner, "select_reference", lambda plan, spec: plan["P4"][0])
    position = {**state.contract, "reference_spec": state.contract["first_p4_spec"],
                "name": runner.ORDER[0], "arm": arm}
    details = {}
    runner.run_reference(position, state.contract["static_authority"], state.out, details)
    assert details["provider_rows"] == 4
    assert details["independent_effects"]["status"] == "PASS"
    assert len(state.operations) == 11
    assert details["observation"]["callback_counts"] == {"attempted": 11, "returned": 11}
    assert len(details["observation"]["runtime_intervals"]) == (0 if arm == "U" else 9)
    assert json.loads((state.out / "coordinator-before.json").read_text()) == json.loads(
        (state.out / "coordinator-after.json").read_text()
    )


def observation(arm="S", duration=100_000_000):
    value = {
        "mode": arm,
        "errors": [],
        "callback_counts": {"attempted": 11, "returned": 11},
        "setup_callbacks": None,
        "runtime_intervals": [],
        "session_interval": None,
        "runtime_union_ns": None,
        "status": "STRICT_U_UNTIMED",
    }
    if arm == "S":
        start = 10_000_000_000
        rows = [
            {
                "ordinal": i + 1,
                "start_ns": start + i * duration,
                "end_ns": start + (i + 1) * duration,
                "returned": True,
                "callback_attempted_delta": 1,
                "callback_returned_delta": 1,
            }
            for i in range(9)
        ]
        value.update(
            status="COMPLETE_RUNTIME_INTERVALS",
            setup_callbacks={"attempted": 2, "returned": 2},
            runtime_intervals=rows,
            session_interval={"start_ns": start - 1, "end_ns": start + 9 * duration + 1},
            runtime_union_ns=9 * duration,
        )
    return value


def wave(u=(20, 20, 20), s=(21, 21, 21), duration=100_000_000):
    children, results = [], []
    for i, name in enumerate(runner.ORDER):
        arm, pair = name[-2].upper(), int(name[-1]) - 1
        children.append(
            {
                "phase": name,
                "pid": 4000 + i,
                "returncode": 0,
                "cleanup_complete": True,
                "owned_group_gone": True,
                "elapsed_seconds": (u if arm == "U" else s)[pair],
            }
        )
        results.append(
            {
                "position": name,
                "arm": arm,
                "pid": 4000 + i,
                "status": "REFERENCE_COMPLETE_OBSERVATION_NOT_YET_CALIBRATED",
                "details": {"observation": observation(arm, duration)},
            }
        )
    return children, results


@pytest.fixture
def contract(tmp_path):
    pin = "a" * 64
    files = {str(runner.ORIGINAL_MANIFEST): runner.ORIGINAL_MANIFEST_SHA256,
             str(runner.A0_REVIEW): runner.A0_REVIEW_SHA256}
    files.update(runner.R05_EVIDENCE_PINS)
    authority = {
        "bundle_path": str(tmp_path / "static.bundle"),
        "bundle_sha256": pin,
        "receipt_path": str(tmp_path / "receipt.json"),
        "receipt_sha256": pin,
        "limits": {
            "max_header_bytes": 100,
            "max_payload_bytes": 100,
            "max_paths": 100,
            "max_blobs": 100,
        },
    }
    files.update({authority["bundle_path"]: pin, authority["receipt_path"]: pin})
    positions = []
    for name in runner.ORDER:
        root = runner.BASE / name
        public = {"path": str(tmp_path / "public.json"), "sha256": pin}
        baseline = {"path": str(tmp_path / (name + "-baseline.json")), "sha256": pin}
        files.update(
            {str(root / "execution-binding.json"): pin, public["path"]: pin, baseline["path"]: pin}
        )
        positions.append(
            {
                "name": name,
                "arm": name[-2].upper(),
                "root": str(root),
                "binding_sha256": pin,
                "reference_spec": {
                    "id": name + "-p4-03",
                    "stage": "P4",
                    "actions": [{"action": "put_record"}, {"action": "put_record"}],
                    "kind": runner.LONG_PATH.kind,
                    "root": runner.LONG_PATH.root,
                    "scope": name,
                },
                "public_source": public,
                "coordinator_baseline": baseline,
            }
        )
    return {
        "status": "R05_LONG_PATH_CALIBRATION_FROZEN",
        "execution_revision": runner.REVISION,
        "testbed_guarantee": runner.TESTBED_GUARANTEE,
        "operation": "A1_REFERENCE_CALIBRATION",
        "reference_selection": runner.asdict(runner.LONG_PATH),
        "positions": positions,
        "limits": copy.deepcopy(runner.LIMITS),
        "static_authority": authority,
        "files": files,
    }


def test_fixed_six_contract(contract):
    assert runner.validate_contract(contract) is contract


@pytest.mark.parametrize("change", ["operation", "index", "turns", "runtime", "source", "a0"])
def test_fixed_shape_and_prerequisite_contract_refuse_drift(contract, change):
    if change == "operation":
        contract["operation"] = "K3_FULL_CPU_WORKFLOW"
    elif change in {"index", "turns", "runtime"}:
        contract["reference_selection"][change] += 1
    else:
        path = runner.ORIGINAL_MANIFEST if change == "source" else runner.A0_REVIEW
        contract["files"][str(path)] = "f" * 64
    with pytest.raises(ValueError):
        runner.validate_contract(contract)


@pytest.fixture
def selected_plan(tmp_path, monkeypatch):
    spec = {
        "id": "retainv1-d1-u1-p4-03",
        "root": runner.LONG_PATH.root,
        "kind": runner.LONG_PATH.kind,
        "scope": "synthetic_scope",
        "initial_state_sha256": "synthetic_hash",
        "actions": [{"value": "first complete value"}, {"value": "second complete value"}],
        "intent": {"ordered_writes": ["first", "second"]},
    }
    plan = {"P3": [{} for _ in range(16)], "P4": [{} for _ in range(24)]}
    plan["P4"][2] = spec
    original = copy.deepcopy(plan)
    original["P4"][2].update(id="original-p4-03", scope="original_scope")
    path = tmp_path / "original-manifest.json"
    path.write_text(json.dumps({"contract": original}))
    monkeypatch.setattr(runner, "ORIGINAL_MANIFEST", path)
    monkeypatch.setattr(runner, "ORIGINAL_MANIFEST_SHA256", runner.sha(path))
    return plan, spec, path


def test_selection_returns_actual_producer_object(selected_plan):
    plan, spec, _ = selected_plan
    assert runner.select_reference(plan, copy.deepcopy(spec)) is spec


@pytest.mark.parametrize("change", ["value", "order", "intent", "index", "plan", "source"])
def test_selection_retains_entire_original_case(selected_plan, change):
    plan, spec, path = selected_plan
    if change == "value":
        spec["actions"][0]["value"] = "truncated"
    elif change == "order":
        spec["actions"].reverse()
    elif change == "intent":
        spec["intent"]["ordered_writes"] = ["only first"]
    elif change == "index":
        plan["P4"][2] = {}
    elif change == "plan":
        plan["P4"].pop()
    else:
        path.write_text("{}")
    with pytest.raises(ValueError):
        runner.select_reference(plan, copy.deepcopy(spec))


@pytest.mark.parametrize("change", ["order", "root", "arm", "public", "spec", "baseline", "sql"])
def test_contract_refuses_cross_position_or_unfrozen_inputs(contract, change):
    positions = contract["positions"]
    if change == "order":
        positions.reverse()
    elif change == "root":
        positions[0]["root"] += "-extra"
    elif change == "arm":
        positions[0]["arm"] = "S"
    elif change == "public":
        positions[1]["public_source"] = positions[1]["coordinator_baseline"]
    elif change == "spec":
        positions[1]["reference_spec"]["root"] = "different_case"
    elif change == "baseline":
        positions[1]["coordinator_baseline"] = positions[0]["coordinator_baseline"]
    else:
        contract["files"][str(runner.BASE / runner.ORDER[0] / "batch.sqlite")] = "a" * 64
    with pytest.raises(ValueError):
        runner.validate_contract(contract)


def test_full_runtime_union_can_pass_when_session_outer_exceeds_18():
    value = observation(duration=2_000_000_000)
    value["session_interval"]["end_ns"] = value["session_interval"]["start_ns"] + 20_000_000_000
    assert runner.validate_observation(value, "S") == 18_000_000_000


@pytest.mark.parametrize(
    "change", ["overlap", "outside", "unreturned", "missing", "delta", "sum", "60"]
)
def test_incomplete_or_invalid_runtime_intervals_refuse(change):
    value = observation()
    rows = value["runtime_intervals"]
    if change == "overlap":
        rows[1]["start_ns"] = rows[0]["start_ns"]
    elif change == "outside":
        rows[0]["start_ns"] = 0
    elif change == "unreturned":
        rows[0]["returned"] = False
    elif change == "missing":
        rows.pop()
    elif change == "delta":
        rows[0]["callback_returned_delta"] = 2
    elif change == "sum":
        value["runtime_union_ns"] += 1
    else:
        value["session_interval"]["end_ns"] = value["session_interval"]["start_ns"] + 60_000_000_001
    with pytest.raises(ValueError):
        runner.validate_observation(value, "S")


def test_strict_u_cannot_present_runtime_observer_data():
    value = observation("U")
    assert runner.validate_observation(value, "U") is None
    value["runtime_union_ns"] = 0
    with pytest.raises(ValueError, match="STRICT_U_NO_INTERNAL"):
        runner.validate_observation(value, "U")


def test_paired_median_is_primary_not_ratio_of_medians():
    result = runner.calibration_verdict(*wave(u=(10, 20, 30), s=(11, 25, 30)))
    assert result["paired_ratio_median"] == 1.1
    assert result["ratio_of_medians_descriptive_only"] == 1.25
    assert result["measurement_qualified"] is True
    result = runner.calibration_verdict(*wave(u=(10, 20, 50), s=(12, 21, 56)))
    assert result["paired_ratio_median"] > 1.1
    assert result["ratio_of_medians_descriptive_only"] <= 1.1
    assert result["measurement_qualified"] is False


def test_u_over_60_is_unknown_without_dropping_sample():
    result = runner.calibration_verdict(*wave(u=(61, 61, 61), s=(62, 62, 62)))
    assert result["strict_u_complete_session_bound"] == "UNKNOWN"
    assert result["measurement_qualified"] is False
    assert len(result["strict_u_worker_outer_seconds"]) == 3
    assert result["all_s_runtime_unions_at_most_18"] is None


def test_qualified_measurement_can_still_fail_original_headroom():
    result = runner.calibration_verdict(
        *wave(u=(30, 30, 30), s=(31, 31, 31), duration=3_000_000_000)
    )
    assert result["measurement_qualified"] is True
    assert result["all_s_runtime_unions_at_most_18"] is False
    assert result["gate_a"] == "NOT_PASSED_BY_CALIBRATION"


def test_missing_child_and_incomplete_lifecycle_refuse():
    children, workers = wave()
    with pytest.raises(ValueError, match="SIX_POSITIONS"):
        runner.calibration_verdict(children[:-1], workers[:-1])
    children[0]["owned_group_gone"] = False
    with pytest.raises(ValueError, match="ACTUAL_COMPLETE_COLD_CHILD"):
        runner.calibration_verdict(children, workers)


def test_raw_collection_error_cannot_replace_business_primary(tmp_path, monkeypatch):
    name = runner.ORDER[0]
    path = tmp_path / "contract.json"
    path.write_text("{}")
    contract = {"positions": [{"name": name, "arm": "U"}], "static_authority": {}}
    monkeypatch.setattr(runner, "load_contract", lambda *a: (path, contract))
    monkeypatch.setattr(runner, "verify_inputs", lambda *a: None)
    primary = RuntimeError("ORIGINAL_ADMISSION_PRIMARY")

    def fail_reference(position, authority, out, details):
        (out / "raw.bin").write_bytes(b"present before collection")
        raise primary

    original_sha = runner.sha

    def failed_hash(path):
        if Path(path).name == "raw.bin":
            raise OSError("RAW_DISAPPEARED")
        return original_sha(path)

    monkeypatch.setattr(runner, "run_reference", fail_reference)
    monkeypatch.setattr(runner, "sha", failed_hash)
    with pytest.raises(RuntimeError) as caught:
        runner.worker(str(path), "a" * 64, name)
    assert caught.value is primary
    result = json.loads(
        (tmp_path / "calibration-v1/positions" / name / "worker-result.json").read_text()
    )
    assert result["reason"] == "ORIGINAL_ADMISSION_PRIMARY"
    assert result["raw_pins_complete"] is False
    assert any("SECONDARY_RAW_PIN_COLLECTION_FAILURE" in note for note in result["notes"])


@pytest.mark.parametrize("change", ["guarantee", "r05_review", "failed_a1"])
def test_r05_subcontract_is_mandatory(contract, change):
    if change == "guarantee":
        contract["testbed_guarantee"] = "R04"
    else:
        suffix = (
            "independent-r05-testbed-scope-review.json"
            if change == "r05_review" else "independent-a1-calibration-result-review.json"
        )
        key = next(key for key in runner.R05_EVIDENCE_PINS if key.endswith(suffix))
        del contract["files"][key]
    with pytest.raises(ValueError):
        runner.validate_contract(contract)
