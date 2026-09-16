"""Fixed MockHTTP script and CPU worker binding tests, not a cold matrix.

No actual Batch, lineage, reference materialization or acceptance is faked into
a PASS. Pure script tests use MockTransport. Bootstrap tests only run short-lived
local Python help/invalid-root processes; no real CPU_ROOT or model is opened.
"""

import ast
import copy
import inspect
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import run_v0222_scoped_cpu_worker as bootstrap
import v0222_presentation_worker_v2 as live_worker
import v0222_scoped_cpu_mock as mock
import v0222_scoped_cpu_worker as worker
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_provider_hardened import ProviderStop
from v0222_diagnostic import request
from v0222_presentation_provider_v2 import FullProvider as OriginalProvider
from v0222_scoped_cpu_batch import CPU_ROOT, OfflineBatch


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU_WORKER_TEST_MOCK_HTTP_ONLY")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def identity():
    return {"endpoint": ENDPOINT, "model": MODEL, "context": 65536, "version": "MOCK_SCRIPT"}


def wire():
    return request("T1", "D00")[1]


def counted_body(body):
    return {key: copy.deepcopy(body[key]) for key in TOKENIZE_KEYS}


def client(outputs=()):
    return httpx.Client(
        base_url=ENDPOINT,
        trust_env=False,
        transport=mock._scripted_transport(identity(), tuple(outputs)),
    )


def test_fixed_identity_and_explicitly_simulated_counts():
    with client() as local:
        assert local.get("/v1/models").json() == {"data": [{"id": MODEL, "max_model_len": 65536}]}
        assert local.get("/version").json() == {"version": "MOCK_SCRIPT"}
        for body in (
            counted_body(wire()),
            {"model": MODEL, "prompt": "完整原文", "add_special_tokens": False},
        ):
            response = local.post("/tokenize", json=body)
            assert response.status_code == 200
            assert response.json() == {"count": mock.MOCK_PROMPT_TOKENS}
            assert type(response.json()["count"]) is int
    assert mock.MOCK_PROMPT_TOKENS == 100 and mock.MOCK_COMPLETION_TOKENS == 20


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not JSON",
        ' \n{"完整":"Unicode 世界 العربية","array":[1,2]}\t ',
        '{"escape":"\\n\\t\\"\\\\\\u263a"}',
        "[" * 1100 + "0" + "]" * 1100,
    ],
)
def test_entire_scripted_raw_is_returned_without_normalization(raw):
    body = wire()
    with client([raw]) as local:
        local.post("/tokenize", json=counted_body(body))
        response = local.post("/v1/chat/completions", json=body)
        assert response.status_code == 200
        value = response.json()
        assert value["choices"] == [{"message": {"content": raw}, "finish_reason": "stop"}]
        assert value["id"] == "CPU_MOCK_ONLY-1"
        assert value["usage"] == {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        }


@pytest.mark.parametrize(
    "change", ["missing", "messages", "extra_key", "bool_int", "output_tokenize"]
)
def test_generation_requires_exact_tokenize_projection(change):
    body = wire()
    count = counted_body(body)
    if change == "messages":
        count["messages"] = []
    elif change == "extra_key":
        count["unbound_extra"] = True
    elif change == "bool_int":
        assert type(count["add_generation_prompt"]) is bool
        count["add_generation_prompt"] = int(count["add_generation_prompt"])
    elif change == "output_tokenize":
        count = {"model": MODEL, "prompt": "answer", "add_special_tokens": False}
    with client(["raw"]) as local:
        if change != "missing":
            local.post("/tokenize", json=count)
        with pytest.raises(ProviderStop, match="EXACT_ACTUAL_TOKENIZE_INPUT"):
            local.post("/v1/chat/completions", json=body)


def test_each_generation_consumes_one_tokenize_and_one_script_position():
    body = wire()
    with client(["first", "second"]) as local:
        for index, raw in enumerate(("first", "second"), 1):
            local.post("/tokenize", json=counted_body(body))
            result = local.post("/v1/chat/completions", json=body).json()
            assert result["id"] == f"CPU_MOCK_ONLY-{index}"
            assert result["choices"][0]["message"]["content"] == raw
            with pytest.raises(ProviderStop, match="EXACT_ACTUAL_TOKENIZE_INPUT"):
                local.post("/v1/chat/completions", json=body)
        for _ in range(2):
            local.post("/tokenize", json=counted_body(body))
            with pytest.raises(ProviderStop, match="SCRIPT_EXHAUSTED_NO_RETRY"):
                local.post("/v1/chat/completions", json=body)


def test_latest_tokenize_cannot_authorize_an_earlier_body():
    body = wire()
    alternate = counted_body(body)
    alternate["messages"] = [{"role": "user", "content": "different"}]
    with client(["raw"]) as local:
        local.post("/tokenize", json=counted_body(body))
        local.post("/tokenize", json=alternate)
        with pytest.raises(ProviderStop, match="EXACT_ACTUAL_TOKENIZE_INPUT"):
            local.post("/v1/chat/completions", json=body)


def test_empty_preflight_script_cannot_generate_after_tokenize():
    body = wire()
    with client() as local:
        local.post("/tokenize", json=counted_body(body))
        with pytest.raises(ProviderStop, match="SCRIPT_EXHAUSTED_NO_RETRY"):
            local.post("/v1/chat/completions", json=body)


@pytest.mark.parametrize(
    "method,route",
    [
        ("GET", "/tokenize"),
        ("POST", "/version"),
        ("POST", "/v1/models"),
        ("GET", "/v1/chat/completions"),
        ("POST", "/other"),
        ("PUT", "/tokenize"),
    ],
)
def test_only_fixed_methods_and_routes_exist(method, route):
    with client() as local:
        with pytest.raises(ProviderStop, match="ROUTE_NOT_IN_FIXED_SCRIPT"):
            local.request(method, route, json={"model": MODEL})


@pytest.mark.parametrize("route", ["/tokenize", "/v1/chat/completions"])
def test_wrong_model_rejected_on_both_post_routes(route):
    with client(["raw"]) as local:
        with pytest.raises(ProviderStop, match="MODEL_DRIFT"):
            local.post(route, json={"model": "not-the-fixed-model"})


@pytest.mark.parametrize("raw", [b"{", b'{"model":1,"model":2}', b'{"model":NaN}', b"\xff"])
@pytest.mark.parametrize("route", ["/tokenize", "/v1/chat/completions"])
def test_invalid_json_duplicate_nonfinite_and_utf8_rejected(raw, route):
    with client(["raw"]) as local:
        with pytest.raises(ValueError):
            local.post(route, content=raw)


def test_complete_live_worker_run_body_is_retained_without_statement_elision():
    old = ast.parse(textwrap.dedent(inspect.getsource(live_worker.run)))
    current = ast.parse(textwrap.dedent(inspect.getsource(worker.run)))
    assert ast.dump(old, include_attributes=False) == ast.dump(current, include_attributes=False)
    assert worker.Batch is OfflineBatch and worker.ROOT == CPU_ROOT
    assert worker.OriginalProvider is OriginalProvider


def test_public_cpu_factories_expose_no_transport_url_or_output_override():
    assert list(inspect.signature(worker.FullProvider).parameters) == [
        "root",
        "batch",
        "episode",
        "world",
    ]
    assert list(inspect.signature(mock.make_mock_transport).parameters) == ["batch", "episode"]
    for target in (worker.FullProvider, mock.make_mock_transport):
        assert all(
            p.kind not in {p.VAR_KEYWORD, p.VAR_POSITIONAL}
            for p in inspect.signature(target).parameters.values()
        )
    tree = ast.parse(textwrap.dedent(inspect.getsource(worker.FullProvider)))
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "OriginalProvider"
    )
    transport = next(keyword.value for keyword in call.keywords if keyword.arg == "transport")
    assert isinstance(transport, ast.Call) and isinstance(transport.func, ast.Name)
    assert transport.func.id == "make_mock_transport"


def test_bootstrap_enables_guard_before_importing_worker():
    tree = ast.parse(textwrap.dedent(inspect.getsource(bootstrap.main)))
    statements = tree.body[0].body
    assert (
        isinstance(statements[0], ast.ImportFrom)
        and statements[0].module == "v0222_scoped_cpu_guard"
    )
    assert (
        isinstance(statements[1], ast.Expr)
        and statements[1].value.func.id == "enable_cpu_network_guard"
    )
    assert (
        isinstance(statements[2], ast.ImportFrom)
        and statements[2].module == "v0222_scoped_cpu_worker"
    )


@pytest.mark.parametrize("operation", ["run", "provider", "factory"])
def test_unguarded_entry_refuses_before_creating_any_file_in_fresh_process(tmp_path, operation):
    tools = Path(__file__).resolve().parents[2] / "tools"
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from v0222_scoped_cpu_worker import run, FullProvider
from v0222_scoped_cpu_mock import make_mock_transport
root = Path(sys.argv[2])
try:
    if sys.argv[3] == 'run':
        run(root, '0' * 64, 'synthetic-episode')
    elif sys.argv[3] == 'provider':
        FullProvider(root, batch=None, episode='synthetic-episode')
    else:
        make_mock_transport(None)
except RuntimeError as error:
    assert str(error) == 'FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED'
else:
    raise AssertionError('unguarded entry accepted')
assert not root.exists()
print('UNGUARDED_ENTRY_REJECTED_NO_FILES')
"""
    root = tmp_path / "not-created"
    result = subprocess.run(  # noqa: S603 -- Fixed local refusal script, no bootstrap/model.
        [sys.executable, "-c", code, str(tools), str(root), operation],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "UNGUARDED_ENTRY_REJECTED_NO_FILES" and not root.exists()


@pytest.mark.parametrize("operation", ["help", "invalid_root"])
def test_short_lived_guarded_bootstrap_is_not_a_cold_matrix(tmp_path, operation):
    tools = Path(__file__).resolve().parents[2] / "tools"
    root = tmp_path / "not-a-cpu-instance"
    args = (
        ["--help"]
        if operation == "help"
        else ["--root", str(root), "--binding-sha256", "0" * 64, "--episode", "synthetic"]
    )
    result = subprocess.run(  # noqa: S603 -- Fixed guarded CLI, only help/wrong-root refusal.
        [sys.executable, str(tools / "run_v0222_scoped_cpu_worker.py"), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if operation == "help":
        assert result.returncode == 0 and "--binding-sha256" in result.stdout
    else:
        assert (
            result.returncode != 0
            and "ONE_FIXED_CANONICAL_CPU_REPLAY_ROOT_REQUIRED" in result.stderr
        )
    assert not root.exists()
