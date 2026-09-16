"""Bounded synthetic current-candidate calibration checks; no real fixtures/timing."""

import ast
import copy
import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public
from test_v0223_reference_prefix_v2 import factory

import run_v0223_diagnostic_admission as worker
import v0221_http_batch as transaction_module
import v0222_scoped_cpu_guard as guard
import v0222_scoped_evidence as evidence
import v0223_diagnostic_cpu_batch as binding
import v0223_reference_prefix_v2 as helper
from v0222_admission_read_scope import AdmissionReadScope
from v0223_coarse_observation import CoarseObserver, interval_union_ns
from v0223_transaction_primary_fix import corrected_transaction
from v0223_tree_readonly_candidate import verify_tree as candidate_tree

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def contract():
    return {
        "status": "INVENTORY_DIAGNOSTIC_CALIBRATION_FROZEN",
        "execution_revision": "V0224_GATE_A_EXECUTION_R02",
        "observation_revision": "INVENTORY_BREAKDOWN_R01",
        "baseline_policy": "TRANSACTION_PRIMARY_FIX_BOTH_MODES",
        "candidate_policy": "TREE_CANDIDATE_BOTH_MODES",
        "http_requests_allowed": 0,
        "model_requests_allowed": 0,
        "concurrency": 1,
        "calibration_outer_seconds": 300,
        "session_seconds": 60,
        "expected_scope_count": 5,
        "overhead_median_limit": 1.10,
        "files": {"/synthetic/source": "a" * 64},
        "calibration_order": [
            {
                "instance": instance,
                "mode": mode,
                "variant": "candidate",
                "root": str(worker.CPU_BASE / ("diagv1-" + instance)),
                "binding_sha256": "b" * 64,
            }
            for instance, mode in worker.CALIBRATION_ORDER
        ],
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "K0_FROZEN"),
        ("execution_revision", "old"),
        ("observation_revision", "old"),
        ("baseline_policy", "TRANSACTION_PRIMARY_FIX_BOTH_ARMS"),
        ("candidate_policy", "ORIGINAL_U_CANDIDATE_S"),
        ("http_requests_allowed", False),
        ("model_requests_allowed", 1),
        ("concurrency", True),
        ("concurrency", 2),
        ("calibration_outer_seconds", 301),
        ("session_seconds", 61),
        ("expected_scope_count", 55),
        ("overhead_median_limit", 1.11),
        ("overhead_median_limit", True),
        ("files", {}),
        ("files", {"relative": "a" * 64}),
        ("files", {"/synthetic": "G" * 64}),
    ],
)
def test_contract_rejects_unreviewed_widened_or_mixed_arms(key, value):
    frozen = contract()
    frozen[key] = value
    with pytest.raises(ValueError):
        worker.validate_contract(frozen, "d1-u1", "U")


def test_exact_all_six_positions_and_selected_mode():
    for instance, mode in worker.CALIBRATION_ORDER:
        assert worker.validate_contract(contract(), instance, mode)["variant"] == "candidate"
    for value in (None, [], "contract"):
        with pytest.raises(ValueError):
            worker.validate_contract(value, "d1-u1", "U")
    for instance, mode in (("d1-u1", "S"), ("k1-u1", "U"), ("d1-prefix", "S")):
        with pytest.raises(ValueError):
            worker.validate_contract(contract(), instance, mode)
    for field, value in (
        ("mode", "U"),
        ("variant", "original"),
        ("binding_sha256", "bad"),
        ("root", "/old"),
    ):
        frozen = contract()
        frozen["calibration_order"][1][field] = value
        with pytest.raises(ValueError):
            worker.validate_contract(frozen, "d1-u1", "U")
    frozen = contract()
    frozen["calibration_order"].reverse()
    with pytest.raises(ValueError):
        worker.validate_contract(frozen, "d1-u1", "U")


@pytest.mark.parametrize("hook", ["getprofile", "gettrace"])
def test_profile_or_trace_refused_before_contract_io(monkeypatch, hook):
    monkeypatch.setattr(sys, hook, lambda: object())
    with pytest.raises(ValueError, match="UNPROFILED_UNTRACED"):
        worker.main()


def test_binding_changes_only_roots_not_constructor_authorization(monkeypatch):
    def methods(filename):
        module = ast.parse((TOOLS / filename).read_text())
        cls = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "OfflineBatch"
        )
        return {
            node.name: ast.dump(node, include_attributes=False)
            for node in cls.body
            if isinstance(node, ast.FunctionDef)
        }

    assert methods("v0223_diagnostic_cpu_batch.py") == methods("v0223_k2_cpu_batch.py")
    roots = []
    for instance, _ in worker.CALIBRATION_ORDER:
        monkeypatch.setenv("MILA_V0223_INSTANCE", instance)
        roots.append(binding.selected_root())
    assert len(set(roots)) == 6 and len({len(str(root)) for root in roots}) == 1
    assert all(root.parent == worker.CPU_BASE == binding.CPU_BASE for root in roots)
    for instance in ("k2-base", "k1-u1", "d1-cold", "../d1-u1", ""):
        monkeypatch.setenv("MILA_V0223_INSTANCE", instance)
        with pytest.raises(Exception, match="EXPLICIT_FROZEN"):
            binding.selected_root()


@pytest.mark.parametrize("entry", ["worker", "prepare", "inventory"])
def test_ineffective_guard_refuses_before_stack_or_output_in_fresh_child(tmp_path, entry):
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.addaudithook = lambda hook: None
if sys.argv[2] == 'worker':
    import run_v0223_diagnostic_admission as target
    sys.argv = ['worker', '--contract', '/absent', '--contract-sha256', '0'*64,
                '--instance', 'd1-u1', '--mode', 'U']
elif sys.argv[2] == 'prepare':
    import prepare_v0223_diagnostic_fixture as target
    sys.argv = ['prepare', '--instance', 'd1-u1']
else:
    import inventory_v0223_diagnostic_fixture as target
    sys.argv = ['inventory', '--instance', 'd1-u1', '--output', sys.argv[3]]
try:
    target.main()
except RuntimeError as error:
    assert str(error) == 'CPU_NETWORK_GUARD_REGISTRATION_NOT_CONFIRMED'
else:
    raise AssertionError('unguarded accepted')
assert 'v0223_diagnostic_cpu_batch' not in sys.modules
print('GUARD_REFUSED_BEFORE_STACK')
"""
    output = tmp_path / "not-created.json"
    result = subprocess.run(  # noqa: S603 -- fixed synthetic guard-refusal script.
        [sys.executable, "-c", code, str(TOOLS), entry, str(output)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "GUARD_REFUSED_BEFORE_STACK" and not output.exists()


@pytest.mark.parametrize("mode", ["U", "S"])
def test_exact_installer_order_private_json_span_and_restore(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(guard, "_installed", True)  # Synthetic local test, no transport.
    path = tmp_path / "tree.json"
    path.write_text('{"unused":{"items":[1,2,3]}}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    Batch = factory(tmp_path / "batch-source.json")
    before_tree, before_transaction = evidence.verify_tree, transaction_module.Batch.transaction

    def forbidden_clock():
        raise AssertionError("U observer clock invoked")

    observer = CoarseObserver(
        "synthetic", enabled=mode == "S", **({"clock": forbidden_clock} if mode == "U" else {})
    )
    with worker.installed_diagnostic_stack(observer, batch_class=Batch), observer.span("execution"):
        assert transaction_module.Batch.transaction is corrected_transaction
        if mode == "U":
            assert evidence.verify_tree is candidate_tree
        else:
            from v0223_inventory_breakdown import inventory_breakdown_report

            assert evidence.verify_tree is not candidate_tree
            assert inventory_breakdown_report(observer)["status"] == "COMPLETE_AGGREGATES"
        with AdmissionReadScope() as scope:
            evidence.verify_tree(scope, path, digest)
        assert scope.stats["json_parses"] == 1
    assert (
        evidence.verify_tree is before_tree
        and transaction_module.Batch.transaction is before_transaction
    )
    report = observer.report()
    assert report["status"] == "COMPLETE_SPANS"
    if mode == "S":
        assert any(row["category"] == "inventory" for row in report["records"])
        assert (
            sum(
                row["json_docs"]
                for row in report["records"]
                if row["category"] == "json_parse_copy"
            )
            == 0
        )
        assert {"private_json_parse", "private_json_eligibility", "private_json_copy_guard"} <= {
            row["category"] for row in report["records"]
        }
        assert sum(row["exclusive_wall_ns"] for row in report["records"]) == next(
            row["inclusive_wall_ns"] for row in report["records"] if row["category"] == "execution"
        )
    else:
        assert report["records"] == []
    prefix = {"coverage": {"scopes": [{"stats": scope.stats}]}}
    coverage = worker.observation_coverage(prefix, report, mode)
    assert coverage["scope_json_parse_events"] == 1
    assert coverage["unclassified_private_parse_events"] == (1 if mode == "S" else None)


def test_current_five_scope_original_session_u_s_coverage_and_u_clock_isolation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(guard, "_installed", True)
    original_time = helper.time
    results = []
    for mode in ("U", "S"):
        Batch = factory(tmp_path / "source.json")
        observer = CoarseObserver("synthetic", enabled=mode == "S")

        def forbidden():
            raise AssertionError("U helper observation clock invoked")

        monkeypatch.setattr(
            helper,
            "time",
            SimpleNamespace(monotonic=original_time.monotonic, perf_counter_ns=forbidden)
            if mode == "U"
            else original_time,
        )
        with (
            worker.installed_diagnostic_stack(observer, batch_class=Batch),
            observer.span("execution"),
        ):
            result = helper.run_reference_prefix(
                Batch,
                tmp_path / mode,
                full_prefix=False,
                public_loader=lambda _: public(),
                observe_internal_timing=mode == "S",
            )
        assert result["terminal_status"] == "PREFIX_REACHED_NOT_REFERENCE_PASS"
        assert result["scope_count"] == 5 and result["coverage"]["runtime_guard_count"] == 2
        assert result["session_result"]["completed_turns"] == 0
        assert observer.report()["status"] == "COMPLETE_SPANS"
        if mode == "U":
            assert result["runtime_guard_wall_ns"] == []
            assert result["runtime_guard_union_ns"] is None
            assert result["session_start_monotonic"] is result["session_end_monotonic"] is None
        else:
            assert len(result["runtime_guard_intervals"]) == 2
            assert (
                interval_union_ns(observer.records, {"operation_entry", "final_revalidation"}) > 0
            )
        results.append(copy.deepcopy(result["coverage"]))
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "module_name,function",
    [
        ("prepare_v0223_diagnostic_fixture", "prepare"),
        ("inventory_v0223_diagnostic_fixture", "main"),
    ],
)
def test_setup_inventory_refuse_profile_before_stack(monkeypatch, module_name, function):
    import importlib

    module = importlib.import_module(module_name)
    monkeypatch.setattr(sys, "getprofile", lambda: object())
    with pytest.raises(ValueError, match="UNPROFILED_UNTRACED"):
        getattr(module, function)()


@pytest.mark.parametrize("original_failure", [False, True])
def test_invalid_breakdown_refuses_without_masking_original_failure(
    tmp_path, monkeypatch, original_failure
):
    from contextlib import nullcontext

    import v0220_evidence
    import v0223_inventory_breakdown

    path = tmp_path / "contract.json"
    path.write_text("{}")
    root = tmp_path / "root"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker",
            "--contract",
            str(path),
            "--contract-sha256",
            hashlib.sha256(path.read_bytes()).hexdigest(),
            "--instance",
            "d1-u1",
            "--mode",
            "U",
        ],
    )
    monkeypatch.setattr(guard, "enable_cpu_network_guard", lambda: None)
    monkeypatch.setattr(
        worker,
        "validate_contract",
        lambda *_: {
            "root": str(root),
            "binding_sha256": "a" * 64,
        },
    )
    # Keep ordinary contract JSON reading while bypassing heavy fixture integrity.
    path.write_text('{"files": {}}')
    sys.argv[4] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(binding, "selected_root", lambda: root)
    monkeypatch.setattr(v0220_evidence, "sha", lambda _: "a" * 64)
    monkeypatch.setattr(worker, "installed_diagnostic_stack", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(worker, "observation_coverage", lambda *_: {})
    primary = ValueError("original admission failure")

    def prefix(*args, **kwargs):
        if original_failure:
            raise primary
        return {"terminal_status": "PREFIX_REACHED_NOT_REFERENCE_PASS"}

    monkeypatch.setattr(helper, "run_reference_prefix", prefix)
    monkeypatch.setattr(
        v0223_inventory_breakdown,
        "inventory_breakdown_report",
        lambda _: {
            "status": "INVALID_OBSERVATION",
            "categories": [],
            "errors": ["clock failure"],
        },
    )
    with pytest.raises(ValueError if original_failure else RuntimeError) as caught:
        worker.main()
    if original_failure:
        assert caught.value is primary
    else:
        assert str(caught.value) == "INVENTORY_BREAKDOWN_INVALID_OBSERVATION"
    import json

    result = json.loads((tmp_path / "d1-u1/worker-result.json").read_text())
    assert result["inventory_breakdown"]["status"] == "INVALID_OBSERVATION"
    assert result["status"] != "PREFIX_REACHED_NOT_REFERENCE_PASS"
    if original_failure:
        assert result["exception_type"] == "ValueError"
        assert result["reason"] == "original admission failure"
