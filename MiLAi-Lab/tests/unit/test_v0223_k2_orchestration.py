"""Refusal, process evidence and fresh-root boundaries for the K2 pair."""

import ast
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

from prepare_v0223_k2_fixture import _require_fresh_root  # noqa: E402
from run_v0223_k2_pair import read_worker_evidence  # noqa: E402
from run_v0223_k2_prefix import validate_contract  # noqa: E402
from v0222_presentation_finish_v2 import Batch as LiveBatch  # noqa: E402
from v0223_k2_cpu_batch import CPU_BASE, OfflineBatch, selected_root  # noqa: E402


def contract():
    return {
        "status": "K2_PAIR_FROZEN",
        "execution_revision": "V0224_GATE_A_EXECUTION_R02",
        "baseline_policy": "TRANSACTION_PRIMARY_FIX_BOTH_ARMS",
        "http_requests_allowed": 0,
        "model_requests_allowed": 0,
        "prefix_outer_seconds": 3600,
        "session_seconds": 60,
        "files": {"synthetic": "0" * 64},
        "pair_order": [
            {"instance": "k2-base", "variant": "original", "mode": "U"},
            {"instance": "k2-edit", "variant": "candidate", "mode": "U"},
        ],
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "K0_FROZEN"),
        ("execution_revision", "V0223_v0.1"),
        ("baseline_policy", "ORIGINAL_UNCORRECTED"),
        ("http_requests_allowed", False),
        ("model_requests_allowed", 1),
        ("prefix_outer_seconds", 3601),
        ("session_seconds", 61),
        ("files", {}),
    ],
)
def test_contract_refuses_unreviewed_or_widened_pair(key, value):
    value_contract = contract()
    value_contract[key] = value
    with pytest.raises(ValueError):
        validate_contract(value_contract, "k2-base")


def test_pair_order_mode_and_instance_cannot_be_swapped():
    for positions in (
        list(reversed(contract()["pair_order"])),
        [{**p, "mode": "S"} for p in contract()["pair_order"]],
        [contract()["pair_order"][0], {**contract()["pair_order"][1], "mode": "S"}],
        [contract()["pair_order"][0]] * 2,
    ):
        value = contract()
        value["pair_order"] = positions
        with pytest.raises(ValueError):
            validate_contract(value, "k2-base")
    with pytest.raises(ValueError):
        validate_contract(contract(), "k3-cold")


def test_two_new_equal_length_root_ids_and_old_roots_refused(monkeypatch):
    roots = []
    for name in ("k2-base", "k2-edit"):
        monkeypatch.setenv("MILA_V0223_INSTANCE", name)
        roots.append(selected_root())
        assert selected_root() == CPU_BASE / ("k2v1-" + name)
    assert roots[0] != roots[1] and len(str(roots[0])) == len(str(roots[1]))
    for name in ("k1-u1", "k1-prefix", "../k2-base", "k3-cold", ""):
        monkeypatch.setenv("MILA_V0223_INSTANCE", name)
        with pytest.raises(Exception, match="EXPLICIT_FROZEN_V0223_INSTANCE_REQUIRED"):
            selected_root()


def test_fresh_setup_refuses_existing_and_symlink_roots(tmp_path):
    root = tmp_path / "new"
    _require_fresh_root(root)
    root.mkdir()
    with pytest.raises(ValueError, match="NO_RETRY"):
        _require_fresh_root(root)
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    with pytest.raises(ValueError):
        _require_fresh_root(alias)


def test_binding_keeps_original_constructor_authorizer_and_dynamic_methods():
    def methods(name):
        module = ast.parse((TOOLS / name).read_text())
        cls = next(
            n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "OfflineBatch"
        )
        return {
            n.name: ast.dump(n, include_attributes=False)
            for n in cls.body
            if isinstance(n, ast.FunctionDef)
        }

    assert methods("v0223_k2_cpu_batch.py") == methods("v0223_cpu_batch_v2.py")
    for name in ("_operation", "_check_journal", "initialize", "stop", "snapshot"):
        assert getattr(OfflineBatch, name) is getattr(LiveBatch, name)


@pytest.fixture
def raw_child(tmp_path):
    position = contract()["pair_order"][0]
    header = {**position, "pid": os.getpid(), "contract_sha256": "a" * 64}
    result = {**position, "pid": os.getpid(), "status": "PREFIX_REACHED_NOT_REFERENCE_PASS"}
    (tmp_path / "worker-start.json").write_text(json.dumps(header))
    (tmp_path / "worker-result.json").write_text(json.dumps(result))
    return tmp_path, {"pid": os.getpid()}, position, header, result


def test_acceptance_hashes_the_exact_same_raw_result_bytes(raw_child):
    directory, child, position, _, result = raw_child
    accepted, digest = read_worker_evidence(directory, child, position, "a" * 64)
    assert accepted == result
    assert digest == hashlib.sha256((directory / "worker-result.json").read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "filename,field,value",
    [
        ("worker-start.json", "pid", -1),
        ("worker-result.json", "pid", -1),
        ("worker-start.json", "contract_sha256", "b" * 64),
        ("worker-result.json", "variant", "candidate"),
        ("worker-start.json", "instance", "k2-edit"),
        ("worker-result.json", "mode", "S"),
        ("worker-result.json", "status", "K2_PREFIX_STOP"),
    ],
)
def test_wrong_child_identity_or_terminal_is_never_accepted(raw_child, filename, field, value):
    directory, child, position, header, result = raw_child
    modified = copy.deepcopy(header if filename == "worker-start.json" else result)
    modified[field] = value
    (directory / filename).write_text(json.dumps(modified))
    with pytest.raises(ValueError, match="WRONG_OR_FAILED_RAW_CHILD_EVIDENCE"):
        read_worker_evidence(directory, child, position, "a" * 64)


def _parent_contract(tmp_path, monkeypatch):
    payload = tmp_path / "payload"
    payload.write_text("local synthetic input")
    value = contract()
    value["files"] = {str(payload): hashlib.sha256(payload.read_bytes()).hexdigest()}
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_v0223_k2_pair.py",
            "--contract",
            str(path),
            "--contract-sha256",
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ],
    )
    return path


@pytest.mark.parametrize("failure", [KeyboardInterrupt("parent interrupted"), SystemExit(9)])
def test_parent_preserves_interruption_terminal_before_reraising(tmp_path, monkeypatch, failure):
    import run_v0222_presentation
    import run_v0223_k2_pair
    import v0222_scoped_cpu_guard

    path = _parent_contract(tmp_path, monkeypatch)
    monkeypatch.setattr(v0222_scoped_cpu_guard, "enable_cpu_network_guard", lambda: None)

    def interrupted(*args, **kwargs):
        raise failure

    monkeypatch.setattr(run_v0222_presentation, "run_child", interrupted)
    with pytest.raises(type(failure)) as caught:
        run_v0223_k2_pair.main()
    assert caught.value is failure
    terminal = json.loads((path.parent / "pair/terminal.json").read_text())
    assert terminal["status"] == "K2_PAIR_STOP"
    assert len(terminal["not_run"]) == 1
    assert "exit" not in terminal["rows"][0]
    assert "No successful exit is inferred" in terminal["rows"][0]["exit_receipt_limit"]


def test_parent_stops_before_candidate_when_complete_outer_wall_exceeds_limit(
    tmp_path, monkeypatch
):
    import run_v0222_presentation
    import run_v0223_k2_pair
    import v0222_scoped_cpu_guard

    path = _parent_contract(tmp_path, monkeypatch)
    monkeypatch.setattr(v0222_scoped_cpu_guard, "enable_cpu_network_guard", lambda: None)
    calls = []

    def late(*args, **kwargs):
        calls.append(kwargs["timeout"])
        return {"pid": 123, "returncode": 0, "timed_out": False, "seconds": 3600.01}

    monkeypatch.setattr(run_v0222_presentation, "run_child", late)
    assert run_v0223_k2_pair.main() == 1
    assert calls == [3600]
    terminal = json.loads((path.parent / "pair/terminal.json").read_text())
    assert terminal["status"] == "K2_PAIR_STOP"
    assert terminal["not_run"][0]["instance"] == "k2-edit"
