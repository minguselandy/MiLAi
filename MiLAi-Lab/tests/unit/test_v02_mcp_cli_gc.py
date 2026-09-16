from __future__ import annotations

import gc
import importlib
import json
import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
wrapper = importlib.import_module("observe_v02_mcp_cli_gc")


@pytest.mark.parametrize("finish", ["exit", "sigterm"])
def test_cli_argv_gc_policy_and_termination_are_preserved_with_observation(tmp_path, finish):
    entrypoint = tmp_path / "console"
    entrypoint.write_text(
        "import gc, sys, signal\n"
        "assert sys.argv[1:] == ['--profile', 'fixture']\n"
        "gc.collect()\n"
        + ("raise SystemExit(7)\n" if finish == "exit" else "signal.raise_signal(signal.SIGTERM)\n")
    )
    argv = sys.argv
    previous_handler, callbacks = signal.getsignal(signal.SIGTERM), list(gc.callbacks)
    policy = (gc.isenabled(), gc.get_threshold())
    with pytest.raises(SystemExit) as caught:
        wrapper.run(entrypoint, ["--profile", "fixture"], tmp_path)
    assert caught.value.code == (7 if finish == "exit" else 143)
    assert sys.argv is argv and signal.getsignal(signal.SIGTERM) == previous_handler
    assert gc.callbacks == callbacks and (gc.isenabled(), gc.get_threshold()) == policy
    observation = json.loads((tmp_path / "mcp-gc.json").read_text())
    assert observation["scope"] == "MCP_SERVER_STANDARD_GC_AROUND_PUBLISHED_CLI"
    assert observation["events"] and observation["dropped_events"] == 0
