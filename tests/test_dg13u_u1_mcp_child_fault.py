from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from scripts.dg13u_u1_mcp_child_fault import build_child_fixture

PRIVATE_PROMPT = "private child prompt must not persist"
PRIVATE_TOKEN = "private child token must not persist"


def _build(tmp_path: Path, mode: str, **kwargs: object) -> tuple[Path, Path, Path]:
    executable = tmp_path / f"mcp-child-{mode.lower()}"
    ledger = tmp_path / f"{mode.lower()}-ledger.json"
    receipt = tmp_path / f"{mode.lower()}-cleanup.json"
    build_child_fixture(
        mode,
        executable_path=executable,
        ledger_path=ledger,
        cleanup_receipt_path=receipt,
        **kwargs,
    )
    return executable, ledger, receipt


def _request(identifier: str = "one") -> bytes:
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": identifier,
                "method": "initialize",
                "params": {
                    "capabilities": {},
                    "private_prompt": PRIVATE_PROMPT,
                    "private_token": PRIVATE_TOKEN,
                },
            }
        ).encode()
        + b"\n"
    )


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _broker_module() -> ModuleType:
    source = (
        Path(__file__).parents[1]
        / "integrations/openworker-mcp/src/milai_openworker_mcp/broker.py"
    )
    spec = importlib.util.spec_from_file_location("dg13u_child_fault_broker", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_builder_creates_digest_bound_private_executable_and_manifest(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "fixture/mcp-child"
    ledger = tmp_path / "evidence/ledger.json"
    receipt = tmp_path / "evidence/cleanup.json"
    manifest = tmp_path / "evidence/builder.json"

    result = build_child_fixture(
        "MALFORMED",
        executable_path=executable,
        ledger_path=ledger,
        cleanup_receipt_path=receipt,
        manifest_path=manifest,
    )

    assert result["mode"] == "MALFORMED"
    assert result["mcp_executable"] == str(executable)
    assert result["mcp_executable_sha256"] == hashlib.sha256(
        executable.read_bytes()
    ).hexdigest()
    assert len(result["source_sha256"]) == 64
    assert stat.S_IMODE(executable.stat().st_mode) == 0o700
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    assert _json(manifest) == result
    assert not ledger.exists()
    assert not receipt.exists()


def test_actual_broker_policy_accepts_builder_executable_and_exact_digest(
    tmp_path: Path,
) -> None:
    executable, _ledger, _receipt = _build(tmp_path, "MALFORMED")
    broker = _broker_module()
    policy_path = tmp_path / "policy.json"
    policy = {
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "profile": "reader-lite",
        "socket_path": str(tmp_path / "reader-lite.sock"),
        "socket_mode": "0600",
        "allowed_peer_uids": [0],
        "mcp_executable": str(executable),
        "mcp_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "base_url": "http://127.0.0.1:18080",
        "scope": {"project_ids": ["synthetic"]},
        "required_authority": "INFORMATIONAL",
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_limit": 3,
        "max_connections": 1,
        "child_shutdown_seconds": 1,
        "mcp_max_retries": 0,
    }
    policy_path.write_bytes(json.dumps(policy).encode() + b"\n")
    policy_path.chmod(0o600)

    loaded = broker.Policy.load(policy_path)

    assert loaded.mcp_executable == executable
    assert loaded.mcp_executable_sha256 == policy["mcp_executable_sha256"]
    assert loaded.child_argv() == [
        str(executable),
        "--profile",
        "reader-lite",
        "--max-retries",
        "0",
    ]
    loaded.validate_executable()


def test_down_exits_before_initialize_with_zero_attempt_receipts(tmp_path: Path) -> None:
    executable, ledger, receipt = _build(tmp_path, "DOWN")

    completed = subprocess.run(
        [str(executable), "--profile", "reader-lite", "--max-retries", "0"],
        input=_request(),
        capture_output=True,
        check=False,
        timeout=3,
    )

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert _json(ledger)["logical_requests"] == 0
    cleanup = _json(receipt)
    assert cleanup["status"] == "PASS"
    assert cleanup["logical_requests"] == 0
    assert cleanup["automatic_retries"] == 0


def test_malformed_emits_only_bounded_non_json_and_redacted_one_request_ledger(
    tmp_path: Path,
) -> None:
    executable, ledger, receipt = _build(tmp_path, "MALFORMED")

    completed = subprocess.run(
        [str(executable), "--profile", "reader-lite"],
        input=_request(),
        capture_output=True,
        check=False,
        timeout=3,
    )

    assert completed.returncode == 0
    assert completed.stdout == b"not-json\n"
    evidence = _json(ledger)
    encoded = json.dumps(evidence, sort_keys=True)
    assert evidence["logical_requests"] == 1
    assert evidence["automatic_retries"] == 0
    assert evidence["events"][0]["request"]["method"] == "initialize"
    assert len(evidence["events"][0]["request"]["frame_sha256"]) == 64
    assert PRIVATE_PROMPT not in encoded
    assert PRIVATE_TOKEN not in encoded
    assert stat.S_IMODE(ledger.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600


def test_child_rejects_nonzero_broker_retry_argument_before_artifact_mutation(
    tmp_path: Path,
) -> None:
    executable, ledger, receipt = _build(tmp_path, "MALFORMED")

    completed = subprocess.run(
        [str(executable), "--profile", "reader-lite", "--max-retries", "1"],
        input=_request(),
        capture_output=True,
        check=False,
        timeout=3,
    )

    assert completed.returncode != 0
    assert not ledger.exists()
    assert not receipt.exists()


def test_timeout_accepts_sigterm_and_writes_private_cleanup_receipt(
    tmp_path: Path,
) -> None:
    executable, ledger, receipt = _build(
        tmp_path, "TIMEOUT", timeout_delay_seconds=5.0
    )
    process = subprocess.Popen(
        [str(executable), "--profile", "reader-lite"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    process.stdin.write(_request())
    process.stdin.flush()
    deadline = time.monotonic() + 3
    while not ledger.exists():
        assert process.poll() is None
        assert time.monotonic() < deadline
        time.sleep(0.01)

    process.terminate()
    stdout, stderr = process.communicate(timeout=3)

    assert process.returncode == 0, stderr
    assert stdout == b""
    evidence = _json(ledger)
    assert evidence["logical_requests"] == 1
    assert evidence["events"][0]["outcome"] == "TERMINATED_DURING_TIMEOUT"
    cleanup = _json(receipt)
    assert cleanup["signal_received"] == "SIGTERM"
    assert cleanup["status"] == "PASS"
    assert cleanup["stdout_protocol_bytes"] == 0


def test_second_request_is_detected_but_never_counted_or_processed(
    tmp_path: Path,
) -> None:
    executable, ledger, _receipt = _build(tmp_path, "MALFORMED")

    completed = subprocess.run(
        [str(executable), "--profile", "reader-lite"],
        input=_request("one") + _request("two"),
        capture_output=True,
        check=False,
        timeout=3,
    )

    assert completed.stdout == b"not-json\n"
    evidence = _json(ledger)
    assert evidence["logical_requests"] == 1
    assert evidence["additional_frame_detected"] is True
    assert len(evidence["events"]) == 1
    assert "two" not in json.dumps(evidence)


def test_oversize_frame_fails_without_hashing_or_echoing_body(tmp_path: Path) -> None:
    executable, ledger, receipt = _build(
        tmp_path, "MALFORMED", max_frame_bytes=1_024
    )
    payload = (PRIVATE_PROMPT.encode() * 80) + b"\n"

    completed = subprocess.run(
        [str(executable), "--profile", "reader-lite"],
        input=payload,
        capture_output=True,
        check=False,
        timeout=3,
    )

    assert completed.returncode != 0
    assert completed.stdout == b""
    evidence = _json(ledger)
    assert evidence["logical_requests"] == 1
    assert evidence["events"][0]["outcome"] == "REQUEST_FRAME_TOO_LARGE"
    assert evidence["events"][0]["request"]["frame_sha256"] is None
    assert PRIVATE_PROMPT not in json.dumps(evidence)
    assert _json(receipt)["status"] == "PASS"


@pytest.mark.parametrize(
    ("mode", "kwargs", "message"),
    (
        ("UNKNOWN", {}, "mode"),
        ("TIMEOUT", {"timeout_delay_seconds": 5.01}, "timeout_delay_seconds"),
        ("MALFORMED", {"max_frame_bytes": 100}, "max_frame_bytes"),
    ),
)
def test_invalid_builder_configuration_mutates_nothing(
    tmp_path: Path, mode: str, kwargs: dict[str, object], message: str
) -> None:
    parent = tmp_path / "new"
    with pytest.raises(ValueError, match=message):
        build_child_fixture(
            mode,
            executable_path=parent / "child",
            ledger_path=parent / "ledger",
            cleanup_receipt_path=parent / "receipt",
            **kwargs,
        )
    assert not parent.exists()


def test_builder_rejects_relative_paths_duplicates_and_overwrite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        build_child_fixture(
            "DOWN",
            executable_path=Path("relative"),
            ledger_path=tmp_path / "ledger",
            cleanup_receipt_path=tmp_path / "receipt",
        )
    with pytest.raises(ValueError, match="distinct"):
        build_child_fixture(
            "DOWN",
            executable_path=tmp_path / "same",
            ledger_path=tmp_path / "same",
            cleanup_receipt_path=tmp_path / "receipt",
        )
    executable, ledger, receipt = _build(tmp_path, "DOWN")
    original = executable.read_bytes()
    with pytest.raises(FileExistsError):
        build_child_fixture(
            "DOWN",
            executable_path=executable,
            ledger_path=ledger,
            cleanup_receipt_path=receipt,
        )
    assert executable.read_bytes() == original


def test_cli_help_and_build_are_bounded(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts/dg13u_u1_mcp_child_fault.py"
    help_result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0
    assert "build" in help_result.stdout

    executable = tmp_path / "cli-child"
    ledger = tmp_path / "cli-ledger.json"
    receipt = tmp_path / "cli-cleanup.json"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "build",
            "--mode",
            "DOWN",
            "--executable",
            str(executable),
            "--ledger",
            str(ledger),
            "--cleanup-receipt",
            str(receipt),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["mcp_executable"] == str(executable)
    assert value["mcp_executable_sha256"] == hashlib.sha256(
        executable.read_bytes()
    ).hexdigest()
