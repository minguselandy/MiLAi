"""Synthetic orchestration and original business AST; no real K3 or HTTP."""

import ast
import copy
import inspect
import os
import sys
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import run_v0224_k3_cpu as runner
from v0220_provider_hardened import ProviderStop


@pytest.fixture
def batch_module(monkeypatch, tmp_path):
    class Batch:
        pass

    module = SimpleNamespace(CPU_ROOT=tmp_path / "k3", OfflineBatch=Batch)
    monkeypatch.setitem(sys.modules, "v0224_k3_cpu_batch", module)
    monkeypatch.setattr("v0222_scoped_cpu_guard.require_cpu_network_guard", lambda: None)
    return module


def contract(module, tmp_path):
    pin = "a" * 64
    bundle, receipt, policy = [str(tmp_path / n) for n in ("bundle", "receipt", "policy")]
    return {
        "status": "V0224_K3_FUNCTIONAL_FROZEN",
        "execution_revision": "V0224_K3_COMPLETION_PRIORITY_01",
        "root": str(module.CPU_ROOT),
        "binding_sha256": pin,
        "static_authority": {
            "bundle_path": bundle,
            "bundle_sha256": pin,
            "receipt_path": receipt,
            "receipt_sha256": pin,
            "limits": {
                "max_header_bytes": 100,
                "max_payload_bytes": 100,
                "max_paths": 10,
                "max_blobs": 10,
            },
        },
        "files": {
            str(module.CPU_ROOT / "execution-binding.json"): pin,
            bundle: pin,
            receipt: pin,
            policy: pin,
        },
        "priority_policy": {"path": policy, "sha256": pin},
        "limits": dict(runner.LIMITS),
    }


def test_exact_full_functional_contract(batch_module, tmp_path):
    value = contract(batch_module, tmp_path)
    assert runner.validate_contract(value) is value


@pytest.mark.parametrize(
    "mutation", ["rows", "bool", "status", "extra", "binding", "policy", "sql", "authority"]
)
def test_contract_rejects_bad_or_incomplete_claim(batch_module, tmp_path, mutation):
    value = contract(batch_module, tmp_path)
    if mutation == "rows":
        value["limits"]["p4_reference_rows"] = 79
    elif mutation == "bool":
        value["limits"]["http_requests"] = False
    elif mutation == "status":
        value["status"] = "PASS"
    elif mutation == "extra":
        value["efficiency_override"] = True
    elif mutation == "binding":
        value["binding_sha256"] = "b" * 64
    elif mutation == "policy":
        value["priority_policy"]["sha256"] = "b" * 64
    elif mutation == "sql":
        value["files"][str(batch_module.CPU_ROOT / "batch.sqlite")] = "a" * 64
    else:
        value["static_authority"]["receipt_path"] = value["static_authority"]["bundle_path"]
    with pytest.raises(ProviderStop):
        runner.validate_contract(value)


class FakeBatch:
    def __init__(self, root, stage, count):
        self.root = root
        self.plan = {stage: [{"id": f"episode-{n}"} for n in range(count)]}
        self.events = []

    def launch_once(self, stage):
        self.events.append(("launch", stage))

    @contextmanager
    def _operation(self, stage):
        self.events.append(("admit", stage))
        db = SimpleNamespace(
            execute=lambda *a: SimpleNamespace(fetchone=lambda: [str(time.time() + 1000)])
        )
        yield db, None, None

    def finish(self, episode):
        self.events.append(("finish", episode))
        return {"pid": 20000 + int(episode.split("-")[-1])}

    def freeze_p3_gate(self, path):
        self.events.append(("gate", str(path)))

    def snapshot(self):
        return {"stop": False, "episodes": []}


@pytest.mark.parametrize("stage,count", [("P3", 16), ("P4", 24)])
def test_complete_cold_matrix_exit_before_parent_finish(
    batch_module, tmp_path, monkeypatch, stage, count
):
    batch = FakeBatch(tmp_path, stage, count)
    commands = []
    monkeypatch.setattr(runner, "_batch", lambda *a: batch)

    def child(command, **kwargs):
        n = len(commands)
        commands.append(command)
        batch.events.append(("exit", n))
        return {
            "pid": 20000 + n,
            "parent_pid": os.getpid(),
            "returncode": 0,
            "timed_out": False,
            "seconds": 1,
        }

    monkeypatch.setattr(runner, "run_child", child)
    result = runner.run_stage(
        tmp_path,
        "a" * 64,
        stage,
        object(),
        contract_path=tmp_path / "contract",
        contract_sha256="b" * 64,
    )
    assert result["status"] == f"CPU_REPLAY_{stage}_PASS"
    assert len(commands) == count
    for n in range(count):
        assert batch.events.index(("exit", n)) < batch.events.index(("finish", f"episode-{n}"))
    assert sum(e[0] == "gate" for e in batch.events) == (stage == "P3")
    assert all(c[2] == "worker" and "--contract-sha256" in c for c in commands)


@pytest.mark.parametrize("failure", ["exit", "timeout", "pid"])
def test_failed_child_never_advances_or_freezes_gate(batch_module, tmp_path, monkeypatch, failure):
    batch = FakeBatch(tmp_path, "P3", 16)
    calls = []
    stops = []
    monkeypatch.setattr(runner, "_batch", lambda *a: batch)
    monkeypatch.setattr(runner, "stop_batch", lambda *a: stops.append(a[-1]))

    def child(*a, **kw):
        calls.append(a)
        return {
            "pid": 0 if failure == "pid" else 20000,
            "returncode": 1 if failure == "exit" else 0,
            "timed_out": failure == "timeout",
        }

    monkeypatch.setattr(runner, "run_child", child)
    result = runner.run_stage(
        tmp_path,
        "a" * 64,
        "P3",
        object(),
        contract_path=tmp_path / "contract",
        contract_sha256="b" * 64,
    )
    assert result["status"] == "CPU_REPLAY_STAGE_NOT_MET"
    assert len(calls) == 1 and stops
    assert not any(e[0] == "gate" for e in batch.events)


def test_child_real_pid_and_actual_exit_no_http():
    result = runner.run_child(
        [sys.executable, "-c", 'print("synthetic")'], timeout=5, on_failure=lambda exc: None
    )
    assert (
        result["returncode"] == 0
        and result["pid"] != os.getpid()
        and result["parent_pid"] == os.getpid()
    )
    assert result["stdout"].strip() == "synthetic" and not result["timed_out"]


def test_timeout_reaps_owned_child():
    stops = []
    result = runner.run_child(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.02, on_failure=stops.append
    )
    assert result["timed_out"] and result["returncode"] is not None and stops
    with pytest.raises(ProcessLookupError):
        os.kill(result["pid"], 0)


def test_worker_original_business_ast_preserved():
    import v0222_scoped_cpu_worker as old

    before = ast.parse(textwrap.dedent(inspect.getsource(old.run))).body[0]
    after = ast.parse(textwrap.dedent(inspect.getsource(runner.run_worker))).body[0]
    # Only explicit factory and local import/guard setup differ; original run try/finally exact.
    before_body = before.body
    after_body = after.body[-2:]

    class Factory(ast.NodeTransformer):
        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "Batch":
                node.func.id = "_batch"
                node.args.append(ast.Name(id="authority", ctx=ast.Load()))
            return node

    assert ast.dump(
        Factory().visit(ast.Module(body=copy.deepcopy(before_body), type_ignores=[]))
    ) == ast.dump(ast.Module(body=after_body, type_ignores=[]))


def test_worker_failure_preserves_primary_after_close_failure(batch_module, tmp_path, monkeypatch):
    primary = RuntimeError("generation primary")
    calls = []
    batch = SimpleNamespace(
        claim=lambda episode: None,
        spec=lambda episode: {"stage": "P3"},
        references=lambda stage: [{"episode": "one", "canonical": str(tmp_path / "request")}],
    )

    class Provider:
        def verify(self):
            pass

        def generate(self, *args):
            raise primary

        def close(self):
            raise OSError("secondary close")

    monkeypatch.setattr(runner, "_batch", lambda *args: batch)
    monkeypatch.setattr(runner, "FullProvider", lambda *args, **kwargs: Provider())
    monkeypatch.setattr(runner, "stop_batch", lambda *args: calls.append(args[-1]))
    monkeypatch.setattr("v0220_evidence.read", lambda path: {})
    with pytest.raises(RuntimeError) as caught:
        runner.run_worker(tmp_path, "a" * 64, "one", object())
    assert caught.value is primary and calls[0] is primary
    assert any("SECONDARY_PROVIDER_CLOSE_FAILURE" in note for note in primary.__notes__)


def test_reference_delegates_complete_original_materializer(batch_module, tmp_path, monkeypatch):
    batch, authority = object(), object()
    calls = []
    monkeypatch.setattr(runner, "_batch", lambda *args: batch)

    def original(value):
        calls.append(value)
        return {
            "status": "REFERENCE_PREPARATION_PASS",
            "P3_requests": 16,
            "P4_requests": 80,
            "P4_chains": 24,
        }

    monkeypatch.setattr("prepare_v0222_presentation_v2.materialize_references", original)
    result = runner.prepare_references(tmp_path, "a" * 64, authority)
    assert calls == [batch] and result["P4_requests"] == 80 and result["P4_chains"] == 24


def test_interruption_keeps_primary_and_reaps_only_owned_child(monkeypatch):
    primary = KeyboardInterrupt("primary")
    killed = []

    class Child:
        pid = 999999
        returncode = None

        def communicate(self, timeout):
            if self.returncode is None:
                self.returncode = -9
                raise primary
            return "", ""

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Child())
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: killed.append(pid))
    with pytest.raises(KeyboardInterrupt) as caught:
        runner.run_child(["fixed"], timeout=1, on_failure=lambda exc: None)
    assert caught.value is primary and killed == [999999]
