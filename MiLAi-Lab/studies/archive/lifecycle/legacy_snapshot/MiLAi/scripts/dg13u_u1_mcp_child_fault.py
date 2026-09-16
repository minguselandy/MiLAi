#!/usr/bin/env python3
"""Digest-bound, run-owned stdio MCP child fault fixtures for DG13U U1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import stat
import sys
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import FrameType
from typing import Any, Literal

FaultMode = Literal["DOWN", "MALFORMED", "TIMEOUT"]

_LEDGER_SCHEMA = "milai.dg13u.u1-mcp-child-fault-ledger.v1"
_CLEANUP_SCHEMA = "milai.dg13u.u1-mcp-child-fault-cleanup.v1"
_BUILDER_SCHEMA = "milai.dg13u.u1-mcp-child-fault-builder.v1"
_MALFORMED_FRAME = b"not-json\n"
_ALLOWED_METHODS = {
    "initialize",
    "notifications/initialized",
    "tools/list",
    "tools/call",
}
_ALLOWED_TOP_LEVEL_KEYS = {"jsonrpc", "id", "method", "params"}
_ALLOWED_PARAM_KEYS = {
    "protocolVersion",
    "capabilities",
    "clientInfo",
    "name",
    "arguments",
}


class ChildFaultError(RuntimeError):
    """A bounded configuration or child-fixture failure."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_absolute(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return path


def _reject_symlink_chain(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise ValueError("symlink paths are forbidden")
        if current == current.parent:
            return
        current = current.parent


def _prepare_parent(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _reject_symlink_chain(path.parent)
    current = path.parent.lstat()
    if not stat.S_ISDIR(current.st_mode) or stat.S_IMODE(current.st_mode) & 0o022:
        raise ValueError("artifact parent must be an owner-controlled directory")


def _atomic_write(
    path: Path,
    payload: bytes,
    *,
    mode: int,
    replace: bool,
) -> None:
    _prepare_parent(path)
    if path.is_symlink():
        raise FileExistsError(path)
    if not replace and path.exists():
        raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
        os.chmod(path, mode)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: Mapping[str, Any], *, replace: bool) -> None:
    _atomic_write(path, _canonical_bytes(value) + b"\n", mode=0o600, replace=replace)


def _source_path() -> Path:
    return Path(__file__).resolve()


def _validate_builder(
    mode: str,
    executable_path: Path,
    ledger_path: Path,
    cleanup_receipt_path: Path,
    manifest_path: Path | None,
    timeout_delay_seconds: float,
    max_frame_bytes: int,
) -> None:
    if mode not in {"DOWN", "MALFORMED", "TIMEOUT"}:
        raise ValueError("mode must be DOWN, MALFORMED, or TIMEOUT")
    paths = [
        _require_absolute(executable_path, "executable_path"),
        _require_absolute(ledger_path, "ledger_path"),
        _require_absolute(cleanup_receipt_path, "cleanup_receipt_path"),
    ]
    if manifest_path is not None:
        paths.append(_require_absolute(manifest_path, "manifest_path"))
    if len(set(paths)) != len(paths):
        raise ValueError("fixture paths must be distinct")
    if not 0.01 <= timeout_delay_seconds <= 5.0:
        raise ValueError("timeout_delay_seconds must be in [0.01, 5.0]")
    if (
        not isinstance(max_frame_bytes, int)
        or isinstance(max_frame_bytes, bool)
        or not 1_024 <= max_frame_bytes <= 2_097_152
    ):
        raise ValueError("max_frame_bytes must be in [1024, 2097152]")
    for path in paths:
        _reject_symlink_chain(path)
        if path.exists():
            raise FileExistsError(path)


def _wrapper_bytes(
    *,
    source: Path,
    source_sha256: str,
    mode: str,
    ledger_path: Path,
    cleanup_receipt_path: Path,
    timeout_delay_seconds: float,
    max_frame_bytes: int,
) -> bytes:
    argv = [
        str(source),
        "child",
        "--mode",
        mode,
        "--ledger",
        str(ledger_path),
        "--cleanup-receipt",
        str(cleanup_receipt_path),
        "--timeout-delay-seconds",
        str(timeout_delay_seconds),
        "--max-frame-bytes",
        str(max_frame_bytes),
        "--expected-source-sha256",
        source_sha256,
    ]
    return (
        "#!/usr/bin/python3\n"
        "import hashlib\n"
        "import os\n"
        "import sys\n"
        f"source = {str(source)!r}\n"
        f"expected = {source_sha256!r}\n"
        "try:\n"
        "    with open(source, 'rb') as stream:\n"
        "        observed = hashlib.sha256(stream.read()).hexdigest()\n"
        "except OSError:\n"
        "    raise SystemExit(70)\n"
        "if observed != expected:\n"
        "    raise SystemExit(71)\n"
        f"argv = {argv!r} + sys.argv[1:]\n"
        "os.execv('/usr/bin/python3', ['/usr/bin/python3', *argv])\n"
    ).encode()


def build_child_fixture(
    mode: str,
    *,
    executable_path: str | Path,
    ledger_path: str | Path,
    cleanup_receipt_path: str | Path,
    manifest_path: str | Path | None = None,
    timeout_delay_seconds: float = 1.0,
    max_frame_bytes: int = 65_536,
) -> dict[str, Any]:
    """Build one policy-digestable executable bound to this exact source."""

    executable = Path(executable_path)
    ledger = Path(ledger_path)
    receipt = Path(cleanup_receipt_path)
    manifest = Path(manifest_path) if manifest_path is not None else None
    _validate_builder(
        mode,
        executable,
        ledger,
        receipt,
        manifest,
        timeout_delay_seconds,
        max_frame_bytes,
    )
    source = _source_path()
    source_sha256 = _sha256(source)
    wrapper = _wrapper_bytes(
        source=source,
        source_sha256=source_sha256,
        mode=mode,
        ledger_path=ledger,
        cleanup_receipt_path=receipt,
        timeout_delay_seconds=timeout_delay_seconds,
        max_frame_bytes=max_frame_bytes,
    )
    created: list[Path] = []
    try:
        _atomic_write(executable, wrapper, mode=0o700, replace=False)
        created.append(executable)
        result = {
            "schema": _BUILDER_SCHEMA,
            "mode": mode,
            "mcp_executable": str(executable),
            "mcp_executable_sha256": hashlib.sha256(wrapper).hexdigest(),
            "source_path": str(source),
            "source_sha256": source_sha256,
            "ledger_path": str(ledger),
            "cleanup_receipt_path": str(receipt),
            "timeout_delay_seconds": timeout_delay_seconds,
            "max_frame_bytes": max_frame_bytes,
            "logical_request_maximum": 1,
            "automatic_retries": 0,
        }
        if manifest is not None:
            _write_json(manifest, result, replace=False)
            created.append(manifest)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return result


def _request_inventory(raw: bytes) -> dict[str, Any]:
    inventory: dict[str, Any] = {
        "frame_bytes": len(raw) + 1,
        "frame_sha256": hashlib.sha256(raw + b"\n").hexdigest(),
        "json_kind": "invalid",
        "method": None,
        "params_keys": [],
        "request_id_sha256": None,
        "top_level_keys": [],
        "unknown_top_level_key_count": 0,
    }
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return inventory
    if not isinstance(value, dict):
        inventory["json_kind"] = type(value).__name__
        return inventory
    inventory["json_kind"] = "object"
    keys = {key for key in value if isinstance(key, str)}
    inventory["top_level_keys"] = sorted(keys & _ALLOWED_TOP_LEVEL_KEYS)
    inventory["unknown_top_level_key_count"] = len(keys - _ALLOWED_TOP_LEVEL_KEYS)
    method = value.get("method")
    inventory["method"] = method if method in _ALLOWED_METHODS else "OTHER"
    params = value.get("params")
    if isinstance(params, dict):
        inventory["params_keys"] = sorted(set(params) & _ALLOWED_PARAM_KEYS)
    if "id" in value:
        inventory["request_id_sha256"] = hashlib.sha256(
            _canonical_bytes(value["id"])
        ).hexdigest()
    return inventory


def _read_one_frame(max_frame_bytes: int) -> tuple[bytes | None, bool, int]:
    buffer = bytearray()
    while b"\n" not in buffer and len(buffer) <= max_frame_bytes:
        block = os.read(sys.stdin.fileno(), min(4_096, max_frame_bytes + 1))
        if not block:
            break
        buffer.extend(block)
    if b"\n" not in buffer:
        return None, False, len(buffer)
    raw, _, remainder = buffer.partition(b"\n")
    if len(raw) + 1 > max_frame_bytes:
        return None, bool(remainder), len(buffer)
    return bytes(raw), bool(remainder), len(buffer)


def _initial_ledger(
    mode: str, profile: str, source_sha256: str, max_frame_bytes: int
) -> dict[str, Any]:
    return {
        "schema": _LEDGER_SCHEMA,
        "mode": mode,
        "profile": profile,
        "source_sha256": source_sha256,
        "active": True,
        "logical_request_maximum": 1,
        "logical_requests": 0,
        "automatic_retries": 0,
        "additional_frame_detected": False,
        "max_frame_bytes": max_frame_bytes,
        "raw_request_persisted": False,
        "request_credentials_persisted": False,
        "events": [],
    }


def _run_child(args: argparse.Namespace) -> int:
    ledger_path = _require_absolute(args.ledger, "ledger")
    receipt_path = _require_absolute(args.cleanup_receipt, "cleanup_receipt")
    if ledger_path == receipt_path:
        raise ChildFaultError("CHILD_ARTIFACT_PATHS_COLLIDE")
    source_sha256 = _sha256(_source_path())
    if source_sha256 != args.expected_source_sha256:
        raise ChildFaultError("CHILD_SOURCE_DIGEST_MISMATCH")
    if ledger_path.exists() or ledger_path.is_symlink():
        raise ChildFaultError("CHILD_LEDGER_ALREADY_EXISTS")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ChildFaultError("CHILD_CLEANUP_RECEIPT_ALREADY_EXISTS")

    stop = threading.Event()
    signal_received: list[str] = []

    def handle(signum: int, _frame: FrameType | None) -> None:
        signal_received[:] = [signal.Signals(signum).name]
        stop.set()

    previous_term = signal.signal(signal.SIGTERM, handle)
    previous_int = signal.signal(signal.SIGINT, handle)
    ledger = _initial_ledger(
        args.mode, args.profile, source_sha256, args.max_frame_bytes
    )
    _write_json(ledger_path, ledger, replace=False)
    exit_code = 0
    stdout_protocol_bytes = 0
    try:
        if args.mode == "DOWN":
            ledger["terminal_outcome"] = "CONTROLLED_EXIT_BEFORE_INITIALIZE"
            exit_code = 20
        else:
            raw, additional, observed_bytes = _read_one_frame(args.max_frame_bytes)
            ledger["logical_requests"] = 1
            ledger["additional_frame_detected"] = additional
            if raw is None:
                ledger["events"] = [
                    {
                        "logical_request": 1,
                        "outcome": "REQUEST_FRAME_TOO_LARGE",
                        "request": {
                            "frame_bytes": observed_bytes,
                            "frame_sha256": None,
                            "json_kind": "not_inspected",
                        },
                    }
                ]
                ledger["terminal_outcome"] = "REQUEST_FRAME_TOO_LARGE"
                exit_code = 21
            else:
                inventory = _request_inventory(raw)
                outcome = (
                    "MALFORMED_RESPONSE_SENT"
                    if args.mode == "MALFORMED"
                    else "DELAYING"
                )
                ledger["events"] = [
                    {
                        "logical_request": 1,
                        "outcome": outcome,
                        "request": inventory,
                    }
                ]
                _write_json(ledger_path, ledger, replace=True)
                if args.mode == "MALFORMED":
                    stdout_protocol_bytes = os.write(
                        sys.stdout.fileno(), _MALFORMED_FRAME
                    )
                    ledger["terminal_outcome"] = "MALFORMED_RESPONSE_SENT"
                else:
                    terminated = stop.wait(args.timeout_delay_seconds)
                    outcome = (
                        "TERMINATED_DURING_TIMEOUT" if terminated else "TIMEOUT_ELAPSED"
                    )
                    ledger["events"][0]["outcome"] = outcome
                    ledger["terminal_outcome"] = outcome
        ledger["active"] = False
        _write_json(ledger_path, ledger, replace=True)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        receipt = {
            "schema": _CLEANUP_SCHEMA,
            "status": "PASS",
            "mode": args.mode,
            "profile": args.profile,
            "source_sha256": source_sha256,
            "logical_requests": ledger["logical_requests"],
            "automatic_retries": 0,
            "signal_received": signal_received[0] if signal_received else None,
            "stdout_protocol_bytes": stdout_protocol_bytes,
            "raw_request_persisted": False,
            "request_credentials_persisted": False,
        }
        _write_json(receipt_path, receipt, replace=False)
    return exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DG13-U1 stdio MCP child fault fixture")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build one digest-bound child executable")
    build.add_argument("--mode", choices=("DOWN", "MALFORMED", "TIMEOUT"), required=True)
    build.add_argument("--executable", type=Path, required=True)
    build.add_argument("--ledger", type=Path, required=True)
    build.add_argument("--cleanup-receipt", type=Path, required=True)
    build.add_argument("--manifest", type=Path)
    build.add_argument("--timeout-delay-seconds", type=float, default=1.0)
    build.add_argument("--max-frame-bytes", type=int, default=65_536)
    child = commands.add_parser("child", help=argparse.SUPPRESS)
    child.add_argument("--mode", choices=("DOWN", "MALFORMED", "TIMEOUT"), required=True)
    child.add_argument("--ledger", type=Path, required=True)
    child.add_argument("--cleanup-receipt", type=Path, required=True)
    child.add_argument("--timeout-delay-seconds", type=float, required=True)
    child.add_argument("--max-frame-bytes", type=int, required=True)
    child.add_argument("--expected-source-sha256", required=True)
    child.add_argument("--profile", required=True)
    child.add_argument("--max-retries", type=_zero_retries)
    return parser


def _zero_retries(value: str) -> int:
    if value != "0":
        raise argparse.ArgumentTypeError("--max-retries must be exactly 0")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_child_fixture(
                args.mode,
                executable_path=args.executable,
                ledger_path=args.ledger,
                cleanup_receipt_path=args.cleanup_receipt,
                manifest_path=args.manifest,
                timeout_delay_seconds=args.timeout_delay_seconds,
                max_frame_bytes=args.max_frame_bytes,
            )
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
        return _run_child(args)
    except (ChildFaultError, FileExistsError, OSError, ValueError) as exc:
        print(f"dg13u_u1_mcp_child_fault: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
