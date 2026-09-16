from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import httpx
import pytest

from milai_lab.methods.state_control import MODEL, Case, ControlStop, Material

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
runner = importlib.import_module("run_v0210_negative_controls")


@pytest.mark.parametrize("unknown", [False, True])
def test_b2_preflights_all_inputs_and_stops_on_unknown_usage(tmp_path, monkeypatch, unknown):
    source = Case("scope", "task", (), (), (Material("full", "v1", "scope", "Complete source"),))
    monkeypatch.setattr(runner, "load_case", lambda _: source)
    paths, bodies = [], []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        assert paths.count("/tokenize") == 4
        assert request.url.path == "/v1/chat/completions"
        bodies.append(json.loads(request.content))
        body = {"choices": [{"finish_reason": "stop", "message": {"content": "visible reply"}}]}
        if not unknown:
            body["usage"] = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        return httpx.Response(200, json=body)

    root = tmp_path / "b2"
    if unknown:
        with pytest.raises(ControlStop, match="USAGE_UNKNOWN"):
            runner.run(root, authorization="MOCK_ONLY", transport=httpx.MockTransport(handle))
        report = json.loads((root / "result.json").read_text())
        assert len(bodies) == 1 and len(report["accounting"]["pending"]) == 1
    else:
        report = runner.run(root, authorization="MOCK_ONLY", transport=httpx.MockTransport(handle))
        assert report["accounting"]["raw_tokens"] == 440
        assert not report["accounting"]["pending"]
        assert len(bodies) == 4
        for a, b in ((bodies[0], bodies[1]), (bodies[2], bodies[3])):
            assert a["messages"][:2] == b["messages"][:2]
            assert a["messages"][2] != b["messages"][2]
            assert a["max_tokens"] == b["max_tokens"] == 1024
