"""Current calibration process receipt and stop boundaries."""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
from run_v0223_diagnostic_calibration import read_worker_evidence  # noqa: E402


@pytest.fixture
def child_files(tmp_path):
    position = {"instance": "d1-s1", "variant": "candidate", "mode": "S"}
    header = {**position, "pid": 987, "contract_sha256": "a" * 64}
    result = {**position, "pid": 987, "status": "PREFIX_REACHED_NOT_REFERENCE_PASS"}
    for name, value in (("worker-start.json", header), ("worker-result.json", result)):
        (tmp_path / name).write_text(json.dumps(value))
    return tmp_path, {"pid": 987}, position, header, result


def test_exact_result_bytes_are_bound(child_files):
    path, child, position, _, result = child_files
    actual, digest = read_worker_evidence(path, child, position, "a" * 64)
    assert actual == result
    assert digest == hashlib.sha256((path / "worker-result.json").read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("worker-start.json", "pid", 988),
        ("worker-result.json", "pid", 988),
        ("worker-start.json", "contract_sha256", "b" * 64),
        ("worker-result.json", "variant", "original"),
        ("worker-start.json", "mode", "U"),
        ("worker-result.json", "mode", "U"),
        ("worker-result.json", "status", "MEASUREMENT_STOP"),
    ],
)
def test_wrong_raw_receipt_is_rejected(child_files, name, field, value):
    path, child, position, header, result = child_files
    raw = copy.deepcopy(header if name == "worker-start.json" else result)
    raw[field] = value
    (path / name).write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="WRONG_OR_FAILED_RAW_CHILD_EVIDENCE"):
        read_worker_evidence(path, child, position, "a" * 64)


def setup_parent(tmp_path, monkeypatch):
    import run_v0223_diagnostic_admission as worker
    import v0222_scoped_cpu_guard as guard

    source = tmp_path / "input"
    source.write_text("bounded synthetic parent test")
    positions = [
        {"instance": name, "mode": mode, "variant": "candidate"}
        for name, mode in worker.CALIBRATION_ORDER
    ]
    value = {
        "calibration_order": positions,
        "files": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value))
    monkeypatch.setattr(worker, "validate_contract", lambda *a: positions[0])
    monkeypatch.setattr(guard, "enable_cpu_network_guard", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parent",
            "--contract",
            str(path),
            "--contract-sha256",
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ],
    )
    return path


@pytest.mark.parametrize("seconds", [300.01, 0, -1, float("nan")])
def test_complete_child_limit_stops_before_next_position(tmp_path, monkeypatch, seconds):
    import run_v0222_presentation as old
    import run_v0223_diagnostic_calibration as parent

    path = setup_parent(tmp_path, monkeypatch)
    calls = []

    def child(*args, **kwargs):
        calls.append(kwargs["timeout"])
        return {"pid": 987, "returncode": 0, "timed_out": False, "seconds": seconds}

    monkeypatch.setattr(old, "run_child", child)
    assert parent.main() == 1
    assert calls == [300]
    terminal = json.loads((path.parent / "calibration/terminal.json").read_text())
    assert terminal["status"] == "DIAGNOSTIC_CALIBRATION_STOP"
    assert len(terminal["not_run"]) == 5 and terminal["median_ratio"] is None


@pytest.mark.parametrize("failure", [KeyboardInterrupt("interrupted"), SystemExit(8)])
def test_primary_interruption_keeps_stop_receipt(tmp_path, monkeypatch, failure):
    import run_v0222_presentation as old
    import run_v0223_diagnostic_calibration as parent

    path = setup_parent(tmp_path, monkeypatch)

    def child(*args, **kwargs):
        raise failure

    monkeypatch.setattr(old, "run_child", child)
    with pytest.raises(type(failure)) as caught:
        parent.main()
    assert caught.value is failure
    terminal = json.loads((path.parent / "calibration/terminal.json").read_text())
    assert terminal["status"] == "DIAGNOSTIC_CALIBRATION_STOP"
    assert len(terminal["not_run"]) == 5
    assert "exit" not in terminal["rows"][0]


def test_six_fixed_children_bind_modes_and_compute_paired_median(tmp_path, monkeypatch):
    import run_v0222_presentation as old
    import run_v0223_diagnostic_calibration as parent

    path = setup_parent(tmp_path, monkeypatch)
    positions = json.loads(path.read_text())["calibration_order"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    seconds = iter((20.0, 21.0, 24.0, 20.0, 40.0, 40.0))
    calls = []

    def child(command, **kwargs):
        index = len(calls)
        position = positions[index]
        assert command[command.index("--instance") + 1] == position["instance"]
        assert command[command.index("--mode") + 1] == position["mode"]
        assert kwargs["timeout"] == 300
        calls.append(command)
        directory = tmp_path / position["instance"]
        directory.mkdir()
        header = {**position, "pid": 990 + index, "contract_sha256": digest}
        result = {**header, "status": "PREFIX_REACHED_NOT_REFERENCE_PASS"}
        (directory / "worker-start.json").write_text(json.dumps(header))
        (directory / "worker-result.json").write_text(json.dumps(result))
        return {"pid": header["pid"], "returncode": 0, "timed_out": False, "seconds": next(seconds)}

    monkeypatch.setattr(old, "run_child", child)
    assert parent.main() == 0
    terminal = json.loads((tmp_path / "calibration/terminal.json").read_text())
    assert len(calls) == 6 and terminal["not_run"] == terminal["failures"] == []
    assert terminal["paired_S_over_U_outer_wall"] == [1.05, 1.2, 1.0]
    assert terminal["median_ratio"] == 1.05
    assert terminal["status"] == "SIX_EXITS_PENDING_INDEPENDENT_COVERAGE_AUDIT"
