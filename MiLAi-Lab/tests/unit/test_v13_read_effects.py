"""A material increase can have a lower continuation cost; missing rewards stay masked."""

import importlib
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    return importlib.import_module("report_memory_control_v13_read_effects")


def test_expensive_subset_uses_total_cost_and_observed_native_quality(monkeypatch):
    m = module(monkeypatch)
    base = dict(
        source="src",
        native_group="g",
        first_packet_differs=True,
        first_ranges_differ=True,
        terminal_wire_differs=False,
        independent_terminal_responses=False,
        immediate_tokens_delta=100,
    )
    measured = [
        dict(base, quality_delta=q, future_cost_delta=f, total_cost_delta=c)
        for q, f, c in ((0.0, -100, 0.0), (-0.1, -30, 70.0), (None, 10, 110.0), (0.2, None, None))
    ]
    summary = m.summarize_levels(measured, {"src": Counter(roots=4), "no_pairs": Counter(roots=2)})
    assert summary["src"]["expensive_without_quality_gain_all"] == m.rate(1, 2)
    assert summary["src"]["no_quality_gain_given_higher_total_cost"] == m.rate(1, 1)
    assert summary["src"]["missing_quality"] == summary["src"]["missing_future_cost"] == 1
    assert summary["no_pairs"]["first_packet_difference"]["rate"] is None


def test_partial_or_unavailable_interval_does_not_complete_bridge(monkeypatch):
    m = module(monkeypatch)
    obj = SimpleNamespace(id=5, body="abcdef")
    pool = SimpleNamespace(by_ref={"s": obj}, objects={5: obj})

    def span(a, b):
        return dict(source_ref="s", source_revision=1, start=a, end=b)

    item = dict(
        visibility="visible",
        body_delivered=True,
        source_ranges=[span(0, 6)],
        unavailable_source_ranges=[span(2, 4)],
    )
    env = SimpleNamespace(pool=pool, ops=SimpleNamespace(opened={0: item}))
    assert m.ranges(env) == [(5, 0, 2), (5, 4, 6)]
    assert not m.full_objects(m.ranges(env), pool, {5})
    env.ops.opened[1] = {**item, "source_ranges": [span(2, 4)], "unavailable_source_ranges": []}
    assert m.full_objects(m.ranges(env), pool, {5}) == {5}
