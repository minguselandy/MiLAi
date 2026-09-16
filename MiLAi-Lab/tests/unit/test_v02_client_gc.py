from __future__ import annotations

import gc
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
probe = importlib.import_module("v02_client_gc")


def test_probe_restores_callback_and_preserves_exception_and_gc_policy(tmp_path):
    callbacks, thresholds, enabled = list(gc.callbacks), gc.get_threshold(), gc.isenabled()
    with pytest.raises(KeyboardInterrupt):
        with probe.observe(tmp_path, enabled=True):
            gc.collect()
            raise KeyboardInterrupt()
    assert gc.callbacks == callbacks
    assert gc.get_threshold() == thresholds and gc.isenabled() == enabled
    observed = json.loads((tmp_path / "client-gc.json").read_text())
    intervals = probe.spans(observed)
    assert intervals and any(generation == 2 for _, _, generation in intervals)
    assert observed["initial_policy"] == observed["final_policy"]


def test_disabled_probe_does_not_install_callback_or_create_observation(tmp_path):
    callbacks = list(gc.callbacks)
    with probe.observe(tmp_path, enabled=False):
        assert gc.callbacks == callbacks
    assert not (tmp_path / "client-gc.json").exists()


@pytest.mark.parametrize("mode", ["overflow", "unclosed", "reversed", "generation", "duplicate"])
def test_incomplete_gc_capture_stays_unknown(mode):
    events = [["start", 1.0, 2], ["stop", 1.1, 2]]
    observation = {"events": events, "dropped_events": 1 if mode == "overflow" else 0}
    if mode == "unclosed":
        events.pop()
    elif mode == "reversed":
        events[1][1] = 0.9
    elif mode == "generation":
        events[1][2] = 0
    elif mode == "duplicate":
        events.append(events[-1])
    assert probe.spans(observation) is None


def test_overlap_is_clipped_to_call_and_excludes_outside_intervals():
    observed = {"dropped_events": 0, "events": [
        ["start", 1, 0], ["stop", 2, 0],
        ["start", 3, 2], ["stop", 4, 2],
        ["start", 5, 0], ["stop", 6, 0],
    ]}
    assert probe.overlap_ms(1.5, 3.5, probe.spans(observed)) == 1000
