from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any


class _WireHost:
    """Minimal independent legacy MCP host used only for stdio interoperability smoke."""

    def __init__(self, profile: str) -> None:
        executable = Path(sys.executable).with_name("milai-mcp")
        if not executable.is_file():
            raise RuntimeError("milai-mcp entrypoint is not installed")
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("MILAI_")
        }
        environment.update(
            {
                "MILAI_BASE_URL": os.environ["MILAI_BASE_URL"],
                "MILAI_AGENT_TOKEN": os.environ["MILAI_AGENT_TOKEN"],
            }
        )
        for name in (
            "MILAI_AGENT_SCOPE_JSON",
            "MILAI_AGENT_REQUIRED_AUTHORITY",
            "MILAI_AGENT_CONSISTENCY_FLOOR",
            "MILAI_AGENT_MAX_LIMIT",
        ):
            if name in os.environ:
                environment[name] = os.environ[name]
        self._process = subprocess.Popen(
            [str(executable), "--profile", profile],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=environment,
        )
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("MCP stdio pipes were not created")
        self._input: IO[str] = self._process.stdin
        self._output: IO[str] = self._process.stdout
        self._next_id = 1

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        deadline = time.monotonic() + 15
        selector = selectors.DefaultSelector()
        selector.register(self._output, selectors.EVENT_READ)
        try:
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise RuntimeError("MCP server exited before responding")
                if not selector.select(timeout=min(0.25, deadline - time.monotonic())):
                    continue
                line = self._output.readline()
                if not line:
                    continue
                message = json.loads(line)
                if not isinstance(message, dict):
                    continue
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError("MCP wire request returned an error")
                    result = message.get("result")
                    if not isinstance(result, dict):
                        raise RuntimeError("MCP wire result was not an object")
                    return result
                if "method" in message and "id" in message:
                    self._send(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "error": {
                                "code": -32601,
                                "message": "Method not supported",
                            },
                        }
                    )
        finally:
            selector.close()
        raise TimeoutError("MCP wire response timed out")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        value: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            value["params"] = params
        self._send(value)

    def close(self) -> None:
        self._input.close()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)

    def _send(self, value: dict[str, Any]) -> None:
        self._input.write(json.dumps(value, separators=(",", ":")) + "\n")
        self._input.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=("reader-lite", "reader-detail", "reader", "submitter", "operator"),
        required=True,
    )
    parser.add_argument(
        "--mode", choices=("2026-07-28", "legacy"), default="2026-07-28"
    )
    parser.add_argument("--tool")
    args = parser.parse_args()
    arguments = json.load(sys.stdin)
    if not isinstance(arguments, dict):
        raise TypeError("MCP arguments must be an object")
    host = _WireHost(args.profile)
    try:
        protocol = "2025-11-25" if args.mode == "legacy" else "2026-07-28"
        meta: dict[str, Any] = {}
        if args.mode == "legacy":
            initialized = host.request(
                "initialize",
                {
                    "protocolVersion": protocol,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "milai-independent-wire-smoke",
                        "version": "0.1.0",
                    },
                },
            )
            host.notify("notifications/initialized")
            negotiated = initialized.get("protocolVersion")
        else:
            meta = {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": protocol,
                    "io.modelcontextprotocol/clientInfo": {
                        "name": "milai-independent-wire-smoke",
                        "version": "0.1.0",
                    },
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            }
            discovered = host.request("server/discover", meta)
            if protocol not in discovered.get("supportedVersions", []):
                raise RuntimeError("MCP modern protocol was not advertised")
            negotiated = protocol
        catalog = host.request("tools/list", meta)
        tools = catalog.get("tools", [])
        names = [str(tool["name"]) for tool in tools if isinstance(tool, dict)]
        result: dict[str, Any] = {
            "host": "independent-jsonrpc-wire",
            "protocol_version": negotiated,
            "tools": names,
        }
        if args.tool:
            result["call"] = host.request(
                "tools/call",
                {"name": args.tool, "arguments": arguments, **meta},
            )
        json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
    finally:
        host.close()


if __name__ == "__main__":
    main()
