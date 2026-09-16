from __future__ import annotations

import http.client
import json
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from scripts.dg13u_u1_provider_fault import ProviderFaultInjector

PRIVATE_PROMPT = "private synthetic prompt that must never enter evidence"
PRIVATE_TOKEN = "private-provider-token-that-must-never-enter-evidence"


def _post(
    injector: ProviderFaultInjector,
    *,
    timeout: float = 2.0,
    body: bytes | None = None,
) -> tuple[int, str, bytes]:
    payload = (
        body
        or json.dumps(
            {
                "model": "synthetic-model",
                "messages": [{"role": "user", "content": PRIVATE_PROMPT}],
                "stream": False,
            }
        ).encode()
    )
    request = urllib.request.Request(
        injector.endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {PRIVATE_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.headers.get_content_type(), response.read()


def _ledger(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_malformed_mode_returns_invalid_sse_and_redacted_ledger(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "evidence" / "provider-fault-ledger.json"

    with ProviderFaultInjector("MALFORMED", ledger_path=ledger_path) as injector:
        with urllib.request.urlopen(injector.health_url) as response:
            health = json.loads(response.read())
        status, content_type, response = _post(injector)

        assert health == {
            "mode": "MALFORMED",
            "native_attempts": 0,
            "status": "ok",
        }
        assert status == 200
        assert content_type == "text/event-stream"
        assert response == b"data: {invalid-json\n\n"
        assert injector.native_attempts == 1

    ledger = _ledger(ledger_path)
    encoded = json.dumps(ledger, sort_keys=True)
    assert ledger["native_attempts"] == 1
    assert ledger["automatic_retries"] == 0
    assert ledger["active"] is False
    assert ledger["events"][0]["request"] == {
        "authorization_present": True,
        "body_bytes": 147,
        "body_sha256": ledger["events"][0]["request"]["body_sha256"],
        "json_kind": "object",
        "message_count": 1,
        "message_roles": ["user"],
        "top_level_keys": ["messages", "model", "stream"],
    }
    assert len(ledger["events"][0]["request"]["body_sha256"]) == 64
    assert PRIVATE_PROMPT not in encoded
    assert PRIVATE_TOKEN not in encoded
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600
    assert not list(ledger_path.parent.glob(f".{ledger_path.name}.*.tmp"))


def test_timeout_records_one_attempt_before_client_disconnect(tmp_path: Path) -> None:
    ledger_path = tmp_path / "timeout.json"

    with ProviderFaultInjector(
        "TIMEOUT", ledger_path=ledger_path, timeout_delay_seconds=0.15
    ) as injector:
        with pytest.raises((TimeoutError, urllib.error.URLError)):
            _post(injector, timeout=0.02)

        deadline = time.monotonic() + 2
        while _ledger(ledger_path)["events"][0]["outcome"] == "DELAYING":
            assert time.monotonic() < deadline
            time.sleep(0.01)

    ledger = _ledger(ledger_path)
    assert ledger["native_attempts"] == 1
    assert ledger["events"][0]["outcome"] == "CLIENT_DISCONNECTED"


def test_exact_route_and_bounded_body_are_fail_closed(tmp_path: Path) -> None:
    ledger_path = tmp_path / "bounded.json"
    with ProviderFaultInjector(
        "MALFORMED", ledger_path=ledger_path, max_body_bytes=32
    ) as injector:
        with pytest.raises(urllib.error.HTTPError) as wrong_path:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{injector.base_url}/v1/chat/completions/",
                    data=b"{}",
                    method="POST",
                )
            )
        with wrong_path.value:
            assert wrong_path.value.code == 404
        assert injector.native_attempts == 0

        connection = http.client.HTTPConnection(injector.host, injector.port, timeout=2)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=b"x" * 33,
            headers={"Content-Length": "33"},
        )
        assert connection.getresponse().status == 413
        connection.close()
        assert injector.native_attempts == 1

    event = _ledger(ledger_path)["events"][0]
    assert event["outcome"] == "BODY_TOO_LARGE"
    assert event["request"]["body_sha256"] is None
    assert event["request"]["body_bytes"] == 33


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "DOWN"}, "mode must be MALFORMED or TIMEOUT"),
        (
            {"mode": "TIMEOUT", "timeout_delay_seconds": 5.01},
            "timeout_delay_seconds must be in",
        ),
        ({"mode": "MALFORMED", "host": "0.0.0.0"}, "host must be loopback"),
    ],
)
def test_invalid_configuration_fails_before_filesystem_mutation(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    ledger = tmp_path / "new-parent" / "ledger.json"
    with pytest.raises(ValueError, match=message):
        ProviderFaultInjector(ledger_path=ledger, **kwargs)
    assert not ledger.parent.exists()


def test_existing_ledger_is_never_overwritten(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text("owned by another run", encoding="utf-8")
    injector = ProviderFaultInjector("MALFORMED", ledger_path=ledger)

    with pytest.raises(FileExistsError):
        injector.start()

    assert ledger.read_text(encoding="utf-8") == "owned by another run"


def test_cli_ready_file_health_and_sigterm_shutdown(tmp_path: Path) -> None:
    ledger = tmp_path / "cli-ledger.json"
    ready = tmp_path / "cli-ready.json"
    script = Path(__file__).parents[1] / "scripts/dg13u_u1_provider_fault.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--mode",
            "MALFORMED",
            "--ledger",
            str(ledger),
            "--ready-file",
            str(ready),
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        readiness = json.loads(ready.read_text(encoding="utf-8"))
        with urllib.request.urlopen(readiness["health_url"]) as response:
            health = json.loads(response.read())
        assert health["status"] == "ok"
        assert stat.S_IMODE(ready.stat().st_mode) == 0o600
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 0, (stdout, stderr)
    assert _ledger(ledger)["active"] is False
    assert _ledger(ledger)["native_attempts"] == 0
    assert PRIVATE_TOKEN not in ledger.read_text(encoding="utf-8")


def test_stop_is_idempotent_and_releases_port(tmp_path: Path) -> None:
    injector = ProviderFaultInjector("MALFORMED", ledger_path=tmp_path / "stop.json")
    injector.start()
    port = injector.port
    injector.stop()
    injector.stop()

    with pytest.raises(OSError):
        connection = http.client.HTTPConnection(injector.host, port, timeout=0.1)
        connection.connect()
