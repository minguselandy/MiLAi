from __future__ import annotations

import http.client
import importlib
import json
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from scripts.dg13u_u1_runtime_fault import (
    RuntimeFaultInjector,
    closed_loopback_endpoint_identity,
)

PRIVATE_PROMPT = "private synthetic Runtime prompt that must never enter evidence"
PRIVATE_TOKEN = "private-runtime-token-that-must-never-enter-evidence"


def _artifact(tmp_path: Path, name: str = "runtime-fault-receipt.json") -> Path:
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    return evidence / name


def _receipt(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _post(
    injector: RuntimeFaultInjector,
    *,
    body: bytes | None = None,
    timeout: float = 2.0,
) -> bytes:
    payload = body or json.dumps({"query": PRIVATE_PROMPT}).encode()
    request = urllib.request.Request(
        injector.prepare_context_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {PRIVATE_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        assert response.status == 200
        return response.read()


def _client_types() -> tuple[type[object], type[Exception]]:
    source = Path(__file__).parents[1] / "integrations/python-client/src"
    sys.path.insert(0, str(source))
    client = importlib.import_module("milai_client")
    return client.MilaiClient, client.MilaiClientError


def test_malformed_targets_prepare_context_after_real_client_negotiation(
    tmp_path: Path,
) -> None:
    client_type, error_type = _client_types()
    artifact = _artifact(tmp_path)
    with RuntimeFaultInjector(
        "MALFORMED",
        artifact_path=artifact,
        run_id="dg13u-runtime-malformed",
        delay_seconds=0.1,
    ) as injector:
        client = client_type(
            injector.base_url,
            PRIVATE_TOKEN,
            timeout_seconds=1.0,
            max_retries=0,
        )
        with pytest.raises(error_type, match="invalid JSON"):
            client.prepare_context({"query": PRIVATE_PROMPT})
        client.close()
        assert injector.request_count == 1

    receipt = _receipt(artifact)
    encoded = json.dumps(receipt, sort_keys=True)
    assert receipt["request_count"] == 1
    assert receipt["capability_request_count"] == 1
    assert receipt["automatic_retries"] == 0
    assert receipt["faults_injected"] == 1
    assert receipt["cleanup"]["server_stopped"] is True
    assert receipt["reconciliation"]["single_request"] is True
    assert receipt["reconciliation"]["raw_request_persisted"] is False
    assert PRIVATE_PROMPT not in encoded
    assert PRIVATE_TOKEN not in encoded
    assert "authorization" not in encoded.lower()
    assert "body_sha256" not in encoded
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
    assert not list(artifact.parent.glob(f".{artifact.name}.*.tmp"))


def test_unavailable_is_schema_valid_and_maps_to_typed_provider_prohibition(
    tmp_path: Path,
) -> None:
    client_type, _ = _client_types()
    task_memory = importlib.import_module("milai_client.task_memory")
    artifact = _artifact(tmp_path)
    with RuntimeFaultInjector(
        "UNAVAILABLE",
        artifact_path=artifact,
        run_id="dg13u-runtime-unavailable",
        delay_seconds=0.1,
    ) as injector:
        client = client_type(
            injector.base_url,
            PRIVATE_TOKEN,
            timeout_seconds=1.0,
            max_retries=0,
        )
        envelope = client.prepare_context({"query": PRIVATE_PROMPT})
        client.close()
        outcome = task_memory._terminal_outcome(envelope)

        assert envelope.status == "DEGRADED"
        assert envelope.reason == "CANONICAL_UNAVAILABLE"
        assert envelope.current_state_envelope is not None
        assert envelope.current_state_envelope.status == "CANONICAL_UNAVAILABLE"
        assert outcome.status == "MEMORY_REQUIRED_BUT_UNAVAILABLE"
        assert outcome.execution_action == "RETRY"
        assert outcome.provider_execution == "PROHIBITED"
        assert outcome.terminal_stage == "TRANSPORT"
        assert outcome.reason_code == "CANONICAL_UNAVAILABLE"
        assert injector.request_count == 1

    receipt = _receipt(artifact)
    encoded = json.dumps(receipt, sort_keys=True)
    assert receipt["request_count"] == 1
    assert receipt["capability_request_count"] == 1
    assert receipt["automatic_retries"] == 0
    assert receipt["faults_injected"] == 1
    assert receipt["reconciliation"]["response_is_valid_context"] is True
    assert receipt["cleanup"]["server_stopped"] is True
    assert PRIVATE_PROMPT not in encoded
    assert PRIVATE_TOKEN not in encoded
    assert "body" not in encoded.lower()
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600


def test_timeout_is_one_request_zero_retry_and_cleanup_interruptible(
    tmp_path: Path,
) -> None:
    client_type, error_type = _client_types()
    artifact = _artifact(tmp_path)
    injector = RuntimeFaultInjector(
        "TIMEOUT",
        artifact_path=artifact,
        run_id="dg13u-runtime-timeout",
        delay_seconds=5.0,
    ).start()
    client = client_type(
        injector.base_url,
        PRIVATE_TOKEN,
        timeout_seconds=0.05,
        max_retries=0,
    )
    errors: list[Exception] = []

    def invoke() -> None:
        try:
            client.prepare_context({"query": PRIVATE_PROMPT})
        except error_type as exc:
            errors.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    deadline = time.monotonic() + 2
    while injector.request_count != 1:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    started = time.monotonic()
    injector.stop()
    thread.join(timeout=2)
    client.close()

    assert not thread.is_alive()
    assert time.monotonic() - started < 1.0
    assert len(errors) == 1 and isinstance(errors[0], error_type)
    receipt = _receipt(artifact)
    assert receipt["request_count"] == 1
    assert receipt["automatic_retries"] == 0
    assert receipt["cleanup"] == {
        "attempted": True,
        "listener_closed": True,
        "server_stopped": True,
        "worker_threads_stopped": True,
    }
    assert receipt["reconciliation"]["single_request"] is True


def test_second_prepare_request_is_rejected_without_second_fault(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    with RuntimeFaultInjector(
        "MALFORMED",
        artifact_path=artifact,
        run_id="dg13u-runtime-second",
        delay_seconds=0.1,
    ) as injector:
        assert _post(injector).startswith(b'{"status"')
        with pytest.raises(urllib.error.HTTPError) as second:
            _post(injector)
        with second.value:
            assert second.value.code == 409

    receipt = _receipt(artifact)
    assert receipt["request_count"] == 1
    assert receipt["rejected_request_count"] == 1
    assert receipt["faults_injected"] == 1
    assert receipt["reconciliation"]["single_request"] is True


def test_oversize_body_consumes_only_attempt_and_persists_no_body(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    with RuntimeFaultInjector(
        "MALFORMED",
        artifact_path=artifact,
        run_id="dg13u-runtime-oversize",
        delay_seconds=0.1,
        max_body_bytes=32,
    ) as injector:
        connection = http.client.HTTPConnection(injector.host, injector.port, timeout=2)
        connection.request(
            "POST",
            "/v1/memory/prepare-context",
            body=b"x" * 33,
            headers={"Content-Length": "33", "Authorization": PRIVATE_TOKEN},
        )
        assert connection.getresponse().status == 413
        connection.close()
        with pytest.raises(urllib.error.HTTPError) as second:
            _post(injector)
        with second.value:
            assert second.value.code == 409

    receipt = _receipt(artifact)
    encoded = json.dumps(receipt, sort_keys=True)
    assert receipt["request_count"] == 1
    assert receipt["faults_injected"] == 0
    assert receipt["rejected_request_count"] == 1
    assert PRIVATE_TOKEN not in encoded
    assert "body" not in encoded.lower()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "DOWN"}, "mode must be UNAVAILABLE, MALFORMED, or TIMEOUT"),
        ({"run_id": "bad"}, "run_id is invalid"),
        ({"run_id": "dg13u-secret-runtime"}, "run_id is secret-like"),
        ({"delay_seconds": 0.0}, "delay_seconds must be in"),
        ({"delay_seconds": 15.01}, "delay_seconds must be in"),
        ({"host": "0.0.0.0"}, "host must be loopback IPv4"),
        ({"port": 65536}, "port must be in"),
        ({"max_body_bytes": 0}, "max_body_bytes must be in"),
    ],
)
def test_invalid_configuration_precedes_artifact_mutation(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    artifact = _artifact(tmp_path)
    options: dict[str, object] = {
        "mode": "MALFORMED",
        "artifact_path": artifact,
        "run_id": "dg13u-runtime-invalid",
        "delay_seconds": 0.1,
    }
    options.update(kwargs)
    with pytest.raises(ValueError, match=message):
        RuntimeFaultInjector(**options)  # type: ignore[arg-type]
    assert not artifact.exists()


def test_artifact_path_must_be_absolute_private_nonsecret_and_new(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="artifact_path must be absolute"):
        RuntimeFaultInjector(
            "MALFORMED",
            artifact_path=Path("relative.json"),
            run_id="dg13u-runtime-path",
            delay_seconds=0.1,
        )

    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="artifact_path is secret-like"):
        RuntimeFaultInjector(
            "MALFORMED",
            artifact_path=secrets / "receipt.json",
            run_id="dg13u-runtime-path",
            delay_seconds=0.1,
        )

    public = tmp_path / "public"
    public.mkdir(mode=0o770)
    with pytest.raises(ValueError, match="artifact parent mode is unsafe"):
        RuntimeFaultInjector(
            "MALFORMED",
            artifact_path=public / "receipt.json",
            run_id="dg13u-runtime-path",
            delay_seconds=0.1,
        )

    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="artifact parent must be a real directory"):
        RuntimeFaultInjector(
            "MALFORMED",
            artifact_path=linked / "receipt.json",
            run_id="dg13u-runtime-path",
            delay_seconds=0.1,
        )

    artifact = real / "receipt.json"
    artifact.write_text("owned elsewhere", encoding="utf-8")
    with pytest.raises(FileExistsError):
        RuntimeFaultInjector(
            "MALFORMED",
            artifact_path=artifact,
            run_id="dg13u-runtime-path",
            delay_seconds=0.1,
        )


def test_closed_down_endpoint_identity_is_loopback_hashed_and_not_listening() -> None:
    identity = closed_loopback_endpoint_identity()
    assert identity.base_url == f"http://127.0.0.1:{identity.port}"
    assert len(identity.endpoint_sha256) == 64
    assert identity.prebound_then_closed is True
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", identity.port), timeout=0.1)


def test_cli_sigterm_writes_final_private_cleanup_receipt(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "cli-runtime-fault.json")
    script = Path(__file__).parents[1] / "scripts/dg13u_u1_runtime_fault.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--artifact",
            str(artifact),
            "--run-id",
            "dg13u-runtime-cli",
            "--mode",
            "MALFORMED",
            "--delay-seconds",
            "0.1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout = ""
    stderr = ""
    communication_complete = False
    try:
        assert process.stdout is not None
        readiness = json.loads(process.stdout.readline())
        assert readiness["mode"] == "MALFORMED"
        assert readiness["endpoint"].startswith("http://127.0.0.1:")
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        communication_complete = True
    finally:
        if not communication_complete:
            if process.poll() is None:
                process.kill()
            stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 0, (stdout, stderr)
    receipt = _receipt(artifact)
    assert receipt["active"] is False
    assert receipt["cleanup"]["server_stopped"] is True
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
