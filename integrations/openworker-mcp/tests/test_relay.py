from __future__ import annotations

import socket
from pathlib import PurePosixPath

import pytest

from milai_openworker_mcp import relay


def test_relay_rejects_out_of_root_profile_and_wide_socket(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relay, "_SOCKET_ROOT", PurePosixPath(str(tmp_path)))
    tmp_path.chmod(0o755)
    with pytest.raises(relay.RelayError, match="SOCKET_PATH_REJECTED"):
        relay._validate_path(str(tmp_path.parent / "reader-lite.sock"))
    with pytest.raises(relay.RelayError, match="SOCKET_PROFILE_REJECTED"):
        relay._validate_path(str(tmp_path / "unknown.sock"))

    path = tmp_path / "reader-lite.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    path.chmod(0o666)
    try:
        with pytest.raises(relay.RelayError, match="SOCKET_MODE_REJECTED"):
            relay._socket_identity(str(path))
    finally:
        listener.close()


def test_relay_main_emits_bounded_diagnostic_without_socket(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["milai-mcp-relay"])
    assert relay.main() == 64
    diagnostic = capsys.readouterr().err
    assert '"reason":"ARGUMENTS_REJECTED"' in diagnostic
    assert "MILAI_" not in diagnostic
