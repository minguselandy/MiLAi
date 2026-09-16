from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
observation = importlib.import_module("v02_cgroup_observation")


def fixture(tmp_path):
    proc = tmp_path / "proc/42"
    group = tmp_path / "cgroup/system.slice/docker-owned.scope"
    proc.mkdir(parents=True)
    group.mkdir(parents=True)
    (proc / "cgroup").write_text("0::/system.slice/docker-owned.scope\n")
    # /proc/stat field 22, indexed from field 3 after the process name.
    (proc / "stat").write_text("42 (postgres worker) " + " ".join(["0"] * 19 + ["1234"]))
    (group / "cpu.stat").write_text("usage_usec 12\nnr_throttled 0\nthrottled_usec 0\n")
    (group / "cpu.max").write_text("200000 100000\n")
    return proc, group


def bind(tmp_path, container_id="owned"):
    return observation.ContainerObservation.bind(
        42, container_id, proc_root=tmp_path / "proc", cgroup_root=tmp_path / "cgroup",
    )


def test_bound_container_reads_and_missing_optional_counters_stay_explicit(tmp_path):
    fixture(tmp_path)
    sample = bind(tmp_path).sample()
    assert sample["raw"]["cpu.max"] == "200000 100000\n"
    assert "io.pressure" in sample["unavailable"] and "io.pressure" not in sample["raw"]
    assert sample["started_s"] <= sample["ended_s"]


def test_host_scheduler_sample_missing_counters_and_processes_are_not_zero(tmp_path):
    proc, _ = fixture(tmp_path)
    (proc / "schedstat").write_text("1000000 2000000 3\n")
    (tmp_path / "proc/stat").write_text("cpu 1 2 3 4 5 6 7 8 0 0\n")
    result = observation.host_scheduler_sample(
        {"load_client": 42, "gone_mcp": 404}, proc_root=tmp_path / "proc")
    assert result["processes"]["load_client"] == {
        "pid": 42, "start_ticks": "1234", "status": "OBSERVED",
        "main_thread_schedstat": "1000000 2000000 3\n"}
    assert result["processes"]["gone_mcp"] == {"pid": 404, "status": "UNAVAILABLE"}
    assert result["unavailable"] == ["pressure/cpu", "pressure/io"]
    assert "pressure/cpu" not in result["host_raw"]
    assert result["started_s"] <= result["ended_s"]


def test_host_scheduler_pid_change_does_not_attribute_wait_to_old_process(tmp_path, monkeypatch):
    proc, _ = fixture(tmp_path)
    (proc / "schedstat").write_text("1000000 2000000 3\n")
    identities = iter(["1234", "5678"])
    monkeypatch.setattr(observation, "start_ticks", lambda proc: next(identities))
    result = observation.host_scheduler_sample({"api": 42}, proc_root=tmp_path / "proc")
    assert result["processes"]["api"] == {"pid": 42, "status": "IDENTITY_CHANGED"}


@pytest.mark.parametrize("change", ["other_container", "reused_pid", "moved_group", "gone"])
def test_unconfirmed_or_changed_identity_stops_observation(tmp_path, change):
    proc, _ = fixture(tmp_path)
    if change == "other_container":
        with pytest.raises(RuntimeError, match="IDENTITY_UNCONFIRMED"):
            bind(tmp_path, "different")
        return
    observer = bind(tmp_path)
    if change == "reused_pid":
        (proc / "stat").write_text((proc / "stat").read_text().replace("1234", "5678"))
    elif change == "moved_group":
        (proc / "cgroup").write_text("0::/other\n")
    else:
        (proc / "stat").unlink()
    with pytest.raises((RuntimeError, FileNotFoundError)):
        observer.sample()


@pytest.mark.parametrize("mode", ["complete", "missing", "reset"])
def test_counter_window_encloses_call_and_does_not_fill_missing_or_reset_with_zero(mode):
    samples = [
        {"started_s": at, "ended_s": at + 0.01, "unavailable": ["cpu.stat.local"],
         "raw": {"cpu.stat": f"throttled_usec {value}\nnr_throttled 0\n",
                 "io.pressure": f"full avg10=0.00 avg60=0.00 avg300=0.00 total={value}"}}
        for at, value in [(1.0, 10), (1.5, 20), (2.0, 5 if mode == "reset" else 30)]
    ]
    if mode == "missing":
        samples.pop()
    result = observation.enclosing_window(samples, 1.4, 1.7)
    if mode == "complete":
        assert result["started_s"] == 1.0 and result["ended_s"] == 2.01
        assert result["delta"]["cpu.throttled_usec"] == 20
        assert result["delta"]["io.pressure.full.total_usec"] == 20
        assert "cpu.stat.local" in result["unavailable"]
    else:
        assert "delta" not in result and result["status"].endswith("NOT_ZERO")
