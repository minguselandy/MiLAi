"""CPU contract/AST/network guard only; no replay instance or timing verdict.

The irreversible guard is tested in fresh short-lived Python children, never
installed in the pytest process. Existing live sources remain unchanged.
"""

import ast
import copy
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_presentation_batch_v2 as live
import v0222_scoped_cpu_batch as cpu
from v0220_provider_hardened import ProviderStop
from v0222_presentation_finish_v2 import Batch as LiveBatch


def history():
    return {"sources": [], "unresolved_reservations": [{"SYNTHETIC_ONLY": True}]}


def test_cpu_contract_preserves_original_limits_without_live_authority():
    source = history()
    expected = live.make_authorization(live.ROOT, issued=100, expires=200, history=source)
    actual = cpu.make_cpu_authorization(cpu.CPU_ROOT, issued=100, expires=200, history=source)
    differences = {
        key for key in actual.keys() | expected.keys() if actual.get(key) != expected.get(key)
    }
    assert differences == {
        "root",
        "batch_id",
        "coordinator_revision",
        "execution_mode",
        "real_http_allowed",
        "device_calls_allowed",
        "mock_cost_is_not_real_cost",
    }
    assert actual["root"] == str(cpu.CPU_ROOT) and actual["execution_mode"] == "CPU_MOCK_ONLY"
    assert actual["real_http_allowed"] is actual["device_calls_allowed"] is False
    assert actual["mock_cost_is_not_real_cost"] is True
    assert actual["caps"] == {"P3": 16, "P4": 96}
    assert actual["phase_wall_seconds"] == {"P3": 1800, "P4": 7200}
    assert actual["episode_wall_seconds"] == 300 and actual["http_wall_seconds"] == 60
    assert actual["raw_cap"] is None and actual["concurrency"] == 1
    actual["historical"]["sources"].append("changed return")
    assert source == history()
    grant = cpu.cpu_authorization_source()
    assert grant["origin"] == "USER_DIRECTED_OFFLINE_ENGINEERING"
    assert grant["real_http_allowed"] is grant["model_capability_or_live_admission"] is False


@pytest.mark.parametrize("root", [live.ROOT, Path("relative"), cpu.CPU_ROOT.parent])
def test_cpu_builder_refuses_live_or_unbound_roots(root):
    with pytest.raises(ProviderStop, match="CPU_REPLAY_ROOT"):
        cpu.make_cpu_authorization(root, issued=100, expires=200, history=history())


@pytest.mark.parametrize(
    "issued,expires", [(True, 200), (100, float("inf")), (100, 100), (0, 129601)]
)
def test_original_authorization_window_validation_preserved(issued, expires):
    with pytest.raises(ProviderStop, match="36_HOUR"):
        cpu.make_cpu_authorization(cpu.CPU_ROOT, issued=issued, expires=expires, history=history())


def test_live_constructor_refuses_cpu_root_without_opening_it():
    with pytest.raises(ProviderStop, match="NEW_SCOPED_ROOT"):
        LiveBatch(cpu.CPU_ROOT, "0" * 64)


def test_only_constructor_and_static_contract_binding_are_versioned():
    own_methods = {
        key for key, value in vars(cpu.OfflineBatch).items() if inspect.isfunction(value)
    }
    assert own_methods == {"__init__", "_authorize"}
    for name in (
        "_validate_plan",
        "_time_check",
        "_operation",
        "_check_journal",
        "_ready",
        "authorize",
        "initialize",
        "launch_once",
        "claim",
        "admit",
        "http_admit",
        "reserve_request",
        "dispatch_started",
        "settle_event",
        "stop",
        "snapshot",
        "freeze_artifact",
        "references",
        "finish",
        "freeze_p3_gate",
    ):
        assert getattr(cpu.OfflineBatch, name) is getattr(LiveBatch, name)


class NormalizeCpu(ast.NodeTransformer):
    """Exact allowlisted AST differences; no blanket removal of assertions."""

    names: ClassVar = {
        "CPU_ROOT": "ROOT",
        "CPU_REVISION": "COORDINATOR_REVISION",
        "make_cpu_authorization": "make_authorization",
        "cpu_authorization_source": "authorization_source",
    }
    errors: ClassVar = {
        "ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED": (
            "ONE_FIXED_CANONICAL_NEW_SCOPED_ROOT_REQUIRED"
        ),
        "EXACT_SCOPED_CPU_CONTRACT_AND_HISTORY_REQUIRED": (
            "EXACT_SCOPED_AUTHORIZATION_AND_HISTORY_REQUIRED"
        ),
        "EXPLICIT_CPU_ONLY_SOURCE_REQUIRED": "EXPLICIT_USER_SCOPE_SOURCE_REQUIRED",
        "FROZEN_SCOPED_CPU_CONTRACT_REQUIRED": "FROZEN_SCOPED_PRESENTATION_CONTRACT_REQUIRED",
    }

    def visit_Name(self, node):
        node.id = self.names.get(node.id, node.id)
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            node.value = self.errors.get(node.value, node.value)
        return node

    def visit_Expr(self, node):
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "require_cpu_network_guard"
            and not node.value.args
            and not node.value.keywords
        ):
            return None
        return self.generic_visit(node)

    def visit_Dict(self, node):
        extra = {
            "execution_mode",
            "real_http_allowed",
            "device_calls_allowed",
            "mock_cost_is_not_real_cost",
        }
        pairs = [
            (key, value)
            for key, value in zip(node.keys, node.values, strict=True)
            if not (isinstance(key, ast.Constant) and key.value in extra)
        ]
        node.keys, node.values = [p[0] for p in pairs], [p[1] for p in pairs]
        return self.generic_visit(node)


@pytest.mark.parametrize("name", ["__init__", "_authorize"])
def test_full_original_static_checks_retained_with_only_explicit_cpu_differences(name):
    original = ast.parse(textwrap.dedent(inspect.getsource(getattr(live.Batch, name))))
    current = ast.parse(textwrap.dedent(inspect.getsource(getattr(cpu.OfflineBatch, name))))
    normalized = NormalizeCpu().visit(copy.deepcopy(current))
    assert ast.dump(original, include_attributes=False) == ast.dump(
        normalized, include_attributes=False
    )


@pytest.mark.parametrize(
    "operation", ["socket", "default_httpx", "guard_required", "wrong_root", "registration_denied"]
)
def test_fresh_cpu_process_fails_closed_before_network_or_instance_creation(operation):
    tools = str(Path(__file__).resolve().parents[2] / "tools")
    code = f"""
import sys
sys.path.insert(0, {tools!r})
from v0222_scoped_cpu_guard import enable_cpu_network_guard, require_cpu_network_guard
operation = {operation!r}
if operation == 'registration_denied':
    def block_registration(event, args):
        if event == 'sys.addaudithook':
            raise RuntimeError('SYNTHETIC_REGISTRATION_REFUSAL')
    sys.addaudithook(block_registration)
    try:
        enable_cpu_network_guard()
    except RuntimeError as error:
        assert str(error) == 'CPU_NETWORK_GUARD_REGISTRATION_NOT_CONFIRMED'
    else:
        raise AssertionError('silently refused hook was marked installed')
    try:
        require_cpu_network_guard()
    except RuntimeError as error:
        assert str(error) == 'FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED'
    else:
        raise AssertionError('unconfirmed guard passed admission')
elif operation == 'guard_required':
    from v0222_scoped_cpu_batch import OfflineBatch, CPU_ROOT
    try:
        OfflineBatch(CPU_ROOT, '0' * 64)
    except RuntimeError as error:
        assert str(error) == 'FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED'
    else:
        raise AssertionError('unguarded CPU construction accepted')
else:
    enable_cpu_network_guard()
    enable_cpu_network_guard()
    require_cpu_network_guard()
    if operation == 'wrong_root':
        from v0222_scoped_cpu_batch import OfflineBatch, ROOT
        from v0220_provider_hardened import ProviderStop
        try:
            OfflineBatch(ROOT, '0' * 64)
        except ProviderStop as error:
            assert str(error) == 'ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED'
        else:
            raise AssertionError('live root accepted')
    else:
        try:
            if operation == 'socket':
                import socket
                socket.socket()
            else:
                import httpx
                with httpx.Client(trust_env=False) as client:
                    client.get('http://127.0.0.1:1', timeout=0.1)
        except RuntimeError as error:
            assert str(error) == 'CPU_REPLAY_SOCKET_FORBIDDEN'
        else:
            raise AssertionError('socket/default HTTP was not denied')
print('CPU_CONTRACT_NEGATIVE_PASS')
"""
    result = subprocess.run(  # noqa: S603 -- Fixed local test script and enumerated operation.
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CPU_CONTRACT_NEGATIVE_PASS"
