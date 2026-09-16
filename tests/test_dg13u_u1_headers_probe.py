from __future__ import annotations

import json
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import dg13u_u1_headers_probe as probe


def _configure_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    runs = root / "var/dg13/runs"
    temporary = root / "var/dg13/tmp"
    source = root / "scripts/dg13u_u1_headers_probe.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic probe source\n", encoding="utf-8")
    config = root / "integrations/openworker-mcp/openworker/opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "model": f"openworker/{probe.EXACT_MODEL_ID}",
                "mcp": {
                    "milai": {
                        "type": "local",
                        "command": ["/synthetic/milai-mcp-relay"],
                        "enabled": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "ROOT", root)
    monkeypatch.setattr(probe, "RUNS_ROOT", runs)
    monkeypatch.setattr(probe, "TMP_ROOT", temporary)
    monkeypatch.setattr(probe, "PROBE_SOURCE", source)
    monkeypatch.setattr(probe, "_is_cra_path", lambda _path: True)
    return runs, temporary


def _body() -> bytes:
    return json.dumps(
        {
            "model": probe.EXACT_MODEL_ID,
            "messages": [
                {"role": "system", "content": "private system"},
                {"role": "user", "content": "private synthetic NONE prompt"},
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
            "tools": [
                {"type": "function", "function": {"name": "ordinary_tool"}}
            ],
            "tool_choice": "auto",
            "temperature": 0.2,
        }
    ).encode()


def test_request_inventory_accepts_only_frozen_subset_and_discards_raw_content() -> None:
    inventory = probe._request_inventory(_body())
    encoded = json.dumps(inventory, sort_keys=True)

    assert inventory["status"] == "PASS"
    assert inventory["model"] == probe.EXACT_MODEL_ID
    assert inventory["stream"] is True
    assert inventory["stream_options"] == {"include_usage": True}
    assert inventory["message_roles"] == ["system", "user"]
    assert inventory["tool_names"] == ["ordinary_tool"]
    assert inventory["request_sha256"] == probe._sha256_bytes(_body())
    assert "private system" not in encoded
    assert "private synthetic NONE prompt" not in encoded

    unsupported = json.loads(_body())
    unsupported["user"] = "body-task-selector"
    with pytest.raises(probe.ProbeError, match="unsupported provider request field"):
        probe._request_inventory(json.dumps(unsupported).encode())


def test_capture_requires_exact_bearer_and_single_native_headers_without_persisting_raw() -> None:
    token = "synthetic-private-ingress-token"
    headers = {
        "Authorization": [f"Bearer {token}"],
        "X-MiLAi-Host-Instance": ["7880d4bb-a56d-4f7d-8f8f-478281e38ea0"],
        "X-MiLAi-Task-Session": ["ses_private_123"],
        "X-MiLAi-Task-Operation": ["msg_private_456"],
    }
    evidence = probe._redacted_ingress_evidence(
        headers,
        expected_token=token,
        session_id="ses_private_123",
        message_id="msg_private_456",
    )
    encoded = json.dumps(evidence, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["authorization"] == "EXACT_SINGLE_BEARER_MATCH"
    assert evidence["header_cardinality"] == {
        name: 1 for name in probe.HEADER_NAMES
    }
    assert token not in encoded
    assert "ses_private_123" not in encoded
    assert "msg_private_456" not in encoded

    duplicated = {name: list(values) for name, values in headers.items()}
    duplicated["X-MiLAi-Task-Session"].append("ses_conflict")
    with pytest.raises(probe.ProbeError, match="header cardinality"):
        probe._redacted_ingress_evidence(
            duplicated,
            expected_token=token,
            session_id="ses_private_123",
            message_id="msg_private_456",
        )


def test_probe_uses_owned_bridge_u1_image_zero_real_calls_and_full_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    commands: list[list[str]] = []
    ingress_token = "synthetic-private-ingress-token"

    def fake_command(command: list[str], *, timeout: int = 60) -> str:
        del timeout
        commands.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": "sha256:u1-exact-image",
                        "RepoDigests": [],
                        "Config": {"Entrypoint": ["/openworker/image/entrypoint.sh"]},
                    }
                ]
            )
        if command[:3] == ["docker", "network", "inspect"]:
            return "172.31.0.1"
        if command[:2] == ["docker", "port"]:
            return "127.0.0.1:49153"
        return ""

    class Sink:
        def __init__(self) -> None:
            self.port = 48211
            self.request_count = 1
            self.non_generation_requests = 0
            self.rejected_requests = 0
            self.capture_error = None
            self.captured_headers = {
                "Authorization": [f"Bearer {ingress_token}"],
                "X-MiLAi-Host-Instance": [
                    "7880d4bb-a56d-4f7d-8f8f-478281e38ea0"
                ],
                "X-MiLAi-Task-Session": ["ses_private_123"],
                "X-MiLAi-Task-Operation": ["msg_private_456"],
            }
            self.captured_request_inventory = {
                "schema": "milai.dg13u.u1-provider-ingress-request.v1",
                "status": "PASS",
                "model": probe.EXACT_MODEL_ID,
                "top_level_keys": ["messages", "model", "stream", "stream_options"],
                "message_roles": ["user"],
                "raw_content_persisted": False,
                "credentials_persisted": False,
            }

    @contextmanager
    def fake_sink(_gateway: str, _token: str) -> Iterator[Sink]:
        yield Sink()

    monkeypatch.setattr(probe, "_run_command", fake_command)
    monkeypatch.setattr(probe, "_fake_host_sink", fake_sink)
    monkeypatch.setattr(probe, "_wait_ready", lambda _port, _name: None)
    monkeypatch.setattr(
        probe,
        "_exercise_opencode",
        lambda _port: ("ses_private_123", "msg_private_456"),
    )
    monkeypatch.setattr(probe.secrets, "token_urlsafe", lambda _length: ingress_token)

    run_id = "u1-headers-probe-unit-success"
    report = probe.run_probe(run_id)
    run_dir = runs / run_id

    assert report["status"] == "PASS"
    ledger = json.loads((run_dir / "call-ledger.json").read_text())
    assert ledger["fake_host_requests"] == 1
    assert ledger["real_provider_calls"] == 0
    assert ledger["mcp_calls"] == 0
    assert ledger["vllm_calls"] == 0
    manifest_text = (run_dir / "manifest.json").read_text()
    capture_text = (run_dir / "ingress-capture.json").read_text()
    assert ingress_token not in manifest_text
    assert ingress_token not in capture_text
    assert "ses_private_123" not in capture_text
    cleanup = json.loads((run_dir / "cleanup-receipt.json").read_text())
    assert cleanup["status"] == "PASS"
    assert cleanup["container"]["removed"] is True
    assert cleanup["network"]["removed"] is True
    assert cleanup["temporary_directory"]["removed"] is True
    assert cleanup["label_reconciliation"] == {
        "container_count": 0,
        "network_count": 0,
    }
    assert not (temporary / run_id).exists()
    docker_run = next(command for command in commands if command[:2] == ["docker", "run"])
    assert probe.IMAGE in docker_run
    assert "--network" in docker_run
    assert any(value.startswith("OPENWORKER_URL=http://172.31.0.1:") for value in docker_run)
    assert all("7860" not in value for command in commands for value in command)
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in run_dir.iterdir()
        if path.is_file()
    )


def test_probe_failure_after_container_start_still_reconciles_only_owned_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    commands: list[list[str]] = []

    def fake_command(command: list[str], *, timeout: int = 60) -> str:
        del timeout
        commands.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"Id": "sha256:u1-exact-image", "RepoDigests": []}])
        if command[:3] == ["docker", "network", "inspect"]:
            return "172.31.0.1"
        if command[:2] == ["docker", "port"]:
            return "127.0.0.1:49153"
        return ""

    class Sink:
        def __init__(self) -> None:
            self.port = 48211
            self.request_count = 0
            self.non_generation_requests = 0
            self.rejected_requests = 0
            self.capture_error = None
            self.captured_headers: dict[str, list[str]] = {}
            self.captured_request_inventory: dict[str, object] = {}

    @contextmanager
    def fake_sink(_gateway: str, _token: str) -> Iterator[Sink]:
        yield Sink()

    monkeypatch.setattr(probe, "_run_command", fake_command)
    monkeypatch.setattr(probe, "_fake_host_sink", fake_sink)
    monkeypatch.setattr(probe, "_wait_ready", lambda _port, _name: None)
    monkeypatch.setattr(
        probe,
        "_exercise_opencode",
        lambda _port: (_ for _ in ()).throw(probe.ProbeError("synthetic failure")),
    )

    run_id = "u1-headers-probe-unit-failure"
    report = probe.run_probe(run_id)
    cleanup = json.loads((runs / run_id / "cleanup-receipt.json").read_text())

    assert report["status"] == "FAIL"
    assert cleanup["status"] == "PASS"
    assert cleanup["container"]["removed"] is True
    assert cleanup["network"]["removed"] is True
    assert not (temporary / run_id).exists()
    assert any(command[:3] == ["docker", "rm", "-f"] for command in commands)
    assert any(command[:3] == ["docker", "network", "rm"] for command in commands)
