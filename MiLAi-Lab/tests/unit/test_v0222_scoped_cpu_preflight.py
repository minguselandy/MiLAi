"""CPU preflight binding/refusal checks, not a complete CPU replay.

The complete live body is compared without dropping acceptance, accounting or
failure statements. Fresh child processes only exercise refusal/help paths;
no guard is installed in pytest, no Batch acceptance is mocked into a PASS,
and neither the real CPU root nor real lineage is opened by these tests.
"""

import ast
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import preflight_v0222_presentation_v2 as live
import preflight_v0222_scoped_cpu as cpu
import run_v0222_scoped_cpu_preflight as bootstrap
from v0222_scoped_cpu_batch import OfflineBatch
from v0222_scoped_cpu_guard import require_cpu_network_guard
from v0222_scoped_cpu_mock import make_mock_transport
from v0222_scoped_cpu_worker import stop_batch


def function_tree(function):
    return ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]


def dump(node):
    return ast.dump(node, include_attributes=False)


def statement(source):
    return ast.parse(source).body[0]


def test_complete_preflight_has_only_three_explicit_cpu_differences():
    old, current = function_tree(live.preflight), function_tree(cpu.preflight)
    assert [arg.arg for arg in old.args.kwonlyargs] == ["transport"]
    assert [dump(value) for value in old.args.kw_defaults] == [dump(ast.Constant(None))]
    assert current.args.kwonlyargs == [] and current.args.kw_defaults == []
    old.args.kwonlyargs = []
    old.args.kw_defaults = []

    assert dump(current.body[0]) == dump(statement("require_cpu_network_guard()"))
    del current.body[0]
    construction = statement("batch = Batch(root, binding)")
    factory = statement("transport = make_mock_transport(batch)")
    matches = []
    for outer in current.body:
        if isinstance(outer, ast.Try):
            for index, item in enumerate(outer.body):
                if dump(item) == dump(construction):
                    matches.append((outer, index))
    assert len(matches) == 1
    outer, index = matches[0]
    assert dump(outer.body[index + 1]) == dump(factory)
    del outer.body[index + 1]

    # Exact comparison of every remaining statement, including nested handlers,
    # all reference/receipt/count checks, final freeze and post-freeze admission.
    assert dump(current) == dump(old)


def test_admission_and_all_non_cpu_workflow_dependencies_are_original_objects():
    assert cpu.admit_preflight is live.admit_preflight
    assert cpu.Batch is OfflineBatch
    assert cpu.make_mock_transport is make_mock_transport
    assert cpu.require_cpu_network_guard is require_cpu_network_guard
    assert cpu.stop_batch is stop_batch
    for name in (
        "PREFLIGHT_SECONDS",
        "RECEIPT_COUNTS",
        "REFERENCE_COUNTS",
        "ENDPOINT",
        "MODEL",
        "TOKENIZE_KEYS",
        "save",
        "sha",
        "ProviderStop",
        "encoded",
        "bounded_request",
        "strict_http_json",
        "validate_reference",
        "identity",
        "owned_timeout",
        "time",
        "httpx",
    ):
        assert getattr(cpu, name) is getattr(live, name), name
    assert cpu.REFERENCE_COUNTS == {"P3": 16, "P4": 80}
    assert cpu.RECEIPT_COUNTS == {"P3": 104, "P4": 488}
    assert cpu.PREFLIGHT_SECONDS == {"P3": 1200, "P4": 2400}


@pytest.mark.parametrize("override", ["transport", "endpoint", "url", "handler", "outputs"])
def test_public_preflight_has_no_external_transport_or_url_override(tmp_path, override):
    signature = inspect.signature(cpu.preflight)
    assert list(signature.parameters) == ["root", "binding", "stage"]
    assert all(
        parameter.kind not in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}
        for parameter in signature.parameters.values()
    )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        signature.bind(tmp_path / "absent", "0" * 64, "P3", **{override: object()})


def test_cli_body_only_adds_guard_and_retains_failure_exit_code():
    old, current = function_tree(live.main), function_tree(cpu.main)
    assert dump(current.body[0]) == dump(statement("require_cpu_network_guard()"))
    del current.body[0]
    assert dump(current) == dump(old)


def test_bootstrap_guard_precedes_replay_stack_import():
    tree = function_tree(bootstrap.main)
    expected = ast.parse(
        "from v0222_scoped_cpu_guard import enable_cpu_network_guard\n"
        "enable_cpu_network_guard()\n"
        "from preflight_v0222_scoped_cpu import main as preflight_main\n"
        "from v0222_scoped_cpu_observation import run_observed\n"
        "return run_observed(preflight_main, 'preflight')\n"
    ).body
    assert [dump(item) for item in tree.body] == [dump(item) for item in expected]


@pytest.mark.parametrize("entry", ["preflight", "main"])
def test_unguarded_entry_refuses_in_fresh_child_without_files_or_sockets(tmp_path, entry):
    tools = Path(__file__).resolve().parents[2] / "tools"
    root = tmp_path / "not-created"
    code = """
import sys
from pathlib import Path
attempts = []
def deny_network(event, args):
    if event.startswith('socket.'):
        attempts.append(event)
        raise AssertionError('NO_SOCKET_ATTEMPT_ALLOWED')
sys.addaudithook(deny_network)
sys.path.insert(0, sys.argv[1])
import preflight_v0222_scoped_cpu as cpu
# Imported dependencies may catch an audit-denied socket capability probe.
# Keep the deny hook active, but distinguish import probes from this entry.
import_attempts = tuple(attempts)
root = Path(sys.argv[2])
entry = sys.argv[3]
sys.argv = ['cpu-preflight', '--root', str(root), '--binding-sha256', '0'*64, '--stage', 'P3']
try:
    if entry == 'preflight':
        cpu.preflight(root, '0'*64, 'P3')
    else:
        cpu.main()
except RuntimeError as error:
    assert str(error) == 'FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED'
else:
    raise AssertionError('unguarded entry accepted')
assert not root.exists() and tuple(attempts) == import_attempts
print('UNGUARDED_PREFLIGHT_REJECTED_NO_FILES_NO_ENTRY_SOCKET')
"""
    result = subprocess.run(  # noqa: S603 -- Fixed short-lived refusal code, no model.
        [sys.executable, "-c", code, str(tools), str(root), entry],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "UNGUARDED_PREFLIGHT_REJECTED_NO_FILES_NO_ENTRY_SOCKET"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entry", ["help", "invalid_root"])
def test_guarded_bootstrap_short_lived_help_or_wrong_root_is_not_replay(tmp_path, entry):
    tools = Path(__file__).resolve().parents[2] / "tools"
    root = tmp_path / "not-a-cpu-instance"
    args = (
        ["--help"]
        if entry == "help"
        else ["--root", str(root), "--binding-sha256", "0" * 64, "--stage", "P3"]
    )
    result = subprocess.run(  # noqa: S603 -- Guarded bootstrap only help/wrong-root refusal.
        [sys.executable, str(tools / "run_v0222_scoped_cpu_preflight.py"), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if entry == "help":
        assert result.returncode == 0
        assert "--binding-sha256" in result.stdout and "--stage {P3,P4}" in result.stdout
        assert "--transport" not in result.stdout and "--url" not in result.stdout
    else:
        assert result.returncode != 0
        assert "ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED" in result.stderr
    assert list(tmp_path.iterdir()) == []
