"""Prototype refusal tests; never launch a timing or reference instance."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import run_v0223_admission_pair as worker


def contract():
    return {
        "status": "K0_FROZEN",
        "model_requests_allowed": 0,
        "http_requests_allowed": 0,
        "files": {"/synthetic/source": "0" * 64},
        "calibration_order": [
            {"instance": instance, "mode": mode} for instance, mode in worker.CALIBRATION_ORDER
        ],
    }


def test_fixed_six_order_and_position():
    frozen = contract()
    assert worker.validate_contract(frozen, "k1-s2", "S") == frozen["calibration_order"][2]
    frozen["calibration_order"].reverse()
    with pytest.raises(ValueError, match="SIX_PROCESS_ORDER"):
        worker.validate_contract(frozen, "k1-s2", "S")
    with pytest.raises(ValueError, match="U_S_POSITION"):
        worker.validate_contract(contract(), "k1-s2", "U")


def test_prefix55_requires_separately_frozen_s_position():
    frozen = contract()
    with pytest.raises(ValueError, match="55_SCOPE"):
        worker.validate_contract(frozen, "k1-prefix", "S", prefix55=True)
    frozen["prefix55"] = {"instance": "k1-prefix", "mode": "S"}
    assert worker.validate_contract(frozen, "k1-prefix", "S", prefix55=True) == frozen["prefix55"]
    with pytest.raises(ValueError, match="55_SCOPE"):
        worker.validate_contract(frozen, "k1-prefix", "U", prefix55=True)
    with pytest.raises(ValueError, match="U_S_POSITION"):
        worker.validate_contract(frozen, "k1-prefix", "S")


@pytest.mark.parametrize("key", ["http_requests_allowed", "model_requests_allowed"])
@pytest.mark.parametrize("value", [None, False, "0", 1])
def test_network_and_model_allocations_must_be_integer_zero(key, value):
    frozen = contract()
    frozen[key] = value
    with pytest.raises(ValueError, match="CPU_ONLY_K0"):
        worker.validate_contract(frozen, "k1-s2", "S")


@pytest.mark.parametrize("hook", ["getprofile", "gettrace"])
def test_instrumented_process_refused(monkeypatch, hook):
    monkeypatch.setattr(sys, hook, lambda: object())
    with pytest.raises(ValueError, match="UNPROFILED_UNTRACED"):
        worker.validate_contract(contract(), "k1-s2", "S")


def test_unprofiled_check_precedes_contract_io(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker",
            "--contract",
            "/does/not/exist",
            "--contract-sha256",
            "0" * 64,
            "--instance",
            "k1-u1",
            "--mode",
            "U",
        ],
    )
    monkeypatch.setattr(sys, "getprofile", lambda: object())
    with pytest.raises(ValueError, match="UNPROFILED_UNTRACED"):
        worker.main()
