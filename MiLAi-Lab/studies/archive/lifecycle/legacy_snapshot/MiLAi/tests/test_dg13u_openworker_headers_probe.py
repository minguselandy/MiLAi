from __future__ import annotations

import json
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import probe_dg13u_openworker_headers as probe


def _configure_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    runs = root / "var/dg13/runs"
    temporary = root / "var/dg13/tmp"
    contract = root / "contracts/agent/v1/openworker-task-metadata-headers.md"
    contract.parent.mkdir(parents=True)
    contract.write_text("candidate contract\n", encoding="utf-8")
    probe_source = root / "scripts/probe_dg13u_openworker_headers.py"
    probe_source.parent.mkdir(parents=True)
    probe_source.write_text("# synthetic probe source\n", encoding="utf-8")
    monkeypatch.setattr(probe, "ROOT", root)
    monkeypatch.setattr(probe, "RUNS_ROOT", runs)
    monkeypatch.setattr(probe, "TMP_ROOT", temporary)
    monkeypatch.setattr(probe, "CONTRACT", contract)
    monkeypatch.setattr(probe, "PROBE_SOURCE", probe_source)
    monkeypatch.setattr(probe, "_is_cra_path", lambda _path: True)
    return runs, temporary


def test_plugin_emits_only_candidate_headers_from_native_chat_identity() -> None:
    source = probe._render_plugin()
    assert '"chat.headers"' in source
    assert "crypto.randomUUID()" in source
    assert 'output.headers["X-MiLAi-Host-Instance"] = hostInstance' in source
    assert 'output.headers["X-MiLAi-Task-Session"] = input.sessionID' in source
    assert 'output.headers["X-MiLAi-Task-Operation"] = input.message.id' in source
    assert "prompt" not in source.lower()


def test_header_evidence_persists_hashes_without_raw_values() -> None:
    raw = {
        "X-MiLAi-Host-Instance": "7880d4bb-a56d-4f7d-8f8f-478281e38ea0",
        "X-MiLAi-Task-Session": "ses_private_123",
        "X-MiLAi-Task-Operation": "msg_private_456",
    }
    evidence = probe._redacted_header_evidence(
        raw,
        session_id="ses_private_123",
        message_id="msg_private_456",
    )
    encoded = json.dumps(evidence, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["header_names"] == list(probe.HEADER_NAMES)
    assert all(len(value) == 64 for value in evidence["value_sha256"].values())
    assert "ses_private_123" not in encoded
    assert "msg_private_456" not in encoded
    assert "7880d4bb-a56d-4f7d-8f8f-478281e38ea0" not in encoded


def test_request_inventory_keeps_structure_and_discards_content() -> None:
    raw = json.dumps(
        {
            "model": "AUTO",
            "messages": [
                {"role": "system", "content": "private system"},
                {"role": "user", "content": "private prompt"},
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()
    inventory = probe._request_inventory(raw)
    encoded = json.dumps(inventory, sort_keys=True)

    assert inventory["top_level_keys"] == [
        "messages",
        "model",
        "stream",
        "stream_options",
    ]
    assert inventory["message_roles"] == ["system", "user"]
    assert inventory["stream_option_keys"] == ["include_usage"]
    assert "private system" not in encoded
    assert "private prompt" not in encoded


def test_live_probe_writes_zero_real_call_ledger_and_closes_owned_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    commands: list[list[str]] = []

    def fake_command(command: list[str], *, timeout: int = 60) -> str:
        del timeout
        commands.append(command)
        if command[:3] == ["docker", "network", "inspect"]:
            return "172.31.0.1"
        if command[:2] == ["docker", "port"]:
            return "127.0.0.1:49153"
        if command[:3] == ["docker", "image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": "sha256:exact-image",
                        "RepoDigests": [],
                        "Config": {"Entrypoint": ["/openworker/image/entrypoint.sh"]},
                    }
                ]
            )
        return ""

    class Sink:
        def __init__(self) -> None:
            self.port = 48211
            self.request_count = 1
            self.non_generation_requests = 0
            self.captured_headers = {
                "X-MiLAi-Host-Instance": "7880d4bb-a56d-4f7d-8f8f-478281e38ea0",
                "X-MiLAi-Task-Session": "ses_private_123",
                "X-MiLAi-Task-Operation": "msg_private_456",
            }
            self.captured_request_inventory = {
                "schema": "milai.dg13u.openworker-request-inventory.v1",
                "status": "PASS",
                "top_level_keys": ["messages", "model", "stream"],
                "message_roles": ["user"],
                "raw_content_persisted": False,
                "credentials_persisted": False,
            }

    @contextmanager
    def fake_sink(_gateway: str) -> Iterator[Sink]:
        yield Sink()

    monkeypatch.setattr(probe, "_run_command", fake_command)
    monkeypatch.setattr(probe, "_fake_provider_sink", fake_sink)
    monkeypatch.setattr(probe, "_wait_ready", lambda _port, _name: None)
    monkeypatch.setattr(
        probe,
        "_exercise_opencode",
        lambda _port: ("ses_private_123", "msg_private_456"),
    )

    run_id = "headers-probe-unit-success"
    report = probe.run_probe(run_id)
    run_dir = runs / run_id

    assert report["status"] == "PASS"
    ledger = json.loads((run_dir / "call-ledger.json").read_text())
    assert ledger == {
        "schema": "milai.dg13u.headers-probe-calls.v1",
        "fake_provider_requests": 1,
        "real_provider_calls": 0,
        "mcp_calls": 0,
        "vllm_calls": 0,
        "automatic_retries": 0,
    }
    capture = (run_dir / "header-capture.json").read_text()
    assert "ses_private_123" not in capture
    assert "msg_private_456" not in capture
    inventory = (run_dir / "request-inventory.json").read_text()
    assert "private" not in inventory
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
    assert ["docker", "rm", "-f", cleanup["container"]["name"]] in commands
    assert ["docker", "network", "rm", cleanup["network"]["name"]] in commands
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in run_dir.iterdir()
        if path.is_file()
    )


def test_capture_failure_still_removes_container_network_and_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs, temporary = _configure_roots(tmp_path, monkeypatch)
    commands: list[list[str]] = []

    def fake_command(command: list[str], *, timeout: int = 60) -> str:
        del timeout
        commands.append(command)
        if command[:3] == ["docker", "network", "inspect"]:
            return "172.31.0.1"
        if command[:2] == ["docker", "port"]:
            return "127.0.0.1:49153"
        if command[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"Id": "sha256:exact-image", "RepoDigests": []}])
        return ""

    class Sink:
        def __init__(self) -> None:
            self.port = 48211
            self.request_count = 0
            self.non_generation_requests = 0
            self.captured_headers: dict[str, str] = {}
            self.captured_request_inventory: dict[str, object] = {}

    @contextmanager
    def fake_sink(_gateway: str) -> Iterator[Sink]:
        yield Sink()

    monkeypatch.setattr(probe, "_run_command", fake_command)
    monkeypatch.setattr(probe, "_fake_provider_sink", fake_sink)
    monkeypatch.setattr(probe, "_wait_ready", lambda _port, _name: None)

    def fail(_port: int) -> tuple[str, str]:
        raise probe.ProbeError("synthetic capture failure")

    monkeypatch.setattr(probe, "_exercise_opencode", fail)
    run_id = "headers-probe-unit-failure"
    report = probe.run_probe(run_id)
    cleanup = json.loads((runs / run_id / "cleanup-receipt.json").read_text())

    assert report["status"] == "FAIL"
    assert cleanup["status"] == "PASS"
    assert cleanup["container"]["removed"] is True
    assert cleanup["network"]["removed"] is True
    assert not (temporary / run_id).exists()
    assert any(command[:3] == ["docker", "rm", "-f"] for command in commands)
    assert any(command[:3] == ["docker", "network", "rm"] for command in commands)
