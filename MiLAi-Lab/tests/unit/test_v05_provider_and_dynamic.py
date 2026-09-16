from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

from milai_lab.methods.state_control import MODEL, ControlStop

LAB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(LAB / "tools"))
provider_module = importlib.import_module("v0210_v05_provider")
dynamic = importlib.import_module("run_v0210_v05_dynamic")


@pytest.mark.parametrize("known_usage", [True, False])
def test_provider_exact_reservations_survive_caller_reopen(tmp_path, known_usage):
    calls = []

    def handle(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        calls.append(json.loads(request.content))
        value = {"choices": [{"finish_reason": "stop", "message": {"content": "visible"}}]}
        if known_usage:
            value["usage"] = {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}
        return httpx.Response(200, json=value)

    limits = {"sessions": {"A": 1}, "max_generations": 1, "max_raw_tokens": 1200, "seed": 1}
    with provider_module.Deadline(time.monotonic(), 30) as deadline:
        for attempt in range(2):
            provider = provider_module.V05Provider(
                tmp_path, limits, deadline, transport=httpx.MockTransport(handle))
            try:
                provider.verify()
                if attempt == 0 and known_usage:
                    assert provider.generate("A", [{"role": "user", "content": "material"}])
                else:
                    with pytest.raises(ControlStop):
                        provider.generate("A", [{"role": "user", "content": "material"}])
            finally:
                provider.close()
    assert len(calls) == 1 and calls[0]["max_tokens"] == 1024
    events = provider_module.read_events(tmp_path / "provider-ledger.jsonl")
    state = provider_module.accounting(events)
    assert bool(state["pending"]) is not known_usage


def test_dynamic_initial_sources_match_and_policy_does_not_route_source_ids():
    config = json.loads((LAB / "configs/v0210-v05-dynamic.json").read_text())
    a, b = (dynamic.initial_messages(config, arm) for arm in ("A", "B"))
    assert a[:2] == b[:2]
    assert all(s["id"] not in config["exploration_policy"] for s in config["sources"])
    assert all(o["text"] not in json.dumps(a, ensure_ascii=False)
               for o in config["observation_schedule"])
    source = config["sources"][0]
    value = dynamic.read_or_search(config, {"action": "read", "source_id": source["id"]})
    assert value["text"] == source["text"] and value["version"] == source["version"]
    assert value["span_utf8"] == [0, len(source["text"].encode())]


def test_new_observations_preserve_host_notes_and_follow_frozen_turns(tmp_path, monkeypatch):
    config = json.loads((LAB / "configs/v0210-v05-dynamic.json").read_text())
    captured = {"A": [], "B": []}

    class FixedProvider:
        def __init__(self, *args):
            pass

        def verify(self):
            return {"id": MODEL}

        def close(self):
            pass

        def generate(self, arm, messages, *, schema):
            snapshot = json.loads(json.dumps(messages))
            captured[arm].append(snapshot)
            turn = len(captured[arm])
            sources = ["export-records", "publication-records", "receipt-records"]
            return json.dumps({"action": "answer" if turn == 4 else "read",
                               "source_id": "" if turn == 4 else sources[turn - 1],
                               "query": "", "note": f"own note {turn}",
                               "answer": "bounded answer" if turn == 4 else ""})

    monkeypatch.setattr(dynamic, "V05Provider", FixedProvider)
    report = dynamic.run(tmp_path / "batch", authorization="MOCK_ONLY")
    for arm, turns in captured.items():
        assert len(turns) == 4
        for index, messages in enumerate(turns, start=1):
            text = json.dumps(messages, ensure_ascii=False)
            for observation in config["observation_schedule"]:
                assert (observation["text"] in text) == (
                    index >= observation["before_generation"])
            assert sum(m["role"] == "assistant" for m in messages) == index - 1
        assert report["sessions"][arm]["status"] == "ANSWERED"
        assert report["tools_executed"][arm] == 3
