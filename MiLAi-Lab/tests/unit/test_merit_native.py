"""Finite synthetic domains and public metered completion contract, no benchmark gold."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from milai_lab.datasets.merit import load_frozen_arc, load_native_domain_arc
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, write_json
from milai_lab.providers import merit_metered
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


def receipt(message: dict[str, Any], finish: str = "stop") -> dict[str, Any]:
    return {"id": "actual-synthetic-id", "object": "chat.completion", "created": 1,
            "model": "synthetic-native", "choices": [{"index": 0, "message": message,
                                                       "finish_reason": finish}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}}


def test_metered_sdk_public_bridge_one_attempt_actual_receipt_and_finally_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = SimpleNamespace(completion=object(), register_model=object(), num_retries=2,
                          drop_params=False, request_timeout=7)
    before = vars(sdk).copy()
    monkeypatch.setattr(merit_metered.importlib, "import_module", lambda name: sdk)
    wires = []

    def send(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        return httpx.Response(200, json=receipt({"role": "assistant", "content": "Final"}))

    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="synthetic-native",
        tool_mode="native", max_tokens=4096, enable_thinking=False), budget=budget,
        transport=httpx.MockTransport(send)) as client:
        with pytest.raises(ValueError, match="synthetic outer failure"):
            with merit_metered.metered_litellm(client):
                sdk.num_retries = 5  # Upstream assignment must not add network attempts.
                sdk.drop_params = True
                result = sdk.completion(model="synthetic-native", temperature=0,
                                        messages=[{"role": "user", "content": "Current"}], tools=[])
                assert result.id == "actual-synthetic-id" and result.usage.total_tokens == 9
                raise ValueError("synthetic outer failure")
        assert vars(sdk) == before
    assert len(wires) == 1 and budget.state["generation_requests"] == 1
    assert budget.state["generation"]["known_tokens"] == 9


@pytest.mark.parametrize("mode", ["truncated", "invalid_arguments", "http_error"])
def test_native_metered_failure_is_not_success_and_never_retried(tmp_path: Path, mode: str) -> None:
    attempts = []
    message = {"role": "assistant", "content": None, "tool_calls": [{"type": "function",
        "id": "original-id", "function": {"name": "read", "arguments": "[]"}}]}

    def send(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(503 if mode == "http_error" else 200, json=receipt(message,
            "length" if mode == "truncated" else "tool_calls"))

    budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="synthetic-native",
        tool_mode="native", max_tokens=4096), budget=budget,
        transport=httpx.MockTransport(send)) as client:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            merit_metered.completion(client, model="synthetic-native", temperature=0,
                                      messages=[{"role": "user", "content": "Current"}])
    assert len(attempts) == budget.state["generation_requests"] == 1
    assert budget.state["generation"]["unknown_usage"] == (1 if mode == "http_error" else 0)


def _selection(tmp_path: Path, domain: str, *, historical: bool = False) -> Path:
    root = tmp_path / "source"
    package = root / "merit"
    package.mkdir(parents=True)
    modules = {
        "__init__.py": "",
        "arcs.py": (
            "from dataclasses import dataclass\nimport sqlite3\n"
            "class World:\n"
            "    def __init__(self): self.conn=sqlite3.connect(':memory:')\n"
            "    def dump_json(self): return '{}'\n"
            "@dataclass\nclass Task:\n"
            "    dependent: bool=False\n    user_messages: tuple=('Synthetic current request',)\n"
            "@dataclass\nclass Episode:\n    task: Task\n"
            "@dataclass\nclass Arc:\n    arc_id: str\n    episodes: tuple\n"
            "    def make_world(self): return World()\n"
            "def generate_suite(**kw): return [Arc('synthetic-d1', tuple(Episode(Task()) "
            "for _ in range(5)))]\n"
        ),
        "tools.py": "TOOL_SCHEMAS=[]\nTOOL_FUNCS={}\n",
        "metrics.py": "",
        "runner.py": "SYSTEM_PROMPT='Official {memory_block}'\nMAX_TURNS=12\n"
                     "def run_episode(*a,**kw): raise RuntimeError('not used by loader')\n",
        "memory.py": "",
        "domains.py": "from types import SimpleNamespace\nfrom .arcs import generate_suite\n"
                      "DOMAINS={k:SimpleNamespace(generate_suite=generate_suite,tool_funcs={},"
                      "tool_schemas=[],system_prompt='Domain '+k+' {memory_block}') "
                      "for k in ('d1','d2','d3')}\n",
    }
    for name, content in modules.items():
        (package / name).write_text(content)
    arc = {"arc_id": "synthetic-d1", "episodes": [
        {"task": {"dependent": False, "user_messages": ["Synthetic current request"]}}
        for _ in range(5)]}
    arc_path, world_path = tmp_path / "arc.json", tmp_path / "world.json"
    arc_path.write_text(json.dumps(arc, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    world_path.write_text("{}")
    selection = tmp_path / "selection.json"
    write_json(selection, {"dataset": "MERIT", "domain": domain,
        "source_commit": "293933d96b1d1849e1f20d1bb324def5de9ed33f",
        "generator": "merit.arcs.generate_suite" if historical else
            "merit.domains.DOMAINS.generate_suite",
        "generator_arguments": {"n_arcs": 1, "episodes_per_arc": 5, "dep_ratio": 0.5,
                                "base_seed": 0, "difficulty": "hard"},
        "external_root": str(root), "source_sha256": {
            "merit/" + name: hashlib.sha256(content.encode()).hexdigest()
            for name, content in modules.items()}, "arc_id": "synthetic-d1",
        "episode_count": 5, "dependent_episode_count": 0, "user_message_count": 5,
        "private_artifacts": {"arc": str(arc_path), "arc_sha256": hashlib.sha256(
            arc_path.read_bytes()).hexdigest(), "initial_world": str(world_path),
            "initial_world_sha256": hashlib.sha256(world_path.read_bytes()).hexdigest()}})
    return selection


@pytest.mark.parametrize("domain", ["d1", "d2", "d3"])
def test_opt_in_official_domain_contract_keeps_arc_world_hash_and_complete_sequence(
    tmp_path: Path, domain: str,
) -> None:
    selection = _selection(tmp_path, domain)
    identity, arc, tools, _, runner = load_native_domain_arc(selection)
    assert identity["domain"] == domain and len(arc.episodes) == 5
    assert tools.TOOL_SCHEMAS == [] and runner.SYSTEM_PROMPT == f"Domain {domain} {{memory_block}}"
    data = json.loads(selection.read_text())
    data["private_artifacts"]["arc_sha256"] = "0" * 64
    write_json(selection, data)
    with pytest.raises(ValueError, match="ARC_IDENTITY_MISMATCH"):
        load_native_domain_arc(selection)


def test_historical_d1_generator_identity_unchanged(tmp_path: Path) -> None:
    selection = _selection(tmp_path, "d1", historical=True)
    _, arc, tools, _, runner = load_frozen_arc(selection)
    assert len(arc.episodes) == 5 and tools.TOOL_FUNCS == {}
    assert runner.SYSTEM_PROMPT == "Official {memory_block}"
