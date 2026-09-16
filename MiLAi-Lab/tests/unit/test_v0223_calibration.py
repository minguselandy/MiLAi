"""Parent rejects unbound or invalid worker evidence without real workloads."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from run_v0223_calibration import read_worker_evidence


@pytest.mark.parametrize(
    "change", ["pid", "mode", "contract", "result_pid", "not_ready", "stop", "malformed"]
)
def test_parent_rejects_wrong_child_or_invalid_evidence(tmp_path, change):
    start = {"pid": 123, "mode": "U", "contract_sha256": "frozen"}
    result = {"observer": {"pid": 123}, "status": "OBSERVED"}
    if change == "pid":
        start["pid"] = 456
    elif change == "mode":
        start["mode"] = "S"
    elif change == "contract":
        start["contract_sha256"] = "changed"
    elif change == "result_pid":
        result["observer"]["pid"] = 456
    elif change == "not_ready":
        result["measurement_readiness"] = "NOT_READY_FOR_K1"
    elif change == "stop":
        result["status"] = "MEASUREMENT_STOP"
    (tmp_path / "worker-start.json").write_text(json.dumps(start))
    (tmp_path / "worker-result.json").write_text(
        "{" if change == "malformed" else json.dumps(result)
    )
    with pytest.raises(ValueError):
        read_worker_evidence(tmp_path, {"pid": 123}, mode="U", contract_sha256="frozen")


def test_parent_binds_digest_of_the_same_result_bytes(tmp_path):
    (tmp_path / "worker-start.json").write_text(
        json.dumps({"pid": 123, "mode": "S", "contract_sha256": "frozen"})
    )
    raw = b'{"observer":{"pid":123},"status":"OBSERVED"}'
    (tmp_path / "worker-result.json").write_bytes(raw)
    result, digest = read_worker_evidence(
        tmp_path, {"pid": 123}, mode="S", contract_sha256="frozen"
    )
    assert result["observer"]["pid"] == 123
    assert digest == hashlib.sha256(raw).hexdigest()


def test_parent_preserves_terminal_and_not_run_on_broken_child_result(tmp_path, monkeypatch):
    import run_v0222_presentation as child_module
    import run_v0223_admission_pair as worker
    import run_v0223_calibration as parent
    import v0222_scoped_cpu_guard as guard

    order = [{"instance": name, "mode": mode} for name, mode in worker.CALIBRATION_ORDER]
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"calibration_order": order, "files": {}}))
    digest = hashlib.sha256(contract.read_bytes()).hexdigest()
    monkeypatch.setattr(guard, "enable_cpu_network_guard", lambda: None)
    monkeypatch.setattr(worker, "validate_contract", lambda *args: order[0])
    monkeypatch.setattr(
        child_module,
        "run_child",
        lambda *args, **kwargs: {
            "pid": 123,
            "returncode": 0,
            "seconds": 0.5,
            "timed_out": False,
        },
    )
    directory = tmp_path / "k1-u1"
    directory.mkdir()
    (directory / "worker-start.json").write_text("{")
    monkeypatch.setattr(
        sys, "argv", ["runner", "--contract", str(contract), "--contract-sha256", digest]
    )
    assert parent.main() == 1
    terminal = json.loads((tmp_path / "calibration/terminal.json").read_bytes())
    assert terminal["status"] == "CALIBRATION_STOP"
    assert terminal["not_run"] == order[1:]
    assert terminal["rows"][0]["evidence_failure"]["type"] == "JSONDecodeError"
    assert terminal["rows"][0]["exit"]["pid"] == 123
