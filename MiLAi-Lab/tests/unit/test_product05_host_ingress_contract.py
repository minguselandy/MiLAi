from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

LAB = Path(__file__).resolve().parents[2]
BRIDGE_GATEWAY = "172.18.0.1"


def _tool_module(name: str, monkeypatch: Any) -> Any:
    if name == "run_product05_lifecycle":
        monkeypatch.setitem(sys.modules, "psycopg", types.ModuleType("psycopg"))
    path = LAB / "tools" / f"{name}.py"
    module_name = f"{name}_ingress_contract"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    original_path = list(sys.path)
    original_modules = set(sys.modules)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
        for loaded_name in set(sys.modules) - original_modules:
            if loaded_name == "milai_client" or loaded_name.startswith(
                "milai_openworker_mcp"
            ):
                sys.modules.pop(loaded_name, None)
    return module


class _ProcessRecorder:
    def __init__(self) -> None:
        self.starts: list[list[str]] = []

    def start(self, arguments: list[str], *_args: Any, **_kwargs: Any) -> Any:
        self.starts.append(arguments)
        return SimpleNamespace(poll=lambda: None)


def _argument(arguments: list[str], name: str) -> str:
    return arguments[arguments.index(name) + 1]


def test_lifecycle_host_and_container_share_the_recorded_bridge_gateway(
    tmp_path: Path, monkeypatch: Any
) -> None:
    module = _tool_module("run_product05_lifecycle", monkeypatch)
    processes = _ProcessRecorder()
    ingress_token = tmp_path / "ingress.token"
    ingress_token.write_text("test-ingress-token\n", encoding="utf-8")
    stack = SimpleNamespace(
        environment={},
        root=tmp_path,
        api_port=4101,
        host_port=4201,
        reader_socket=tmp_path / "reader.sock",
        submitter_socket=tmp_path / "submitter.sock",
        reader_policy=tmp_path / "reader.json",
        submitter_policy=tmp_path / "submitter.json",
        reader_token_file=tmp_path / "reader.token",
        submitter_token_file=tmp_path / "submitter.token",
        ingress_token_file=ingress_token,
        manifest=tmp_path / "manifest.json",
        ledger=tmp_path / "ledger.jsonl",
        trace=tmp_path / "trace.jsonl",
        container="product05-lifecycle-test-container",
        processes=processes,
    )
    probes: list[tuple[str, int]] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(module, "_wait_http", lambda *_args: None)
    monkeypatch.setattr(module, "_wait_socket", lambda *_args: None)
    monkeypatch.setattr(
        module,
        "_wait_port",
        lambda host, port, _process: probes.append((host, port)),
    )

    def command(arguments: list[str], **_kwargs: Any) -> Any:
        commands.append(arguments)
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(module, "_command", command)
    monkeypatch.setattr(module, "_container_health", lambda _container: None)

    module._start_process_stack(stack, BRIDGE_GATEWAY)
    module._start_container(stack, "product05-test-network", BRIDGE_GATEWAY)

    host_arguments = processes.starts[-1]
    assert _argument(host_arguments, "--listen-host") == BRIDGE_GATEWAY
    assert "0.0.0.0" not in host_arguments  # noqa: S104 - rejected wildcard
    assert probes == [(BRIDGE_GATEWAY, stack.host_port)]
    assert f"OPENWORKER_URL=http://{BRIDGE_GATEWAY}:{stack.host_port}/v1" in commands[0]


def test_openworker_lme_host_and_container_share_the_recorded_bridge_gateway(
    tmp_path: Path, monkeypatch: Any
) -> None:
    module = _tool_module("run_product05_openworker_lme", monkeypatch)
    processes = _ProcessRecorder()
    ingress_token = tmp_path / "ingress.token"
    ingress_token.write_text("test-ingress-token\n", encoding="utf-8")
    lane = SimpleNamespace(
        mode="direct",
        port=4202,
        manifest=tmp_path / "manifest.json",
        ledger=tmp_path / "ledger.jsonl",
        trace=tmp_path / "trace.jsonl",
        ingress_token=ingress_token,
        container="product05-test-container",
    )
    stack = SimpleNamespace(
        root=tmp_path,
        reader_socket=tmp_path / "reader.sock",
        reader_policy=tmp_path / "reader.json",
        processes=processes,
        containers=[],
    )
    probes: list[tuple[str, int]] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(
        module,
        "_wait_port",
        lambda host, port, _process: probes.append((host, port)),
    )

    def command(arguments: list[str], **_kwargs: Any) -> Any:
        commands.append(arguments)
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(module, "_command", command)

    module._start_lane(stack, lane, "product05-test-network", BRIDGE_GATEWAY)

    host_arguments = processes.starts[-1]
    assert _argument(host_arguments, "--listen-host") == BRIDGE_GATEWAY
    assert "0.0.0.0" not in host_arguments  # noqa: S104 - rejected wildcard
    assert probes == [(BRIDGE_GATEWAY, lane.port)]
    assert f"OPENWORKER_URL=http://{BRIDGE_GATEWAY}:{lane.port}/v1" in commands[0]
