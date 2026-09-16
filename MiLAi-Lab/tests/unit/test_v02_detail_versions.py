from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
check = importlib.import_module("check_v02_detail_versions")


@pytest.mark.parametrize("occupied", ["container", "volume"])
@pytest.mark.parametrize("module", ["check_v02_detail_versions", "check_v02_tool_disclosure_live"])
def test_existing_namespace_rejected_before_prepare_or_cleanup(
    tmp_path, monkeypatch, occupied, module,
):
    check = importlib.import_module(module)
    calls = []
    monkeypatch.setattr(check.base, "read_json", lambda _: {"model_transport_enabled": False})

    def command(args):
        calls.append(args)
        kind = "volume" if args[1] == "volume" else "container"
        return SimpleNamespace(stdout="existing-owned-elsewhere" if kind == occupied else "")

    def forbidden(*args, **kwargs):
        raise AssertionError("Occupied namespace must not reach preparation or cleanup")

    monkeypatch.setattr(check.base, "_command", command)
    monkeypatch.setattr(check.base, "prepare", forbidden)
    monkeypatch.setattr(check.base, "pin", forbidden)
    monkeypatch.setattr(check, "stop_owned", forbidden)
    root = tmp_path / "specific-run"
    with pytest.raises(RuntimeError, match="SERVICE_NAMESPACE_ALREADY_EXISTS"):
        check.run(root)
    assert not root.exists()
    assert len(calls) == (1 if occupied == "container" else 2)
    assert all(args[-1] == "label=com.docker.compose.project=specific-run-product-pg"
               for args in calls)
