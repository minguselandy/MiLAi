import json
import sys
from pathlib import Path

import pytest

from milai_lab.methods.observational_capacity import (
    CapacityObservationalMemoryHost,
    CapacityOMConfig,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from reasoningbank_om import NativeCapacityOMSession


def host(*, output=None, **config):
    calls, events = [], []

    def generate(call):
        calls.append(call)
        return json.dumps(
            {"observations": output or "Preserved fact: user 104.", "continuationHints": {}}
        )

    value = CapacityObservationalMemoryHost(
        goal="Authorized task",
        actor_policy="Actor",
        summary_policy="Observer",
        reflector_policy="Reflector",
        generate=generate,
        validate_action=lambda a: None,
        dispatch=lambda a: "",
        source_entries=lambda: [],
        read_source=lambda *a: {},
        count_text=len,
        count_messages=lambda m: len(json.dumps(m)),
        config=CapacityOMConfig(
            context_tokens=1800,
            actor_output_tokens=100,
            observer_output_tokens=100,
            reflector_output_tokens=100,
            measurement_margin_tokens=32,
            observation_tokens=1,
            reflection_tokens=1,
            recent_events=1,
            **config,
        ),
        emit=events.append,
    )
    return value, calls, events


def test_observer_subdivides_large_seen_page_preserving_exact_source_and_unseen_tail():
    h, calls, _ = host()
    original = "original exact data " * 180
    h.observe(original)
    h.actor_seen_pages.update(h.raw_tail)
    h.observe("recent unseen feedback")
    unseen = set(h.raw_tail) - h.actor_seen_pages
    assert h.observe_batch()
    assert len(calls) == 1 and h._fits(calls[0].messages, "observer")
    supplied = json.loads(calls[0].messages[-1]["content"])["raw_pages"]
    assert set(h.covered_ranges) == {p["id"] for p in supplied}
    # A second batch reaches the oversized page; splitting must not lose bytes.
    assert h.observe_batch()
    assert len([p for p in h.pages if p["event"] == 1]) > 1
    pages = sorted((p for p in h.pages if p["event"] == 1), key=lambda p: p["source"]["start"])
    assert "".join(p["text"] for p in pages) == original
    for page in pages:
        source = page["source"]
        assert original[source["start"] : source["start"] + source["length"]] == page["text"]
    assert not unseen.intersection(h.covered_ranges)
    assert set(h.raw_tail).isdisjoint(h.covered_ranges)
    assert set(h.raw_tail) | set(h.covered_ranges) == set(range(len(h.pages)))
    restored, _, _ = host()
    restored.restore(h.checkpoint())
    assert restored.checkpoint() == h.checkpoint()


def test_partial_reflection_replaces_only_supplied_prefix_and_preserves_originals():
    h, calls, _ = host()
    for i in range(3):
        h.observe(f"original evidence {i}")
    h.observation_groups = [
        {
            "text": f"Group {i}: " + "evidence " * 90,
            "pages": [i],
            "source_ranges": [h.pages[i]["source"]],
            "mapping": "coarse_batch_union",
        }
        for i in range(3)
    ]
    old = list(h.observation_groups)
    assert h.reflect_batch(force=True)
    supplied = json.loads(calls[-1].messages[-1]["content"])["observations"]
    assert 0 < len(supplied) < len(old)
    assert h.observation_groups[1:] == old[len(supplied) :]
    assert h.observation_groups[0]["pages"] == list(range(len(supplied)))
    assert h.events[1]["text"] == "original evidence 0"
    assert h._fits(calls[-1].messages, "reflector")


def test_nonshrinking_reflection_is_not_committed_or_retried_after_restore():
    h, calls, events = host(output="longer " * 200)
    h.observation_groups = [
        {"text": "Small useful fact", "pages": [0], "source_ranges": [h.pages[0]["source"]]}
    ]
    original = list(h.observation_groups)
    assert not h.reflect_batch(force=True)
    assert h.observation_groups == original
    assert not h.reflect_batch(force=True) and len(calls) == 1
    restored, new_calls, _ = host()
    restored.restore(h.checkpoint())
    assert not restored.reflect_batch(force=True) and not new_calls
    assert any(e["event"] == "OM_REFLECTION_NO_PROGRESS" for e in events)


def test_observer_retry_identity_is_actual_input_and_survives_restore():
    h, _, _ = host()
    attempts = []

    def reject(call):
        attempts.append(call)
        return "{}"

    h.generate = reject
    h.actor_seen_pages.update(h.raw_tail)
    h.observe("new current event")
    assert not h.observe_batch()
    assert not h.observe_batch() and len(attempts) == 1
    assert not h.covered_ranges
    restored, _, _ = host()
    restored.restore(h.checkpoint())
    restored.generate = reject
    assert not restored.observe_batch() and len(attempts) == 1
    # Same raw IDs, but genuinely different accepted prior evidence makes this
    # a different request. Merely assembling the same request above did not.
    restored.observation_groups.append({"text": "New fact", "pages": [], "source_ranges": []})
    assert not restored.observe_batch() and len(attempts) == 2
    assert not restored.observe_batch() and len(attempts) == 2
    assert attempts[0].messages != attempts[1].messages


class Provider:
    context = 65536

    def __init__(self):
        self.calls = []

    def count_text(self, text):
        return len(text)

    def count_messages(self, messages, tools=None):
        return len(json.dumps({"messages": list(messages), "tools": tools}))

    def memory_call(self, task, call):
        self.calls.append(call)
        return '{"observations":"Useful fact: user 104.","continuationHints":{}}'


def session(*, provider=None, state=None, **config):
    return NativeCapacityOMSession(
        state={} if state is None else state,
        scope={
            "experiment": "unit",
            "method": "OM_SYNC_PORT",
            "model": "test",
            "domain": "travel",
            "method_version": NativeCapacityOMSession.method_version,
        },
        provider=provider or Provider(),
        task_id="task",
        policy_root=Path(__file__).resolve().parents[2] / "configs/policies/om_sync",
        emit=lambda e: None,
        compact_provenance=True,
        config={"context_tokens": 10000, "measurement_margin_tokens": 128, **config},
    )


def test_large_omission_catalog_is_bounded_and_original_pages_remain_readable():
    s = session(observation_tokens=999999)
    s.start("task", "Current task")
    for i in range(100):
        s.observe("tool", f"source {i}: " + "x" * 300)
    s.current_boundary = len(s.host.events)
    s.native_messages = [{"role": "system", "content": "native facts"}]
    s.native_tools = [{"name": "real_tool", "description": "schema" * 50}]
    text = s.memory_context()
    body = json.loads(text.split("\n\n", 1)[1])
    catalog = body["omitted_pages"]
    assert len(catalog) == 1 and len(json.dumps(catalog)) < 250
    assert catalog[0]["page_count"] > 80
    ref = catalog[0]["source_ref"]
    first = s.read(ref, length=100)
    assert first["has_more"]
    chunks = [
        s.read(ref, start=i, length=16000)["text"] for i in range(0, first["total_chars"], 16000)
    ]
    rows = json.loads("".join(chunks))
    original = rows[2]["source"]
    assert s.read(original["ref"], length=16000)["text"].startswith("tool:")
    s.mark_seen()
    assert not {r["page_id"] for r in rows} & s.host.actor_seen_pages
    messages = [{"role": "system", "content": "native facts\n\n" + text}]
    s.check_actor_request(messages, s.native_tools)
    assert not s.provider.calls
    s.finish("trajectory", commit=True)
    fresh = session(state=s.checkpoint(), observation_tokens=999999)
    fresh.start("next", "Next task")
    assert fresh.read(ref, length=100) == first


def test_required_native_overflow_fails_before_generation_and_schema_is_counted():
    s = session()
    s.start("task", "Current task")
    s.native_messages = [{"role": "user", "content": "required fact" * 1000}]
    with pytest.raises(ValueError, match="REQUIRED_NATIVE"):
        s.memory_context()
    s.native_messages = [{"role": "user", "content": "small"}]
    s.native_tools = [{"schema": "x" * 10000}]
    with pytest.raises(ValueError, match="REQUIRED_NATIVE"):
        s.memory_context()
    assert not s.provider.calls


def test_maintenance_call_cap_and_accepted_coverage_are_jointly_bounded():
    s = session(observation_tokens=1, reflection_tokens=999999, maintenance_max_calls=2)
    s.start("task", "Current task")
    for i in range(10):
        s.observe("tool", f"page{i}: " + "x" * 3000)
    s.host.actor_seen_pages.update(s.host.raw_tail)
    s._maintenance()
    assert len(s.provider.calls) == 2
    supplied = {
        p["id"]
        for c in s.provider.calls
        if c.role == "observer"
        for p in json.loads(c.messages[-1]["content"])["raw_pages"]
    }
    assert supplied == set(s.host.covered_ranges)
    assert s.host.raw_tail
